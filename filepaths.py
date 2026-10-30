#!/usr/bin/env python3

# ----------------------------------------------------------------------------------------------------------------------
# filepaths.py

"""
This is a child window used to select the file / folder path for various
aspects of both the MAME executable and the pfeMAME application.
"""

# Import python & wxPython modules
import wx
import wx.grid
import os
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path

# Import my own modules
import busy_window
import functions
from functions import show_error_dialog, show_information_dialog
import iniFile
from pubsub import pub

# This is the lookup folders list.  It is case-insensitive as the code manages that now.
MAME_FOLDERS = [('file', 'mame_executable', 'mame64.exe', 'mame.exe', 'mame'),
                        ('file', 'history_dat', 'history.xml', 'history.dat'),
                        ('file', 'mameinfo_dat', 'mameinfo.dat'),
                        ('file', 'catver_ini', 'catver.ini'),
                        ('folder', 'pcbs_directory', 'pcb', 'pcbs'),
                        ('folder', 'bosses_directory', 'bosses'),
                        ('folder', 'cabinets_directory', 'cabinets', 'cabs'),
                        ('folder', 'cpanels_directory', 'cpanels', 'cpanel'),
                        ('folder', 'flyers_directory', 'flyer', 'flyers'),
                        ('folder', 'titles_directory', 'titles'),
                        ('folder', 'ends_directory', 'ends'),
                        ('folder', 'marquees_directory', 'marquees'),
                        ('folder', 'snapshot_directory', 'snap', 'snaps'),
                        ('folder', 'icons', 'icon', 'icons'),
                        ('folder', 'rompath', 'rom', 'roms'),
                        ('folder', 'video', 'video', 'videos', 'movie', 'movies'),
                        ('folder', 'samplepath', 'sample', 'samples'),
                        ('folder', 'artpath', 'art', 'artwork'),
                        ('folder', 'ctrlrpath', 'ctrlr', 'controller'),
                        ('folder', 'inipath', 'ini'),
                        ('folder', 'cfg_directory', 'config', 'configs', 'configuration', 'cfg'),
                        ('folder', 'nvram_directory', 'nvram'),
                        ('folder', 'diff_directory', 'diff', 'difference'),
                        ('folder', 'input_directory', 'input', 'inputs', 'inp'),
                        ('folder', 'state_directory', 'state', 'states', 'sta'),
                        ('folder', 'cheatpath', 'cheat', 'cheats'),
                        ('folder', 'hashpath', 'hash'),
                        ('folder', 'pluginspath', 'plugin', 'plugins'),
                        ('folder', 'input_mapping', 'mapping', 'mappings')]

REQUIRED_PATHS = {'mame_ini', 'mame_executable', 'catver_ini', 'history_dat'}  # Red when empty - the rest are optional
SIDE_PANEL_WIDTH = 300      # The instructions / MAME version panel beside the grid
MAME_TIMEOUT = 30           # Seconds to wait for MAME to answer -showconfig / -createconfig


def _build_dir_lookup(location: str) -> dict:
    """Scan a directory once into a case-insensitive {name: Path} dict."""
    result = {}
    try:
        for item in Path(location).iterdir():
            result[item.name.lower()] = item
    except (OSError, PermissionError):
        pass
    return result


def _contrasting_colour(bg: wx.Colour) -> wx.Colour:
    """Return black or white, whichever contrasts better against bg."""
    luminance = 0.299 * bg.Red() + 0.587 * bg.Green() + 0.114 * bg.Blue()
    return wx.BLACK if luminance > 128 else wx.WHITE


# ----------------------------------------------------------------------------------------------------------------------
@dataclass
class PathRow:
    label:       str   # col 0 — visible
    path:        str   # col 1 — visible
    add_flag:    str   # '' or 'Add' (an entry that can hold more than one path)
    wildcard:    str
    ini_key:     str
    data_type:   str
    ini_file:    str
    problem:     str = ''   # Why the path is shown in red ('' = fine) - also the row's tooltip


# ----------------------------------------------------------------------------------------------------------------------
class PathTableBase(wx.grid.GridTableBase):
    """GridTableBase that stores PathRow objects and drives a 2-column grid."""

    def __init__(self, app_colors: dict):
        super().__init__()
        self._rows: list = []
        self._app_colors = app_colors

        bg_even    = wx.Colour(app_colors['row_alt_2'])
        bg_odd     = wx.Colour(app_colors['row_alt_1'])
        bg_invalid = wx.RED

        self._attr_even = wx.grid.GridCellAttr()
        self._attr_even.SetBackgroundColour(bg_even)
        self._attr_even.SetTextColour(_contrasting_colour(bg_even))

        self._attr_odd = wx.grid.GridCellAttr()
        self._attr_odd.SetBackgroundColour(bg_odd)
        self._attr_odd.SetTextColour(_contrasting_colour(bg_odd))

        self._attr_invalid = wx.grid.GridCellAttr()
        self._attr_invalid.SetBackgroundColour(bg_invalid)
        self._attr_invalid.SetTextColour(_contrasting_colour(bg_invalid))

    # --- GridTableBase required overrides ---

    def GetNumberRows(self) -> int:
        return len(self._rows)

    def GetNumberCols(self) -> int:
        return 2

    def GetValue(self, row: int, col: int) -> str:
        if not (0 <= row < len(self._rows)):
            return ''
        if col == 0:
            return self._rows[row].label
        return self._rows[row].path or _('double click to set')     # Unset paths are stored as '', only shown

    def SetValue(self, row: int, col: int, value: str):
        if col == 1 and 0 <= row < len(self._rows):
            self._rows[row].path = value

    def GetColLabelValue(self, col: int) -> str:
        return (_('Name'), _('Path'))[col] if 0 <= col < 2 else ''

    def IsEmptyCell(self, row: int, col: int) -> bool:
        return False

    def GetAttr(self, row: int, col: int, kind):
        if 0 <= row < len(self._rows) and self._rows[row].problem:
            attr = self._attr_invalid
        elif row % 2 == 0:
            attr = self._attr_even
        else:
            attr = self._attr_odd
        attr.IncRef()       # The grid releases the attribute after use, so share one rather than copying it
        return attr

    # --- Helper methods (not part of GridTableBase protocol) ---

    def get_row(self, row: int) -> PathRow:
        return self._rows[row]

    def set_path(self, row: int, value: str):
        if 0 <= row < len(self._rows):
            self._rows[row].path = value

    def insert_row(self, row: int, data: PathRow):
        self._rows.insert(row, data)

    def delete_row(self, row: int):
        del self._rows[row]

    def swap_rows(self, first: int, second: int):
        self._rows[first], self._rows[second] = self._rows[second], self._rows[first]

    def find_path_by_ini_key(self, key: str) -> str:
        for r in self._rows:
            if r.ini_key == key:
                return r.path
        return ''

    def update_path_by_ini_key(self, key: str, value: str):
        for r in self._rows:
            if r.ini_key == key:
                r.path = value

    def set_rows(self, rows: list):
        self._rows = rows

    def get_all_rows(self) -> list:
        return list(self._rows)

    def row_count(self) -> int:
        return len(self._rows)


# ----------------------------------------------------------------------------------------------------------------------
class _PathDropTarget(wx.FileDropTarget):
    """Lets a file or folder be dragged from the desktop's file manager onto a row to set its path."""

    def __init__(self, panel):
        super().__init__()
        self.panel = panel

    def OnDropFiles(self, x, y, filenames):
        return self.panel.on_drop_files(x, y, filenames)


# ----------------------------------------------------------------------------------------------------------------------
# Thin wrapper frame for running FilePaths standalone (debug / testing only).
class WindowFilePaths(wx.Frame):
    def __init__(self, my_logger):
        style = wx.SYSTEM_MENU | wx.CAPTION | wx.CLOSE_BOX | wx.CLIP_CHILDREN | wx.STAY_ON_TOP
        wx.Frame.__init__(self, None, -1, _('Edit File Paths'), wx.DefaultPosition,
                          size=wx.Size(1000, 640), style=style)

        path_to_me = functions.path_to_me()
        self.SetIcon(wx.Icon(os.path.join(path_to_me, 'images', 'pfemame.ico'), wx.BITMAP_TYPE_ICO))

        panel = FilePaths(self, my_logger)
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(panel, 1, wx.EXPAND)
        self.SetSizer(sizer)

        self.Centre()
        self.Show()


