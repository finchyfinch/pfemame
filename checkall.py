#!/usr/bin/env python3

# ----------------------------------------------------------------------------------------------------------------------
# checkall.py

"""
This presents a pop-up window allowing a verification to be carried out
on all existing games in the mylist database.  The results are displayed
for the user to view, filter, copy, save and re-check.

MAME '-verifyroms' is run on chunks of ROM sets, several MAME processes at once, in a worker thread so the window
stays responsive.  Parsing, filtering and formatting the results are plain functions (no wx calls) so they can be
unit tested - see tests/test_checkall.py.
"""

import html
import os
import re
import shelve
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

import wx
import wx.html
import wx.lib.agw.pygauge as gauge

import functions
from rom_database import INDEX_EXISTS, INDEX_ROM_FILE_NAME

_ = functions.set_up_language()  # Set of the application language

# ----------------------------------------------------------------------------------------------------------------------
# ROM set statuses (also the values behind the filter radio buttons)
GOOD = 'good'
BAD = 'bad'
BEST_AVAILABLE = 'best available'
NOT_FOUND = 'not found'
OTHER = 'other'             # A status this MAME version reports that pfeMAME doesn't know about

RECHECK_STATUSES = (BAD, NOT_FOUND)

CHUNK_SIZE = 50             # ROM sets per MAME run
MAX_WORKERS = 8             # Upper limit on parallel MAME runs (more just thrashes the disk)
SEPARATOR = '-' * 72        # Separates the ROM sets in the text version of the results

_ROMSET_LINE = re.compile(r'^romset (\S+) (?:\[(\S+)\] )?is (.+?)\s*$')
_ROMSET_NOT_FOUND_LINE = re.compile(r'^romset "?([^"\s]+)"? not found')
_SUMMARY_LINE = re.compile(r'^\d+ romsets? found, \d+ were OK')
_STATUS_WORDS = {'good': GOOD, 'bad': BAD, 'best available': BEST_AVAILABLE}

_RED_TERMS = ('NOT FOUND', 'INCORRECT CHECKSUM', 'INCORRECT LENGTH', 'EXPECTED', 'FOUND')
_ORANGE_TERMS = ('NO GOOD DUMP KNOWN', 'NEEDS REDUMP')
_STATUS_COLOURS = {BAD: 'red', NOT_FOUND: 'red', BEST_AVAILABLE: 'orange'}


# ----------------------------------------------------------------------------------------------------------------------
# Results model (no wx)
@dataclass
class RomsetResult:
    name: str
    status: str
    parent: str = ''
    details: list = field(default_factory=list)     # MAME's per-file lines for this set
    line: str = ''                                  # MAME's own 'romset ... is ...' line ('' if MAME printed none)

    def status_line(self) -> str:
        if self.line:
            return self.line
        return _('romset {} was not found (it is missing from your ROM folders or unknown to this version of '
                 'MAME)').format(self.name)


def mame_worker_count() -> int:
    """How many MAME processes to run at once - one per CPU core, up to MAX_WORKERS."""
    return max(1, min(os.cpu_count() or 4, MAX_WORKERS))


def chunk_names(names: list, size: int = CHUNK_SIZE) -> list:
    return [names[i:i + size] for i in range(0, len(names), size)]


