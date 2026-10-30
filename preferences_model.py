#!/usr/bin/env python3

# ----------------------------------------------------------------------------------------------------------------------
# preferences_model.py

"""
The data side of the preferences window (preferences.py), kept free of wx so that it can be tested on its own.

  * The tables of preferences: those kept in pfemame.ini and the MAME options kept in mame.ini / ROM INI files.
  * Reading and building ROM specific INI files.

A ROM INI file written by pfeMAME looks like this (sections other than the game preferences are only there when
they have something in them, the slot and manual sections only for systems):

    # File created by pfeMAME
    #
    # spectrum game.tzx
    #
    # Game preferences section
    cheat 1                         <- only the MAME options that differ from mame.ini
    #
    # OTHER SETTINGS
    joystick_deadzone 0.2           <- lines pfeMAME doesn't manage (e.g. added by hand), kept as they are
    # END OF OTHER SETTINGS
    #
    # SLOT DEVICES
    exp melodik
    exp:melodik:exp fuller #(SUB)(PARENT=exp:melodik)
    # END OF SLOT DEVICES
    #
    #
    # MANUAL DATA
    ...
    # END OF MANUAL DATA
    #
    # END OF FILE
"""

from typing import NamedTuple


class MameOption(NamedTuple):
    attr: str       # Preferences attribute (the name the notebook panels send values for)
    ini_key: str    # Option name in mame.ini / ROM INI files
    is_bool: bool   # Stored as 1 / 0 in the INI file, held as 'True' / 'False' in the window


class PfeMameOption(NamedTuple):
    attr: str
    ini_key: str    # Key in the [preferences] section of pfemame.ini

    @property
    def default(self) -> str:
        """Used if pfemame.ini doesn't have the key"""
        return PFEMAME_DEFAULTS['preferences'][self.ini_key]


# The default for each pfemame.ini setting: the one place they are set.  A new pfemame.ini is written with these
# (iniFile.create_ini_file), and iniFile.read_ini_file returns them for a setting the file doesn't have (e.g. one
# added in a later version), so a missing setting works the same as on a new installation everywhere.
# Not here: the language (empty until one is chosen), the fonts and colours (see iniFile.create_ini_file and
# functions.get_application_colors), the catver.ini path (it depends on where pfeMAME is) and the values pfeMAME
# remembers rather than the user sets (e.g. the [system] section and Tile View's position).
PFEMAME_DEFAULTS = {
    'preferences': {
        'enablejoystickmainview': 'True',
        'enablejoysticktileview': 'True',
        'joystickselected': '',
        'joystick_polling_freq': '20',
        'view': 'False',
        'tiledim': 'True',
        'tilesize': 'Medium',
        'tileletterjump': 'False',
        'tilemouse': 'False',
        'brightness': '0.4',
        'showgameicons': 'True',
        'iconsize': '16',
        'mainview': 'All',
        'highlitemissing': 'True',
        'dayscheckcache': '50',
        'checkdatabaseage': 'True',
        'systemssupport': 'True',
        'uselastselected': 'True',
        'videoautoload': 'True',
        'videodisable': 'False',
        'softwarevideo': 'False',
        'clickfavrating': 'False',
        'suppressshortname': 'False',
        'checkcatverversion': 'True',
        'checksoftwareversion': 'True',
        'disableartwork': 'False',
        'screensavertime': '10',
        'screensaverhidetitle': 'True',
        'fullsystemsmethod': 'False',
        'force_all_fullscreen': 'False',
        'force_all_window': 'False',
        'flashiferrors': 'True',
        'mainwindowfullscreen': 'False',
        'recallromlistcolumns': 'True',
    },
    'folders': {
        'video': '',
    },
    'path': {
        'mame_executable': '',
        'history_dat': '',
    },
}


