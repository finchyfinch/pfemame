#!/usr/bin/env python3

# ----------------------------------------------------------------------------------------------------------------------
# functions.py

"""
This is a generic library of functions that could be used in any application
"""

# Import python & wxPython modules
import wx
import wx.adv
import wx.lib.buttons
import os
import sys
import subprocess
import time
import html
import re
import shutil
import logging
import logging.handlers
import gettext
import locale
import platform
from collections import namedtuple
from functools import lru_cache
from pubsub import pub

try:
    from PIL import Image
except ModuleNotFoundError:
    print('ERROR!! - You need to install pillow.  Use pip install pillow, '
          'or pip3 install pillow if required')
    sys.exit(1)


# Import my own modules
import iniFile
import app_paths
import emulator_config
import global_defaults as gd

# --------------------------------------------------------------------------------------------------------------
# Set up the application language
def set_up_language():
    """
    This sets up the language helper for the module that it is called from.

    :return: gettext translation function
    """
    try:
        language_preference = iniFile.read_ini_file('preferences', 'language', 'english')
    except FileNotFoundError:
        language_preference = 'english'

    language = language_translation(language_preference)
    language.install()
    return language.gettext


def language_translation(language_key: str) -> gettext.NullTranslations:
    """The gettext translation for a language as pfemame.ini stores it ('german' ...), English if unknown."""
    code = gd.get_language(language_key).code
    return gettext.translation('base', localedir='locales', fallback=True, languages=[code])



# ------------------------------------------------------------------------------------------------------------------
# Helper function for error message dialogs
def show_error_dialog(parent, message: str, title: str) -> None:
    """
    Display an error message dialog window with a single OK button
    :param parent: The caller (usually self)
    :param message: The message to display
    :param title: The title to show
    :return: None
    """
    _dlg = wx.MessageDialog(parent, message, title, wx.OK | wx.ICON_ERROR)
    _dlg.ShowModal()
    _dlg.Destroy()


# ------------------------------------------------------------------------------------------------------------------
# Helper function for information message dialogs
def show_information_dialog(parent, message: str, title: str) -> None:
    """
        Display an information message dialog window with a single OK button
        :param parent: The caller (usually self)
        :param message: The message to display
        :param title: The title to show
        :return: None
        """
    _dlg = wx.MessageDialog(parent, message, title, wx.OK | wx.ICON_INFORMATION)
    _dlg.ShowModal()
    _dlg.Destroy()


# ------------------------------------------------------------------------------------------------------------------
def show_popup_menu(window: wx.Window, menu: wx.Menu) -> None:
    """
    Show a popup menu without freezing a playing video, then destroy the menu.

    Video frames reach the screen through wx.CallAfter.  On Windows, PopupMenu() runs the system's modal menu loop,
    which only lets wx process its CallAfter queue after a burst of messages (such as mouse moves), so the video froze
    whenever the pointer rested on a menu item.  Timer messages are still dispatched inside that loop, so a short
    timer is used to keep the queue moving while the menu is open.
    """
    def pump_pending_events(_event) -> None:
        wx.GetApp().ProcessPendingEvents()

    pump_timer = wx.Timer(window)
    window.Bind(wx.EVT_TIMER, pump_pending_events, pump_timer)
    pump_timer.Start(10)
    try:
        window.PopupMenu(menu)
    finally:
        pump_timer.Stop()
        window.Unbind(wx.EVT_TIMER, source=pump_timer, handler=pump_pending_events)
        menu.Destroy()


# ------------------------------------------------------------------------------------------------------------------
# Load the categories file
def load_categories_file(_path_to_me: str) -> tuple[list[str], bool, str]:
    """
    Load the categories file

    :param _path_to_me: Path to the categores file
    :return: List of categories, Boolean True if no categories, Message for logging
    """
    file_path = app_paths.data_path('categories.dat')
    try:
        categories = [line.strip() for line in read_dat_lines(file_path)]
        ignore_categories = False  # Start by assuming the categories file exists with no read errors
        message = _('Categories file loaded successfully')
    except IOError:
        # For some reason we couldn't read the file so disable the categories option
        categories = []
        ignore_categories = True
        message = _('Unable to locate categories.dat file.  '
                    'Select some ROM categories by checking the box for the category.')
    return categories, ignore_categories, message


# ------------------------------------------------------------------------------------------------------------------
# This is used for faster image scaling
def load_and_scale_bitmap(path: str, width: int, height: int, filter: str = "BOX") -> wx.Bitmap:
    """
    Load an image with Pillow, scale it quickly, and return a wx.Bitmap.

    :param path: Path to the image file.
    :param width: Target width.
    :param height: Target height.
    :param filter: Resampling filter: "NEAREST", "BOX", "BILINEAR", "BICUBIC", "LANCZOS"
    :return: wx.Bitmap scaled to the desired size.
    """
    if not os.path.exists(path):
        return wx.NullBitmap

    filter_map = {
        "NEAREST": Image.NEAREST,
        "BOX": Image.BOX,
        "BILINEAR": Image.BILINEAR,
        "BICUBIC": Image.BICUBIC,
        "LANCZOS": Image.LANCZOS
    }

    pil_filter = filter_map.get(filter.upper(), Image.BOX)

    # Load and convert image to RGBA
    img = Image.open(path)
    img = img.resize((width, height), pil_filter)
    img = img.convert("RGBA")

    # Convert to wx.Bitmap
    return wx.Bitmap.FromBufferRGBA(img.width, img.height, img.tobytes())

# ------------------------------------------------------------------------------------------------------------------
# Set the font of the controlled passed to the function as BOLD
def set_font(control) -> None:
    """
        Set the font of the controlled passed to the function as BOLD

        :param control: The control to have its font set to BOLD
        :return: None
        """
    control_font = control.GetFont()
    control_font.SetWeight(wx.FONTWEIGHT_BOLD)
    control.SetFont(control_font)

# ------------------------------------------------------------------------------------------------------------------
# Developer Message Logging
def dev_message_log(is_developer: bool, logger, message: str) -> None:
    """
    Log a message if we are in developer mode

    :param is_developer: True if we are in developer mode
    :param logger: The logger instance and log type (e.g .info)
    :param message: Message to be logged
    :return: None
    """
    if is_developer:
        logger(message)  # Write to the log file

# ------------------------------------------------------------------------------------------------------------------
# On Close event handler for the escape key
def on_key_up(event, parent) -> None:
    """
    On Close event handler for the escape key.

    :param event: The event triggered
    :param parent: The parent that this event occurred in

    :return: None
    """
    if event.GetKeyCode() == wx.WXK_ESCAPE:
        parent.on_close(-1)
    event.Skip()


# ----------------------------------------------------------------------------------------------------------------------
def get_column_clicked(clicked_object) -> int:
    """
    Determine which column in a multi-column object has been clicked in.  Works with listctrl and ultimatelistctrl
    and possibly others.
    Credit to Dev Player for parts of this code.

    :param clicked_object: The object to detect the click within

    :return: An integer containing the column that was clicked
    """
    spt = wx.GetMousePosition()
    fpt = clicked_object.ScreenToClient(spt)
    x, y = fpt
    last_col = 0
    col_selected = None
    for col in range(clicked_object.GetColumnCount()):
        col_width = clicked_object.GetColumnWidth(col)
        left_pxl_col = last_col
        right_pxl_col = last_col + col_width - 1
        if left_pxl_col <= x <= right_pxl_col:
            # Mouse was clicked in the current column "col"; done
            col_selected = col
            break
        # prep for next calculation of next column
        last_col += col_width
    return col_selected


