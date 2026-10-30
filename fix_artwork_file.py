#!/usr/bin/env python3

# ----------------------------------------------------------------------------------------------------------------------
# fix_artwork_file.py

"""
Artwork Layout Fixer.

Older MAME artwork layout (.lay) files place their pictures with the view item tags <backdrop>, <overlay>, <bezel>,
<cpanel> and <marquee>, which newer MAME versions no longer support.  This finds them in the artwork of every
mame.ini artpath folder (.zip files and unzipped artwork folders) and rewrites them as <element ref="..."> items,
keeping the way each layer used to be drawn:

    <backdrop element="bg">...</backdrop>   ->  <element ref="bg" blend="add">...</element>
    <overlay element="ov">...</overlay>     ->  <element ref="ov" blend="multiply">...</element>
    <bezel element="bz">...</bezel>         ->  <element ref="bz">...</element>     (cpanel and marquee the same)

Opening the window only analyses the artwork.  Nothing is changed until FIX is pressed, and each file is first
copied to an 'artwork_backup' folder inside its artwork folder so that RESTORE BACKUP can put it back.

Scanning, converting, backing up, restoring and the summaries are plain functions (no wx calls) so they can be unit
tested - see tests/test_fix_artwork_file.py.
"""

import codecs
import os
import re
import shutil
import sys
import tempfile
import threading
import zipfile
from collections import Counter
from dataclasses import dataclass, field

import wx
import wx.lib.agw.pygauge as gauge

import functions

_ = functions.set_up_language()  # Set of the application language

# ----------------------------------------------------------------------------------------------------------------------
MINIMUM_MAME_VERSION = '0.255'
BACKUP_FOLDER = 'artwork_backup'        # Made inside each artwork folder.  Holds the original of every changed file
OLD_TAGS = ('backdrop', 'overlay', 'bezel', 'cpanel', 'marquee')
BLEND_MODES = {'backdrop': 'add', 'overlay': 'multiply'}    # How MAME used to draw these (the others were 'alpha')

_ATTRIBUTES = r'''(?:[^>"']|"[^"]*"|'[^']*')*?'''
_OLD_ITEM_RE = re.compile(r'<(' + '|'.join(OLD_TAGS) + r')\b(' + _ATTRIBUTES + r')(/>|>(.*?)</\1\s*>)',
                          re.IGNORECASE | re.DOTALL)
_ATTRIBUTE_RE = re.compile(r'''([\w:.-]+)(\s*=\s*)("[^"]*"|'[^']*')''')


# ----------------------------------------------------------------------------------------------------------------------
# Converting a layout (no wx)
def convert_layout(text: str) -> tuple:
    """
    Replace the old view item tags in the text of a .lay file.  Returns (new text, Counter of old tag -> number
    replaced).  Items without an element attribute are left alone (MAME never accepted those).
    """
    counts = Counter()

    def replace(match):
        tag = match.group(1).lower()
        attributes = _ATTRIBUTE_RE.findall(match.group(2))
        names = [name.lower() for name, _equals, _value in attributes]
        if 'element' not in names:
            return match.group(0)

        parts = [('ref' if name.lower() == 'element' else name) + equals + value
                 for name, equals, value in attributes]
        if tag in BLEND_MODES and 'blend' not in names:
            parts.append(f'blend="{BLEND_MODES[tag]}"')
        counts[tag] += 1

        opening = '<element ' + ' '.join(parts)
        if match.group(3) == '/>':
            return opening + '/>'
        return opening + '>' + match.group(4) + '</element>'

    return _OLD_ITEM_RE.sub(replace, text), counts


def convert_layout_bytes(raw: bytes) -> tuple:
    """
    convert_layout() for the bytes of a .lay file, which come back in the file's own encoding.  Latin-1 maps each
    byte to one character and back, so UTF-8, ISO-8859-1 and the other ASCII based encodings are untouched apart
    from the replaced tags (which are plain ASCII).  UTF-16 files (with a byte order mark) are decoded properly.
    """
    codec = 'utf-16' if raw.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)) else 'latin-1'
    text, counts = convert_layout(raw.decode(codec))
    return (text.encode(codec) if counts else raw), counts