# MAME options shown in the preferences window
MAME_OPTIONS = (
    MameOption('pref_cheat', 'cheat', True),
    MameOption('pref_window', 'window', True),
    MameOption('pref_artwork_crop', 'artwork_crop', True),
    MameOption('pref_skip_game_info', 'skip_gameinfo', True),
    MameOption('pref_auto_frame_skip', 'autoframeskip', True),
    MameOption('pref_video', 'video', False),
    MameOption('pref_osd_key', 'uimodekey', False),
    MameOption('pref_use_mouse', 'mouse', True),
    MameOption('pref_use_joystick', 'joystick', True),
    MameOption('pref_use_lightgun', 'lightgun', True),
    MameOption('pref_logfile', 'log', True),
    MameOption('pref_verbose', 'verbose', True),
    MameOption('pref_offscreen_reload', 'offscreen_reload', True),
    MameOption('pref_sound_samplerate', 'samplerate', False),
    MameOption('pref_sound_samples', 'samples', True),
    MameOption('pref_sound_volume', 'volume', False),
    MameOption('pref_sound_subsystem', 'sound', False),
    MameOption('pref_sound_latency', 'audio_latency', False),
    MameOption('pref_bgfx_backend', 'bgfx_backend', False),
    MameOption('pref_bgfx_screenchains', 'bgfx_screen_chains', False),
    MameOption('pref_bgfx_shadowmask', 'bgfx_shadow_mask', False),
    MameOption('pref_bios', 'bios', False),
)

# pfeMAME's own preferences.  Tile View's brightness is not here: Tile View saves it itself.
PFEMAME_OPTIONS = (
    PfeMameOption('pref_joystick_selected', 'joystickselected'),
    PfeMameOption('pref_show_game_icons', 'showgameicons'),
    PfeMameOption('pref_tile_dim', 'tiledim'),
    PfeMameOption('pref_tile_size', 'tilesize'),
    PfeMameOption('pref_enable_joystick_mainview', 'enablejoystickmainview'),
    PfeMameOption('pref_enable_joystick_tileview', 'enablejoysticktileview'),
    PfeMameOption('pref_view', 'view'),
    PfeMameOption('pref_main_view', 'mainview'),
    PfeMameOption('pref_highlight_missing', 'highlitemissing'),
    PfeMameOption('pref_days_check_cache', 'dayscheckcache'),
    PfeMameOption('pref_screensaver_time', 'screensavertime'),
    PfeMameOption('pref_screensaver_hide_title', 'screensaverhidetitle'),
    PfeMameOption('pref_system_support', 'systemssupport'),
    PfeMameOption('pref_short_name_global_suppress', 'suppressshortname'),
    PfeMameOption('pref_check_database_age', 'checkdatabaseage'),
    PfeMameOption('pref_use_last_selected', 'uselastselected'),
    PfeMameOption('pref_video_autoload', 'videoautoload'),
    PfeMameOption('pref_video_disable', 'videodisable'),
    PfeMameOption('pref_software_video', 'softwarevideo'),
    PfeMameOption('pref_icon_size', 'iconsize'),
    PfeMameOption('pref_click_fav_rating', 'clickfavrating'),
    PfeMameOption('pref_full_systems_method', 'fullsystemsmethod'),
    PfeMameOption('pref_check_catver_version', 'checkcatverversion'),
    PfeMameOption('pref_force_all_fullscreen', 'force_all_fullscreen'),
    PfeMameOption('pref_force_all_window', 'force_all_window'),
    PfeMameOption('pref_check_software_version', 'checksoftwareversion'),
    PfeMameOption('pref_flash_messages_if_error', 'flashiferrors'),
    PfeMameOption('pref_disable_artwork', 'disableartwork'),
    PfeMameOption('pref_set_window_fullscreen', 'mainwindowfullscreen'),
    PfeMameOption('pref_recall_column_widths', 'recallromlistcolumns'),
    PfeMameOption('pref_tile_letter_jump', 'tileletterjump'),
    PfeMameOption('pref_tile_mouse', 'tilemouse'),
)