# ----------------------------------------------------------------------------------------------------------------------

def set_tab_order(controls: list) -> None:
    """
    Put controls in this TAB order.  wx tabs through a window's children in the order they were created, which doesn't
    always match the layout.  The controls must have the same parent; a panel in the list takes its own children with
    it.

    :param controls: The controls in the order TAB should visit them
    """
    for previous, control in zip(controls, controls[1:]):
        control.MoveAfterInTabOrder(previous)


# ----------------------------------------------------------------------------------------------------------------------
def set_colors(control, application_colors, exclusions=None) -> None:
    """
    Recursively set foreground and background colors for a wxPython control and its children,
    excluding specified control types.

    :param control: The top-level wx control.
    :param application_colors: Dictionary with 'text' and 'background_color' keys.
    :param exclusions: A list of control types to exclude from color setting (at every level, not just the top).
    """
    # # Ensure all controls have the system-wide colors
    # for child in child_controls:
    #     if type(child) != wx.Button and type(child) != wx.StaticLine and type(child) != wx.lib.buttons.GenButton:
    #         child.SetForegroundColour(application_colors['text'])
    #         child.SetBackgroundColour(application_colors['text_background'])
    # Skip specific controls that don't need styling

    if exclusions is None:
        exclusions = []

    default_exclusions = (wx.Button, wx.StaticLine, wx.lib.buttons.GenButton)
    all_exclusions = default_exclusions + tuple(exclusions)
    if not isinstance(control, all_exclusions):
        try:
            control.SetForegroundColour(application_colors['text'])
            control.SetBackgroundColour(application_colors['text_background'])
            # The custom controls (drop-down lists, text boxes, scrolled lists) draw their own scrollbars
            if hasattr(control, 'SetScrollbarColor') and 'scrollbar_thumb' in application_colors:
                control.SetScrollbarColor(application_colors['scrollbar_thumb'], application_colors['scrollbar_track'])
        except Exception as e:
            print(f"Could not set color for {type(control)}: {e}")

    try:
        for child in control.GetChildren():
            set_colors(child, application_colors, exclusions)
    except AttributeError as e:
        print(f'Error applying colors: {e}')


# ----------------------------------------------------------------------------------------------------------------------

def path_to_me() -> str:
    """The application folder (images, locales, manual ...).  User data lives in data_dir() - see app_paths.py."""
    return app_paths.app_dir()


def data_dir() -> str:
    """The folder holding the user's data (pfemame.ini, favorites.dat, the ROM database ...).  See app_paths.py."""
    return app_paths.data_dir()


# ----------------------------------------------------------------------------------------------------------------------
# The data files (categories.dat, favorites.dat, ratings.dat ...) are written as UTF-8.  Before v3.10.2 some were
# written in the system's own encoding (e.g. cp1252 on Windows), so reading falls back to that if a file isn't UTF-8 -
# a ROM or program name with an accented letter would otherwise stop the whole file being read.
def read_dat_lines(path: str) -> list[str]:
    """The lines of a data file, line ends included.  Raises OSError (e.g. FileNotFoundError) if it can't be read."""
    with open(path, 'rb') as fp:
        data = fp.read()
    try:
        text = data.decode('utf-8')
    except UnicodeDecodeError:
        text = data.decode(locale.getpreferredencoding(False), errors='replace')
    # Line ends become '\n' as when reading in text mode (writing in text mode turns them back into the system's)
    return text.replace('\r\n', '\n').replace('\r', '\n').splitlines(keepends=True)


def write_dat_lines(path: str, lines) -> None:
    """Write a data file (UTF-8).  Each line should end with a newline.  Raises OSError if it can't be written."""
    with open(path, 'w', encoding='utf-8') as fp:
        fp.writelines(lines)


# favorites.dat / watchlist.dat style files hold one entry per line: the ROM file name, or for a system program
# 'system-->name-->program file'.
def dat_file_contains(path: str, entry: str) -> bool:
    """True if a favorites.dat style file contains the entry (False if the file can't be read)."""
    try:
        return any(line.strip() == entry for line in read_dat_lines(path))
    except OSError:
        return False


def add_dat_entry(path: str, entry: str) -> None:
    """Add an entry to a favorites.dat style file, keeping it sorted with no duplicates.  Raises OSError if the file
    can't be written."""
    try:
        entries = {line.strip() for line in read_dat_lines(path) if line.strip()}
    except FileNotFoundError:
        entries = set()
    entries.add(entry)
    write_dat_lines(path, (f'{line}\n' for line in sorted(entries)))


def remove_dat_entry(path: str, entry: str) -> None:
    """Remove an entry from a favorites.dat style file.  Raises FileNotFoundError if the file doesn't exist."""
    lines = read_dat_lines(path)
    write_dat_lines(path, (line for line in lines if line.strip() != entry))


# ----------------------------------------------------------------------------------------------------------------------
# MAME folder / subprocess helpers live in mame_paths.py (no wx dependency, usable from threads, worker
# processes and tests).  Re-exported here so existing callers can keep using functions.<name>.
from mame_paths import (NO_CONSOLE, ARCHIVE_EXTENSIONS, mame_working_dir, split_mame_paths,  # noqa: F401
                        resolve_mame_folder,
                        find_ui_ini, find_mame_ini, mame_ini_candidates, mame_version, find_rom_sets,
                        ini_search_folders, rom_ini_folder, find_rom_ini, rom_set_present, find_in_folders)


@lru_cache(maxsize=None)
def find_tool(name: str) -> str | None:
    """
    Full path of a helper program such as ffmpeg / ffprobe: a copy in the pfeMAME folder wins, otherwise the PATH.
    (Previously these were run as './ffprobe.exe' / './ffmpeg', i.e. relative to whatever the current directory
    happened to be.)  Returns None if it can't be found.
    """
    executable = name + ('.exe' if sys.platform == 'win32' else '')
    for folder in (path_to_me(), os.path.dirname(os.path.abspath(sys.executable))):
        candidate = os.path.join(folder, executable)
        if os.path.isfile(candidate):
            return candidate
    return shutil.which(name)


# ----------------------------------------------------------------------------------------------------------------------
def get_platform() -> str:
    """
    Try to work out the platform
    This is needed to sort out some platform specific differences
    :param: None
    :return: String containing the platform name 'windows', 'linux', 'mac'
    """
    system = platform.system()
    return {
        'Windows': 'windows',
        'Linux': 'linux',
        'Darwin': 'mac'
    }.get(system, 'windows')


# ----------------------------------------------------------------------------------------------------------------------
def find_mame_ini_line(ini_file_content: list, item: str, default_value: str, convert_to_true_false: bool):
    """
    This function looks for a matching item in the ROM specific MAME ini file
    If it finds a match, it tries to retrieve the value
    If it can't, or no value exists, it returns the default value passed to it

    :param ini_file_content: A list of ini file fields
    :param item: The item to get the value from the list
    :param default_value: Default value to return if the item is not found
    :param convert_to_true_false: If True, a 1 will return True and all others False
    :return: The value for the field found (or the default value if not found)
    """
    for line in ini_file_content:
        if not line.strip() or line.strip().startswith("#"):
            continue  # Skip empty or commented lines
        try:
            line_split = line.split()
            if line_split[0] == item and len(line_split) > 1:
                if convert_to_true_false:
                    return 'True' if line_split[1] == '1' else 'False'
                else:
                    return line_split[1]
        except IndexError:
            # This will happen if any lines in the INI file don't contain the correctly formatted info
            pass
    # No match so return the default value
    return default_value




