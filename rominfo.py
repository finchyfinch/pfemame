#!/usr/bin/env python3

# ----------------------------------------------------------------------------------------------------------------------
# rominfo.py

"""
ROM file information viewer
This displays information on what MAME expects to see in the rom file / folder
for the specified game (mame -listroms), and can check the ROM set against it (mame -verifyroms)
"""
# Import python & wxPython modules
import html
import os
import re
import subprocess
import threading
from dataclasses import dataclass

import wx
import wx.html

# Import my own modules
import checkall
import functions

_ = functions.set_up_language()  # Set up the application language

LIST_TIMEOUT = 60           # Seconds to wait for 'mame -listroms'
VERIFY_TIMEOUT = 300        # Seconds to wait for 'mame -verifyroms' (large CHD sets take a while to hash)

# Status colours used in the html window
OK_COLOUR = '#3cb043'
PROBLEM_COLOUR = 'red'
WARNING_COLOUR = 'orange'

# Dump states of a ROM, from the -listroms output
GOOD_DUMP = ''
BAD_DUMP = 'bad dump'
NO_DUMP = 'no good dump known'

_CRC = re.compile(r'CRC\(([0-9a-fA-F]+)\)')
_SHA1 = re.compile(r'SHA1\(([0-9a-fA-F]+)\)')
_VERIFY_FILE_LINE = re.compile(r'^\S+\s*:\s*(\S+)(?: \(\d+ bytes\))? - (.+?)\s*$')    # 'set : file (n bytes) - STATUS'
_WARNING_TERMS = ('NO GOOD DUMP KNOWN', 'NEEDS REDUMP')


# ----------------------------------------------------------------------------------------------------------------------
# MAME output parsing (no wx)
@dataclass
class RomEntry:
    name: str
    size: str = ''          # '' for a disk (CHD) - MAME doesn't list a size for those
    crc: str = ''
    sha1: str = ''
    dump: str = GOOD_DUMP   # GOOD_DUMP, BAD_DUMP or NO_DUMP
    status: str = ''        # Filled in by a verify: 'OK' or MAME's problem text

    @property
    def is_disk(self) -> bool:
        return not self.size


def parse_listroms_output(text: str) -> tuple[str, list]:
    """
    Turn 'mame -listroms <name>' output into (header, [RomEntry]).  MAME prints e.g.

        ROMs required for driver "pacman".
        Name                                   Size Checksum
        pacman.6e                              4096 CRC(c1e6ab10) SHA1(e87e059c5be45753f7e9f33dff851f16d6751181)
        epr-1286.16                            2048 BAD CRC(fbe0d501) SHA1(bfa2...) BAD_DUMP
        kinst                                       SHA1(81d833236e994528d1482979261401b198d1ca53)     <- a disk (CHD)
        prom.1                                   32 NO GOOD DUMP KNOWN

    or just 'No ROMs required for driver "pong".'  An unknown name prints nothing to stdout: ('', []).
    """
    lines = [line.rstrip() for line in text.splitlines() if line.strip()]
    if not lines:
        return '', []

    roms = []
    for line in lines[1:]:
        tokens = line.split()
        if tokens[:3] == ['Name', 'Size', 'Checksum']:
            continue
        rest = tokens[1:]
        size = rest.pop(0) if rest and rest[0].isdigit() else ''
        checksums = ' '.join(rest)
        crc = _CRC.search(checksums)
        sha1 = _SHA1.search(checksums)
        if 'NO GOOD DUMP KNOWN' in checksums:
            dump = NO_DUMP
        elif 'BAD_DUMP' in rest or 'BAD' in rest:
            dump = BAD_DUMP
        else:
            dump = GOOD_DUMP
        roms.append(RomEntry(name=tokens[0], size=size, crc=crc.group(1) if crc else '',
                             sha1=sha1.group(1) if sha1 else '', dump=dump))
    return lines[0], roms