# Application colours: (attribute / pfemame.ini key, functions.get_application_colors() name)
COLOR_OPTIONS = (
    ('window_background_color', 'window_background'),
    ('text_color', 'text'),
    ('row_alt_1_color', 'row_alt_1'),
    ('row_alt_2_color', 'row_alt_2'),
    ('text_background_color', 'text_background'),
    ('missing_game_color', 'missing_game'),
    ('control_bar_color', 'control_bar'),
    ('selected_row_color', 'selected_row'),
    ('selected_row_background_color', 'selected_row_background'),
    ('ribbon_bar_color', 'ribbon_bar'),
    ('ribbon_item_highlight', 'ribbon_item_highlight'),
    ('scrollbar_thumb_color', 'scrollbar_thumb'),
    ('scrollbar_track_color', 'scrollbar_track'),
    ('button_background_color', 'button_background'),
)

# Values the panels send that are not saved as preferences themselves
EXTRA_VARIABLES = ('slot_rows', 'manual_config_control_value')

SETTABLE = frozenset([option.attr for option in MAME_OPTIONS] + [option.attr for option in PFEMAME_OPTIONS] +
                     [attr for attr, _name in COLOR_OPTIONS] + list(EXTRA_VARIABLES))


# ----------------------------------------------------------------------------------------------------------------------
def mame_ini_value(raw: str, is_bool: bool) -> str:
    """A value as read from a MAME INI file, in the form the window holds it ('True' / 'False' for booleans)."""
    if is_bool:
        return 'True' if raw == '1' else 'False'
    return raw


def mame_defaults(platform: str) -> list[tuple[str, tuple[str, ...], str]]:
    """(attribute, values that are not valid, value to use instead) for MAME options that need a valid value."""
    windows = platform == 'windows'
    return [
        ('pref_video', ('',), 'd3d' if windows else 'soft'),
        ('pref_sound_samplerate', ('0', ''), '48000'),
        ('pref_sound_samples', ('',), 'True'),
        ('pref_sound_volume', ('',), '0'),
        ('pref_sound_subsystem', ('0', ''), 'dsound' if windows else 'sdl'),
        ('pref_sound_latency', ('', '0'), '1'),
    ]


def apply_mame_defaults(values: dict[str, str], platform: str) -> dict[str, str]:
    """Return a copy of {attribute: value} with invalid MAME option values replaced by valid defaults."""
    fixed = dict(values)
    for attr, invalid, default in mame_defaults(platform):
        if attr in fixed and fixed[attr] in invalid:
            fixed[attr] = default
    return fixed


def int_in_range(text: str, low: int, high: int) -> bool:
    """True if text is a whole number from low to high."""
    try:
        number = int(str(text).strip())
    except ValueError:
        return False
    return low <= number <= high


# ----------------------------------------------------------------------------------------------------------------------
def read_lines(path: str) -> list[str]:
    """
    Read a text file into a list of lines (each ending in '\\n', like readlines()).  Files are UTF-8, but older ROM
    INI files may have been saved in the Windows code page, so fall back to that rather than failing.
    Raises OSError if the file can't be read.
    """
    with open(path, 'rb') as handle:
        data = handle.read()
    try:
        text = data.decode('utf-8-sig')
    except UnicodeDecodeError:
        text = data.decode('cp1252', errors='replace')
    return [line + '\n' for line in text.splitlines()]


# ----------------------------------------------------------------------------------------------------------------------
HEADER_LINE = '# File created by pfeMAME'
PREFERENCES_MARKER = '# Game preferences section'
OTHER_START, OTHER_END = '# OTHER SETTINGS', '# END OF OTHER SETTINGS'
SLOTS_START, SLOTS_END = '# SLOT DEVICES', '# END OF SLOT DEVICES'
MANUAL_START, MANUAL_END = '# MANUAL DATA', '# END OF MANUAL DATA'
END_OF_FILE = '# END OF FILE'


def _section(lines: list[str], start: str, end: str) -> tuple[int, int] | None:
    """(index of the start marker, index of the end marker) of a section, or None if it isn't complete."""
    try:
        first = lines.index(start)
        return first, lines.index(end, first + 1)
    except ValueError:
        return None