def parse_verify_output(lines: list, requested: list) -> tuple:
    """
    Turn the (stdout) lines of one MAME '-verifyroms' run into (results, messages): one RomsetResult per ROM set
    plus any lines that weren't about a ROM set.
    MAME prints a set's per-file problem lines before its 'romset NAME [PARENT] is STATUS' line, and prints nothing
    at all for a set none of whose files it can find - those, and sets this MAME doesn't know, are NOT_FOUND.
    MAME's 'N romsets found, M were OK.' line is dropped - pfeMAME shows its own totals.
    """
    results = {}
    pending = []
    for raw in lines:
        line = raw.rstrip()
        if not line.strip() or _SUMMARY_LINE.match(line):
            continue

        match = _ROMSET_LINE.match(line)
        if match:
            name, parent, status = match.groups()
            results[name] = RomsetResult(name, _STATUS_WORDS.get(status, OTHER), parent or '', pending, line)
            pending = []
            continue

        match = _ROMSET_NOT_FOUND_LINE.match(line)
        if match:
            results[match.group(1)] = RomsetResult(match.group(1), NOT_FOUND)
            continue

        pending.append(line)

    for name in requested:
        if name not in results:
            results[name] = RomsetResult(name, NOT_FOUND)

    return list(results.values()), pending  # Lines not followed by a 'romset' line are messages, not set details


def stderr_messages(lines: list) -> list:
    """MAME's error output, less the 'N romsets found, M were OK.' line (some MAME versions print it there)."""
    return [line.strip() for line in lines if line.strip() and not _SUMMARY_LINE.match(line.strip())]


def merge_results(old: list, new: list) -> list:
    """The old results with any set that is also in new replaced by its new result, sorted by name."""
    merged = {result.name: result for result in old}
    merged.update((result.name, result) for result in new)
    return sorted(merged.values(), key=lambda result: result.name)


def count_results(results: list) -> dict:
    counts = {GOOD: 0, BAD: 0, BEST_AVAILABLE: 0, NOT_FOUND: 0, OTHER: 0}
    for result in results:
        counts[result.status] += 1
    return counts


def filter_results(results: list, status: str | None) -> list:
    """The results with the given status (all of them for None)."""
    return [result for result in results if status is None or result.status == status]


def summary_lines(results: list, elapsed: float, stopped: bool) -> list:
    counts = count_results(results)
    lines = [_('ROM sets checked: {total}   Good: {good}   Bad: {bad}   Best available: {best}   '
               'Not found: {not_found}').format(total=len(results), good=counts[GOOD], bad=counts[BAD],
                                                best=counts[BEST_AVAILABLE], not_found=counts[NOT_FOUND]),
             _('The check took {} seconds.').format(f'{elapsed:.1f}')]
    if stopped:
        lines.append(_('The check was stopped before it finished, so not all of your ROMs were checked.'))
    return lines


def detail_colour(line: str) -> str | None:
    """The colour for one of MAME's per-file lines (None = the normal text colour)."""
    if any(term in line for term in _RED_TERMS) and 'NO GOOD DUMP KNOWN' not in line:
        return 'red'
    if any(term in line for term in _ORANGE_TERMS):
        return 'orange'
    return None


def _html_line(text: str, colour: str | None) -> str:
    text = html.escape(text)
    return f'<font color="{colour}">{text}</font><br>' if colour else f'{text}<br>'


def render_html(results: list, header: list, messages: list, text_colour: str, background_colour: str) -> str:
    out = [f'<body bgcolor="{background_colour}"><font color="{text_colour}">']
    out.extend(_html_line(line, None) for line in header)
    if messages:
        out.append('<br>' + _html_line(_('MAME reported:'), None))
        out.extend(_html_line(message, 'red') for message in messages)
    out.append('<hr>')
    if not results:
        out.append(_html_line(_('No ROM sets match this filter.'), None))
    for result in results:
        out.extend(_html_line(line, detail_colour(line)) for line in result.details)
        out.append(_html_line(result.status_line(), _STATUS_COLOURS.get(result.status)))
        out.append('<hr>')
    out.append('</font></body>')
    return ''.join(out)


def render_text(results: list, header: list, messages: list) -> str:
    """Plain text version of the results ('\n' line endings - text mode files and the clipboard convert them)."""
    out = list(header)
    if messages:
        out += ['', _('MAME reported:')] + messages
    out.append(SEPARATOR)
    if not results:
        out.append(_('No ROM sets match this filter.'))
    for result in results:
        out += result.details + [result.status_line(), SEPARATOR]
    return '\n'.join(out) + '\n'