# ----------------------------------------------------------------------------------------------------------------------
def match_list_location(search_list: list, column: int, search_string: str):
    """
    This function allows you to search a 2-dimensional list for a match.
    If no match is found, None is returned as a result

    :param    search_list:      A 2D list to search
    :param    column:           The column number in the list to look for a match
    :param    search_string:    The string to find

    :returns:    Returns the row in the 2D list that the match was found in, or None if not found
    """
    return next((i for i, x in enumerate(search_list) if x[column] == search_string), None)


# ----------------------------------------------------------------------------------------------------------------------
def convert_sting_to_color(colour_string: str) -> tuple:
    """
    Convert a string like '(255, 255, 255, 255)' into an (R, G, B, A) tuple of integers.
    Returns (0, 0, 0, 0) if conversion fails.
    :param colour_string:
    :return: colour value
    """

    try:
        # Safely evaluate the tuple-like string
        values = tuple(int(x.strip()) for x in colour_string.strip('()').split(','))
        if len(values) == 4:
            return values
    except (ValueError, AttributeError):
        pass
    return 0, 0, 0, 0


# ----------------------------------------------------------------------------------------------------------------------
def get_application_colors() -> dict:
    """
    Read application color settings from the INI file, convert them to wx.Colour, and return them in a dictionary.
    """
    COLOR_DEFAULTS = gd.get_color_defaults()

    color_keys = {
        "row_alt_1": ("row_alt_1_color", COLOR_DEFAULTS['row_alt_1']),
        "row_alt_2": ("row_alt_2_color", COLOR_DEFAULTS['row_alt_2']),
        "text": ("text_color", COLOR_DEFAULTS['text']),
        "text_background": ("text_background_color", COLOR_DEFAULTS['text_background']),
        "window_background": ("window_background_color", COLOR_DEFAULTS['window_background']),
        "missing_game": ("missing_game_color", COLOR_DEFAULTS['missing_game']),
        "control_bar": ("control_bar_color", COLOR_DEFAULTS['control_bar']),
        "selected_row": ("selected_row_color", COLOR_DEFAULTS['selected_row']),
        "selected_row_background": ("selected_row_background_color", COLOR_DEFAULTS['selected_row_background']),
        "ribbon_item_highlight": ("ribbon_item_highlight", COLOR_DEFAULTS['ribbon_item_highlight']),
        "ribbon_bar": ("ribbon_bar_color", COLOR_DEFAULTS['ribbon_bar']),
        "scrollbar_track": ("scrollbar_track_color", COLOR_DEFAULTS['scrollbar_track']),
        "scrollbar_thumb": ("scrollbar_thumb_color", COLOR_DEFAULTS['scrollbar_thumb']),
        "button_background": ("button_background_color", COLOR_DEFAULTS['button_background']),
    }

    result = {}
    for key, (ini_key, default) in color_keys.items():
        ini_value = iniFile.read_ini_file('preferences', ini_key, default=default)

        # If the returned value is already a wx.Colour object (i.e., the default was used), use it directly
        if isinstance(ini_value, wx.Colour):
            result[key] = ini_value
        else:
            # Otherwise, it's a string from the INI file that needs conversion
            result[key] = convert_sting_to_color(ini_value)

    return result


# ----------------------------------------------------------------------------------------------------------------------
def build_one_button(parent: wx.Panel,
                     label: str,
                     handler,
                     tooltip: str = '',
                     background_color: tuple = wx.NullColour,
                     vertical_size: int = -1,
                     name: str = '',
                     foreground_color: tuple = wx.NullColour,
                     horizontal_size: int = -1) -> wx.lib.buttons.GenButton:
    """
    This function creates a single button with bindings and tooltips
    :param    parent:
    :param    label:
    :param    handler:
    :param    tooltip:
    :param    background_color:
    :param    vertical_size:
    :param    name:
    :param    foreground_color:
    :param    horizontal_size:

    :returns:    button
    """

    if background_color == wx.NullColour:
        background_color = get_application_colors()['button_background']

    if foreground_color == wx.NullColour:
        foreground_color = get_application_colors()['text']

    size = (horizontal_size, vertical_size)
    button = wx.lib.buttons.GenButton(parent=parent, label=label, pos=wx.DefaultPosition, size=size, name=name)
    button.SetToolTip(wx.ToolTip(tooltip))
    button.SetBackgroundColour(background_color)
    button.SetForegroundColour(foreground_color)
    parent.Bind(wx.EVT_BUTTON, handler, button)

    def button_highlight(_event):
        size = button.GetSize()
        # Draw directly on the button itself - no coordinate translation needed
        box_parameters = [0, 0, size[0], size[1]]

        dc = wx.WindowDC(button)  # Draw on the button, not the parent
        dc.SetPen(wx.Pen(wx.BLUE, 4))
        dc.SetBrush(wx.Brush('grey', wx.TRANSPARENT))
        dc.DrawRectangle(*box_parameters)
        dc.Destroy()

    # def button_highlight(_event):
    #     size = button.GetSize()
    #     position = button.GetPosition()
    #     box_parameters = [position[0], position[1], size[0] + 2, size[1] + 2]  # Draw the box
    #
    #     dc = wx.WindowDC(parent)
    #     dc.SetPen(wx.Pen(wx.BLUE, 4))
    #     dc.SetBrush(wx.Brush('grey', wx.TRANSPARENT))
    #     dc.DrawRectangle(*box_parameters)
    #     dc.Destroy()

    def button_normal(_event):
        parent.Refresh()

    button.Bind(wx.EVT_ENTER_WINDOW, button_highlight)
    button.Bind(wx.EVT_LEAVE_WINDOW, button_normal)

    return button


# --------------------------------------------------------------------------------------------------------------
# These two functions are for recalling fonts information
def get_font_from_ini(prefix: str, default_point_size: int, default_family=wx.DEFAULT, default_style=wx.NORMAL,
                      default_weight=wx.NORMAL, underline=False) -> wx.Font:
    """
    Helper to construct a wx.Font from INI entries with a given prefix.
    :param prefix:
    :param default_point_size:
    :param default_family:
    :param default_style:
    :param default_weight:
    :param underline:
    :return: wx.Font
    """
    # A value that isn't a number (e.g. after a hand edit) uses the default rather than stopping pfeMAME starting
    point_size = iniFile.read_ini_int('preferences', f'{prefix}_pointsize', default_point_size, low=1, high=200)
    family = iniFile.read_ini_int('preferences', f'{prefix}_family', default_family)
    style = iniFile.read_ini_int('preferences', f'{prefix}_style', default_style)
    weight = iniFile.read_ini_int('preferences', f'{prefix}_weight', default_weight)
    return wx.Font(point_size, family, style, weight, underline=underline)


