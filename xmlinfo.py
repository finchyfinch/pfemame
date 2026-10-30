#!/usr/bin/env python3

# ----------------------------------------------------------------------------------------------------------------------
# xmlinfo.py
#
"""
Looks up the short name information for the selected system program in the XML file data (MAME's HASH files).
It looks for file size and hash info and compares against the file found.  The comparison is shown as a pop-up,
together with the other files of the same software (e.g. side B of a two sided cassette).
"""
# Import python & wxPython modules
import hashlib
import html
import os
import threading
import zlib
from dataclasses import dataclass, field

import wx
import wx.html

import functions
import software_lists

_ = functions.set_up_language()

OK_COLOUR = '#90ee90'          # Background of a matching value
OK_TEXT_COLOUR = '#3cb043'     # Text saying something matched (readable on light and dark backgrounds)
NOT_OK_COLOUR = 'red'

# File check results
MATCH = 'match'
WRONG_SIZE = 'wrong size'
WRONG_CHECKSUM = 'wrong checksum'
MISSING = 'missing'
NOT_CHECKED = 'not checked'     # Disks (CHDs) and files with no known good dump


# ----------------------------------------------------------------------------------------------------------------------
# Checking (no wx)
@dataclass
class FileHashes:
    size: str
    crc: str
    sha1: str


@dataclass
class FileCheck:
    expected: software_lists.SoftwareFile
    path: str = ''                          # The file that was checked ('' if not found)
    actual: FileHashes | None = None
    result: str = MISSING


@dataclass
class XmlReport:
    entry: software_lists.SoftwareEntry
    program_path: str                       # Where the selected program file was found
    program: FileCheck                      # The selected program file against its best matching HASH file entry
    files: list = field(default_factory=list)   # A FileCheck for every file of the software


def file_hashes(path: str) -> FileHashes:
    """Size, CRC32 and SHA1 of a file, reading it once in chunks."""
    crc = 0
    sha1 = hashlib.sha1()
    size = 0
    with open(path, 'rb') as handle:
        while chunk := handle.read(1024 * 1024):
            crc = zlib.crc32(chunk, crc)
            sha1.update(chunk)
            size += len(chunk)
    return FileHashes(str(size), f'{crc & 0xFFFFFFFF:08x}', sha1.hexdigest())


def compare(expected: software_lists.SoftwareFile, actual: FileHashes) -> str:
    if expected.is_disk or expected.status == 'nodump':
        return NOT_CHECKED
    if expected.size != actual.size:
        return WRONG_SIZE
    if expected.crc != actual.crc or (expected.sha1 and expected.sha1 != actual.sha1):
        return WRONG_CHECKSUM
    return MATCH


def program_folders(rom_folders: list, list_names: list, short_name: str) -> list:
    """The folders a system program can be in, in search order: <rom folder>/<list> and <rom folder>/<list>/<short
    name> for each ROM folder (the same places pfeMAME looks when running the program)."""
    folders = []
    for rom_folder in rom_folders:
        for list_name in list_names:
            for folder in (os.path.join(rom_folder, list_name), os.path.join(rom_folder, list_name, short_name)):
                if folder not in folders:
                    folders.append(folder)
    return folders


def find_file(folders: list, file_name: str) -> str:
    """The first folder/file_name that exists, or ''."""
    for folder in folders:
        path = os.path.join(folder, file_name)
        if os.path.isfile(path):
            return path
    return ''


def best_match(files: list, file_name: str, actual: FileHashes) -> software_lists.SoftwareFile | None:
    """The HASH file entry the selected file should be compared with: the one with the same name, else the one
    with the same checksum, else the same size, else the first one."""
    roms = [file for file in files if not file.is_disk]
    for test in (lambda f: f.name.lower() == file_name.lower(),
                 lambda f: f.crc == actual.crc,
                 lambda f: f.size == actual.size):
        for rom in roms:
            if test(rom):
                return rom
    return roms[0] if roms else None


def check_software(entry: software_lists.SoftwareEntry, program_path: str) -> XmlReport | None:
    """Check the selected program file, and each of the software's other files found next to it.
    None if the software has no files that can be compared (e.g. it is only a disk image)."""
    actual = file_hashes(program_path)
    expected = best_match(entry.files, os.path.basename(program_path), actual)
    if expected is None:
        return None
    program = FileCheck(expected, program_path, actual, compare(expected, actual))

    folder = os.path.dirname(program_path)
    checks = []
    for file in entry.files:
        if file is expected:
            checks.append(program)
            continue
        if file.is_disk:                    # CHDs are usually kept in a folder named after the software
            path = find_file([os.path.join(folder, entry.software.name), folder], file.name + '.chd')
        else:
            path = os.path.join(folder, file.name)
        if not os.path.isfile(path):
            checks.append(FileCheck(file))
        elif file.is_disk or file.status == 'nodump':
            checks.append(FileCheck(file, path, None, NOT_CHECKED))
        else:
            hashes = file_hashes(path)
            checks.append(FileCheck(file, path, hashes, compare(file, hashes)))
    return XmlReport(entry, program_path, program, checks)