def verify_file_statuses(details: list) -> dict:
    """
    MAME's per-file '-verifyroms' lines for one ROM set as {file name: problem}, e.g.

        pacman      : pacman.5f (4096 bytes) - INCORRECT CHECKSUM:
        EXPECTED: CRC(958fedf9) SHA1(4a937ac02216ea8c96477d4a15522070507fb599)
           FOUND: CRC(c71c0011)
        pacman      : 82s123.7f (32 bytes) - NOT FOUND (puckman)

    gives {'pacman.5f': 'INCORRECT CHECKSUM - FOUND: CRC(c71c0011)', '82s123.7f': 'NOT FOUND (puckman)'}
    """
    statuses = {}
    last = None
    for line in details:
        match = _VERIFY_FILE_LINE.match(line)
        if match:
            last = match.group(1)
            statuses[last] = match.group(2).rstrip(':')
        elif last and line.strip().startswith('FOUND:'):
            statuses[last] += ' - ' + line.strip()
    return statuses


def apply_verify_result(roms: list, result) -> None:
    """Fill in each RomEntry's status from a checkall.RomsetResult."""
    statuses = verify_file_statuses(result.details)
    for rom in roms:
        if result.status == checkall.NOT_FOUND:
            rom.status = 'NOT FOUND'
        else:
            rom.status = statuses.get(rom.name, 'OK')


def status_colour(status: str) -> str | None:
    if not status:
        return None
    if status == 'OK':
        return OK_COLOUR
    if any(term in status for term in _WARNING_TERMS):
        return WARNING_COLOUR
    return PROBLEM_COLOUR


def render_html(header: str, roms: list, messages: list, summary: str, summary_colour: str | None,
                text_colour: str, background_colour: str) -> str:
    """The html shown in the window: MAME's header line, a table of the ROMs and (after a verify) the summary."""
    def cell(value, colour=None, bold=False):
        value = html.escape(value) if value else '&nbsp;'
        if bold:
            value = f'<b><u>{value}</u></b>'
        return f'<td nowrap><font color="{colour or text_colour}">{value}</font></td>'

    parts = [f'<body bgcolor="{background_colour}"><font size="3">',
             f'<font color="{text_colour}"><b>{html.escape(header)}</b></font><br>']

    for message in messages:
        parts.append(f'<font color="{PROBLEM_COLOUR}">{html.escape(message)}</font><br>')

    if summary:
        parts.append(f'<font color="{summary_colour or text_colour}"><b>{html.escape(summary)}</b></font><br>')

    parts.append('<table border="0" cellspacing="0" cellpadding="4">')
    if roms:
        # The Dump and Status columns are only shown when there is something in them
        show_dump = any(rom.dump for rom in roms)
        show_status = any(rom.status for rom in roms)
        titles = [_('Name'), _('Size'), _('CRC'), _('SHA1')]
        titles += [_('Dump')] if show_dump else []
        titles += [_('Status')] if show_status else []
        parts.append('<tr>' + ''.join(cell(title, bold=True) for title in titles) + '</tr>')
        dump_text = {BAD_DUMP: (_('BAD DUMP'), PROBLEM_COLOUR), NO_DUMP: (_('NO GOOD DUMP KNOWN'), WARNING_COLOUR)}
        for rom in roms:
            row = (cell(rom.name) +
                   cell(rom.size if not rom.is_disk else _('disk (CHD)')) +
                   cell(rom.crc) +
                   cell(rom.sha1))
            if show_dump:
                row += cell(*dump_text.get(rom.dump, ('', None)))
            if show_status:
                row += cell(rom.status, status_colour(rom.status))
            parts.append(f'<tr>{row}</tr>')

    parts.append('</table></font></body>')
    return ''.join(parts)


def run_mame(path_executable: str, args: list, timeout: int) -> tuple[str, list, bool]:
    """
    Run MAME and return (stdout, stderr lines, ran).  Never raises - if MAME couldn't be run (or didn't finish)
    ran is False and the reason is returned as the stderr line.
    """
    try:
        output = subprocess.run([path_executable] + args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                universal_newlines=True, errors='replace', timeout=timeout,
                                cwd=functions.mame_working_dir(path_executable), **functions.NO_CONSOLE)
    except subprocess.TimeoutExpired:
        return '', [_('MAME did not finish within {} seconds.').format(timeout)], False
    except OSError as e:
        return '', [_('Error running MAME: {}').format(e)], False
    return output.stdout, checkall.stderr_messages(output.stderr.splitlines()), True