def get_font_info():
    """
    Get font information from the INI file
    :return: Returns a named tuple of:
                global_font_bold
                global_font_normal
                global_font_normal_8
                global_font_normal_12
                global_font_bold
                global_font_bold_20
    """
    fonts = namedtuple('fonts', [
        'global_font_bold',
        'global_font_normal',
        'global_font_normal_8',
        'global_font_normal_12',
        'global_font_bold_underline',
        'global_font_bold_20'
    ])

    return fonts(
        get_font_from_ini('global_font_bold', 10, default_weight=wx.BOLD),
        get_font_from_ini('global_font_normal', 10),
        get_font_from_ini('global_font_normal_8', 8),
        get_font_from_ini('global_font_normal_12', 12),
        get_font_from_ini('global_font_bold', 10, default_weight=wx.BOLD, underline=True),
        get_font_from_ini('global_font_bold_20', 20, default_weight=wx.BOLD)
    )

# ----------------------------------------------------------------------------------------------------------------------
def get_system_media_types(path_mame_exe: str, rom_file_name: str, file_extension: str = ''):
    """
    Get the media list for the selected system type using -listmedia with the MAME command

    This function is used by a few bits of code that need slightly different data, so it may seem to do more than is
    really needed, but it is.

    :param    path_mame_exe:   The full path to the MAME executable file
    :param    rom_file_name:   The file name of the system to check for media types
    :param    file_extension:  This is an optional file extension to check for in the media list.  If an extension is passed to
                               this function, then its output will be a True or False to indicate if it found a match with that
                               extension or not.

    :returns:
    If file_extension is not empty, then a True or False will be output depending upon if a match with that file
    extension has been found.  The media type for the match is also returned.

    If file_extension is empty, then the untested full media list is output.
    The list is kept for each MAME executable and system (asking MAME takes a second or so), until MAME is updated.
    """
    if not rom_file_name:
        return -1

    extensions, media_types = _list_media(path_mame_exe, rom_file_name)

    if not file_extension:
        return list(extensions)

    # Exact match - '.d' must not match '.dsk'
    match = next(((True, media) for extension, media in zip(extensions, media_types)
                  if file_extension.lower() == extension.lower()), (False, ''))
    return match


# (MAME executable, its modification time, system) -> (extensions, media types).  Only lists MAME answered with are
# kept, so a MAME that couldn't be run is asked again next time.
_media_cache: dict[tuple, tuple[tuple, tuple]] = {}


def _list_media(path_mame_exe: str, rom_file_name: str) -> tuple[tuple, tuple]:
    """The extensions a system's media accept, and the media type (brief name, e.g. 'cass') for each one."""
    try:
        modified = os.path.getmtime(path_mame_exe)       # A new MAME version may change the media
    except (OSError, TypeError, ValueError):
        modified = 0                                     # On the PATH (e.g. 'mame' on Linux)
    key = (path_mame_exe, modified, rom_file_name)
    if key in _media_cache:
        return _media_cache[key]

    cmd = [path_mame_exe, rom_file_name, '-listmedia']
    try:
        output = subprocess.run(cmd,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE,
                                universal_newlines=True,
                                errors='replace',
                                cwd=mame_working_dir(path_mame_exe),
                                **NO_CONSOLE)
    except (OSError, ValueError):
        return (), ()

    # Parse the output, e.g. 'spectrum  cassette  (cass)  .wav  .tzx  .tap', looking for the extension types
    extensions = []
    media_types = []
    for line in (output.stdout or '').splitlines():
        line = line.rstrip()
        if '(' not in line or ')' not in line:
            continue
        media = line.split('(')[1].split(')')[0]
        for a in line.split(')', 1)[1].split('.')[1:]:
            extensions.append(''.join(['.', a.strip()]))
            media_types.append(media)

    result = (tuple(extensions), tuple(media_types))
    if extensions:
        _media_cache[key] = result
    return result


# ----------------------------------------------------------------------------------------------------------------------
def debug_type_print(development_mode: bool, start_time: float, message: str, collector: list | None = None) -> str:
    """
    Return or store a debug message if we are in development mode
    """
    if development_mode:
        result = f'{message} completed in {time.time() - start_time:.4f} seconds\n'
        if collector is not None:
            collector.append(result)
        return result
    return ''

# ----------------------------------------------------------------------------------------------------------------------
def get_softwarelist_name(_path_to_me: str, path_mame_exe: str, rom_name: str, short_name: str) -> str:
    try:
        cmd = [path_mame_exe, '-listsoftware', '-nodtd', rom_name]
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                cwd=mame_working_dir(path_mame_exe), **NO_CONSOLE)

        if result.returncode != 0:
            return ''

        out = result.stdout
        if out is None:
            return ''
        out = out.decode('utf-8', errors='ignore').lower()

        pos = 0
        while True:
            start_index = out.find('<softwarelist name="', pos)
            if start_index == -1:
                break

            list_name_start = start_index + len('<softwarelist name="')
            list_name_end = out.find('"', list_name_start)
            if list_name_end == -1:
                break

            list_name = out[list_name_start:list_name_end]
            end_index = out.find('</softwarelist>', list_name_end)
            if end_index == -1:
                break

            block = out[start_index:end_index]
            if f'name="{short_name}"' in block:
                return list_name  # <-- Directly return here

            pos = end_index + len('</softwarelist>')

    except OSError:
        return ''

    return ''  # <-- Return '' if no match found


# ----------------------------------------------------------------------------------------------------------------------
# Matches a <software name="..."> element and its <description> child in MAME's -listsoftware output.
SOFTWARELIST_BLOCK_PATTERN = re.compile(
    r'<softwarelist\s+name="(?P<name>[^"]+)"[^>]*>(?P<body>.*?)</softwarelist>', re.DOTALL | re.IGNORECASE)
SOFTWARE_BLOCK_PATTERN = re.compile(
    r'<software\s+name="(?P<name>[^"]+)"[^>]*>(?P<body>.*?)</software>', re.DOTALL | re.IGNORECASE)
DESCRIPTION_PATTERN = re.compile(r'<description>(?P<text>.*?)</description>', re.DOTALL | re.IGNORECASE)


def get_software_details(path_mame_exe: str, rom_name: str, short_name: str) -> tuple[str, str]:
    """
    Look up the human-readable description of a single software list entry (a 'system program') by running
    ``mame -listsoftware <system>`` once and parsing the result.

    Unlike get_softwarelist_name() the output is NOT lower-cased here, because the description is shown to the
    user and used to build online image search queries, where the original capitalisation matters.

    :param path_mame_exe: Full path to the MAME executable.
    :param rom_name:      The system ROM name, e.g. 'nes'.
    :param short_name:    The software list short name of the program, e.g. 'smb'.
    :return: (description, softwarelist_name), e.g. ('Super Mario Bros.', 'nes').  Either or both are '' when the
             entry cannot be resolved (no MAME executable, no HASH files, unknown short name...).
    """
    if not path_mame_exe or not rom_name or not short_name:
        return '', ''

    try:
        result = subprocess.run([path_mame_exe, '-listsoftware', '-nodtd', rom_name],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                cwd=mame_working_dir(path_mame_exe), **NO_CONSOLE)
    except Exception:
        return '', ''

    if result.returncode != 0 or not result.stdout:
        return '', ''

    out = result.stdout.decode('utf-8', errors='ignore')
    wanted = short_name.lower()

    for software_list in SOFTWARELIST_BLOCK_PATTERN.finditer(out):
        for software in SOFTWARE_BLOCK_PATTERN.finditer(software_list.group('body')):
            if software.group('name').lower() != wanted:
                continue
            description = DESCRIPTION_PATTERN.search(software.group('body'))
            text = html.unescape(description.group('text').strip()) if description else ''
            return text, software_list.group('name')

    return '', ''