def result_text(check: FileCheck) -> str:
    text = {MATCH: _('OK'),
            WRONG_SIZE: _('Wrong size'),
            WRONG_CHECKSUM: _('Wrong checksum'),
            MISSING: _('Not found'),
            NOT_CHECKED: _('Not checked')}[check.result]
    if check.expected.status == 'baddump':
        text += ' ' + _('(known bad dump)')
    elif check.expected.status == 'nodump':
        text += ' ' + _('(no good dump known)')
    elif check.expected.is_disk:
        text += ' ' + _('(disk image)')
    return text


def info_rows(system_name: str, system: str, program_file: str, short_name: str,
              report: XmlReport | None = None) -> list:
    """(label, value) pairs describing the program and the software it was matched to."""
    rows = [(_('System:'), f'{system_name} ({system})'),
            (_('Program file:'), program_file),
            (_('Short name:'), short_name)]
    if report:
        software = report.entry.software
        rows += [(_('Software:'), software.description),
                 (_('Year / Publisher:'), ' / '.join(value for value in (software.year, software.publisher) if value)),
                 (_('Software list:'), report.entry.list_name),
                 (_('Found at:'), report.program_path)]
    return rows


def render_html(rows: list, report: XmlReport | None, message: str, text_colour: str, background_colour: str) -> str:
    """The html shown in the window."""
    def esc(value):
        return html.escape(str(value)) if value else '&nbsp;'

    def actual_cell(expected, actual, checked):
        colour = OK_COLOUR if expected == actual or not checked else NOT_OK_COLOUR
        return f'<td bgcolor="{colour}"><font color="black">{esc(actual)}</font></td>'

    parts = [f'<html><body bgcolor="{background_colour}"><font color="{text_colour}">',
             '<table border="0" cellspacing="0" cellpadding="4">']
    parts += [f'<tr><td nowrap><b>{esc(label)}</b></td><td colspan="2">{esc(value)}</td></tr>'
              for label, value in rows]
    parts.append('<tr><td colspan="3"><hr></td></tr>')

    if message:
        parts.append(f'<tr><td colspan="3"><font color="{NOT_OK_COLOUR}"><b>{esc(message)}</b></font></td></tr>')

    if report:
        program = report.program
        expected, actual = program.expected, program.actual
        checked = program.result != NOT_CHECKED
        if expected.name.lower() != os.path.basename(report.program_path).lower():
            parts.append(f'<tr><td nowrap><b>{esc(_("Compared with:"))}</b></td><td colspan="2">'
                         f'{esc(expected.name)}</td></tr>')
        parts.append(f'<tr><td></td><td><b><u>{esc(_("Expected"))}</u></b></td>'
                     f'<td><b><u>{esc(_("Actual"))}</u></b></td></tr>')
        for label, wanted, got in ((_('File size:'), expected.size, actual.size),
                                   (_('CRC:'), expected.crc, actual.crc),
                                   (_('SHA1:'), expected.sha1, actual.sha1)):
            parts.append(f'<tr><td nowrap><b>{esc(label)}</b></td><td>{esc(wanted)}</td>'
                         f'{actual_cell(wanted, got, checked)}</tr>')
        parts.append(f'<tr><td nowrap><b>{esc(_("Result:"))}</b></td><td colspan="2">'
                     f'<font color="{OK_TEXT_COLOUR if program.result == MATCH else NOT_OK_COLOUR}">'
                     f'<b>{esc(result_text(program))}</b></font></td></tr>')
        parts.append('</table>')

        if len(report.files) > 1:
            parts.append(f'<p><b>{esc(_("Files in this software:"))}</b></p>'
                         '<table border="0" cellspacing="0" cellpadding="4">'
                         f'<tr><td><b><u>{esc(_("Name"))}</u></b></td><td><b><u>{esc(_("Size"))}</u></b></td>'
                         f'<td><b><u>{esc(_("CRC"))}</u></b></td><td><b><u>{esc(_("Status"))}</u></b></td></tr>')
            for check in report.files:
                colour = OK_TEXT_COLOUR if check.result == MATCH else text_colour if check.result == NOT_CHECKED \
                    else NOT_OK_COLOUR
                name = esc(check.expected.name)
                if check is program:
                    name = f'<b>{name}</b> {esc(_("(selected)"))}'
                parts.append(f'<tr><td nowrap>{name}</td><td>{esc(check.expected.size)}</td>'
                             f'<td>{esc(check.expected.crc)}</td>'
                             f'<td nowrap><font color="{colour}">{esc(result_text(check))}</font></td></tr>')
            parts.append('</table>')
    else:
        parts.append('</table>')

    parts.append('</font></body></html>')
    return ''.join(parts)