def unmanaged_lines(content: list[str], replaces_slots_and_manual: bool) -> list[str]:
    """
    The setting lines of an existing ROM INI file that pfeMAME doesn't write itself, so they can be kept.

    Comments and blank lines are dropped, as are the MAME options pfeMAME manages (they are written from the window).
    For a system the slot and manual sections are rewritten from the Slots tab, so their lines are dropped too.  For
    anything else those sections are not shown in the window, so their lines are kept like any other setting.
    """
    lines = [line.rstrip('\r\n').strip() for line in content]
    managed = {option.ini_key for option in MAME_OPTIONS}
    skip = set()
    if replaces_slots_and_manual:
        for start, end in ((SLOTS_START, SLOTS_END), (MANUAL_START, MANUAL_END)):
            section = _section(lines, start, end)
            if section:
                skip.update(range(section[0], section[1] + 1))

    kept = []
    for index, line in enumerate(lines):
        if index in skip or not line or line.startswith('#'):
            continue
        if line.split()[0] in managed:
            continue
        kept.append(line)
    return kept


def format_slot_line(slot_name: str, option: str, parent: str) -> str:
    """One slot line of the ROM INI file (sub-slots carry their full path plus a note of the parent)."""
    if slot_name.startswith(':'):
        return f'{parent}{slot_name} {option} #(SUB)(PARENT={parent})'
    return f'{slot_name} {option}'


def _section_lines(content: list[str], start: str, end: str) -> list[str] | None:
    """The lines inside a section of an existing file (without the markers), or None if it has no such section."""
    lines = [line.rstrip('\r\n').strip() for line in content]
    section = _section(lines, start, end)
    return None if section is None else lines[section[0] + 1:section[1]]


def build_rom_ini(content: list[str],
                  title: str,
                  values: dict[str, str],
                  global_values: dict[str, str],
                  is_a_system: bool = False,
                  slot_rows: list[tuple[str, str, str]] | None = None,
                  manual_text: str | None = None) -> list[str]:
    """
    Build the lines of a ROM INI file.

    :param content:       the lines of the existing ROM INI file ([] if there isn't one)
    :param title:         the ROM (and system program) name for the header
    :param values:        {attribute: value} of the MAME options as set in the window
    :param global_values: {attribute: value} of the same options in mame.ini.  Only options that differ are written,
                          so that a later change to mame.ini still applies to this ROM.
    :param is_a_system:   True if the window has a Slots tab (the slot and manual sections are written)
    :param slot_rows:     [(slot name, option name, parent)] from the Slots tab.  None if the Slots tab hasn't been
                          changed: the file's own slot section is kept.
    :param manual_text:   the Manual Configuration text.  None if it hasn't been changed: the file's own is kept.
    """
    output = [HEADER_LINE, '#', f'# {title}'.rstrip(), '#', PREFERENCES_MARKER]

    for option in MAME_OPTIONS:
        value = values.get(option.attr, '')
        if value == global_values.get(option.attr, ''):
            continue
        if option.is_bool:
            value = int(value in ('True', 1))
        output.append(f'{option.ini_key} {value}')

    other = unmanaged_lines(content, replaces_slots_and_manual=is_a_system)
    if other:
        output.extend(['#', OTHER_START, *other, OTHER_END])

    if is_a_system:
        if slot_rows is None:
            slot_lines = _section_lines(content, SLOTS_START, SLOTS_END)
        else:
            slot_lines = [format_slot_line(*row) for row in slot_rows if row[0] and row[1]]
        if manual_text is None:
            manual_lines = _section_lines(content, MANUAL_START, MANUAL_END)
        else:
            manual_lines = [line.strip() for line in manual_text.splitlines()]

        # No slot section means "MAME's defaults" to the Slots tab, so don't add an empty one
        if slot_lines is not None:
            output.extend(['', '#', SLOTS_START, *slot_lines, SLOTS_END, '#'])
        if manual_lines is not None:
            output.extend(['', '#', MANUAL_START, *manual_lines, MANUAL_END])

    output.extend(['#', END_OF_FILE])
    return output