# ----------------------------------------------------------------------------------------------------------------------
# Finding and checking the artwork (no wx)
@dataclass
class ArtworkSet:
    art_folder: str                 # The artpath folder it is in
    path: str                       # The .zip file or the unzipped artwork folder
    layouts_checked: int = 0
    changes: dict = field(default_factory=dict)     # .lay file name (in the zip / folder) -> Counter of old tags
    error: str = ''
    single_folder: bool = True      # The only artwork folder being checked, so the folder needn't be shown

    @property
    def name(self) -> str:
        return os.path.basename(self.path)

    @property
    def display_name(self) -> str:
        return self.name if self.single_folder else self.path

    @property
    def is_zip(self) -> bool:
        return self.path.lower().endswith('.zip')

    def tag_counts(self) -> Counter:
        return sum(self.changes.values(), Counter())


@dataclass
class ScanResult:
    sets: list = field(default_factory=list)            # ArtworkSet for each .zip / folder found
    missing_folders: list = field(default_factory=list)
    unsupported: list = field(default_factory=list)     # .7z artwork, which can't be rewritten

    def needing_update(self) -> list:
        return [artwork_set for artwork_set in self.sets if artwork_set.changes]


def find_artwork_sets(art_folders: list) -> ScanResult:
    """The artwork sets (.zip files and folders) in the artpath folders, not yet analysed."""
    result = ScanResult()
    single_folder = len(art_folders) == 1
    for art_folder in art_folders:
        if not os.path.isdir(art_folder):
            result.missing_folders.append(art_folder)
            continue
        for entry in sorted(os.listdir(art_folder), key=str.lower):
            path = os.path.join(art_folder, entry)
            if os.path.isdir(path):
                if entry.lower() != BACKUP_FOLDER:
                    result.sets.append(ArtworkSet(art_folder, path, single_folder=single_folder))
            elif entry.lower().endswith('.zip'):
                result.sets.append(ArtworkSet(art_folder, path, single_folder=single_folder))
            elif entry.lower().endswith('.7z'):
                result.unsupported.append(path)
    return result


def _folder_layout_names(folder: str) -> list:
    names = []
    for root, _dirs, files in os.walk(folder):
        for file_name in files:
            if file_name.lower().endswith('.lay'):
                names.append(os.path.relpath(os.path.join(root, file_name), folder).replace(os.sep, '/'))
    return sorted(names, key=str.lower)


def _read_layouts(artwork_set: ArtworkSet) -> dict:
    """{.lay file name: bytes} for every layout file in the set."""
    if artwork_set.is_zip:
        with zipfile.ZipFile(artwork_set.path) as zin:
            return {info.filename: zin.read(info) for info in zin.infolist()
                    if not info.is_dir() and info.filename.lower().endswith('.lay')}
    layouts = {}
    for name in _folder_layout_names(artwork_set.path):
        with open(os.path.join(artwork_set.path, name), 'rb') as fp:
            layouts[name] = fp.read()
    return layouts


def analyse_set(artwork_set: ArtworkSet) -> ArtworkSet:
    """Fill in which of the set's layout files use old tags (or the error that stopped it being read)."""
    artwork_set.changes = {}
    artwork_set.error = ''
    try:
        layouts = _read_layouts(artwork_set)
    except (OSError, zipfile.BadZipFile, zipfile.LargeZipFile, NotImplementedError, RuntimeError) as exc:
        artwork_set.error = str(exc) or type(exc).__name__
        return artwork_set
    artwork_set.layouts_checked = len(layouts)
    for name, raw in layouts.items():
        _new, counts = convert_layout_bytes(raw)
        if counts:
            artwork_set.changes[name] = counts
    return artwork_set


# ----------------------------------------------------------------------------------------------------------------------
# Backing up, fixing and restoring (no wx)
def backup_path(art_folder: str, path: str) -> str:
    """Where the backup of a file in an artwork folder goes."""
    return os.path.join(art_folder, BACKUP_FOLDER, os.path.relpath(path, art_folder))


def _backup_file(art_folder: str, path: str) -> None:
    """Copy a file to the backup folder - unless it is already there, so the backup is always the first original."""
    destination = backup_path(art_folder, path)
    if not os.path.exists(destination):
        os.makedirs(os.path.dirname(destination), exist_ok=True)
        shutil.copy2(path, destination)


def _replace_file(path: str, write) -> None:
    """Write a new version of a file safely: write(temp path) next to it, then swap it in, so the file is never
    left half written."""
    handle, temp_path = tempfile.mkstemp(dir=os.path.dirname(path), prefix='.pfemame_', suffix='.tmp')
    os.close(handle)
    try:
        write(temp_path)
        shutil.copystat(path, temp_path)
        os.replace(temp_path, path)
    except BaseException:
        if os.path.exists(temp_path):
            os.remove(temp_path)
        raise


