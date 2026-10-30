#!/usr/bin/env python3

# ----------------------------------------------------------------------------------------------------------------------
# tileview.py

"""
Tileview display mode for ROM lists.

It presents a tiled view of ROM images that can be scrolled up / down.  The size of the images can be changed in
the main program preferences (small, medium, and large).  The program will automatically calculate the number of
tiles to show horizontally and vertically depending upon the screen resolution and tile size.
Tile navigation can be performed using the cursor keys or joystick / gamepad.
"""

# Import python & wxPython modules
import wx, wx.richtext, wx.lib.scrolledpanel
import iniFile
import os
import logging.handlers
import time

# Import my own modules
import rungame
import functions
import fullscreenplay
import play_stats
from video_class import Video
from preferences_model import PFEMAME_DEFAULTS
from tile_grid_model import (TileGridModel, LruCache, HoldRepeater, shift_page, favorite_key, find_video,
                             UP, DOWN, LEFT, RIGHT, PAGE_UP, PAGE_DOWN, HOME, END, MOVES,
                             SORT_NAME, SORT_MOST_RUNS, SORT_ORDERS, tile_view_key,
                             VIEW_EXISTS, VIEW_FAVORITES, VIEW_WATCHLIST, VIEW_RECENT, VIEW_MOST_PLAYED,
                             index_rom_name, index_rom_file_name, index_system_program_file_name, index_exists,
                             index_number_runs, index_favorite, index_system_short_name, index_system_folder_name)

# Define Constants
image_size_x = 224
image_size_y = 256
# Used if the saved setting isn't a number (e.g. after a hand edit)
default_brightness = float(PFEMAME_DEFAULTS['preferences']['brightness'])
info_panel_width = 300
GLOW_COLOR = (0, 200, 255)   # Cyan — works well on dark arcade backgrounds.
                              # Change to (255, 180, 0) for amber, (180, 0, 255) for purple, etc.
GLOW_LAYERS = [
    (8, 25),   # (extra pixels out from button edge, alpha 0-255)
    (4, 70),
    (2, 160),
    (0, 255),  # The solid inner border
]
VIDEO_PLAYBACK_DELAY = 2000     # Delay in ms for video playback
KEY_COMBO_TIMEOUT = 500         # Time in ms to wait for the second key of a key combination (e.g. ALT-1)
JOYSTICK_POLL_INTERVAL = 20     # Time in ms between reads of the joystick stick / D-pad position
POINTER_HIDE_DELAY = 3000        # Time in ms the mouse pointer stays visible after the mouse stops moving
DOUBLE_CLICK_TIME = 0.5         # Seconds between two clicks on the same tile for them to count as a double-click
KEY_IGNORE_AFTER_GAME = 1.0     # Seconds to ignore keys after a game ends, so a held ESC that quit MAME doesn't
                                # also exit Tile View