# ----------------------------------------------------------------------------------------------------------------------
def load_history_dat(parent,
                     my_logger: logging.Logger,
                     path_history: str,
                     file_type: str,
                     suppress: bool = False) -> str:
    """
    Load the history or mameinfo files.

    For the history file, only .xml file version is now supported.
    For the mameinfo.dat file it is just a .dat

    :param parent:        Used to call parent functions (like alert timer)
    :param my_logger:     Access the parent logger function to log messages
    :param path_history:  Defined path to the file
    :param file_type:     A text field of either 'history' or 'mameinfo' that is used to adjust error messages
    :param suppress:      If True this function won't try to append messages to the parent messages window (e.g., Tile View)

    :return:    Returns the history data as a string
    """
    if not path_history or path_history == '.':
        return ''

    ext = path_history.lower()
    if ext.endswith('xml') and file_type == 'history':
        msg = _('Reading history.xml file.')
        my_logger.info(msg)
    elif ext.endswith('dat') and file_type == 'mameinfo':
        msg = _('Reading mameinfo.dat file.')
        my_logger.info(msg)

    try:
        with open(path_history, 'r', encoding='utf-8', errors='ignore') as fp:
            return fp.read()
    except (FileNotFoundError, PermissionError) as e:
        msg = _('Unable to read the {file_type} file at "{path}": {error}').format(file_type=file_type,
                                                                              path=path_history, error=str(e))
        my_logger.error(msg)
        if not suppress:
            parent.messages_append(f'ERROR: {msg}\n')
            parent.enable_alert_timer()
        return ''

# ----------------------------------------------------------------------------------------------------------------------
def get_rom_info(history_data: str,
                 mylist: list,
                 rom_file_name: str,
                 system_file_name: str,
                 short_name: str,
                 index_system_folder_name: int,
                 file_type: str) -> str:
    """
    Get ROM information from the history data file or the mameinfo file
    - For the history file, only the XML format file is supported.
    - For the mameinfo file, the file type is a .dat file.
    """

    if not history_data:
        return _('No History file defined')

    if file_type == 'mameinfo':
        # Look for ROM file name matches in mameinfo.dat
        start_position = history_data.find(rom_file_name)
        if start_position == -1:
            return _('No information in the {file_type} file for System: {rom} with system program {program}').format(
                file_type=file_type, rom=rom_file_name, program=system_file_name
            )

        start_text = history_data.find('$mame', start_position)
        end_text = history_data.find('$end', start_text)
        if start_text == -1 or end_text == -1:
            return _('No history text found between $mame and $end tags for ROM: {}').format(rom_file_name)

        output = history_data[start_text + 6:end_text]
        return html.unescape(output)  # unescape HTML entities

    # Otherwise, must be the history.xml file
    if system_file_name:
        output = _('No information in the History file for System: {rom} with system program {program}').format(
            rom=rom_file_name, program=system_file_name
        )
        if not short_name:
            return output
        # Find matching system entry
        temp = match_list_location(mylist, 2, system_file_name)
        mt1_system = mylist[temp][index_system_folder_name]
        match_string = f'<item list="{mt1_system}" name="{short_name}"'
    else:
        output = _('No information in the History file for {}').format(rom_file_name)
        match_string = f'<system name="{rom_file_name}"'

    position = history_data.find(match_string)
    if position == -1:
        return output  # no match found, return earlier message

    start_text = history_data.find('<text>', position)
    end_text = history_data.find('</text>', start_text)
    if start_text == -1 or end_text == -1:
        return output  # no text section found, return earlier message

    output = history_data[start_text + 6:end_text]
    return html.unescape(output)


# ----------------------------------------------------------------------------------------------------------------------
def create_text_ctrl(parent,
                     id_in: int,
                     text: str,
                     style,
                     font_size: int,
                     font_family: int,
                     font_style: int,
                     font_weight: int,
                     foreground_color: str = '',
                     background_color: str = '') -> wx.StaticText:
    """
    Create a static text control and set font and color
    """
    text_ctrl = wx.StaticText(parent=parent, id=id_in, label=text, style=style)
    text_ctrl.SetFont(wx.Font(font_size, font_family, font_style, font_weight))

    if foreground_color:
        text_ctrl.SetForegroundColour(wx.Colour(foreground_color))

    if background_color:
        text_ctrl.SetBackgroundColour(wx.Colour(background_color))

    return text_ctrl


# ----------------------------------------------------------------------------------------------------------------------
def compare_version(version1: str, version2: str) -> int:
    """
    Compare version numbers between two strings

    INPUTS:
    :param    version1:   first version to check
    :param    version2:   second version to check

    :returns:
    returns 1 if version1 is greater than version2
    returns -1 if version2 is greater than version1
    returns 0 if they match or if there is an error

    """
    try:
        def set_up_version_info(version) -> list[int]:
            return [int(v) for v in version.split(".")]

        versions1 = set_up_version_info(version1)
        versions2 = set_up_version_info(version2)
        for i in range(max(len(versions1), len(versions2))):
            v1 = versions1[i] if i < len(versions1) else 0
            v2 = versions2[i] if i < len(versions2) else 0
            if v1 > v2:
                return 1
            elif v1 < v2:
                return -1
        return 0
    except ValueError:
        return 0

# ----------------------------------------------------------------------------------------------------------------------
def joystick_setup(parent, my_logger: logging.Logger, pref_joystick_selected: str) -> tuple:
    """
    Joystick setup code

    Check if a joystick is available / connected and set up various defaults to get it working.

    :param parent:                         The parent caller
    :param my_logger:                      The logging capture on the parent
    :param pref_joystick_selected:         Joystick preference setting

    :returns:
     joystick - The joystick object
     joystick_polling_timer - Polling event timer for DHAT / POV
     joystickXMin - Joystick minimum X value
     joystickXMax - Joystick maximum X value
     joystickYMin                   Joystick minimum Y value
     joystickYMax                   Joystick maximum Y value
    """
    polling_frequency = iniFile.read_ini_int('preferences', 'joystick_polling_freq', low=1, high=1000)

    try:
        # Get the joystick
        joystick_map = {
            'Joystick 1': wx.JOYSTICK1,
            'Joystick 2': wx.JOYSTICK2,
        }

        for name, wx_const in joystick_map.items():
            if name in pref_joystick_selected:
                joystick = wx.adv.Joystick(joystick=wx_const)
                if my_logger:
                    my_logger.info(_('Using {} for navigation').format(name))
                break
        else:
            raise NotImplementedError

        if joystick.IsOk():
            joystick.SetCapture(parent, pollingFreq=polling_frequency)

            # Get the extents of the directional control
            joystickXMin = joystick.GetXMin()
            joystickXMax = joystick.GetXMax()
            joystickYMin = joystick.GetYMin()
            joystickYMax = joystick.GetYMax()

            # Bind the joystick events
            parent.Bind(wx.EVT_JOYSTICK_EVENTS, parent.on_joystick)

            # Set up the joystick polling timer.
            # This is needed as the DHAT / POV / DPAD movement does not generate events, so I have to poll
            # it continuously.
            joystick_polling_timer = wx.Timer(parent)
            if joystick.HasPOV():
                parent.Bind(wx.EVT_TIMER, parent.on_joystick_pov, joystick_polling_timer)
                joystick_polling_timer.Start(200)
        else:
            raise NotImplementedError
    except NotImplementedError:
        if my_logger:
            my_logger.info(_('No joystick available for navigation'))  # Write to the log file

        joystick = None
        joystick_polling_timer = None
        joystickXMin = -1
        joystickXMax = -1
        joystickYMin = -1
        joystickYMax = -1

    return joystick, joystick_polling_timer, joystickXMin, joystickXMax, joystickYMin, joystickYMax