def _rewrite_zip(path: str, new_layouts: dict) -> None:
    def write(temp_path):
        with zipfile.ZipFile(path) as zin, zipfile.ZipFile(temp_path, 'w') as zout:
            zout.comment = zin.comment
            for info in zin.infolist():     # The ZipInfo keeps each file's date, attributes and compression
                zout.writestr(info, new_layouts[info.filename] if info.filename in new_layouts else zin.read(info))
    _replace_file(path, write)              # Both zips are closed by now, so Windows lets the original be replaced


def fix_set(artwork_set: ArtworkSet) -> Counter:
    """
    Back up and rewrite the set's layout files that use old tags.  Returns the Counter of tags replaced.
    Raises OSError / zipfile.BadZipFile if it can't - the original file is left as it was.
    """
    new_layouts = {}
    counts = Counter()
    for name, raw in _read_layouts(artwork_set).items():   # Read again: the files may have changed since analysis
        new_raw, layout_counts = convert_layout_bytes(raw)
        if layout_counts:
            new_layouts[name] = new_raw
            counts += layout_counts
    if not new_layouts:
        artwork_set.changes = {}
        return counts

    if artwork_set.is_zip:
        _backup_file(artwork_set.art_folder, artwork_set.path)
        _rewrite_zip(artwork_set.path, new_layouts)
    else:
        for name, new_raw in new_layouts.items():
            path = os.path.join(artwork_set.path, name)
            _backup_file(artwork_set.art_folder, path)

            def write(temp_path, data=new_raw):
                with open(temp_path, 'wb') as fp:
                    fp.write(data)
            _replace_file(path, write)
    artwork_set.changes = {}
    return counts


def find_backups(art_folders: list) -> list:
    """(backup file, file it was copied from) for every file in the artwork_backup folders."""
    backups = []
    for art_folder in art_folders:
        folder = os.path.join(art_folder, BACKUP_FOLDER)
        for root, _dirs, files in os.walk(folder):
            for file_name in sorted(files, key=str.lower):
                backup = os.path.join(root, file_name)
                backups.append((backup, os.path.join(art_folder, os.path.relpath(backup, folder))))
    return backups


def restore_file(backup: str, original: str) -> None:
    """Put a backed up file back (the backup is kept, in case it is needed again)."""
    os.makedirs(os.path.dirname(original), exist_ok=True)
    if os.path.exists(original):
        _replace_file(original, lambda temp_path: shutil.copy2(backup, temp_path))
    else:
        shutil.copy2(backup, original)


# ----------------------------------------------------------------------------------------------------------------------
# Text for the log window (no wx)
def describe_counts(counts: Counter) -> str:
    """e.g. '2 backdrop, 1 overlay' (in the OLD_TAGS order)."""
    return ', '.join(f'{counts[tag]} {tag}' for tag in OLD_TAGS if counts.get(tag))


def set_lines(artwork_set: ArtworkSet) -> list:
    """The log lines for one analysed set that needs updating (or couldn't be read)."""
    if artwork_set.error:
        return [_('{name}: could not be read - {error}').format(name=artwork_set.display_name,
                                                                 error=artwork_set.error)]
    return ['{}: {}'.format(f'{artwork_set.display_name} ({name})' if artwork_set.is_zip
                            else f'{artwork_set.display_name}/{name}', describe_counts(counts))
            for name, counts in artwork_set.changes.items()]