# ----------------------------------------------------------------------------------------------------------------------
# Embedded panel version of the File Paths editor, suitable for adding as a notebook tab in the main window.
# All parent communication uses pubsub instead of direct parent references.
class FilePaths(wx.Panel):

    def __init__(self, parent, my_logger):
        super().__init__(parent=parent)

        self.my_logger = my_logger
        self.path_to_me = functions.path_to_me()
        self.application_colors = functions.get_application_colors()

        fonts = functions.get_font_info()
        self.global_font_bold = fonts.global_font_bold
        self.global_font_normal = fonts.global_font_normal
        self.global_font_normal_8 = fonts.global_font_normal_8
        self.global_font_normal_12 = fonts.global_font_normal_12

        self.system = functions.get_platform()
        self.activePath = os.getcwd()     # Where AUTO FIND's folder chooser starts (the last MAME folder chosen)
        self.mame_folders_path = ''

        # Read current INI state
        path_executable = iniFile.read_ini_file('path', 'mame_executable')
        self.path_to_mame_ini_file = iniFile.read_ini_file('path', 'mame_ini')
        self.folders_ini = iniFile.get_from_mameini('inipath', self.path_to_mame_ini_file)

        # Flag: if the exe was blank on first load, a restart is needed after first successful apply
        self._first_run = (path_executable == '')

        self.SetBackgroundColour(self.application_colors['window_background'])

        # ------------------------------------------------------------------------------------------------------------------
        # Build the UI on self (no inner top_panel needed — self IS the panel)
        sizer_buttons = wx.BoxSizer(wx.HORIZONTAL)
        sizer_horizontal = wx.BoxSizer(wx.HORIZONTAL)
        sizer_vertical = wx.BoxSizer(wx.VERTICAL)

        # Create the table and grid
        self.table = PathTableBase(self.application_colors)
        self.list_control = wx.grid.Grid(self, -1)
        self.list_control.SetTable(self.table, takeOwnership=False)

        # Grid appearance — matches original ULC look
        self.list_control.SetSelectionMode(wx.grid.Grid.GridSelectRows)
        self.list_control.EnableEditing(False)
        self.list_control.EnableDragRowSize(False)
        self.list_control.EnableDragColMove(False)
        self.list_control.EnableDragColSize(False)
        self.list_control.SetRowLabelSize(0)         # hide row-number gutter
        self.list_control.SetDefaultCellFont(self.global_font_normal)
        self.list_control.SetColSize(0, 200)
        self.list_control.SetColSize(1, 400)

        # Column header styling (replaces UltimateHeaderRenderer)
        label_font = wx.SystemSettings.GetFont(wx.SYS_DEFAULT_GUI_FONT)
        label_font.SetWeight(wx.BOLD)
        label_font.SetPointSize(10)
        self.list_control.SetLabelFont(label_font)
        self.list_control.SetLabelBackgroundColour(wx.Colour(self.application_colors['control_bar']))
        self.list_control.SetLabelTextColour(wx.Colour(self.application_colors['text']))
        functions.style_grid_column_header(self.list_control, self.application_colors)

        # Event bindings
        self.list_control.Bind(wx.grid.EVT_GRID_CELL_LEFT_DCLICK, self.on_double_click_list)
        self.list_control.Bind(wx.grid.EVT_GRID_CELL_RIGHT_CLICK, self.on_right_click_list)
        self.list_control.Bind(wx.EVT_SIZE, self._on_grid_size)
        self._tooltip_row = -1
        self.list_control.GetGridWindow().Bind(wx.EVT_MOTION, self._on_grid_motion)
        self.list_control.GetGridWindow().SetDropTarget(_PathDropTarget(self))
        # Column drag prevention is handled by EnableDragColSize(False) — no event needed.

        self.build_filepaths_table()
        self.data_changed = False

        # Side info panel
        self.side_panel_text = wx.TextCtrl(
            self,
            value='',
            size=wx.Size(SIDE_PANEL_WIDTH, -1),
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_WORDWRAP | wx.BORDER_NONE
        )
        self.side_panel_text.SetForegroundColour(self.application_colors['text'])
        self.side_panel_text.SetBackgroundColour(self.application_colors['window_background'])

        self.side_panel_text.SetValue(self._first_run_instructions())

        # Which MAME the executable row points at - checked in the background whenever that row changes
        self.mame_version_text = wx.StaticText(self, label='')
        self.mame_version_text.SetFont(self.global_font_bold)
        self.mame_version_text.SetForegroundColour(self.application_colors['text'])
        self._version_for = None            # The executable the shown / pending version belongs to
        self._version_thread = None

        # APPLY / AUTO FIND / MAKE INI run MAME in a worker thread (see run_in_background)
        self.use_background_thread = True   # Tests switch this off to run the work straight away
        self._worker = None
        self._auto_find_cancel = None

        sizer_side = wx.BoxSizer(wx.VERTICAL)
        sizer_side.Add(self.mame_version_text, 0, wx.BOTTOM | wx.EXPAND, 5)
        sizer_side.Add(self.side_panel_text, 1, wx.EXPAND)
        sizer_horizontal.Add(self.list_control, 1, wx.ALL | wx.EXPAND, 0)
        sizer_horizontal.AddSpacer(5)
        sizer_horizontal.Add(sizer_side, 0, wx.ALL | wx.EXPAND, 0)
        sizer_vertical.Add(sizer_horizontal, 1, wx.ALL | wx.EXPAND, 0)

        button_definitions = [
            (_('APPLY'),     self.on_apply,     _('Apply the file path changes')),
            (_('REVERT'),    self.on_revert,    _('Discard any unsaved changes and reload the file paths from the '
                                                  'INI files.')),
            (_('CLEAR ALL'), self.on_clear_all, _('Clear all file & folder path input fields.')),
            (_('AUTO FIND'), self.on_auto_find, _('Search for all file & folder paths automatically.')),
            (_('MAKE INI'),  self.on_make_ini,  _(
                'Create the mame.ini file using the MAME executable - in the folder of the MAME INI File row if it is '
                'set, otherwise in the MAME folder on Windows and macOS, or in ~/.mame on Linux.')),
        ]

        self.apply_button = None
        self.buttons = []
        for label, handler, tooltip in button_definitions:
            btn = functions.build_one_button(self, label, self._then_repaint_buttons(handler), tooltip)
            if handler == self.on_apply:
                self.apply_button = btn
            self.buttons.append(btn)
            sizer_buttons.Add(btn, 0, wx.ALL, 2)

        sizer_vertical.Add(sizer_buttons, 0, wx.ALL | wx.ALIGN_RIGHT)
        sizer_vertical.AddSpacer(5)
        self.SetSizer(sizer_vertical)

        wx.CallAfter(self.check_valid_paths)

    # ------------------------------------------------------------------------------------------------------------------
    def _then_repaint_buttons(self, handler):
        """Wrap a button handler so the buttons are repainted once it (and any dialog it showed) has finished."""
        def run(event):
            try:
                handler(event)
            finally:
                self._repaint_buttons()
        return run

    # ------------------------------------------------------------------------------------------------------------------
    def _repaint_buttons(self):
        """
        The buttons are GenButtons, which draw themselves greyed out while a modal dialog has the window disabled
        and are not redrawn when it is re-enabled - so they stayed grey (until hovered) after e.g. AUTO FIND.  Redraw
        them once the dialog has gone and the window is enabled again.  How this shows up varies by platform, hence
        the CallAfter.
        """
        def repaint():
            if not self:            # The panel may have been destroyed before the deferred call ran
                return
            for button in self.buttons:
                button.Refresh()
                button.Update()

        wx.CallAfter(repaint)

    # ------------------------------------------------------------------------------------------------------------------
    def run_in_background(self, work, then, cancel: threading.Event | None = None):
        """
        Run work(progress) in a worker thread, with the Please Wait window up and this tab disabled, then call
        then(result) back on the GUI thread.  work must only run MAME / look at files - no wx calls - and can call
        progress(text) to show what it is doing.  If cancel is given the Please Wait window has a Cancel button that
        sets it: work should check it between steps, and then() is still called (and can check cancel.is_set()).
        """
        if not self.use_background_thread:
            then(work(lambda text: self.my_logger.info(f'FILEPATHS INFO:  {text}')))
            return

        busy = busy_window.BusyWindow(wx.GetTopLevelParent(self), on_cancel=cancel.set if cancel else None)
        busy.show()
        self.Disable()

        def progress(text: str):
            self.my_logger.info(f'FILEPATHS INFO:  {text}')
            wx.CallAfter(busy.set_message, text)

        def finish(result):
            busy.close()
            if not self:                # The window was closed while MAME was running - nothing left to update
                return
            self.Enable()
            if isinstance(result, Exception):
                show_error_dialog(self, _('Something went wrong:') + f'\n\n{result}', _('ERROR'))
            else:
                then(result)
            self._repaint_buttons()

        def worker():
            result = None
            try:
                result = work(progress)
            except Exception as e:
                result = e
                self.my_logger.exception('FILEPATHS ERROR:  Background task failed')
            finally:
                wx.CallAfter(finish, result)        # Always hand back, so the tab is re-enabled whatever happens

        self._worker = threading.Thread(target=worker, daemon=True)
        self._worker.start()

    # ------------------------------------------------------------------------------------------------------------------
    @staticmethod
    def _first_run_instructions() -> str:
        return _(
            "Instructions\n"
            "-------------------------------\n"
            "You need to set up valid file paths for the files listed on this page."
            "  Critical ones are the MAME executable, catver.ini, and history.xml."
            "  Most of the others are recommended but not critical.\n\n"
            "The application has attempted to find the mame.ini file in its most"
            " likely location - please check this is correct.  You cant just put it"
            " anywhere as MAME needs to find it in very specific locations."
            "  Please read the manual for more information on this.\n\n"
            "Any file paths found in mame.ini have been automatically populated."
            " These may not be correct for a first run, so please review them.\n\n"
            "Setting paths:\n"
            "  - Double-click any row to browse for a file or folder, or drag one onto the row"
            " from your file manager.\n"
            "  - Right-click any row for more options: add an extra path"
            " (for entries that support multiple locations), delete one of them,"
            " move one up or down (MAME searches them in order), clear a path back to empty,"
            " or open its folder.\n"
            "  - A row shown in red has a problem (missing, or required but not set)."
            "  Hover the mouse over it to see why.\n\n"
            "You can also select the AUTO FIND option at the bottom of the window."
            "  It will ask you to select the root MAME folder where your ROMs etc are located"
            ", after which it will try to determine all folder locations and set them"
            " automatically."
        )

    # ------------------------------------------------------------------------------------------------------------------
    # Validate and save all paths, then notify the main app via pubsub
    def on_apply(self, _event):
        path_executable = self.get_path_list_ctrl('mame_executable')
        if path_executable in ('', '.'):
            self._apply_checked(path_executable, (None, ''))
            return
        # Check that it really is MAME before saving anything (in the background - MAME can take a while)
        self.run_in_background(
            lambda progress: self._run_mame(path_executable, '-showconfig',
                                            functions.mame_working_dir(path_executable)),
            lambda result: self._apply_checked(path_executable, result))

    # ------------------------------------------------------------------------------------------------------------------
    def _apply_checked(self, path_executable: str, mame_result: tuple):
        """The rest of APPLY, once MAME has answered -showconfig: save the paths if it really is MAME."""
        result, problem = mame_result
        error = True
        if result is not None:
            if b'CORE CONFIGURATION OPTIONS' in result.stdout:
                error = False
            else:
                self.my_logger.error('FILEPATHS ERROR:  CORE CONFIGURATION OPTIONS not found in the output')

        if error:
            dlg = wx.MessageDialog(
                self,
                _('Not getting the right output from MAME or cannot find the MAME executable.  '
                  'Check that the path is defined correctly.  If the OS is Linux, try running "mame"'
                  ' from the command line.') + (f'\n\n{problem}' if problem else ''),
                _('ERROR'),
                wx.OK | wx.ICON_ERROR
            )
            dlg.ShowModal()
            dlg.Destroy()
            msg = _('FILEPATHS ERROR: Not getting the right output from MAME.  '
                    'Check that the path is defined correctly')
            self.my_logger.error(msg)
            pub.sendMessage('update', msg=msg + '\n')
            return

        # Collect updates from the table in batches per INI file
        mame_ini_updates = []
        ui_ini_updates = []
        pfemame_ini_updates = []

        # Group the rows by entry (a multi-path entry has one row per folder), leaving out unset (empty) rows
        entries = {}
        for r in self.table.get_all_rows():
            _first_row, paths = entries.setdefault(r.ini_key, (r, []))
            if r.path:
                paths.append(r.path)

        for r, paths in entries.values():
            path = ';'.join(paths)
            if r.ini_file == 'mame.ini':
                mame_ini_updates.append([path, r.ini_key, False])
            elif r.ini_file == 'ui.ini':
                ui_ini_updates.append([path, r.ini_key, False])
            else:
                pfemame_ini_updates.append((r.data_type, r.ini_key, path))

        # Save into the mame.ini shown on the MAME INI File row (which may have been changed since loading)
        self.path_to_mame_ini_file = self.get_path_list_ctrl('mame_ini')
        if mame_ini_updates and self.path_to_mame_ini_file.strip() in ('', '.'):
            show_error_dialog(self,
                              _('The path to the mame.ini file is empty, so nothing has been saved.  Set the '
                                'MAME INI File row (or use AUTO FIND or MAKE INI) and then apply again.'),
                              _('ERROR writing to mame.ini file'))
            return

        # ui.ini lives in one of the inipath folders - use the inipath being saved, not the one loaded at start-up
        inipath = next((path for path, key, _convert in mame_ini_updates if key == 'inipath'), self.folders_ini)
        ui_ini_path = functions.find_ui_ini(inipath, path_executable)
        if not ui_ini_path:
            if any(path for path, _key, _convert in ui_ini_updates):
                show_error_dialog(self,
                                  _('None of the INI folders exist, so there is nowhere to save the PCBs, Cabinets, '
                                    'Control Panels, Flyers, Titles, Ends, Marquees and Bosses folders (MAME keeps '
                                    'them in ui.ini).  Nothing has been saved.  Set the INI folder row and then '
                                    'apply again.'),
                                  _('ERROR writing to ui.ini file'))
                return
            ui_ini_updates = []         # Nothing to save to ui.ini anyway

        write_tasks = [
            (
                mame_ini_updates,
                lambda: iniFile.set_to_mameini_bulk(mame_ini_updates, self.path_to_mame_ini_file),
                _('Unable to write to the mame.ini file. The file is most likely read-only.'),
                _('ERROR writing to mame.ini file'),
            ),
            (
                ui_ini_updates,
                lambda: iniFile.set_to_mameini_bulk(ui_ini_updates, ui_ini_path),
                _('Unable to write to the ui.ini file. The file is most likely read-only.'),
                _('ERROR writing to ui.ini file'),
            ),
            (
                pfemame_ini_updates,
                lambda: iniFile.set_ini_file_variables(pfemame_ini_updates),
                _('Unable to write to the pfemame.ini file. The file is most likely read-only.'),
                _('ERROR writing to pfemame.ini file'),
            ),
        ]

        errors = False
        for updates, write_func, msg, title in write_tasks:
            if not updates:
                continue
            try:
                # Failed writes are reported by returning -1 (set_to_mameini_bulk) or False (set_ini_file_variables)
                result = write_func()
                failed = result is False or result == -1     # (Not 'in (-1, False)': 0 == False)
            except OSError:
                failed = True
            if failed:
                errors = True
                self.my_logger.error(f'FILEPATHS ERROR:  {title}')
                show_error_dialog(self, msg, title)

        if not errors:
            self.data_changed = False
            pub.sendMessage('status', msg=_('File paths saved'))
            pub.sendMessage('setup_ini')
            self.check_valid_paths()

            if self._first_run:
                self._first_run = False

            # Ask once, here.  (Setting the main window's restart flag instead asked again on the ROMs tab, and until
            # then closing pfeMAME restarted it.)
            dlg = wx.MessageDialog(
                self,
                _('File paths saved.  Restart pfeMAME now so all the changes take effect?'),
                _('Restart Required'),
                wx.YES_NO | wx.YES_DEFAULT | wx.ICON_QUESTION)
            restart_now = dlg.ShowModal() == wx.ID_YES
            dlg.Destroy()
            pub.sendMessage('refresh_window')
            if restart_now:
                pub.sendMessage('restart_now')
            else:
                pub.sendMessage('status',
                                msg=_('File paths saved - restart pfeMAME for all the changes to take effect'))

    # ------------------------------------------------------------------------------------------------------------------
    def on_revert(self, _event):
        if self.data_changed:
            dlg = wx.MessageDialog(self, _('Are you sure you want to discard all unsaved file path changes?'),
                                   _('Revert file paths'), wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION)
            confirmed = dlg.ShowModal() == wx.ID_YES
            dlg.Destroy()
            if not confirmed:
                return
        self.revert()
        pub.sendMessage('status', msg=_('File paths reloaded'))

    # ------------------------------------------------------------------------------------------------------------------
    def revert(self):
        """Throw away unsaved edits by reloading every row from the INI files on disk."""
        self.path_to_mame_ini_file = iniFile.read_ini_file('path', 'mame_ini')
        self.folders_ini = iniFile.get_from_mameini('inipath', self.path_to_mame_ini_file)
        self.build_filepaths_table()
        self.data_changed = False
        self.check_valid_paths()

    # ------------------------------------------------------------------------------------------------------------------
    def check_valid_paths(self):
        # Reached through wx.CallAfter, so the panel may already be gone by the time it runs.
        if not self:
            return
        for row in self.table.get_all_rows():
            row.problem = self._path_problem(row)
        self.list_control.ForceRefresh()
        self._update_apply_button()
        if self.get_path_list_ctrl('mame_executable') != self._version_for:
            self.refresh_mame_version()
        self._show_problem_tooltip(self._tooltip_row)

    # ------------------------------------------------------------------------------------------------------------------
    def refresh_mame_version(self):
        """Ask the MAME executable on the row for its version, in the background, and show the answer."""
        path_executable = self.get_path_list_ctrl('mame_executable')
        self._version_for = path_executable
        if not path_executable:
            self._show_mame_version(path_executable, '', '')
            return
        self.mame_version_text.SetLabel(_('MAME version:  checking...'))

        def ask_mame():
            version, problem = functions.mame_version(path_executable, MAME_TIMEOUT)
            wx.CallAfter(self._show_mame_version, path_executable, version, problem)
        self._version_thread = threading.Thread(target=ask_mame, daemon=True)
        self._version_thread.start()

    # ------------------------------------------------------------------------------------------------------------------
    def _show_mame_version(self, path_executable: str, version: str, problem: str):
        if not self or path_executable != self._version_for:   # Panel gone, or the executable has changed since
            return
        if version:
            label, colour = _('MAME version:  {}').format(version), self.application_colors['text']
        elif not path_executable:
            label, colour = _('MAME version:  no MAME executable set'), self.application_colors['text']
        else:
            label, colour = _('MAME version:  not working ({})').format(problem), wx.RED
        self.mame_version_text.SetLabel(label)
        self.mame_version_text.SetForegroundColour(colour)
        self.mame_version_text.Wrap(SIDE_PANEL_WIDTH)
        self.Layout()

    # ------------------------------------------------------------------------------------------------------------------
    def _path_problem(self, row: PathRow) -> str:
        """Why this row's path is a problem (shown in red, and as its tooltip), or '' if it is fine."""
        if not row.path:
            return _('Required - pfeMAME needs this to be set.') if row.ini_key in REQUIRED_PATHS else ''
        if row.ini_key == 'mame_executable' and row.path == 'mame':
            return ''       # Run MAME from the system path
        resolved = self._resolve(row)
        wrong_kind = self._wrong_kind(row, resolved)
        if wrong_kind:
            return wrong_kind
        if row.data_type == 'path':
            return '' if os.path.isfile(resolved) else _('File not found:  {}').format(resolved)
        return '' if os.path.isdir(resolved) else _('Folder not found:  {}').format(resolved)

    # ------------------------------------------------------------------------------------------------------------------
    @staticmethod
    def _wrong_kind(row: PathRow, path: str) -> str:
        """Why path can't go in this row because it is a folder where a file is needed (or the other way round)."""
        label = row.label.rstrip(':')
        if row.data_type == 'path' and os.path.isdir(path):
            return _('{} needs a file, not a folder.').format(label)
        if row.data_type != 'path' and os.path.isfile(path):
            return _('{} needs a folder, not a file.').format(label)
        return ''

    # ------------------------------------------------------------------------------------------------------------------
    def _resolve(self, row: PathRow) -> str:
        """The row's path as the program reading it sees it: $VARIABLES and ~ expanded and, for MAME's own paths,
        relative paths taken from the MAME folder."""
        if row.ini_file == 'pfemame.ini':
            return os.path.expanduser(os.path.expandvars(row.path))
        return (functions.split_mame_paths(row.path, self.get_path_list_ctrl('mame_executable')) or [row.path])[0]

    # ------------------------------------------------------------------------------------------------------------------
    def _browse_start(self, row: PathRow) -> tuple[str, str]:
        """
        Where the browse dialog for a row opens, as (folder, file to pre-select): at the row's own path if it exists,
        otherwise in the MAME folder, then the mame.ini folder, then pfeMAME's folder.
        """
        if row.path:
            resolved = os.path.abspath(self._resolve(row))
            if os.path.isfile(resolved):
                return os.path.dirname(resolved), os.path.basename(resolved)
            if os.path.isdir(resolved):
                return resolved, ''
        for folder in (functions.mame_working_dir(self.get_path_list_ctrl('mame_executable')),
                       os.path.dirname(self.path_to_mame_ini_file)):
            if folder and os.path.isdir(folder):
                return folder, ''
        return os.getcwd(), ''

    # ------------------------------------------------------------------------------------------------------------------
    def _on_grid_motion(self, event):
        event.Skip()
        _x, y = self.list_control.CalcUnscrolledPosition(event.GetPosition())
        self._show_problem_tooltip(self.list_control.YToRow(y))

    # ------------------------------------------------------------------------------------------------------------------
    def _show_problem_tooltip(self, row: int):
        """Show the red row's problem as the tooltip while the mouse is over it."""
        self._tooltip_row = row
        tip = self.table.get_row(row).problem if 0 <= row < self.table.row_count() else ''
        window = self.list_control.GetGridWindow()
        if tip != window.GetToolTipText():
            if tip:
                window.SetToolTip(tip)
            else:
                window.UnsetToolTip()

    # ------------------------------------------------------------------------------------------------------------------
    def _update_apply_button(self):
        if not self._first_run or self.apply_button is None:
            return
        exe = self.get_path_list_ctrl('mame_executable')
        # 'mame' is the run-from-PATH fallback (used on macOS/Linux when the
        # executable lives on the system path rather than in the MAME folder).
        # Treat it as valid so Apply is not greyed out, consistent with
        # check_valid_paths().
        valid = exe not in ('', '.') and (os.path.isfile(exe) or exe == 'mame')
        self.apply_button.Enable(valid)

    # ------------------------------------------------------------------------------------------------------------------
    def build_filepaths_table(self, keep_pfemame_rows: bool = False):
        """
        Fill the table from the INI files.  With keep_pfemame_rows, pfeMAME's own rows (executable, history, video,
        etc.) keep their current - possibly unsaved - values and only the mame.ini / ui.ini rows are reloaded.
        """
        kept = {}
        if keep_pfemame_rows:
            for row in self.table.get_all_rows():
                if row.ini_file == 'pfemame.ini':
                    kept.setdefault(row.ini_key, []).append(row.path)

        @dataclass
        class PathEntry:
            label: str
            ini_key: str
            ini_file: str
            data_type: str
            path_type: str
            file_filter: str

        def ini_paths(entry: PathEntry, values: list) -> list:
            """The rows for an entry: one per path, or a single unset ('') row if there are none."""
            paths = [value.strip() for value in values if value.strip()]
            if entry.ini_file == 'pfemame.ini':
                # In mame.ini / ui.ini '.' is MAME's own folder, but in pfemame.ini it was only ever written by the
                # old Clear, meaning 'not set'
                paths = [path for path in paths if path != '.']
            return paths or ['']

        path_executable = (kept['mame_executable'][0] if 'mame_executable' in kept
                           else iniFile.read_ini_file('path', 'mame_executable'))
        ui_ini_path = functions.find_ui_ini(self.folders_ini, path_executable)

        def get_ini_value(entry: PathEntry, base_ini_path: str) -> list:
            match entry.ini_file:
                case 'mame.ini':
                    return iniFile.get_from_mameini(entry.ini_key, base_ini_path).split(';')
                case 'ui.ini':
                    return iniFile.get_from_mameini(entry.ini_key, ui_ini_path).split(';')
                case _ if entry.ini_key in kept:
                    return kept[entry.ini_key]
                case _:
                    return [iniFile.read_ini_file(entry.data_type, entry.ini_key)]

        entries = [
            PathEntry(_('MAME INI File:'),        'mame_ini',          'pfemame.ini', 'path',    'single',   '*.ini'),
            PathEntry(_('MAME Executable:'),       'mame_executable',   'pfemame.ini', 'path',    'single',   '*.exe'),
            PathEntry(_('History file:'),          'history_dat',       'pfemame.ini', 'path',    'single',   '*.xml;*.dat'),
            PathEntry(_('MAME info file:'),        'mameinfo_dat',      'pfemame.ini', 'path',    'single',   '*.dat'),
            PathEntry(_('catver.ini file:'),       'catver_ini',        'pfemame.ini', 'path',    'single',   '*.ini'),
            PathEntry(_('Roms folder:'),           'rompath',           'mame.ini',    'folders', 'multiple', ''),
            PathEntry(_('Video folder:'),          'video',             'pfemame.ini', 'folders', 'single',   ''),
            PathEntry(_('Samples folder:'),        'samplepath',        'mame.ini',    'folders', 'multiple', ''),
            PathEntry(_('Softwarelist HASH folder:'), 'hashpath',          'mame.ini',    'folders', 'multiple', ''),
            PathEntry(_('Plugins folder:'),        'pluginspath',       'mame.ini',    'folders', 'multiple', ''),
            PathEntry(_('Artwork folder:'),        'artpath',           'mame.ini',    'folders', 'multiple', ''),
            PathEntry(_('Icon folder:'),           'icons',             'pfemame.ini', 'folders', 'single',   ''),
            PathEntry(_('Snap folder:'),           'snapshot_directory','mame.ini',    'folders', 'single',   ''),
            PathEntry(_('PCBs folder:'),           'pcbs_directory',    'ui.ini',      'folders', 'single',   ''),
            PathEntry(_('Cabinets folder:'),       'cabinets_directory','ui.ini',      'folders', 'single',   ''),
            PathEntry(_('Control Panels folder:'), 'cpanels_directory', 'ui.ini',      'folders', 'single',   ''),
            PathEntry(_('Flyers folder:'),         'flyers_directory',  'ui.ini',      'folders', 'single',   ''),
            PathEntry(_('Titles folder:'),         'titles_directory',  'ui.ini',      'folders', 'single',   ''),
            PathEntry(_('Ends folder:'),           'ends_directory',    'ui.ini',      'folders', 'single',   ''),
            PathEntry(_('Marquees folder:'),       'marquees_directory','ui.ini',      'folders', 'single',   ''),
            PathEntry(_('Bosses folder:'),         'bosses_directory',  'ui.ini',      'folders', 'single',   ''),
            PathEntry(_('Controller folder:'),     'ctrlrpath',         'mame.ini',    'folders', 'multiple', ''),
            PathEntry(_('INI folder:'),            'inipath',           'mame.ini',    'folders', 'multiple', ''),
            PathEntry(_('Config folder:'),         'cfg_directory',     'mame.ini',    'folders', 'single',   ''),
            PathEntry(_('Mapping folder:'),        'input_mapping',     'pfemame.ini', 'folders', 'single',   ''),
            PathEntry(_('NVRAM folder:'),          'nvram_directory',   'mame.ini',    'folders', 'single',   ''),
            PathEntry(_('Difference folder:'),     'diff_directory',    'mame.ini',    'folders', 'single',   ''),
            PathEntry(_('Cheat File folder:'),     'cheatpath',         'mame.ini',    'folders', 'multiple', ''),
            PathEntry(_('Inputs folder:'),         'input_directory',   'mame.ini',    'folders', 'single',   ''),
            PathEntry(_('States folder:'),         'state_directory',   'mame.ini',    'folders', 'single',   ''),
        ]

        rows = []
        for entry in entries:
            ini_values = get_ini_value(entry, self.path_to_mame_ini_file)
            checked_values = ini_paths(entry, ini_values)
            add_string = '' if entry.path_type == 'single' else 'Add'

            for val in checked_values:
                rows.append(PathRow(
                    label=entry.label,
                    path=val,
                    add_flag=add_string,
                    wildcard=entry.file_filter,
                    ini_key=entry.ini_key,
                    data_type=entry.data_type,
                    ini_file=entry.ini_file,
                ))

        old_count = self.table.row_count()
        self.table.set_rows(rows)
        new_count = self.table.row_count()

        if new_count > old_count:
            msg = wx.grid.GridTableMessage(
                self.table, wx.grid.GRIDTABLE_NOTIFY_ROWS_APPENDED, new_count - old_count)
            self.list_control.ProcessTableMessage(msg)
        elif new_count < old_count:
            msg = wx.grid.GridTableMessage(
                self.table, wx.grid.GRIDTABLE_NOTIFY_ROWS_DELETED, new_count, old_count - new_count)
            self.list_control.ProcessTableMessage(msg)

        self.list_control.ForceRefresh()

    # ------------------------------------------------------------------------------------------------------------------
    def _on_grid_size(self, event):
        event.Skip()
        # Defer the resize — calling SetColSize from inside the size event re-enters this
        # handler when the scrollbar appears or disappears.
        wx.CallAfter(self._resize_path_column)

    # ------------------------------------------------------------------------------------------------------------------
    def _resize_path_column(self):
        """Give the Path column whatever width is left over after the Name column."""
        try:
            available = self.list_control.GetClientSize().width - self.list_control.GetColSize(0)
        except RuntimeError:        # panel was destroyed before the deferred call ran
            return
        self.list_control.SetColSize(1, max(100, available))

    # ------------------------------------------------------------------------------------------------------------------
    def on_right_click_list(self, event):
        row = event.GetRow()
        entry_rows = self.entry_rows(row)
        can_add       = self.table.get_row(row).add_flag == 'Add'
        can_delete    = len(entry_rows) > 1            # An entry always keeps at least one row
        can_move_up   = row > entry_rows[0]
        can_move_down = row < entry_rows[-1]
        folder        = self.folder_to_open(self.table.get_row(row))

        menu = wx.Menu()
        id_add       = wx.NewIdRef()
        id_delete    = wx.NewIdRef()
        id_clear     = wx.NewIdRef()
        id_move_up   = wx.NewIdRef()
        id_move_down = wx.NewIdRef()
        id_open      = wx.NewIdRef()

        if can_add:
            menu.Append(id_add, _('Add extra path for this entry'))
        if can_delete:
            menu.Append(id_delete, _('Delete this path'))
        menu.Append(id_clear, _('Clear path'))
        if can_move_up or can_move_down:
            # MAME searches an entry's paths in order and uses the first match
            menu.AppendSeparator()
            if can_move_up:
                menu.Append(id_move_up, _('Move up (searched earlier)'))
            if can_move_down:
                menu.Append(id_move_down, _('Move down (searched later)'))
        if folder:
            menu.AppendSeparator()
            menu.Append(id_open, _('Open folder'))

        def on_add(_evt):
            current_row = self.table.get_row(row)
            new_row = PathRow(
                label=current_row.label,
                path='',
                add_flag='Add',
                wildcard='',
                ini_key=current_row.ini_key,
                data_type=current_row.data_type,
                ini_file=current_row.ini_file,
            )
            self.insert_row(new_row, row + 1)
            self.data_changed = True
            self.check_valid_paths()

        def on_delete(_evt):
            dlg = wx.MessageDialog(None, _('Are you sure you want to DELETE this row?'),
                                   _('Delete selected row'), wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION)
            if dlg.ShowModal() == wx.ID_YES:
                self.delete_path_row(row)
            dlg.Destroy()

        def on_clear(_evt):
            dlg = wx.MessageDialog(None, _('Are you sure you want to clear this row (set to empty)?'),
                                   _('Clear selected row'), wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION)
            if dlg.ShowModal() == wx.ID_YES:
                self.table.set_path(row, '')
                self.data_changed = True
                self.check_valid_paths()
            dlg.Destroy()

        if can_add:
            menu.Bind(wx.EVT_MENU, on_add, id=id_add)
        if can_delete:
            menu.Bind(wx.EVT_MENU, on_delete, id=id_delete)
        menu.Bind(wx.EVT_MENU, on_clear, id=id_clear)
        if can_move_up:
            menu.Bind(wx.EVT_MENU, lambda _evt: self.move_row(row, -1), id=id_move_up)
        if can_move_down:
            menu.Bind(wx.EVT_MENU, lambda _evt: self.move_row(row, 1), id=id_move_down)
        if folder:
            menu.Bind(wx.EVT_MENU, lambda _evt: self.open_folder(folder), id=id_open)

        functions.show_popup_menu(self.list_control, menu)
        self._repaint_buttons()

    # ------------------------------------------------------------------------------------------------------------------
    def entry_rows(self, row: int) -> list:
        """The row numbers of every row belonging to the same entry as row (an entry's rows are together)."""
        ini_key = self.table.get_row(row).ini_key
        return [index for index, r in enumerate(self.table.get_all_rows()) if r.ini_key == ini_key]

    # ------------------------------------------------------------------------------------------------------------------
    def move_row(self, row: int, offset: int) -> bool:
        """Move a row up (-1) or down (+1) within its entry.  Returns False if it is already at that end."""
        target = row + offset
        if target not in self.entry_rows(row):
            return False
        self.table.swap_rows(row, target)
        self.list_control.SelectRow(target)
        self.list_control.MakeCellVisible(target, 0)
        self.data_changed = True
        self.check_valid_paths()
        return True

    # ------------------------------------------------------------------------------------------------------------------
    def delete_path_row(self, row: int) -> bool:
        """Remove one path of a multi-path entry.  The last remaining row of an entry can't be deleted."""
        if len(self.entry_rows(row)) < 2:
            return False
        self.table.delete_row(row)
        self.list_control.ProcessTableMessage(
            wx.grid.GridTableMessage(self.table, wx.grid.GRIDTABLE_NOTIFY_ROWS_DELETED, row, 1))
        self.data_changed = True
        self.check_valid_paths()
        return True

    # ------------------------------------------------------------------------------------------------------------------
    def insert_row(self, data: PathRow, row_to_insert: int):
        self.table.insert_row(row_to_insert, data)
        msg = wx.grid.GridTableMessage(
            self.table, wx.grid.GRIDTABLE_NOTIFY_ROWS_INSERTED, row_to_insert, 1)
        self.list_control.ProcessTableMessage(msg)
        self.list_control.ForceRefresh()

    # ------------------------------------------------------------------------------------------------------------------
    def on_double_click_list(self, event):
        index = event.GetRow()
        r = self.table.get_row(index)
        path        = r.path
        target_type = r.data_type
        wildcard    = self._file_wildcard(r.wildcard)

        start_folder, start_file = self._browse_start(r)
        output = (self.open_file(path, wildcard, start_folder, start_file) if target_type == 'path'
                  else self.open_dir(path, start_folder))
        problem = self._wrong_kind(r, output) if output != path else ''
        if problem:             # The dialogs shouldn't allow it, but some platforms' file dialogs can return a folder
            pub.sendMessage('status', msg=problem)
        else:
            self.set_row_path(index, output)
        self._repaint_buttons()

    # ------------------------------------------------------------------------------------------------------------------
    def set_row_path(self, index: int, new_path: str):
        """Set a row to a path the user has chosen (browsed to, or dropped on it) and follow up on what it affects."""
        r = self.table.get_row(index)
        if new_path == r.path:
            return
        self.data_changed = True
        self.table.set_path(index, new_path)
        self.list_control.ForceRefresh()

        mame_ini_before = self.path_to_mame_ini_file
        if r.ini_key == 'mame_executable':
            self.update_mame_ini_path()

        if r.ini_key == 'inipath':
            self.folders_ini = new_path or self.mame_folders_path

        # Choosing a mame.ini (or an executable, which moves the mame.ini row) changes where APPLY saves to
        self.path_to_mame_ini_file = self.get_path_list_ctrl('mame_ini')
        if self.path_to_mame_ini_file != mame_ini_before:
            self.offer_to_load_mame_ini()

        self.check_valid_paths()

    # ------------------------------------------------------------------------------------------------------------------
    def on_drop_files(self, x: int, y: int, filenames: list) -> bool:
        """Files / folders dropped on the grid (from Explorer, Finder etc.) - x, y are in the grid window."""
        _x, y = self.list_control.CalcUnscrolledPosition(x, y)
        return self.drop_path(self.list_control.YToRow(y), filenames)

    # ------------------------------------------------------------------------------------------------------------------
    def drop_path(self, index: int, filenames: list) -> bool:
        """Set the row a file or folder was dropped on, if it is the right kind of thing for that row."""
        if not 0 <= index < self.table.row_count():
            return False
        r = self.table.get_row(index)
        if len(filenames) != 1:
            problem = _('Drop one file or folder at a time.')
        else:
            problem = self._wrong_kind(r, filenames[0])
        if problem:
            pub.sendMessage('status', msg=problem)
            return False
        self.list_control.SelectRow(index)
        self.set_row_path(index, filenames[0])
        self._repaint_buttons()
        return True

    # ------------------------------------------------------------------------------------------------------------------
    def folder_to_open(self, r: PathRow) -> str:
        """The folder 'Open folder' shows for a row: the row's folder, or the folder holding its file.  '' if gone."""
        if not r.path:
            return ''
        resolved = os.path.abspath(self._resolve(r))
        if os.path.isdir(resolved):
            return resolved
        return os.path.dirname(resolved) if os.path.isfile(resolved) else ''

    # ------------------------------------------------------------------------------------------------------------------
    def open_folder(self, folder: str):
        """Show a folder in Explorer / Finder / the desktop's file manager."""
        if not wx.LaunchDefaultApplication(folder):
            pub.sendMessage('status', msg=_('Unable to open {}').format(folder))

    # ------------------------------------------------------------------------------------------------------------------
    def offer_to_load_mame_ini(self):
        """A different mame.ini has been chosen - offer to show its folders instead of the ones on screen."""
        if not os.path.isfile(self.path_to_mame_ini_file):
            return
        dlg = wx.MessageDialog(
            self,
            _('Load the folder paths from this mame.ini?\n\n{}\n\n(No keeps the folder paths shown now, and they '
              'will be saved into it when you APPLY.)').format(self.path_to_mame_ini_file),
            _('Different mame.ini'),
            wx.YES_NO | wx.YES_DEFAULT | wx.ICON_QUESTION)
        load = dlg.ShowModal() == wx.ID_YES
        dlg.Destroy()
        if load:
            self.folders_ini = iniFile.get_from_mameini('inipath', self.path_to_mame_ini_file)
            self.build_filepaths_table(keep_pfemame_rows=True)
            self.check_valid_paths()

    # ------------------------------------------------------------------------------------------------------------------
    def update_mame_ini_path(self):
        """Point the MAME INI File row at the mame.ini for the current MAME executable (see find_mame_ini)."""
        self.path_to_mame_ini_file = functions.find_mame_ini(self.get_path_list_ctrl('mame_executable'),
                                                             self.system, self.get_path_list_ctrl('mame_ini'))
        self.set_single_path('mame_ini', self.path_to_mame_ini_file)
        # If none was found the row now shows where it would go, in red with a 'File not found' tooltip

    # ------------------------------------------------------------------------------------------------------------------
    def update_table(self, variable_to_update: str, value_to_update: str):
        self.table.update_path_by_ini_key(variable_to_update, value_to_update)
        self.list_control.ForceRefresh()

    # ------------------------------------------------------------------------------------------------------------------
    def get_path_list_ctrl(self, path_name_to_look_for: str) -> str:
        return self.table.find_path_by_ini_key(path_name_to_look_for)

    # ------------------------------------------------------------------------------------------------------------------
    def on_auto_find(self, _event):
        confirm_dlg = wx.MessageDialog(
            None,
            _('Are you sure you want to automatically look for all file & folder paths?  This '
              'will use the mame -createconfig command which will overwrite any existing mame.ini '
              'settings.'),
            _('Auto Find file & folder paths'),
            wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION
        )
        confirmed = confirm_dlg.ShowModal() == wx.ID_YES
        confirm_dlg.Destroy()
        if not confirmed:
            return

        dir_dlg = wx.DirDialog(
            self,
            message=_('Select the MAME folder where your various files & folders are located, e.g. ROMs, SNAPs, etc'),
            defaultPath=self.activePath,
            style=wx.DD_DEFAULT_STYLE
        )
        if dir_dlg.ShowModal() != wx.ID_OK:
            dir_dlg.Destroy()
            return
        mame_path = dir_dlg.GetPath()
        dir_dlg.Destroy()

        self.my_logger.info(f'FILEPATHS INFO:  MAME Folder: {mame_path}')
        self.activePath = mame_path
        self.mame_folders_path = mame_path
        pub.sendMessage('status', msg=_('Auto Find: searching for MAME paths...'))

        cancel = self._auto_find_cancel = threading.Event()
        self.run_in_background(lambda progress: self._auto_find_search(mame_path, progress, cancel),
                               lambda found_paths: self._auto_find_results(mame_path, found_paths, cancel),
                               cancel=cancel)

    # ------------------------------------------------------------------------------------------------------------------
    def _auto_find_search(self, mame_path: str, progress, cancel: threading.Event) -> dict:
        """
        The slow part of AUTO FIND (runs in the worker thread): look through the MAME folder (and pfeMAME's) for the
        usual files and folders, and find a MAME executable that works.  Returns {ini_key: path ('' = not found)}.
        """
        progress(_('Looking in {}').format(mame_path))
        location_lookups = [_build_dir_lookup(location) for location in (mame_path, os.getcwd())]

        def findmatch(match_number: int) -> str:
            is_a_file = MAME_FOLDERS[match_number][0] == 'file'
            for name in MAME_FOLDERS[match_number][2:]:
                for lookup in location_lookups:
                    item = lookup.get(name.lower())
                    if item and ((is_a_file and item.is_file()) or (not is_a_file and item.is_dir())):
                        return str(item)
            return ''

        found_paths = {line[1]: findmatch(index) for index, line in enumerate(MAME_FOLDERS)}

        path_executable = found_paths['mame_executable']
        found_mame = False
        if path_executable and os.path.isfile(path_executable):
            self.my_logger.info('FILEPATHS INFO:  Looking for MAME exe in the MAME folder')
            progress(_('Checking {}').format(path_executable))
            found_mame = self.check_mame_executable(path_executable, cwd=mame_path)
            if found_mame:
                self.my_logger.info('FILEPATHS INFO: Found the MAME executable in the MAME folder')
            else:
                self.my_logger.error(f'FILEPATHS ERROR:  {path_executable} failed its check, so searching the '
                                     f'system path instead')
        if not found_mame and not cancel.is_set():
            path_executable = self._search_system_for_mame(cwd=mame_path, progress=progress, cancel=cancel)
            found_mame = bool(path_executable)
        found_paths['mame_executable'] = path_executable if found_mame else ''
        return found_paths

    # ------------------------------------------------------------------------------------------------------------------
    def _auto_find_results(self, mame_path: str, found_paths: dict, cancel: threading.Event):
        """The rest of AUTO FIND, back on the GUI thread: put what was found into the table and summarise it."""
        if cancel.is_set():
            self.my_logger.info('FILEPATHS INFO:  Auto Find cancelled')
            pub.sendMessage('status', msg=_('Auto Find cancelled - nothing has been changed'))
            return

        # Each entry Auto Find finds is set to that one path; anything it doesn't find is left as it was
        found, changed, not_found = [], [], []

        def record(ini_key: str, value: str):
            label = self._entry_label(ini_key)
            if value:
                found.append(label)
                if self.set_single_path(ini_key, value):
                    changed.append(label)
            else:
                not_found.append(label)

        path_executable = found_paths['mame_executable']
        if path_executable:
            record('mame_executable', path_executable)
        elif os.path.isfile(self.get_path_list_ctrl('mame_executable')):
            self.my_logger.info('FILEPATHS INFO:  MAME executable not found, so keeping the current one')
            record('mame_executable', '')
        else:
            self.my_logger.error(_('Unable to find the MAME executable so setting to default'))
            show_error_dialog(self,
                              _('Unable to auto-find the MAME executable.  Either I am looking in '
                                'the wrong place, or you dont have MAME installed yet.  Setting it '
                                'to the default \'mame\' which may work.  If not, you will '
                                'need to find it manually'),
                              _('ERROR'))
            if self.set_single_path('mame_executable', 'mame'):
                changed.append(self._entry_label('mame_executable'))

        for line in MAME_FOLDERS[1:]:
            path_name = line[1]
            match = found_paths[path_name]

            if path_name == 'inipath' and not match and not self.get_path_list_ctrl('inipath'):
                # MAME needs somewhere for its INI files, so fall back to its usual place
                match = (mame_path if self.system != 'linux'
                         else os.path.join(os.path.expanduser('~'), '.mame'))
            record(path_name, match)
            if path_name == 'inipath' and match:
                self.folders_ini = match

        mame_ini_before = self.get_path_list_ctrl('mame_ini')
        self.update_mame_ini_path()
        if self.get_path_list_ctrl('mame_ini') != mame_ini_before:
            changed.append(self._entry_label('mame_ini'))

        self.check_valid_paths()
        if changed:
            self.data_changed = True
        self.Refresh()
        pub.sendMessage('status', msg=_('Auto Find complete'))
        show_information_dialog(self, self._auto_find_summary(found, changed, not_found), _('Auto Find complete'))

    # ------------------------------------------------------------------------------------------------------------------
    def _search_system_for_mame(self, cwd: str, progress=None, cancel: threading.Event | None = None) -> str:
        """
        Look for a working MAME on the system path and in the usual install folders.  '' if none is found (or cancel
        is set - it is checked before each MAME is tried).
        """
        self.my_logger.info('FILEPATHS INFO:  Looking for MAME exe in the system path')
        sys_path = os.environ.get('PATH', '').split(os.pathsep)

        if self.system == 'windows':
            sys_path.extend([r'C:\mame', r'C:\Program Files\mame', r'C:\Program Files (x86)\mame'])
        elif self.system == 'mac':
            sys_path.extend([
                '/opt/homebrew/bin', '/usr/local/bin', '/opt/local/bin',
                '/opt/local/libexec/mame', os.path.expanduser('~/bin'),
                os.path.expanduser('~/Applications/mame'),
            ])
        else:
            sys_path.extend(['/usr/games', '/usr/local/games', '/snap/bin'])

        mame_names = {'mame.exe'} if self.system == 'windows' else {'mame'}

        for spath in sys_path:
            if cancel and cancel.is_set():
                return ''
            try:
                files = os.listdir(spath)
            except OSError:         # Missing / unreadable folder, or a PATH entry that isn't a folder
                continue
            for file in files:
                # Windows file names aren't case-sensitive (MAME.EXE, Mame.exe...)
                if (file.lower() if self.system == 'windows' else file) not in mame_names:
                    continue
                full_path = os.path.join(spath, file)
                self.my_logger.info(f'FILEPATHS INFO:  Found: {file} in {spath}')
                if (os.path.isfile(full_path) and os.access(full_path, os.X_OK)
                        and os.path.getsize(full_path) > 50000):
                    self.my_logger.info('FILEPATHS INFO:  Confirmed as a valid executable')
                    if cancel and cancel.is_set():
                        return ''
                    if progress:
                        progress(_('Checking {}').format(full_path))
                    if self.check_mame_executable(full_path, cwd=cwd):
                        self.my_logger.info('FILEPATHS INFO: Found MAME executable in system path')
                        return full_path
                    self.my_logger.error(f'FILEPATHS ERROR:  {full_path} failed its check')
                else:
                    self.my_logger.error(f'FILEPATHS ERROR:  {file} found in {spath} but failed validation checks')
        return ''

    # ------------------------------------------------------------------------------------------------------------------
    @staticmethod
    def _auto_find_summary(found: list, changed: list, not_found: list) -> str:
        lines = [_('Found {found} of {total} paths ({changed} changed).').format(
            found=len(found), total=len(found) + len(not_found), changed=len(changed))]
        if changed:
            lines += ['', _('Changed:'), ', '.join(changed)]
        if not_found:
            lines += ['', _('Not found (left as they were):'), ', '.join(not_found)]
        lines += ['', _('Check the paths, then APPLY to save them or REVERT to undo.')]
        return '\n'.join(lines)

    # ------------------------------------------------------------------------------------------------------------------
    def _entry_label(self, ini_key: str) -> str:
        for row in self.table.get_all_rows():
            if row.ini_key == ini_key:
                return row.label.rstrip(':')
        return ini_key

    # ------------------------------------------------------------------------------------------------------------------
    def set_single_path(self, ini_key: str, value: str) -> bool:
        """
        Make the entry for ini_key a single row holding value, removing any extra rows of a multi-path entry.
        Returns True if anything changed.
        """
        rows = [index for index, row in enumerate(self.table.get_all_rows()) if row.ini_key == ini_key]
        if not rows:
            return False
        changed = len(rows) > 1 or self.table.get_row(rows[0]).path != value
        for row in reversed(rows[1:]):
            self.table.delete_row(row)
            self.list_control.ProcessTableMessage(
                wx.grid.GridTableMessage(self.table, wx.grid.GRIDTABLE_NOTIFY_ROWS_DELETED, row, 1))
        self.table.set_path(rows[0], value)
        self.list_control.ForceRefresh()
        return changed

    # ------------------------------------------------------------------------------------------------------------------
    def _run_mame(self, path_executable: str, option: str,
                  cwd: str | None = None) -> tuple[subprocess.CompletedProcess | None, str]:
        """
        Run MAME with a single option (e.g. -showconfig), with a timeout.
        Returns (finished process, '') or, if MAME could not be run or timed out, (None, why - for showing the user).
        """
        cmd = [path_executable, option]
        self.my_logger.info(f'FILEPATHS INFO:  Running {cmd} in {cwd or os.getcwd()}')
        try:
            result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=MAME_TIMEOUT,
                                    cwd=cwd or None, **functions.NO_CONSOLE)
            self.my_logger.info(f'FILEPATHS INFO:  MAME finished with exit code {result.returncode}')
            return result, ''
        except subprocess.TimeoutExpired:
            self.my_logger.error(f'FILEPATHS ERROR:  {cmd} timed out after {MAME_TIMEOUT} seconds')
            return None, _('MAME did not finish within {} seconds.').format(MAME_TIMEOUT)
        except (OSError, ValueError) as e:   # Not found, not a program (WinError 193), no permission, bad folder...
            self.my_logger.error(f'FILEPATHS ERROR:  Unable to run {cmd}: {e}')
            return None, _('MAME could not be run:  {}').format(e)

    # ------------------------------------------------------------------------------------------------------------------
    def check_mame_executable(self, path: str, cwd: str | None = None) -> bool:
        """Run 'mame -createconfig' in the cwd folder (where MAME then writes mame.ini).  True if MAME succeeded."""
        if path == '':
            self.my_logger.error('FILEPATHS ERROR:  An empty path was used to try and find the MAME executable')
            return False
        result, _problem = self._run_mame(path, '-createconfig', cwd)
        return result is not None and result.returncode == 0

    # ------------------------------------------------------------------------------------------------------------------
    def on_make_ini(self, _event):
        # 'mame' on its own means run MAME from the system path
        path_executable = self.get_path_list_ctrl('mame_executable') or 'mame'
        if path_executable != 'mame' and not os.path.isfile(path_executable):
            show_error_dialog(self, _('The path to the MAME executable is invalid.'), _('ERROR'))
            return

        # MAME writes mame.ini into the folder it is run from.  Use the MAME INI File row's folder if one is set (e.g.
        # ~/mame), otherwise the usual place: MAME's own folder on Windows / macOS, and ~/.mame on Linux (where MAME's
        # own folder is usually read-only and ~/.mame is where it looks)
        current_mame_ini = self.get_path_list_ctrl('mame_ini')
        if current_mame_ini:
            folder = os.path.dirname(os.path.abspath(os.path.expanduser(current_mame_ini)))
        elif self.system == 'linux':
            folder = os.path.join(os.path.expanduser('~'), '.mame')
        else:
            folder = functions.mame_working_dir(path_executable) or os.getcwd()
        try:
            os.makedirs(folder, exist_ok=True)
        except OSError as e:
            show_error_dialog(self, _('Unable to create the folder for mame.ini:') + f'\n\n{folder}\n\n{e}', _('ERROR'))
            return
        mame_ini = os.path.join(folder, 'mame.ini')

        started = time.time()
        self.run_in_background(lambda progress: self._run_mame(path_executable, '-createconfig', folder),
                               lambda mame_result: self._make_ini_done(mame_result, folder, mame_ini, started))

    # ------------------------------------------------------------------------------------------------------------------
    def _make_ini_done(self, mame_result: tuple, folder: str, mame_ini: str, started: float):
        """The rest of MAKE INI, once MAME has finished -createconfig: check mame.ini was really written."""
        result, problem = mame_result
        if result is not None and result.returncode != 0:
            problem = _('MAME reported an error (exit code {}).').format(result.returncode)
        elif result is not None and not (os.path.isfile(mame_ini) and os.path.getmtime(mame_ini) >= started - 2):
            problem = _('MAME ran, but no mame.ini was written to {}.').format(folder)
        if problem:
            show_error_dialog(self,
                              _('Unable to create the mame.ini file.') + '\n\n' + problem + '\n\n' +
                              _('Check the MAME executable path and that the folder is not read-only.'),
                              _('ERROR'))
            return

        if self.set_single_path('mame_ini', mame_ini):
            self.data_changed = True
        self.path_to_mame_ini_file = mame_ini
        self.check_valid_paths()
        show_information_dialog(self, _('Completed creating mame.ini') + f'\n\n{mame_ini}', _('Done'))

    # ------------------------------------------------------------------------------------------------------------------
    def on_clear_all(self, _event):
        dlg = wx.MessageDialog(None, _('Are you sure you want to clear all file & folder paths?'),
                               _('Clear all file paths'), wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION)
        if dlg.ShowModal() == wx.ID_YES:
            for row in range(self.table.row_count()):
                self.table.set_path(row, '')
            self.data_changed = True
            self.check_valid_paths()
        dlg.Destroy()
        self.Refresh()

    # ------------------------------------------------------------------------------------------------------------------
    def _file_wildcard(self, patterns: str) -> str:
        """The file chooser filter for a row: its own file types (e.g. '*.xml;*.dat') first, then All files."""
        all_files = '*.*' if self.system == 'windows' else '*'
        all_choice = f'{_("All files")} ({all_files})|{all_files}'
        if not patterns or (patterns == '*.exe' and self.system != 'windows'):    # Programs have no extension there
            return all_choice
        return f'{patterns}|{patterns}|{all_choice}'

    # ------------------------------------------------------------------------------------------------------------------
    def open_file(self, input_path: str, wildcard: str, start_folder: str, start_file: str = '') -> str:
        dlg = wx.FileDialog(self, message=_('Choose a file'), defaultDir=start_folder,
                            defaultFile=start_file, wildcard=wildcard, style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST)
        path = dlg.GetPath() if dlg.ShowModal() == wx.ID_OK else input_path
        dlg.Destroy()
        return path

    # ------------------------------------------------------------------------------------------------------------------
    def open_dir(self, input_path: str, start_folder: str) -> str:
        dlg = wx.DirDialog(self, message=_('Choose a directory'), defaultPath=start_folder,
                           style=wx.DD_DEFAULT_STYLE | wx.DD_NEW_DIR_BUTTON)
        path = dlg.GetPath() if dlg.ShowModal() == wx.ID_OK else input_path
        dlg.Destroy()
        return path


if __name__ == '__main__':
    app = wx.App()

    # Set up logging if running directly
    logger = functions.setup_logging(functions.path_to_me())

    _ = functions.set_up_language()  # Set of the application language

    WindowFilePaths(logger)
    app.MainLoop()