INFO_SCROLL_MIN_LINES = 20      # Auto-scroll the ROM info once it has more lines than this (approximate)
INFO_LINE_HEIGHT = 8            # Approximate pixel height of a line in the ROM info window
TILE_CACHE_SIZE = 300           # Number of tile images kept in memory (about 70 MB at the Large tile size)
PRELOAD_DELAY = 150             # Idle time in ms before the rows above / below the page are preloaded
PRELOAD_STEP = 10               # Time in ms between preloading each image, so key presses are never held up
# How far the highlight glow reaches outside a tile (widest layer plus its pen width)
GLOW_MARGIN = max(expand + expand // 2 + 1 for expand, _alpha in GLOW_LAYERS) + 2

USE_STATIC_BITMAP = False

# Actions that the keyboard / joystick can trigger
ACTION_PLAY = 'play'
ACTION_CYCLE_VIEW = 'cycle_view'
ACTION_EXIT = 'exit'
ACTION_FINDER = 'finder'
ACTION_BRIGHTNESS = 'brightness'
ACTION_FAVORITE = 'favorite'
ACTION_SORT = 'sort'
ACTION_CATEGORY = 'category'
ACTION_MENU = 'menu'

KEY_ACTIONS = {
    wx.WXK_LEFT: LEFT,
    wx.WXK_RIGHT: RIGHT,
    wx.WXK_UP: UP,
    wx.WXK_DOWN: DOWN,
    wx.WXK_PAGEUP: PAGE_UP,
    wx.WXK_PAGEDOWN: PAGE_DOWN,
    wx.WXK_NUMPAD_PAGEUP: PAGE_UP,
    wx.WXK_NUMPAD_PAGEDOWN: PAGE_DOWN,
    wx.WXK_HOME: HOME,
    wx.WXK_END: END,
    wx.WXK_NUMPAD_HOME: HOME,
    wx.WXK_NUMPAD_END: END,
    wx.WXK_CONTROL: ACTION_CYCLE_VIEW,
    ord('1'): ACTION_PLAY,
    wx.WXK_RETURN: ACTION_PLAY,
    wx.WXK_NUMPAD_ENTER: ACTION_PLAY,
    ord('2'): ACTION_EXIT,
    ord('3'): ACTION_FAVORITE,
    ord('4'): ACTION_SORT,
    ord('7'): ACTION_CATEGORY,
    wx.WXK_ESCAPE: ACTION_EXIT,
    ord('5'): ACTION_BRIGHTNESS,
    ord('6'): ACTION_FINDER,
}
KEY_COMBO_ROM_MENU = {wx.WXK_ALT, ord('1')}

JOYSTICK_BUTTON_ACTIONS = {
    1: ACTION_PLAY,
    2: ACTION_CYCLE_VIEW,
    4: ACTION_FAVORITE,         # Button 3 (GetButtonState is a bit mask)
    16: ACTION_SORT,            # Button 5
    32: ACTION_CATEGORY,        # Button 6
    8: ACTION_MENU,             # Button 4 - Exit is in the menu
}
POV_DIRECTIONS = {
    0: UP,
    9000: RIGHT,
    18000: DOWN,
    27000: LEFT,
}
# Key codes the virtual keyboard understands for each direction
DIRECTION_KEYS = {
    UP: wx.WXK_UP,
    DOWN: wx.WXK_DOWN,
    LEFT: wx.WXK_LEFT,
    RIGHT: wx.WXK_RIGHT,
}

# _ = functions.set_up_language()  # Set up the application language

# ----------------------------------------------------------------------------------------------------------------------
# The following is the Tile View window
class TileView(wx.Frame):

    def __init__(self,
                 mylist_local: list,
                 my_logger: logging.Logger,
                 version: str,
                 mame_version: str,
                 video_disable,
                 copy_right: str,
                 view_filter,
                 development):
        wx.Frame.__init__(self, wx.GetApp().TopWindow, -1, size=wx.DisplaySize(), style=wx.NO_BORDER)

        # _ = functions.set_up_language()  # Set up the application language
        self.development = development
        self.video_disable = video_disable

        # --------------------------------------------------------------------------------------------------------------
        # Get the absolute path to this application.
        self.path_to_me = functions.path_to_me()  # Get the absolute path to me

        # --------------------------------------------------------------------------------------------------------------
        # Load the categories file
        self.categories, self.ignore_categories, _unused = functions.load_categories_file(self.path_to_me)

        # --------------------------------------------------------------------------------------------------------------
        # Try to work out the platform
        # This is needed to sort out some platform specific differences
        self.system = functions.get_platform()

        # --------------------------------------------------------------------------------------------------------------
        # Get the parent
        self.parent = self.GetParent()

        # --------------------------------------------------------------------------------------------------------------
        # Disable the parent window while this is running
        if self.parent is not None:  # Following will only be called if this window is running as a child
            self.CenterOnParent()
            # Disable this for testing purposes so that a code error won't prevent me from closing the program
            self.parent.Disable()

        # --------------------------------------------------------------------------------------------------------------
        # Bind some events
        self.Bind(wx.EVT_CLOSE, self.on_close)  # bind the close event
        self.Bind(wx.EVT_CHAR_HOOK, self.on_key_down)  # Bind a keypress event
        self.Bind(wx.EVT_BUTTON, self.single_click)  # Create the single click event binding

        # --------------------------------------------------------------------------------------------------------------
        # Get font information from the INI file
        fonts = functions.get_font_info()
        self.global_font_normal = fonts.global_font_normal
        self.global_font_normal_8 = fonts.global_font_normal_8

        # --------------------------------------------------------------------------------------------------------------
        # Set up logging
        self.my_logger = my_logger
        self.my_logger.info('Running Tileview')  # Write to the log file

        # --------------------------------------------------------------------------------------------------------------
        # Define the keyboard multi-key decode variables & timer
        self.timer_key = wx.Timer(self)
        self.key_list = []
        self.Bind(wx.EVT_TIMER, self.on_key_timer,self.timer_key)

        # --------------------------------------------------------------------------------------------------------------
        # Set up the ROM history scroll timer and variables
        # This is for auto scrolling the ROM history as the information available will be more than can be displayed
        # in one go.
        self.timer_delay = 100  # Set the speed at which the ROM info will scroll in ms
        self.scroll_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.on_scroll_timer, self.scroll_timer)
        self.scroll_steps = 1

        # --------------------------------------------------------------------------------------------------------------
        # Set up video playback delay timer
        # This creates a pause between selecting a ROM and the video playing (if one exists)
        self.video_delay_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.on_video_playback, self.video_delay_timer)

        # --------------------------------------------------------------------------------------------------------------
        # Tile image cache and the idle preloading of the rows just above / below the page
        self._bitmap_cache = LruCache(TILE_CACHE_SIZE)
        self._default_bitmap = None   # Shared image for ROMs without a snapshot
        self._blank_bitmap = None     # Shared image for empty tiles
        self._preload_queue: list[int] = []
        self.preload_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.on_preload_timer, self.preload_timer)

        # --------------------------------------------------------------------------------------------------------------
        # Setup the local copy of mylist.
        # This copy only has programs that actually exist.
        self.myList = [x for x in mylist_local if x[index_exists] == '1']

        # --------------------------------------------------------------------------------------------------------------
        # Get variables from the pfemame.ini file
        self.tile_dim = iniFile.read_ini_file('preferences', 'tiledim') == 'True'
        # 'Auto Select the last ROM selected and last view' - Tile View also remembers its own position
        self.remember_position = iniFile.read_ini_file('preferences', 'uselastselected') == 'True'
        # A-Z jumps to a letter - off by default as arcade control panels often send letter keys for their buttons
        self.letter_jump = iniFile.read_ini_file('preferences', 'tileletterjump') == 'True'
        # Mouse support - off by default as cabinets often have a trackball / spinner set up as a mouse
        self.mouse_enabled = iniFile.read_ini_file('preferences', 'tilemouse') == 'True'
        self.prefTileSize = iniFile.read_ini_file('preferences', 'tilesize')
        self.path_mame_exe = iniFile.read_ini_file('path', 'mame_executable')
        self.foldersVideo = iniFile.read_ini_file('folders', 'video')
        self.path_to_mame_ini_file = iniFile.read_ini_file('path', 'mame_ini')
        self.folder_mapping = iniFile.read_ini_file('folders', 'input_mapping')
        self.pathHistory = iniFile.read_ini_file('path', 'history_dat')
        self.suppress_short_name = iniFile.read_ini_file('preferences', 'suppressshortname') != 'False'
        self.pref_joystick_selected = iniFile.read_ini_file('preferences', 'joystickselected')
        # An empty setting means joystick navigation is enabled
        self.joystick_enabled = iniFile.read_ini_file('preferences', 'enablejoysticktileview') in ('', 'True')
        # Video autoload only turns the tile preview videos on / off.  The screensaver, like the main window's, only
        # stops when all video playback is disabled (video_disable) or the screensaver time is 0.
        self.preview_videos = iniFile.read_ini_file('preferences', 'videoautoload') != 'False'
        self.screensaver_minutes = iniFile.read_ini_int('preferences', 'screensavertime', low=0)
        try:
            self.brightness_level = float(iniFile.read_ini_file('preferences', 'brightness'))
        except (ValueError, TypeError):
            self.brightness_level = default_brightness

        # Get variables from the mame.ini file
        self.foldersSnap = iniFile.get_from_mameini('snapshot_directory', self.path_to_mame_ini_file)

        # --------------------------------------------------------------------------------------------------------------
        # Calculate the window resolution and determine how many games I can display in the x / y grid
        # Use fraction of the standard 224 * 256 (1 = 100%)
        scale_factors = {
                         'Small': 0.7,
                         'Medium': 0.8,
                         'Large': 1.0
                        }

        scale = scale_factors.get(self.prefTileSize, scale_factors.get('Large'))
        self.imageScale_X = int(scale * image_size_x)
        self.imageScale_Y = int(scale * image_size_y)

        # Take the info panel and spacers away from available size and define how many horizontal and vertical
        # images we can have.  Always show at least one tile, even on a very small display.
        resolution_horizontal, resolution_vertical = self.GetSize()
        space_horizontal = resolution_horizontal - info_panel_width
        self.numHorizontal = max(1, int(space_horizontal // (self.imageScale_X + 14)))
        self.numVertical = max(1, int(resolution_vertical // ((self.imageScale_Y + 4) + 18)))

        # --------------------------------------------------------------------------------------------------------------
        # Process some startup requirements
        # The model holds the filtered ROM list, the scroll position and the focused tile
        self.model = TileGridModel(self.myList,
                                   columns=self.numHorizontal,
                                   rows=self.numVertical,
                                   categories=self.categories,
                                   ignore_categories=self.ignore_categories)
        self.model.play_stats = getattr(self.parent, 'play_stats', None) or \
            play_stats.PlayStats(os.path.join(functions.data_dir(), play_stats.FILE_NAME))
        if self.remember_position:
            self._restore_position(view_filter)
        else:
            self.model.apply_filter(tile_view_key(view_filter))
        self.box_parameters: list = []
        self.joystick_block: bool = False
        self.favorites_changed: bool = False  # The main window refreshes its list once Tile View closes
        self._ignore_keys_until: float = 0.0  # time.monotonic() value
        self.inactivity_timer_block: bool = False

        # --------------------------------------------------------------------------------------------------------------
        # Pre-load the history file (Assuming it exists)
        self.history_data = functions.load_history_dat(self,
                                                       self.my_logger,
                                                       self.pathHistory,
                                                       'history',
                                                       suppress=True)

        # --------------------------------------------------------------------------------------------------------------
        # Set up the inactivity timer and start it.  This is used for the screensaver.
        self.inactivity_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.on_activity_timer, self.inactivity_timer)
        self.inactivity_timer_start()

        self.Bind(wx.EVT_WINDOW_DESTROY, self.on_destroy)

        # --------------------------------------------------------------------------------------------------------------
        # Try to capture the joystick for navigation and determine the directional
        # values for the stick / dpad
        (self.joystick,
         self.joystick_polling_timer,
         self.joystickXMin,
         self.joystickXMax,
         self.joystickYMin,
         self.joystickYMax) = functions.joystick_setup(self, my_logger, self.pref_joystick_selected)

        # A held stick or D-pad repeats, speeding up the longer it is held.  wx only sends joystick events when the
        # stick moves, so both the stick and the D-pad are read on the polling timer (which joystick_setup only
        # starts, slowly, for a D-pad).
        self.hold_repeater = HoldRepeater()
        if self.joystick is not None:
            self.joystick_polling_timer.Stop()
            self.Unbind(wx.EVT_TIMER, source=self.joystick_polling_timer)
            self.Bind(wx.EVT_TIMER, self.on_joystick_pov, self.joystick_polling_timer)
            self.joystick_polling_timer.Start(JOYSTICK_POLL_INTERVAL)

        # --------------------------------------------------------------------------------------------------------------
        # Set the window background colour
        self.SetBackgroundColour('black')

        # --------------------------------------------------------------------------------------------------------------
        # Define the mouse pointer override - this helps to hide the mouse pointer
        self.my_cursor = wx.Cursor(wx.CURSOR_BLANK)
        self.SetCursor(self.my_cursor)

        # --------------------------------------------------------------------------------------------------------------
        # Create the panels
        top_panel = wx.Panel(self)
        self.panel_rom_buttons = wx.Panel(top_panel)

        self.panel_logo = LogoPanel(top_panel,
                                    version,
                                    mame_version,
                                    self.path_to_me,
                                    self.my_cursor,
                                    copy_right,
                                    self.global_font_normal)

        self.panel_info = InfoPanel(top_panel,
                                self.my_cursor,
                                self.global_font_normal_8)

        self.panel_rom_info = RomInfoPanel(top_panel,
                                   self.global_font_normal_8)

        # Create the virtual keyboard, hidden until F is pressed
        self.virtual_keyboard = VirtualKeyboard(
            self,
            on_enter_callback=self._on_finder_enter,
            global_font_normal_8=self.global_font_normal_8
        )
        self.virtual_keyboard.Hide()

        # Create the category picker (7) and the menu (ALT-1 / joystick button 4), hidden until needed
        self.category_picker = ListPopup(
            self,
            title=_('Choose a category'),
            on_select_callback=self._on_category_selected,
            global_font_normal_8=self.global_font_normal_8
        )
        self.category_picker.Hide()
        self.rom_menu = ListPopup(
            self,
            title=_('Menu'),
            on_select_callback=self._on_menu_selected,
            global_font_normal_8=self.global_font_normal_8,
            visible_rows=8
        )
        self.rom_menu.Hide()

        # --------------------------------------------------------------------------------------------------------------
        # Set up the scrolled panel scrolling settings
        self.panel_rom_info.SetupScrolling()
        self.panel_rom_info.SetScrollRate(0, self.scroll_steps)  # Number of pixel lines to scroll at a time
        self.panel_rom_info.ShowScrollbars(horz=wx.SHOW_SB_NEVER, vert=wx.SHOW_SB_NEVER)  # Hide the scrollbars

        # --------------------------------------------------------------------------------------------------------------
        # Create the media control for video playback
        self.media_player_available = self.create_media_control()

        sizer_panel_1_horizontal = wx.BoxSizer(wx.HORIZONTAL)
        sizer_panel_1_vertical = wx.BoxSizer(wx.VERTICAL)

        # --------------------------------------------------------------------------------------------------------------
        # Build the grid of buttons with game names
        sizer_grid = self.create_button_grid()
        self.schedule_preload()

        sizer_panel_1_vertical.AddStretchSpacer()
        sizer_panel_1_vertical.Add(sizer_grid, proportion=1, flag=wx.EXPAND)
        sizer_panel_1_vertical.AddStretchSpacer()

        sizer_panel_1_horizontal.AddSpacer(10)
        sizer_panel_1_horizontal.Add(sizer_panel_1_vertical)
        sizer_panel_1_horizontal.AddSpacer(10)

        # --------------------------------------------------------------------------------------------------------------
        # Optionally dim all buttons that are not in focus
        # This makes it much easier to see which game is selected but the problem
        # is that the dim buttons can be a bit hard to see.
        if self.tile_dim:
            self._show_all_tiles()

        # --------------------------------------------------------------------------------------------------------------
        # Show the sizer
        sizer = wx.BoxSizer(wx.HORIZONTAL)
        sizer_vertical = wx.BoxSizer(wx.VERTICAL)
        sizer.AddSpacer(10)
        sizer.Add(self.panel_rom_buttons, 0, wx.EXPAND | wx.ALL)
        sizer.AddStretchSpacer()

        sizer.Add(sizer_vertical, 1, wx.EXPAND | wx.ALL)

        sizer_vertical.Add(self.panel_logo)
        sizer_vertical.Add(self.panel_info, 1, wx.EXPAND | wx.ALL)
        sizer_vertical.Add(self.panel_rom_info, 1, wx.EXPAND | wx.ALL)
        wx.CallAfter(self._position_virtual_keyboard)

        top_panel.SetSizer(sizer)
        self.panel_rom_buttons.SetSizerAndFit(sizer_panel_1_horizontal)
        self.Layout()
        self.Show()

        # --------------------------------------------------------------------------------------------------------------
        # Display the window
        self.ShowFullScreen(True, wx.FULLSCREEN_NOCAPTION)  # Make it full screen with no title bars etc

        # --------------------------------------------------------------------------------------------------------------
        # Define the event to paint a rectangle around the buttons
        self.panel_rom_buttons.Bind(wx.EVT_PAINT, self.on_paint)

        # --------------------------------------------------------------------------------------------------------------
        # Optional mouse support
        if self.mouse_enabled:
            self._setup_mouse()

        # --------------------------------------------------------------------------------------------------------------
        # Draw a rectangle around the ROM button with focus and update the information bar
        wx.CallAfter(self.display_info)

    # ------------------------------------------------------------------------------------------------------------------
    # Mouse support (when enabled in preferences): click a tile to select it, double-click to play, the wheel moves
    # up / down and right-click opens the menu.  The pointer shows while the mouse moves and hides again after a
    # few seconds.
    def _setup_mouse(self) -> None:
        self.pointer_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.on_pointer_timer, self.pointer_timer)
        self._pointer_visible = False
        self._last_mouse_position = wx.GetMousePosition()
        self._last_click = (-1, 0.0)  # (slot, time.monotonic())
        self._wheel_rotation = 0

        for slot, (button, text) in enumerate(zip(self.controlsButton, self.controlsText)):
            for window in (button, text):
                window.Bind(wx.EVT_LEFT_DOWN, lambda _event, slot=slot: self.on_tile_click(slot))
                window.Bind(wx.EVT_LEFT_DCLICK, lambda _event, slot=slot: self.on_tile_click(slot, double=True))

        for window in self._mouse_windows(include_popups=False):
            window.Bind(wx.EVT_MOUSEWHEEL, self.on_mouse_wheel)
            window.Bind(wx.EVT_RIGHT_DOWN, self.on_mouse_right_click)
        for window in self._mouse_windows(include_popups=True):
            window.Bind(wx.EVT_MOTION, self.on_mouse_motion)
        for popup in (self.rom_menu, self.category_picker):
            popup.enable_mouse()

    # ------------------------------------------------------------------------------------------------------------------
    # This window and everything in it (mouse events don't pass from a control to its parent).  The popups handle
    # their own clicks and wheel, so they are only included when asked for.
    def _mouse_windows(self, include_popups: bool) -> list[wx.Window]:
        windows = []

        def add(window: wx.Window) -> None:
            if isinstance(window, wx.PopupWindow) and not include_popups:
                return
            windows.append(window)
            for child in window.GetChildren():
                add(child)

        add(self)
        return windows

    # ------------------------------------------------------------------------------------------------------------------
    def _show_pointer(self, visible: bool) -> None:
        if visible == self._pointer_visible:
            return
        self._pointer_visible = visible
        cursor = wx.Cursor(wx.CURSOR_ARROW) if visible else self.my_cursor
        for window in self._mouse_windows(include_popups=True):
            window.SetCursor(cursor)

    def on_pointer_timer(self, _event) -> None:
        self._show_pointer(False)

    # ------------------------------------------------------------------------------------------------------------------
    def on_mouse_motion(self, event) -> None:
        event.Skip()
        position = wx.GetMousePosition()
        last = self._last_mouse_position
        if abs(position.x - last.x) + abs(position.y - last.y) < 3:
            return  # Windows sends 'moves' when the window under the pointer changes - ignore those
        self._last_mouse_position = position
        self._show_pointer(True)
        self.pointer_timer.StartOnce(POINTER_HIDE_DELAY)
        self.inactivity_timer_start()

    # ------------------------------------------------------------------------------------------------------------------
    # Click a tile to select it.  A second click on the same tile (or a double-click) plays it.
    def on_tile_click(self, slot: int, double: bool = False) -> None:
        if (self.joystick_block or self.virtual_keyboard.IsShown() or self._shown_list_popup() is not None
                or self.model.row_at(slot) is None):
            return

        now = time.monotonic()
        last_slot, last_time = self._last_click
        double = double or (slot == last_slot and now - last_time < DOUBLE_CLICK_TIME)
        self._last_click = (-1, 0.0) if double else (slot, now)

        self.on_user_input()
        self.single_click(-1)  # Keep the keyboard working
        old_focus = self.model.focused
        if slot != old_focus:
            self.model.focused = slot
            self._show_move(old_focus, self.model.start_index, True, False)
        if double:
            self.play_game()
        elif slot == old_focus:
            self.draw_rectangle(self.controlsButton[slot])  # Restart the video the click stopped

    # ------------------------------------------------------------------------------------------------------------------
    # The wheel moves up / down a row (or through the menu / category list).  Small movements from touchpads are
    # added up until they make a whole step.
    def on_mouse_wheel(self, event) -> None:
        if self.joystick_block or self.virtual_keyboard.IsShown():
            return
        self._wheel_rotation += event.GetWheelRotation()
        delta = max(1, event.GetWheelDelta())
        steps = int(self._wheel_rotation / delta)
        if not steps:
            return
        self._wheel_rotation -= steps * delta

        self.on_user_input()
        direction = UP if steps > 0 else DOWN
        popup = self._shown_list_popup()
        for _step in range(abs(steps)):
            if popup is not None:
                popup.handle_navigation(DIRECTION_KEYS[direction])
            else:
                self.navigate(direction)

    # ------------------------------------------------------------------------------------------------------------------
    def on_mouse_right_click(self, _event) -> None:
        if self.joystick_block or self.virtual_keyboard.IsShown() or self._shown_list_popup() is not None:
            return
        self.on_user_input()
        self.open_menu()

    # ------------------------------------------------------------------------------------------------------------------
    # Create the button grid.  The tile buttons and name labels are kept in self.controlsButton and self.controlsText.
    # For each tile we also keep its label, its undimmed bitmap and (once needed) its dimmed bitmap, so that these
    # can be moved along with the page when it scrolls.
    def create_button_grid(self) -> wx.GridSizer:
        self.controlsButton: list[wx.BitmapButton | wx.StaticBitmap] = []
        self.controlsText: list[wx.StaticText] = []
        self._tile_labels: list[str] = []
        self._tile_bitmaps: list[wx.Bitmap] = []
        self._tile_dimmed: list[wx.Bitmap | None] = [None] * self.model.page_size
        self._tile_dimmed_level = self.brightness_level   # The brightness the dimmed bitmaps were made at
        sizer_grid = wx.GridSizer(rows=self.numVertical, cols=self.numHorizontal, vgap=4, hgap=14)

        for slot in range(self.model.page_size):
            rom_name, image = self.get_rom_image(slot)  # Draw the image
            self._tile_labels.append(rom_name)
            self._tile_bitmaps.append(image)

            button_sizer = wx.BoxSizer(wx.VERTICAL)

            # Create the bitmap image button for the ROM
            if USE_STATIC_BITMAP:
                button = wx.StaticBitmap(self.panel_rom_buttons,
                                         id=wx.ID_ANY,
                                         bitmap=image,
                                         style=wx.BORDER_NONE)
            else:
                button = wx.BitmapButton(self.panel_rom_buttons,
                                         id=wx.ID_ANY,
                                         bitmap=image,
                                         style=wx.BORDER_NONE)

            button.SetBackgroundColour(wx.BLACK)
            button.SetCanFocus(False)  # Don't allow a mouse click to set focus
            self.controlsButton.append(button)
            button_sizer.Add(button, proportion=0, flag=wx.EXPAND, border=0)

            # Create the ROM name text
            text = wx.StaticText(self.panel_rom_buttons,
                                 id=wx.ID_ANY,
                                 label=rom_name,
                                 size=wx.Size(self.imageScale_X, 15),
                                 style=wx.ALIGN_CENTER_HORIZONTAL)
            text.SetFont(self.global_font_normal_8)
            text.SetForegroundColour(wx.WHITE)  # Set text color
            text.SetBackgroundColour(wx.BLACK)
            text.SetCursor(self.my_cursor)  # Hide the mouse pointer
            self.controlsText.append(text)
            button_sizer.Add(wx.Size(self.imageScale_X, 3))  # Add a gap, so we can see the box around the button
            button_sizer.Add(text, proportion=0, flag=wx.ALIGN_CENTER, border=0)
            sizer_grid.Add(button_sizer)

        # Set the correct size for the media control
        if self.media_player_available:
            self.video_player.video_panel.SetSize(self.controlsButton[0].GetSize())

        # Make sure the ROM button has focus so that navigation works
        self.focus_current_tile()

        return sizer_grid

    # ------------------------------------------------------------------------------------------------------------------
    # Create the media control instance
    def create_media_control(self) -> bool:
        if self.video_disable:
            self.my_logger.info(_('Video playback disable selected in preferences'))  # Write to the log file
            return False
        if not self.preview_videos:
            self.my_logger.info(_('Video autoload is off - no tile preview videos'))  # Write to the log file
            return False

        try:
            self.my_logger.info(
                _('Trying to set up the video playback device'))  # Write to the log file
            self.video_player = Video(
                                      parent_panel=self.panel_rom_buttons,
                                      logger=self.my_logger,
                                      image_panel=None,
                                      video_caption_label=None,
                                      use_video_caption=False,
                                      video_path=None,
                                      horizontal_size=image_size_x,
                                      vertical_size=image_size_y
                                     )
            self.media_player_stop()  # Stop & Hide
            return True

        except Exception as e:
            self.my_logger.info(_('No media content player available on this system: {}').format(e))  # Write to the log file
            return False

    # ------------------------------------------------------------------------------------------------------------------
    # Update the ROM information panel
    def display_info(self, suppress_rectangle: bool = False):
        self.scroll_timer.Stop()  # Stop the auto-scrolling of the ROM info window

        if self.model.search:
            fav_text = _('Search: "{}"').format(self.model.search)
        else:
            fav_text = self.view_name(self.model.view)
        if self.model.category:
            fav_text += f' · {self.model.category}'
        if self.model.sort_applies and self.model.sort == SORT_MOST_RUNS:
            fav_text += f' · {_("Most runs")}'

        row = self.model.focused_row
        if row is not None:
            rom_runs = row[index_number_runs]
            rom_name = row[index_rom_name]
            rom_file_name = row[index_rom_file_name]
            system_file_name = row[index_system_program_file_name]
            short_name = row[index_system_short_name]
        else:
            rom_runs = rom_name = rom_file_name = system_file_name = short_name = ''

        # Set up the ROM stats panel data
        label = rom_name
        if system_file_name != '':
            label += f'-->{system_file_name}'
        self.panel_info.selected_rom.SetLabel(label)

        self.panel_info.rom_runs.SetLabel(rom_runs)
        if row is None:
            self.panel_info.favorite.SetLabel('')
        else:
            self.panel_info.favorite.SetLabel(_('Yes') if row[index_favorite] == '1' else _('No'))
        self.panel_info.index_rom.SetLabel(f'{self.model.size} ROMs')
        self.panel_info.view_mode.SetLabel(fav_text)

        # Set up the ROM information panel data
        output = self.get_rom_info(rom_file_name, system_file_name, short_name)
        self.panel_rom_info.controlRomInfo.SetValue(output)
        self.panel_rom_info.controlRomInfo.SetInsertionPoint(0)  # Move the scrollbar back to the top of the game info window

        # Start off with the scroll at the top
        self.info_scroll_position = 0
        self.panel_rom_info.Scroll(0, self.info_scroll_position)

        # Calculate the number of scroll steps for the ROM info window
        number_of_lines = self.panel_rom_info.controlRomInfo.GetNumberOfLines()
        num_pixel_lines = number_of_lines * INFO_LINE_HEIGHT
        self.scroll_size = (num_pixel_lines // self.scroll_steps) * 2

        # This hack is required as I have hidden the panel_rom_info scrolledpanel vertical scrollbar so apparently
        # that makes it unable to work out how to size everything inside it.
        self.panel_rom_info.SendSizeEvent()
        sizer = self.panel_rom_info.GetSizer()
        sizer.SetDimension(sizer.Position, sizer.MinSize)

        # If the number of lines displayed in the ROM info window exceeds what can be displayed on the screen
        # then enable the auto-scrolling.
        if number_of_lines > INFO_SCROLL_MIN_LINES:
            self.scroll_timer.Start(milliseconds=self.timer_delay)  # Start the scrolling timer for the ROM info

        if not suppress_rectangle:
            self.draw_rectangle(self.controlsButton[self.model.focused])  # Draw the rectangle around the selected ROM

    # ------------------------------------------------------------------------------------------------------------------
    # This function processes the timer events.
    def on_activity_timer(self, _event):
        # Stop the timer and open the screensaver
        self.inactivity_timer.Stop()  # Stop the inactivity timer
        if self.media_player_available:
            self.media_player_stop()
        if os.path.exists(self.foldersVideo) and self.foldersVideo != '.' and not self.video_disable:
            fullscreenplay.FullScreenVideoPlayer(self.foldersVideo,
                                                 'tileview',
                                                 self,
                                                 my_logger=self.my_logger,
                                                 rom_list=self.myList)

    def on_scroll_timer(self, _event):
        # A ROM info scroll timer event has been triggered.  Every time it is called it will scroll the ROM
        # information window down.  When it reaches the end it will wind back to the start.
        self.panel_rom_info.Scroll(0, self.info_scroll_position)  # Scroll the panel to the required position
        self.info_scroll_position = (self.info_scroll_position + 1) % self.scroll_size

    # ------------------------------------------------------------------------------------------------------------------
    # This function searches the history file for the game information.
    # It supports the older DAT file format and the newer XML file format.
    def get_rom_info(self, rom_file_name: str, system_file_name: str, short_name: str) -> str:
        return functions.get_rom_info(self.history_data, self.myList, rom_file_name,
                                      system_file_name, short_name, index_system_folder_name, 'history')

    # ------------------------------------------------------------------------------------------------------------------
    # The name shown for a view in the info panel and the menu
    @staticmethod
    def view_name(view: str) -> str:
        return {VIEW_EXISTS: _('Existing ROMs'),
                VIEW_FAVORITES: _('Favorite ROMs'),
                VIEW_WATCHLIST: _('Watchlist ROMs'),
                VIEW_RECENT: _('Recently played'),
                VIEW_MOST_PLAYED: _('Most played')}[view]

    # ------------------------------------------------------------------------------------------------------------------
    # Rebuild the ROMs list (view and / or a ROM Finder search), go back to the first ROM and refresh everything on
    # screen.
    def apply_filter(self, view: str, search: str = '') -> None:
        self.model.apply_filter(view, search=search)
        self.show_new_list()

    # ------------------------------------------------------------------------------------------------------------------
    # Show the model's list after it has been rebuilt (filter, sort or category change)
    def show_new_list(self) -> None:
        self.reload_tiles()
        self.single_click(-1)
        self.display_info()

    # ------------------------------------------------------------------------------------------------------------------
    # Process the mouse single click event
    # This is a fallback as I have to get the focus back to a known location if
    # for some reason the mouse is used in a mode like this where the mouse
    # is assumed to not exist.  All I do is give focus back to the tile panel.
    def single_click(self, event):

        # Explicitly set focus back to parent or another control
        self.panel_rom_buttons.SetFocus()
        if event != -1:
            event.Skip()

    # ------------------------------------------------------------------------------------------------------------------
    def on_key_timer(self, _event):
        self.timer_key.Stop()
        key_set = set(self.key_list)
        self.key_list = []

        # Look for the MENU key combination (ALT-1)
        if key_set == KEY_COMBO_ROM_MENU:
            self.open_menu()

    # ------------------------------------------------------------------------------------------------------------------
    # The menu gives every Tile View action, so a controller with just a stick and two buttons can reach them all
    def _menu_items(self) -> list[tuple[str, str]]:
        row = self.model.focused_row
        sort_names = {SORT_NAME: _('Name'), SORT_MOST_RUNS: _('Most runs')}
        items = []
        if row is not None:
            items.append((ACTION_PLAY, _('Play the selected ROM')))
            is_favorite = row[index_favorite] == '1'
            items.append((ACTION_FAVORITE, _('Remove from favorites') if is_favorite else _('Add to favorites')))
        items.append((ACTION_CYCLE_VIEW, _('View: {}').format(self.view_name(self.model.view))))
        if self.model.sort_applies:  # The played views have their own order
            items.append((ACTION_SORT, _('Sort order: {}').format(sort_names[self.model.sort])))
        items.append((ACTION_CATEGORY, _('Category: {}').format(self.model.category or _('All categories'))))
        items.append((ACTION_FINDER, _('Find a ROM')))
        if self.tile_dim:
            items.append((ACTION_BRIGHTNESS, _('Tile brightness: {}%').format(round(self.brightness_level * 100))))
        items.append((ACTION_EXIT, _('Exit Tile View')))
        return items

    # ------------------------------------------------------------------------------------------------------------------
    def open_menu(self) -> None:
        self.video_delay_timer.Stop()  # Don't start a video behind the menu
        self.rom_menu.set_items(self._menu_items(), '')
        self._centre_popup(self.rom_menu)
        self.rom_menu.Show()

    # ------------------------------------------------------------------------------------------------------------------
    # Close the menu or the category picker and carry on where we left off
    def close_list_popup(self, popup: 'ListPopup') -> None:
        popup.Hide()
        self.inactivity_timer_start()
        self.draw_rectangle(self.controlsButton[self.model.focused])  # Restarts the video delay timer

    # ------------------------------------------------------------------------------------------------------------------
    # A menu item was chosen.  Sort order and brightness stay in the menu (so they can be stepped through); the
    # others close it first.
    def _on_menu_selected(self, action: str) -> None:
        if action in (ACTION_SORT, ACTION_BRIGHTNESS):
            self.do_action(action)
            self.rom_menu.set_items(self._menu_items(), action)
            return
        self.close_list_popup(self.rom_menu)
        self.do_action(action)

    # ------------------------------------------------------------------------------------------------------------------
    # Function to decode key press events on the buttons
    def on_key_down(self, event):
        key_code = event.GetKeyCode()

        # If the virtual keyboard is open, route all navigation to it
        if self.virtual_keyboard.IsShown():
            self.inactivity_timer_start()
            if event.ControlDown() or event.AltDown():
                return  # Don't type letters for Ctrl / Alt key combinations
            consumed = self.virtual_keyboard.handle_navigation(key_code)
            if not consumed and key_code == wx.WXK_ESCAPE:
                self.close_finder()
            return

        # Likewise for the menu and the category picker
        popup = self._shown_list_popup()
        if popup is not None:
            self.inactivity_timer_start()
            consumed = popup.handle_navigation(key_code)
            if not consumed and key_code == wx.WXK_ESCAPE:
                self.close_list_popup(popup)
            return

        # Ignore keys still repeating from the game that has just ended
        if time.monotonic() < self._ignore_keys_until:
            return

        # Normal tile navigation below
        self.on_user_input()

        # ALT starts a key combination - collect keys until the combo timer runs down
        if self.key_list or key_code == wx.WXK_ALT:
            self.key_list.append(key_code)
            self.timer_key.Start(KEY_COMBO_TIMEOUT, wx.TIMER_ONE_SHOT)
            return

        action = KEY_ACTIONS.get(key_code)
        if action:
            self.do_action(action)
        elif self.letter_jump and ord('A') <= key_code <= ord('Z') and not event.HasAnyModifiers():
            self.jump_to_letter(chr(key_code))

    # ------------------------------------------------------------------------------------------------------------------
    # Carry out a navigation / command action from the keyboard or joystick
    def do_action(self, action: str) -> None:
        if action in MOVES:
            self.navigate(action)
        elif action == ACTION_PLAY:
            self.play_game()
        elif action == ACTION_CYCLE_VIEW:
            self.cycle_view_mode()
        elif action == ACTION_EXIT:
            self.on_close(-1)
        elif action == ACTION_FINDER:
            self.finder()
        elif action == ACTION_BRIGHTNESS and self.tile_dim:
            self.adjust_brightness()
        elif action == ACTION_FAVORITE:
            self.toggle_favorite()
        elif action == ACTION_SORT:
            self.cycle_sort()
        elif action == ACTION_CATEGORY:
            self.choose_category()
        elif action == ACTION_MENU:
            self.open_menu()

    # ------------------------------------------------------------------------------------------------------------------
    # The menu or category picker if one is open
    def _shown_list_popup(self) -> 'ListPopup | None':
        for popup in (self.rom_menu, self.category_picker):
            if popup.IsShown():
                return popup
        return None

    # ------------------------------------------------------------------------------------------------------------------
    # Change to the next sort order (name, most runs).  The played views have their own order, so it does nothing there.
    def cycle_sort(self) -> None:
        if not self.model.sort_applies:
            return
        self.model.cycle_sort()
        self.show_new_list()

    # ------------------------------------------------------------------------------------------------------------------
    # Open the category picker, listing the categories in the current view with how many ROMs each has
    def choose_category(self) -> None:
        counts = self.model.category_counts()
        total = sum(count for _category, count in counts)
        items = [('', f"{_('All categories')} ({total:,})")]
        items += [(category, f'{category or _("No category")} ({count:,})') for category, count in counts]
        self.video_delay_timer.Stop()  # Don't start a video behind the picker
        self.category_picker.set_items(items, self.model.category)
        self._centre_popup(self.category_picker)
        self.category_picker.Show()

    # ------------------------------------------------------------------------------------------------------------------
    def _on_category_selected(self, category: str) -> None:
        self.close_list_popup(self.category_picker)
        if category != self.model.category:
            self.model.apply_filter(self.model.view, self.model.search, category=category)
            self.show_new_list()

    # ------------------------------------------------------------------------------------------------------------------
    # Add the selected ROM to favorites, or remove it.  No confirmation is asked for - pressing again undoes it.
    # In the Favorites view a removed ROM stays on screen until the view changes, so the selection doesn't jump.
    def toggle_favorite(self) -> None:
        row = self.model.focused_row
        if row is None:
            return

        key = favorite_key(row)
        data_folder = functions.data_dir()
        favorites_path = os.path.join(data_folder, 'favorites.dat')
        try:
            if row[index_favorite] == '1':
                try:
                    functions.remove_dat_entry(favorites_path, key)
                except FileNotFoundError:
                    pass  # Nothing to remove
                # Show it as a watchlist ROM again if it is still on the watchlist (as the main window does)
                on_watchlist = functions.dat_file_contains(os.path.join(data_folder, 'watchlist.dat'), key)
                row[index_favorite] = '2' if on_watchlist else '0'
                message = _('ROM set {} removed from favorites').format(key)
            else:
                functions.add_dat_entry(favorites_path, key)
                row[index_favorite] = '1'
                message = _('ROM set {} added to favorites').format(key)
        except OSError:
            self.my_logger.error(_('ERROR: Unable to write to favorites.dat file'))  # Write to the log file
            return

        self.favorites_changed = True
        self.my_logger.info(message)  # Write to the log file
        self.display_info()

    # ------------------------------------------------------------------------------------------------------------------
    # Any user input stops a playing video and restarts the screensaver countdown
    def on_user_input(self) -> None:
        if self.media_player_available:
            self.media_player_stop()
        self.inactivity_timer_start()

    # ------------------------------------------------------------------------------------------------------------------
    # Helper function for the Virtual Keyboard used for ROM Finder
    # This sets the correct position for the virtual keyboard
    def _position_virtual_keyboard(self):
        self._centre_popup(self.virtual_keyboard)

    # ------------------------------------------------------------------------------------------------------------------
    # Centre a popup (Finder keyboard / category picker) over the tiles
    def _centre_popup(self, popup: wx.PopupWindow) -> None:
        tile_pos = self.panel_rom_buttons.GetScreenPosition()
        tile_size = self.panel_rom_buttons.GetSize()
        popup_size = popup.GetSize()
        x = tile_pos.x + (tile_size.width - popup_size.width) // 2
        y = tile_pos.y + (tile_size.height - popup_size.height) // 2
        popup.SetPosition(wx.Point(x, y))

    # ------------------------------------------------------------------------------------------------------------------
    # Helper function for the Virtual Keyboard used for ROM Finder
    # This selects the ROMs based on what was entered using the ROM Finder
    def _on_finder_enter(self, search_text):
        search_text = search_text.strip()

        # Nothing matches - leave the current list alone and keep the Finder open so the search can be changed
        if search_text and not self.model.matching(VIEW_EXISTS, search=search_text):
            self.virtual_keyboard.show_message(_('No ROMs match "{}"').format(search_text))
            return

        self.close_finder()
        self.panel_rom_buttons.Show()
        self.Layout()

        if search_text:
            self.apply_filter(VIEW_EXISTS, search=search_text)
        elif self.model.search:
            self.apply_filter(VIEW_EXISTS)  # An empty search clears the current one

    # ------------------------------------------------------------------------------------------------------------------
    # Show the Virtual Keyboard for the ROM Finder
    def finder(self) -> None:
        self.video_delay_timer.Stop()  # Don't start a video behind the keyboard
        self.virtual_keyboard.reset(self.model.search)  # Start from the current search so it can be refined
        self._position_virtual_keyboard()
        self.virtual_keyboard.Show()

    # ------------------------------------------------------------------------------------------------------------------
    # Hide the Virtual Keyboard and carry on where we left off
    def close_finder(self) -> None:
        self.virtual_keyboard.Hide()
        self.inactivity_timer_start()
        self.draw_rectangle(self.controlsButton[self.model.focused])  # Restarts the video delay timer

    # ------------------------------------------------------------------------------------------------------------------
    # Move the selected game (one step, a page, or to the start / end), scrolling the tiles if needed
    def navigate(self, direction: str) -> None:
        old_focus = self.model.focused
        old_start = self.model.start_index
        focus_moved, scrolled = self.model.move(direction)
        self._show_move(old_focus, old_start, focus_moved, scrolled)

    # ------------------------------------------------------------------------------------------------------------------
    # Jump to the next ROM whose name starts with a letter (A-Z keys, if enabled in preferences)
    def jump_to_letter(self, letter: str) -> None:
        index = self.model.find_next_letter(letter)
        if index is None:
            self.draw_rectangle(self.controlsButton[self.model.focused])  # Restart the video the key press stopped
            return
        old_focus = self.model.focused
        old_start = self.model.start_index
        focus_moved, scrolled = self.model.show_index(index)
        self._show_move(old_focus, old_start, focus_moved, scrolled)

    # ------------------------------------------------------------------------------------------------------------------
    # Update the tiles and information after the model's position has changed
    def _show_move(self, old_focus: int, old_start: int, focus_moved: bool, scrolled: bool) -> None:
        if scrolled:
            self.reload_tiles(row_delta=(self.model.start_index - old_start) // self.model.columns)
        elif focus_moved and self.tile_dim:
            self.show_tile(old_focus)
            self.show_tile(self.model.focused)

        if focus_moved or scrolled:
            self.display_info()
        else:
            # Nothing moved (e.g. at an edge) - just restart the video that the key press stopped
            self.draw_rectangle(self.controlsButton[self.model.focused])

    # ------------------------------------------------------------------------------------------------------------------
    # Show a tile's bitmap, dimmed unless it is the focused tile.  Dimming always works from the original bitmap so
    # repeatedly dimming / undimming a tile doesn't lose image quality, and the dimmed version is kept until the
    # tile's ROM or the brightness changes.
    def show_tile(self, slot: int) -> None:
        bitmap = self._tile_bitmaps[slot]
        if self.tile_dim and slot != self.model.focused and self.brightness_level < 1.0:
            if self._tile_dimmed_level != self.brightness_level:
                self._tile_dimmed = [None] * self.model.page_size  # Brightness changed - re-dim at the new level
                self._tile_dimmed_level = self.brightness_level
            if self._tile_dimmed[slot] is None:
                image = bitmap.ConvertToImage()
                self._tile_dimmed[slot] = image.AdjustChannels(1.0, 1.0, 1.0, self.brightness_level).ConvertToBitmap()
            bitmap = self._tile_dimmed[slot]

        button = self.controlsButton[slot]
        if USE_STATIC_BITMAP:
            button.SetBitmap(bitmap)
        else:
            button.SetBitmapLabel(bitmap)

    # ------------------------------------------------------------------------------------------------------------------
    def _show_all_tiles(self) -> None:
        self.Freeze()
        for slot in range(self.model.page_size):
            self.show_tile(slot)
        self.Thaw()

    # ------------------------------------------------------------------------------------------------------------------
    # Change to the next view (existing ROMs, favorites, watchlist, recently played, most played)
    def cycle_view_mode(self) -> None:
        self.model.cycle_view()
        self.show_new_list()

    # ------------------------------------------------------------------------------------------------------------------
    # Load the images and names for the tiles.
    # This is done when scrolling up / down (if we are at the end of the screen size) and when the ROM list changes.
    # When the page has scrolled by one row (row_delta = +1 down / -1 up) the tiles already loaded are moved along
    # and only the new row is loaded.
    def reload_tiles(self, row_delta: int = 0):
        page_size = self.model.page_size
        if row_delta in (1, -1):
            columns = self.model.columns
            self._tile_labels = shift_page(self._tile_labels, row_delta, columns)
            self._tile_bitmaps = shift_page(self._tile_bitmaps, row_delta, columns)
            self._tile_dimmed = shift_page(self._tile_dimmed, row_delta, columns)
        else:
            self._tile_labels = [None] * page_size
            self._tile_bitmaps = [None] * page_size
            self._tile_dimmed = [None] * page_size

        self.Freeze()
        for slot in range(page_size):
            if self._tile_bitmaps[slot] is None:
                self._tile_labels[slot], self._tile_bitmaps[slot] = self.get_rom_image(slot)  # Draw the game image
            self.show_tile(slot)
            text = self.controlsText[slot]
            if text.GetLabel() != self._tile_labels[slot]:
                text.SetLabel(self._tile_labels[slot])
        self.Thaw()

        self.schedule_preload()

    # ------------------------------------------------------------------------------------------------------------------
    # Once the user stops scrolling, quietly load the rows just below and above the page into the image cache so the
    # next scroll doesn't have to wait for the disk.  Images are loaded one per timer tick to keep the controls
    # responsive.
    def schedule_preload(self) -> None:
        model = self.model
        page_end = model.start_index + model.page_size
        below = range(page_end, page_end + model.columns)
        above = range(model.start_index - model.columns, model.start_index)
        self._preload_queue = [index for index in (*below, *above) if 0 <= index < model.size]
        if self._preload_queue:
            self.preload_timer.StartOnce(PRELOAD_DELAY)
        else:
            self.preload_timer.Stop()

    def on_preload_timer(self, _event) -> None:
        if not self._preload_queue:
            return
        self._get_tile_bitmap(self.model.filtered[self._preload_queue.pop(0)])
        if self._preload_queue:
            self.preload_timer.StartOnce(PRELOAD_STEP)

    # ------------------------------------------------------------------------------------------------------------------
    # Start the inactivity timer as long as there are no blocks in place.  A screensaver time of 0 disables it.
    def inactivity_timer_start(self):
        if not self.inactivity_timer_block and self.screensaver_minutes > 0:
            self.inactivity_timer.Start(self.screensaver_minutes * 1000 * 60)

    # ------------------------------------------------------------------------------------------------------------------
    # This function plays the selected ROM.
    def play_game(self) -> None:
        row = self.model.focused_row
        if row is None:
            return  # Blank tile

        if self.media_player_available:
            self.media_player_stop()

        rom_file_name = row[index_rom_file_name]
        rom_name = row[index_rom_name]
        system_file_name = row[index_system_program_file_name]

        self.my_logger.info(f'ROM {rom_file_name} started')  # Write to the log file

        # Get the folder that the mame.ini file resides in (Should be the same as the other MAME folders)
        folder_mame_ini = os.path.dirname(self.path_to_mame_ini_file)

        self.joystick_block = True  # Block the joystick events from being triggered when running a ROM
        self.inactivity_timer_block = True
        self.video_delay_timer.Stop()  # Don't start a preview video behind the game

        rungame.RunGame(self,
                        rom_file_name,
                        self.path_mame_exe,
                        'Tile View',
                        rom_name,
                        system_file_name,
                        row[index_system_short_name],
                        row[index_system_folder_name],
                        folder_mame_ini,
                        self.folder_mapping,
                        self.suppress_short_name)

        # Update the number of runs for the game
        if self.parent is not None:
            self.parent.update_number_runs(rom_file_name, rom_name, system_file_name, system_file_name != '',
                                           'tile view')

        self.my_logger.info(f'ROM {rom_file_name} ended')  # Write to the log file

        self.display_info(suppress_rectangle=True)  # Update the information bar (forces refresh of runs number)

        # Make it full screen with no title bars etc. - this is just a reset as some platforms don't let it go
        # back to being fullscreen after running a fullscreen game.
        self.ShowFullScreen(True, wx.FULLSCREEN_NOCAPTION)
        self.Refresh()
        wx.CallAfter(self.focus_current_tile)  # Make sure the ROM button has focus again
        self._ignore_keys_until = time.monotonic() + KEY_IGNORE_AFTER_GAME

    # ------------------------------------------------------------------------------------------------------------------
    # Set focus back to the ROM tiles
    def focus_current_tile(self):
        if self:  # The window may have been destroyed before a CallAfter runs
            self.controlsButton[self.model.focused].SetFocus()  # Make sure the ROM button has focus again

    # ------------------------------------------------------------------------------------------------------------------
    # Work out which direction the D-pad or analog stick is being pushed in (None if centred).  A D-pad diagonal
    # is ignored; for a diagonal on the stick the axis pushed furthest wins.
    def _joystick_direction(self) -> str | None:
        if self.joystick.HasPOV():
            direction = POV_DIRECTIONS.get(self.joystick.GetPOVPosition())
            if direction is not None:
                return direction

        x, y = self.joystick.GetPosition()
        x_range = max(1, self.joystickXMax - self.joystickXMin)
        y_range = max(1, self.joystickYMax - self.joystickYMin)
        x_threshold = x_range // 4
        y_threshold = y_range // 4

        horizontal = vertical = None
        if x < (self.joystickXMin + x_threshold):
            horizontal = LEFT
        elif x > (self.joystickXMax - x_threshold):
            horizontal = RIGHT
        if y < (self.joystickYMin + y_threshold):
            vertical = UP
        elif y > (self.joystickYMax - y_threshold):
            vertical = DOWN

        if horizontal and vertical:
            x_push = abs(x - (self.joystickXMin + self.joystickXMax) / 2) / x_range
            y_push = abs(y - (self.joystickYMin + self.joystickYMax) / 2) / y_range
            return horizontal if x_push > y_push else vertical
        return horizontal or vertical

    # ------------------------------------------------------------------------------------------------------------------
    # Process the joystick polling timer.  Reads the D-pad / stick and moves (with repeat while it is held).
    def on_joystick_pov(self, _event):
        if self.joystick_block or not self.joystick_enabled:
            self.hold_repeater.update(None, time.monotonic())  # Start afresh once unblocked
            return

        direction = self._joystick_direction()
        finder_open = self.virtual_keyboard.IsShown()
        # No speeding up in the Finder - a fast repeat makes it hard to stop on the right key
        if not self.hold_repeater.update(direction, time.monotonic(), accelerate=not finder_open):
            return

        self.on_user_input()

        if finder_open:
            self.virtual_keyboard.handle_navigation(DIRECTION_KEYS[direction])
        elif self._shown_list_popup() is not None:
            self._shown_list_popup().handle_navigation(DIRECTION_KEYS[direction])
        else:
            self.navigate(direction)

    # ------------------------------------------------------------------------------------------------------------------
    # This function processes joystick button events.
    # It will determine which joystick button has been pressed and will call the required function, essentially
    # mapping the joystick buttons to the keyboard.  Stick / D-pad directions are read on the polling timer
    # (on_joystick_pov) so that they repeat while held.
    def on_joystick(self, _event):
        if self.joystick_block or not self.joystick_enabled:
            return

        button_value = self.joystick.GetButtonState()
        if not button_value:
            return  # Button released, or the stick moved - don't treat it as user input here

        self.on_user_input()

        if self.virtual_keyboard.IsShown():
            # Button 1 = select current key, Button 8 = close keyboard
            if button_value == 1:
                self.virtual_keyboard.press_focused_key()
            elif button_value == 8:
                self.close_finder()
            return

        popup = self._shown_list_popup()
        if popup is not None:
            # Button 1 = choose the highlighted item, Button 4 (8) = close the menu / picker
            if button_value == 1:
                popup.handle_navigation(wx.WXK_RETURN)
            elif button_value == 8:
                self.close_list_popup(popup)
            return

        action = JOYSTICK_BUTTON_ACTIONS.get(button_value)
        if action:
            self.do_action(action)

    # ------------------------------------------------------------------------------------------------------------------
    # Get the ROM image and the tile label for a tile
    def get_rom_image(self, slot: int) -> tuple[str, wx.Bitmap]:
        row = self.model.row_at(slot)
        if row is None:
            # Return blank image and empty name if no valid ROM
            if self._blank_bitmap is None:
                self._blank_bitmap = wx.Bitmap(wx.Image(self.imageScale_X, self.imageScale_Y))  # blank (black) image
            return '', self._blank_bitmap

        # If it's a system file then the label also shows the program file name
        if row[index_system_program_file_name]:
            label = f'{row[index_rom_file_name]}-->{row[index_system_program_file_name]}'
        else:
            label = row[index_rom_name]

        return label, self._get_tile_bitmap(row)

    # ------------------------------------------------------------------------------------------------------------------
    # Get a ROM's tile image from the cache, loading it from disk if it isn't there
    def _get_tile_bitmap(self, row: list) -> wx.Bitmap:
        key = (row[index_rom_file_name], row[index_system_program_file_name])
        bitmap = self._bitmap_cache.get(key)
        if bitmap is None:
            bitmap = self._load_tile_bitmap(row)
            self._bitmap_cache.put(key, bitmap)
        return bitmap

    # ------------------------------------------------------------------------------------------------------------------
    # Load and scale a ROM's snapshot image, or the default image if it doesn't have one
    def _load_tile_bitmap(self, row: list) -> wx.Bitmap:
        rom_file_name = row[index_rom_file_name]
        system_file_name = row[index_system_program_file_name]
        short_name_local = row[index_system_short_name]

        # Get the program file name.  It will be overwritten later if there is a system program, but we have to do
        # this now to at least ensure that the file_name variable is set
        file_name = os.path.join(self.foldersSnap, f'{rom_file_name}.png')

        # Check to see if it's a system file name
        if system_file_name and os.path.isdir(os.path.join(self.foldersSnap, rom_file_name)):
            # Try to get the short name version first.  If that fails, get the long name version
            # Strip off the . and file name suffix (e.g. .rom), and add the '.png' image suffix
            program_name = f'{short_name_local}.png'
            # Build the file name for the snapshot image using the full path
            file_name = os.path.join(self.foldersSnap, rom_file_name, program_name)
            if not os.path.exists(file_name):
                # Strip off the . and file name suffix (e.g. .rom), and add the '.png' image suffix
                program_name = f'{os.path.splitext(system_file_name)[0]}.png'
                # Build the file name for the snapshot image using the full path
                file_name = os.path.join(self.foldersSnap, rom_file_name, program_name)

        def load_image(path: str) -> wx.Bitmap:
            """Try to load image, return default on failure."""
            try:
                image = functions.load_and_scale_bitmap(path, self.imageScale_X, self.imageScale_Y)
                if image and image.IsOk() and image != wx.NullBitmap:
                    return image
            except (FileNotFoundError, PermissionError, IOError):
                functions.dev_message_log(
                    self.development,
                    self.my_logger.info,
                    f'TileView File error loading {path}'
                )

            # Fallback mechanism if the primary load failed or returned a bad bitmap.  Lots of ROMs have no
            # snapshot, so the default image is only loaded once and shared.
            if self._default_bitmap is None:
                fallback_path = os.path.join(self.path_to_me, 'images', 'default.gif')
                self._default_bitmap = functions.load_and_scale_bitmap(fallback_path,
                                                                       self.imageScale_X,
                                                                       self.imageScale_Y)
            return self._default_bitmap

        _null_target = wx.LogNull()  # Prevent a crash with malformed png files in windowsXP
        image = load_image(file_name)
        del _null_target

        return image

    # ------------------------------------------------------------------------------------------------------------------
    # Handle the close event and ensure the parent window is given back control
    def on_close(self, _event):

        # Stop the video playback timer
        self.video_delay_timer.Stop()

        # Remove the on_paint binding to stop a runtime error when exiting due to the on_paint event triggering when
        # the object has been destroyed
        self.panel_rom_buttons.Unbind(event=wx.EVT_PAINT, handler=self.on_paint)

        # Stop the media player if it's running
        if self.media_player_available:
            self.video_player.cleanup()  # This stops and correctly cleans up the video/audio player threads

        # Save the value of the tile brightness, and where we were if that is to be remembered
        settings = [('preferences', 'brightness', str(self.brightness_level))]
        if self.remember_position:
            settings += self._position_settings()
        iniFile.set_ini_file_variables(settings)

        if self.GetParent() is not None:  # Following will only be called if this window is running as a child
            message = _('Switched back to standard view')
            self.GetParent().statusbar_panel.set_status(message)
            self.my_logger.info(message)  # Write to the log file
            if self.favorites_changed:
                self.GetParent().on_tileview_favorites_changed()  # Refresh its ROM list and save the database
            self.GetParent().Enable()
            self.GetParent().list.SetFocus()
            self.GetParent().tileview_running = False  # Re-enable the main windows joystick events
        self.joystick_block = True  # Prevent the event timer from trying to do anything with the joystick
        if self.joystick is not None:
            self.joystick_polling_timer.Stop()
            self.joystick.Destroy()  # Delete the joystick instance to kill its thread
        # Stop the rest of the wx.TIMER events
        self.timer_key.Stop()
        self.scroll_timer.Stop()
        self.inactivity_timer.Stop()
        self.preload_timer.Stop()
        if self.mouse_enabled:
            self.pointer_timer.Stop()
        self.Destroy()

    # ------------------------------------------------------------------------------------------------------------------
    # The view (All / Favorites), sort, category and selected ROM to save in pfemame.ini.  A Finder search isn't
    # saved.  (Some ROM names contain '%' - set_ini_file_variables escapes it for the ini file reader.)
    def _position_settings(self) -> list[tuple[str, str, str]]:
        row = self.model.focused_row
        values = {
            'tileviewview': self.model.view,
            'tileviewsort': self.model.sort,
            'tileviewcategory': self.model.category,
            'tileviewlastrom': favorite_key(row) if row is not None else '',
        }
        return [('preferences', name, value) for name, value in values.items()]

    # ------------------------------------------------------------------------------------------------------------------
    # Put Tile View back where it was last time: view, sort, category and the selected ROM.  Anything missing or no
    # longer valid falls back to the normal start (the main window's view, by name, all categories, first ROM).
    def _restore_position(self, view_filter: str) -> None:
        def saved(name: str) -> str:
            return iniFile.read_ini_file('preferences', name)

        view = tile_view_key(saved('tileviewview') or view_filter)  # Older versions saved 'All' - now Exists
        sort = saved('tileviewsort')
        self.model.sort = sort if sort in SORT_ORDERS else SORT_NAME
        category = saved('tileviewcategory')
        if category and not self.model.matching(view, category=category):
            category = ''  # The category has no ROMs in this view any more
        self.model.apply_filter(view, category=category)

        index = self.model.find_key(saved('tileviewlastrom'))
        if index is not None:
            self.model.show_index(index)

    # ------------------------------------------------------------------------------------------------------------------
    # Catch-all timer shutdown.  A timer left running past its owner's destruction delivers
    # its queued WM_TIMER to a freed window, which corrupts the heap as the app shuts down.
    # The normal close path stops most of these already; this covers every other exit route.
    def on_destroy(self, event):
        for timer_name in ('timer_key', 'scroll_timer', 'video_delay_timer',
                           'inactivity_timer', 'joystick_polling_timer', 'preload_timer', 'pointer_timer'):
            timer = getattr(self, timer_name, None)
            if timer is not None and timer.IsRunning():
                timer.Stop()
        event.Skip()

    # ------------------------------------------------------------------------------------------------------------------
    # The video playback timer has run down so now try to play the video
    def on_video_playback(self, _event):
        self.video_delay_timer.Stop()
        if not self.media_player_available or self.inactivity_timer_block:  # No preview video behind a running game
            return

        self.video_player.video_panel.SetPosition(self.position)

        row = self.model.focused_row
        if (row is None
                or self.foldersVideo in {'.', ''}
                or not os.path.isdir(self.foldersVideo)):
            return

        self.media_player_stop()

        file_match = find_video(self.foldersVideo, row)
        if file_match is None:
            return

        self.Freeze()
        try:
            if self.system != 'mac':
                self.button.Hide()
            self.video_player.set_video_path(file_match)
            self.video_player.play()
            self.video_player.video_panel.Raise()
            self.video_player.video_panel.Show()
        except wx.wxAssertionError:
            self.media_player_available = False
        finally:
            self.Thaw()

    # ------------------------------------------------------------------------------------------------------------------
    # Set the RECT location for the selected ROM highlight box and start video playback
    def draw_rectangle(self, button) -> None:
        position = button.GetPosition()
        size = button.GetSize()

        # Only redraw the area of the old glow (to erase it) and the new one, rather than the whole window
        old_box = self.box_parameters
        # Store base coords — the glow layers are computed in on_paint
        self.box_parameters = [position.x, position.y, size.width, size.height]
        for box in (old_box, self.box_parameters):
            if box:
                x, y, w, h = box
                self.panel_rom_buttons.RefreshRect(wx.Rect(x - GLOW_MARGIN,
                                                           y - GLOW_MARGIN,
                                                           w + GLOW_MARGIN * 2 + 2,
                                                           h + GLOW_MARGIN * 2 + 2))

        # Setup the variables for the video playback
        self.button = button
        self.position = position
        self.video_delay_timer.Start(VIDEO_PLAYBACK_DELAY)  # Start the playback timer

    # ------------------------------------------------------------------------------------------------------------------
    # Paint event to draw the selected ROM highlight box
    def on_paint(self, _event=None) -> None:
        # The paint DC must always be created, even if nothing is drawn, otherwise Windows keeps sending paint events
        dc = wx.PaintDC(self.panel_rom_buttons)
        if not self.box_parameters:
            return

        x, y, w, h = self.box_parameters

        # Use GCDC for alpha support — falls back gracefully if unavailable
        try:
            gc = wx.GCDC(dc)
        except Exception:
            gc = dc

        r, g, b = GLOW_COLOR

        for expand, alpha in GLOW_LAYERS:
            gc.SetBrush(wx.TRANSPARENT_BRUSH)
            pen_color = wx.Colour(r, g, b, alpha)
            # Thicker pen for the outer softer rings, thin for the inner solid one
            pen_width = max(1, expand // 2 + 1)
            gc.SetPen(wx.Pen(pen_color, pen_width))
            try:
                gc.DrawRectangle(
                    x - expand,
                    y - expand,
                    w + expand * 2 + 2,
                    h + expand * 2 + 2
                )
            except Exception:
                pass

    # ------------------------------------------------------------------------------------------------------------------
    # Stop the medial player and hide the video panel
    def media_player_stop(self):
        self.video_player.stop()
        self.video_player.video_panel.Hide()

        # Show the button that was hidden
        if hasattr(self, 'controlsButton'):
            self.controlsButton[self.model.focused].Show()

    # ------------------------------------------------------------------------------------------------------------------
    # Adjust the brightness level of unselected games tiles
    def adjust_brightness(self):
        self.brightness_level = 0.1 if self.brightness_level >= 1.0 else round(self.brightness_level + 0.1, 1)
        self._show_all_tiles()


# ----------------------------------------------------------------------------------------------------------------------
# A scrolling list popup for Tile View, chosen from with the arrows / joystick.  Used for the category picker and the
# menu.  Items are (value, label) pairs; choosing one calls on_select_callback(value).
class ListPopup(wx.PopupWindow):

    ROW_WIDTH = 360
    ROW_HEIGHT = 26
    PANEL_PAD = 20
    BACKGROUND = wx.Colour(20, 20, 20)
    HIGHLIGHT = wx.Colour(0, 200, 255)

    def __init__(self, parent, title: str, on_select_callback, global_font_normal_8: wx.Font, visible_rows: int = 14):
        super().__init__(parent, flags=wx.BORDER_SIMPLE)
        self.on_select_callback = on_select_callback
        self.VISIBLE_ROWS = visible_rows
        self.items: list[tuple[str, str]] = []  # (value, label)
        self.focused = 0
        self.top = 0  # First item shown

        self.SetBackgroundColour(self.BACKGROUND)

        text_title = wx.StaticText(self, label=title)
        text_title.SetFont(global_font_normal_8)
        text_title.SetForegroundColour(self.HIGHLIGHT)
        text_title.SetBackgroundColour(self.BACKGROUND)

        main_sizer = wx.BoxSizer(wx.VERTICAL)
        main_sizer.AddSpacer(self.PANEL_PAD)
        main_sizer.Add(text_title, flag=wx.LEFT | wx.RIGHT, border=self.PANEL_PAD)
        main_sizer.AddSpacer(10)

        self._rows: list[wx.StaticText] = []
        for _row in range(self.VISIBLE_ROWS):
            text = wx.StaticText(self, label='', size=wx.Size(self.ROW_WIDTH, self.ROW_HEIGHT),
                                 style=wx.ALIGN_LEFT | wx.ST_NO_AUTORESIZE | wx.ST_ELLIPSIZE_END)
            text.SetFont(global_font_normal_8)
            main_sizer.Add(text, flag=wx.LEFT | wx.RIGHT, border=self.PANEL_PAD)
            self._rows.append(text)

        main_sizer.AddSpacer(self.PANEL_PAD)
        self.SetSizerAndFit(main_sizer)

    # ------------------------------------------------------------------------------------------------------------------
    # Mouse support (Tile View's preference): click an item to choose it, the wheel scrolls the list
    def enable_mouse(self) -> None:
        for row_number, text in enumerate(self._rows):
            text.Bind(wx.EVT_LEFT_DOWN, lambda _event, row_number=row_number: self._on_row_click(row_number))
        for window in (self, *self._rows):
            window.Bind(wx.EVT_MOUSEWHEEL, self._on_wheel)

    def _on_row_click(self, row_number: int) -> None:
        index = self.top + row_number
        if index < len(self.items):
            self.focused = index
            self._refresh_rows()
            self.handle_navigation(wx.WXK_RETURN)

    def _on_wheel(self, event) -> None:
        self.handle_navigation(wx.WXK_UP if event.GetWheelRotation() > 0 else wx.WXK_DOWN)

    # ------------------------------------------------------------------------------------------------------------------
    # Fill the list and highlight the item with the selected value (or the first item)
    def set_items(self, items: list[tuple[str, str]], selected_value: str) -> None:
        self.items = items
        self.focused = next((number for number, (value, _label) in enumerate(items)
                             if value == selected_value), 0)
        self.top = 0
        self._refresh_rows()

    # ------------------------------------------------------------------------------------------------------------------
    def _refresh_rows(self) -> None:
        # Scroll so the highlighted item is visible
        if self.focused < self.top:
            self.top = self.focused
        elif self.focused >= self.top + self.VISIBLE_ROWS:
            self.top = self.focused - self.VISIBLE_ROWS + 1

        for row_number, text in enumerate(self._rows):
            index = self.top + row_number
            label = f'  {self.items[index][1]}' if index < len(self.items) else ''
            if text.GetLabel() != label:
                text.SetLabel(label)
            highlighted = index == self.focused
            text.SetBackgroundColour(self.HIGHLIGHT if highlighted else self.BACKGROUND)
            text.SetForegroundColour(wx.BLACK if highlighted else wx.WHITE)
            text.Refresh()

    # ------------------------------------------------------------------------------------------------------------------
    def handle_navigation(self, key_code) -> bool:
        count = len(self.items)
        if not count:
            return False

        if key_code == wx.WXK_UP:
            self.focused = (self.focused - 1) % count
        elif key_code == wx.WXK_DOWN:
            self.focused = (self.focused + 1) % count
        elif key_code in (wx.WXK_PAGEUP, wx.WXK_NUMPAD_PAGEUP, wx.WXK_LEFT):
            self.focused = max(0, self.focused - self.VISIBLE_ROWS)
        elif key_code in (wx.WXK_PAGEDOWN, wx.WXK_NUMPAD_PAGEDOWN, wx.WXK_RIGHT):
            self.focused = min(count - 1, self.focused + self.VISIBLE_ROWS)
        elif key_code in (wx.WXK_HOME, wx.WXK_NUMPAD_HOME):
            self.focused = 0
        elif key_code in (wx.WXK_END, wx.WXK_NUMPAD_END):
            self.focused = count - 1
        elif key_code in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER, ord('1')):
            self.on_select_callback(self.items[self.focused][0])
            return True
        else:
            return False  # Not handled here (e.g. ESCAPE closes the popup)

        self._refresh_rows()
        return True


# ----------------------------------------------------------------------------------------------------------------------
# Virtual keyboard panel for the ROM finder
class VirtualKeyboard(wx.PopupWindow):

    KEYS = [
        ['0', '1', '2', '3', '4', '5', '6', '7', '8', '9'],
        ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J'],
        ['K', 'L', 'M', 'N', 'O', 'P', 'Q', 'R', 'S', 'T'],
        ['U', 'V', 'W', 'X', 'Y', 'Z', 'SPC', 'BCK', 'CLR', 'ENT'],
    ]

    # Physical keys that type straight into the search.  The 1 key is left out because it presses the highlighted
    # on-screen key (it is button 1 on arcade control panels) - 1 can still be typed with the on-screen keys.
    TYPED_KEYS = {ord(char): char for char in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ023456789'}
    TYPED_KEYS.update({wx.WXK_NUMPAD0 + number: str(number) for number in range(10)})
    TYPED_KEYS.update({wx.WXK_SPACE: 'SPC',
                       wx.WXK_BACK: 'BCK',
                       wx.WXK_DELETE: 'CLR',
                       wx.WXK_RETURN: 'ENT',          # Enter runs the search
                       wx.WXK_NUMPAD_ENTER: 'ENT'})

    KEY_W = 44
    KEY_H = 44
    KEY_GAP = 6
    PANEL_PAD = 20

    def __init__(self, parent, on_enter_callback, global_font_normal_8: wx.Font):
        super().__init__(parent, flags=wx.BORDER_SIMPLE)
        self.on_enter_callback = on_enter_callback
        self.search_text = ''
        self.focused_row = 0
        self.focused_col = 0
        self._buttons = []

        self.SetBackgroundColour(wx.Colour(20, 20, 20))

        cols = len(self.KEYS[0])
        rows = len(self.KEYS)

        # Title display
        text_title = wx.StaticText(self, label=_('ROM Finder'))
        text_title.SetFont(global_font_normal_8)
        text_title.SetForegroundColour(wx.Colour(0, 200, 255))
        text_title.SetBackgroundColour(wx.Colour(20, 20, 20))

        # Search text display
        self.text_display = wx.StaticText(
            self, label='...',
            size=wx.Size(cols * self.KEY_W + (cols - 1) * self.KEY_GAP, 30),
            style=wx.ALIGN_LEFT | wx.ST_NO_AUTORESIZE
        )
        self.text_display.SetFont(global_font_normal_8)
        self.text_display.SetForegroundColour(wx.Colour(0, 200, 255))
        self.text_display.SetBackgroundColour(wx.Colour(20, 20, 20))

        # Build key buttons
        main_sizer = wx.BoxSizer(wx.VERTICAL)
        main_sizer.AddSpacer(self.PANEL_PAD)
        main_sizer.Add(text_title, flag=wx.LEFT | wx.RIGHT, border=self.PANEL_PAD)
        main_sizer.AddSpacer(self.PANEL_PAD)
        main_sizer.Add(self.text_display, flag=wx.LEFT | wx.RIGHT, border=self.PANEL_PAD)
        main_sizer.AddSpacer(10)

        grid_sizer = wx.FlexGridSizer(rows=rows, cols=cols,
                                      vgap=self.KEY_GAP, hgap=self.KEY_GAP)

        for r, row in enumerate(self.KEYS):
            btn_row = []
            for c, key in enumerate(row):
                btn = wx.Button(self, label=key,
                                size=wx.Size(self.KEY_W, self.KEY_H),
                                style=wx.BORDER_NONE)
                btn.SetFont(global_font_normal_8)
                btn.SetForegroundColour(wx.WHITE)
                btn.SetBackgroundColour(wx.Colour(50, 50, 60))
                btn.SetCanFocus(False)
                btn.Bind(wx.EVT_BUTTON, lambda evt, k=key: self._on_key_press(k))
                grid_sizer.Add(btn)
                btn_row.append(btn)
            self._buttons.append(btn_row)

        main_sizer.Add(grid_sizer, flag=wx.LEFT | wx.RIGHT | wx.BOTTOM, border=self.PANEL_PAD)
        self.SetSizerAndFit(main_sizer)

        self._highlight_focused()

    # ------------------------------------------------------------------------------------------------------------------
    def _highlight_focused(self):
        for r, row in enumerate(self._buttons):
            for c, btn in enumerate(row):
                if r == self.focused_row and c == self.focused_col:
                    btn.SetBackgroundColour(wx.Colour(0, 200, 255))
                    btn.SetForegroundColour(wx.Colour(0, 0, 0))
                else:
                    btn.SetBackgroundColour(wx.Colour(50, 50, 60))
                    btn.SetForegroundColour(wx.WHITE)
                btn.Refresh()

    # ------------------------------------------------------------------------------------------------------------------
    def _on_key_press(self, key):
        if key == 'ENT':
            self.on_enter_callback(self.search_text)
            return  # The callback may have shown a message - leave it on screen
        elif key == 'BCK':
            self.search_text = self.search_text[:-1]
        elif key == 'CLR':
            self.search_text = ''
        elif key == 'SPC':
            self.search_text += ' '
        else:
            self.search_text += key
        self._update_display()

    # ------------------------------------------------------------------------------------------------------------------
    def _update_display(self):
        self.text_display.SetLabel(self.search_text if self.search_text else '...')

    # ------------------------------------------------------------------------------------------------------------------
    def handle_navigation(self, key_code) -> bool:
        rows = len(self.KEYS)
        cols = len(self.KEYS[0])

        if key_code == wx.WXK_LEFT:
            self.focused_col = (self.focused_col - 1) % cols
        elif key_code == wx.WXK_RIGHT:
            self.focused_col = (self.focused_col + 1) % cols
        elif key_code == wx.WXK_UP:
            self.focused_row = (self.focused_row - 1) % rows
        elif key_code == wx.WXK_DOWN:
            self.focused_row = (self.focused_row + 1) % rows
        elif key_code == ord('1'):
            self.press_focused_key()  # Button 1 on arcade control panels
        elif key_code in self.TYPED_KEYS:
            self._on_key_press(self.TYPED_KEYS[key_code])
        else:
            return False  # Not handled here (e.g. ESCAPE closes the keyboard)

        self._highlight_focused()
        return True

    # ------------------------------------------------------------------------------------------------------------------
    # Press the highlighted on-screen key (key 1 or joystick button 1)
    def press_focused_key(self) -> None:
        self._on_key_press(self.KEYS[self.focused_row][self.focused_col])

    # ------------------------------------------------------------------------------------------------------------------
    # Show a message in place of the search text until the next key is pressed
    def show_message(self, message: str) -> None:
        self.text_display.SetLabel(message)

    # ------------------------------------------------------------------------------------------------------------------
    def reset(self, search_text: str = ''):
        self.search_text = search_text
        self.focused_row = 0
        self.focused_col = 0
        self._update_display()
        self._highlight_focused()

# ----------------------------------------------------------------------------------------------------------------------
# This is the class for the logo panel
class LogoPanel(wx.Panel):
    def __init__(self,
                 parent: wx.Panel,
                 version: str,
                 mame_version: str,
                 path_to_me_local: str,
                 my_cursor,
                 copyright_local: str,
                 global_font_normal: wx.Font):
        wx.Panel.__init__(self, parent)

        # Get the MAME logo image
        img = wx.Image(os.path.join(path_to_me_local, 'images', 'MAMELogo.png'), wx.BITMAP_TYPE_ANY).ConvertToBitmap()
        image = wx.StaticBitmap(self, bitmap=img)
        image.SetCursor(my_cursor)  # Hide the mouse pointer

        text_logo = wx.StaticText(self,
                                  wx.ID_ANY,
                                  f'pfeMAME {version}\n'
                                  f'{copyright_local}\n'
                                  f'MAME Version: {mame_version}',
                                  size=wx.Size(info_panel_width, 60),
                                  style=wx.ALIGN_LEFT | wx.EXPAND
                                  )
        text_logo.SetFont(global_font_normal)
        text_logo.SetForegroundColour(wx.Colour('#5ABAEC'))  # Set text color
        text_logo.SetCursor(my_cursor)  # Hide the mouse pointer

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(wx.Size(10, 10), proportion=0, flag=wx.EXPAND)
        sizer.Add(image, proportion=0, flag=0)
        sizer.Add(wx.Size(10, 10), proportion=0, flag=wx.EXPAND)
        sizer.Add(text_logo, proportion=0, flag=wx.EXPAND)
        self.SetSizer(sizer)


# ----------------------------------------------------------------------------------------------------------------------
# This is the class for the information panel
class InfoPanel(wx.Panel):
    def __init__(self, parent: wx.Panel, my_cursor, global_font_normal_8: wx.Font):
        super().__init__(parent)

        def set_attributes(text_description, text_value):
            for ctrl, color in [(text_description, 'white'), (text_value, 'green')]:
                if ctrl:
                    ctrl.SetFont(global_font_normal_8)
                    ctrl.SetForegroundColour(color)
                    ctrl.SetCursor(my_cursor)

        def create_label_value_pair(label_text: str) -> tuple[wx.StaticText, wx.StaticText]:
            label = wx.StaticText(self, label=label_text, size=wx.Size(info_panel_width, 15), style=wx.ALIGN_LEFT)
            value = wx.StaticText(self, label='', size=wx.Size(info_panel_width, 15), style=wx.ALIGN_LEFT)
            set_attributes(label, value)
            return label, value

        # Instruction block
        instructions = (_('NAVIGATION:\n'
                          '  LEFT = Move left\n'
                          '  RIGHT = Move right\n'
                          '  UP = Move up\n'
                          '  DOWN = Move down\n'
                          '  PGUP / PGDN = Move a page\n'
                          '  HOME / END = First / last ROM\n'
                          'ACTIONS:\n'
                          '  L-CTRL(Joy-2) = Change view mode\n'
                          '  ALT-1 (Joy-4) = Menu\n'
                          '  1 / ENTER (Joy-1) = Start the selected ROM\n'
                          '  2 / ESC = Exit Tile View\n'
                          '  3 (Joy-3) = Add / remove favorite\n'
                          '  4 (Joy-5) = Change the sort order\n'
                          '  7 (Joy-6) = Choose a category\n'
                          '  5 = Adjust tile brightness\n'
                          '  6 = Bring up the Finder'))

        text_instructions = wx.StaticText(self, label=instructions, size=wx.Size(info_panel_width, -1), style=wx.ALIGN_LEFT | wx.EXPAND)
        set_attributes(None, text_instructions)

        # Info fields
        selected_rom_lbl, self.selected_rom = create_label_value_pair(_('Selected ROM:'))
        rom_runs_lbl, self.rom_runs = create_label_value_pair(_('Number of runs:'))
        favorite_lbl, self.favorite = create_label_value_pair(_('Favorite:'))
        index_rom_lbl, self.index_rom = create_label_value_pair(_('Available in this view:'))
        view_mode_lbl, self.view_mode = create_label_value_pair(_('View mode:'))

        # Layout
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.AddSpacer(10)
        sizer.Add(text_instructions, flag=wx.EXPAND)
        sizer.AddSpacer(30)

        for label, value in [(selected_rom_lbl, self.selected_rom),
                             (rom_runs_lbl, self.rom_runs),
                             (favorite_lbl, self.favorite),
                             (index_rom_lbl, self.index_rom),
                             (view_mode_lbl, self.view_mode)]:
            sizer.Add(label)
            sizer.Add(value, flag=wx.EXPAND)
            sizer.AddSpacer(5)

        sizer.AddSpacer(30)
        self.SetSizer(sizer)


# ----------------------------------------------------------------------------------------------------------------------
# This is the class for the ROM information panel
class RomInfoPanel(wx.lib.scrolledpanel.ScrolledPanel):
    def __init__(self, parent: wx.Panel, global_font_normal_8: wx.Font):
        super().__init__(parent, size=wx.Size(info_panel_width, -1))

        ctrl = wx.richtext.RichTextCtrl(
                                  self,
                                        value=_('ROM Information not available'),
                                        size=wx.Size(info_panel_width, 10000),
                                        style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_AUTO_URL | wx.TE_RICH | wx.NO_BORDER | wx.EXPAND
                                    )
        ctrl.SetFont(global_font_normal_8)
        ctrl.SetBackgroundColour(wx.BLACK)
        ctrl.BeginTextColour(wx.WHITE)
        ctrl.EnableVerticalScrollbar(False)

        self.controlRomInfo = ctrl

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(ctrl, proportion=1, flag=wx.EXPAND)
        self.SetSizer(sizer)
        self.SetupScrolling()  # Initialize scrolling for wx.lib.scrolledpanel


if __name__ == '__main__':
    app = wx.App()
    path_to_me = functions.path_to_me()  # Get the absolute path to me
    development = True

    # Set up logging if running TileView directly
    logger = functions.setup_logging(path_to_me)

    _ = functions.set_up_language()  # Set of the application language

    # Import the ROMs database
    import shelve

    try:
        with shelve.open(os.path.join(functions.data_dir(), 'mylist.db')) as mylist_db:
            mylist = mylist_db.get('mylist', [])
    except Exception:
        print('ERROR:  mylist.db probably doesnt exist')
        mylist = []

    TileView(mylist,
             logger,
             version='ver abc',
             mame_version='mamever 123',
             video_disable=False,
             copy_right='(C) 2014-2021',
             view_filter='All',
             development=development)
    app.MainLoop()