def analysis_summary(scan: ScanResult) -> list:
    sets = scan.sets
    needing = scan.needing_update()
    tags = sum((artwork_set.tag_counts() for artwork_set in needing), Counter())
    unreadable = [artwork_set for artwork_set in sets if artwork_set.error]
    zips = sum(1 for artwork_set in sets if artwork_set.is_zip)

    lines = ['', _('SUMMARY'),
             _('Artwork sets checked: {total} (zip files: {zips}, folders: {folders})').format(
                 total=len(sets), zips=zips, folders=len(sets) - zips),
             _('Layout (.lay) files checked: {}').format(sum(artwork_set.layouts_checked for artwork_set in sets)),
             _('Artwork sets that need updating: {}').format(len(needing))]
    if needing:
        lines.append(_('Old tags to replace: {total} ({detail})').format(total=sum(tags.values()),
                                                                          detail=describe_counts(tags)))
    if unreadable:
        lines.append(_('Artwork sets that could not be read: {}').format(len(unreadable)))
    if scan.unsupported:
        lines.append(_('.7z artwork skipped (only .zip files and folders can be updated): {}').format(
            len(scan.unsupported)))
    for folder in scan.missing_folders:
        lines.append(_('Artwork folder not found: {}').format(folder))
    lines.append('')
    if needing:
        lines.append(_('Press FIX to update them.  The original files are copied to the {} folder first.').format(
            BACKUP_FOLDER))
    elif sets:
        lines.append(_('Your artwork is up to date - nothing needs changing.'))
    return lines


def fix_summary(updated: int, failed: int, tags: Counter, backup_folders: list, stopped: bool) -> list:
    lines = ['', _('SUMMARY'),
             _('Artwork sets updated: {}').format(updated),
             _('Old tags replaced: {total} ({detail})').format(total=sum(tags.values()),
                                                                detail=describe_counts(tags) or '0')]
    if failed:
        lines.append(_('Artwork sets that failed (left unchanged): {}').format(failed))
    if stopped:
        lines.append(_('Stopped before all the artwork sets were updated.'))
    for folder in backup_folders:
        lines.append(_('The original files are in: {}').format(folder))
    return lines


def restore_summary(restored: int, failed: int, stopped: bool) -> list:
    lines = ['', _('SUMMARY'), _('Files restored from backup: {}').format(restored)]
    if failed:
        lines.append(_('Files that could not be restored: {}').format(failed))
    if stopped:
        lines.append(_('Stopped before all the files were restored.'))
    return lines


# ----------------------------------------------------------------------------------------------------------------------
# Runs one job (analyse / fix / restore) away from the GUI thread
class ArtworkWorker(threading.Thread):
    def __init__(self, job, on_line, on_progress, on_finished):
        """
        job(worker) does the work: it calls worker.line(text) / worker.progress(done, total) and checks
        worker.stopped.  The callbacks are called on the GUI thread.
        """
        super().__init__(daemon=True)
        self.job = job
        self.on_line = on_line
        self.on_progress = on_progress
        self.on_finished = on_finished
        self._stop_event = threading.Event()

    @property
    def stopped(self) -> bool:
        return self._stop_event.is_set()

    def stop(self):
        self._stop_event.set()

    def line(self, text: str):
        wx.CallAfter(self.on_line, text)

    def progress(self, done: int, total: int):
        wx.CallAfter(self.on_progress, done, total)

    def run(self):
        try:
            self.job(self)
        except Exception as exc:    # Report anything unexpected rather than losing it with the thread
            self.line(_('ERROR: {}').format(exc))
        wx.CallAfter(self.on_finished)