def load_rom_names(my_logger=None) -> list:
    """The names of the ROM sets in the ROM database that are present in the ROM folders, sorted."""
    try:
        with shelve.open(os.path.join(functions.data_dir(), 'mylist.db'), flag='r') as db:
            mylist = db.get('mylist', [])
    except Exception as e:      # A missing or damaged database (shelve raises dbm errors, not just OSError)
        if my_logger:
            my_logger.error(_('ERROR opening mylist.db file: {}').format(e))
        return []
    return sorted({row[INDEX_ROM_FILE_NAME] for row in mylist if row[INDEX_EXISTS] == '1'})


# ----------------------------------------------------------------------------------------------------------------------
# This is the thread class where the main work is done
class CheckAllThread(threading.Thread):
    """
    Runs MAME '-verifyroms' on the ROM sets, several MAME processes at once.  on_progress(done, total) and
    on_finished(results, messages, elapsed, stopped) are always called on the GUI thread.
    stop() cancels the chunks not yet started and ends the MAME processes that are running.  The results of those
    chunks are dropped (they'd otherwise show their unchecked sets as not found).
    """

    def __init__(self, path_executable: str, rom_path: str, names: list, on_progress, on_finished):
        super().__init__(daemon=True)
        self.path_executable = path_executable
        self.rom_path = rom_path
        self.names = names
        self.on_progress = on_progress
        self.on_finished = on_finished

        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._processes = set()

    @property
    def stopped(self) -> bool:
        return self._stop_event.is_set()

    def stop(self):
        self._stop_event.set()
        with self._lock:
            for process in self._processes:
                try:
                    process.kill()
                except OSError:
                    pass

    def run(self):
        start_time = time.monotonic()
        results = []
        messages = []
        done = 0

        executor = ThreadPoolExecutor(max_workers=mame_worker_count())
        try:
            futures = [executor.submit(self.verify_chunk, chunk) for chunk in chunk_names(self.names)]
            for future in as_completed(futures):
                outcome = future.result()
                if outcome is None or self.stopped:
                    continue
                chunk, chunk_results, chunk_messages = outcome
                results.extend(chunk_results)
                messages.extend(chunk_messages)
                done += len(chunk)
                wx.CallAfter(self.on_progress, done, len(self.names))
        finally:
            executor.shutdown(wait=True, cancel_futures=True)

        messages = list(dict.fromkeys(messages))    # Each chunk repeats MAME's warnings - show them once
        wx.CallAfter(self.on_finished, results, messages, time.monotonic() - start_time, self.stopped)

    def verify_chunk(self, names: list):
        """Verify one chunk of ROM sets.  Returns (names, results, messages), or None if the check was stopped."""
        if self.stopped:
            return None

        cmd = [self.path_executable, '-rompath', self.rom_path, '-verifyroms'] + names
        try:
            process = subprocess.Popen(cmd,
                                       stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE,
                                       text=True,
                                       errors='replace',
                                       cwd=functions.mame_working_dir(self.path_executable),
                                       **functions.NO_CONSOLE)
        except OSError as e:
            return names, [], [_('Error running MAME: {}').format(e)]

        with self._lock:
            self._processes.add(process)
            if self.stopped:            # stop() ran between the check above and the process being added
                process.kill()
        try:
            stdout, stderr = process.communicate()
        finally:
            with self._lock:
                self._processes.discard(process)

        if self.stopped:
            return None
        results, messages = parse_verify_output(stdout.splitlines(), names)
        return names, results, messages + stderr_messages(stderr.splitlines())