def rgb_to_hex(rgb) -> str:
    """Convert an RGB tuple / wx.Colour to an HTML colour"""
    return '#{:02x}{:02x}{:02x}'.format(*tuple(rgb)[:3])


# ----------------------------------------------------------------------------------------------------------------------
# Window for displaying the rom information
class WindowMessage(wx.Frame):
    def __init__(self, rom_file_name, rom_name, path_executable):
        style = (wx.SYSTEM_MENU | wx.CAPTION | wx.CLOSE_BOX | wx.CLIP_CHILDREN | wx.STAY_ON_TOP)
        wx.Frame.__init__(self,
                          wx.GetApp().TopWindow,
                          -1,
                          _('ROM Information - {}').format(rom_name),
                          wx.DefaultPosition,
                          style=style)

        self.rom_file_name = rom_file_name
        self.path_executable = path_executable
        self.verify_output = ''

        # --------------------------------------------------------------------------------------------------------------
        # Check that we have a valid path before taking control from the main window
        if not os.path.exists(path_executable):
            functions.show_error_dialog(self.GetParent(), _('Unable to find the MAME executable path.'), _('ERROR'))
            self.Destroy()
            return

        # --------------------------------------------------------------------------------------------------------------
        # Get the application colours
        self.application_colors = functions.get_application_colors()
        self.SetBackgroundColour(self.application_colors['window_background'])
        self.SetForegroundColour(self.application_colors['text'])
        self.text_colour = rgb_to_hex(self.application_colors['text'])
        self.background_colour = rgb_to_hex(self.application_colors['text_background'])

        # --------------------------------------------------------------------------------------------------------------
        # Define the application icon
        self.SetIcon(wx.Icon(os.path.join(functions.path_to_me(), 'images', 'pfemame.ico'), wx.BITMAP_TYPE_ICO))

        if self.GetParent():  # Following will only be called if this window is running as a child
            self.CenterOnParent()
            self.GetParent().Disable()

        self.Bind(wx.EVT_CLOSE, self.on_close)
        self.Bind(wx.EVT_CHAR_HOOK, self.on_key_up)  # Use this to capture the escape key to close the window

        panel = wx.Panel(self)
        panel.SetFocus()

        self.htmlControl = wx.html.HtmlWindow(panel, size=wx.Size(-1, 300))  # Create the HTML control
        self.htmlControl.Bind(wx.EVT_TEXT_COPY, self.on_copy)

        # --------------------------------------------------------------------------------------------------------------
        # Get the ROM information from MAME
        self.raw_output, self.messages, _ran = run_mame(path_executable, ['-listroms', rom_file_name], LIST_TIMEOUT)
        self.header, self.roms = parse_listroms_output(self.raw_output)
        if not self.header and not self.messages:
            self.messages = [_('MAME did not return any ROM information for {}.').format(rom_file_name)]
        self.summary = ''
        self.summary_colour = None
        self.show_page()

        # --------------------------------------------------------------------------------------------------------------
        # Setup the sizer and add the buttons
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self.htmlControl, 0, wx.ALL | wx.EXPAND, 2)
        button_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.verify_button = functions.build_one_button(
            panel, _('VERIFY'), self.on_verify,
            tooltip=_('Check the ROM files in your ROM folders against what MAME expects'))
        self.verify_button.Enable(bool(self.roms))
        button_sizer.Add(self.verify_button, 0, wx.ALL, 2)
        button_sizer.Add(functions.build_one_button(panel, _('COPY TO CLIPBOARD'), self.on_copy), 0, wx.ALL, 2)
        button_sizer.Add(functions.build_one_button(panel, _('OK'), self.on_close), 0, wx.ALL, 2)
        sizer.Add(wx.StaticLine(panel), 0, wx.EXPAND | wx.ALL, 5)
        sizer.Add(button_sizer, 0, wx.ALL | wx.ALIGN_RIGHT, 2)

        # --------------------------------------------------------------------------------------------------------------
        # Get the window to size automatically based upon sizer requirements
        # and show the sizer
        panel.SetSizer(sizer)
        sizer.Fit(self)
        sizer.Layout()

        # --------------------------------------------------------------------------------------------------------------
        # Resize the window to fit in all the information, then display it
        wx.CallAfter(self.fit_to_page, True)
        self.Centre()

    # ------------------------------------------------------------------------------------------------------------------
    def show_page(self) -> None:
        self.htmlControl.SetPage(render_html(self.header, self.roms, self.messages, self.summary, self.summary_colour,
                                             self.text_colour, self.background_colour))

    # ------------------------------------------------------------------------------------------------------------------
    # Update the window and html control dimensions to fit the text within
    def fit_to_page(self, first_time: bool = False) -> None:
        if not self:
            return
        y = self.GetClientSize()[1]  # Get the correct y size before I programmatically resize the window
        width = self.htmlControl.GetInternalRepresentation().GetWidth() + 25
        width = max(width, self.GetBestSize()[0], self.FromDIP(450))  # Never narrower than the buttons
        self.htmlControl.SetSize(width, -1)
        self.SetClientSize([width, y])  # Resize the window to remove horizontal scroll bars
        self.Layout()
        if first_time:
            self.Centre()
            self.Show()
        self.Refresh()

    # ------------------------------------------------------------------------------------------------------------------
    # Check the ROM set in a background thread - hashing big ROM / CHD sets can take a while
    def on_verify(self, _event=None) -> None:
        self.verify_button.Disable()
        self.summary = _('Verifying...')
        self.summary_colour = None
        self.show_page()
        threading.Thread(target=self.verify_thread, daemon=True).start()

    def verify_thread(self) -> None:
        stdout, errors, ran = run_mame(self.path_executable, ['-verifyroms', self.rom_file_name], VERIFY_TIMEOUT)
        wx.CallAfter(self.on_verify_done, stdout, errors, ran)

    def on_verify_done(self, stdout: str, errors: list, ran: bool) -> None:
        if not self:  # The window was closed while MAME was still checking
            return
        result = None
        if ran:
            # MAME prints 'romset "name" not found!' to stderr, so read both
            lines = stdout.splitlines() + errors
            self.verify_output = '\n'.join(lines) + '\n'
            results, messages = checkall.parse_verify_output(lines, [self.rom_file_name])
            result = next((r for r in results if r.name == self.rom_file_name), None)
            self.messages = [line for line in messages if line.strip()]
        else:
            self.messages = errors
        if result:
            apply_verify_result(self.roms, result)
            self.summary = result.status_line()
            self.summary_colour = {checkall.GOOD: OK_COLOUR, checkall.BEST_AVAILABLE: WARNING_COLOUR}.get(
                result.status, PROBLEM_COLOUR)
        else:
            self.summary = ''
        self.show_page()
        self.verify_button.Enable()
        self.fit_to_page()

    # ------------------------------------------------------------------------------------------------------------------
    # Process the copy to clipboard request.  The raw output from MAME is used (plus the verify results if checked)
    def on_copy(self, _event=None) -> None:
        text = self.raw_output
        if self.verify_output:
            text = text.rstrip('\n') + '\n\n' + self.verify_output
        data_object = wx.TextDataObject()
        data_object.SetText(text)
        if wx.TheClipboard.Open():
            wx.TheClipboard.SetData(data_object)
            wx.TheClipboard.Close()
        else:
            wx.MessageBox(_('Unable to open the clipboard'), _('ERROR'))

    # ------------------------------------------------------------------------------------------------------------------
    # Capture a key event on the panel and look for the escape key to close the window
    def on_key_up(self, event):
        if event.GetKeyCode() == wx.WXK_ESCAPE:
            self.on_close()
        event.Skip()

    # ------------------------------------------------------------------------------------------------------------------
    # Handle the close event and ensure the parent window is given back control
    def on_close(self, _event=None):
        parent = self.GetParent()
        if parent:  # Following will only be called if this window is running as a child
            parent.Enable()
            if getattr(parent, 'list', None):
                parent.list.SetFocus()
        self.Destroy()


if __name__ == '__main__':
    app = wx.App()
    # This data is just used for testing purposes
    frame = WindowMessage('005', '99 Last War', 'D:/mame/mame.exe')
    app.MainLoop()