# ----------------------------------------------------------------------------------------------------------------------
class LayoutFixerFrame(wx.Frame):
    _open_window = None     # The Artwork Layout Fixer window currently open - there is only ever one

    @classmethod
    def open(cls, art_folders: list):
        """Show the window, bringing the existing one to the front if it is already open."""
        window = cls._open_window
        if window:              # A destroyed wx window is False
            window.Raise()
            return window
        return cls(art_folders)

    def __init__(self, art_folders: list):
        style = (wx.SYSTEM_MENU | wx.CAPTION | wx.CLOSE_BOX | wx.RESIZE_BORDER | wx.MAXIMIZE_BOX | wx.CLIP_CHILDREN)
        app = wx.GetApp()
        super().__init__(app.GetTopWindow() if app else None, -1, _('Artwork Layout Fixer'), style=style)
        LayoutFixerFrame._open_window = self

        self.art_folders = list(art_folders)
        self.scan: ScanResult | None = None
        self.worker: ArtworkWorker | None = None
        self.closing = False
        self.application_colors = functions.get_application_colors()

        # --------------------------------------------------------------------------------------------------------------
        # Define the application icon
        self.SetIcon(wx.Icon(os.path.join(functions.path_to_me(), 'images', 'pfemame.ico'), wx.BITMAP_TYPE_ICO))

        self.Bind(wx.EVT_CLOSE, self.on_close)  # Bind the close event
        self.Bind(wx.EVT_CHAR_HOOK, self.on_key_up)  # Use this to capture the escape key to close the window

        self.panel = panel = wx.Panel(self)
        panel.SetBackgroundColour(self.application_colors['window_background'])
        fonts = functions.get_font_info()

        # --------------------------------------------------------------------------------------------------------------
        # Setup the controls
        intro = wx.StaticText(panel, -1, _('Finds artwork whose layout files use old tags (backdrop, overlay, bezel, '
                                           'cpanel and marquee) that newer MAME versions no longer support, and '
                                           'updates them.  Artwork folders:'))
        intro.SetFont(fonts.global_font_normal)
        intro.Wrap(800)
        folders = wx.StaticText(panel, -1, '\n'.join(self.art_folders or [_('(none set in mame.ini)')]),
                                size=wx.Size(800, -1), style=wx.ST_ELLIPSIZE_MIDDLE)   # Long paths don't widen it
        folders.SetFont(fonts.global_font_bold)

        self.log = wx.TextCtrl(panel, size=wx.Size(800, 450), style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2)
        self.log.SetFont(fonts.global_font_normal)

        self.progress_bar = gauge.PyGauge(panel, -1, size=(800, 10),
                                          style=wx.GA_HORIZONTAL | wx.GA_SMOOTH | wx.GA_PROGRESS)
        self.progress_bar.SetBackgroundColour(wx.WHITE)
        self.progress_bar.SetBorderColor(wx.BLACK)
        self.progress_bar.SetBarColor([wx.Colour(162, 255, 178), wx.Colour(159, 176, 255)])
        self.progress_text = wx.StaticText(panel, -1, '')

        # --------------------------------------------------------------------------------------------------------------
        # Add the buttons
        self.analyse_button = functions.build_one_button(panel, _('ANALYSE'), self.on_analyse,
                                                         tooltip=_('Check the artwork again (changes nothing)'))
        self.fix_button = functions.build_one_button(panel, _('FIX'), self.on_fix,
                                                     tooltip=_('Update the artwork that uses old tags.  The '
                                                               'original files are backed up first'))
        self.restore_button = functions.build_one_button(panel, _('RESTORE BACKUP'), self.on_restore,
                                                         tooltip=_('Put back the original artwork files from the '
                                                                   '{} folders').format(BACKUP_FOLDER))
        self.save_button = functions.build_one_button(panel, _('SAVE LOG'), self.on_save,
                                                      tooltip=_('Save the messages shown to a text file'))
        self.stop_button = functions.build_one_button(panel, _('STOP'), self.on_stop)
        self.exit_button = functions.build_one_button(panel, _('EXIT'), lambda _event: self.Close())
        self.buttons = (self.analyse_button, self.fix_button, self.restore_button, self.save_button,
                        self.stop_button, self.exit_button)

        sizer_buttons = wx.BoxSizer(wx.HORIZONTAL)
        for button in self.buttons:
            sizer_buttons.Add(button, 0, wx.ALL, 2)

        # --------------------------------------------------------------------------------------------------------------
        # Put everything into the main sizer
        sizer_vertical = wx.BoxSizer(wx.VERTICAL)
        sizer_vertical.AddSpacer(5)
        sizer_vertical.Add(intro, 0, wx.ALL | wx.EXPAND, 2)
        sizer_vertical.Add(folders, 0, wx.ALL | wx.EXPAND, 2)
        sizer_vertical.AddSpacer(5)
        sizer_vertical.Add(self.log, 1, wx.EXPAND)
        sizer_vertical.AddSpacer(5)
        sizer_vertical.Add(self.progress_bar, 0, wx.EXPAND)
        sizer_vertical.Add(self.progress_text, 0, wx.ALL | wx.EXPAND, 2)
        sizer_vertical.AddSpacer(5)
        sizer_vertical.Add(sizer_buttons, 0, wx.ALL | wx.ALIGN_RIGHT, 2)
        sizer_vertical.AddSpacer(5)

        sizer_horizontal = wx.BoxSizer(wx.HORIZONTAL)
        sizer_horizontal.AddSpacer(5)
        sizer_horizontal.Add(sizer_vertical, 1, wx.EXPAND)
        sizer_horizontal.AddSpacer(5)

        panel.SetSizer(sizer_horizontal)
        sizer_horizontal.Fit(self)

        # --------------------------------------------------------------------------------------------------------------
        # Display the window
        if self.GetParent():
            self.CenterOnParent()
        else:
            self.Centre()

        # Ensure all controls have the system-wide colors.  The panel and its labels sit on the window background
        functions.set_colors(self, self.application_colors)
        for control in (panel, intro, folders, self.progress_text):
            control.SetBackgroundColour(self.application_colors['window_background'])
        self.progress_bar.SetBackgroundColour(wx.WHITE)
        self.Show()
        self.exit_button.SetFocus()

        self.start_analyse()    # Only looks - nothing is changed until FIX is pressed

    # ------------------------------------------------------------------------------------------------------------------
    # Display helpers
    def add_line(self, text: str):
        if not self or self.closing:
            return
        self.log.AppendText(text + '\n')

    def add_lines(self, lines: list):
        for line in lines:
            self.add_line(line)

    def on_progress(self, done: int, total: int):
        if not self or self.closing:
            return
        self.progress_bar.SetRange(max(total, 1))
        self.progress_bar.SetValue(min(done, total))
        self.progress_bar.Refresh()
        self.progress_text.SetLabel(_('{done} of {total}').format(done=done, total=total))

    def shown_path(self, path: str) -> str:
        """A path in the log - relative to the artwork folder if there is only one (which is shown at the top)."""
        if len(self.art_folders) == 1:
            return os.path.relpath(path, self.art_folders[0]).replace(os.sep, '/')
        return path

    def set_running(self, running: bool):
        """Enable / disable the buttons while a job runs (EXIT stays enabled - closing stops the job)."""
        for button in (self.analyse_button, self.restore_button, self.save_button):
            button.Enable(not running)
        self.fix_button.Enable(not running and bool(self.scan and self.scan.needing_update()))
        self.stop_button.Enable(running)
        self.repaint_buttons()

    def repaint_buttons(self):
        """GenButtons stay grey after a modal dialog / being disabled until something repaints them."""
        def repaint():
            if self:
                for button in self.buttons:
                    button.Refresh()
                    button.Update()
        wx.CallAfter(repaint)

    def run_job(self, job, heading: str):
        self.log.Clear()
        self.add_line(heading)
        self.on_progress(0, 0)
        self.progress_text.SetLabel('')
        self.worker = ArtworkWorker(job, self.add_line, self.on_progress, self.on_job_finished)
        self.set_running(True)
        self.worker.start()

    def on_job_finished(self):
        if not self or self.closing:
            return
        self.worker = None
        self.set_running(False)

    def confirm(self, message: str) -> bool:
        dialog = wx.MessageDialog(self, message, _('Artwork Layout Fixer'),
                                  wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION)
        answer = dialog.ShowModal() == wx.ID_YES
        dialog.Destroy()
        self.repaint_buttons()
        return answer

    # ------------------------------------------------------------------------------------------------------------------
    # Analyse: find the artwork that uses old tags (changes nothing)
    def start_analyse(self):
        def job(worker):
            scan = find_artwork_sets(self.art_folders)
            for done, artwork_set in enumerate(scan.sets, 1):
                if worker.stopped:
                    worker.line(_('Stopped.'))
                    return
                analyse_set(artwork_set)
                for line in set_lines(artwork_set):
                    worker.line(line)
                worker.progress(done, len(scan.sets))
            for path in scan.unsupported:
                worker.line(_('{}: skipped - .7z artwork cannot be updated').format(self.shown_path(path)))
            wx.CallAfter(self.on_analysed, scan)
            for line in analysis_summary(scan):
                worker.line(line)

        self.scan = None
        self.run_job(job, _('Checking the artwork...'))

    def on_analysed(self, scan: ScanResult):
        if self and not self.closing:
            self.scan = scan

    def on_analyse(self, _event):
        self.start_analyse()

    # ------------------------------------------------------------------------------------------------------------------
    # Fix: back up and update the artwork that uses old tags
    def on_fix(self, _event):
        needing = self.scan.needing_update() if self.scan else []
        if not needing:
            return
        if not self.confirm(_('Update {count} artwork sets?\n\nThe original files are copied to the {folder} folder '
                              'inside each artwork folder first, so they can be restored.').format(
                count=len(needing), folder=BACKUP_FOLDER)):
            return

        def job(worker):
            updated = failed = 0
            tags = Counter()
            backup_folders = []
            for done, artwork_set in enumerate(needing, 1):
                if worker.stopped:
                    break
                try:
                    tags += fix_set(artwork_set)
                    updated += 1
                    worker.line(_('{}: updated').format(artwork_set.display_name))
                    folder = os.path.join(artwork_set.art_folder, BACKUP_FOLDER)
                    if folder not in backup_folders:
                        backup_folders.append(folder)
                except (OSError, zipfile.BadZipFile, zipfile.LargeZipFile, NotImplementedError, RuntimeError) as exc:
                    failed += 1
                    worker.line(_('{name}: FAILED, left unchanged - {error}').format(
                        name=artwork_set.display_name, error=exc))
                worker.progress(done, len(needing))
            for line in fix_summary(updated, failed, tags, backup_folders, worker.stopped):
                worker.line(line)

        self.run_job(job, _('Updating the artwork...'))

    # ------------------------------------------------------------------------------------------------------------------
    # Restore: put the original files back from the backup folders
    def on_restore(self, _event):
        backups = find_backups(self.art_folders)
        if not backups:
            wx.MessageBox(_('There are no backed up artwork files to restore.'), _('Artwork Layout Fixer'),
                          wx.OK | wx.ICON_INFORMATION)
            self.repaint_buttons()
            return
        if not self.confirm(_('Restore {count} files from the {folder} folders?\n\nThis replaces the current versions '
                              'of those files with the originals.').format(count=len(backups), folder=BACKUP_FOLDER)):
            return

        def job(worker):
            restored = failed = 0
            for done, (backup, original) in enumerate(backups, 1):
                if worker.stopped:
                    break
                try:
                    restore_file(backup, original)
                    restored += 1
                    worker.line(_('{}: restored').format(self.shown_path(original)))
                except OSError as exc:
                    failed += 1
                    worker.line(_('{name}: FAILED - {error}').format(name=self.shown_path(original), error=exc))
                worker.progress(done, len(backups))
            for line in restore_summary(restored, failed, worker.stopped):
                worker.line(line)
            worker.line('')
            worker.line(_('Press ANALYSE to check the artwork again.'))
            wx.CallAfter(self.on_analysed, None)    # The analysis is out of date now

        self.run_job(job, _('Restoring the artwork...'))

    # ------------------------------------------------------------------------------------------------------------------
    # Save the messages shown to a text file
    def on_save(self, _event):
        file_dialog = wx.FileDialog(self, _('Output path'), '', 'artwork_layout_fixer.txt',
                                    wildcard='TXT files (*.txt)|*.txt|All files (*.*)|*.*',
                                    style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT)
        if file_dialog.ShowModal() == wx.ID_OK:
            path = file_dialog.GetPath()
            if not os.path.splitext(path)[1]:
                path += '.txt'
            try:
                with open(path, 'w', encoding='utf-8') as fp:
                    fp.write(self.log.GetValue())
                wx.MessageBox(_('Results written to file'), _('File Written'), wx.OK | wx.ICON_INFORMATION)
            except OSError:
                wx.MessageBox(_('Unable to save file to location.  Check permissions.'), _('File Write Error'),
                              wx.OK | wx.ICON_ERROR)
        file_dialog.Destroy()
        self.repaint_buttons()

    # ------------------------------------------------------------------------------------------------------------------
    def on_stop(self, _event):
        if self.worker:
            self.worker.stop()
        self.stop_button.Disable()

    # ------------------------------------------------------------------------------------------------------------------
    # Capture a key event on the panel and look for the escape key to close the window
    def on_key_up(self, event):
        if event.GetKeyCode() == wx.WXK_ESCAPE:
            self.Close()
            return
        event.Skip()

    # ------------------------------------------------------------------------------------------------------------------
    # Handle the close event: stop any running job and give the main window back the focus.  A file being written
    # when the job stops is either fully updated or untouched (see _replace_file).
    def on_close(self, _event):
        self.closing = True
        if self.worker:
            self.worker.stop()
        if LayoutFixerFrame._open_window is self:
            LayoutFixerFrame._open_window = None
        parent = self.GetParent()
        if parent and hasattr(parent, 'list'):  # Following will only be called if this window is running as a child
            parent.list.SetFocus()
        self.Destroy()


# ----------------------------------------------------------------------------------------------------------------------
def run_layout_fixer_gui(art_folders: list):
    app = wx.App()
    LayoutFixerFrame.open(art_folders)
    app.MainLoop()


if __name__ == '__main__':
    run_layout_fixer_gui(sys.argv[1:])     # The artwork folders to check