# ----------------------------------------------------------------------------------------------------------------------
def replace_escaped_characters(input_data: list) -> list:
    """
    Function to replace & escaped characters in a list with their correct versions.
    This is used on data retrieved from XMl files

    :param    input_data:      The raw input XML data

    :returns: The escaped version
    """

    return [w if '&' not in w else w.replace('&amp;', '&')
             .replace('&lt;', '<')
             .replace('&gt;', '>')
             .replace('&apos;', "'")
             .replace('&quot;', '"') for w in input_data]


# ----------------------------------------------------------------------------------------------------------------------
class PreferenceManager:
    """
    A reusable class for managing preference updates across multiple GUI forms.

    This class centralizes the logic for collecting values from GUI controls,
    transforming them as needed, and sending them via pubsub messages. It eliminates
    code duplication when dealing with multiple preference forms that follow the
    same pattern of reading control values and sending messages.

    The class supports different types of preferences:
    - Boolean preferences that convert to integers (0/1)
    - String preferences
    - Custom preferences with user-defined transformation functions

    Example usage:
        class MyPreferenceForm(wx.Panel):
            def __init__(self, parent, mode="user"):
                super().__init__(parent)
                self.mode = mode

                # Create your GUI controls
                self.cbWindow = wx.CheckBox(self, label="Windowed Mode")
                self.cbVideo = wx.ComboBox(self, choices=["OpenGL", "DirectX"])

                # Setup preference manager
                self.setup_preference_manager()

            def setup_preference_manager(self):
                self.pref_manager = PreferenceManager(self, self.mode)
                self.pref_manager.add_boolean_preference('pref_window', self.cbWindow)
                self.pref_manager.add_string_preference('pref_video', self.cbVideo)

            def on_save_clicked(self, event):
                # Update all preferences with a single call
                self.pref_manager.update_all()

    Attributes:
        parent: Reference to the parent form/panel containing the controls
        mode: String identifier used as prefix for pubsub message topics
        preferences: Dict storing preference configurations
    """

    def __init__(self, parent, mode):
        self.parent = parent
        self.mode = mode
        self.preferences = {}

    def add_boolean_preference(self, key, control):
        """
        Register a boolean preference that will be converted to integer (0 or 1).

        This method is typically used for checkboxes or other controls that return
        boolean values but need to be stored/transmitted as integers.

        Args:
            key (str): The preference key that will be sent in the pubsub message.
                      This should match the key expected by the receiving code.
            control (wx.Window): The GUI control to read the value from. Must have
                               a GetValue() method that returns a boolean.

        Example:
            # For a checkbox that controls windowed mode
            self.pref_manager.add_boolean_preference('pref_windowed', self.cbWindowed)

            # For a radio button that enables/disables a feature
            self.pref_manager.add_boolean_preference('pref_feature_enabled', self.rbFeature)

        Note:
            The control's GetValue() result will be converted as follows:
            - True becomes 1
            - False becomes 0
            - Any other truthy value becomes 1
            - Any other falsy value becomes 0
        """
        self.preferences[key] = (control, lambda x: 1 if x else 0)

    def add_string_preference(self, key, control):
        """
        Register a string preference.

        This method is used for controls that return values that should be converted
        to strings before transmission. This includes text controls, combo boxes,
        choice controls, etc.

        Args:
            key (str): The preference key that will be sent in the pubsub message.
            control (wx.Window): The GUI control to read the value from. Must have
                               a GetValue() method.

        Example:
            # For a text control containing a file path
            self.pref_manager.add_string_preference('pref_data_path', self.txtDataPath)

            # For a combo box with backend options
            self.pref_manager.add_string_preference('pref_backend', self.cbBackend)

            # For a choice control with quality settings
            self.pref_manager.add_string_preference('pref_quality', self.chQuality)

        Note:
            The control's GetValue() result will be converted to string using str().
            This handles most common data types (int, float, bool, etc.) automatically.
        """
        self.preferences[key] = (control, str)

    def add_custom_preference(self, key, control, transformer):
        """
        Register a preference with a custom transformation function.

        This method provides maximum flexibility for handling controls that need
        special processing of their values before transmission.

        Args:
            key (str): The preference key that will be sent in the pubsub message.
            control (wx.Window): The GUI control to read the value from. Must have
                               a GetValue() method.
            transformer (Callable): A function that takes the raw control value
                                  and returns the transformed value for transmission.

        Example:
            # Convert a slider value to a percentage string
            self.pref_manager.add_custom_preference(
                'pref_volume',
                self.slVolume,
                lambda x: f"{x}%"
            )

            # Convert a list selection to a specific format
            self.pref_manager.add_custom_preference(
                'pref_resolution',
                self.lstResolution,
                lambda x: f"{x[0]}x{x[1]}" if isinstance(x, (list, tuple)) else str(x)
            )

            # Apply bounds checking and formatting
            self.pref_manager.add_custom_preference(
                'pref_timeout',
                self.spnTimeout,
                lambda x: max(1, min(60, int(x)))  # Clamp between 1 and 60
            )

        Note:
            The transformer function should handle any exceptions that might occur
            during transformation, or ensure that the control values are always
            in an expected format.
        """
        self.preferences[key] = (control, transformer)

    def update_all(self):
        """Update all registered preferences"""
        for key, (control, transformer) in self.preferences.items():
            value = transformer(control.GetValue())
            wx.CallAfter(pub.sendMessage, f"{self.mode}_set_variable",
                         msg=[key, value])

        # Force INI update
        wx.CallAfter(pub.sendMessage, f"{self.mode}_update_ini")


