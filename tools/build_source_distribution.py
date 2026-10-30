#!/usr/bin/env python3

# ----------------------------------------------------------------------------------------------------------------------
# build_source_distribution.py

"""
This creates a source file distribution package based on the files and folders contained in the payload info.
"""

# Import python & wxpython modules
import os
import shutil
import wx
import threading
from pathlib import Path

# Never copy Python / pytest caches when a whole folder is included
IGNORE_IN_FOLDERS = shutil.ignore_patterns('__pycache__', '*.pyc', '.pytest_cache')

# Python files in the source folder that are deliberately NOT part of the source distribution
NOT_DISTRIBUTED = {'custom_title_bar.py'}      # Unused (its only import in checkall.py is commented out)

class SourceDistributor(wx.Frame):
    def __init__(self, parent, title="Source Distribution Builder"):
        super().__init__(parent, title=title, size=wx.Size(800, 600))
        self.cwd = Path.cwd().parent
        self.output_root = self.cwd          # Where distribution_source_<version> is created
        self.payload = self.get_payload()
        self.panel = wx.Panel(self)

        # UI Elements
        self.start_button = wx.Button(self.panel, label="START")
        self.output = wx.TextCtrl(self.panel, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.BORDER_SUNKEN)
        self.output.SetBackgroundColour(wx.Colour(255, 255, 255))

        self.line_count_display = wx.ListCtrl(self.panel, style=wx.LC_REPORT)
        self.line_count_display.InsertColumn(0, "Python File", width=300)
        self.line_count_display.InsertColumn(1, "Line Count", wx.LIST_FORMAT_RIGHT, width=100)

        self.sizer = wx.BoxSizer(wx.VERTICAL)
        self.sizer.Add(self.start_button, 0, wx.ALL | wx.EXPAND, 5)
        self.sizer.Add(wx.StaticText(self.panel, label="Copy Log:"), 0, wx.LEFT | wx.TOP, 5)
        self.sizer.Add(self.output, 2, wx.EXPAND | wx.ALL, 5)
        self.sizer.Add(wx.StaticText(self.panel, label="Python Line Counts:"), 0, wx.LEFT | wx.TOP, 5)
        self.sizer.Add(self.line_count_display, 1, wx.EXPAND | wx.ALL, 5)

        self.panel.SetSizer(self.sizer)

        self.start_button.Bind(wx.EVT_BUTTON, self.on_start)

        self.Show()

    def log(self, msg, error=False):
        if error:
            self.output.SetDefaultStyle(wx.TextAttr(wx.RED))
        else:
            self.output.SetDefaultStyle(wx.TextAttr(wx.BLACK))
        self.output.AppendText(msg + "\n")

    def get_payload(self):
        return [
            ['tools', 'cwd', 'folder_all'],
            ['images', 'cwd', 'folder_all'],
            ['toolbar_icons', 'cwd', 'folder_all'],
            ['locales', 'cwd', 'folder_all'],
           ['license', 'cwd', 'folder_all'],
           ['tests', 'cwd', 'folder_all'],             # pytest suite + saved MAME XML fixtures
           ['catver.ini', 'cwd', 'file'],
           ['changelog.docx', 'cwd', 'file'],
           ['checkall.py', 'cwd', 'file'],
           ['fix_artwork_file.py', 'cwd', 'file'],
           ['controls.txt', 'cwd', 'file'],
           ['filepaths.py', 'cwd', 'file'],
           ['functions.py', 'cwd', 'file'],
           ['iniFile.py', 'cwd', 'file'],
           ['pfeMAME_Manual.pdf', 'cwd', 'file'],
           ['pfemame.png', 'cwd', 'file'],
           ['pfemame.py', 'cwd', 'file'],
           ['rom_grid.py', 'cwd', 'file'],
           ['preferences.py', 'cwd', 'file'],
           ['rominfo.py', 'cwd', 'file'],
           ['rungame.py', 'cwd', 'file'],
           ['scrolledwindow.py', 'cwd', 'file'],
           ['tileview.py', 'cwd', 'file'],
           ['tile_grid_model.py', 'cwd', 'file'],
           ['database_build.py', 'cwd', 'file'],
           ['xmlinfo.py', 'cwd', 'file'],
           ['aboutbox.py', 'cwd', 'file'],
           ['PanelSound.py', 'cwd', 'file'],
           ['PanelVideo.py', 'cwd', 'file'],
           ['PanelInput.py', 'cwd', 'file'],
           ['PanelPerformance.py', 'cwd', 'file'],
           ['PanelOSD.py', 'cwd', 'file'],
           ['PanelDebug.py', 'cwd', 'file'],
           ['PanelPfeMame.py', 'cwd', 'file'],
           ['PanelMisc.py', 'cwd', 'file'],
           ['PanelSlots.py', 'cwd', 'file'],
           ['PanelSlotsHelpers.py', 'cwd', 'file'],
           ['slot_model.py', 'cwd', 'file'],
           ['preferences_model.py', 'cwd', 'file'],
           ['fast_download.py', 'cwd', 'file'],
           ['delta_update.py', 'cwd', 'file'],
           ['mame_paths.py', 'cwd', 'file'],
           ['app_paths.py', 'cwd', 'file'],
           ['rom_database.py', 'cwd', 'file'],
           ['backup.py', 'cwd', 'file'],
           ['views.py', 'cwd', 'file'],
           ['updater_client.py', 'cwd', 'file'],
           ['search.py', 'cwd', 'file'],
           ['play_stats.py', 'cwd', 'file'],
           ['slot_presets.py', 'cwd', 'file'],
           ['software_lists.py', 'cwd', 'file'],
           ['software_browser.py', 'cwd', 'file'],
           ['starRating.py', 'cwd', 'file'],
           ['get_joystick_names.py', 'cwd', 'file'],
           ['fullscreenplay.py', 'cwd', 'file'],
           ['busy_window.py', 'cwd', 'file'],
           ['requirements.txt', 'cwd', 'file'],
           ['popupimage.py', 'cwd', 'file'],
           ['alternate_emulators.py', 'cwd', 'file'],
           ['emulator_config.py', 'cwd', 'file'],
           ['languagepicker.py', 'cwd', 'file'],
           ['non_mame_defaults.xml', 'cwd', 'file'],
           ['pfemame_updater.py', 'cwd', 'file'],
           ['video_class.py', 'cwd', 'file'],
           ['pfemame_ribbon_bar.py', 'cwd', 'file'],
           ['custom_text_ctrl.py', 'cwd', 'file'],
           ['custom_scrolled_panel.py', 'cwd', 'file'],
           ['custom_drop_down.py', 'cwd', 'file'],
           ['custom_scrollbar.py', 'cwd', 'file'],
           ['global_defaults.py', 'cwd', 'file'],
           ['online_image_search.py', 'cwd', 'file'],
           ['image_picker_dialog.py', 'cwd', 'file'],
           ['online_rom_search.py', 'cwd', 'file'],
           ['rom_picker_dialog.py', 'cwd', 'file'],
            ['rom_credentials.py', 'cwd', 'file'],
            ['rom_source_dialog.py', 'cwd', 'file'],
            ['program_cleanup.py', 'cwd', 'file'],
            ['linux_libs_check.py', 'cwd', 'file'],
               ]

    def missing_from_payload(self) -> list[str]:
        """Top-level .py files in the source folder that the payload doesn't include."""
        listed = {name for name, _source, _type in self.payload}
        return sorted(path.name for path in self.cwd.glob('*.py')
                      if path.name not in listed and path.name not in NOT_DISTRIBUTED)

    def on_start(self, _event):
        threading.Thread(target=self.build_distribution, daemon=True).start()

    def build_distribution(self):
        release_pos = str(self.cwd).find('_v')
        if release_pos == -1:
            wx.CallAfter(self.log, "Error: Could not find release version in path", True)
            return
        release_version = str(self.cwd)[release_pos + 1:]
        dist_folder = self.output_root / f'distribution_source_{release_version}'

        os.makedirs(dist_folder, exist_ok=True)
        wx.CallAfter(self.log, f"Created/verified distribution folder: {dist_folder}")

        # Warn about any Python module in the source folder that is missing from the payload (e.g. a new file)
        for name in self.missing_from_payload():
            wx.CallAfter(self.log, f"Warning: {name} is in the source folder but not in the payload list", True)

        copy_count = 0

        for item_name, source_dir, item_type in self.payload:
            dest_path = dist_folder / item_name
            source_path = self.cwd / item_name if source_dir == 'cwd' else Path(source_dir) / item_name

            try:
                if item_type == 'folder_all':
                    if not source_path.exists():
                        wx.CallAfter(self.log, f"Warning: Source folder '{source_path}' does not exist", True)
                        continue
                    shutil.copytree(source_path, dest_path, dirs_exist_ok=True, ignore=IGNORE_IN_FOLDERS)
                    copied_files = sum(len(f) for _, _, f in os.walk(dest_path))
                    copy_count += copied_files
                    wx.CallAfter(self.log, f"Copied folder tree: {source_path} -> {dest_path} ({copied_files} files)")

                elif item_type == 'folder':
                    os.makedirs(dest_path, exist_ok=True)
                    wx.CallAfter(self.log, f"Created folder: {dest_path}")

                elif item_type == 'file':
                    if not source_path.is_file():
                        wx.CallAfter(self.log, f"Warning: File '{source_path}' not found", True)
                        continue
                    shutil.copy2(source_path, dest_path)
                    copy_count += 1
                    wx.CallAfter(self.log, f"Copied file: {source_path}")

                    # Count lines for .py files
                    if source_path.suffix == ".py":
                        with source_path.open("r", encoding="utf-8", errors="ignore") as f:
                            lines = [line for line in f if line.strip() and not line.strip().startswith("#")]
                        wx.CallAfter(self.add_line_count, source_path.name, len(lines))
                else:
                    wx.CallAfter(self.log, f"Unknown item type: {item_type}", True)
            except Exception as e:
                wx.CallAfter(self.log, f"Error copying {item_name}: {e}", True)

        wx.CallAfter(self.log, "-" * 60)
        wx.CallAfter(self.log, f"Total files copied: {copy_count}")

    def add_line_count(self, filename, count):
        index = self.line_count_display.InsertItem(self.line_count_display.GetItemCount(), filename)
        self.line_count_display.SetItem(index, 1, str(count))


if __name__ == '__main__':
    app = wx.App(False)
    SourceDistributor(None)
    app.MainLoop()