def render_text(rows: list, report: XmlReport | None, message: str) -> str:
    """Plain text version of the window contents (for the clipboard)."""
    lines = [f'{label} {value}' for label, value in rows]
    if message:
        lines += ['', message]
    if report:
        program = report.program
        lines += ['',
                  f'{_("Compared with:")} {program.expected.name}',
                  f'{_("File size:")} {_("expected")} {program.expected.size}, {_("actual")} {program.actual.size}',
                  f'{_("CRC:")} {_("expected")} {program.expected.crc}, {_("actual")} {program.actual.crc}',
                  f'{_("SHA1:")} {_("expected")} {program.expected.sha1}, {_("actual")} {program.actual.sha1}',
                  f'{_("Result:")} {result_text(program)}']
        if len(report.files) > 1:
            lines += ['', _('Files in this software:')]
            lines += [f'  {check.expected.name}  {check.expected.size}  {check.expected.crc}  {result_text(check)}'
                      + (f'  {_("(selected)")}' if check is program else '') for check in report.files]
    return '\n'.join(lines) + '\n'


def analyse(path_executable: str, system: str, short_name: str, program_file: str, rom_folders: list,
            system_folder_name: str = '') -> tuple:
    """Look the program up in the system's software lists and check it.  Returns (report, message): report is None
    and message says why if it couldn't be checked."""
    entries = software_lists.load_software(path_executable, system, short_name)
    if not entries:
        return None, _('There is no software called {software} in the software lists of {system}.').format(
            software=short_name, system=system)

    # The same short name can be in more than one of the system's lists - use the one the program came from
    entries.sort(key=lambda e: e.list_name != system_folder_name)
    list_names = [entry.list_name for entry in entries]
    if system_folder_name and system_folder_name not in list_names:
        list_names.append(system_folder_name)

    folders = program_folders(rom_folders, list_names, short_name)
    path = find_file(folders, program_file)
    if not path:
        return None, _('Unable to find {file_name} in any of these folders: {folders}').format(
            file_name=program_file, folders='; '.join(folders))

    entry = next((e for e in entries if os.path.dirname(path) in program_folders(rom_folders, [e.list_name],
                                                                                    short_name)), entries[0])
    report = check_software(entry, path)
    if report is None:
        return None, _('{} has no files that can be compared (it may be a disk image).').format(short_name)
    return report, ''


def rgb_to_hex(rgb) -> str:
    return '#{:02x}{:02x}{:02x}'.format(*tuple(rgb)[:3])