# ----------------------------------------------------------------------------------------------------------------------
class StatusBarPanel(wx.Panel):
    """
    A Custom statusbar panel

    This allows you to have complete control over the foreground and background colors across all platforms which
    the standard status bar does not (I'm looking at you macOS!).
    """

    def __init__(self, parent):
        wx.Panel.__init__(self, parent)

        self.application_colors: dict = get_application_colors()
        self.SetBackgroundColour(self.application_colors['control_bar'])

        self.sizer = wx.GridBagSizer(2, 1)
        self.sizer.AddGrowableCol(0)

        sizer_quantities = wx.BoxSizer(wx.HORIZONTAL)

        self.statusbar_status = wx.StaticText(self, -1, '')
        self.statusbar_status.SetBackgroundColour(self.application_colors['control_bar'])
        self.statusbar_status.SetForegroundColour(self.application_colors['text'])

        global_font_bold = get_font_info().global_font_bold

        def _create_label_value_pair(label_text, initial_value='0'):
            label = wx.StaticText(self, -1, label_text)
            label.SetBackgroundColour(self.application_colors['control_bar'])
            label.SetForegroundColour(self.application_colors['text'])
            label.SetFont(global_font_bold)

            value = wx.StaticText(self, -1, initial_value)
            value.SetBackgroundColour(self.application_colors['control_bar'])
            value.SetForegroundColour(self.application_colors['text'])

            return label, value

        label, self.total_roms = _create_label_value_pair(_('Total ROMs: '))
        sizer_quantities.Add(label)
        sizer_quantities.Add(self.total_roms)
        sizer_quantities.AddSpacer(10)

        label, self.exists = _create_label_value_pair(_('Exists: '))
        sizer_quantities.Add(label)
        sizer_quantities.Add(self.exists)
        sizer_quantities.AddSpacer(10)

        label, self.in_current = _create_label_value_pair(_('In Current View: '))
        sizer_quantities.Add(label)
        sizer_quantities.Add(self.in_current)
        sizer_quantities.AddSpacer(10)

        self.sizer.Add(self.statusbar_status, pos=(0, 0), flag=wx.ALL | wx.EXPAND, border=0)
        # Column 1 is kept for an optional progress bar (see add_progress_bar)
        self.sizer.Add(sizer_quantities, pos=(0, 2), flag=wx.ALL | wx.EXPAND, border=0)

        self.SetSizer(self.sizer)

    def add_progress_bar(self, progress_bar: wx.Window) -> None:
        """
        Give a progress bar (created with this panel as its parent) its own place between the status message and the
        ROM quantities.  It used to be a separate window laid over the whole status bar, which on Linux (GTK)
        painted over the status message so none of the messages could be seen while the progress bar was showing.
        """
        self.sizer.Add(progress_bar, pos=(0, 1), flag=wx.ALIGN_CENTER_VERTICAL | wx.LEFT | wx.RIGHT,
                       border=self.FromDIP(6))
        self.Layout()

    def show_progress_bar(self, progress_bar: wx.Window, show: bool) -> None:
        progress_bar.Show(show)
        self.Layout()

    def set_status(self, status: str) -> None:
        """
        Set the status message
        :param status: Message to display
        :return: None
        """
        self.statusbar_status.SetLabelText(status)

    def set_quantities(self, total_roms: str, exists: str, in_current_view: str) -> None:
        """
        Set the ROM quantities
        :param total_roms:
        :param exists:
        :param in_current_view:
        :return:
        """
        self.total_roms.SetLabelText(total_roms)
        self.exists.SetLabelText(exists)
        self.in_current.SetLabelText(in_current_view)
        self.Refresh()
        self.Layout()

    def get_status_text(self):
        return self.statusbar_status.GetLabel()

    def get_rect(self):
        return self.sizer.GetPosition()

    # This just kills any unwanted events for the control it is bound to
    def stop_focus(self, event):
        pass


# ----------------------------------------------------------------------------------------------------------------------
def copy_one_file(source_path: str, destination_path: str, file_to_copy: str) -> str:
    """
    # Copy one file from source to destination

    :param source_path:
    :param destination_path:
    :param file_to_copy:

    :returns:  Returns a string showing the file copied or if the file doesn't exist, a note that it wasn't copied as it
               doesn't exist.
    """
    if os.path.exists(os.path.join(source_path, file_to_copy)):
        shutil.copy2(os.path.join(source_path, file_to_copy), os.path.join(destination_path, file_to_copy))
        return f'{file_to_copy}\n'
    else:
        return _('Skipped {} as it does not exist\n').format(file_to_copy)

# ------------------------------------------------------------------------------------------------------------------
# def load_other_emulators_detail(_path_to_me: str) -> tuple[list, bool]:
#     """
#     Load the Non Mame Emulators list from the XML file.
#
#     :param _path_to_me: This is the local path to the pfeMAME application
#
#     :returns:
#     Returns a list of alternate emulation engines and their relevant details.
#     Also returns an error flag indicating there was some sort of problem retrieving info from the INI file.
#     """
#     xml_path = app_paths.data_path('non_mame_emulators.xml')
#     if not os.path.exists(xml_path):
#         return [], False
#
#     try:
#         with open(xml_path, 'r') as fp:
#             temp_list = fp.readlines()
#     except (FileNotFoundError, IOError):
#         # Can't open the file
#         return [], True
#
#     if not temp_list:
#         return [], False
#
#     non_mame_emulators = []
#     error = False
#     index = 0
#
#     try:
#         while '</pfemame>' not in temp_list[index]:
#             line = temp_list[index]
#             if '<machine' in line:
#                 machine_name = line.split('name="')[1].split('"')[0]
#                 path_to_emulator = line.split('pathToEmulator="')[1].split('"')[0]
#                 rom_folder = line.split('romFolder="')[1].split('"')[0]
#                 use_this_engine = line.split('useThisEngine="')[1].split('"')[0] == 'True'
#                 include_extension = line.split('includeExtension="')[1].split('"')[0] == 'True'
#                 include_folder_path = line.split('includeFolderPath="')[1].split('"')[0] == 'True'
#
#                 # read next lines for description, extra commands, extensions
#                 emulator_description = temp_list[index + 1].split('description>')[1].split('<')[0]
#                 extra_commands = temp_list[index + 2].split('extraCommands>')[1].split('<')[0]
#                 extensions = temp_list[index + 3].split('extensions>')[1].split('<')[0]
#
#                 index += 4
#
#                 while '</machine>' not in temp_list[index]:
#                     line = temp_list[index]
#                     if '<game' in line:
#                         game_name = unescape(line.split('name="')[1].split('"')[0])
#                         game_file_name = unescape(line.split('fileName="')[1].split('"')[0])
#                         non_mame_emulators.append([
#                             machine_name,
#                             path_to_emulator,
#                             rom_folder,
#                             emulator_description,
#                             use_this_engine,
#                             include_extension,
#                             include_folder_path,
#                             extra_commands,
#                             extensions,
#                             game_name,
#                             game_file_name
#                         ])
#                     index += 1
#             else:
#                 index += 1
#     except (IndexError, FileNotFoundError):
#         error = True
#
#     return non_mame_emulators, error

def load_other_emulators_detail(_path_to_me: str) -> tuple[list, bool]:
    """
    Load the Non Mame Emulators list from the XML file.

    :param _path_to_me: This is the local path to the pfeMAME application (no longer needed: the file is in the
                        user's data folder)

    :returns:
    Returns a list of alternate emulation engines and their relevant details (see emulator_config.EmulatorFields).
    Also returns an error flag indicating there was some sort of problem retrieving info from the XML file.
    """
    return emulator_config.load_emulators(app_paths.data_path(emulator_config.EMULATORS_XML_FILE))

