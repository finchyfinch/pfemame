#!/usr/bin/env python3

# ----------------------------------------------------------------------------------------------------------------------
# pfemame.py

"""
Python Front End for the MAME emulation system

Author Gareth Finch

This is a front-end for MAME written in Python and using the wx graphical toolkit.  It is cross-platform and has
been tested in Windows (8, 10, 11), Ubuntu Linux, WSL2-Ubuntu, and macOS.
Minimum requirements are;
 python 3.14 or later (64 bit)
 wxPython 4.2.2 or later
 pypubsub
 python-docx
 cx_Freeze 6.0 or later if freezing the application for distribution for Windows or Linux
 py2app for freezing the application for distribution for macOS
 MAME 0.206 or later

For first time users or people wanting to build from this source, please read the manual from front to back as it
answers a lot of questions.
"""

import sys

# First of all, remove the program files an older version left in lib/ - a stale one can break the imports below
# (e.g. 3.9.2's Python 3.14 lib/backports/__init__.pyc stopped 3.10.2 starting).  Installed builds only.
import program_cleanup
program_cleanup.clean_before_imports()

# pfeMAME --check-libs (Linux): list the system libraries that are missing.  Handled before anything else is imported,
# because a missing library stops wx (or another package) loading at all.
if '--check-libs' in sys.argv[1:]:
    import linux_libs_check
    sys.exit(linux_libs_check.main())


def _library_problem(error):
    """
    A package is installed but can't be loaded because a system library it needs is missing.  In the installed Linux
    version, say which libraries are missing and which packages provide them (a terminal and a desktop dialog), then
    stop - started from a desktop menu, pfeMAME would otherwise just not appear.
    """
    if sys.platform.startswith('linux') and getattr(sys, 'frozen', False):
        import linux_libs_check
        linux_libs_check.report_startup_failure(error)
        sys.exit(1)
    raise error


# List your non-standard packages and their install names
REQUIRED_PACKAGES = {
    "pubsub.pub": "pypubsub",
    "docx": "python-docx",
    "OpenGL": "pyopengl",                 # note: PyOpenGL module is "OpenGL"
    "OpenGL_accelerate": "pyopengl_accelerate",
    "py7zr": "py7zr",
    "PIL": "pillow",
    "cv2": "opencv-python-headless",
    "sounddevice": "sounddevice",
}

missing = []

for module, pip_name in REQUIRED_PACKAGES.items():
    try:
        __import__(module)
    except ModuleNotFoundError:
        missing.append((module, pip_name))
    except OSError as e:                    # Installed, but a system library it needs is missing
        if module != 'sounddevice':         # No PortAudio: pfeMAME runs, preview videos are silent (see video_class)
            _library_problem(e)
    except ImportError as e:
        _library_problem(e)

if missing:
    print("ERROR: Missing required packages:")
    for module, pip_name in missing:
        print(f" - {module} (install with: pip install {pip_name})")
    sys.exit(1)

# Import python & wxPython modules
try:
    import wx
except ImportError as e:                    # e.g. libnotify.so.4: cannot open shared object file
    _library_problem(e)
import wx.lib.agw.pygauge as gauge
import os
import io
import subprocess
from functools import lru_cache
import wx.grid
import shutil
import urllib.parse
import urllib.error
import webbrowser
import multiprocessing
import time
import datetime
import argparse
import re
import locale
import wx.lib.agw.flatnotebook as flatnotebook
from dataclasses import dataclass
from threading import Thread
import threading
from random import randint
from pubsub import pub
import docx
from pathlib import Path
import zipfile
import tempfile
from PIL import Image

import global_defaults as _gd      # Only needs wx, so it is safe to import before the language is stored

# The languages that can be chosen with --language (see functions.set_up_language)
LANGUAGES = _gd.LANGUAGE_KEYS


def _store_language_argument() -> None:
    """
    Save a --language / -l choice in pfemame.ini before pfeMAME's own modules are imported.  Each module picks its
    language up as it is imported, so setting it any later only changed the language at the next start.
    """
    language = None
    for position, argument in enumerate(sys.argv[1:], 1):
        if argument in ('-l', '--language') and position + 1 < len(sys.argv):
            language = sys.argv[position + 1]
        elif argument.startswith('--language='):
            language = argument.split('=', 1)[1]
    if language and language.lower() in LANGUAGES:
        import iniFile as _ini      # Only needs functions / wx, which don't translate anything when imported
        _ini.set_ini_file_variables([('preferences', 'language', language.lower())])


if __name__ == '__main__':          # Not when imported (e.g. by the tests)
    _store_language_argument()

# Import my own modules
import languagepicker
import fix_artwork_file
import iniFile
import filepaths
import rominfo
import preferences
import tileview
import checkall
import rungame
import functions
import scrolledwindow
import rom_database
import views
import backup
import updater_client
import search
import play_stats
import software_browser
import xmlinfo
import aboutbox
import busy_window
import fullscreenplay
import popupimage
import online_image_search
import image_picker_dialog
import online_rom_search
import rom_picker_dialog
import rom_credentials
import rom_source_dialog
import alternate_emulators
import starRating
from video_class import Video
import pfemame_ribbon_bar
from custom_text_ctrl import CustomTextCtrl
from custom_scrolled_panel import CustomScrolledPanel
from custom_drop_down import ModernDropdown, EVT_DROPDOWN_SELECTION

# Define Constants here
__version__ = '3.10.2'
__author__ = 'Gareth Finch'
__copyright__ = u'(c)Gareth Finch 2014 - 2026'
__credits__ = ['']
__license__ = 'pfeMAME Licence (free, non-commercial) - see the license folder'
__maintainer__ = 'Gareth Finch'
__email__ = 'pfemame@gmail.com'
__status__ = 'Production'
__developer__ = False

# The ROMs list row layout (mylist index locations / grid columns) lives in rom_grid.py with the grid itself
from rom_grid import (RomGrid, StarCellRenderer, TickCrossRenderer, index_rom_name, index_rom_file_name,
                      index_system_program_file_name, index_exists, index_rating, index_number_runs, index_favorite,
                      index_category, index_system_short_name, index_system_folder_name, index_path_media_name)
import rom_grid

# Define the image / video size
image_scale = 1.2
image_size_x = int(224 * image_scale)
image_size_y = int(256 * image_scale)

# Define any dataclasses
@dataclass
class RomInfo:
    rom_name: str = ''
    rom_file_name: str = ''
    rom_type: str = ''
    system_file_name: str = ''
    game_rating: int = 0
    short_name: str = ''
    favorites_flag: int = 0
    system_folder_name: str = ''

MESSAGE_DELIMITER = '-' * 100 + '\n'

# ROM list views: language-neutral keys and their filters (see views.py)
VIEW_KEYS = views.VIEW_KEYS
VIEW_FILTERS = views.VIEW_FILTERS

BACKUP_FILES = backup.BACKUP_FILES   # Files included in a settings backup (see backup.py)

VIDEO_TIMER_DELAY = 5 # Seconds for countdown
FADE_IN_SECONDS = 0.3           # How long the main window takes to fade in at start-up, see fade_in

FILTER_CACHE_SIZE = 32          # Most filtered ROM lists (views) kept in memory, see populate_list
MESSAGES_MAX_LINES = 5000       # Lines kept in the Messages window, see messages_append

# Set when a restart has been asked for.  When the main window then closes, the main loop at the bottom of this file
# starts pfeMAME again from scratch.
restart_requested = False

# Ensure we are operating in the correct path.  THis fixes macOS localisation issues when frozen.
if getattr(sys, 'frozen', False):
    application_path = os.path.dirname(sys.executable)
    os.chdir(application_path)

_ = functions.set_up_language()  # Set up the application language