# ----------------------------------------------------------------------------------------------------------------------
class XMLInfo(wx.Frame):
    def __init__(self, rom_file_name, rom_name, system_file_name, short_name, path_executable, folder_systems,
                 system_folder_name=''):
        style = wx.SYSTEM_MENU | wx.CAPTION | wx.CLOSE_BOX | wx.CLIP_CHILDREN | wx.STAY_ON_TOP
        super().__init__(wx.GetApp().TopWindow, title=_('XML Information - {}').format(rom_name),
                         style=style)

        self.rom_file_name = rom_file_name
        self.rom_name = rom_name
        self.system_file_name = system_file_name
        self.short_name = short_name
        self.path_executable = path_executable
        self.system_folder_name = system_folder_name
        # The ROM folders setting can hold several ';' separated (and relative) folders
        self.rom_folders = functions.split_mame_paths(folder_systems, path_executable)
        self.text = ''

        # Check the inputs before taking control from the main window
        if not self.validate_inputs():
            self.Destroy()
            return

        self.setup_colors()
        self.setup_ui()
        threading.Thread(target=self.process_rom_info_thread, daemon=True).start()

    def validate_inputs(self):
        if not os.path.exists(self.path_executable):
            functions.show_error_dialog(self.GetParent(), _('Unable to find the MAME executable path.'), _('ERROR'))
            return False

        if not self.short_name:
            functions.show_information_dialog(self.GetParent(), _('This program does not exist in an XML HASH file.'),
                                              _('Information'))
            return False

        return True

    def setup_colors(self):
        self.application_colors = functions.get_application_colors()
        self.text_color = self.application_colors['text']
        self.text_color_html = rgb_to_hex(self.text_color)
        self.background_color = self.application_colors['window_background']
        self.background_color_html = rgb_to_hex(self.background_color)

    def setup_ui(self):
        self.SetIcon(wx.Icon(os.path.join(functions.path_to_me(), 'images', 'pfemame.ico'), wx.BITMAP_TYPE_ICO))
        if self.GetParent():
            self.CenterOnParent()
            self.GetParent().Disable()

        self.Bind(wx.EVT_CLOSE, self.on_close)
        self.Bind(wx.EVT_CHAR_HOOK, self.on_key_up)

        panel = wx.Panel(self)
        panel.SetFocus()

        # A loading panel shown while the files are checked
        self.loading_panel = wx.Panel(panel, size=wx.Size(760, 460))
        self.loading_panel.SetBackgroundColour(self.background_color)

        loading_sizer = wx.BoxSizer(wx.VERTICAL)
        loading_text = wx.StaticText(self.loading_panel, label=_('Analysing...'))
        loading_text.SetForegroundColour(self.text_color)
        font = loading_text.GetFont()
        font.SetPointSize(12)
        loading_text.SetFont(font)
        loading_sizer.Add(loading_text, 1, wx.ALIGN_CENTER)
        self.loading_panel.SetSizer(loading_sizer)

        self.htmlControl = wx.html.HtmlWindow(panel, size=wx.Size(760, 460))
        self.htmlControl.SetBackgroundColour(self.background_color)
        self.htmlControl.Hide()  # Hide initially

        self.copy_button = functions.build_one_button(panel, _('COPY TO CLIPBOARD'), self.on_copy)
        self.copy_button.Disable()
        ok_button = functions.build_one_button(panel, _('OK'), self.on_close)

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self.loading_panel, 0, wx.ALL | wx.EXPAND, 2)
        sizer.Add(self.htmlControl, 0, wx.ALL | wx.EXPAND, 2)
        sizer.Add(wx.StaticLine(panel), flag=wx.EXPAND | wx.BOTTOM, border=1)
        button_sizer = wx.BoxSizer(wx.HORIZONTAL)
        button_sizer.Add(self.copy_button, 0, wx.ALL, 2)
        button_sizer.Add(ok_button, 0, wx.ALL, 2)
        sizer.Add(button_sizer, 0, wx.ALL | wx.ALIGN_RIGHT, 2)

        panel.SetSizer(sizer)
        sizer.Fit(self)
        sizer.Layout()
        self.SetForegroundColour(self.text_color)
        self.SetBackgroundColour(self.background_color)
        self.Centre()
        self.Show()

    def process_rom_info_thread(self):
        """Background thread function - no GUI operations here!"""
        try:
            report, message = analyse(self.path_executable, self.rom_file_name, self.short_name,
                                      self.system_file_name, self.rom_folders, self.system_folder_name)
        except Exception as e:  # e.g. MAME couldn't be run, or the file couldn't be read
            report, message = None, _('Error: {}').format(e)
        wx.CallAfter(self.on_processing_complete, report, message)

    def on_processing_complete(self, report, message):
        """Called in main thread when processing is complete"""
        if not self:  # The window was closed while the files were being checked
            return
        rows = info_rows(self.rom_name, self.rom_file_name, self.system_file_name, self.short_name, report)
        self.text = render_text(rows, report, message)
        self.loading_panel.Hide()
        self.htmlControl.Show()
        self.htmlControl.SetPage(render_html(rows, report, message, self.text_color_html,
                                             self.background_color_html))
        self.copy_button.Enable()
        self.Layout()

    def on_copy(self, _event=None):
        data_object = wx.TextDataObject()
        data_object.SetText(self.text)
        if wx.TheClipboard.Open():
            wx.TheClipboard.SetData(data_object)
            wx.TheClipboard.Close()
        else:
            wx.MessageBox(_('Unable to open the clipboard'), _('ERROR'))

    def on_close(self, _event=None):
        # The checking thread is left to finish on its own - its result is ignored once the window has gone
        parent = self.GetParent()
        if parent:
            parent.Enable()
            if getattr(parent, 'list', None):
                parent.list.SetFocus()
        self.Destroy()

    def on_key_up(self, event):
        if event.GetKeyCode() == wx.WXK_ESCAPE:
            self.on_close()
        event.Skip()


if __name__ == '__main__':
    app = wx.App()
    # This data is just used for testing purposes
    frame = XMLInfo('spectrum',
                    'ZX Spectrum',
                    'dizzy - the ultimate cartoon adventure.tzx',
                    'dizzya',
                    'd:/mame/mame.exe',
                    'd:/Mame/roms')
    app.MainLoop()