# ----------------------------------------------------------------------------------------------------------------------
def remove_duplicates_by_first_two_fields(data):
    """
    Remove duplicate lines based on first and second fields.
    When duplicates are found, remove the line where position 3 == '0'.
    This is used for filtering duplicates from self.mylist after a database build when one of the duplicate pair
    exists and the other does not.  If both are flagged as exists then they are left alone as that would be the
    situation for systems programs.

    Args:
        data: List of lists representing your nested data

    Returns:
        List of lists with duplicates removed
    """
    # Dictionary to group lines by first two fields
    groups = {}

    # Group lines by their first two fields
    for line in data:
        if len(line) >= 5:  # Ensure line has at least 5 elements
            key = (line[0], line[1])  # First and second field as tuple key
            if key not in groups:
                groups[key] = []
            groups[key].append(line)

    result = []

    # Process each group
    for key, lines in groups.items():
        if len(lines) == 1:
            # No duplicates, keep the line
            result.append(lines[0])
        else:
            # Multiple lines with same first two fields
            # Remove lines where position 4 == '0', keep others
            filtered_lines = [line for line in lines if line[3] != '0']

            if filtered_lines:
                # If we have lines after filtering, add them all
                result.extend(filtered_lines)
            else:
                # If all lines had '0' in position 4, keep one of them
                # (This handles edge case where all duplicates have '0')
                result.append(lines[0])

    return result

# ----------------------------------------------------------------------------------------------------------------------
def setup_logging(_path_to_me: str) -> logging.Logger:
    """
    This sets up the application logging

    :param _path_to_me:

    :returns: my_logger
    """
    my_logger = logging.getLogger('>')
    my_logger.propagate = False  # Stop windows complaining about logged warnings (stops a popup after closing)

    # Add the log message handler to the logger
    logging.basicConfig(level=logging.INFO)
    handler = logging.handlers.RotatingFileHandler(app_paths.data_path('logfile.log'),
                                                   maxBytes=512 * 1024, backupCount=2, encoding='utf-8')
    # Create a logging format
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(lineno)d:%(filename)s - %(message)s')
    handler.setFormatter(formatter)
    my_logger.addHandler(handler)

    return my_logger


# ----------------------------------------------------------------------------------------------------------------------
class MyLog(wx.Log):
    """
    This is the class to override the wx.Log.

    I have implemented this primarily to get rid of the annoying tEXt CRC error
    pop-up that sometimes appears due to malformed png image files.  Rather than
    a popup, this just writes the message to the messages box as well as the logfile.

    :param text_control:     The text control that the wx.Log message will output to
    :param my_logger:        An instance of your logger
    :param logTime:          Not used for this purpose

    :returns: None:           Nothing returned

    """

    def __init__(self, text_control, my_logger, logTime=0):
        wx.Log.__init__(self)
        self.tc = text_control
        self.logTime = logTime
        self.my_logger = my_logger

    def DoLogString(self, message):
        if self.tc:
            self.tc.AppendText(message + '\n')
            self.my_logger.warning(message)  # Write to the log file


# ------------------------------------------------------------------------------------------------------------------
# Custom renderer for the UltimateListCtrl header drawing so that we can have custom colors
class UltimateHeaderRenderer(object):
    """
    Custom renderer for the UltimateListCtrl header drawing so that we can have custom colors
    """
    def __init__(self, application_colors: dict):
        self._hover = False
        self._pressed = False
        self.application_colors = application_colors

    def DrawHeaderButton(self, dc, rect, _flags: int):
        self._hover = False
        self._pressed = False

        color = self.application_colors['control_bar']

        dc.SetBrush(wx.Brush(color, wx.SOLID))
        dc.SetBackgroundMode(wx.SOLID)
        dc.SetPen(wx.TRANSPARENT_PEN)
        dc.DrawRectangle(rect)
        dc.SetBackgroundMode(wx.TRANSPARENT)

    def GetForegroundColour(self):
        pass
        """
        if self._hover:
            return wx.Colour(255,255,255)
        else:
            return wx.Colour(0,0,0)
        """

# ------------------------------------------------------------------------------------------------------------------
# Custom column header drawing for wx.grid.Grid so that we can have custom colors
def style_grid_column_header(grid, application_colors: dict) -> None:
    """
    Paint the column labels of a wx.grid.Grid in the control bar color.

    wxWidgets tints the label of the column that holds the grid cursor with the selection
    color, so the header changes color as the user clicks from column to column.  Taking
    over the paint event keeps every label on the control bar color wherever the cursor is.

    :param grid: The wx.grid.Grid whose column labels are to be drawn
    :param application_colors: The application color dictionary, read at paint time
    """

    label_window = grid.GetGridColLabelWindow()

    def on_paint(_event):
        dc = wx.PaintDC(label_window)

        # The label window does not scroll itself, so shift the origin to follow the grid
        scroll_x, _scroll_y = grid.CalcUnscrolledPosition(0, 0)
        dc.SetDeviceOrigin(-scroll_x, 0)

        background = wx.Colour(application_colors['control_bar'])
        foreground = wx.Colour(application_colors['text'])
        height = grid.GetColLabelSize()

        # Fill the whole strip first so any space past the last column is covered as well
        dc.SetBrush(wx.Brush(background))
        dc.SetPen(wx.TRANSPARENT_PEN)
        dc.DrawRectangle(0, 0, label_window.GetClientSize().width + scroll_x, height)

        dc.SetFont(grid.GetLabelFont())
        dc.SetTextForeground(foreground)
        horizontal_align, vertical_align = grid.GetColLabelAlignment()

        for col in range(grid.GetNumberCols()):
            width = grid.GetColSize(col)
            if width <= 0:                  # hidden column
                continue
            rect = wx.Rect(grid.GetColLeft(col), 0, width, height)
            dc.SetBrush(wx.Brush(background))
            dc.SetPen(wx.Pen(grid.GetGridLineColour()))
            dc.DrawRectangle(rect)
            rect.Deflate(2, 1)
            grid.DrawTextRectangle(dc, grid.GetColLabelValue(col), rect,
                                   horizontal_align, vertical_align)

    label_window.Bind(wx.EVT_PAINT, on_paint)
    label_window.Bind(wx.EVT_ERASE_BACKGROUND, lambda _event: None)

# ------------------------------------------------------------------------------------------------------------------
# This is a basic XML file parser implementation
class BasicXMLParser:
    """
    Basic XML file parser

    :param file_path: File path to the XML file to parse
    """

    __slots__ = ['file_path', 'file_data']

    def __init__(self, file_path: str):
        self.file_path = file_path
        self.file_data = []

    def read_file(self) -> list[str]:
        """
        Read the file and return the parsed data
        """

        try:
            with open(self.file_path, 'r') as fp:
                self.file_data = [
                    line.strip() for line in fp
                    if line.strip().startswith('<') and line.strip().endswith('>')
                ]
        except FileNotFoundError:
            self.file_data = []

        return self.file_data

    def get_file_version(self) -> str:
        version = ''
        for line in self.read_file():
            if 'fileVersion' in line:
                version = self.get_data_between_tags(line, 'fileVersion')
                break
        return version

    @staticmethod
    def get_data_between_tags(data: str, tag_name: str) -> str:
        return data.split(f'<{tag_name}>')[1].split(f'</{tag_name}>')[0]





# ----------------------------------------------------------------------------------------------------------------------
# This isn't really an entry point for executing this file stand-alone as nothing will happen.  This is just here
# to satisfy linters not seeing the _ declaration.
if __name__ == '__main__':
    def _(unused):  # Just used to stop pycharm from complaining
        return ''
    print('Please don\'t run me directly!')

# ----------------------------------------------------------------------------------------------------------------------