# This is the mainloop class and is the program entry point
class MainFrame(wx.Frame):
    def __init__(self):
        wx.Frame.__init__(self,
                          None,
                          -1,
                          f'pfeMAME {__version__}',
                          pos=wx.Point(0, 0),
                          size=wx.Size(-1, -1),
                          style=wx.DEFAULT_FRAME_STYLE)

        # --------------------------------------------------------------------------------------------------------------
        self.initialize_member_variables()
        self.setup_ini_variables()

        # --------------------------------------------------------------------------------------------------------------
        # Make the message box background colors the same as the main panel
        self.message_window_background_color = self.application_colors['window_background']

        # --------------------------------------------------------------------------------------------------------------
        # Go through setting everything up
        self.setup_platform()
        self.setup_startup_state()
        self.setup_logging_and_pubsub()
        self.load_alternate_emulator_engines()
        self.log_platform_type()
        self.initialize_runtime_variables_and_timers()  # this new method for runtime vars, timers, menubar
        self.capture_key_bindings()
        self.setup_joystick()
        self.build_gui_elements()
        self.set_version_information()

        # --------------------------------------------------------------------------------------------------------------
        # Pre-load the history & mameinfo.dat files (Assuming they exist)
        # This is done in a thread to speed the startup process up and prevent any blocking issues
        self.load_info_files()


        # --------------------------------------------------------------------------------------------------------------
        # Check to see if there are any software updates available
        if self.pref_check_software_version == 'True':
            self.check_for_updates('auto')
        functions.debug_type_print(self.development, self.debug_start_time, 'Starting software update check process',
                                   self.development_startup_info)

        # --------------------------------------------------------------------------------------------------------------
        # Check if the application restarted from an internal forced restart
        if self.forced_restart != '':
            self.my_logger.info(self.forced_restart)
            self.messages_append(f'{self.forced_restart}\n', False)

        # --------------------------------------------------------------------------------------------------------------
        # Call the processes that must happen after the main display is drawn.  These include database setup, checks etc
        # They wait for the window to finish fading in, so the fade isn't held up and their messages show over it.
        self.when_window_shown(self.initial_setup)

        # --------------------------------------------------------------------------------------------------------------
        # Give the ROMs list the focus
        self.list.SetFocus()
        self.Refresh()

        # --------------------------------------------------------------------------------------------------------------
        # Allow any changed to the filter list to cause the ROM list to be repopulated
        self.blockFilter = False

        # --------------------------------------------------------------------------------------------------------------
        # If we are in developer mode then display developer startup information
        if self.development:
            self.messages_append(_('Developer mode enabled\n'))
            for line in self.development_startup_info:
                self.messages_append(line)

        # --------------------------------------------------------------------------------------------------------------
        # Capture mouse events just so that we can reset the inactivity timer if the mouse is moved
        self.bind_mouse_events_recursively(self)

        # --------------------------------------------------------------------------------------------------------------
        # Capture the main window resize event
        self.Bind(wx.EVT_SIZE, self.on_resize)

        # --------------------------------------------------------------------------------------------------------------
        # All startup actions complete
        elapsed_time = time.time() - self.startup_process_start_time
        msg = _('Application startup complete in {:.2f} seconds').format(elapsed_time)
        self.my_logger.info(msg)
        self.messages_append(f'{msg}\n', True)
        self.start_up_complete = True  # Used by the single click event handler

    # ------------------------------------------------------------------------------------------------------------------
    # Process any cleanup actions needed when the window is resized
    def on_resize(self, event):
        new_size = event.GetSize()
        old_size = getattr(self, '_last_frame_size', None)
        self._last_frame_size = new_size
        if old_size is not None and new_size != old_size:
            self.video_stop()
        event.Skip()

    # --------------------------------------------------------------------------------------------------------------
    def initialize_member_variables(self):
        self.language = iniFile.read_ini_file('preferences', 'language', 'english')
        self.path_to_me = functions.path_to_me()
        self.default_image_file_name = os.path.join(self.path_to_me, 'images', 'default.gif')
        self.data_dir = functions.data_dir()   # User data (pfemame.ini, *.dat, ROM database, log) - see app_paths.py
        self.play_stats = play_stats.PlayStats(os.path.join(self.data_dir, play_stats.FILE_NAME))
        self.my_logger = functions.setup_logging(self.data_dir)
        program_cleanup.log_results(self.my_logger)    # What the start-up clean-up of lib/ removed, if anything

        self.filtercolumn_cache = 0
        self.filtervalue_cache = ''
        self.timerSeconds = VIDEO_TIMER_DELAY
        self.categories = []
        self.image_options = []
        self.cacheDate = ''
        self.lastromselected = ''
        self.lastsystemselected = ''
        self.lastviewselected = ''
        self.prefCheckDatabaseAge = ''
        self.prefUseLastSelected = ''
        self.pref_icon_size = ''
        self.pref_show_rom_icons = ''
        self.prefMainView = ''
        self.pref_highlight_missing = ''
        self.prefDaysCheckCache = ''
        self.prefScreenSaverTime = 0  # Minutes, 0 = screensaver off
        self.folders_icons = ''
        self.foldersVideo = ''
        self.folder_mapping = ''
        self.path_mame_exe = ''
        self.mame_version = ''
        self._mame_version_known = False        # Set once MAME has answered (see set_version_information)
        self._mame_version_waiting = []         # Callbacks waiting for the MAME version
        self._window_shown = False              # Set once the window has faded in (see fade_in)
        self._window_shown_waiting = []         # Callbacks waiting for that
        self._search_timer = None
        self.pathHistory = ''
        self.pathMAMEInfoDat = ''
        self.pathCatver = ''
        self.prefView = ''
        self.prefSystemsSupport = ''
        self.prefVideoAutoload = ''
        self.prefVideoDisable = ''
        self.prefClickFavRating = ''
        self.pref_short_name_global_suppress = ''
        self.pref_full_systems_method = False
        self.path_to_mame_ini_file = ''
        self.application_colors = {}
        self.pref_check_catver_version = ''
        self.pref_check_software_version = ''
        self.pref_flash_messages_if_error = ''
        self.pref_joystick_selected = ''
        self.pref_enable_joystick_mainview = ''
        self.set_window_fullscreen = ''
        self.pref_recall_column_widths = ''
        self.global_font_bold = wx.SystemSettings.GetFont(wx.SYS_DEFAULT_GUI_FONT)
        self.global_font_normal = wx.SystemSettings.GetFont(wx.SYS_DEFAULT_GUI_FONT)
        self.global_font_normal_8 = wx.SystemSettings.GetFont(wx.SYS_DEFAULT_GUI_FONT)
        self.folders_roms = ''
        self.folders_systems = ''
        self.rom_folders: list[str] = []    # Resolved rompath folders (see functions.split_mame_paths)
        self.folders_samples = ''
        self.foldersSnap = ''
        self.folder_ini = ''
        self.folderInput = ''
        self.folder_config = ''

        # Set of MAME machine (ROM) names that are 'systems' - i.e. they expose one or more software lists (or
        # loadable media) in the -listxml output.  Populated during the ROMs database build.
        self.system_rom_names = set()

    # ------------------------------------------------------------------------------------------------------------------
    def setup_platform(self):
        self.system = functions.get_platform()

    # ------------------------------------------------------------------------------------------------------------------
    def setup_startup_state(self):
        self.run_specified_rom = False
        self.forced_restart = ''
        self.process_args()
        self.development_startup_info = []
        self.startup_process_start_time = time.time()
        self.debug_start_time = time.time()

        try:
            locale.setlocale(locale.LC_ALL, '')
        except locale.Error:        # e.g. Linux with a LANG setting that isn't installed - keep the default
            pass

    def setup_logging_and_pubsub(self):
        self.start_up_complete = False  # Used by the single click event handler

        # Set app icon
        self.SetIcon(wx.Icon(os.path.join(self.path_to_me, 'images', 'pfemame.ico'), wx.BITMAP_TYPE_ANY))

        # Change working directory to the executable's directory
        os.chdir(os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(
            os.path.abspath(__file__)))

        # Setup pubsub subscriptions
        pub.subscribe(self.update_display_messages, 'update')
        pub.subscribe(self.update_logfile, 'log')
        pub.subscribe(self.update_display_popups, 'popup')
        pub.subscribe(self.update_display_number_of_runs, 'number_of_runs')
        pub.subscribe(self.on_rom_played, 'rom_played')
        pub.subscribe(self.enable_alert_timer, 'enable_alert_timer')
        pub.subscribe(self.update_status, 'status')
        pub.subscribe(self.setup_ini_variables, 'setup_ini')
        pub.subscribe(self.on_force_restart, 'force_restart')
        pub.subscribe(self.on_restart_now, 'restart_now')
        pub.subscribe(self.on_refresh_window, 'refresh_window')


    # --------------------------------------------------------------------------------------------------------------
    # This is the window refresh handler use by PubSub requests
    def on_refresh_window(self):
        self.Refresh()

    # --------------------------------------------------------------------------------------------------------------
    # Load the alternate emulation engine data
    def load_alternate_emulator_engines(self):
        (self.alternate_emulation_engines,
         self.alternate_emulation_engines_error) = functions.load_other_emulators_detail(self.path_to_me)

    # --------------------------------------------------------------------------------------------------------------
    # Log various versions information
    def log_platform_type(self):
        info = [
            _('Application Started'),
            f'Platform: {sys.platform}',
            f'Python Version: {sys.version}',
            f'WX Version: {wx.version()}',
        ]

        for x in info:
            self.my_logger.info(x)

    # --------------------------------------------------------------------------------------------------------------
    # Set some other default variables
    def initialize_runtime_variables_and_timers(self):
        self._app_closing = False
        self._info_files_loading = False            # True while load_info_files runs in its thread
        self._database_build_running = False        # True while rom_database.build runs in its thread
        self._database_build_cancel = threading.Event()
        self._database_build_progress = None        # Latest (message, done, total) from the build thread
        self._database_build_busy = None            # 'Please wait' window shown until the progress bar takes over
        self._database_progress_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._show_database_build_progress, self._database_progress_timer)
        self._skip_ini_save_on_close = False  # Set after a settings restore so the restored INI is kept
        self._video_folder_cache = {}  # {stem: full_path}
        self._video_folder_cached_path = ''  # which folder the cache was built from
        self.sort_column = -1  # which column is currently sorted
        self.sort_ascending = True  # sort direction
        self.selected_row = -1
        self.mylist = []
        self.mylist_filtered = []
        self.filter_cache = {}  # cache: (filtercolumn, filtervalue.lower()) -> filtered list
        self.history_data = ''
        self.mame_info_data = ''
        self.blockFilter = True
        self.video_to_play = ''
        self.availableRoms = 0
        self.alert_colors_decrement_value = 16
        self.alert_colors_value = 240
        self.tileview_running = False
        self.joystick_block = False
        self.inactivity_timer_block = False
        self.image_options_index = 0  # Start with Snapshots displayed
        self.overlay_image = wx.Bitmap(os.path.join(self.path_to_me, 'images', 'lg2.png'), wx.BITMAP_TYPE_ANY)
        self.overlay_image_size = self.overlay_image.GetSize()

        functions.debug_type_print(self.development, self.debug_start_time, 'Initial variables set',
                                   self.development_startup_info)

        # --------------------------------------------------------------------------------------------------------------
        # Set up the alert timer
        self.alert_timer = wx.Timer(self, id=9991)
        self.Bind(wx.EVT_TIMER, self.on_timer_event, self.alert_timer)

        # --------------------------------------------------------------------------------------------------------------
        # Set up the inactivity timer and start it.  This is used for the screensaver.
        self.inactivity_timer = wx.Timer(self, id=9992)
        self.Bind(wx.EVT_TIMER, self.on_timer_event, self.inactivity_timer)
        self.inactivity_timer_start()

        # --------------------------------------------------------------------------------------------------------------
        # Set up the video playback countdown timer.
        self.video_playback_timer = wx.Timer(self, id=9994)
        self.timerSeconds = VIDEO_TIMER_DELAY
        self._pending_play = None  # Handle to the deferred autoload play (wx.CallLater)
        self.Bind(wx.EVT_TIMER, self.on_timer_event, self.video_playback_timer)

    # ------------------------------------------------------------------------------------------------------------------
    def capture_key_bindings(self):
        # Create key bindings for quick menu access options
        # CTRL-F will trigger a search event from anywhere
        # CTRL-P opens default preferences
        # CTRL-SHIFT-P opens rom specific preferences
        # F11 opens the fullscreen video player
        #
        # NOTE: Every accelerator must have a handler, and must not use a plain (or SHIFT+) printable key.  An
        # accelerator swallows its key before any text control sees it - the old SHIFT-F entry made it impossible
        # to type a capital 'F' in the search box.

        self.Bind(wx.EVT_MENU, self.on_find, id=301)
        self.Bind(wx.EVT_MENU, self.on_preferences_default, id=302)
        self.Bind(wx.EVT_MENU, self.preferences_rom_specific, id=303)
        self.Bind(wx.EVT_MENU, self.on_fullscreen_video_player, id=304)
        self.Bind(wx.EVT_CLOSE, self.on_close)

        entries = [wx.AcceleratorEntry() for _i in range(4)]
        entries[0].Set(wx.ACCEL_CTRL, ord('F'), 301)
        entries[1].Set(wx.ACCEL_CTRL, ord('P'), 302)
        entries[2].Set(wx.ACCEL_CTRL | wx.ACCEL_SHIFT, ord('P'), 303)
        entries[3].Set(wx.ACCEL_NORMAL, wx.WXK_F11, 304)

        accel = wx.AcceleratorTable(entries)
        self.SetAcceleratorTable(accel)

    # ------------------------------------------------------------------------------------------------------------------
    def setup_joystick(self):
        # Try to capture the joystick for navigation and determine the directional
        # values for the stick / dpad

        (self.joystick,
         self.joystick_polling_timer,
         self.joystickXMin,
         self.joystickXMax,
         self.joystickYMin,
         self.joystickYMax) = functions.joystick_setup(self, self.my_logger, self.pref_joystick_selected)

    # ------------------------------------------------------------------------------------------------------------------
    def build_gui_elements(self):
        """
        Set up the various GUI elements
        """
        self._setup_panels()
        self._setup_sizers()
        self._setup_toolbar()
        self._setup_view_combobox()
        self._setup_search_field()
        self._setup_versions_field()
        self._setup_age_fields()
        self.create_image_option_selector()
        self._setup_rom_list()
        self._rom_image_placeholder()
        self._setup_media_control()
        self.setup_info_notebook()
        self._setup_messages_window()
        self._add_rom_categories()
        self.sizer_horizontal_main.Add(self.sizer_image_video, proportion=0, flag=wx.EXPAND, border=1)
        self._set_logger_target()
        self._add_statusbar()
        self._lay_out_window()
        self._setup_progress_bar()
        self._show_the_window()

    # ------------------------------------------------------------------------------------------------------------------
    # Set up various window panels
    def _setup_panels(self):
        self.panel = wx.Panel(self)

        # Apply fonts and colors from your app-wide theme
        self.panel.SetFont(self.global_font_normal)
        self.panel.SetBackgroundColour(self.application_colors['window_background'])

    # ------------------------------------------------------------------------------------------------------------------
    def _setup_sizers(self):
        """
        Layout: Vertical box with:
        - Toolbar
        - Top filter/search/version area
        - Main area: left = categories, right = rom list/media
        """

        self.sizer = wx.BoxSizer(wx.VERTICAL)
        self.sizer_toolbar = wx.BoxSizer(wx.HORIZONTAL)
        self.sizer_horizontal_top = wx.BoxSizer(wx.HORIZONTAL)
        self.sizer_horizontal_main = wx.BoxSizer(wx.HORIZONTAL)
        self.sizer_vertical_main = wx.BoxSizer(wx.VERTICAL)
        self.sizer_messages = wx.BoxSizer(wx.VERTICAL)
        self.sizer_image_video = wx.BoxSizer(wx.VERTICAL)

        # Add toolbar and spacing
        self.sizer.Add(self.sizer_toolbar, proportion=0, flag=wx.EXPAND)
        self.sizer.AddSpacer(self.FromDIP(4))

        # Add top and main layout sections
        self.sizer.Add(self.sizer_horizontal_top, proportion=0, flag=wx.EXPAND, border=1)
        self.sizer.Add(self.sizer_horizontal_main, proportion=1, flag=wx.EXPAND, border=1)

        functions.debug_type_print(self.development, self.debug_start_time, 'Main sizers defined',
                                   self.development_startup_info)

    # ------------------------------------------------------------------------------------------------------------------
    # Set up the window toolbar
    def _setup_toolbar(self):
        self.ribbon_bar = pfemame_ribbon_bar.RibbonWebView(self.panel, self)
        self.ribbon_bar.SetMinSize(wx.Size(-1, 100))
        self.sizer_toolbar.Add(self.ribbon_bar, 1, wx.EXPAND)
        functions.debug_type_print(self.development, self.debug_start_time, 'Ribbon Bar creation',
                                   self.development_startup_info)

    # ------------------------------------------------------------------------------------------------------------------
    # Create the 'view' combobox
    def _setup_view_combobox(self):
        text_view = wx.StaticText(self.panel, -1, _('View:'), style=wx.ALIGN_CENTER_VERTICAL)
        text_view.SetFont(self.global_font_bold)
        text_view.SetForegroundColour(self.application_colors['text'])

        self.sizer_horizontal_top.Add(text_view,
                                      proportion=0,
                                      flag=wx.ALL | wx.ALIGN_CENTER_VERTICAL,
                                      border=self.FromDIP(4)
                                      )

        self.comboBoxFilter = ModernDropdown(self.panel,
                                             choices=self.view_labels(),
                                             size=self.FromDIP(wx.Size(200, 25))
                                             )
        self.comboBoxFilter.Bind(EVT_DROPDOWN_SELECTION, self.on_filter_rom_list)
        self.comboBoxFilter.SetBackgroundColour(self.application_colors['window_background'])
        self.comboBoxFilter.SetForegroundColour(self.application_colors['text'])
        self.comboBoxFilter.SetScrollbarColor(self.application_colors['scrollbar_thumb'],
                                              self.application_colors['scrollbar_track'])

        self.sizer_horizontal_top.AddSpacer(self.FromDIP(4))
        self.sizer_horizontal_top.Add(self.comboBoxFilter,
                                      proportion=0,
                                      flag=wx.ALL | wx.ALIGN_CENTER_VERTICAL,
                                      border=self.FromDIP(1))

    # --------------------------------------------------------------------------------------------------------------
    # View filter helpers.  The drop-down shows translated labels; everything else works with VIEW_KEYS.
    @staticmethod
    def view_labels() -> list[str]:
        """Translated labels for the view drop-down, in VIEW_KEYS order."""
        return views.view_labels(_)

    def normalize_view_key(self, value: str) -> str:
        """Map a view key, or a translated label (older pfemame.ini files stored those), to a VIEW_KEYS key."""
        return views.normalize_view_key(value, _)

    def get_view_key(self) -> str:
        """The language-neutral key for the view currently selected in the drop-down."""
        index = self.comboBoxFilter.GetSelection()
        if 0 <= index < len(VIEW_KEYS):
            return VIEW_KEYS[index]
        return self.normalize_view_key(self.comboBoxFilter.GetValue())

    def set_view_key(self, key: str) -> None:
        """Show the given view (key or legacy label) in the drop-down without triggering a filter event."""
        self.comboBoxFilter.SetValue(self.view_labels()[VIEW_KEYS.index(self.normalize_view_key(key))])

    # --------------------------------------------------------------------------------------------------------------
    # Create a search entry field
    def _setup_search_field(self):
        self.clear_event_override = False
        self.sizer_horizontal_top.AddSpacer(self.FromDIP(4))  # Spacer between combobox and search field
        self.controlSearch = wx.SearchCtrl(
                                     self.panel,
                                           style=wx.TE_PROCESS_ENTER,
                                           size=self.FromDIP(wx.Size(200, -1))
                                          )
        self.controlSearch.ShowCancelButton(True)
        self.controlSearch.SetToolTip(_(search.HELP_TEXT))
        self.controlSearch.SetBackgroundColour(self.application_colors['window_background'])
        self.controlSearch.SetForegroundColour(self.application_colors['text'])
        self.sizer_horizontal_top.Add(self.controlSearch,
                                      proportion=0,
                                      flag=wx.ALL | wx.ALIGN_CENTER_VERTICAL,
                                      border=self.FromDIP(1))
        self.controlSearch.Bind(wx.EVT_TEXT, self.on_search_dynamic)

    # ------------------------------------------------------------------------------------------------------------------
    # Create the versions text fields
    def _setup_versions_field(self):
        text = wx.StaticText(self.panel, -1, _('MAME Version: '), style=wx.ALIGN_LEFT)
        text.SetFont(self.global_font_bold)
        text.SetForegroundColour(self.application_colors['text'])

        self.text_version_mame = wx.StaticText(self.panel, -1, _('Unknown'), style=wx.ALIGN_LEFT)
        self.text_version_mame.SetForegroundColour(self.application_colors['text'])

        self.sizer_horizontal_top.AddStretchSpacer()

        self.sizer_horizontal_top.Add(text, proportion=0,
                                      flag=wx.ALL | wx.ALIGN_CENTER_VERTICAL, border=self.FromDIP(1))

        self.sizer_horizontal_top.Add(self.text_version_mame, proportion=0,
                                      flag=wx.ALL | wx.ALIGN_CENTER_VERTICAL, border=self.FromDIP(1))

    # --------------------------------------------------------------------------------------------------------------
    # Create the database age text fields
    def _setup_age_fields(self):
        text_database_age = wx.StaticText(self.panel, -1, _('Database Age: '), style=wx.ALIGN_LEFT)
        text_database_age.SetFont(self.global_font_bold)
        text_database_age.SetForegroundColour(self.application_colors['text'])

        self.text_database_ageValue = wx.StaticText(self.panel, -1, _('Unknown'), style=wx.ALIGN_LEFT)
        self.text_database_ageValue.SetForegroundColour(self.application_colors['text'])

        self.sizer_horizontal_top.AddSpacer(self.FromDIP(8))  # Spacer between version and age fields

        self.sizer_horizontal_top.Add(text_database_age, proportion=0,
                                      flag=wx.ALL | wx.ALIGN_CENTER_VERTICAL, border=self.FromDIP(1))

        self.sizer_horizontal_top.Add(self.text_database_ageValue, proportion=0,
                                      flag=wx.ALL | wx.ALIGN_CENTER_VERTICAL, border=self.FromDIP(1))

    # --------------------------------------------------------------------------------------------------------------
    # Create the ROM list control
    def _setup_rom_list(self):
        self.list_notebook = flatnotebook.FlatNotebook(self.panel, agwStyle=flatnotebook.FNB_NO_NAV_BUTTONS |
                                                                            flatnotebook.FNB_NO_X_BUTTON |
                                                                            flatnotebook.FNB_TABS_BORDER_SIMPLE |
                                                                            flatnotebook.FNB_NODRAG |
                                                                            flatnotebook.FNB_SMART_TABS
                                                       )
        self.list_notebook.Bind(flatnotebook.EVT_FLATNOTEBOOK_PAGE_CHANGED, self.notebook_page_changed)
        self.list_notebook.Bind(flatnotebook.EVT_FLATNOTEBOOK_PAGE_CHANGING, self.notebook_page_changing)

        self.list_notebook.SetActiveTabColour(self.application_colors['window_background'])
        self.list_notebook.SetTabAreaColour(self.application_colors['control_bar'])
        self.list_notebook.SetNonActiveTabTextColour(self.application_colors['text'])
        self.list_notebook.SetForegroundColour(self.application_colors['text'])
        self.list_notebook.SetBackgroundColour(self.application_colors['window_background'])
        self.list_notebook.SetActiveTabTextColour(self.application_colors['text'])

        self.list = RomGrid(self.list_notebook,
                            self.pref_icon_size,
                            self.pref_show_rom_icons,
                            self.folders_icons,
                            self.pref_highlight_missing,
                            self.application_colors,
                            self.my_logger)  # This is the ROM list grid control class

        self.list.SetDefaultCellFont(self.global_font_normal_8)
        self.list.SetSelectedRowForegroundColor(self.application_colors['selected_row'])
        self.list.SetSelectedRowBackgroundColor(self.application_colors['selected_row_background'])

        self.list.Bind(wx.grid.EVT_GRID_SELECT_CELL,      self.on_single_click)
        self.list.Bind(wx.grid.EVT_GRID_CELL_LEFT_DCLICK, self.on_double_click)
        self.list.Bind(wx.grid.EVT_GRID_CELL_RIGHT_CLICK,  self.on_right_down)
        self.list.Bind(wx.EVT_CHAR_HOOK,                  self.on_key_press)
        self.list.Bind(wx.grid.EVT_GRID_LABEL_LEFT_CLICK, self.on_column_clicked)

        self.list_notebook.AddPage(self.list, _('ROMs List'))

        # File Paths tab (index 1) — embedded panel replaces the old popup window
        self.filepaths_panel = filepaths.FilePaths(parent=self.list_notebook, my_logger=self.my_logger)
        self.list_notebook.AddPage(self.filepaths_panel, _('File Paths'))

        self.preferences_panel = preferences.Preferences(parent=self.list_notebook,
                                                         title=_('Default Preferences'),
                                                         mode='default',
                                                         rom_file_name='',
                                                         folder_ini='',
                                                         path_executable='',
                                                         system_file_name='')
        self.list_notebook.AddPage(self.preferences_panel, _('pfeMAME Preferences'))

        self.sizer_vertical_main.Add(self.list_notebook,
                                     proportion=1,
                                     flag=wx.EXPAND,
                                     border=1)  # Add the control to the sizer

    # --------------------------------------------------------------------------------------------------------------
    # Insert a placeholder for the ROM image - this is just a blank bitmap for now
    def _rom_image_placeholder(self):
        self.image_panel = ImagePanel(self.panel, image_size_x, image_size_y, self.list, main_frame=self)
        # Attach drop target to panel
        drop_target = MyFileDropTarget(self.on_files_dropped)
        self.image_panel.SetDropTarget(drop_target)
        
        self.sizer_image_video.Add(self.image_panel,
                                   proportion=0,
                                   flag=wx.ALL | wx.ALIGN_CENTER_HORIZONTAL,
                                   border=self.FromDIP(4)
                                   )

        # Common UI element for 'No video available'
        self.videoLoadCaption = wx.Button(
                                    self.panel,
                                          -1,
                                          label=_('No Video Available'),
                                          size=self.FromDIP(wx.Size(224, 20))
                                        )
        self.videoLoadCaption.Bind(wx.EVT_BUTTON, self.on_play_clicked)

    # --------------------------------------------------------------------------------------------------------------
    # Add the media player control
    # It starts off hidden as it is designed to occupy the same space as the ROM image (one will hide and the other
    # will show)
    def _setup_media_control(self):
        self.media_player_available = True
        self.video_player = Video(
                                  parent_panel=self.panel,
                                  logger=self.my_logger,
                                  image_panel=self.image_panel,
                                  video_caption_label=self.videoLoadCaption,
                                  use_video_caption=True,
                                  video_path=self.video_to_play,
                                  horizontal_size=image_size_x,
                                  vertical_size=image_size_y
                                  )
        self.video_stop()

        # Add the video player and caption to the panel
        self.sizer_image_video.Add(self.video_player.video_panel, proportion=0, flag=wx.EXPAND | wx.ALL, border=self.FromDIP(0))
        self.sizer_image_video.Add(self.videoLoadCaption, proportion=0, flag=wx.EXPAND, border=self.FromDIP(0))

    # --------------------------------------------------------------------------------------------------------------
    # Add the messages box
    def _setup_messages_window(self):
        label_messages = wx.StaticText(self.panel, -1, _('Messages:'))
        label_messages.SetFont(self.global_font_bold)
        label_messages.SetForegroundColour(self.application_colors['text'])
        label_messages.SetBackgroundColour(self.application_colors['text_background'])

        self.controlMessages = CustomTextCtrl(self.panel, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.NO_BORDER)
        self.controlMessages.SetFont(self.global_font_normal_8)
        self.controlMessages.SetBackgroundColour(self.message_window_background_color)
        self.controlMessages.SetForegroundColour(self.application_colors['text'])
        self.controlMessages.SetScrollbarThumbColor(self.application_colors['scrollbar_thumb'])
        self.controlMessages.SetScrollbarTrackColor(self.application_colors['scrollbar_track'])
        self.controlMessages.Bind(wx.EVT_LEFT_DCLICK, self.disable_alert_timer)

        self.controlMessages.SetMinSize(self.FromDIP(wx.Size(400, 120)))
        self.controlMessages.SetMaxLines(MESSAGES_MAX_LINES)     # The oldest messages are dropped after this

        self.sizer_messages.Add(label_messages, proportion=0,
                                flag=wx.ALL | wx.ALIGN_LEFT,
                                border=self.FromDIP(2))

        self.sizer_messages.Add(self.controlMessages,
                                proportion=1,
                                flag=wx.EXPAND | wx.ALL,
                                border=self.FromDIP(2))

        self.sizer_vertical_main.Add(self.sizer_messages,
                                     proportion=0,
                                     flag=wx.EXPAND,
                                     border=self.FromDIP(4)
                                     )

        self.sizer_horizontal_main.Add(self.sizer_vertical_main,
                                       proportion=1,
                                       flag=wx.EXPAND | wx.ALL,
                                       border=self.FromDIP(4)
                                       )

    # ------------------------------------------------------------------------------------------------------------------
    # Build the ROM categories, create the categories box and setup
    def _add_rom_categories(self):
        self.category_dict, self.catver_version = self.add_rom_categories()

    # ------------------------------------------------------------------------------------------------------------------
    # Add the override for wx.Log messages
    def _set_logger_target(self):
        wx.Log.SetActiveTarget(
            functions.MyLog(self.controlMessages, self.my_logger))  # All wx.Log messages will go to the messages box

    # ------------------------------------------------------------------------------------------------------------------
    # Add the custom status bar panel
    def _add_statusbar(self):
        self.statusbar_panel = functions.StatusBarPanel(self.panel)
        self.sizer.Add(self.statusbar_panel, proportion=0,
                       flag=wx.EXPAND | wx.TOP,
                       border=self.FromDIP(2))

    # ------------------------------------------------------------------------------------------------------------------
    # Get the window to size automatically based upon sizer requirements
    def _lay_out_window(self):
        self.panel.SetSizer(self.sizer)
        self.sizer.Fit(self)
        self.Layout()

    # ------------------------------------------------------------------------------------------------------------------
    # Initialise the progress bar
    def _setup_progress_bar(self):
        self.progress_bar = self.create_progress_bar()

    # ------------------------------------------------------------------------------------------------------------------
    # Position the frame and make it visible
    def _show_the_window(self):
        self.Centre()
        # Set the window to fullscreen if the preference is set - before it is shown, so it fades in at its full size
        if self.set_window_fullscreen == 'True':
            self.Maximize()
        if wx.Platform == '__WXGTK__':
            self.Show()  # Just show without fading
            self.Raise()  # Bring to front
            self.Update()  # Force immediate refresh
            self._window_is_shown()
        else:
            wx.CallAfter(self.fade_in)

        functions.debug_type_print(self.development, self.debug_start_time, 'Set size and display window',
                                   self.development_startup_info)

    # ------------------------------------------------------------------------------------------------------------------
    # Fade the window in - ooooh, pretty!
    def fade_in(self):
        """
        Show the window and fade it in with a timer.  The alpha follows the time since the fade started, so it stays
        smooth even when a timer tick arrives late, and nothing else runs in between (start-up work waits for
        when_window_shown) - so a message box can't stop it half-way.
        """
        if not self:            # The window was closed before it was shown
            return
        if not self.SetTransparent(0):      # Fully transparent - or the platform can't do it, so just show it
            self.Show()
            self._window_is_shown()
            return
        self.Show()
        self.Update()           # Paint it while still invisible, so it doesn't appear half-drawn

        self._fade_start = None             # Set by the first tick
        self._fade_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._on_fade_timer, self._fade_timer)
        self._fade_timer.Start(15)

    def _on_fade_timer(self, _event) -> None:
        """Fade timer tick: set the window's alpha for how far into the fade we are."""
        now = time.perf_counter()
        if self._fade_start is None:
            self._fade_start = now
        progress = min(1.0, (now - self._fade_start) / FADE_IN_SECONDS)
        if progress < 1.0:
            self.SetTransparent(int(255 * progress * progress * (3 - 2 * progress)))  # Ease in and out
            return
        self._fade_timer.Stop()
        self.SetTransparent(255)            # Fully opaque (on Windows this also drops the layered window style)
        self._window_is_shown()

    # ------------------------------------------------------------------------------------------------------------------
    def _window_is_shown(self) -> None:
        """The window is fully on screen - run whatever was waiting for it (see when_window_shown)."""
        self._window_shown = True
        waiting, self._window_shown_waiting = self._window_shown_waiting, []

        def run_waiting() -> None:
            # In order, each after the one before has finished - so a message box is closed before the next one runs
            for callback in waiting:
                if not self:        # The window was closed
                    return
                callback()

        wx.CallAfter(run_waiting)   # After this returns (some take a while or show a message box)

    # ------------------------------------------------------------------------------------------------------------------
    def when_window_shown(self, callback) -> None:
        """Run callback now if the window has finished fading in, otherwise as soon as it has (see fade_in)."""
        if self._window_shown:
            callback()
        else:
            self._window_shown_waiting.append(callback)

    # ------------------------------------------------------------------------------------------------------------------
    # Store the MAME & pfeMAME version information
    def set_version_information(self):
        # Ask MAME for its version in the background so it doesn't hold up start-up.  Anything that needs the
        # version waits for it with when_mame_version_known() (e.g. the ROMs database - its cache is per MAME version
        # - and the catver.ini version check).
        self.mame_version = _('Unknown')
        self._mame_version_known = False
        self._mame_version_waiting = []
        self.text_version_mame.SetLabel('...')
        path_mame_exe = self.path_mame_exe

        def ask_mame() -> None:
            version, problem = functions.mame_version(path_mame_exe)
            wx.CallAfter(self._mame_version_found, version, problem)
        Thread(target=ask_mame, daemon=True).start()

        self.my_logger.info(f'pfeMAME version: {__version__}')  # Write to the log file
        if hasattr(sys, 'frozen'):
            text = _('Deployment build is frozen (cx_freeze)')
        else:
            text = _('Deployment build is source (i.e. not frozen)')
        self.my_logger.info(text)  # Write to the log file
        functions.debug_type_print(self.development, self.debug_start_time, _('Retrieved MAME & pfeMAME version'),
                                   self.development_startup_info)

    # ------------------------------------------------------------------------------------------------------------------
    def _mame_version_found(self, version: str, problem: str) -> None:
        """GUI-thread half of set_version_information: store the version and run whatever was waiting for it."""
        if not self:            # The window was closed before MAME answered
            return
        self.mame_version = version or _('Unknown')
        self.text_version_mame.SetLabel(self.mame_version)
        self.text_version_mame.GetParent().Layout()       # The label has changed width
        self.my_logger.info(f'MAME version: {self.mame_version}')  # Write to the log file
        if problem:
            self.my_logger.warning(f'Unable to get the MAME version: {problem}')
        self._mame_version_known = True
        waiting, self._mame_version_waiting = self._mame_version_waiting, []
        for callback in waiting:
            callback()

    # ------------------------------------------------------------------------------------------------------------------
    def when_mame_version_known(self, callback) -> None:
        """Run callback now if MAME's version is known, otherwise as soon as it is (see set_version_information)."""
        if self._mame_version_known:
            callback()
        else:
            self._mame_version_waiting.append(callback)

    # ------------------------------------------------------------------------------------------------------------------
    def bind_mouse_events_recursively(self, widget):
        """
        Adds a mouse event binding to all controls
        :param widget: Widget to bind
        :return:
        """

        widget.Bind(wx.EVT_MOTION, self.on_mouse)
        widget.Bind(wx.EVT_ENTER_WINDOW, self.on_mouse)

        for child in widget.GetChildren():
            self.bind_mouse_events_recursively(child)

    # --------------------------------------------------------------------------------------------------------------
    # Create the progress bar
    def create_progress_bar(self) -> gauge.PyGauge:
        """
        Create and initialize a hidden horizontal progress bar.

        :returns: A PyGauge object representing the progress bar
        """
        # The progress bar and a Cancel button (for the ROMs database rebuild) share one area of the status bar
        self.progress_area = wx.Panel(self.statusbar_panel)
        self.progress_area.SetBackgroundColour(self.application_colors['control_bar'])
        progress_bar = gauge.PyGauge(
                                     self.progress_area,
                                     -1,
                                     style=wx.GA_HORIZONTAL | wx.GA_SMOOTH | wx.GA_PROGRESS
                                    )
        progress_bar.SetMinSize(self.FromDIP(wx.Size(250, 12)))

        # Set gradient bar color (start, end)
        progress_bar.SetBarColor([
                                  wx.Colour(162, 255, 178),  # light green
                                  wx.Colour(159, 176, 255)  # light blue
                                 ])

        self.progress_cancel_button = wx.Button(self.progress_area, -1, _('Cancel'), style=wx.BU_EXACTFIT)
        self.progress_cancel_button.SetFont(self.global_font_normal_8)
        self.progress_cancel_button.SetToolTip(_('Stop rebuilding the ROMs database'))
        self.progress_cancel_button.Bind(wx.EVT_BUTTON, self.on_cancel_database_build)

        area_sizer = wx.BoxSizer(wx.HORIZONTAL)
        area_sizer.Add(progress_bar, 0, wx.ALIGN_CENTER_VERTICAL)
        area_sizer.Add(self.progress_cancel_button, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, self.FromDIP(4))
        self.progress_area.SetSizer(area_sizer)

        self.progress_area.Hide()
        self.statusbar_panel.add_progress_bar(self.progress_area)
        return progress_bar

    # ------------------------------------------------------------------------------------------------------------------
    # Create the ROM categories label and scrollable panel.
    def create_rom_categories_ui(self):
        label = wx.StaticText(self.panel, -1, _('ROM Categories:'))
        label.SetFont(self.global_font_bold)
        label.SetForegroundColour(self.application_colors['text'])
        label.SetBackgroundColour(self.application_colors['text_background'])

        toggle_button = functions.build_one_button(self.panel, label=_('Toggle All'), handler=self.on_toggle_categories)

        self.panel_categories = CustomScrolledPanel(self.panel)
        self.panel_categories.SetMinSize(wx.Size(-1, 150))  # fix height to 150 pixels
        self.panel_categories.SetBackgroundColour(self.application_colors['window_background'])
        self.panel_categories.SetScrollbarThumbColor(self.application_colors['scrollbar_thumb'])
        self.panel_categories.SetScrollbarTrackColor(self.application_colors['scrollbar_track'])

        # Vertical sizer for layout
        self.category_sizer = wx.BoxSizer(wx.VERTICAL)
        self.sizer_horizontal_main.Add(self.category_sizer, proportion=0, flag=wx.EXPAND, border=1)
        self.category_sizer.Add(label, proportion=0, flag=wx.EXPAND, border=1)
        self.category_sizer.Add(toggle_button, proportion=0, flag=wx.EXPAND, border=1)
        self.category_sizer.Add(self.panel_categories, 1, wx.EXPAND | wx.ALL)

        functions.debug_type_print(self.development, self.debug_start_time, 'Controls creation',
                                   self.development_startup_info)

    # ------------------------------------------------------------------------------------------------------------------
    # Add the ROM categories box and populate it
    def add_rom_categories(self) -> tuple[dict[str, str], str]:
        """
        Add and populate the ROM categories panel.

        :returns:  Dictionary containing the categories and a string containg the categories file version
        """
        self.create_rom_categories_ui()
        self.categories = self.load_categories()
        functions.debug_type_print(self.development, self.debug_start_time, 'Categories created',
                                   self.development_startup_info)

        category_dict, catver_version = self.build_categories()

        self.Freeze()

        checkboxes = []
        for category in sorted(set(category_dict.values())):
            cb = wx.CheckBox(self.panel_categories.content, label=category, name=category)
            cb.Bind(wx.EVT_CHECKBOX, self.on_update_categories)
            cb.SetValue(category in self.categories)
            checkboxes.append(cb)

        self.panel_categories.add_widgets(checkboxes)    # One layout for all of them

        def set_color_and_font():
            for widget in self.panel_categories.content.GetChildren():
                widget.SetForegroundColour(self.application_colors['text'])
                widget.SetFont(self.global_font_normal_8)

        wx.CallAfter(set_color_and_font)
        self.Thaw()

        functions.debug_type_print(self.development, self.debug_start_time, 'ROM categories window populated',
                                   self.development_startup_info)
        return category_dict, catver_version

    # ------------------------------------------------------------------------------------------------------------------
    # Create the ROM Info and MAME info notebook controls
    def setup_info_notebook(self):
        def create_info_textctrl(parent, bind_url=False):
            """Helper to create a styled multiline read-only TextCtrl."""
            ctrl = CustomTextCtrl(parent, size=wx.Size(224, 310),
                                  style=wx.TE_MULTILINE | wx.TE_READONLY | wx.NO_BORDER | wx.TE_AUTO_URL | wx.TE_WORDWRAP)

            if bind_url:
                ctrl.Bind(wx.EVT_TEXT_URL, self.on_url_selected)
            ctrl.SetFont(self.global_font_normal_8)
            ctrl.SetBackgroundColour(self.message_window_background_color)
            ctrl.SetForegroundColour(self.application_colors['text'])
            ctrl.SetScrollbarThumbColor(self.application_colors['scrollbar_thumb'])
            ctrl.SetScrollbarTrackColor(self.application_colors['scrollbar_track'])
            return ctrl
        """Create notebook with ROM and MAME info text controls."""
        style_flags = (
                flatnotebook.FNB_NO_NAV_BUTTONS |
                flatnotebook.FNB_NO_X_BUTTON |
                flatnotebook.FNB_TABS_BORDER_SIMPLE |
                flatnotebook.FNB_NODRAG
        )

        notebook = flatnotebook.FlatNotebook(self.panel, agwStyle=style_flags)
        notebook.SetActiveTabColour(self.application_colors['window_background'])
        notebook.SetTabAreaColour(self.application_colors['control_bar'])
        notebook.SetNonActiveTabTextColour(self.application_colors['text'])
        notebook.SetForegroundColour(self.application_colors['text'])
        notebook.SetActiveTabTextColour(self.application_colors['text'])

        self.controlRomInfo = create_info_textctrl(notebook, bind_url=True)
        self.controlMAMEInfo = create_info_textctrl(notebook)

        notebook.AddPage(self.controlRomInfo, _('ROM Info'))
        notebook.AddPage(self.controlMAMEInfo, _('MAME Info'))

        self.sizer_image_video.Add(notebook, proportion=1, flag=wx.EXPAND, border=0)


    # --------------------------------------------------------------------------------------------------------------
    # Create the image option selector
    def create_image_option_selector(self):
        btn_size = wx.Size(20, 22)

        # Helper function to create a navigation button
        def create_nav_button(art_id: str, handler) -> wx.BitmapButton:
            bmp = wx.ArtProvider.GetBitmap(art_id, wx.ART_BUTTON, btn_size)
            btn = wx.BitmapButton(
                                  self.panel,
                                  bitmap=bmp,
                                  size=btn_size,
                                  style=wx.BORDER_NONE  # No border
                                 )
            btn.SetBackgroundColour(self.panel.GetBackgroundColour())  # Match parent background
            btn.SetWindowStyleFlag(wx.NO_BORDER)  # Optional: reinforce no border
            btn.Bind(wx.EVT_BUTTON, handler)
            return btn

        # Image option selector UI
        image_option_sizer = wx.BoxSizer(wx.HORIZONTAL)

        btn_left = create_nav_button(wx.ART_GO_BACK, lambda event: self.scroll_image_options(-1))
        btn_right = create_nav_button(wx.ART_GO_FORWARD, lambda event: self.scroll_image_options(1))

        self.image_option = wx.StaticText(self.panel,
                                          -1,
                                          '',
                                          size=wx.Size(image_size_x - 40, 20),
                                          style=wx.ALIGN_CENTER
                                          )
        self.image_option.SetForegroundColour(self.application_colors['text'])

        # Set initial label if options exist
        if self.image_options:
            self.image_option.SetLabel(_(self.image_options[self.image_options_index][1]))
        else:
            self.image_option.SetLabel(_('Empty'))

        # Add controls to sizer
        image_option_sizer.Add(btn_left, flag=wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, border=5)
        image_option_sizer.Add(self.image_option, flag=wx.ALIGN_CENTER_VERTICAL)
        image_option_sizer.Add(btn_right, flag=wx.ALIGN_CENTER_VERTICAL | wx.LEFT, border=5)

        # Add to parent sizer
        self.sizer_image_video.Add(image_option_sizer, proportion=0, flag=wx.EXPAND)

    # --------------------------------------------------------------------------------------------------------------
    def process_args(self) -> None:
        """
        Set up the argument parser for command line interface and process the arguments
        :return: None
        """
        args = self.set_up_arg_parser()

        self._handle_developer_mode(args.developer)

        if args.no_video:
            self._handle_disable_video()

        if args.force_restart:
            self._handle_force_restart()

        if args.version:
            self._handle_version_info()
            sys.exit()

        if args.count:
            self._handle_rom_count()
            sys.exit()

        if args.run:
            self._handle_run_rom(args.run)

        if args.language:
            self.language =  self._handle_language(args.language)

    def _send_windows_commands(self, messages: list[str]) -> None:
        """
        Send the Windows commands

        :param messages: List of commands to send
        :return:
        """
        if self.system == 'windows' and getattr(sys, 'frozen', False):
            def escaped(text: str) -> str:      # cmd.exe would treat these as command separators / redirection
                return re.sub(r'([&|<>^])', r'^\1', text)
            try:
                command = 'start cmd /K "' + ' & '.join(f'echo  - {escaped(msg)}' for msg in messages) + '"'
                os.system(command)
            except OSError:
                pass
        else:
            print('\n'.join(f' - {message}' for message in messages))

    def _handle_developer_mode(self, developer_arg: bool):
        self.development = developer_arg or __developer__ is True

    def _handle_disable_video(self):
        self._no_video_argument = True
        self.video_disable = True

    def _handle_force_restart(self) -> None:
        """
        Acknowledge that the application was restarted automatically (shown in the messages window once it exists)
        :return: None
        """
        print('Application was restarted automatically')
        self.forced_restart = _('pfeMAME was restarted automatically')

    def _handle_version_info(self) -> None:
        """
        Display version information
        :return: None
        """
        print('Retrieving version information')
        lines = [
            f'pfeMAME version {__version__}',
            f'MAME version {self.get_mame_version()}',
            f'Platform: {sys.platform}',
            f'Python Version: {sys.version}',
            f'WX Version: {wx.version()}'
        ]
        self._send_windows_commands(lines)

    def _handle_rom_count(self) -> None:
        """
        Display the number of ROMs
        :return: None
        """
        try:
            mylist, available_roms = self.load_database_file()
        except Exception:
            mylist = []
            available_roms = 0
        lines = [
            f'Number of ROMs: {len(mylist)}',
            f'ROMs that exist: {available_roms}'
        ]
        self._send_windows_commands(lines)

    def _handle_run_rom(self, rom_name: str) -> None:
        """
        Run ROM selected

        :param rom_name:
        :return:
        """
        self.specified_rom_name = rom_name
        self.run_specified_rom = True

    @staticmethod
    def _handle_language(language: str) -> str:
        """
        The language has already been saved in pfemame.ini and applied (see _store_language_argument at the top
        of this file, which has to run before the other modules are imported).

        :param language: This is the language we are asking to use
        :return: The language requested
        """
        language = language.lower()
        print(f'Language has been set to {language}')
        return language

    @staticmethod
    def set_up_arg_parser():
        parser = argparse.ArgumentParser(
            description=_("pfeMAME is a cross-platform front-end for the widely popular MAME emulation engine.\n"
                         "Please read the manual for a full description of the application and how to use it.\n"
                         "Please also rate pfeMAME at the SourceForge page you downloaded it from.\n"
                         "For additional requests, you can email pfemame@gmail.com."),
            epilog="Enjoy!"
        )

        parser.add_argument(
            '-d', '--developer',
            help='Enable developer mode',
            action='store_true'
        )

        parser.add_argument(
            '-novid', '--no_video',
            help='Disable video playback',
            action='store_true'
        )

        parser.add_argument(
            '-x', '--force_restart',
            help='Force a restart (for testing purposes)',
            action='store_true'
        )

        parser.add_argument(
            '-v', '--version',
            help='Display version information',
            action='store_true'
        )

        parser.add_argument(
            '-c', '--count',
            help='Display the ROM count from the database file',
            action='store_true'
        )

        parser.add_argument(
            '-r', '--run',
            help='Run the specified ROM file',
            type=str,
            metavar='ROM_FILE'
        )

        parser.add_argument(
            '-l', '--language',
            help='Set the application language',
            type=str,
            choices=LANGUAGES
        )

        parser.add_argument(
            '--check-libs',
            help='Linux: list any system libraries pfeMAME needs that are missing, and the packages that provide them',
            action='store_true'     # Handled at the very top of pfemame.py, before wx is loaded
        )
        args = parser.parse_args()
        return args

    # ------------------------------------------------------------------------------------------------------------------
    # Recall the last selected ROM
    def recall_last_selected_rom(self) -> None:
        """
        Restore the last selected ROM and view if preferences allow.

        :return: None
        """

        use_last_selection = (
                self.lastviewselected and
                self.prefUseLastSelected == 'True' and
                self.lastromselected
        )

        if use_last_selection:
            # Set the filter view.  Older pfemame.ini files stored the translated label, so normalise it first.
            view_key = self.normalize_view_key(self.lastviewselected)
            self.set_view_key(view_key)

            # Process the filter to only show what we want to see
            filtercolumn, filtervalue = VIEW_FILTERS[view_key]

            filtered_rom_count = self.populate_list(
                filtercolumn=filtercolumn,
                filtervalue=filtervalue,
                read_from_cache=False
            )

            self.update_rom_numbers(filtered_rom_count)


            last_rom = self.lastromselected
            last_system = self.lastsystemselected

            # Try to match ROM name
            match_index = next(
                (i for i, x in enumerate(self.mylist_filtered) if x[index_rom_name] == last_rom),
                None
            )

            # If also system-specific and matched, look for system ROM match *after* previous match
            if last_system and match_index is not None:
                start = match_index
                system_match = next(
                    (i for i, x in enumerate(self.mylist_filtered[start:]) if
                     x[index_system_program_file_name] == last_system),
                    None
                )
                if system_match is not None:
                    match_index = start + system_match

            # Select and scroll to the matched item
            if match_index is not None:
                self.list.Select(match_index)
                self.list.EnsureVisible(match_index)
        else:
            # Fallback: use the default (main view) filter and select first ROM if available
            view_key = self.normalize_view_key(self.prefMainView)
            self.set_view_key(view_key)
            if self.mylist:
                filtercolumn, filtervalue = VIEW_FILTERS[view_key]
                self.update_rom_numbers(self.populate_list(filtercolumn=filtercolumn,
                                                           filtervalue=filtervalue,
                                                           read_from_cache=False))

            if self.mylist and self.list.GetItemCount() > 0:
                self.list.Select(0)
                self.list.EnsureVisible(0)

    # --------------------------------------------------------------------------------------------------------------
    def initial_setup(self) -> None:
        """
        Process initial setups.  These are called after the main display is drawn as some of them call long-running
        tasks that would otherwise cause the display to lockup and not look right.
        """

        # --------------------------------------------------------------------------------------------------------------
        # If pfeMAME was closed (crash, kill, power cut) while a system program was running, the system's own INI
        # file is still parked as <rom>_backup.ini - put it back before anything else uses it.
        for ini_folder in functions.ini_search_folders(self.folder_ini, self.path_mame_exe, self.path_to_mame_ini_file):
            for rom in rungame.recover_stranded_system_inis(ini_folder):
                msg = _('Restored the INI file for {} left over from an unfinished system program run').format(rom)
                self.my_logger.info(msg)
                self.messages_append(f'{msg}\n')

        # The same for MAME's default.cfg, which holds a ROM's input mapping while that ROM runs
        try:
            if rungame.restore_default_cfg(self.folder_config):
                msg = _('Restored the default.cfg file left over from an unfinished game with an inputs mapping')
                self.my_logger.info(msg)
                self.messages_append(f'{msg}\n')
        except OSError as e:
            self.my_logger.error(f'Unable to restore default.cfg in {self.folder_config}: {e}')

        # --------------------------------------------------------------------------------------------------------------
        # Build up the ROM database, parse various flags, and format for final display.  If the database has to be
        # rebuilt this happens in a background thread, so the rest of the start-up continues once it is ready.
        self.on_database_refresh('auto', on_done=self._initial_setup_after_database)

    # ------------------------------------------------------------------------------------------------------------------
    def _initial_setup_after_database(self) -> None:
        """The part of initial_setup that needs the ROMs database (runs once it has been loaded or rebuilt)."""
        functions.debug_type_print(self.development, self.debug_start_time, 'ROMs database loaded',
                                   self.development_startup_info)

        # --------------------------------------------------------------------------------------------------------------
        # First-time run: if MAME executable is not set, switch directly to the File Paths tab so the user
        # is immediately prompted to configure paths rather than seeing an empty ROMs list.
        if not self.path_mame_exe:
            self._select_notebook_page(self.filepaths_panel)

        # --------------------------------------------------------------------------------------------------------------
        # If the preferences setting for recalling the last selected ROM is set, then do it
        self.recall_last_selected_rom()
        functions.debug_type_print(self.development, self.debug_start_time, 'Last rom selected process',
                                   self.development_startup_info)

        # --------------------------------------------------------------------------------------------------------------
        # Adjust the window size and show / hide the systems column depending upon the preferences setting
        self._hide_hidden_columns()

        # --------------------------------------------------------------------------------------------------------------
        # Put the ROMs list column widths back the way they were when pfeMAME was closed (if the preference is set)
        if self.pref_recall_column_widths == 'True':
            self._restore_column_widths()

        # --------------------------------------------------------------------------------------------------------------
        # Check to see if our preferences setting for the tile view is set.
        # If it is, then after startup we need to automatically switch to the tile view
        if self.prefView == 'True':
            self.inactivity_timer.Stop()  # Stop the inactivity timer from this view
            self.on_tile_view()  # Launch tile view

        # --------------------------------------------------------------------------------------------------------------
        # Check when the ROMs database cache was fully updated - suggest a refresh if its getting old
        # If it's blank then skip this as it will be fully refreshed
        if self.cacheDate:
                try:
                    # Calculate age of cache in days
                    cache_time = datetime.datetime.strptime(self.cacheDate, '%Y-%m-%d %H:%M:%S')
                    current_time = datetime.datetime.now()
                    days_old = (current_time - cache_time).days
                    self.text_database_ageValue.SetLabel(f'{days_old} days')

                    # Check if user wants to be notified
                    notify = self.prefCheckDatabaseAge in ('True', '')
                    threshold = int(self.prefDaysCheckCache)

                    if notify and days_old > threshold:
                        dlg = wx.RichMessageDialog(
                            self,
                            _('The database cache is {} days old. I suggest you refresh the ROMs database cache manually.').format(
                                days_old),
                            _('ROMs Database Cache out of date'),
                            wx.OK | wx.ICON_INFORMATION
                        )
                        dlg.ShowCheckBox(_('Don’t show this message again'))

                        if dlg.ShowModal() == wx.ID_OK and dlg.IsCheckBoxChecked():
                            iniFile.set_ini_file_variables([('preferences', 'checkdatabaseage', 'False')])

                        dlg.Destroy()
                        self.Refresh()

                except ValueError:
                    functions.show_information_dialog(
                        self,
                        _('Unable to check age of ROMs cache. Please check the Preferences and then refresh the ROMs cache'),
                        _('ROMs Database Cache check error')
                    )
                    self.Refresh()

        functions.debug_type_print(self.development, self.debug_start_time, 'Database cache age check',
                                   self.development_startup_info)

        # --------------------------------------------------------------------------------------------------------------
        def check_category_version() -> None:
            """
            Compare the catver.ini file version against the MAME version and advise the user if there is a mismatch
            """
            # Exit early if required conditions are not met
            if not self.category_dict:
                return
            if self.pref_check_catver_version != 'True':
                return
            if not self.path_mame_exe:
                return

            # Compare MAME and catver versions
            if functions.compare_version(self.mame_version, self.catver_version) == 1:
                message = _(
                    'Your MAME version is {mame_version} while your catver.ini file '
                    'version is {catver_version}.  Suggest you find an updated copy '
                    'of the catver.ini file if it is older than the MAME version.'
                ).format(mame_version=self.mame_version, catver_version=self.catver_version)

                _dlg = wx.RichMessageDialog(
                    self,
                    message,
                    _('MAME and catver version mismatch'),
                    wx.OK | wx.ICON_INFORMATION
                )
                _dlg.ShowCheckBox(_('Don\'t show this message again'))
                _dlg.ShowModal()

                if _dlg.IsCheckBoxChecked():
                    iniFile.set_ini_file_variables([('preferences', 'checkcatverversion', 'False')])
                    pub.sendMessage('disable_catver_check')

                _dlg.Destroy()
                self.Refresh()

        self.when_mame_version_known(check_category_version)

        # --------------------------------------------------------------------------------------------------------------
        # If we have received the command line option to manually run a specific ROM on startup, then do it now
        if self.run_specified_rom:
            # Set the position in the ROMs list based on the rom name specified
            match_index = next((i for i, x in enumerate(self.mylist_filtered) if
                                x[index_rom_file_name] == self.specified_rom_name), None)
            if match_index is not None:
                self.list.Select(int(match_index))
                self.list.EnsureVisible(int(match_index))
            # Run the ROM
            self.on_double_click(suppress=True,
                                 ignore_columns=False,
                                 input_playback_or_record='',
                                 pb_r_filename='',
                                 rom_file_name=self.specified_rom_name,
                                 system_file_name='')

    # ------------------------------------------------------------------------------------------------------------------
    def get_mame_version(self):
        """
        Get the MAME executable version straight away (for --version on the command line - the window gets it in the
        background, see set_version_information).
        """
        return functions.mame_version(self.path_mame_exe)[0] or _('Unknown')

    # ------------------------------------------------------------------------------------------------------------------
    def on_export_favorite(self, _event) -> None:
        """
        Copy all ROMs tagged as favorite (their .zip / .7z, and any CHD folder) to the chosen folder.  The copy runs
        in the background with a Cancel button; files already in the folder are only replaced if the user agrees.
        :param _event:
        :return:
        """
        # Open folder dialog
        with wx.DirDialog(self, message=_('Choose a path to export the file to')) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return  # User cancelled
            destination_path = dlg.GetPath()

        items = favorite_export_items(self.mylist, self.rom_folders)
        if not items:
            functions.show_information_dialog(self, _('None of your favorites were found in the ROM folders.'),
                                              _('Export Complete'))
            return

        existing = [name for _source, name in items if os.path.exists(os.path.join(destination_path, name))]
        overwrite = False
        if existing:
            with wx.MessageDialog(self,
                                  _('{existing} of the {count} favorite file(s) are already in the folder.  '
                                    'Replace them?\n\n'
                                    'Yes replaces them, No only copies the others.').format(
                                      existing=len(existing), count=len(items)),
                                  _('Export Favorites'),
                                  wx.YES_NO | wx.CANCEL | wx.NO_DEFAULT | wx.ICON_QUESTION) as ask:
                answer = ask.ShowModal()
            if answer == wx.ID_CANCEL:
                return
            overwrite = answer == wx.ID_YES

        cancel = threading.Event()
        busy = busy_window.BusyWindow(self, on_cancel=cancel.set)
        busy.show()
        progress = self._rom_search_progress_callback(busy)
        N_ = views.N_

        def worker() -> None:
            copied, skipped, failed = 0, 0, []
            for number, (source, name) in enumerate(items, 1):
                if cancel.is_set():
                    break
                target = os.path.join(destination_path, name)
                if os.path.exists(target) and not overwrite:
                    skipped += 1
                    continue
                progress(N_('Exporting favorite {number} of {count}: {name}'), number=number, count=len(items),
                         name=name)
                try:
                    if os.path.isdir(source):
                        shutil.copytree(source, target, dirs_exist_ok=True)      # A CHD folder
                    else:
                        shutil.copyfile(source, target)
                    copied += 1
                except OSError as e:
                    failed.append(f'{name}: {e}')
            wx.CallAfter(self._finish_export_favorite, busy, copied, skipped, failed, cancel.is_set())

        Thread(target=worker, daemon=True).start()

    def _finish_export_favorite(self, busy, copied: int, skipped: int, failed: list[str], cancelled: bool) -> None:
        """GUI-thread half of on_export_favorite: say what was copied."""
        busy.close()
        self.statusbar_panel.set_status(_('Ready'))
        for problem in failed:
            self.my_logger.error(f'Export favorites: {problem}')
        message = _('{} favorite file(s) successfully exported.').format(copied)
        if skipped:
            message += '\n' + _('{} file(s) were already in the folder and were left as they were.').format(skipped)
        if failed:
            message += '\n' + _('{} file(s) could not be copied - see the log file.').format(len(failed))
        if cancelled:
            message += '\n' + _('The export was cancelled.')
        self.messages_append(f'{message}\n', True)
        wx.MessageBox(message=message, caption=_('Export Complete'), style=wx.OK | wx.ICON_INFORMATION, parent=self)

    # ------------------------------------------------------------------------------------------------------------------
    def notebook_page_changing(self, event) -> None:
        if (event.GetOldSelection() == 1
                and hasattr(self, 'filepaths_panel')
                and self.filepaths_panel.data_changed):
            dlg = wx.MessageDialog(
                self,
                _('Unapplied FilePath changes – are you sure you wish to discard changes?'),
                _('Unapplied Changes'),
                wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION
            )
            result = dlg.ShowModal()
            dlg.Destroy()
            if result != wx.ID_YES:
                event.Veto()
                return
            self.filepaths_panel.revert()     # Reload from the INI files so the discarded edits aren't still on show
        event.Skip()

    # ------------------------------------------------------------------------------------------------------------------
    def notebook_page_changed(self, _event) -> None:
        """
        Call this event when we have selected a different tab on the list notebook
        :param _event:
        :return:
        """
        # Check to see if we have four notebook pages.  If we do, the 4th page is the ROM specific.  If we don't have
        # that page selected, then delete it.
        # (Tabs: 0=ROMs List, 1=File Paths, 2=pfeMAME Preferences, 3=ROM Preferences [dynamic])
        if self.list_notebook.GetPageCount() > 3:
            if self.list_notebook.GetSelection() != 3:
                self.list_notebook.DeletePage(3)

        # If we have selected the first tab, then ensure the list has focus to highlight the currently selected row
        if self.list_notebook.GetSelection() == 0 and self.start_up_complete:
            # Deal with the restart prompt first.  Asking for the focus before the dialog goes up
            # leaves the deferred call to fire while the dialog has the frame disabled, and Windows
            # then fails the SetFocus with 0x57 which wxWidgets logs to the console.
            global restart_requested
            if restart_requested:
                _dlg = wx.MessageDialog(self,
                                        _('A setting has been changed that will only take effect when pfeMAME is '
                                          'restarted.  Would you like it to restart now?'),
                                        _('Restart Required'),
                                        wx.YES_NO | wx.YES_DEFAULT | wx.ICON_QUESTION)
                restart_now = _dlg.ShowModal() == wx.ID_YES
                _dlg.Destroy()
                if restart_now:
                    wx.CallAfter(self.on_close)
                    return
                restart_requested = False

            wx.CallLater(100, self._focus_rom_list)

    # ------------------------------------------------------------------------------------------------------------------
    def _focus_rom_list(self) -> None:
        """
        Give the ROM grid the focus, if it is still able to take it.

        Guarded because the call is deferred:  the grid may have been disabled by a modal dialog,
        hidden by another tab, or destroyed altogether before the timer fires.
        """
        try:
            if self.list.IsEnabled() and self.list.IsShownOnScreen():
                self.list.SetFocus()
        except RuntimeError:        # grid was destroyed before the deferred call ran
            pass

    # ------------------------------------------------------------------------------------------------------------------
    def on_mouse(self, _event) -> None:
        """
        Reset the inactivity timer on any mouse event
        :param _event:
        :return:
        """
        self.inactivity_timer_start()  # Reset the inactivity timer
        _event.Skip()

    # ------------------------------------------------------------------------------------------------------------------
    def on_joystick_pov(self, _event) -> None:
        """
        Process the joystick polling timer so we can see if the POV HAT / DPAD direction has been selected.
        :param _event:
        :return:
        """
        # Early exit if joystick input should be ignored
        if self.tileview_running or self.joystick_block or self.pref_enable_joystick_mainview != 'True':
            return

        pov = self.joystick.GetPOVPosition()
        if pov == 65535:
            return

        # POV direction detected
        self.inactivity_timer_start()  # Reset the inactivity timer

        if pov == 0:  # Have we selected move up?
            self.scroll_list_up()  # scroll up a row
        elif pov == 18000:  # Have we selected move down?
            self.scroll_list_down()  # scroll down a row

    # ------------------------------------------------------------------------------------------------------------------
    def on_joystick(self, _event) -> None:
        """
        This function processes joystick events for navigation.
        It will determine which joystick button / direction has been selected
        and will call the required function essentially mapping the joystick
        to the keyboard arrow keys and buttons
        :param _event:
        :return:
        """
        self.inactivity_timer_start()  # Reset the inactivity timer

        # Early exit if joystick input should be ignored
        if self.tileview_running or self.joystick_block or self.pref_enable_joystick_mainview != 'True':
            return

        # Get the button and direction raw values from the joystick
        button_value = self.joystick.GetButtonState()
        direction_value = self.joystick.GetPosition()

        # Define a mapping of button values to actions
        button_actions = {
            1: lambda: self.on_double_click(None),  # Play selected ROM
            32: lambda: self.scroll_list_by_page(1),  # Page down
            16: lambda: self.scroll_list_by_page(-1),  # Page up
        }

        # Call the appropriate function if the button is in the dictionary
        action = button_actions.get(button_value)
        if action:
            action()

        # Process the directions
        # This convoluted method is due to the different way that windows & linux determine joystick
        # positions.  E.g. Linux is -327676 - 0 - 32767 for the left, center, and right
        # while Windows is 0 - 32767 - 65535 for the left, center, and right
        y_position = direction_value[1]
        y_center = ((self.joystickYMax - self.joystickYMin) // 2) // 2

        if y_position < (self.joystickYMin + y_center):  # Have we selected move up?
            self.scroll_list_up()  # scroll up a row
        if y_position > (self.joystickYMax - y_center):  # Have we selected move down?
            self.scroll_list_down()  # scroll down a row

    # ------------------------------------------------------------------------------------------------------------------
    def enable_alert_timer(self) -> None:
        """
        Enable the alert color strobing timer
        :return:
        """
        if self.pref_flash_messages_if_error == 'True':
            self.alert_timer.Start(50)
            msg = _('IMPORTANT NOTIFICATION:  '
                    'Please check this window for the ERROR message.  '
                    'Double-click to cancel alert.')
            self.messages_append(f'{msg}\n', True)
            # New messages don't move the window while it is scrolled up (to read older ones), but an error must show
            self.controlMessages.ShowEnd()

    # ------------------------------------------------------------------------------------------------------------------
    def disable_alert_timer(self, _event) -> None:
        """
        Disable the alert color strobing timer
        :param _event:
        :return:
        """
        self.alert_timer.Stop()
        self.controlMessages.SetBackgroundColour(self.message_window_background_color)
        self.controlMessages.Refresh()

    # ------------------------------------------------------------------------------------------------------------------
    def setup_ini_variables(self) -> None:
        """
        Read variable data from mame.ini, pfemame.ini, and ui.ini and set the application variables
        :param msg: Just an empty string as this can be called from pubsub
        :return: None
        """
        self.my_logger.info(_('Reading INI file settings'))  # Write to the log file

        # Check if the INI file actually exists - if not then create it (first time run situation typically)
        if not os.path.isfile(os.path.join(self.data_dir, 'pfemame.ini')):
            iniFile.create_ini_file()
            self.my_logger.info(_('New pfeMAME.ini file created as existing one not found'))  # Write to the log file
        iniFile.convert_old_settings()

        # Read variables from the pfemame.ini file
        self.cacheDate = iniFile.read_ini_file('system', 'cachedate')
        self.lastromselected = iniFile.read_ini_file('system', 'lastromselected')
        self.lastsystemselected = iniFile.read_ini_file('system', 'lastsystemselected')
        self.lastviewselected = iniFile.read_ini_file('system', 'lastviewselected')
        self.prefCheckDatabaseAge = iniFile.read_ini_file('preferences', 'checkdatabaseage')
        self.prefUseLastSelected = iniFile.read_ini_file('preferences', 'uselastselected')
        # Kept as text, as the ROMs list compares and converts it
        self.pref_icon_size = str(iniFile.read_ini_int('preferences', 'iconsize', low=8, high=256))
        self.pref_show_rom_icons = iniFile.read_ini_file('preferences', 'showgameicons')
        self.prefMainView = iniFile.read_ini_file('preferences', 'mainview')
        self.pref_highlight_missing = iniFile.read_ini_file('preferences', 'highlitemissing')
        self.prefDaysCheckCache = iniFile.read_ini_file('preferences', 'dayscheckcache')
        self.prefScreenSaverTime = iniFile.read_ini_int('preferences', 'screensavertime', low=0)
        self.folders_icons = iniFile.read_ini_file('folders', 'icons')
        self.foldersVideo = iniFile.read_ini_file('folders', 'video')
        self._video_folder_cached_path = ''  # invalidate video cache on settings reload
        self.folder_mapping = iniFile.read_ini_file('folders', 'input_mapping')
        self.path_mame_exe = iniFile.read_ini_file('path', 'mame_executable')
        self.pathHistory = iniFile.read_ini_file('path', 'history_dat')
        self.pathMAMEInfoDat = iniFile.read_ini_file('path', 'mameinfo_dat')
        self.pathCatver = iniFile.read_ini_file('path', 'catver_ini', default=os.path.join(self.path_to_me, 'catver.ini'))
        self.prefView = iniFile.read_ini_file('preferences', 'view')
        self.prefSystemsSupport = iniFile.read_ini_file('preferences', 'systemssupport')
        self.pref_full_systems_method = iniFile.read_ini_file('preferences', 'fullsystemsmethod')
        self.prefVideoAutoload = iniFile.read_ini_file('preferences', 'videoautoload')
        self.prefVideoDisable = iniFile.read_ini_file('preferences', 'videodisable')

        # self.video_disable is used everywhere: video is off if the preference says so or pfeMAME was started with
        # --no_video.  (Before, once it had been switched off it stayed off until pfeMAME was restarted, even after
        # the preference was turned back off.)
        was_disabled = getattr(self, 'video_disable', False)
        self.video_disable = self.prefVideoDisable == 'True' or getattr(self, '_no_video_argument', False)
        if self.video_disable and not was_disabled and hasattr(self, 'video_player'):
            self.video_player.stop(caption=False)       # Switched off while a video was playing
            self.video_playback_timer.Stop()

        self.prefClickFavRating = iniFile.read_ini_file('preferences', 'clickfavrating')
        self.pref_short_name_global_suppress = iniFile.read_ini_file('preferences', 'suppressshortname')
        self.pref_full_systems_method = True if self.pref_full_systems_method == 'True' else False
        self.path_to_mame_ini_file = iniFile.read_ini_file('path', 'mame_ini')
        self.application_colors = functions.get_application_colors()
        self.pref_check_catver_version = iniFile.read_ini_file('preferences', 'checkcatverversion')
        self.pref_check_software_version = iniFile.read_ini_file('preferences', 'checksoftwareversion')
        self.pref_flash_messages_if_error = iniFile.read_ini_file('preferences', 'flashiferrors')
        self.pref_joystick_selected = iniFile.read_ini_file('preferences', 'joystickselected')
        self.pref_enable_joystick_mainview = iniFile.read_ini_file('preferences', 'enablejoystickmainview')
        self.set_window_fullscreen = iniFile.read_ini_file('preferences', 'mainwindowfullscreen')
        self.pref_recall_column_widths = iniFile.read_ini_file('preferences', 'recallromlistcolumns')

        fonts = functions.get_font_info()
        self.global_font_bold = fonts.global_font_bold
        self.global_font_normal = fonts.global_font_normal
        self.global_font_normal_8 = fonts.global_font_normal_8

        # Read variables from the mame.ini file
        self.folders_roms = iniFile.get_from_mameini('rompath', self.path_to_mame_ini_file)
        self.folders_systems = self.folders_roms
        # rompath can hold several ';' separated (and relative) folders - these are the resolved folder paths
        self.rom_folders = functions.split_mame_paths(self.folders_roms, self.path_mame_exe)
        self.folders_samples = iniFile.get_from_mameini('samplepath', self.path_to_mame_ini_file)
        self.foldersSnap = iniFile.get_from_mameini('snapshot_directory', self.path_to_mame_ini_file)
        self.folder_ini = iniFile.get_from_mameini('inipath', self.path_to_mame_ini_file)
        self.folderInput = iniFile.get_from_mameini('input_directory', self.path_to_mame_ini_file)
        # Resolved like MAME does ('cfg' is relative to the MAME folder, '$HOME/.mame/cfg' on Linux) so the controller
        # mapping is copied from the same default.cfg that rungame copies it back to
        self.folder_config = functions.resolve_mame_folder(
            iniFile.get_from_mameini('cfg_directory', self.path_to_mame_ini_file), self.path_mame_exe)

        # Try to read variables from the ui.ini file and create the image options list
        ui_ini_path = functions.find_ui_ini(self.folder_ini, self.path_mame_exe)

        if os.path.isfile(ui_ini_path):
            # Define keys and human-readable labels.  The labels stay in English here (the online image search
            # uses them) and are translated when shown.
            image_keys = [
                ('pcbs_directory', views.N_('PCBs')),
                ('bosses_directory', views.N_('Bosses')),
                ('cabinets_directory', views.N_('Cabinets')),
                ('cpanels_directory', views.N_('Control Panels')),
                ('flyers_directory', views.N_('Flyers')),
                ('titles_directory', views.N_('Title Screens')),
                ('ends_directory', views.N_('Ending Screens')),
                ('marquees_directory', views.N_('Marquees')),
            ]

            # Dynamically assign directories as attributes and build the dir list
            dir_list = [[self.foldersSnap, views.N_('Snapshots')]]
            for key, label in image_keys:
                directory = iniFile.get_from_mameini(key, ui_ini_path)
                setattr(self, f"{key.replace('_directory', '')}_directory", directory)
                dir_list.append([directory, label])
        else:
            dir_list = [[self.foldersSnap, views.N_('Snapshots')]]

        # Filter valid directories
        self.image_options = [entry for entry in dir_list if os.path.isdir(entry[0])]

        # Sync icon-related settings to the virtual list and clear the icon cache if either value changed.
        # The hasattr guard is needed because setup_ini_variables() is called during __init__ before self.list exists.
        if hasattr(self, 'list') and len(self.mylist) > 0:
            if (self.list.pref_icon_size != self.pref_icon_size or
                    self.list.folders_icons != self.folders_icons):
                self.list.pref_icon_size = self.pref_icon_size
                self.list.folders_icons = self.folders_icons
                self.list.clear_icon_cache()

    # ----------------------------------------------------------------------------------------------------------------
    def scroll_image_options(self, direction: int) -> None:
        """
        Scroll the image option text right or left depending upon the direction value
        :param direction: 1 = RIGHT, -1 = LEFT
        :return: None
        """
        new_index = self.image_options_index + direction
        if 0 <= new_index < len(self.image_options):
            self.image_options_index = new_index
            self.image_option.SetLabel(_(self.image_options[self.image_options_index][1]))
            self.on_single_click()

    # ------------------------------------------------------------------------------------------------------------------

    def on_url_selected(self, event) -> None:
        """
        This event captures a left mouse click on the URL at the end of the ROM info window.  It then launches
        the default web browser pointing at that URL.
        :param event:
        :return:
        """
        if event.MouseEvent.LeftUp():
            # Open just the link that was clicked (it used to take everything from the first 'http' to the end
            # of the text).  The text control shows the hand cursor over links itself.
            url = event.GetEventObject().GetRange(event.GetURLStart(), event.GetURLEnd()).strip()
            if url:
                webbrowser.open(url)
        event.Skip()

    # ------------------------------------------------------------------------------------------------------------------
    # Open the pfeMAME sourceforge web page in the default browser
    @staticmethod
    def open_web_page(_self) -> None:
        webbrowser.open('https://sourceforge.net/projects/pfemame/')

    # ------------------------------------------------------------------------------------------------------------------
    def check_for_updates(self, event) -> None:
        """
        Get the version information from sourceforge to see if there is a newer version of pfeMAME available.
        This is done by looking for any files listed that match the operating system type in the following formats:
        pfemame_windows_v
        pfemame_linux_v
        pfemame_mac_v
        The text after the 'v' will be the version number.

        :param event:
        :return:
        """

        def prompt_for_update(parent: wx.Window, current_version: str, new_version: str, download_url: str,
                              launch_callback) -> None:
            """
            Prompt the user to confirm downloading and installing an update.

            :param parent: The wx parent window
            :param current_version: Current installed version string
            :param new_version: Latest available version string
            :param download_url: URL to the update file
            :param launch_callback: Function to call with download_url if user agrees
            """
            dlg = wx.RichMessageDialog(
                parent,
                _('A newer version of pfeMAME is available.\n\nYou have version {0}, and version {1} is available.\n\n'
                  'Would you like to download and install it now?').format(current_version, new_version),
                _('New Version Available'),
                wx.YES_NO | wx.ICON_INFORMATION
            )
            dlg.ShowCheckBox(_("Don't check for updates on startup"))

            result = dlg.ShowModal()
            suppress_check = dlg.IsCheckBoxChecked()
            dlg.Destroy()
            parent.Refresh()

            if suppress_check:
                iniFile.set_ini_file_variables([('preferences', 'checksoftwareversion', 'False')])
                pub.sendMessage('disable_software_version_check')

            if result == wx.ID_YES:
                launch_callback(download_url)

        def display_threadsafe_message(parent: wx.Window, message: tuple) -> None:
            """
            Display dialog box messages.  In this case they are called from a callafter in the thread below
            :param parent: Parent caller
            :param message:Tuple containing (Message text, Caption, Style, Flag=True if checkbox needed)
            :return: None
            """
            text, caption, style = message[:3]

            if not message[3]:
                dlg = wx.MessageDialog(parent, text, caption, style)
            else:
                dlg = wx.RichMessageDialog(parent, text, caption, style)
                dlg.ShowCheckBox(_("Don't check software on startup"))

            dlg.ShowModal()

            if message[3] and dlg.IsCheckBoxChecked():
                iniFile.set_ini_file_variables([('preferences', 'checksoftwareversion', 'False')])
                pub.sendMessage('disable_software_version_check')

            dlg.Destroy()
            parent.Refresh()  # refresh the passed-in parent

        def run_update_thread(update_type: str) -> None:
            wx.CallAfter(self.statusbar_panel.set_status, _('Checking for Software Updates'))
            wx.CallAfter(self.Refresh)

            self.my_logger.info(_('Checking for software update - requesting data from sourceforge'))
            wx.CallAfter(self.messages_append, message=_('Checking for software update\n'))

            def handle_network_error(msg, error):
                """Helper function to handle network errors consistently"""
                wx.CallAfter(self.statusbar_panel.set_status, _('Ready'))
                self.my_logger.error(f'{msg} : {error}')
                wx.CallAfter(self.messages_append, f'{msg}\n', True)
                wx.CallAfter(self.enable_alert_timer)

            # Preferred source: SourceForge's best_release.json API (certificate-verified), which also gives us a
            # checksum for the updater to verify the download against.  Fall back to scraping the files page.
            # SourceForge's best_release.json first (verified, with a checksum), the files page as a fallback
            try:
                online_version, download_url, checksum = updater_client.find_latest_release(self.system,
                                                                                            self.my_logger)
            except TimeoutError as e:
                handle_network_error(_('Connection timed out - server is taking too long to respond'), e)
                return
            except urllib.error.URLError as e:
                handle_network_error(_('Unable to access network connection or update version file not found'), e)
                return

            msg = _('Received data from sourceforge')
            self.my_logger.info(msg)

            if not self._app_closing:
                try:
                    self.my_logger.info(_('Trying to calculate version'))

                    result = functions.compare_version(online_version, __version__)
                    if result == 1:
                        self.my_logger.info(_('New pfeMAME version exists'))

                        # At start-up the answer can arrive before the window has faded in - wait for that
                        wx.CallAfter(self.when_window_shown,
                                     lambda: prompt_for_update(self,
                                                               __version__,
                                                               online_version,
                                                               download_url,
                                                               lambda url: self.launch_updater(url, checksum)))
                    else:
                        msg = _('You already have the latest version')
                        self.my_logger.info(msg)
                        wx.CallAfter(self.messages_append, f'{msg}\n')
                        wx.CallAfter(self.controlMessages.AppendText, f'{MESSAGE_DELIMITER}')
                        if update_type != 'auto':
                            wx.CallAfter(display_threadsafe_message,
                                         self,
                                         (_('You already have the latest version of pfeMAME installed.'),
                                          _('Check for software update'),
                                          wx.OK | wx.ICON_INFORMATION, False))
                except (TypeError, AttributeError):
                    self.my_logger.error(_('Unable to get version information from Sourceforge.  Request returned: {}. '
                                           'It should have returned three numbers separated by a dot (e.g. 2.2.2)').format(
                        online_version))
                    if update_type != 'auto':
                        wx.CallAfter(display_threadsafe_message,
                                     self,
                                     (_('An error has occurred and I am unable to check the online version. '
                                        'Check the logfile for more information.'),
                                      _('Error retrieving version'),
                                      wx.OK | wx.ICON_INFORMATION, False))
                wx.CallAfter(self.statusbar_panel.set_status, _('Ready'))

        # Run the update checking function in a separate thread
        thread = Thread(target=run_update_thread, args=(event,))
        thread.daemon = True  # Force the thread to close with the main thread
        thread.start()

    # ------------------------------------------------------------------------------------------------------------------
    # ------------------------------------------------------------------------------------------------------------------
    def launch_updater(self, download_url: str, checksum: str = ''):
        """
        This calls the external pfemame_update mule to update the application
        :param download_url:  Ths is the address to download the file from
        :param checksum: Expected archive checksum ('sha256:<hex>' / 'md5:<hex>') for the updater to verify
        :return:
        """

        # Build command to run updater
        updater_exe = os.path.join(self.path_to_me, "pfemame_updater")
        if sys.platform == "win32":
            updater_exe += ".exe"

        cmd = [updater_exe, "--download", download_url, "--install-dir", self.path_to_me, "--restart"]
        if checksum:
            cmd.extend(["--checksum", checksum])

        try:
            # Call the updater application
            subprocess.Popen(cmd, cwd=self.path_to_me)
            # Cleanup the current application
            self.cleanup()
            # Force immediate process termination (doesn't wait for wx cleanup)
            time.sleep(1)
            os._exit(0)

        except Exception as e:
            wx.MessageBox(_('Failed to launch updater:\n{}').format(e), _('Error'), wx.ICON_ERROR)

    # ------------------------------------------------------------------------------------------------------------------
    def on_toggle_categories(self, _event) -> None:
        """
        # ROM categories checkbox double click handler
        This will toggle all checkboxs selected or not-selected

        :param _event:
        :return:
        """

        checkbox_controls = self.get_checkbox_controls()
        any_checked = next((x for x in checkbox_controls if x.GetValue() is True), False)
        for ctrl in checkbox_controls:
            ctrl.SetValue(not any_checked)
        self.on_update_categories()

    # ------------------------------------------------------------------------------------------------------------------
    def get_checkbox_controls(self) -> list:
        """
        Get list containing all checkbox controls for the ROM categories list

        :return:
        """
        checkbox_controls: list[wx.CheckBox] = [widget for widget in list(self.panel_categories.content.GetChildren())
                                             if isinstance(widget, wx.CheckBox)]
        return checkbox_controls

    # ------------------------------------------------------------------------------------------------------------------
    def on_update_categories(self, _event=None) -> None:
        """
        This will update the categories.dat file with the current state of the ROM categories check boxes
        and then refresh the ROMs list to show the new selection.

        :param _event:
        :return:
        """

        # Look at the state of each checkbox control, and get its name if it's checked.
        # The name was set to the unique categories so can be used to determine which
        # categories I want selected.
        # Write these out to the 'categories.dat' text file for later use.
        checkbox_controls = self.get_checkbox_controls()
        file_path = os.path.join(self.data_dir, 'categories.dat')

        try:
            functions.write_dat_lines(file_path, (ctrl.GetName() + '\n' for ctrl in checkbox_controls
                                                  if ctrl.GetValue()))
        except IOError as e:
            # Consider logging the error or handling it appropriately
            self.my_logger.error(_('Unable to write to the categories.dat file: {}').format(e))

        self.set_view_key('All')
        self.controlSearch.SetValue('')  # Empty the search input box
        self.categories = self.load_categories()  # Rebuild the categories list

        number_roms_in_filtered_list = self.populate_list(-1, '', False)  # Update the ROMs view
        self.update_rom_numbers(number_roms_in_filtered_list)

    # ------------------------------------------------------------------------------------------------------------------
    def on_play_clicked(self, _event):
        """
        This is called by clicking on the 'Play Video' control and by the video timer event.  It makes sure that the
        main ROMs list is given back focus.

        :param _event:
        :return:
        """
        if self.video_player.is_playing():
            self.video_stop()
        else:
            self.video_player.video_path = self.video_to_play  # Ensure path is up to date
            self.video_player.play()
            self.list.SetFocus()

    # ------------------------------------------------------------------------------------------------------------------
    def inactivity_timer_start(self) -> None:
        """
        Start the inactivity timer (or reset it if already started)
        """
        if not self.inactivity_timer_block and not self.video_disable and self.prefScreenSaverTime > 0:
            self.inactivity_timer.Start(self.prefScreenSaverTime * 1000 * 60)

    # ------------------------------------------------------------------------------------------------------------------
    def on_timer_event(self, event) -> None:
        """
        Process various timer events.  The event ID determines which timer event has been triggered
        """
        event_id = event.GetId()
        if event_id == 9991:
            # It's the alert timer that's triggered this event
            # Starting at '#FFF0F0'
            # Decrement the value of the 2nd & 3rd pair by 10h (16D) at a time until we reach '#FF0000'
            # Then increment in the same steps back to the start
            alert_color = ''.join(['#ff', '{:02x}'.format(self.alert_colors_value),
                                   '{:02x}'.format(self.alert_colors_value)])
            self.controlMessages.SetBackgroundColour(alert_color)
            self.controlMessages.Refresh()
            self.alert_colors_value -= self.alert_colors_decrement_value  # Decrement / increment to next value
            # If we have hit the bottom or top of the range then invert the incrementing direction
            if self.alert_colors_value == -16 or self.alert_colors_value == 256:
                self.alert_colors_decrement_value = -self.alert_colors_decrement_value
                self.alert_colors_value = 0 if self.alert_colors_value == -16 else 240
        elif event_id == 9992:
            # It's the inactivity timer, so we need to stop the timer and open the screensaver
            self.on_fullscreen_video_player(-2)
        elif event_id == 9994:
            if os.path.isfile(self.video_player.video_path):
                self.timerSeconds -= 1
                self.video_player.set_video_caption(_("Auto loading video in {} seconds").format(self.timerSeconds))

                if self.timerSeconds <= 0:
                    self.video_playback_timer.Stop()
                    self.timerSeconds = VIDEO_TIMER_DELAY

                    # Ensure the panel is shown before trying to play
                    # self.video_player.video_panel.Show()
                    # Delay video play slightly to allow rendering system to catch up.
                    # Keep a handle so video_stop() can cancel it — otherwise this
                    # deferred play() can fire after we've switched to tile view and
                    # start the main window's video playing in the background.
                    self._pending_play = wx.CallLater(200, self._deferred_play)  # Delay by 200ms


    # ------------------------------------------------------------------------------------------------------------------
    def _deferred_play(self) -> None:
        """
        Fire the autoload video play that was scheduled by the countdown timer.

        Guarded so it can never start playback in the background: if the user has
        switched to tile view (or video is disabled) between the timer completing
        and this deferred call firing, we simply skip it.
        """
        if self.tileview_running or self.video_disable:
            return
        self.video_player.play()

    # ------------------------------------------------------------------------------------------------------------------
    def on_fullscreen_video_player(self, _event=None) -> None:
        """
        Show the full screen video player
        :param _event:
        :return:
        """
        self.inactivity_timer.Stop()
        self.video_stop()

        # Manual player request checks (when the screensaver starts it, the player closes itself if there's nothing
        # to play)
        if _event != -2:
            if not os.path.exists(self.foldersVideo) or self.foldersVideo == '.':
                functions.show_error_dialog(
                    self,
                    _('Please set up a valid Videos folder in Filepaths'),
                    _('ERROR')
                )
                return

            try:
                video_list = fullscreenplay.list_video_files(self.foldersVideo)
            except OSError:
                video_list = []
            if not video_list:
                functions.show_error_dialog(
                    self,
                    _("It doesn't look like there are any valid video files in the Video folder"),
                    _('ERROR')
                )
                return

        # Launch video player if appropriate
        if (os.path.exists(self.foldersVideo)
                and self.foldersVideo != '.'
                and not self.video_disable):
            iniFile.set_ini_file_variables([('preferences', 'videodisable', 'False')])

            fullscreenplay.FullScreenVideoPlayer(
                self.foldersVideo,
                'mainview',
                self,
                my_logger=self.my_logger,
                rom_list=self.mylist
            )

    # ------------------------------------------------------------------------------------------------------------------
    def on_clear_messages(self, _event) -> None:
        """
        Clear the messages text box
        :param _event:
        :return:
        """
        self.controlMessages.Clear()

    # ------------------------------------------------------------------------------------------------------------------
    def on_copy_messages(self, _event) -> None:
        """
        Copy the messages window content to the clipboard
        :param _event:
        :return:
        """
        data_object = wx.TextDataObject()
        data_object.SetText(self.controlMessages.GetValue())
        if wx.TheClipboard.Open():
            wx.TheClipboard.SetData(data_object)
            wx.TheClipboard.Close()
        else:
            wx.MessageBox(_('Unable to open the clipboard'), _('Error'))

    # ------------------------------------------------------------------------------------------------------------------
    def on_enable_alert_timer(self, _event) -> None:
        self.enable_alert_timer()

    # ------------------------------------------------------------------------------------------------------------------
    def load_history_dat(self, file_to_load: str, file_type: str = 'history') -> str:
        """
         Load the history or mameinfo file into memory.  Safe to call from a background thread - any error message
         is shown in the messages window on the GUI thread.
        :param file_to_load:
        :param file_type: 'history' or 'mameinfo'
        :return:
        """
        return functions.load_history_dat(_GuiThreadCalls(self), self.my_logger, file_to_load, file_type)

    def load_info_files(self) -> None:
        """Load history.xml and mameinfo.dat in a background thread (they can be large)."""
        if self._info_files_loading:
            return
        self._info_files_loading = True
        path_history, path_mame_info = self.pathHistory, self.pathMAMEInfoDat

        def load() -> None:
            history = self.load_history_dat(path_history, 'history')
            mame_info = self.load_history_dat(path_mame_info, 'mameinfo')
            wx.CallAfter(self._info_files_loaded, history, mame_info)

        Thread(target=load, daemon=True).start()

    def _info_files_loaded(self, history: str, mame_info: str) -> None:
        """GUI-thread half of load_info_files."""
        if not self:
            return
        self.history_data, self.mame_info_data = history, mame_info
        self._info_files_loading = False
        functions.debug_type_print(self.development, self.debug_start_time, 'History and mameinfo.dat files loaded',
                                   self.development_startup_info)
        if self.start_up_complete:
            self._show_info_text(self.get_virtual_list_row_info())  # The selected ROM's info can be looked up now

    # ------------------------------------------------------------------------------------------------------------------
    def on_save_image(self, _event) -> None:
        """
        Try to save the image stored in the clipboard to a file
        :param _event:
        :return:
        """
        if not os.path.exists(self.foldersSnap):
            return

        results = self.get_virtual_list_row_info()
        rom_file_name = results.rom_file_name

        file_path = os.path.join(self.foldersSnap, f'{rom_file_name}.png')

        # Check for file existence and confirm overwrite
        if os.path.exists(file_path):
            dlg = wx.MessageDialog(
                self,
                _('The file name {}.png already exists in the Snapshots folder.  '
                  'Would you like to continue?').format(rom_file_name),
                _('File Already Exists'),
                wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION
            )
            if dlg.ShowModal() != wx.ID_YES:
                dlg.Destroy()
                return
            dlg.Destroy()

        self.update_logfile(_('Trying to save clipboard image as file {}').format(file_path))

        # Clipboard compatibility check (especially important on macOS)
        if not wx.TheClipboard.IsSupported(wx.DataFormat(wx.DF_BITMAP)):
            message = _('Clipboard does not contain a supported image format')
            self.update_logfile(message)
            functions.show_information_dialog(self, message, _('Image Saving Message'))
            return

        # Try to retrieve image from clipboard and save
        success = False
        try:
            if wx.TheClipboard.Open():
                bitmap_object = wx.BitmapDataObject()
                if wx.TheClipboard.GetData(bitmap_object):
                    bitmap = bitmap_object.GetBitmap()
                    if bitmap.IsOk():
                        success = bitmap.SaveFile(file_path, wx.BITMAP_TYPE_PNG)
                wx.TheClipboard.Close()
        except Exception as e:
            self.update_logfile(f'Clipboard error: {e}')
            success = False

        # Show result
        if success:
            message = _('File saved successfully')
            self.on_single_click()  # Refresh to show new image
            self.Refresh()
        else:
            message = _('Unable to access the clipboard image')

        self.update_logfile(message)
        functions.show_information_dialog(self, message, _('Image Saving Message'))

    # ------------------------------------------------------------------------------------------------------------------
    # Add the ROM specific preferences tab to the main list view.
    # If it already exists, then delete it and recreate.  This is done so that the tab changes with changed
    # ROMs.
    def preferences_rom_specific(self, _event=None) -> None:
        if not preferences.mame_executable_found(self.path_mame_exe):
            functions.show_error_dialog(self, _('Unable to find the MAME executable path.  Check the file path settings.'),
                                        _('ERROR'))
            return

        # inipath can list several folders - one of them has to exist to keep ROM INI files in
        if functions.rom_ini_folder(self.folder_ini, self.path_mame_exe):
            results = self.get_virtual_list_row_info()
            rom_file_name = results.rom_file_name
            rom_name = results.rom_name
            system_file_name = results.system_file_name

            is_a_system = rom_file_name in self.system_rom_names

            # If it's a system program then add that to the title
            if system_file_name:
                rom_name = f'{rom_name}: {system_file_name}'

            # If we have more than three pages then delete the fourth page as it's the old ROM specific preferences,
            # and we need to remove that before we add the new one.
            # (Tabs: 0=ROMs List, 1=File Paths, 2=pfeMAME Preferences, 3=ROM Preferences [dynamic])
            if self.list_notebook.GetPageCount() > 3:
                self.list_notebook.DeletePage(3)

            if rom_name != '':  # Don't show if we don't have a valid ROM selected
                self.list_notebook.Freeze()
                self.list_notebook.AddPage(preferences.Preferences(parent=self.list_notebook,
                                                                   title=_('ROM Preferences - {}').format(rom_name),
                                                                   mode='game',
                                                                   rom_file_name=rom_file_name,
                                                                   folder_ini=self.folder_ini,
                                                                   path_executable=self.path_mame_exe,
                                                                   system_file_name=system_file_name,
                                                                   is_a_system=is_a_system),
                                           _('{} Preferences').format(rom_name))
                self.list_notebook.Thaw()
                # Show the ROM specific preferences tab
                self.list_notebook.SetSelection(3)
        else:
            msg = _('The INI Folder path is not valid.  '
                    'Please select EDIT > File Paths and set a valid path for this folder.')
            title = _('No INI folder path set')
            functions.show_error_dialog(self, msg, title)

    # ------------------------------------------------------------------------------------------------------------------
    # Process the tile view menu option event
    def on_tile_view(self, _event=None) -> None:
        self.video_stop()  # Stop the video
        self.inactivity_timer.Stop()  # Stop the inactivity timer from this view
        self.tileview_running = True  # Flag to prevent joystick events from doing anything when tileview is running
        view_filter = self.get_view_key()  # Language-neutral key ('Favorites' etc.)
        self.my_logger.info(_('Switching to tile view'))  # Write to the log file
        tileview.TileView(mylist_local=self.mylist,
                          my_logger=self.my_logger,
                          version=__version__,
                          mame_version=self.mame_version,
                          video_disable=self.video_disable,
                          copy_right=__copyright__,
                          view_filter=view_filter,
                          development=self.development)

    # ------------------------------------------------------------------------------------------------------------------
    # Load the database file
    @staticmethod
    def load_database_file() -> tuple[list, int]:
        """
        Load mylist.db, the saved ROMs database.  Returns (mylist, number of ROMs flagged as available).
        Raises if the file is missing or was written by an older version (see rom_database.load_database).
        """
        mylist, _system_names = rom_database.load_database(
            os.path.join(functions.data_dir(), rom_database.DATABASE_NAME))
        return mylist, sum(1 for row in mylist if row[index_exists] == '1')

    # ------------------------------------------------------------------------------------------------------------------
    # When requested, rebuild the full ROMs database (refresh and reload)
    def on_database_refresh(self, event=None, on_done=None) -> None:
        """
        Load or rebuild the ROMs database.

        event='auto' (start-up) uses the saved database (mylist.db) when it is valid.  Otherwise the database is
        rebuilt by rom_database.build() in a background thread - the window stays responsive and shows progress.
        on_done() is called on the GUI thread once the database is ready (immediately if nothing had to be built).
        """
        if self._database_build_running:
            self.statusbar_panel.set_status(_('The ROMs database is already being rebuilt - please wait'))
            return
        if not self._mame_version_known:
            # The saved database is only valid for the MAME version it was built with, so wait for MAME to say
            self.when_mame_version_known(lambda: self.on_database_refresh(event, on_done))
            return

        self.filter_cache.clear()  # Clear the search filter cache as mylist may now change

        if not self.categories:
            self.categories = self.load_categories()

        self.video_stop()

        def finish() -> None:
            if self.start_up_complete:
                self.refresh_ui_post_database()
            self.post_refresh_controls()
            self.list.Enable()
            self.list.SetFocus()
            if on_done:
                on_done()

        if self.invalid_mame_path():
            self.show_mame_path_error()
            if on_done:
                on_done()
            return

        if not (self.path_mame_exe and self.folders_roms):
            self.handle_first_time_setup()
            self.list.Enable()
            if on_done:
                on_done()
            return

        if event == 'auto' and self.cacheDate and self.try_load_cached_database():
            finish()
            return

        self._start_database_build(finish)

    # ------------------------------------------------------------------------------------------------------------------
    def _start_database_build(self, finish) -> None:
        """Run rom_database.build() in a background thread; _finish_database_build() picks up the result."""
        self._database_build_running = True
        self._database_build_cancel.clear()
        self.list.Disable()
        self.availableRoms = 0
        self.mylist = []
        self.mylist_filtered = []
        self.list.set_data([])
        self.progress_bar.SetValue(0)
        self.progress_cancel_button.Enable()
        self.statusbar_panel.show_progress_bar(self.progress_area, True)
        self.statusbar_panel.set_status(_('Building ROM list. Please Wait.........'))
        self.my_logger.info(_('Started building full ROMs database'))

        # Show the 'please wait' window until the progress bar has something to count (reading the machine list
        # from MAME the first time can take a while and has no known total).
        self._close_database_build_busy()
        self._database_build_busy = busy_window.BusyWindow(self, on_cancel=self.on_cancel_database_build)
        self._database_build_busy.show()
        self.statusbar_panel.Update()

        settings = rom_database.BuildSettings(
            mame_exe=self.path_mame_exe,
            mame_version=self.mame_version,
            data_dir=self.data_dir,
            rom_folders=list(self.rom_folders),
            systems_folders=functions.split_mame_paths(self.folders_systems, self.path_mame_exe),
            systems_support=(self.prefSystemsSupport == 'True'),
            category_dict=dict(self.category_dict),
            alternate_engines=(list(self.alternate_emulation_engines)
                               if self.alternate_emulation_engines and not self.alternate_emulation_engines_error
                               else []))
        started = time.monotonic()

        # The build thread only records its latest progress; a GUI timer picks it up and draws it.  (Posting an event
        # per update, as before, could leave the status bar unchanged on Linux until the slow first phase - reading
        # the MAME machine list - had finished.)
        self._database_build_progress = None

        def progress(message: str, done: int, total: int) -> None:
            self._database_build_progress = (message, done, total)

        self._database_progress_timer.Start(100)

        def worker() -> None:
            try:
                result = rom_database.build(settings, progress, self._database_build_cancel)
            except Exception as e:      # Including rom_database.BuildCancelled
                result = e
            wx.CallAfter(self._finish_database_build, result, started, finish)

        Thread(target=worker, daemon=True).start()

    def on_cancel_database_build(self, _event=None) -> None:
        """Cancel button (status bar or Please Wait window): stop the ROMs database rebuild at its next check."""
        if self._database_build_running:
            self._database_build_cancel.set()
            self.progress_cancel_button.Disable()
            self.statusbar_panel.set_status(_('Cancelling the ROMs database rebuild...'))

    def _show_database_build_progress(self, _event=None) -> None:
        """Timer handler: show the build thread's latest progress in the status bar and progress bar."""
        if not self or self._app_closing or not self._database_build_running:
            return
        latest = self._database_build_progress
        if latest is None:
            return
        message, done, total = latest
        self.statusbar_panel.set_status(_(message).format(done) + ' ...')
        if total:
            self._close_database_build_busy()   # The progress bar takes over from here
            self.progress_bar.SetRange(total)
            self.progress_bar.SetValue(min(done, total))
            self.progress_bar.Refresh()
        self.statusbar_panel.Update()           # Repaint now rather than whenever the GUI is next idle

    def _close_database_build_busy(self) -> None:
        if self._database_build_busy:
            self._database_build_busy.close()
        self._database_build_busy = None

    def _report_mame_changes(self, changes) -> None:
        """MAME has been upgraded since the last build: save the list of changes and offer to show it."""
        path = os.path.join(self.data_dir, f'mame_changes_{changes.old_version}_to_{changes.new_version}.txt')
        try:
            with open(path, 'w', encoding='utf-8') as handle:
                handle.write(rom_database.format_changes(changes))
        except OSError as e:
            self.my_logger.error(f'Unable to write {path}: {e}')
            return
        self.my_logger.info(changes.summary)
        self.messages_append(f'{changes.summary}\n', True)
        with wx.MessageDialog(self, _('{}\n\nWould you like to see the list?').format(changes.summary),
                              _("What's New in MAME"), wx.YES_NO | wx.YES_DEFAULT | wx.ICON_INFORMATION) as dlg:
            if dlg.ShowModal() == wx.ID_YES:
                self._show_text_file(_("What's New in MAME"), path)

    def _show_text_file(self, title: str, path: str) -> None:
        scrolledwindow.DisplayScrolledDialog(title=title, file_path=path, scroll=True, size=wx.Size(900, 600))

    # ------------------------------------------------------------------------------------------------------------------
    # Ribbon: show the most recent 'what changed in MAME' report
    def on_mame_changes(self, _event=None) -> None:
        reports = sorted((os.path.join(self.data_dir, name) for name in os.listdir(self.data_dir)
                          if name.startswith('mame_changes_') and name.endswith('.txt')), key=os.path.getmtime)
        if not reports:
            functions.show_information_dialog(
                self, _('No MAME upgrade has been recorded yet.  The list of new, now-working and removed '
                        'machines is made the first time the ROMs database is rebuilt after MAME is updated.'),
                _("What's New in MAME"))
            return
        self._show_text_file(_("What's New in MAME"), reports[-1])

    # ------------------------------------------------------------------------------------------------------------------
    # Software list browser for the selected system
    def on_software_browser(self, _event=None) -> None:
        results = self.get_virtual_list_row_info()
        system = results.rom_file_name
        if not system:
            return
        if system not in self.system_rom_names:
            functions.show_information_dialog(self, _('{} is not a system with software lists.').format(results.rom_name),
                                              _('Software Lists'))
            return
        software_browser.SoftwareBrowser(self, system, results.rom_name, self.path_mame_exe, self.mylist)

    def select_rom_row(self, row: list) -> bool:
        """Show the given mylist row in the ROM list (All view, no search) and select it."""
        self.set_view_key('All')
        self.clear_event_override = True
        self.controlSearch.SetValue('')
        self.clear_event_override = False
        self.update_rom_numbers(self.populate_list(-1, '', False))
        index = next((i for i, line in enumerate(self.mylist_filtered) if line is row), None)
        if index is None:
            return False
        self.list_notebook.SetSelection(0)
        self.list.Select(index)
        self.list.EnsureVisible(index)
        self.on_single_click()
        self.Raise()
        return True

    # ------------------------------------------------------------------------------------------------------------------
    def _finish_database_build(self, result, started: float, finish) -> None:
        """GUI-thread half of the rebuild: store the result, load favourites etc., save and refresh the view."""
        if not self or self._app_closing:
            return
        self._database_build_running = False
        self._database_progress_timer.Stop()
        self._close_database_build_busy()
        self.progress_bar.SetValue(0)
        self.statusbar_panel.show_progress_bar(self.progress_area, False)

        if isinstance(result, rom_database.BuildCancelled):
            msg = _('ROMs database rebuild cancelled')
            self.my_logger.info(msg)
            self.messages_append(f'{msg}\n', True)
            # Go back to the ROMs database saved by the last complete build (if there is one)
            if not self.try_load_cached_database():
                self.mylist = []
            finish()
            self.statusbar_panel.set_status(msg)
            return

        if isinstance(result, Exception):
            self.my_logger.error(f'ROMs database build failed: {result}')
            wx.MessageBox(_('ERROR:  Can\'t read XML cache file and unable to get MAME to create a new one.  '
                            'Check that the MAME executable is working correctly and the MAME path is correct '
                            'in FilePaths.') + f'\n\n{result}',
                          _('ERROR WITH MAME XML'))
            finish()
            return

        self.mylist = result.mylist
        self.availableRoms = result.available_roms
        self.system_rom_names = result.system_rom_names
        search.set_system_names(self.system_rom_names)
        self.my_logger.info(f'ROMs database build: {len(self.mylist):,} rows, {result.available_roms:,} exist, '
                            f'{result.clones_added} merged-set clones, machine list from '
                            f'{"cache" if result.machines_from_cache else "MAME"}, timings {result.timings}')

        for kind, message in result.messages:
            if kind == 'error':
                self.my_logger.error(message)
                self.messages_append(_('ERROR:  ') + f'{message}\n', True)
                self.enable_alert_timer()
            else:
                self.my_logger.info(message)

        if result.mame_changes:
            wx.CallAfter(self._report_mame_changes, result.mame_changes)

        # If any errors were detected during the database build then manage them here
        if result.errors:
            self.my_logger.error(_('Errors detected when building ROMs database.  Check the build_errors.txt file.'))
            try:
                with open(os.path.join(self.data_dir, 'build_errors.txt'), 'w', encoding='utf-8') as fp:
                    fp.writelines(f'{error}\n' for error in result.errors)
            except IOError:
                self.my_logger.error(_('Unable to write to the build_errors.txt file'))
            functions.show_information_dialog(self,
                                              _('Errors were detected when building the ROMs database.  Please '
                                                'check the build_errors.txt file for information.'),
                                              _('Errors during Database Build'))

        if self.mylist:
            self.load_all_dat_files()  # Load favorites, runs, etc dat file data
            # The time the build finished (not when pfeMAME started, which may be days ago)
            iniFile.set_ini_file_variables([('system', 'cachedate',
                                             datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'))])
            msg = _('ROMs database refresh completed in {} seconds.').format(int(time.monotonic() - started))
            self.my_logger.info(msg)
            self.messages_append(f'{msg}\n', True)
            self.write_database()

        finish()

    def invalid_mame_path(self) -> bool:
        return self.path_mame_exe not in ('', 'mame') and not os.path.exists(self.path_mame_exe)

    def show_mame_path_error(self) -> None:
        functions.show_error_dialog(self, _('Unable to find the MAME executable.'), _('ERROR'))

    def try_load_cached_database(self) -> bool:
        self.my_logger.info(_('Started reading the temporary ROMs database file'))
        try:
            self.mylist, self.system_rom_names = rom_database.load_database(
                os.path.join(self.data_dir, rom_database.DATABASE_NAME))
            if not self.mylist:
                raise ValueError(_('The ROMs database is empty. Forcing full rebuild.'))
            self.availableRoms = sum(1 for row in self.mylist if row[index_exists] == '1')
            search.set_system_names(self.system_rom_names)
            self.my_logger.info(_('Completed reading the temporary ROMs database file'))
            return True
        except Exception as e:
            self.my_logger.error(str(e))
            self.messages_append(f'{str(e)}\n', True)
            return False

    def refresh_ui_post_database(self) -> None:
        number_roms = self.populate_list(filtercolumn=-1, filtervalue='', read_from_cache=False)
        self.update_rom_numbers(number_roms)
        if number_roms == 0:
            msg = _('Looks like your ROMs list is empty. Please check that you have at least one ROM category selected.')
            title = _('Empty ROMs list')
            functions.show_information_dialog(self, msg, title)

    def post_refresh_controls(self) -> None:
        self.blockFilter = True
        self.set_view_key('All')
        self.blockFilter = False

        self.controlSearch.Enable(False)
        self.clear_event_override = True
        self.controlSearch.SetValue('')
        self.controlSearch.Enable(True)
        self.clear_event_override = False

        self.text_database_ageValue.SetLabel(_('0 days'))
        self.statusbar_panel.set_status(_('Ready'))

        # Normally loaded at start-up already (load_info_files ignores this while that is still running)
        if not self.history_data:
            self.load_info_files()

    def handle_first_time_setup(self) -> None:
        self.statusbar_panel.set_status(_('File Paths need to be set up'))
        self.Refresh()

        if iniFile.read_ini_file('preferences', 'language') == '':
            dlg = languagepicker.LanguagePicker(self)
            if dlg.ShowModal() == wx.ID_OK:  # Not English, which pfeMAME is running in
                languagepicker.show_restart_note(self, dlg.chosen)
            dlg.Destroy()

        msg = _("""
It Looks like this is the first time you have run pfeMAME
as the INI file data is missing.  Your first step is to 
set up the necessary file paths to MAME files and supporting
folders.

Please open EDIT > File Paths and set the MAME 
executable file path and ROMS folder as a minimum.  
NOTE:  You can use the Auto Find option in the file paths 
window to make this a lot easier in most cases.

After this you need to select some ROM categories (the right of the screen).
Then restart the application and refresh the ROMs database using
VIEW > Refresh ROMs Database.
        """
                )
        title = _('MAME file path or ROMS folder not found')
        functions.show_information_dialog(self, msg, title)

        for ctrl in self.get_checkbox_controls():
            ctrl.SetValue(True)
        self.on_update_categories()

    # ------------------------------------------------------------------------------------------------------------------
    # Write out the ROM database (mylist) to a cache file.  This is then reloaded on
    # startup to speed the startup process.
    def write_database(self) -> None:
        self.my_logger.info(_('Writing the temporary ROMs database file'))  # Write to the log file
        try:
            rom_database.save_database(os.path.join(self.data_dir, rom_database.DATABASE_NAME), self.mylist,
                                       self.system_rom_names)
        except (IOError, OSError):
            self.my_logger.error(_('Unable to write the temporary ROMs database file'))  # Write to the log file

    # ------------------------------------------------------------------------------------------------------------------
    # Build a list with ROM name and category from the catver.ini file
    # This is later used when building the ROM list to find out what the ROM category is.
    # category_dict is the dictionary created
    def build_categories(self) -> tuple[dict[str, str], str]:
        """
        Parses catver.ini and builds a dictionary of ROM categories.

        Returns:
            category_dict: A dictionary mapping ROM keys to categories.
            catver_version: The version string extracted from the file.
        """

        self.my_logger.info(_('Reading categories from catver.ini'))

        category_dict = {}
        catver_version = ''
        in_category_section = False

        try:
            with open(self.pathCatver, 'r', encoding='utf-8') as fp:
                for line in fp:
                    stripped = line.strip()

                    # Extract version string
                    if not catver_version and ';; catver.ini' in stripped.lower() and 'MAME' in stripped:
                        # e.g. ';; catver.ini 0.287 / 06-Apr-26 / MAME 0.287 ;;' - take just the number after
                        # MAME (the trailing ';;' used to be kept, so the MAME version check never worked)
                        start = stripped.find('MAME') + len('MAME')
                        match = re.search(r'\d+(?:\.\d+)+', stripped[start:])
                        catver_version = match.group(0) if match else stripped[start:].strip(' ;')
                        self.my_logger.info(_('catver.ini file version: {}').format(catver_version))

                    # Detect and process [Category] section
                    if stripped == '[Category]':
                        in_category_section = True
                        continue
                    elif stripped.startswith('[') and in_category_section:
                        break  # End of [Category] section

                    if in_category_section and '=' in stripped:
                        key, value = map(str.strip, stripped.split('=', 1))
                        category = value.split('/', 1)[0].strip()
                        category_dict[key] = category

        except (ValueError, OSError) as e:
            if isinstance(e, ValueError):
                msg = _('Parsing error in the catver.ini file. Please revert to a previous version.')
            elif isinstance(e, FileNotFoundError) or os.path.isdir(self.pathCatver):
                # A folder gives IsADirectoryError on Linux but PermissionError on Windows - either way it's the path
                msg = _('Cannot find the catver.ini file. Please check file path settings.  All ROMs will default '
                        'to Not Classified.')
            else:       # Permissions, a drive that has gone, etc.
                msg = _('Unable to read the catver.ini file. Please check file and folder permissions.')

            # This is read while the window is being built, so show the message once it is on screen
            self.when_window_shown(lambda: functions.show_error_dialog(self, msg, _('ERROR')))
            self.my_logger.error(str(e))

        # Add fallback category
        category_dict.setdefault('.1', 'Not Classified')
        # Add the Pinball category to be compatable with Visual Pinball
        category_dict.setdefault('.2', 'Pinball')

        self.my_logger.info(_('Completed reading categories from catver.ini'))
        return category_dict, catver_version

    # ------------------------------------------------------------------------------------------------------------------
    # Re-check which ROMs exist (e.g. after a ROM has been downloaded).  The full ROMs database build is in
    # rom_database.py.
    def get_exists(self) -> int:
        self.availableRoms = rom_database.set_exists_flags(self.mylist, self.rom_folders)
        return self.availableRoms

    # ------------------------------------------------------------------------------------------------------------------
    # Select the preferences tab (used when pressing CTRL-P).
    # Tabs: 0=ROMs List, 1=File Paths, 2=pfeMAME Preferences, 3=ROM Preferences [dynamic]
    def on_preferences_default(self, _event=None) -> None:
        self._select_notebook_page(self.preferences_panel)

    # ------------------------------------------------------------------------------------------------------------------
    def _select_notebook_page(self, page: wx.Window) -> None:
        """Show one of the main notebook's tabs.  Found by the page itself, not its (translated) tab title."""
        for i in range(self.list_notebook.GetPageCount()):
            if self.list_notebook.GetPage(i) is page:
                self.list_notebook.SetSelection(i)
                return

    # ------------------------------------------------------------------------------------------------------------------
    # This function is called on a key event from the list control.
    # We have to handle the scroll up and down ourselves to get around a problem trying to use EVT_KEY_UP
    # If we are in the 'favorites' view, then we will delete the selected game from the favorites list (if its delete)
    # We are also checking for ENTER key on selected rom to run that rom
    def on_key_press(self, event) -> None:
        key_code = event.GetKeyCode()
        self.inactivity_timer_start()  # Reset inactivity timer

        control_down = event.ControlDown()
        shift_down = event.ShiftDown()

        # Map basic key actions (no modifier keys)
        basic_key_actions = {
            wx.WXK_PAGEDOWN: lambda: self.scroll_list_by_page(1),
            wx.WXK_PAGEUP: lambda: self.scroll_list_by_page(-1),
            wx.WXK_DOWN: self.scroll_list_down,
            wx.WXK_UP: self.scroll_list_up,
            wx.WXK_RETURN: lambda: self.on_double_click(ignore_columns=True),
            wx.WXK_NUMPAD_ENTER: lambda: self.on_double_click(ignore_columns=True),
            wx.WXK_DELETE: self.delete_favorite,
            wx.WXK_BACK: self.delete_favorite,
            wx.WXK_F5: lambda: self.on_database_refresh(),
            wx.WXK_HOME: lambda: self.scroll_list_to(0),
            wx.WXK_END: lambda: self.scroll_list_to(self.list.GetItemCount() - 1),
            wx.WXK_WINDOWS_MENU: lambda: self.show_rom_menu(self.list.GetFirstSelected()),   # The 'menu' key
        }

        # Execute action if in basic keys
        action = basic_key_actions.get(key_code)
        if action:
            action()
            return

        # Map complex key combinations
        if key_code == ord('F') and control_down:
            self.on_find()
        elif key_code == ord('P') and control_down:
            if shift_down:
                self.preferences_rom_specific()
            else:
                self.on_preferences_default()
        elif key_code == ord('V') and shift_down and not control_down:
            self.on_fullscreen_video_player()
        elif key_code == ord('Q') and control_down:
            self.on_close()
        elif key_code == wx.WXK_F10 and shift_down:
            self.show_rom_menu(self.list.GetFirstSelected())     # SHIFT-F10 opens the right-click menu

    # ------------------------------------------------------------------------------------------------------------------
    def scroll_list_by_page(self, modifier: int) -> None:
        """
        Scroll the list up or down one page
        If the modifier is 1 then scroll down
        If the modifier is -1 then scroll up
        """

        row_count = self.list.GetItemCount()
        if row_count == 0:
            return
        self.video_stop()  # Stop the video player and reset the timer
        current_row = max(0, self.list.GetFirstSelected())
        # Stop at the first / last ROM rather than doing nothing when less than a page is left
        new_row = max(0, min(row_count - 1, current_row + modifier * self.list.GetCountPerPage()))
        self.list.Select(new_row)
        self.list.EnsureVisible(new_row)

    # ------------------------------------------------------------------------------------------------------------------
    # Jump to a row (HOME / END)
    def scroll_list_to(self, row: int) -> None:
        if 0 <= row < self.list.GetItemCount():
            self.video_stop()
            self.list.Select(row)
            self.list.EnsureVisible(row)

    # ------------------------------------------------------------------------------------------------------------------
    # Scroll the list down one line
    def scroll_list_down(self) -> None:
        self.video_stop()  # Stop the video player and reset the timer
        current_row = self.list.GetFirstSelected()
        if current_row < self.list.GetItemCount() - 1:
            self.list.Select(current_row + 1)
            self.list.EnsureVisible(current_row + 1)

    # ------------------------------------------------------------------------------------------------------------------
    # Scroll the list up one line
    def scroll_list_up(self) -> None:
        self.video_stop()  # Stop the video player and reset the timer
        current_row = self.list.GetFirstSelected()
        if current_row > 0:
            self.list.Select(current_row - 1)
            self.list.EnsureVisible(current_row - 1)

    # ------------------------------------------------------------------------------------------------------------------
    # Delete the currently selected file from the favorites list
    def delete_favorite(self, _event=None) -> None:
        self.video_stop()  # Stop the video

        results = self.get_virtual_list_row_info()
        rom_file_name = results.rom_file_name
        rom_name = results.rom_name
        system_file_name = results.system_file_name

        if results.favorites_flag != 1 or not rom_file_name:
            return  # Not a favorite or no ROM selected

        if system_file_name:
            rom_file_name = f'{rom_file_name}-->{rom_name}-->{system_file_name}'

        confirm_msg = _('Are you sure you want to remove {} from favorites?').format(rom_file_name)
        confirm_title = _('Confirm Remove From Favorites')

        dlg = wx.MessageDialog(None, confirm_msg, confirm_title, wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION)
        user_confirmed = dlg.ShowModal() == wx.ID_YES
        dlg.Destroy()

        if not user_confirmed:
            return

        # Clear the mylist flag
        _ignore, index = self.get_rom_file_name(system_file_name, rom_name, results.rom_file_name)
        if index is None:
            return
        # Flag this ROM as not a favorite - unless it is still on the watchlist, in which case show it as that
        self.mylist[index][index_favorite] = '2' if self._dat_file_contains('watchlist.dat', rom_file_name) else '0'

        try:
            functions.remove_dat_entry(os.path.join(self.data_dir, 'favorites.dat'), rom_file_name)
        except FileNotFoundError:
            msg = _('ERROR: Unable to find the favorites.dat file in the pfemame folder')
            self.my_logger.error(msg)
            self.messages_append(f'{msg}\n', True)
            return

        # Reload and refresh
        # self.load_all_dat_files()
        self.on_filter_rom_list(preserve_selection=True, preserve_search=True)

        msg = _('Romset {} removed from favorites').format(rom_file_name)
        self.statusbar_panel.set_status(msg)
        self.Refresh()
        self.my_logger.info(msg)
        self.messages_append(f'{msg}\n', True)
        self.write_database()

    # ------------------------------------------------------------------------------------------------------------------
    # Delete the currently selected file from the watchlist
    def delete_watchlist(self, rom_file_name=None, rom_name: str = '', system_file_name: str = '', remove_from_mylist: bool = True) -> None:
        """
        Remove a ROM from watchlist.dat.
        remove_from_mylist=True: the currently selected ROM (menu / key press - rom_file_name may be the event).
        remove_from_mylist=False: called from on_add_favorite with the ROM details; its mylist flag is left alone.
        """
        self.video_stop()  # Stop the video

        if remove_from_mylist:
            results = self.get_virtual_list_row_info()
            if results.favorites_flag != 2 or not results.rom_file_name:
                return  # Not on the watchlist or no ROM selected

            rom_file_name = results.rom_file_name
            rom_name = results.rom_name
            system_file_name = results.system_file_name
            display_name = f'{rom_file_name}-->{rom_name}-->{system_file_name}' if system_file_name else rom_file_name

            confirm_msg = _('Are you sure you want to remove {} from watchlist?').format(display_name)
            confirm_title = _('Confirm Remove From Watchlist')

            dlg = wx.MessageDialog(None, confirm_msg, confirm_title, wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION)
            user_confirmed = dlg.ShowModal() == wx.ID_YES
            dlg.Destroy()

            if user_confirmed:
                _ignore, index = self.get_rom_file_name(system_file_name, rom_name, rom_file_name)
                if index is None:
                    return
                self.mylist[index][index_favorite] = '0'  # Remove the watchlist flag
            else:
                return

        # The key used in watchlist.dat ('system-->name-->file' for system programs).  Don't add the suffix twice.
        if system_file_name and '-->' not in rom_file_name:
            rom_file_name = f'{rom_file_name}-->{rom_name}-->{system_file_name}'

        watchlist_file = os.path.join(self.data_dir, 'watchlist.dat')

        try:
            functions.remove_dat_entry(watchlist_file, rom_file_name)
        except FileNotFoundError:
            msg = _('ERROR: Unable to find the watchlist.dat file in the pfeMAME folder')
            self.my_logger.error(msg)
            self.messages_append(f'{msg}\n', True)
            return

        # Reload and refresh
        # self.load_all_dat_files()
        self.on_filter_rom_list(preserve_selection=True, preserve_search=True)

        msg = _('Romset {} removed from watchlist').format(rom_file_name)
        self.statusbar_panel.set_status(msg)
        self.Refresh()
        self.my_logger.info(msg)
        self.messages_append(f'{msg}\n', True)
        self.write_database()

    # ------------------------------------------------------------------------------------------------------------------
    # This function gets the currently selected row in the virtual list control.
    # It then looks at various columns and returns their values.
    # It uses the RomInfo dataclass
    def get_virtual_list_row_info(self):
        self.selected_row = int(self.list.GetFirstSelected())
        if 0 <= self.selected_row < len(self.mylist_filtered):
            row_data = self.mylist_filtered[self.selected_row]
            return RomInfo(
                rom_name=row_data[index_rom_name],
                rom_file_name=row_data[index_rom_file_name],
                rom_type=row_data[index_category],
                system_file_name=row_data[index_system_program_file_name],
                game_rating=int(row_data[index_rating]),
                short_name=row_data[index_system_short_name],
                favorites_flag=int(row_data[index_favorite]),
                system_folder_name=row_data[index_system_folder_name]
            )
        return RomInfo()

    # ------------------------------------------------------------------------------------------------------------------
    def on_single_click(self, _event=None) -> None:
        """
        Function to process the single click ROM selection
        This updates the snapshot image for the ROM (if it exists) and also the ROM & MAME info windows
        :param _event:
        :return:
        """
        if _event is not None:
            _event.Skip()
            self.list.Update()  # Repaint grid now so selection highlight shows before slow image/text work
        self.video_stop()  # Stop the video playback and reset it

        self.inactivity_timer_start()  # Reset the inactivity timer

        results = self.get_virtual_list_row_info()
        rom_file_name = results.rom_file_name

        # Find a matching video file using the stored cache
        def update_video_ui():
            if not os.path.isdir(self.foldersVideo) or self.video_disable:
                self.videoLoadCaption.Disable()
                label = _('Video Playback Disabled') if self.video_disable else _('No Video Available')
                self.videoLoadCaption.SetLabel(label)
                self.video_to_play = ''
                return

            file_match = self._get_video_folder_cache().get(rom_file_name, '')
            if file_match:
                self.videoLoadCaption.SetLabel(_('Video Available - Click to Play'))
                self.videoLoadCaption.Enable()
                self.video_to_play = file_match
                self.video_player.video_path = file_match

                if self.prefVideoAutoload == 'True' and self.image_options_index == 0:
                    self.video_player.set_video_caption(
                        _("Auto loading video in {} seconds").format(VIDEO_TIMER_DELAY))
                    self.video_playback_timer.Start(1000)
            else:
                self.videoLoadCaption.Disable()
                self.videoLoadCaption.SetLabel(_('No Video Available'))
                self.video_to_play = ''

        update_video_ui()
        image_file = self._compute_image_path(results)
        self.display_rom_image(image_file)

        self._show_info_text(results)
        self._show_play_stats()

    def _show_info_text(self, results) -> None:
        """Show the ROM Info (history.xml) and MAME Info (mameinfo.dat) text for a RomInfo."""
        for info_type, control in [('history', self.controlRomInfo), ('mameinfo', self.controlMAMEInfo)]:
            output = self.get_info_text(info_type, results.rom_file_name, results.system_file_name,
                                        results.short_name)
            control.SetValue(output)

    # ------------------------------------------------------------------------------------------------------------------
    def _find_system_row(self, rom_file_name: str, system_file_name: str) -> int | None:
        """
        Find the mylist row for a system program.  The same program file name can appear under more than one
        system, so the system ROM is matched as well; a match on the file name alone is kept as a fallback.

        :return: The mylist index, or None if the program is not in the list.
        """
        if not system_file_name:
            return None

        fallback = None
        for i, row in enumerate(self.mylist):
            if row[index_system_program_file_name] != system_file_name:
                continue
            if row[index_rom_file_name] == rom_file_name:
                return i
            if fallback is None:
                fallback = i
        return fallback

    # ------------------------------------------------------------------------------------------------------------------
    def _compute_image_path(self, results, for_save: bool = False) -> str:
        """
        Determine the image file path for the currently selected ROM and image option (Snapshot, PCB, Cabinet...).

        This is the single source of truth for *where* an image lives, used both for displaying the image and as
        the save target for the 'Replace image from online' feature, so the two never disagree.

        System programs (software list items such as 'Super Mario Bros.' loaded into 'nes') follow their own
        naming convention: <image folder>/<system ROM>/<software short name>.png, falling back to the program
        file name (minus its extension) when there is no short name.

        :param results:  A RomInfo instance for the selected ROM.
        :param for_save: Set when the caller is about to WRITE an image rather than read one.  Reading falls back
                         to the system's own image when the per-system sub-folder or the program's file is
                         missing; writing has to create them instead, and picks the short-name form the display
                         lookup prefers.
        :return: The full path to the image file (which may or may not yet exist), or '' if no image option exists.
        """
        if not self.image_options:
            return ''

        rom_file_name = results.rom_file_name
        system_file_name = results.system_file_name
        image_path = self.image_options[self.image_options_index][0]
        folder_path = os.path.join(image_path, rom_file_name)

        # The per-system sub-folder only exists once one of its programs has an image, so when saving an image
        # for a system program we build the path anyway and create the folder on write.
        if not os.path.isdir(folder_path) and not (for_save and system_file_name):
            # Folder doesn't exist → fallback to rom_file_name.png
            return os.path.join(image_path, f"{rom_file_name}.png")

        # Folder exists
        if not system_file_name:
            # No system file → fallback to default 0000.png
            return os.path.join(image_path, f"{rom_file_name}", "0000.png")

        # Folder exists and system_file_name is set
        index = self._find_system_row(rom_file_name, system_file_name)
        if index is not None:
            short_name_source = self.mylist[index][index_system_short_name]
            program_source = self.mylist[index][index_system_program_file_name]
        elif for_save:
            # Not in the list (shouldn't happen) but a save still needs a target, so use the selected row itself
            short_name_source, program_source = results.short_name, system_file_name
        else:
            # system_file_name not found → fallback to default 0000.png
            return os.path.join(image_path, f"{rom_file_name}", "0000.png")

        def get_file_name(program_name):
            if not program_name:
                return ''
            if rom_file_name != "visualpinball":
                program_name = os.path.splitext(program_name)[0]
            return os.path.join(image_path, rom_file_name, f"{program_name}.png")

        short_name_file = get_file_name(short_name_source)
        program_file = get_file_name(program_source)

        if short_name_file and os.path.exists(short_name_file):
            return short_name_file
        if program_file and os.path.exists(program_file):
            return program_file

        # Neither exists yet: a save creates the preferred short-name file (which the lookup above checks first),
        # while a read keeps the original fallback so the 'missing image' behaviour is unchanged.
        return (short_name_file or program_file) if for_save else (program_file or short_name_file)

    # ------------------------------------------------------------------------------------------------------------------
    def on_replace_rom_image(self) -> None:
        """
        Right-click handler for the ROM image thumbnail.  Searches online for replacement images that match the
        currently selected ROM and image option (Snapshot, PCB, Cabinet...), and presents them in a tiled picker.
        The chosen image is downloaded, converted to PNG, and written to the location the app loads images from.

        When the selected row has a system file name it is a system program - a software list item such as
        'Super Mario Bros.' loaded into the 'nes' system - rather than an arcade machine.  The ROM name of such a
        row is the *system*, so searching with it would return pictures of the console; the search is therefore
        aimed at the program itself, and the result is saved under the system program naming convention that
        _compute_image_path() implements.
        """
        if not self.image_options:
            self.statusbar_panel.set_status(_('No image folders are configured'))
            return

        results = self.get_virtual_list_row_info()
        if not results.rom_file_name:
            self.statusbar_panel.set_status(_('Select a ROM first'))
            return

        category_label = self.image_options[self.image_options_index][1]     # English - the search uses it
        shown_label = _(category_label)
        target_path = self._compute_image_path(results, for_save=True)
        if not target_path:
            return

        if results.system_file_name:
            # System program: search for the software item, with the system used only as context.
            system = online_image_search.SystemContext(
                machine_name=results.rom_file_name,      # System ROM name, e.g. 'nes'
                machine_desc=results.rom_name,           # System description, e.g. 'Nintendo Entertainment System'
                software_list=results.system_folder_name,
                software_short=results.short_name        # Software list short name, e.g. 'smb'
            )
            # Best names available without shelling out to MAME.  The worker below upgrades them to the software
            # list description ('Super Mario Bros.') when MAME can resolve one.
            short_name = results.short_name or os.path.splitext(results.system_file_name)[0]
            full_name = os.path.splitext(results.system_file_name)[0]
            display_name = f'{full_name} ({results.rom_name})'
        else:
            system = None
            short_name = results.rom_file_name      # MAME short / ROM name, e.g. 'galaxian'
            full_name = results.rom_name            # Full description, e.g. 'Galaxian (Namco set 1)'
            display_name = results.rom_name

        self.video_stop()
        self.statusbar_panel.set_status(_('Searching online for {} images...').format(shown_label))
        self.messages_append(_('Searching online for {0} images for "{1}"\n').format(shown_label, display_name))

        busy = busy_window.BusyWindow(self)
        busy.show()

        def worker():
            name_to_search = full_name
            label = display_name
            if system is not None:
                # The software list description is the accurate name to search with, but resolving it runs MAME,
                # so it is done here on the background thread and degrades to the file name if it fails.
                try:
                    description, software_list = functions.get_software_details(
                        self.path_mame_exe, results.rom_file_name, results.short_name)
                    if description:
                        name_to_search = description
                        label = f'{description} ({results.rom_name})'
                    if software_list:
                        system.software_list = software_list
                except Exception as exc:
                    self.my_logger.warning(f'Could not resolve the system program description: {exc}')

            try:
                candidates = online_image_search.search(short_name, name_to_search, category_label,
                                                        self.my_logger, system=system)
            except Exception as exc:
                self.my_logger.error(f'Online image search failed: {exc}')
                candidates = []
            wx.CallAfter(self._show_image_picker, busy, candidates, target_path, shown_label, label)

        Thread(target=worker, daemon=True).start()

    # ------------------------------------------------------------------------------------------------------------------
    def _show_image_picker(self, busy, candidates, target_path, category_label, display_name) -> None:
        """Close the busy window and open the tiled picker with the search results (runs on the GUI thread)."""
        busy.close()
        self.statusbar_panel.set_status(_('Ready'))

        if not candidates:
            self.messages_append(_('No online images were found for "{}"\n').format(display_name), True)
            wx.MessageBox(_('No suitable images were found online for this ROM.'),
                          _('No Images Found'), wx.OK | wx.ICON_INFORMATION, self)
            return

        title = _('Select a {0} image for {1}').format(category_label, display_name)
        dlg = image_picker_dialog.ImagePickerDialog(self, title, candidates)
        try:
            if dlg.ShowModal() == wx.ID_OK and dlg.selected_candidate:
                self._apply_replacement_image(dlg.selected_candidate, target_path)
        finally:
            dlg.Destroy()
        self.inactivity_timer_start()

    # ------------------------------------------------------------------------------------------------------------------
    def _apply_replacement_image(self, candidate, target_path) -> None:
        """Download the chosen candidate, confirm any overwrite, save it as a PNG, and refresh the display."""
        self.statusbar_panel.set_status(_('Downloading image...'))
        try:
            data = online_image_search.download_image(candidate.full_url)
            image = wx.Image(io.BytesIO(data))
            if not image.IsOk():
                raise IOError('downloaded data is not a valid image')
        except Exception as exc:
            self.my_logger.error(f'Failed to download replacement image: {exc}')
            self.messages_append(_('Failed to download the selected image\n'), True)
            self.enable_alert_timer()
            self.statusbar_panel.set_status(_('Ready'))
            wx.MessageBox(_('The selected image could not be downloaded.'),
                          _('Download Failed'), wx.OK | wx.ICON_ERROR, self)
            return

        # Confirm before overwriting an existing file
        if os.path.exists(target_path):
            answer = wx.MessageBox(
                _('An image already exists at:\n{}\n\nReplace it with the selected image?').format(target_path),
                _('Replace Existing Image'), wx.YES_NO | wx.ICON_QUESTION, self)
            if answer != wx.YES:
                self.statusbar_panel.set_status(_('Ready'))
                return

        try:
            os.makedirs(os.path.dirname(target_path), exist_ok=True)
            # Save as PNG regardless of the source format, since the app loads images as PNG.
            if not image.SaveFile(target_path, wx.BITMAP_TYPE_PNG):
                raise IOError('SaveFile returned False')
        except Exception as exc:
            self.my_logger.error(f'Failed to save replacement image to {target_path}: {exc}')
            self.messages_append(_('Failed to save the image to {}\n').format(target_path), True)
            self.enable_alert_timer()
            self.statusbar_panel.set_status(_('Ready'))
            wx.MessageBox(_('The image could not be saved to:\n{}').format(target_path),
                          _('Save Failed'), wx.OK | wx.ICON_ERROR, self)
            return

        # Drop any cached scaled bitmap for this path so the new image shows immediately
        _scaled_rom_image.cache_clear()
        self.messages_append(_('Saved new image to {}\n').format(target_path))
        self.statusbar_panel.set_status(_('Image updated'))
        self.on_single_click()

    # ------------------------------------------------------------------------------------------------------------------
    def _rom_download_folder(self) -> str:
        """
        The folder a downloaded ROM ZIP should be written to: the first entry of the (possibly semicolon-separated)
        MAME rompath.  Returns '' if no usable rompath is configured.
        """
        return self.rom_folders[0] if self.rom_folders else ''

    # ------------------------------------------------------------------------------------------------------------------
    # How many of the search results to download + verify with MAME up front.  The rest are verified on demand via
    # the picker's "Verify more" button.
    ROM_VALIDATE_TOP_N = 5

    def on_search_rom_online(self, _event=None) -> None:
        """
        Right-click handler for the ROMs list.  Lets the operator pick a download source (and manage credentials),
        searches online for the selected ROM's ZIP, validates the top candidates against the running MAME version,
        and presents them in a picker.  The chosen ZIP is saved to the MAME rompath folder.
        """
        download_folder = self._rom_download_folder()
        if not download_folder:
            self.statusbar_panel.set_status(_('No ROM folder (rompath) is configured'))
            wx.MessageBox(_('No ROM folder is configured in mame.ini (rompath), so the ROM cannot be saved.'),
                          _('No ROM Folder'), wx.OK | wx.ICON_ERROR, self)
            return

        results = self.get_virtual_list_row_info()
        if not results.rom_file_name:
            self.statusbar_panel.set_status(_('Select a ROM first'))
            return

        short_name = results.rom_file_name      # MAME short / ROM name and ZIP base name, e.g. 'galaxian'
        full_name = results.rom_name            # Full description, e.g. 'Galaxian (Namco set 1)'

        # 1. Let the operator choose the source(s) and manage credentials.
        source_dlg = rom_source_dialog.RomSourceDialog(self, self.mame_version, logger=self.my_logger)
        try:
            if source_dlg.ShowModal() != wx.ID_OK or not source_dlg.selected_sources:
                return
            sources = list(source_dlg.selected_sources)
        finally:
            source_dlg.Destroy()

        # Gather stored credentials for the chosen credentialed sources.
        creds = {}
        for key in sources:
            if online_rom_search.source_needs_credentials(key):
                entry = rom_credentials.get(key)
                if entry:
                    creds[key] = entry

        self._rom_temp_dirs = []  # temp folders created during validation, cleaned up when the picker closes
        self.statusbar_panel.set_status(_('Searching online for ROM "{}"...').format(short_name))
        self.messages_append(_('Searching online for ROM "{0}" ({1})\n').format(short_name, full_name))

        cancel = threading.Event()
        busy = busy_window.BusyWindow(self, on_cancel=cancel.set)
        busy.show()
        progress = self._rom_search_progress_callback(busy)

        def worker():
            try:
                try:
                    candidates = online_rom_search.search(short_name, full_name, sources=sources,
                                                          mame_version=self.mame_version, creds=creds,
                                                          logger=self.my_logger, progress=progress, cancel=cancel)
                except online_rom_search.SearchCancelled:
                    raise
                except Exception as exc:
                    self.my_logger.error(f'Online ROM search failed: {exc}')
                    candidates = []
                # Download + verify the most promising few before showing the list.
                self._validate_rom_candidates(candidates, short_name, 0, self.ROM_VALIDATE_TOP_N, progress, cancel)
            except online_rom_search.SearchCancelled:
                wx.CallAfter(self._rom_search_cancelled, busy, short_name)
                return
            wx.CallAfter(self._show_rom_picker, busy, candidates, short_name, full_name, download_folder)

        Thread(target=worker, daemon=True).start()

    # ------------------------------------------------------------------------------------------------------------------
    def _rom_search_progress_callback(self, busy=None):
        """
        A progress(message_format, *args, **kwargs) callback for the online ROM search worker threads: shows each step
        in the status bar and the Please Wait window (on the GUI thread).  The message is translated here.
        """
        def show(message: str, *args, **kwargs) -> None:
            if not self or self._app_closing:
                return
            text = _(message).format(*args, **kwargs)
            self.statusbar_panel.set_status(text)
            self.statusbar_panel.Update()
            if busy:
                busy.set_message(text)

        return lambda message, *args, **kwargs: wx.CallAfter(show, message, *args, **kwargs)

    def _rom_search_cancelled(self, busy, short_name: str) -> None:
        busy.close()
        self._cleanup_rom_temp_dirs()
        self.my_logger.info(f'Online ROM search for {short_name} cancelled')
        self.messages_append(_('Online ROM search for "{}" cancelled\n').format(short_name))
        self.statusbar_panel.set_status(_('ROM search cancelled'))

    # ------------------------------------------------------------------------------------------------------------------
    @staticmethod
    def _parse_verifyroms(out: str) -> tuple:
        """
        Interpret MAME '-verifyroms' output.  Returns (status, wrong_basenames, missing_count) where status is one
        of 'good' / 'best available' / 'bad' / 'error'.  Best-effort: phrasing varies slightly across MAME versions,
        so we fall back to the overall status line and degrade gracefully.
        """
        text = out or ''
        lowered = text.lower()
        if 'is good' in lowered:
            status = 'good'
        elif 'is best available' in lowered:
            status = 'best available'
        elif 'is bad' in lowered:
            status = 'bad'
        else:
            status = 'error'  # e.g. "romset X not found"

        wrong_basenames = set()
        missing_count = 0
        for line in text.splitlines():
            upper = line.upper()
            # Per-file problem lines look like: "galaxian: 7l (2048 bytes) - NOT FOUND"
            if 'NOT FOUND' in upper:
                missing_count += 1
            elif 'INCORRECT' in upper or 'WRONG' in upper or 'BAD CHECKSUM' in upper:
                match = re.search(r'[:\-]\s*([\w.\-]+)\s*\(', line)
                if match:
                    wrong_basenames.add(match.group(1).lower())
                else:
                    wrong_basenames.add(f'_wrong_{len(wrong_basenames)}')
        return status, wrong_basenames, missing_count

    # ------------------------------------------------------------------------------------------------------------------
    # How long MAME may take to verify one downloaded candidate before it is given up on
    ROM_VERIFY_TIMEOUT = 120

    def _validate_rom_candidates(self, candidates: list, short_name: str, start: int, count: int,
                                 progress=None, cancel=None) -> None:
        """
        Download candidates[start:start+count] to isolated temp folders and run MAME '-verifyroms' on each against
        the current MAME version, recording the result on each RomCandidate.  Runs on a worker thread.
        progress / cancel are as for online_rom_search.search; cancelling raises online_rom_search.SearchCancelled.
        """
        if not getattr(self, '_rom_temp_dirs', None):
            self._rom_temp_dirs = []
        report = online_rom_search.Reporter(progress, cancel)
        N_ = online_rom_search.N_

        batch = candidates[start:start + count]
        for number, candidate in enumerate(batch, 1):
            if candidate.verify_status or candidate.local_path:
                continue  # already validated
            try:
                report(N_('Downloading result {number} of {count} from {source} to check it'), number=number,
                       count=len(batch), source=candidate.source)
                temp_dir = tempfile.mkdtemp(prefix='pfemame_rom_')
                self._rom_temp_dirs.append(temp_dir)
                zip_path = os.path.join(temp_dir, f'{short_name}.zip')
                last_shown = [0.0]

                def downloaded(done, total, number=number, source=candidate.source):
                    now = time.monotonic()
                    if progress and now - last_shown[0] >= 0.5:
                        last_shown[0] = now
                        progress(N_('Downloading result {number} of {count} from {source} ({done} of {total})'),
                                 number=number, count=len(batch), source=source,
                                 done=online_rom_search.human_size(done),
                                 total=online_rom_search.human_size(total) or '?')

                online_rom_search.download_rom(candidate.download_url, zip_path,
                                               auth_header=candidate.auth_header,
                                               cookie_header=candidate.cookie_header,
                                               progress=downloaded, cancel=cancel)
                candidate.local_path = zip_path
                if not candidate.size:
                    candidate.size = os.path.getsize(zip_path)

                self.my_logger.info(f'Validating ROM candidate from {candidate.source}: {candidate.download_url} '
                                    f'-> {zip_path} ({os.path.getsize(zip_path)} bytes)')
                report(N_('Checking result {number} of {count} with MAME'), number=number, count=len(batch))
                out, err = self._run_mame_command(['-rompath', temp_dir, '-verifyroms', short_name],
                                                  timeout=self.ROM_VERIFY_TIMEOUT)
                status, wrong, missing = self._parse_verifyroms(f'{out}\n{err}')
                self.my_logger.info(f'verifyroms {short_name} ({candidate.source}): status={status}, '
                                    f'wrong={len(wrong)}, missing={missing}')

                # Count files actually present in the downloaded ZIP for the "matching" figures.
                try:
                    with zipfile.ZipFile(zip_path) as archive:
                        present = [n for n in archive.namelist() if not n.endswith('/')]
                except Exception:
                    present = []
                present_count = len(present)

                candidate.verify_status = status
                if status == 'good':
                    candidate.verify_good = present_count
                    candidate.verify_bad = 0
                else:
                    candidate.verify_bad = len(wrong) + missing
                    candidate.verify_good = max(0, present_count - len(wrong))
            except online_rom_search.SearchCancelled:
                raise
            except Exception as exc:
                self.my_logger.warning(f'Could not validate ROM candidate {candidate.download_url}: {exc}')
                candidate.verify_status = 'error'

    # ------------------------------------------------------------------------------------------------------------------
    def _cleanup_rom_temp_dirs(self) -> None:
        """Remove any temp folders created while validating candidates."""
        for temp_dir in getattr(self, '_rom_temp_dirs', []):
            try:
                shutil.rmtree(temp_dir, ignore_errors=True)
            except Exception:
                pass
        self._rom_temp_dirs = []

    # ------------------------------------------------------------------------------------------------------------------
    def _show_rom_picker(self, busy, candidates, short_name, full_name, download_folder) -> None:
        """Close the busy window and open the ROM picker with the (validated) search results (GUI thread)."""
        busy.close()
        self.statusbar_panel.set_status(_('Ready'))

        if not candidates:
            self._cleanup_rom_temp_dirs()
            self.messages_append(_('No online ROM downloads were found for "{}"\n').format(short_name), True)
            wx.MessageBox(_('No downloadable ROM ZIP was found online for this ROM.'),
                          _('No ROM Found'), wx.OK | wx.ICON_INFORMATION, self)
            return

        # Offer "Verify more" only if some candidates are still unverified.
        has_unverified = any(not c.verify_status and not c.local_path for c in candidates)
        verify_more = (lambda dlg: self._on_verify_more(dlg, candidates, short_name)) if has_unverified else None

        title = _('Select a ROM ZIP to download for {}').format(full_name or short_name)
        dlg = rom_picker_dialog.RomPickerDialog(self, title, candidates, on_verify_more=verify_more)
        chosen = dlg.selected_candidate if (dlg.ShowModal() == wx.ID_OK) else None
        dlg.Destroy()

        if chosen is not None:
            # Don't clean up temp dirs here: the save runs on a background thread and still needs the validated
            # temp copy.  _finish_rom_download does the cleanup once the move/download has completed.
            self._apply_downloaded_rom(chosen, download_folder)
        else:
            self._cleanup_rom_temp_dirs()
        self.inactivity_timer_start()

    # ------------------------------------------------------------------------------------------------------------------
    def _on_verify_more(self, dlg, candidates, short_name) -> None:
        """Validate the next batch of so-far-unverified candidates, then refresh the picker (GUI thread entry)."""
        # Find where the unverified ones start so we validate the next ROM_VALIDATE_TOP_N of them.
        start = next((i for i, c in enumerate(candidates) if not c.verify_status and not c.local_path),
                     len(candidates))

        progress = self._rom_search_progress_callback()

        def worker():
            self._validate_rom_candidates(candidates, short_name, start, self.ROM_VALIDATE_TOP_N, progress)
            wx.CallAfter(self._after_verify_more, dlg, candidates)

        Thread(target=worker, daemon=True).start()

    def _after_verify_more(self, dlg, candidates) -> None:
        self.statusbar_panel.set_status(_('Ready'))
        if not dlg:
            return
        dlg.refresh_rows()
        still_unverified = any(not c.verify_status and not c.local_path for c in candidates)
        dlg.set_verify_enabled(still_unverified)

    # ------------------------------------------------------------------------------------------------------------------
    def _apply_downloaded_rom(self, candidate, download_folder) -> None:
        """Save the chosen ROM ZIP to the rompath (reusing the validated copy if present), confirm overwrite."""
        target_path = os.path.join(download_folder, candidate.filename)

        # Confirm before overwriting an existing ROM file
        if os.path.exists(target_path):
            answer = wx.MessageBox(
                _('A ROM already exists at:\n{}\n\nReplace it with the downloaded ROM?').format(target_path),
                _('Replace Existing ROM'), wx.YES_NO | wx.ICON_QUESTION, self)
            if answer != wx.YES:
                self.statusbar_panel.set_status(_('Ready'))
                self._cleanup_rom_temp_dirs()
                return

        self.statusbar_panel.set_status(_('Saving ROM {}...').format(candidate.filename))
        cancel = threading.Event()
        busy = busy_window.BusyWindow(self, on_cancel=cancel.set)
        busy.show()
        progress = self._rom_search_progress_callback(busy)
        N_ = online_rom_search.N_
        last_shown = [0.0]

        def downloaded(done, total):
            now = time.monotonic()
            if now - last_shown[0] >= 0.5:
                last_shown[0] = now
                progress(N_('Downloading {file_name} from {source} ({done} of {total})'),
                         file_name=candidate.filename, source=candidate.source, done=online_rom_search.human_size(done),
                         total=online_rom_search.human_size(total) or '?')

        # Download to a temporary file first so a failed/partial download never replaces a good ROM.
        temp_path = target_path + '.part'
        result: dict = {}

        def worker():
            try:
                os.makedirs(download_folder, exist_ok=True)
                if candidate.local_path and os.path.exists(candidate.local_path):
                    # Already downloaded during validation - just move it into place (handles cross-drive temp).
                    if os.path.exists(target_path):
                        os.remove(target_path)
                    shutil.move(candidate.local_path, target_path)
                    candidate.local_path = ''
                else:
                    progress(N_('Downloading {file_name} from {source}'), file_name=candidate.filename,
                             source=candidate.source)
                    online_rom_search.download_rom(candidate.download_url, temp_path,
                                                   auth_header=candidate.auth_header,
                                                   cookie_header=candidate.cookie_header,
                                                   progress=downloaded, cancel=cancel)
                    if os.path.exists(target_path):
                        os.remove(target_path)
                    os.replace(temp_path, target_path)
                result['ok'] = True
            except online_rom_search.SearchCancelled:
                result['cancelled'] = True
            except Exception as exc:
                result['error'] = str(exc)
                try:
                    if os.path.exists(temp_path):
                        os.remove(temp_path)
                except Exception:
                    pass
            wx.CallAfter(self._finish_rom_download, busy, result, target_path, candidate)

        Thread(target=worker, daemon=True).start()

    # ------------------------------------------------------------------------------------------------------------------
    def _finish_rom_download(self, busy, result, target_path, candidate) -> None:
        """Report the outcome of a ROM download and refresh the list's exists flags (runs on the GUI thread)."""
        busy.close()
        # The save has finished (success or failure), so the validation temp copies are no longer needed.
        self._cleanup_rom_temp_dirs()
        if result.get('cancelled'):
            self.messages_append(_('Download of ROM "{}" cancelled\n').format(candidate.filename))
            self.statusbar_panel.set_status(_('ROM download cancelled'))
            return
        if not result.get('ok'):
            self.my_logger.error(f'Failed to download ROM {candidate.filename}: {result.get("error")}')
            self.messages_append(_('Failed to download ROM "{}"\n').format(candidate.filename), True)
            self.enable_alert_timer()
            self.statusbar_panel.set_status(_('Ready'))
            wx.MessageBox(_('The ROM could not be downloaded:\n{}').format(result.get('error', '')),
                          _('Download Failed'), wx.OK | wx.ICON_ERROR, self)
            return

        self.messages_append(_('Downloaded ROM to {}\n').format(target_path))
        self.statusbar_panel.set_status(_('ROM downloaded'))
        # Refresh the exists flags so the freshly downloaded ROM is marked as present, then redraw the list.
        try:
            self.get_exists()
            self.list.ForceRefresh()
            self.update_rom_numbers(len(self.mylist_filtered))
            self.write_database()       # So the ROM still shows as present after a restart
        except Exception as exc:
            self.my_logger.warning(f'Could not refresh ROM exists flags after download: {exc}')

    # ------------------------------------------------------------------------------------------------------------------
    # This provides a basic override function for the softwarelist HASH file short names.
    # For systems, to get the software HASH file support (needed for cheats), you have to run the system program
    # using the HASH (XML) file short name, not the program file name.  The problem is that some of these do not seem to
    # be working properly (e.g. ZX81 and ZX Spectrum tape files).  To get around this I have added this override feature
    # at least for now, until either the problem is solved, or I find out that I have been doing it wrong (honestly, the
    # documentation in this area of MAME is virtually non-existent).
    def on_suppress_short_version(self, _event) -> None:
        self.on_double_click(suppress=False)

    # ------------------------------------------------------------------------------------------------------------------
    # Start a random ROM
    # This will search for a random ROM that has the exists flag set (no point running one that doesn't exist).
    # It won't however be able to determine that the selected ROM is working.
    def on_random(self, _event) -> None:

        # Build a list of indices of ROMs that actually exist in the current filtered view
        existing_indices = [
            i for i, row in enumerate(self.mylist_filtered)
            if row[index_exists] == '1'
        ]

        if not existing_indices:
            functions.show_error_dialog(
                self,
                _('I am having trouble finding a ROM to play that exists. Do you actually have any?'),
                _('ERROR'))
            return

        random_index = existing_indices[randint(0, len(existing_indices) - 1)]
        self.list.SetFocus()
        self.list.Select(random_index)
        self.list.EnsureVisible(random_index)
        wx.GetApp().Yield()
        self.on_double_click()

    # ------------------------------------------------------------------------------------------------------------------
    # Function to process the double click event to run a ROM
    def on_double_click(self,
                        _event=None,
                        suppress: bool = True,
                        force_mame: bool = False,
                        ignore_columns: bool = False,
                        input_playback_or_record: str = '',
                        pb_r_filename: str = '',
                        rom_file_name: str = '',
                        system_file_name: str = '') -> None:
        """
        Function to process the double click event to run a ROM
        :param _event:
        :param suppress: This will prevent the software list HASH file from being used for systems and will just run the
                         system based on the file name.  This is needed as some systems may not have the right checksum
                         or some other detail contained in the HASH file and therefore won't run the program.
        :param force_mame: Force the use of the MAME engine
        :param ignore_columns: If this is False, then double clicking in any column will run the game.  If its True then it
                               will check if the mouse pointer is in the favorite column or the ratings column.  If its in
                               one of those, a different action will be performed (changing game rating or adding / removing
                               from the favorites list).
        :param input_playback_or_record: Tells the function to send info to rungame to that when the MAME rom is executed,
                                         a command is sent to record or play back previously recorded input file.
        :param pb_r_filename: This is the file name for the above
        :param rom_file_name: ROM file name to run
        :param system_file_name: System file name it applicable
        :return:
        """

        if _event is not None:
            _event.Skip()

        self.inactivity_timer.Stop()  # Stop the inactivity timer so we don't trigger screensaver when playing a ROM
        self.video_stop()  # Stop the video

        selected_row = self.get_virtual_list_row_info()

        # Allow a double click in the favorites column or the ROM rating column to make a change to those settings
        # but not actually run the ROM
        if self.start_up_complete and not ignore_columns and self.prefClickFavRating == 'True':
            column_selected = functions.get_column_clicked(self.list)  # Get the column that was clicked in

            if column_selected == index_favorite:
                # If the ROM is not currently flagged as a favorite, then make it one, otherwise remove it from
                # the favorites list and delete the flag
                if selected_row.favorites_flag == 0:
                    self.on_add_favorite()
                else:
                    self.delete_favorite()
                return

            if column_selected == index_rating:
                self.on_set_rating(_event)
                return

        # If the names were not passed into the function call, then get them from the curerntly selected row
        if not rom_file_name:
            rom_file_name = selected_row.rom_file_name
            rom_name = selected_row.rom_name
            system_file_name = selected_row.system_file_name
            short_name = selected_row.short_name
        else:
            # Named by the caller (e.g. -r on the command line): take the rest of its details from the ROMs list,
            # not from whatever row happens to be selected
            _key, index = self.get_rom_file_name(system_file_name, '', rom_file_name)
            row = self.mylist[index] if index is not None else None
            rom_name = row[index_rom_name] if row else rom_file_name
            short_name = row[index_system_short_name] if row else ''

        # Get the system folder name based upon what has already been stored in mylist (assuming one is needed).
        # The same program file name can be in more than one system's list, so match the system ROM as well.
        index = self._find_system_row(rom_file_name, system_file_name)
        system_folder_name = self.mylist[index][index_system_folder_name] if index is not None else ''

        #  Check if we are suppressing the softwarelist HASH file short name version for system files
        suppress_short_name = False if suppress and self.pref_short_name_global_suppress != 'True' else True

        # Make sure there is actually a rom file selected (When application is first run there isn't)
        # This just prevents odd errors in the output
        if not rom_file_name:
            self.my_logger.error(_('Tried running a ROM without a file name selected'))
            return  # Exit the function as there is no point proceeding

        if system_file_name:
            msg = _('System {rom} started with program {program} selected').format(rom=rom_name,
                                                                                  program=system_file_name)
        else:
            msg = _('Romset {} started').format(rom_name)
        self.my_logger.info(msg)  # Write to the log file
        self.messages_append(f'{msg}\n')

        # Get the folder the mame.ini file resides in (Should be the same as the other MAME folders
        folder_mame_ini = os.path.dirname(self.path_to_mame_ini_file)

        self.joystick_block = True  # Block the joystick events from being triggered when running a ROM
        self.inactivity_timer_block = True  # Block the inactivity timer from being started while running a ROM

        # Call the rungame class (imported file) and make this party happen.  This is done in a separate thread.
        rungame.RunGame(self,
                        rom_file_name,
                        self.path_mame_exe,
                        'Normal View',
                        rom_name,
                        system_file_name,
                        short_name,
                        system_folder_name,
                        folder_mame_ini,
                        self.folder_mapping,
                        suppress_short_name,
                        input_playback_or_record,
                        pb_r_filename,
                        force_mame
                        )

    # ------------------------------------------------------------------------------------------------------------------
    # Process the thread request to update the main process gui.
    # This one is to send data to the messages control
    def update_display_messages(self, msg: str, add_delimiter: bool = False, include_datetime: bool = True) -> None:
        self.messages_append(msg, add_delimiter, include_datetime)

    # ------------------------------------------------------------------------------------------------------------------
    # Process the thread request to update the main process gui.
    # This one is to send data to the logfile
    def update_logfile(self, msg: str) -> None:
        self.my_logger.info(msg)  # Write to the log file

    # ------------------------------------------------------------------------------------------------------------------
    # Process the thread request to update the main process gui.
    # This one is to send data pop-up messages
    def update_display_popups(self, msg: str) -> None:
        functions.show_information_dialog(self, msg, _('Important Notification'))

    # ------------------------------------------------------------------------------------------------------------------
    # Process the thread request to update the main process gui.
    # This one is to display a statusbar message
    def update_status(self, msg: str) -> None:
        self.statusbar_panel.set_status(msg)
        self.Refresh()

    # ------------------------------------------------------------------------------------------------------------------
    # Process the thread request to update the main process gui.
    # Update the number of runs for the currently selected game
    def update_display_number_of_runs(self, attr1: str, attr2: str, attr3: str, attr4: bool, attr5: str) -> None:
        self.update_number_runs(rom_file_name=attr1,
                                rom_name=attr2,
                                system_file_name_passed=attr3,
                                is_a_system=attr4,
                                caller=attr5)  # Update the number of runs for the ROM

    # ------------------------------------------------------------------------------------------------------------------
    # Processes the CTRL-F keypress capture and set up, so you can just start typing to find a ROM
    def on_find(self, _event=None) -> None:
        self.controlSearch.SetFocus()  # Set focus to the search input control
        self.controlSearch.SetSelection(-1, -1)  # Select all text in the control

    # ------------------------------------------------------------------------------------------------------------------
    # Some cleanup required for the on_close and on_restart events
    def cleanup(self) -> None:
        self._app_closing = True  # used by software update to make sure we don't try to update the GUI if app is shutdown
        self._database_build_cancel.set()   # Stop a ROMs database rebuild that is still running (and its MAME)

        # Gather all ini updates
        ini_updates = []

        # Store the column widths in the main view ROMs list so that they are automatically reset upon loading
        count = self.list.GetColumnCount()
        for col_number in range(count):
            col_width = str(self.list.GetColumnWidth(col_number))
            ini_updates.append(('system', f'column_width_{col_number}', col_width))

        results = self.get_virtual_list_row_info()
        rom_name = results.rom_name
        system_file_name = results.system_file_name

        # Store the currently selected view and row so that they can be recalled on startup
        view = self.get_view_key()  # Store the language-neutral key, not the translated label

        ini_updates.append(('system', 'lastviewselected', view))
        if rom_name:
            ini_updates.append(('system', 'lastromselected', rom_name))
            ini_updates.append(('system', 'lastsystemselected', system_file_name))

        # Write all settings in one call (unless a settings restore has just replaced pfemame.ini)
        if not self._skip_ini_save_on_close:
            iniFile.set_ini_file_variables(ini_updates)

        # Stop gamepad thread
        if self.joystick is not None:
            self.joystick_polling_timer.Stop()
            self.joystick.Destroy()  # Delete the joystick instance to kill its thread

        # Stop all other timer related events
        self.alert_timer.Stop()
        self._database_progress_timer.Stop()
        self.inactivity_timer.Stop()
        self.video_playback_timer.Stop()
        if self._search_timer:
            self._search_timer.Stop()
        # Deferred autoload play - left running it fires into a half destroyed window
        if self._pending_play is not None and self._pending_play.IsRunning():
            self._pending_play.Stop()

        # Clear the bitmap caches
        StarCellRenderer._bitmaps.clear()
        TickCrossRenderer._bitmaps.clear()

        if hasattr(self, 'video_player') and self.video_player:
            self.video_player.cleanup()  # Stop and clean up the video player

        # Unsubscribe all pubsub listeners before destroying
        pub.unsubscribe(self.update_display_messages, 'update')
        pub.unsubscribe(self.update_logfile, 'log')
        pub.unsubscribe(self.update_display_popups, 'popup')
        pub.unsubscribe(self.update_display_number_of_runs, 'number_of_runs')
        pub.unsubscribe(self.on_rom_played, 'rom_played')
        pub.unsubscribe(self.enable_alert_timer, 'enable_alert_timer')
        pub.unsubscribe(self.update_status, 'status')
        pub.unsubscribe(self.setup_ini_variables, 'setup_ini')
        pub.unsubscribe(self.on_force_restart, 'force_restart')
        pub.unsubscribe(self.on_restart_now, 'restart_now')
        pub.unsubscribe(self.on_refresh_window, 'refresh_window')

    # ------------------------------------------------------------------------------------------------------------------
    # Handle the close event and ensure the parent window is given back control
    def on_close(self, _event=None) -> None:

        if hasattr(self, 'filepaths_panel') and self.filepaths_panel.data_changed:
            dlg = wx.MessageDialog(
                self,
                _('Unapplied FilePath changes – are you sure you wish to discard changes?'),
                _('Unapplied Changes'),
                wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION
            )
            result = dlg.ShowModal()
            dlg.Destroy()
            if result != wx.ID_YES:
                return

        self.cleanup()  # Perform some cleanup before closing
        elapsed_time = str(datetime.timedelta(seconds=time.time() - self.startup_process_start_time))
        self.my_logger.info(_('Application Ended after {}').format(elapsed_time))  # Write to the log file

        # Remove any existing logging handlers to prevent duplicate logging after an auto-restart
        for handler in self.my_logger.handlers[:]:
            self.my_logger.removeHandler(handler)
            handler.close()

        self.Destroy()

    # ------------------------------------------------------------------------------------------------------------------
    # Force the pfeMAME application to restart.
    # This allows us to use newly changed variables or settings that need a restart to be performed.
    def on_force_restart(self) -> None:
        self.on_restart()

    # Restart straight away - e.g. the user answered Yes to restarting after applying File Paths
    def on_restart_now(self) -> None:
        self.on_restart()
        wx.CallAfter(self.on_close)

    @staticmethod
    def on_restart(_event=None) -> None:
        # Request a restart. The '--force_restart' (-x) flag is added to the
        # relaunch arguments at the os.execv call site so the relaunched
        # process knows it was auto-restarted.
        print('The restart requested flag has been set')
        global restart_requested
        restart_requested = True

    # ------------------------------------------------------------------------------------------------------------------
    # A game (or system program) has finished - add its play time to the play statistics
    def on_rom_played(self, key: str, seconds: float) -> None:
        if not self or self._app_closing or not self.play_stats.record(key, seconds):
            return
        try:
            self.play_stats.save()
        except OSError as e:
            self.my_logger.error(f'Unable to save play statistics: {e}')
        self.filter_cache.clear()
        if self.get_view_key() in ('Recent', 'MostPlayed'):
            self.on_filter_rom_list(preserve_selection=True, preserve_search=True)
        self._show_play_stats()

    def _show_play_stats(self) -> None:
        """Show the selected ROM's play statistics in the status bar."""
        results = self.get_virtual_list_row_info()
        if results.rom_file_name:
            text = self.play_stats.describe(play_stats.make_key(results.rom_file_name, results.system_file_name), _)
            self.statusbar_panel.set_status(text or _('Ready'))

    # ------------------------------------------------------------------------------------------------------------------
    # This function updates the number of runs info for the ROM just run
    def update_number_runs(self,
                           rom_file_name: str,
                           rom_name: str,
                           system_file_name_passed: str,
                           is_a_system: bool,
                           caller: str) -> None:

        results = self.get_virtual_list_row_info()

        if rom_file_name:
            # RunGame now reports the ROM it actually launched (the selection may have changed during the game)
            system_file_name = system_file_name_passed if is_a_system else ''
        else:
            rom_name = rom_name or results.rom_name
            rom_file_name = results.rom_file_name
            system_file_name = (
                results.system_file_name if caller == 'normal_view'
                else system_file_name_passed if is_a_system
                else ''
            )

        self.my_logger.info(_('Updating number of runs info for ROM {}').format(rom_file_name))  # Write to the log file

        # Increment the number of runs in the games list
        rom_file_name, index = self.get_rom_file_name(system_file_name, rom_name, rom_file_name)
        if index is None:
            return
        try:
            runs = int(self.mylist[index][index_number_runs])
        except (TypeError, ValueError):
            runs = 0
        self.mylist[index][index_number_runs] = str(runs + 1)

        self.on_filter_rom_list(read_from_cache=True, preserve_selection=True, preserve_search=True)  # Force an update of the ROM list to show the number of runs changed

        # Get all ROMs with runs from the ROMs list and store them in the runs.dat file
        try:
            functions.write_dat_lines(os.path.join(self.data_dir, 'runs.dat'),
                                      (f'{self._dat_key(line)}={line[index_number_runs]}\n' for line in self.mylist
                                       if line[index_number_runs] and line[index_number_runs] != '0'))
        except IOError:  # Issue writing so just ignore
            self.my_logger.error(_('ERROR: Unable to write to runs.dat file'))  # Write to the log file

        self.write_database()  # Write out the ROM database (mylist) to a cache file

    # ------------------------------------------------------------------------------------------------------------------

    def on_set_rating(self, _event) -> None:
        """
        This function is the event service for the add rating event
        It pops up a box requesting a rating between 1 and 5 for the
        currently selected ROM and then updates the ROM info
        and refreshes the display.
        :param _event:
        :return:
        """
        results = self.get_virtual_list_row_info()
        rom_file_name = results.rom_file_name
        rom_name = results.rom_name
        game_rating = results.game_rating
        system_file_name = results.system_file_name

        if not rom_file_name:
            return

        selected_rom_position = self.list.GetFocusedItem()  # Used to place the selected ROM to the top of the view

        def on_rating_selected(rating):
            result = str(rating)

            rom_file_name_new, index = self.get_rom_file_name(system_file_name, rom_name, rom_file_name)
            if index is None:
                return
            self.mylist[index][index_rating] = result

            self.on_filter_rom_list(read_from_cache=True, preserve_search=True)  # Force an update of the ROM list to show the ROM rating changed
            self.statusbar_panel.set_status(_('Romset {rom} rated as {stars} stars').format(rom=rom_file_name_new,
                                                                                 stars=result))
            self.Refresh()
            self.list.EnsureVisible(selected_rom_position)  # Recover the scroll position to this ROM

            # Now we read in the current ratings.dat file and strip out the selected ROM if it exists
            ratings_path = os.path.join(self.data_dir, 'ratings.dat')
            try:
                ratings = [line for line in functions.read_dat_lines(ratings_path)
                           if line.split('=')[0].strip() != rom_file_name_new]
            except IOError:
                ratings = []
                self.my_logger.warning(_('WARNING: Failed to read {}').format(ratings_path))

            ratings.append(f'{rom_file_name_new}={result}\n')

            try:
                functions.write_dat_lines(ratings_path, ratings)
            except IOError:
                self.my_logger.error(_('ERROR: Unable to write to {}').format(ratings_path))

            message = _('Romset {} rating updated').format(rom_file_name_new)
            self.my_logger.info(message)
            self.messages_append(f'{message}\n', True)
            self.write_database()  # Write out the ROM database (mylist) to a cache file

        # Ask user for new rating
        popup = starRating.StarRatingPopup(self, initial_rating=int(game_rating), callback=on_rating_selected)
        mouse_pos = wx.GetMousePosition()
        popup.Position(mouse_pos, (0, 0))
        popup.Popup()

    # ------------------------------------------------------------------------------------------------------------------
    # This function takes the currently selected ROM and adds it to the favorites file
    # A check is performed before adding to the favorites file to ensure it doesn't already
    # exist (to prevent duplicates).
    # It also checks to see if it is in the watchlist and if so it is removed.
    def on_add_favorite(self, _event=None) -> None:
        results = self.get_virtual_list_row_info()
        rom_file_name = results.rom_file_name
        rom_name = results.rom_name
        system_file_name = results.system_file_name

        if not rom_file_name:
            return

        self.my_logger.info(_('Adding ROM {} to favorites').format(rom_file_name))  # Write to the log file

        # For system programs this returns the full 'system-->name-->file' key that favorites.dat stores
        rom_file_name, index = self.get_rom_file_name(system_file_name, rom_name, rom_file_name)
        if index is None:
            return
        self.mylist[index][index_favorite] = '1'  # Flag this ROM as a favorite

        # Add the ROM to the favorites file (kept sorted, without duplicates)
        try:
            functions.add_dat_entry(os.path.join(self.data_dir, 'favorites.dat'), rom_file_name)
        except OSError:  # Issue writing so just ignore
            self.my_logger.error(_('ERROR: Unable to write to favorites.dat file'))  # Write to the log file


        # Check for the existence of the ROM file in the watchlist.  If so ask if you would like it removed.
        try:
            watchlist_path = os.path.join(self.data_dir, 'watchlist.dat')
            if functions.dat_file_contains(watchlist_path, rom_file_name):
                _dlg = wx.MessageDialog(self,
                                        _('The selected ROM currently exists in the watchlist.  '
                                          'Would you like it removed?'),
                                        _('File In Watchlist'),
                                        wx.YES_NO | wx.YES_DEFAULT | wx.ICON_QUESTION)
                if _dlg.ShowModal() == wx.ID_YES:
                    self.delete_watchlist(rom_file_name, rom_name, system_file_name, remove_from_mylist=False)
                _dlg.Destroy()

        except OSError:
            pass

        self.on_filter_rom_list(preserve_selection=True, preserve_search=True)  # Force an update of the ROM list to show the ROM now selected as a favorite

        msg = _('ROM set {} added to favorites').format(rom_file_name)
        self.statusbar_panel.set_status(msg)
        self.Refresh()
        self.my_logger.info(msg)
        self.messages_append(f'{msg}\n', True)

        self.write_database()  # Write out the ROM database (mylist) to a cache file

    # ------------------------------------------------------------------------------------------------------------------
    # This function takes the currently selected ROM and adds it to the watchlist
    def on_add_watchlist(self, _event) -> None:
        results = self.get_virtual_list_row_info()
        rom_file_name = results.rom_file_name
        rom_name = results.rom_name
        system_file_name = results.system_file_name

        if not rom_file_name:
            return

        rom_file_name, index = self.get_rom_file_name(system_file_name, rom_name, rom_file_name)
        if index is None:
            return
        if self.mylist[index][index_favorite] == '1':
            wx.MessageBox(_('You cannot add a favourite file to the watchlist'),
                          _('ERROR - Already Favourite'))
            return

        self.my_logger.info(_('Adding ROM {} to watchlist').format(rom_file_name))  # Write to the log file

        # (rom_file_name/index were looked up above - a second lookup with the already-suffixed system-program
        # name found no row and raised StopIteration)
        self.mylist[index][index_favorite] = '2'  # Flag this ROM as a watchlist

        # Read from the watchlist file and store in a temporary list
        watchlist_path = os.path.join(self.data_dir, 'watchlist.dat')
        try:
            existing_watchlist = set(line.strip() for line in functions.read_dat_lines(watchlist_path) if line.strip())
        except IOError:  # The watchlist file doesn't currently exist so no problem, just ignore the error
            self.my_logger.warning(_('WARNING: Unable to read from watchlist.dat file'))  # Write to the log file
            existing_watchlist = set()

        # Now add the new watchlist ROM to the list
        existing_watchlist.add(rom_file_name)

        # Write out the new watchlist file
        try:
            functions.write_dat_lines(watchlist_path, (f'{line}\n' for line in sorted(existing_watchlist)))
        except IOError:  # Issue writing so just ignore
            self.my_logger.error(_('ERROR: Unable to write to watchlist.dat file'))  # Write to the log file

        self.on_filter_rom_list(preserve_selection=True, preserve_search=True)  # Force an update of the ROM list to show the ROM now selected as a watchlist

        msg = _('ROM set {} added to watchlist').format(rom_file_name)
        self.statusbar_panel.set_status(msg)
        self.Refresh()
        self.my_logger.info(msg)
        self.messages_append(f'{msg}\n', True)

        self.write_database()  # Write out the ROM database (mylist) to a cache file

    # ------------------------------------------------------------------------------------------------------------------
    # True if the favorites.dat / watchlist.dat style file contains the given entry
    def _dat_file_contains(self, file_name: str, entry: str) -> bool:
        return functions.dat_file_contains(os.path.join(self.data_dir, file_name), entry)

    # ------------------------------------------------------------------------------------------------------------------
    # Tile View has changed favorites (it updates the shared mylist rows and favorites.dat itself).  Refresh the ROM
    # list and save the ROMs database once, when Tile View closes.
    def on_tileview_favorites_changed(self) -> None:
        self.filter_cache.clear()  # Cached filtered lists (e.g. the Favorites view) may now be out of date
        self.on_filter_rom_list(preserve_selection=True, preserve_search=True)
        self.write_database()

    # ------------------------------------------------------------------------------------------------------------------
    # Get the rom_file_name and index for the match required
    def get_rom_file_name(self, system_file_name: str, rom_name: str, rom_file_name: str) -> tuple[str, int | None]:
        """
        Find a ROM's mylist row.  Returns (the key favorites.dat etc. store it under, mylist index), or
        (key, None) if it is not in the list.  The key is the ROM file name, or 'system-->name-->program' for
        system programs.
        """
        if not system_file_name:
            # The MAME short name is unique; the full name was used before and failed when it wasn't known (a ROM
            # started with -r on the command line)
            if rom_file_name:
                index = next((i for i, x in enumerate(self.mylist) if x[index_rom_file_name] == rom_file_name
                              and not x[index_system_program_file_name]), None)
            else:
                index = next((i for i, x in enumerate(self.mylist) if x[index_rom_name] == rom_name), None)
        else:
            index = next((i for i, x in enumerate(self.mylist) if (x[index_system_program_file_name] == system_file_name
                                                                   and x[index_rom_file_name] == rom_file_name)),
                         None)
            if not rom_name and index is not None:
                rom_name = self.mylist[index][index_rom_name]
            rom_file_name = f'{rom_file_name}-->{rom_name}-->{system_file_name}'
        if index is None:
            self.my_logger.warning(f'ROM {rom_file_name} is not in the ROMs list')
        return rom_file_name, index

    # ------------------------------------------------------------------------------------------------------------------
    # Reload all dat file data
    def load_all_dat_files(self):
        for dat_file in ['favorites.dat', 'ratings.dat', 'runs.dat', 'watchlist.dat']:
            self.get_dat_file_data(dat_file)

    # ------------------------------------------------------------------------------------------------------------------
    # Get the requested DAT file data
    #
    # This is used for runs, favorites, and ratings.DAT files when refreshing the database and you need to read the
    # values out again to update in mylist
    def get_dat_file_data(self, file_to_update: str) -> None:
        file_type = os.path.splitext(file_to_update)[0]  # e.g., 'favorites', 'ratings', 'runs'
        self.my_logger.info(_('Reading ROM {} flags').format(file_type))
        self.statusbar_panel.set_status(_('Reading ROM {} flags.  Please Wait.........').format(file_type))
        self.Refresh()

        if not self.mylist:
            return

        # Setup behavior based on file type
        # If reset_value is not NONE, then if no match is found, the walue is set to this value
        config = {
            'favorites': {
                'index': index_favorite,
                'reset_value': '0',
                'set_func': lambda row, value: value,
                'parse_line': lambda line: (line.strip(), '1'),
            },
            'watchlist': {
                'index': index_favorite,
                'reset_value': None,
                # Favourites and the watchlist are mutually exclusive in the ROM list.  If a ROM is in both files
                # (the user kept it on the watchlist when making it a favourite), it shows as a favourite.
                'set_func': lambda row, value: row[index_favorite] if row[index_favorite] == '1' else value,
                'parse_line': lambda line: (line.strip(), '2'),
            },
            'ratings': {
                'index': index_rating,
                'reset_value': None,
                'set_func': lambda row, value: value,
                'parse_line': lambda line: line.strip().split('=', 1) if '=' in line else (None, None),
            },
            'runs': {
                'index': index_number_runs,
                'reset_value': None,
                'set_func': lambda row, value: value,
                'parse_line': lambda line: line.strip().split('=', 1) if '=' in line else (None, None),
            }
        }

        if file_type not in config:
            self.my_logger.warning(_('Unsupported data file: {}').format(file_to_update))
            return

        conf = config[file_type]
        error_count = 0

        # Reset favorite flags if needed
        if conf['reset_value'] is not None:
            for row in self.mylist:
                row[conf['index']] = conf['reset_value']

        # Look-ups built once, rather than searching the whole list for every line of the file
        arcade_rows = {}            # ROM file name -> index (rows that aren't system programs)
        program_rows = {}           # System program file name -> [indexes] (several systems can share a file name)
        file_name_rows = {}         # ROM file name -> first index (any row)
        for i, row in enumerate(self.mylist):
            program = row[index_system_program_file_name]
            if program:
                program_rows.setdefault(program, []).append(i)
            else:
                arcade_rows.setdefault(row[index_rom_file_name], i)
            file_name_rows.setdefault(row[index_rom_file_name], i)

        try:
            for line in functions.read_dat_lines(os.path.join(self.data_dir, file_to_update)):
                rom_file_name, value = conf['parse_line'](line)
                if not rom_file_name:
                    continue

                # Handle system ROM formats
                rom_parts = rom_file_name.split('-->')
                if len(rom_parts) > 2:
                    index = self._match_system_program(program_rows, rom_parts)
                elif len(rom_parts) > 1:
                    index = file_name_rows.get(rom_parts[1])
                else:
                    index = arcade_rows.get(rom_file_name, file_name_rows.get(rom_file_name))

                if index is not None:
                    self.mylist[index][conf['index']] = conf['set_func'](self.mylist[index], value)
                else:
                    error_count += 1
                    self.my_logger.warning(
                        _('A file name called {rom} in the {file} file does not exist in the '
                          'MAME ROM list').format(rom=rom_file_name, file=file_to_update))

        except IOError:
            self.my_logger.warning(_('WARNING: {} file does not exist').format(file_to_update))

        if error_count > 0:
            self.messages_append(_('{count} error(s) found in {file} file.  See logfile.log for '
                                   'more information.\n').format(count=error_count, file=file_to_update), True)

        self.my_logger.info(_('Completed reading ROM {} flags').format(file_type))

    # ------------------------------------------------------------------------------------------------------------------
    def _match_system_program(self, program_rows: dict, rom_parts: list[str]) -> int | None:
        """
        The mylist row for a 'system-->name-->program' data file entry.  The program file name alone is not enough -
        the same file name can be in more than one system's software list - so the system ROM has to match too.
        favorites.dat / watchlist.dat / ratings.dat store 'system ROM-->system name-->program'; runs.dat used to store
        'system name-->system ROM-->program', so either of the first two parts may be the system ROM.
        """
        candidates = program_rows.get(rom_parts[2], [])
        for i in candidates:
            if self.mylist[i][index_rom_file_name] in (rom_parts[0], rom_parts[1]):
                return i
        return candidates[0] if candidates else None

    @staticmethod
    def _dat_key(row: list) -> str:
        """The key a mylist row is stored under in the data files: the ROM file name, or for a system program
        'system ROM-->system name-->program' (the same as favorites.dat)."""
        if not row[index_system_program_file_name]:
            return row[index_rom_file_name]
        return '-->'.join([row[index_rom_file_name], row[index_rom_name], row[index_system_program_file_name]])

    # ------------------------------------------------------------------------------------------------------------------
    # This function reads the categories.dat file and stores it in a list
    def load_categories(self) -> list[str]:
        categories, unused, message = functions.load_categories_file(self.data_dir)
        self.my_logger.info(message)
        return categories

    #------------------------------------------------------------------------------------------------------------------
    def populate_list(self, filtercolumn: int, filtervalue: str, read_from_cache: bool) -> int:
        """
        This function creates the filtered ROM list for display.
        To use the filter, pass the mylist column and value you wish to filter for.
        To just show all, pass a -1 as the column and empty string as value
        :param filtercolumn:
        :param filtervalue:
        :param read_from_cache:
        :return:
        """

        if read_from_cache:
            filtercolumn = self.filtercolumn_cache
            filtervalue = self.filtervalue_cache

        self.filtercolumn_cache = filtercolumn
        self.filtervalue_cache = filtervalue

        # Include categories in cache key to ensure correctness when categories change
        key = (filtercolumn, filtervalue.lower(), tuple(sorted(self.categories)))
        if read_from_cache and key in self.filter_cache:
            mylist_filtered = self.filter_cache[key]
        else:
            # We go here when selecting a view filter with no cache
            categories_local = set(self.categories)
            filter_value_lower = filtervalue.lower()
            mylist_filtered = []
            # The search box understands field:value terms (see search.py)
            query = search.parse_query(filtervalue) if filtercolumn == 1 else None
            # Recently Played / Most Played are ordered by the play statistics rather than filtered on a column
            play_order = None
            if filtercolumn in (views.RECENT, views.MOST_PLAYED):
                keys = self.play_stats.recent() if filtercolumn == views.RECENT else self.play_stats.most_played()
                play_order = {key: position for position, key in enumerate(keys)}

            for line in self.mylist:
                category = line[index_category]
                if category not in categories_local:
                    continue

                if filtercolumn == 1:
                    if search.matches(line, query):
                        mylist_filtered.append(line)

                elif filtercolumn == -1:
                    mylist_filtered.append(line)

                elif play_order is not None:
                    if play_stats.row_key(line) in play_order:
                        mylist_filtered.append(line)

                else:
                    if filter_value_lower in line[filtercolumn].lower():
                        mylist_filtered.append(line)

            if play_order is not None:
                mylist_filtered.sort(key=lambda line: play_order[play_stats.row_key(line)])

            # Cache the views (there are only a few) but not search box results - every search typed was kept
            # before, so a long session could hold hundreds of copies of the list
            if filtercolumn != 1:
                if len(self.filter_cache) >= FILTER_CACHE_SIZE:
                    self.filter_cache.clear()
                self.filter_cache[key] = mylist_filtered  # cache result

        self.mylist_filtered = mylist_filtered
        self.list.set_data(mylist_filtered)
        return len(mylist_filtered)

    # ------------------------------------------------------------------------------------------------------------------
    # This function processes the ROM filter combo box selection event
    def on_filter_rom_list(self, event=None, read_from_cache=False, preserve_selection=False,
                           preserve_search=False) -> None:
        if self.blockFilter:
            return

        # Capture current selection before rebuilding so we can restore it without any intermediate scroll
        preserved_row = self.list.GetFocusedItem() if preserve_selection else -1

        # When this is an internal refresh after an action (favorite, watchlist, rating, run, etc.) and the
        # user currently has an active search, re-apply the search filter rather than reverting to the combo
        # box filter and wiping out the search box.  preserve_search is left False for the combo box dropdown
        # event handler so that explicitly choosing a view still clears the search as intended.
        search_text = self.controlSearch.GetValue()
        use_search = preserve_search and bool(search_text.strip())

        if use_search:
            filtercolumn, filtervalue = 1, search_text.lower()
        else:
            # read_from_cache = (event == 1)
            filtercolumn, filtervalue = VIEW_FILTERS[self.get_view_key()]

        number_roms_in_filtered_list = self.populate_list(
            filtercolumn=filtercolumn,
            filtervalue=filtervalue,
            read_from_cache=read_from_cache
        )

        self.update_rom_numbers(number_roms_in_filtered_list)

        # Reset search box if needed (skip when we are preserving an active search)
        if not use_search and getattr(self, 'clearSearch', False):
            self.controlSearch.Enable(False)
            self.clear_event_override = True
            self.controlSearch.SetValue('')
            self.controlSearch.Enable()

        self.clearSearch = True
        self.clear_event_override = False

        if preserve_selection and preserved_row >= 0 and self.list.GetItemCount() > 0:
            self.list.Select(preserved_row)
            self.list.EnsureVisible(preserved_row)
        elif event not in (1, -1) and self.list.GetItemCount() > 0:
            # Focus the first item in the list if not called from filter dropdown (event == 1 or -1)
            self.list.SetFocus()
            self.list.Select(0)
            self.list.EnsureVisible(0)

    # ------------------------------------------------------------------------------------------------------------------
    # This function stops the video player and displays the right caption depending upon if there was a video to
    # play, or not.
    def video_stop(self) -> None:
        if not self.video_disable:
            self.video_playback_timer.Stop()
            # Cancel any deferred autoload play still queued from the countdown
            # timer, otherwise it can fire after we've stopped and restart the
            # video (e.g. once we've already switched to tile view).
            if self._pending_play is not None and self._pending_play.IsRunning():
                self._pending_play.Stop()
            self.video_player.stop(caption=False)  # Stop the ROM video player (the caption is set below)
            self.timerSeconds = VIDEO_TIMER_DELAY
            text = _('Video Available - Click to Play') if self.video_to_play else _('No Video Available')
            self.videoLoadCaption.SetLabel(text)

    # ------------------------------------------------------------------------------------------------------------------
    # This caches the videos folder to make looking up a video file match a lot faster for people using network shares
    # of slow HDDs
    def _get_video_folder_cache(self) -> dict:
        """Build (or return cached) dict mapping ROM name stems to video file paths."""
        if self.foldersVideo == self._video_folder_cached_path:
            return self._video_folder_cache

        cache = {}
        try:
            for entry in os.scandir(self.foldersVideo):
                if entry.is_file():
                    stem = os.path.splitext(entry.name)[0]
                    cache[stem] = entry.path
        except (FileNotFoundError, PermissionError):
            pass

        self._video_folder_cache = cache
        self._video_folder_cached_path = self.foldersVideo
        return cache

    # ------------------------------------------------------------------------------------------------------------------
    # This function processes the search box event trigger to allow for dynamic searching.
    # A 200ms debounce is applied so that rapid keystrokes do not each trigger a full O(n) list scan —
    # only the final keystroke in a burst fires the search.
    def on_search_dynamic(self, event) -> None:

        # Don't allow the event to be processed if we have suppressed the event by setting the following flag.  This is
        # done to prevent the selection of the views drop down box causing the search control to be cleared and thus
        # triggering the search event when then resets the view drop down box (a cyclic issue).
        if not self.clear_event_override:
            if self._search_timer:
                self._search_timer.Stop()
            self._search_timer = wx.CallLater(200, self._execute_search)
            event.Skip(True)

    # ------------------------------------------------------------------------------------------------------------------
    def _execute_search(self) -> None:
        self.video_stop()
        self.inactivity_timer_start()
        search_text = self.controlSearch.GetValue().lower()
        self.blockFilter = True
        self.set_view_key('All')
        self.comboBoxFilter.Refresh()
        self.blockFilter = False

        number_roms_in_filtered_list = self.populate_list(filtercolumn=1,
                                                          filtervalue=search_text,
                                                          read_from_cache=False)
        self.update_rom_numbers(number_roms_in_filtered_list)

        if number_roms_in_filtered_list > 0:
            self.list.EnsureVisible(0)

    # ------------------------------------------------------------------------------------------------------------------
    # Update the ROM quantity counters in the status bar
    def update_rom_numbers(self, number_roms_in_filtered_list: int) -> None:
        self.statusbar_panel.set_quantities(f'{str(len(self.mylist))} ',
                                            f'{str(self.availableRoms)} ',
                                            f'{str(number_roms_in_filtered_list)}')

    # ------------------------------------------------------------------------------------------------------------------
    # This function updates the ROM image placeholder
    # Images are scaled to fit 224 x 256 pixels (x,y) times image_scale, keeping their shape
    def display_rom_image(self, file_name: str) -> None:
        with wx.LogNull():  # Suppress image loading errors
            bitmap = None
            if file_name and os.path.isfile(file_name):
                try:
                    bitmap = _scaled_rom_image(file_name, os.path.getmtime(file_name))
                except Exception as e:
                    msg = _('The snapshot image {} could not be loaded.  It may be corrupted.').format(file_name)
                    self.my_logger.error(f'{msg} ({e})')
                    self.messages_append(_('ERROR:  ') + f'{msg}\n')
                    self.enable_alert_timer()
            if bitmap is None or not bitmap.IsOk():
                # The image based on file_name probably doesn't exist so display the default image
                try:
                    bitmap = _scaled_rom_image(self.default_image_file_name, 0)
                except Exception:
                    bitmap = wx.Bitmap(image_size_x, image_size_y)

            # Draw the magnifier on a copy - the bitmap is cached, and drawing on it every time the ROM was selected
            # made the magnifier's soft edges darker each time
            x, y = bitmap.GetSize()
            img = bitmap.GetSubBitmap(wx.Rect(0, 0, x, y))
            dc = wx.MemoryDC(img)
            dc.DrawBitmap(self.overlay_image, x - self.overlay_image_size[0], y - self.overlay_image_size[1], True)
            dc.SelectObject(wx.NullBitmap)
            del dc

            self.image_panel.image.SetBitmap(img)
            self.image_panel.Layout()

            # Store filename for popup viewer
            self.image_panel.set_image_file_name(file_name)

    # ------------------------------------------------------------------------------------------------------------------
    # Switch to the File Paths tab in the main notebook
    def on_file_paths(self, _event) -> None:
        self._select_notebook_page(self.filepaths_panel)

    # ------------------------------------------------------------------------------------------------------------------
    # Helper function for the on_verify_roms
    def _run_mame_command(self, args: list[str], timeout: float | None = None) -> tuple[str, str]:
        """Run MAME with args and return (stdout, stderr).  With a timeout, a MAME that runs longer is stopped."""
        cmd = [self.path_mame_exe] + args
        try:
            p = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
                cwd=functions.mame_working_dir(self.path_mame_exe),
                timeout=timeout,
                **functions.NO_CONSOLE
            )
        except subprocess.TimeoutExpired:
            self.my_logger.warning(f'MAME {" ".join(args)} did not finish within {timeout} seconds')
            return '', f'MAME did not finish within {timeout} seconds'
        out = p.stdout.strip()
        err = p.stderr.strip()

        return out, err

    # ------------------------------------------------------------------------------------------------------------------
    # Execute the mame command '-verifyroms' and pass the output to the message box.  Then do the same using
    # -verifysamples but only pass the output if there are supposed to be samples.
    def on_verify_roms(self, _event) -> None:
        results = self.get_virtual_list_row_info()
        rom_file_name = results.rom_file_name

        if rom_file_name == '':
            return

        # Verify the ROMs
        self.messages_append(_('Verifying ROM image for {}\n').format(rom_file_name))
        out, err = self._run_mame_command(['-rompath', ';'.join(self.rom_folders), '-verifyroms', rom_file_name])

        for message in (out, err):
            if message:
                self.messages_append(message)

        self.controlMessages.AppendText(MESSAGE_DELIMITER)

        # Verify the samples
        self.messages_append(_('Verifying sample files for {}\n').format(rom_file_name))
        out, err = self._run_mame_command(['-verifysamples', rom_file_name])

        # Determine what message to show
        if (not out or out.lower() == 'not required!') and not err:
            out = "No Sample Files Required\n"
        elif err:
            out = f"{out}\n{err}\n" if out else err + '\n'

        self.messages_append(out, True)

        if not self.folders_samples or self.folders_samples == '.':
            self.messages_append(_('WARNING:  The MAME samples folder has not been set in filepaths\n'))

    # ------------------------------------------------------------------------------------------------------------------
    # This function executes the MAME command -listmedia for the selected rom.
    # It is intended to be used with systems (e.g. ZX Spectrum) where the system is capable of running a number
    # of types of program with different media extensions (e.g. .tap, .bin)
    def on_view_media_types(self, _event) -> None:
        rom_file_name = self.get_virtual_list_row_info().rom_file_name

        if rom_file_name:
            extensions = functions.get_system_media_types(self.path_mame_exe, rom_file_name)

            # Display the result in the messages window
            self.messages_append(_('Media types associated with ROM {}:\n').format(rom_file_name))
            self.controlMessages.AppendText(' '.join(extensions) + ' ')
            self.controlMessages.AppendText('\n')
            self.controlMessages.AppendText(MESSAGE_DELIMITER)

    # ------------------------------------------------------------------------------------------------------------------
    # Get MAME rom information
    def on_rom_info(self, _event) -> None:
        results = self.get_virtual_list_row_info()
        rom_file_name = results.rom_file_name
        rom_name = results.rom_name

        if rom_file_name:
            rominfo.WindowMessage(rom_file_name=rom_file_name, rom_name=rom_name, path_executable=self.path_mame_exe)

    # ------------------------------------------------------------------------------------------------------------------
    # Get ROM information from the history or mameinfo files.
    def get_info_text(self, info_type: str, rom_file_name: str, system_file_name: str, short_name: str) -> str:
        data_source = self.history_data if info_type == 'history' else self.mame_info_data
        return functions.get_rom_info(
            data_source,
            self.mylist,
            rom_file_name,
            system_file_name,
            short_name,
            index_system_folder_name,
            info_type
        )

    # ------------------------------------------------------------------------------------------------------------------
    # This function passes the application version number to the 'about' dialog box
    # and shows the 'about box'
    @staticmethod
    def on_about_box_display(_event) -> None:
        aboutbox.OnAboutBox(version=__version__, copy_right=__copyright__)

    # ------------------------------------------------------------------------------------------------------------------
    # This function displays the MAME in-game controls window
    def on_controls_box_display(self, _event) -> None:
        scrolledwindow.DisplayScrolledDialog(title=_('MAME Controls'),
                                             file_path=os.path.join(self.path_to_me, 'controls.txt'),
                                             scroll=False,
                                             size=wx.Size(500, 600))

    # ------------------------------------------------------------------------------------------------------------------
    # This function displays the pfeMAME logfile in a window
    @staticmethod
    def on_logfile_display(_event) -> None:
        scrolledwindow.DisplayScrolledDialog(title=_('pfeMAME Log File'),
                                               file_path=os.path.join(functions.data_dir(), "logfile.log"),
                                               scroll=True,
                                               size=wx.Size(800, 500))

    # ------------------------------------------------------------------------------------------------------------------
    # This function displays the pfeMAME changelog file in a window
    def on_changelog_display(self, _event) -> None:
        # Bullet glyphs used for each list-indent level (cycles if deeper than the list).
        bullet_glyphs = ['•', '◦', '▪', '‣', '·']

        def format_paragraph(para):
            # Detect a Word list paragraph and its indent level from the numbering properties.
            pPr = para._p.pPr
            if pPr is not None and pPr.numPr is not None:
                ilvl = 0
                if pPr.numPr.ilvl is not None and pPr.numPr.ilvl.val is not None:
                    ilvl = pPr.numPr.ilvl.val
                indent = '    ' * ilvl
                bullet = bullet_glyphs[ilvl % len(bullet_glyphs)]
                return f'{indent}{bullet} {para.text}'
            return para.text

        try:
            doc = docx.Document(os.path.join(self.path_to_me, 'changelog.docx'))  # Creating word reader object.
            full_text = [format_paragraph(para) for para in doc.paragraphs]
            data = '\n'.join(full_text)

            scrolledwindow.DisplayScrolledDialog(title=_('pfeMAME Changelog File'),
                                                 scroll=False,
                                                 size=wx.Size(800, 500),
                                                 text_to_display=data)
        except docx.opc.exceptions.PackageNotFoundError:
            wx.MessageBox(
                _('Unable to find the changelog.docx file.  '
                  'Please check that it exists in the pfeMAME folder.'),
                _('ERROR'), wx.OK | wx.ICON_ERROR)

    # ------------------------------------------------------------------------------------------------------------------
    # This function displays the pfeMAME manual
    def on_manual_display(self, _event) -> None:
        manual_path = os.path.join(self.path_to_me, 'pfeMAME_Manual.pdf')

        if not os.path.isfile(manual_path):
            wx.MessageBox(
                _('Unable to find the pfeMAME_Manual.pdf file!  '
                  'Please check that it exists in the pfeMAME folder.'),
                _('ERROR'), wx.OK | wx.ICON_ERROR)
            return

        try:
            if self.system == 'mac':
                subprocess.run(['open', manual_path], check=False)
            elif os.name == 'nt':
                os.startfile(manual_path)
            elif os.name == 'posix':
                # Use webbrowser fallback to xdg-open, gio, etc.
                if not webbrowser.open(f'file://{manual_path}'):
                    raise RuntimeError('webbrowser.open failed')
        except Exception:
            wx.MessageBox(
                _('Sorry, but I was unable to open the pfeMAME manual. '
                  'Please open it manually: {}').format(manual_path),
                _('ERROR'), wx.OK | wx.ICON_ERROR)

    # ------------------------------------------------------------------------------------------------------------------
    def on_check_artwork(self, _event):
        """
        Open the MAME artwork file fixer window

        :param _event:
        :return:
        """
        minimum_mame_version = fix_artwork_file.MINIMUM_MAME_VERSION
        if not re.fullmatch(r'\d+(\.\d+)*', self.mame_version or ''):
            wx.MessageBox(_('pfeMAME could not find out which version of MAME you have, so the artwork files cannot '
                            'be checked.  Please check the path to the MAME executable in the File Paths window.'),
                          _('Unknown MAME Version'), wx.OK | wx.ICON_ERROR)
            return
        if functions.compare_version(self.mame_version, minimum_mame_version) < 0:
            wx.MessageBox(_('The artwork files can only be updated for MAME {minimum} or newer.  You have MAME '
                            '{version}.').format(minimum=minimum_mame_version, version=self.mame_version),
                          _('Incorrect Mame Version'), wx.OK | wx.ICON_ERROR)
            return

        art_path = iniFile.get_from_mameini('artpath', self.path_to_mame_ini_file)
        art_folders = functions.split_mame_paths(art_path, self.path_mame_exe)
        if not any(os.path.isdir(folder) for folder in art_folders):
            functions.show_error_dialog(self, _('No artwork folder was found.  Please set the Artwork folder in the '
                                                'File Paths window.'), _('ERROR'))
            return
        fix_artwork_file.LayoutFixerFrame.open(art_folders)

    # ------------------------------------------------------------------------------------------------------------------

    def on_check_all(self, _event) -> None:
        """
        This function opens the checkall window to allow all 'existing'
        ROMs to be checked for correctness
        :param _event:
        :return:
        """

        rom_file_name = self.get_virtual_list_row_info().rom_file_name

        if not rom_file_name:
            return

        if not any(os.path.isdir(folder) for folder in self.rom_folders):
            msg = _('Please select a valid ROMs folder and path to the MAME executable from the File Paths window.')
            title = _('ERROR')
            functions.show_error_dialog(self, msg, title)
            return

        checkall.CheckAll.open(path_executable=self.path_mame_exe, folders_roms=';'.join(self.rom_folders),
                               my_logger=self.my_logger)

    # ------------------------------------------------------------------------------------------------------------------
    # Run the selected ROM and record the inputs for playback later
    def handle_input_record_or_playback(self, mode: str) -> None:
        """
        Handles both input recording and playback operations.

        :param mode: 'record' or 'playback'
        """
        if not self.folderInput:
            wx.MessageBox(
                _('Please set a valid Inputs folder under the File Paths'),
                _('ERROR'), wx.OK | wx.ICON_ERROR)
            return

        results = self.get_virtual_list_row_info()
        rom_file_name = results.rom_file_name

        if not rom_file_name:
            return

        is_record = mode == 'record'
        wildcard = 'INP Files (*.inp)|*.inp'
        default_filename = f'{rom_file_name}.inp'

        dlg = wx.FileDialog(
            self,
            message=(_('Create the file for recording inputs for {}') if is_record else
                     _('Select the file to play back inputs for {}')).format(rom_file_name),
            defaultDir=self.folderInput,
            defaultFile=default_filename,
            wildcard=wildcard,
            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT if is_record else wx.FD_OPEN
        )

        if dlg.ShowModal() == wx.ID_OK:
            # MAME looks for the file in its Inputs folder, so a file there is passed by name.  A file somewhere
            # else is passed with its full path - only the name was passed before, so MAME couldn't find it.
            file_path = dlg.GetPath()
            if os.path.normcase(os.path.abspath(os.path.dirname(file_path))) == \
                    os.path.normcase(os.path.abspath(self.folderInput)):
                file_path = os.path.basename(file_path)
            msg = (_('Recording playback for the rom using {}') if is_record else
                   _('Playing the rom using recorded input from {}')).format(file_path)
            self.my_logger.info(msg)
            self.messages_append(f'{msg}\n')
            self.on_double_click(
                input_playback_or_record='-record' if is_record else '-playback',
                pb_r_filename=file_path
            )

        dlg.Destroy()

    def on_input_record(self, _event) -> None:
        self.handle_input_record_or_playback('record')

    def on_input_playback(self, _event) -> None:
        self.handle_input_record_or_playback('playback')

    # ------------------------------------------------------------------------------------------------------------------
    def handle_backup_or_restore(self, mode: str) -> None:
        """
        Handles both backup and restore operations.

        A backup is a single time-stamped zip file (pfeMAME_backup_YYYYMMDD_HHMMSS.zip) holding the files in
        BACKUP_FILES plus a manifest.json:

        categories.dat
        favorites.dat
        watchlist.dat
        ratings.dat
        runs.dat
        pfemame.ini
        non_mame_emulators.xml
        rom_sources.dat (stored online-ROM-source credentials - optional, the user is asked)

        Restore accepts one of those zip files, or (for backups made by older versions) any of the loose files in
        a legacy backup folder.  The current files are saved to backups/pre_restore_<date>.zip first, and pfeMAME
        restarts afterwards so that everything is re-read from the restored files.

        :param mode: 'backup' or 'restore'
        """
        if mode == 'backup':
            self.backup_user_settings()
        else:
            self.restore_user_settings()

    # ------------------------------------------------------------------------------------------------------------------
    def _write_backup_zip(self, target: str, files: list[str]) -> list[str]:
        """Write the given BACKUP_FILES that exist into a backup zip with a manifest.  Returns the files included."""
        return backup.write_backup_zip(self.data_dir, target, files, __version__)

    # ------------------------------------------------------------------------------------------------------------------
    def backup_user_settings(self) -> None:
        with wx.DirDialog(self,
                          message=_('Choose a directory for backup:'),
                          defaultPath=self.path_to_me,
                          style=wx.DD_DEFAULT_STYLE | wx.DD_NEW_DIR_BUTTON) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                functions.show_information_dialog(self, _('Backup process canceled'), _('INFORMATION'))
                return
            folder = dlg.GetPath()

        files = list(BACKUP_FILES)

        # The stored ROM-site logins are only obfuscated, not encrypted, so let the user decide if they go into
        # a backup file that may be copied elsewhere.
        if os.path.isfile(os.path.join(self.data_dir, rom_credentials.STORE_NAME)):
            with wx.MessageDialog(self,
                                  _('Include your saved online ROM source logins ({}) in the backup?\n\n'
                                    'They are stored obfuscated, not encrypted, so anyone with the backup file and '
                                    'pfeMAME could recover them.').format(rom_credentials.STORE_NAME),
                                  _('Backup ROM Source Logins?'),
                                  wx.YES_NO | wx.CANCEL | wx.NO_DEFAULT | wx.ICON_QUESTION) as ask:
                answer = ask.ShowModal()
            if answer == wx.ID_CANCEL:
                functions.show_information_dialog(self, _('Backup process canceled'), _('INFORMATION'))
                return
            if answer == wx.ID_NO:
                files.remove(rom_credentials.STORE_NAME)

        target = os.path.join(folder, backup.backup_file_name())
        try:
            included = self._write_backup_zip(target, files)
        except (OSError, zipfile.BadZipFile) as e:
            self.my_logger.error(f'Backup failed: {e}')
            functions.show_error_dialog(self,
                                        _('Unable to copy the application files to the selected folder.  '
                                          'Check the folder permissions.'),
                                        _('ERROR'))
            return

        summary_msg = _('Application preferences and DAT files backed up to {path}').format(path=target)
        self.messages_append(f'{summary_msg}.\n' + ''.join(f'{name}\n' for name in included), True)
        self.my_logger.info(summary_msg)

    # ------------------------------------------------------------------------------------------------------------------
    def restore_user_settings(self) -> None:
        with wx.FileDialog(self,
                           message=_('Choose the backup to restore application preferences and DAT files from:'),
                           defaultDir=self.path_to_me,
                           wildcard=f"{_('pfeMAME backup')} (*.zip)|*.zip|"
                                    f"{_('Older backup folder')} (pfemame.ini)|pfemame.ini",
                           style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                functions.show_information_dialog(self, _('Restore process canceled'), _('INFORMATION'))
                return
            chosen = dlg.GetPath()

        # Work out what is available to restore.  Only names in BACKUP_FILES are ever written (this also stops a
        # crafted zip from writing outside the application folder).
        try:
            available = backup.restorable_files(chosen)
        except (OSError, zipfile.BadZipFile) as e:
            self.my_logger.error(f'Restore failed reading {chosen}: {e}')
            available = []

        if not available:
            functions.show_error_dialog(self,
                                        _('Unable to restore the preferences and DAT files from the selected folder.  '
                                          'Check this is the correct folder and check folder & file permissions.'),
                                        _('ERROR'))
            return

        with wx.MessageDialog(self,
                              _('The following files will be restored, replacing your current ones:\n\n{}\n\n'
                                'Your current files are saved to the backups folder first.  pfeMAME will then '
                                'restart to load the restored settings.\n\nContinue?').format('\n'.join(available)),
                              _('Restore'),
                              wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION) as confirm:
            if confirm.ShowModal() != wx.ID_YES:
                functions.show_information_dialog(self, _('Restore process canceled'), _('INFORMATION'))
                return

        try:
            # Keeps a safety copy of the current files first (backups/pre_restore_<date>.zip)
            safety_zip = backup.restore_files(chosen, available, self.data_dir, __version__)
        except (OSError, zipfile.BadZipFile) as e:
            self.my_logger.error(f'Restore failed: {e}')
            functions.show_error_dialog(self,
                                        _('Unable to restore the preferences and DAT files from the selected folder.  '
                                          'Check this is the correct folder and check folder & file permissions.'),
                                        _('ERROR'))
            return

        summary_msg = _('Application preferences and DAT files restored from {path}').format(path=chosen)
        self.my_logger.info(summary_msg)
        self.my_logger.info(f'Previous files saved to {safety_zip}')

        # Restart so every setting is re-read from the restored files.  Skip the normal save of window state on
        # close, otherwise it would overwrite parts of the pfemame.ini that was just restored.
        self._skip_ini_save_on_close = True
        global restart_requested
        restart_requested = True
        wx.CallAfter(self.on_close)

    def on_backup(self, _event) -> None:
        self.handle_backup_or_restore('backup')

    def on_restore(self, _event) -> None:
        self.handle_backup_or_restore('restore')

    # ------------------------------------------------------------------------------------------------------------------
    def messages_append(self,
                        message: str,
                        add_delimiter: bool = False,
                        include_datetime: bool = True) -> None:
        """
        Add a message to the messages control window and include a date time / delimiter

        :param message:               The message to display
        :param add_delimiter:         True / False (default False) to add a delimiter after the message
        :param include_datetime:     True / False (default True) to show the date time before the message

        :returns: None
        """
        parts = []
        if include_datetime:
            parts.append(f'{datetime.datetime.now():%Y-%m-%d %H:%M:%S} - > - ')
        parts.append(message)
        if add_delimiter:
            parts.append(MESSAGE_DELIMITER)

        s = ''.join(parts)

        # normalize any CR/LF variants to '\n' so splitting is consistent
        s = s.replace('\r\n', '\n').replace('\r', '\n')

        # One append for the whole message - the window redraws all of its text on each append
        lines = s.splitlines()
        if lines:
            self.controlMessages.AppendText('\n'.join(lines) + '\n')

    # ------------------------------------------------------------------------------------------------------------------
    # Reset the ROMs list column spacing back to default
    def on_reset_spacing(self, _event) -> None:
        for index, width in rom_grid.DEFAULT_COLUMN_WIDTHS:
            if index not in self._hidden_columns():
                self.list.SetColumnWidth(index, width)
        # Setting a width shows a hidden column again, so hide them again to be sure
        self._hide_hidden_columns()
        self.list.distribute_columns()
        self.Refresh()

    # ------------------------------------------------------------------------------------------------------------------
    def _hidden_columns(self) -> set[int]:
        """The ROMs list columns that are never shown: Path Media Name, and the system columns if systems are off."""
        hidden = {index_path_media_name}
        if self.prefSystemsSupport == 'False':
            hidden |= {index_system_program_file_name, index_system_short_name}
        return hidden

    def _hide_hidden_columns(self) -> None:
        for col in self._hidden_columns():
            self.list.SetColumnShown(col, False)

    def _restore_column_widths(self) -> None:
        """Set the ROMs list column widths saved in pfemame.ini when pfeMAME was last closed (see cleanup)."""
        hidden = self._hidden_columns()
        for col in range(self.list.GetColumnCount()):
            if col in hidden:
                continue
            try:
                width = int(iniFile.read_ini_file('system', f'column_width_{col}', default='0'))
            except (TypeError, ValueError):
                continue
            if width > 0:           # 0 = the column was hidden when the width was saved
                self.list.SetColumnWidth(col, width)
        self.list.distribute_columns()

    # ------------------------------------------------------------------------------------------------------------------
    # This function looks up the short name information for the selected system program in the XML file data.
    # It looks for file size and hash info and compares against the file found.  The comparison is shown as a pop-up.
    def on_xml_info(self, _event) -> None:
        results = self.get_virtual_list_row_info()
        rom_file_name = results.rom_file_name
        rom_name = results.rom_name
        system_file_name = results.system_file_name
        short_name = results.short_name

        if rom_file_name:
            xmlinfo.XMLInfo(rom_file_name=rom_file_name,
                            rom_name=rom_name,
                            system_file_name=system_file_name,
                            short_name=short_name,
                            path_executable=self.path_mame_exe,
                            folder_systems=self.folders_systems,
                            system_folder_name=results.system_folder_name)

    # ------------------------------------------------------------------------------------------------------------------
    # Copy the default.cfg file to a rom.map file (Where rom is the ROM name selected).  The file is stored
    # in the defined 'Mappings' folder (Which is set in FilePaths).  When the same ROM is later run again, pfeMAME
    # will check to see if the rom.map file exists, and if it does the default.cfg file will be overwritten with it
    # before the ROM is run.  This then allows for per-rom input mapping.
    def on_controller_mapping(self, _event) -> None:
        rom_file_name = self.get_virtual_list_row_info().rom_file_name

        if self.folder_mapping == '':
            msg = _('You have not set a Mapping folder under File Paths.  This is not a standard '
                    'MAME folder.  You need to create a folder (Suggest within your MAME folder) '
                    'called Mapping, and then in the File Paths window you need to set the Input '
                    'Mapping folder to the folder you have created.')
            title = _('Mapping Folder Not Defined')
            functions.show_information_dialog(self, msg, title)
            return
        if self.folder_config == '':
            msg = _('You have not set a Config Folder under file paths.  This needs to be defined so '
                    'that the default.cfg file can be copied.')
            title = _('Config Folder Not Defined')
            functions.show_information_dialog(self, msg, title)
            return
        if not os.path.isfile(os.path.join(self.folder_config, 'default.cfg')):
            msg = _('I am unable to find the default.cfg file within the Config folder set in '
                    'File Paths.  Check that the folder exists and that within it there is a valid '
                    'default.cfg file.  If the file is not present, maybe you have not run MAME for '
                    'the first time so run it and check again if the file exists.')
            title = _('ERROR - cant find default.cfg')
            functions.show_information_dialog(self, msg, title)
            return

        # All files and folders seem to be valid so lets proceed.
        # Copy the default.cfg file to the Mapping folder but naming it as rom.map
        try:
            shutil.copyfile(os.path.join(self.folder_config, 'default.cfg'),
                            os.path.join(self.folder_mapping, f'{rom_file_name}.map'))
            self.messages_append(_('Configuration file copied across for ROM file {}\n').format(rom_file_name), True)
            self.my_logger.info(_('Configuration file copied to Mapping folder for ROM file {}').format(rom_file_name))
        except PermissionError:
            msg = _('I am unable to write the {}.map file into the Mapping folder.  '
                    'Check the folder permissions and that the folder and files within are not '
                    'Read Only or write protected.  Under Linux check that everyone has permissions '
                    'to write to the file / folder.').format(rom_file_name)
            title = _('ERROR - cant write map file')
            functions.show_error_dialog(self, msg, title)
            return

    # ------------------------------------------------------------------------------------------------------------------
    # This function resets any information in a MAME INI file listed against the currently selected program.
    # No data in mame.ini is affected, just the ROM specific INI file
    def on_ini_file_reset(self, _event) -> None:
        results = self.get_virtual_list_row_info()
        rom_file_name = results.rom_file_name
        rom_name = results.rom_name
        system_file_name = results.system_file_name

        # Check that the INI folder is defined (inipath can list several folders - one of them has to exist)
        if not functions.ini_search_folders(self.folder_ini, self.path_mame_exe, self.path_to_mame_ini_file):
            self.messages_append(
                _('Unable to reset the INI file as the INI folder has not been correctly defined\n'), True)
            return

        # Check to see if it's a system program.  If it is, we need to delete the system program INI file.
        if system_file_name:
            ini_file = f'{rom_file_name}_system_{system_file_name}.ini'
            display_name = system_file_name
            is_system = True
        else:
            ini_file = f'{rom_file_name}.ini'
            display_name = rom_name
            is_system = False

        # The copy MAME would use (there could be one in each INI folder)
        ini_file_path = functions.find_rom_ini(ini_file, self.folder_ini, self.path_mame_exe,
                                               self.path_to_mame_ini_file)

        if ini_file_path and os.path.isfile(ini_file_path):
            try:
                os.remove(ini_file_path)
            except OSError as e:        # Read only, or in use - say so rather than failing part way
                msg = _('Unable to remove the INI file {path}: {error}\n').format(path=ini_file_path, error=e)
                self.messages_append(msg, True)
                return
            if is_system:
                msg = _('INI file for system program "{}" removed\n').format(display_name)
            else:
                msg = _('INI file for ROM "{}" removed\n').format(display_name)
        else:
            if is_system:
                msg = _('No INI file for system program "{}" exists so it can’t be removed\n').format(display_name)
            else:
                msg = _('No INI file for ROM "{}" exists so it can’t be removed\n').format(display_name)

        self.messages_append(msg, True)

    # ------------------------------------------------------------------------------------------------------------------
    # The right click has been captured on the ROM list control so call the popup context menu class
    def on_right_down(self, event) -> None:
        self.show_rom_menu(event.GetRow())

    def show_rom_menu(self, row: int) -> None:
        """Show the ROMs list right-click menu for a row (also opened from the keyboard - menu key / SHIFT-F10)."""
        functions.show_popup_menu(self, MyPopupMenu(self, row, self.alternate_emulation_engines))

    # ------------------------------------------------------------------------------------------------------------------
    # Sort the ROMs list control based on the column clicked
    def on_column_clicked(self, _event) -> None:
        column_selected = _event.GetCol()

        # Toggle direction if same column, otherwise reset to ascending
        if column_selected == self.sort_column:
            self.sort_ascending = not self.sort_ascending
        else:
            self.sort_column = column_selected
            self.sort_ascending = True

        # Sort the list.  Number columns sort as numbers, so 2 runs comes before 10 runs.
        if column_selected in rom_grid.NUMERIC_COLUMNS:
            def sort_key(row):
                try:
                    return int(row[column_selected]), ''
                except (TypeError, ValueError):
                    return -1, ''
        else:
            def sort_key(row):
                return row[column_selected].lower(), row[column_selected]
        self.mylist.sort(key=sort_key, reverse=not self.sort_ascending)

        # Update column header arrows
        for col in range(self.list.GetColumnCount()):
            current_text = self.list.GetColumnLabel(col).lstrip('▲▼ ')
            if col == self.sort_column:
                arrow = '▲' if self.sort_ascending else '▼'
                self.list.SetColumnLabel(col, f'{arrow} {current_text}')
            else:
                self.list.SetColumnLabel(col, current_text)

        # Clear the cache and show the sorted list again, keeping the current view or search (previously this
        # always showed every ROM while the view drop-down still showed e.g. Favorites)
        self.filter_cache.clear()
        self.on_filter_rom_list(event=-1, preserve_search=True)
        self.Refresh()
        _event.Skip()

    # ------------------------------------------------------------------------------------------------------------------
    # Show the alternate emulators window
    def on_alternate_emulators(self, _event) -> None:
        # The window doesn't block, so re-load the alternate emulation engine data when it closes as it may have changed
        alternate_emulators.AlternateEmulators(on_closed=self.load_alternate_emulator_engines)

    # ------------------------------------------------------------------------------------------------------------------
    # Force pfeMAME to run the selected ROM using MAME rather than the alternate emulator engine assigned
    def on_force_play_mame(self, _event) -> None:
        self.on_double_click(force_mame=True)

    # ------------------------------------------------------------------------------------------------------------------
    # This is the handler for image files dropped on the ROM image panel
    def on_files_dropped(self, files):
        """
        Handle an image file dropped onto the ROM image panel.  The file is converted to PNG and written to the
        location the app loads images from for the selected ROM and the currently displayed image option
        (Snapshot, PCB, Cabinet...), which is the same target the 'Replace image from online' feature uses.
        """
        if not files:
            return
        file_path = files[0]  # While we can detect multiple files, only one image can be assigned
        if not os.path.isfile(file_path):
            return

        if not self.image_options:
            self.statusbar_panel.set_status(_('No image folders are configured'))
            return

        results = self.get_virtual_list_row_info()
        if not results.rom_file_name:
            self.statusbar_panel.set_status(_('Select a ROM first'))
            return

        # Validate by loading it - this also gives us the image to re-encode as PNG
        with wx.LogNull():  # Suppress image loading errors for non-image files
            image = wx.Image(file_path)
        if not image.IsOk():
            self.messages_append(_('{} is not a valid image file\n').format(os.path.basename(file_path)), True)
            self.enable_alert_timer()
            return

        # _compute_image_path() is the single source of truth for where an image lives, and handles both
        # arcade ROMs and system programs (software list items)
        target_path = self._compute_image_path(results, for_save=True)
        if not target_path:
            return

        if os.path.exists(target_path):
            answer = wx.MessageBox(
                _('An image already exists at:\n{}\n\nReplace it with the dropped image?').format(target_path),
                _('Replace Existing Image'), wx.YES_NO | wx.ICON_QUESTION, self)
            if answer != wx.YES:
                return

        try:
            os.makedirs(os.path.dirname(target_path), exist_ok=True)
            # Save as PNG regardless of the source format, since the app loads images as PNG
            if not image.SaveFile(target_path, wx.BITMAP_TYPE_PNG):
                raise IOError('SaveFile returned False')
        except Exception as exc:
            self.my_logger.error(f'Failed to save dropped image to {target_path}: {exc}')
            self.messages_append(_('Failed to save the image to {}\n').format(target_path), True)
            self.enable_alert_timer()
            wx.MessageBox(_('The image could not be saved to:\n{}').format(target_path),
                          _('Save Failed'), wx.OK | wx.ICON_ERROR, self)
            return

        # Drop any cached scaled bitmap for this path so the new image shows immediately
        _scaled_rom_image.cache_clear()
        self.messages_append(_('Saved new image to {}\n').format(target_path))
        self.statusbar_panel.set_status(_('Image updated'))
        self.on_single_click()


# ------------------------------------------------------------------------------------------------------------------
def favorite_export_items(mylist: list, rom_folders: list[str]) -> list[tuple[str, str]]:
    """
    What Export Favorites copies: (source path, name to give it) for each favorite ROM set found in the ROM folders -
    its .zip or .7z, and its CHD folder (a folder with the ROM set's name) if it has one.  Each ROM set only once.
    """
    items, seen = [], set()
    for row in mylist:
        name = row[index_rom_file_name]
        if row[index_favorite] != '1' or not name or name in seen:
            continue
        seen.add(name)
        for ext in ('.zip', '.7z'):
            source = functions.find_in_folders(rom_folders, name + ext)
            if source and os.path.isfile(source):
                items.append((source, name + ext))
                break   # Stop after first found extension
        for folder in rom_folders:
            chd_folder = os.path.join(folder, name)
            if os.path.isdir(chd_folder):
                items.append((chd_folder, name))
                break
    return items


# ------------------------------------------------------------------------------------------------------------------
class _GuiThreadCalls:
    """Stands in for the main window in code that may run on a background thread: the messages window and alert
    timer calls it makes are passed on to the GUI thread."""

    def __init__(self, frame):
        self._frame = frame

    def messages_append(self, *args, **kwargs) -> None:
        wx.CallAfter(self._frame.messages_append, *args, **kwargs)

    def enable_alert_timer(self) -> None:
        wx.CallAfter(self._frame.enable_alert_timer)


# ------------------------------------------------------------------------------------------------------------------
@lru_cache(maxsize=512)
def _scaled_rom_image(file_name: str, _modified: float) -> wx.Bitmap:
    """
    Load a ROM image scaled to fit the image panel, keeping its shape.  Cached by file name and modification time
    (_modified), so an image that is replaced on disk is loaded again rather than the old one being shown.
    Raises if the file is not a readable image.
    """
    with Image.open(file_name) as picture:
        w, h = picture.size
    if w <= 0 or h <= 0:
        raise ValueError(f'image has no size ({w} x {h})')
    if w >= h:
        scale_x = image_size_x
        scale_y = max(1, int(h * (scale_x / w)))
    else:
        scale_y = image_size_y
        scale_x = max(1, int(w * (scale_y / h)))
    return functions.load_and_scale_bitmap(file_name, scale_x, scale_y, "NEAREST")


# ------------------------------------------------------------------------------------------------------------------
# This class provides the drop target event handler.
# This is used for the dropping of image files onto the image snapshot panel.
class MyFileDropTarget(wx.FileDropTarget):
    def __init__(self, callback):
        super().__init__()
        self.callback = callback  # Function to call when files are dropped

    def OnDropFiles(self, x, y, filenames):
        """
        Called when files are dropped onto the target.
        x, y: Drop coordinates relative to the window
        filenames: List of file paths
        """
        try:
            self.callback(filenames)
            return True
        except Exception as e:
            wx.LogError(f"Error handling dropped files: {e}")
            return False


# ------------------------------------------------------------------------------------------------------------------
class MyPopupMenu(wx.Menu):
    """
    Context menu for the ROMs list (right-click menu).
    """

    def __init__(self, parent, item: int, alternate_emulation_engines: list) -> None:
        super().__init__()
        self.parent = parent

        # Define menu items as tuples: (attribute_name, label, help_text, handler_function)
        # A None entry inserts a separator between groups
        self.menu_items = [
            # Play
            ("on_double_click_id", _("Play ROM"), _("Play the selected ROM"), parent.on_double_click),
            ("on_force_play_mame_id", _("Play ROM with MAME rather than alternate engine"),
             _("Play the selected ROM with MAME"), parent.on_force_play_mame),
            ("on_suppress_short_version_id", _("Play ROM without softlist HASH support"),
             _("Play the system program directly without using the softwarelist HASH file"),
             parent.on_suppress_short_version),
            None,
            # Information
            ("on_rom_info_id", _("ROM information"), _("Information on the selected ROM"), parent.on_rom_info),
            ("on_view_media_types_id", _("View media types"), _("View supported media types"),
             parent.on_view_media_types),
            ("on_software_browser_id", _("Browse software lists..."),
             _("Browse all the software MAME knows for this system, and what you have"), parent.on_software_browser),
            ("on_xml_info_id", _("Analyse XML info"), _("Check XML info for this program"), parent.on_xml_info),
            None,
            # Favorites, watchlist and rating
            ("on_add_favorite_id", _("Add to favorites"), _("Add ROM to favorites"), parent.on_add_favorite),
            ("on_delete_favorite_id", _("Remove from favorites"), _("Remove ROM from favorites"), parent.delete_favorite),
            ("on_add_watchlist_id", _("Add to watchlist"), _("Add ROM to watch list"), parent.on_add_watchlist),
            ("on_delete_watchlist_id", _("Remove from watchlist"), _("Remove ROM from watch list"), parent.delete_watchlist),
            ("on_set_rating_id", _("Set ROM rating..."), _("Set star rating for this ROM"), parent.on_set_rating),
            None,
            # Per-ROM configuration
            ("on_preferences_rom_id", _("ROM preferences"), _("Set MAME preferences for this ROM"),
             parent.preferences_rom_specific),
            ("on_copy_controller_mappping_id", _("Copy controller mapping to this ROM"),
             _("Copy default.cfg to this ROM for per-ROM input mapping"), parent.on_controller_mapping),
            ("on_ini_file_reset_id", _("Reset INI file"), _("Reset the INI config file for this program"),
             parent.on_ini_file_reset),
            None,
            # ROM file maintenance
            ("on_verify_roms_id", _("Verify ROM"), _("Verify the integrity of the selected ROM"),
             parent.on_verify_roms),
            ("on_search_rom_online_id", _("Search for ROM online..."),
             _("Search online for this ROM's ZIP file and download it to the ROMs folder"),
             parent.on_search_rom_online),
        ]

        self.context_menu_ids = []

        for menu_item in self.menu_items:
            if menu_item is None:
                self.AppendSeparator()
                continue
            attr, label, help_text, handler = menu_item
            control_id = wx.Window.NewControlId()
            setattr(self, attr, control_id)
            self.context_menu_ids.append(control_id)
            self.Append(control_id, label, help_text)
            self.Bind(wx.EVT_MENU, handler, id=control_id)

        if item != -1:
            self.Bind(wx.EVT_MENU_HIGHLIGHT, self.on_help_string)
            self.Bind(wx.EVT_MENU_CLOSE, self.on_remove_text)

            temp = parent.statusbar_panel.get_status_text()
            parent.list.Select(item)
            results = parent.get_virtual_list_row_info()

            # Disable unsupported options based on ROM metadata
            if not results.short_name:
                self.Enable(id=self.on_suppress_short_version_id, enable=False)

            if not any(results.rom_file_name in group for group in alternate_emulation_engines):
                self.Enable(id=self.on_force_play_mame_id, enable=False)

            if results.favorites_flag == 1 :
                self.Enable(id=self.on_add_favorite_id, enable=False)

            if results.favorites_flag == 2 :
                self.Enable(id=self.on_add_watchlist_id, enable=False)

            if results.favorites_flag != 1 :
                self.Enable(id=self.on_delete_favorite_id, enable=False)

            if results.favorites_flag != 2 :
                self.Enable(id=self.on_delete_watchlist_id, enable=False)

            if results.rom_file_name not in parent.system_rom_names:
                self.Enable(id=self.on_software_browser_id, enable=False)

            parent.statusbar_panel.set_status(temp)

    # ------------------------------------------------------------------------------------------------------------------
    # Display the help string in the status bar for the ROM list right-click menu
    #
    # By default, wxPython should be doing this for me, but there seems to be an issue with the current release
    # whereby the toolbar menu works ok but the right-click context menu won't display help text.
    #
    # The check for the event_id being from the list of valid ids for the context menu is there to prevent a core
    # error event.  This happens when you try to get an argument that doesn't exist.
    def on_help_string(self, event) -> None:
        event_id = event.GetId()
        if event_id in self.context_menu_ids:
            self.parent.statusbar_panel.set_status(self.GetHelpString(event_id))

    # ------------------------------------------------------------------------------------------------------------------
    # We are no longer selecting any items in the context menu so reset the status bar to 'Ready'
    def on_remove_text(self, _event) -> None:
        self.parent.statusbar_panel.set_status(_('Ready'))


# ------------------------------------------------------------------------------------------------------------------
class ImagePanel(wx.Panel):
    """
    A panel that displays an image centered both horizontally and vertically.
    Expands to fill available space with padding.
    """

    def __init__(self, parent: wx.Panel, image_x_size: int, image_y_size: int, rom_list, main_frame=None) -> None:
        super().__init__(parent)

        self.parent = parent
        self.rom_list = rom_list
        self.main_frame = main_frame   # The PfeMAME frame, used for the online image-replace feature
        self.image_file_name = ''

        # Prevent shrinking smaller than initial image size
        self.SetMinSize(wx.Size(image_x_size, image_y_size))

        # Placeholder bitmap initially (could be blank or loaded later)
        self.image = wx.StaticBitmap(self, bitmap=wx.Bitmap(image_x_size, image_y_size))
        self.image.SetCursor(wx.Cursor(wx.CURSOR_HAND))  # Hint that the image is clickable
        self.image.Bind(wx.EVT_LEFT_DOWN, self.on_clicked)
        self.image.Bind(wx.EVT_RIGHT_DOWN, self.on_right_clicked)

        # Layout: center image using stretch spacers
        main_sizer = wx.BoxSizer(wx.VERTICAL)
        horizontal_sizer = wx.BoxSizer(wx.HORIZONTAL)

        horizontal_sizer.AddStretchSpacer()
        horizontal_sizer.Add(self.image, flag=wx.ALIGN_CENTER)
        horizontal_sizer.AddStretchSpacer()

        main_sizer.AddStretchSpacer()
        main_sizer.Add(horizontal_sizer, flag=wx.EXPAND)
        main_sizer.AddStretchSpacer()

        self.SetSizer(main_sizer)

    def set_image_file_name(self, file_name: str) -> None:
        self.image_file_name = file_name

    def on_clicked(self, _event) -> None:
        current_item = self.rom_list.GetFirstSelected()
        if current_item != -1:
             if os.path.exists(self.image_file_name):
                rom_name = self.rom_list.GetItemText(current_item, index_rom_name)
                popupimage.PopUpImageViewer(rom_name, self.image_file_name)

    def on_right_clicked(self, _event) -> None:
        """Show a context menu offering to replace the current image with one found online."""
        if self.main_frame is None:
            return
        menu = wx.Menu()
        replace_item = menu.Append(wx.ID_ANY, _('Replace image from online...'))
        self.Bind(wx.EVT_MENU, lambda evt: self.main_frame.on_replace_rom_image(), replace_item)
        functions.show_popup_menu(self, menu)


# ----------------------------------------------------------------------------------------------------------------------
# This is where the application starts
if __name__ == '__main__':
    # Must come first: in a frozen Windows build a multiprocessing worker starts this program again, and this is
    # where it has to stop and run the worker (before, it got as far as creating the main window).
    multiprocessing.freeze_support()
    app = wx.App()

    first_time_call = True

    # Run the main loop until we exit the application.  This allows in-app restarts to be supported.
    while restart_requested or first_time_call:
        restart_requested = False
        first_time_call = False
        MainFrame()
        app.MainLoop()
        if restart_requested and sys.platform == 'darwin':
            # In a frozen (PyInstaller) build sys.argv[0] is already the
            # executable path, so re-using sys.executable as argv[0] would
            # duplicate it. The extra path is then seen by argparse as an
            # unrecognized positional argument and the relaunched process
            # exits immediately. Strip argv[0] when frozen.
            relaunch_args = sys.argv[1:] if getattr(sys, 'frozen', False) else sys.argv
            # Pass the force-restart flag so the relaunched process knows it
            # was auto-restarted (drives _handle_force_restart on startup).
            if '-x' not in relaunch_args and '--force_restart' not in relaunch_args:
                relaunch_args = relaunch_args + ['-x']
            os.execv(sys.executable, [sys.executable] + relaunch_args)