# ----------------------------------------------------------------------------------------------------------------------
class CheckAll(wx.Frame):
    _open_window = None     # The Check All window currently open - there is only ever one

    @classmethod
    def open(cls, path_executable: str, folders_roms: str, my_logger):
        """Show the Check All window, bringing the existing one to the front if it is already open."""
        window = cls._open_window
        if window:              # A destroyed wx window is False
            window.Raise()
            return window
        return cls(path_executable, folders_roms, my_logger)

    def __init__(self, path_executable: str, folders_roms: str, my_logger):
        style = (wx.SYSTEM_MENU | wx.CAPTION | wx.CLOSE_BOX | wx.CLIP_CHILDREN)
        wx.Frame.__init__(self, wx.GetApp().TopWindow, -1, _('Check All ROMs'), wx.DefaultPosition, style=style)
        CheckAll._open_window = self

        self.path_executable = path_executable
        self.rom_folders = [folder for folder in folders_roms.split(';') if folder.strip()]
        self.my_logger = my_logger

        # --------------------------------------------------------------------------------------------------------------
        # Get the absolute path to this application.  This is needed if we run via shortcut
        # or link otherwise we couldn't find relative files like icons etc
        self.path_to_me = functions.path_to_me()  # Get the absolute path to me

        # --------------------------------------------------------------------------------------------------------------
        # Get colour data from the INI file.
        self.application_colors = functions.get_application_colors()
        self.hex_color_text = '#%02x%02x%02x' % self.application_colors['text'][0:3]
        self.hex_color_background = '#%02x%02x%02x' % self.application_colors['text_background'][0:3]

        # --------------------------------------------------------------------------------------------------------------
        # The results of the last check (all of them - the filter is applied when they are shown)
        self.results: list = []
        self.messages: list = []
        self.elapsed: float = 0.0
        self.stopped: bool = False
        self.has_run: bool = False
        self.worker: CheckAllThread | None = None
        self.recheck: bool = False      # The running check is a re-check of the bad / not found sets
        self.closing: bool = False

        # --------------------------------------------------------------------------------------------------------------
        # Define the application icon
        self.SetIcon(wx.Icon(os.path.join(self.path_to_me, 'images', 'pfemame.ico'), wx.BITMAP_TYPE_ICO))

        self.Bind(wx.EVT_CLOSE, self.on_close)  # Bind the close event
        self.Bind(wx.EVT_CHAR_HOOK, self.on_key_up)  # Use this to capture the escape key to close the window

        self.panel = panel = wx.Panel(self)  # Define the panel
        panel.SetBackgroundColour(self.application_colors['window_background'])

        fonts = functions.get_font_info()

        # --------------------------------------------------------------------------------------------------------------
        # Setup the controls
        self.textResults = wx.html.HtmlWindow(panel, size=wx.Size(500, 600))

        def set_color():
            self.textResults.SetBackgroundColour(self.application_colors['window_background'])
        wx.CallAfter(set_color)  # Can only set the controls color after it has fully drawn
        self.textResults.SetFont(fonts.global_font_normal)
        self.progress_bar = gauge.PyGauge(panel, -1, size=(500, 10),
                                          style=wx.GA_HORIZONTAL | wx.GA_SMOOTH | wx.GA_PROGRESS)
        self.progress_bar.SetBackgroundColour(wx.WHITE)
        self.progress_bar.SetBorderColor(wx.BLACK)
        self.progress_bar.SetBarColor([wx.Colour(162, 255, 178), wx.Colour(159, 176, 255)])
        self.progress_text = wx.StaticText(panel, -1, '')
        self.progress_text.SetForegroundColour(self.application_colors['text'])
        self.set_page([_('This could take 5 minutes or more depending upon a number of factors')])

        # --------------------------------------------------------------------------------------------------------------
        # Add the filter controls.  The labels get the number of ROM sets added once there are results
        self.filters = [
            (None, _('All')),
            (GOOD, _('Is Good')),
            (BAD, _('Is Bad')),
            (BEST_AVAILABLE, _('Is Best Available')),
            (NOT_FOUND, _('Not Found')),
        ]
        self.filter_buttons = []

        sizer_filters = wx.BoxSizer(wx.HORIZONTAL)
        for index, (status, label) in enumerate(self.filters):
            rb = wx.RadioButton(panel, -1, label, style=wx.RB_GROUP if index == 0 else 0)
            rb.SetForegroundColour(self.application_colors['text'])
            rb.Bind(wx.EVT_RADIOBUTTON, self.on_filter)
            rb.SetValue(index == 0)
            self.filter_buttons.append(rb)
            sizer_filters.Add(rb, 0, wx.ALL, 2)

        # --------------------------------------------------------------------------------------------------------------
        # Add the buttons
        self.save_button = functions.build_one_button(panel, _('SAVE RESULTS'), self.on_save,
                                                      tooltip=_('Save the results shown to a text file'))
        self.copy_button = functions.build_one_button(panel, _('COPY'), self.on_copy,
                                                      tooltip=_('Copy the results shown to the clipboard'))
        self.recheck_button = functions.build_one_button(panel, _('RE-CHECK BAD'), self.on_recheck,
                                                         tooltip=_('Check only the bad and not found ROM sets again'))
        self.run_check_button = functions.build_one_button(panel, _('RUN CHECK'), self.on_run_check)
        self.stop_button = functions.build_one_button(panel, _('STOP'), self.on_stop)
        self.exit_button = functions.build_one_button(panel, _('EXIT'), self.on_ok)
        self.exit_button.SetFocus()
        self.stop_button.Disable()
        self.results_buttons = (self.save_button, self.copy_button, self.recheck_button)

        sizer_buttons = wx.BoxSizer(wx.HORIZONTAL)
        for button in (self.save_button, self.copy_button, self.recheck_button, self.run_check_button,
                       self.stop_button, self.exit_button):
            sizer_buttons.Add(button, 0, wx.ALL, 2)

        # --------------------------------------------------------------------------------------------------------------
        # Put everything into the main sizer
        sizer_vertical = wx.BoxSizer(wx.VERTICAL)
        sizer_vertical.AddSpacer(5)
        sizer_vertical.Add(self.textResults, 0, wx.ALIGN_CENTER, 5)
        sizer_vertical.Add(self.progress_bar, 0, wx.ALIGN_CENTER, 5)
        sizer_vertical.Add(self.progress_text, 0, wx.ALL | wx.EXPAND, 2)
        sizer_vertical.AddSpacer(5)
        sizer_vertical.Add(sizer_filters, 0, wx.ALL | wx.ALIGN_RIGHT, 2)
        sizer_vertical.AddSpacer(5)
        sizer_vertical.Add(sizer_buttons, 0, wx.ALL | wx.ALIGN_RIGHT, 2)
        sizer_vertical.AddSpacer(5)

        sizer_horizontal = wx.BoxSizer(wx.HORIZONTAL)
        sizer_horizontal.AddSpacer(5)
        sizer_horizontal.Add(sizer_vertical, 1, wx.EXPAND)
        sizer_horizontal.AddSpacer(5)

        # --------------------------------------------------------------------------------------------------------------
        # Get the window to size automatically based upon sizer requirements
        # And show the sizer
        panel.SetSizer(sizer_horizontal)
        sizer_horizontal.Fit(self)
        panel.SetFocus()

        # --------------------------------------------------------------------------------------------------------------
        # Display the window
        # Following will only be called if this window is running as a child
        if self.GetParent():
            self.CenterOnParent()
        else:
            self.Centre()
        self.Show()
        for button in self.results_buttons:     # Start with these hidden as there are no results
            button.Hide()

        # Ensure all controls have the system-wide colors
        functions.set_colors(self, self.application_colors)

    # ------------------------------------------------------------------------------------------------------------------
    # Display helpers
    def set_page(self, lines: list):
        self.textResults.SetPage(f'<body bgcolor="{self.hex_color_background}"><font color="{self.hex_color_text}">'
                                 + ''.join(_html_line(line, None) for line in lines) + '</font></body>')

    def current_filter(self) -> str | None:
        for (status, _label), rb in zip(self.filters, self.filter_buttons):
            if rb.GetValue():
                return status
        return None

    def shown_results(self) -> tuple:
        """(results, header) for the current filter."""
        return (filter_results(self.results, self.current_filter()),
                summary_lines(self.results, self.elapsed, self.stopped))

    def show_results(self):
        results, header = self.shown_results()
        self.textResults.SetPage(render_html(results, header, self.messages,
                                             self.hex_color_text, self.hex_color_background))

        counts = count_results(self.results)
        for (status, label), rb in zip(self.filters, self.filter_buttons):
            rb.SetLabel('{} ({})'.format(label, len(self.results) if status is None else counts[status]))

        for button in self.results_buttons:
            button.Show()
        self.recheck_button.Enable(any(result.status in RECHECK_STATUSES for result in self.results))
        self.panel.GetSizer().Fit(self)     # The counts make the filter labels wider

    def set_running(self, running: bool):
        """Enable / disable the controls while a check runs (EXIT stays enabled - closing stops the check)."""
        self.stop_button.Enable(running)
        self.run_check_button.Enable(not running)
        for button in self.results_buttons:
            button.Enable(not running)
        for rb in self.filter_buttons:
            rb.Enable(not running)
        if not running and self.has_run:
            self.recheck_button.Enable(any(result.status in RECHECK_STATUSES for result in self.results))

    def repaint_buttons(self):
        """GenButtons stay grey after a modal dialog until something repaints them."""
        def repaint():
            if self:
                for button in self.results_buttons + (self.run_check_button, self.stop_button, self.exit_button):
                    button.Refresh()
                    button.Update()
        wx.CallAfter(repaint)

    def rom_path(self) -> str | None:
        """The ROM folders for MAME's -rompath (';' separated), or None if none of them exist."""
        folders = [folder for folder in self.rom_folders if os.path.isdir(folder)]
        return ';'.join(folders) if folders else None

    # ------------------------------------------------------------------------------------------------------------------
    # Handle the save results event
    def on_save(self, _event):
        file_dialog = wx.FileDialog(self, _('Output path'), '', '',
                                    wildcard='TXT files (*.txt)|*.txt|All files (*.*)|*.*',
                                    style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT)

        if file_dialog.ShowModal() == wx.ID_OK:
            path = file_dialog.GetPath()
            if not os.path.splitext(path)[1]:
                path += '.txt'

            results, header = self.shown_results()
            try:
                with open(path, 'w', encoding='utf-8') as fp:
                    fp.write(render_text(results, header, self.messages))
                wx.MessageBox(_('Results written to file'),
                              _('File Written'),
                              wx.OK | wx.ICON_INFORMATION)
            except OSError:
                wx.MessageBox(_('Unable to save file to location.  Check permissions.'),
                              _('File Write Error'),
                              wx.OK | wx.ICON_ERROR)
        file_dialog.Destroy()
        self.repaint_buttons()

    # ------------------------------------------------------------------------------------------------------------------
    # Copy the results shown to the clipboard
    def on_copy(self, _event):
        results, header = self.shown_results()
        if wx.TheClipboard.Open():
            wx.TheClipboard.SetData(wx.TextDataObject(render_text(results, header, self.messages)))
            wx.TheClipboard.Flush()     # Keep the text on the clipboard after pfeMAME closes
            wx.TheClipboard.Close()
            wx.MessageBox(_('Results copied to the clipboard'), _('Check All ROMs'), wx.OK | wx.ICON_INFORMATION)
        self.repaint_buttons()

    # ------------------------------------------------------------------------------------------------------------------
    # Capture a key event on the panel and look for the escape key to close the window
    def on_key_up(self, event):
        if event.GetKeyCode() == wx.WXK_ESCAPE:
            self.Close()
            return
        event.Skip()

    # ------------------------------------------------------------------------------------------------------------------
    # Handle the close event: stop any running check and give the main window back the focus
    def on_close(self, _event):
        self.closing = True
        if self.worker:
            self.worker.stop()
        if CheckAll._open_window is self:
            CheckAll._open_window = None
        parent = self.GetParent()
        if parent and hasattr(parent, 'list'):  # Following will only be called if this window is running as a child
            parent.list.SetFocus()
        self.Destroy()

    # ------------------------------------------------------------------------------------------------------------------
    # Handle the ok event
    def on_ok(self, _event):
        self.Close()

    # ------------------------------------------------------------------------------------------------------------------
    # Handle the stop now event
    def on_stop(self, _event):
        if self.worker:
            self.worker.stop()
        self.stop_button.Disable()

    # ------------------------------------------------------------------------------------------------------------------
    # Run the check on all existing games
    def on_run_check(self, _event):
        self.start_check(load_rom_names(self.my_logger), recheck=False)

    # Run the check again on just the bad and not found ROM sets
    def on_recheck(self, _event):
        self.start_check([result.name for result in self.results if result.status in RECHECK_STATUSES], recheck=True)

    def start_check(self, names: list, recheck: bool):
        rom_path = self.rom_path()
        if not rom_path:
            wx.MessageBox(_('The path {} for your ROMs folder doesnt exist.  Please check '
                            'file paths settings.').format(';'.join(self.rom_folders)),
                          _('ERROR'),
                          wx.OK | wx.ICON_ERROR)
            self.repaint_buttons()
            return

        if not names:
            wx.MessageBox(_('There are no ROMs to check.  Your ROM list is empty or none of its ROMs are present in '
                            'your ROM folders.'),
                          _('Check All ROMs'),
                          wx.OK | wx.ICON_INFORMATION)
            self.repaint_buttons()
            return

        if self.my_logger:
            self.my_logger.info(_('Started checking all ROMs'))  # Write to the log file

        self.recheck = recheck
        self.progress_bar.SetRange(len(names))
        self.progress_bar.SetValue(0)
        self.progress_bar.Refresh()
        self.on_progress(0, len(names))
        self.set_running(True)

        self.worker = CheckAllThread(self.path_executable, rom_path, names, self.on_progress, self.on_finished)
        self.worker.start()

    # ------------------------------------------------------------------------------------------------------------------
    # This event is called when a filter option is changed
    def on_filter(self, _event):
        if self.has_run:
            self.show_results()

    # ------------------------------------------------------------------------------------------------------------------
    # Called (on the GUI thread) by the worker thread
    def on_progress(self, done: int, total: int):
        if not self or self.closing:
            return
        self.progress_bar.SetValue(min(done, total))
        self.progress_bar.Refresh()
        self.progress_text.SetLabel(_('Checked {done} of {total} ROM sets').format(done=done, total=total))

    def on_finished(self, results: list, messages: list, elapsed: float, stopped: bool):
        if not self or self.closing:
            return
        self.worker = None
        if self.recheck:
            self.results = merge_results(self.results, results)
        else:
            self.results = merge_results([], results)
        self.messages = messages
        self.elapsed = elapsed
        self.stopped = stopped
        self.has_run = True

        self.set_running(False)
        self.show_results()

        if self.my_logger:
            self.my_logger.info(_('Completed checking all ROMs'))  # Write to the log file


if __name__ == '__main__':
    app = wx.App()

    # Set up logging if running directly
    logger = functions.setup_logging(functions.path_to_me())

    # CheckAll.open(path_executable='/usr/games/mame',
    #               folders_roms='/media/finchy/Expansion Drive/Mameui64/Roms')
    CheckAll.open(path_executable='D:/mame/mame.exe',
                  folders_roms='D:/mame/roms',
                  my_logger=logger)
    app.MainLoop()
