#!/usr/bin/python3

# ----------------------------------------------------------------------------------------------------------------------
# iniFile.py

"""
INI file processing functions

  * pfemame.ini (pfeMAME's own settings, in the user data folder): read_ini_file, set_ini_file_variables,
    create_ini_file (a new file with the defaults from preferences_model.PFEMAME_DEFAULTS) and convert_old_settings.
  * mame.ini / ui.ini (MAME's settings): get_from_mameini and set_to_mameini_bulk, which read and write them the way
    MAME does.

Reads are served from an in-memory copy of pfemame.ini that is only re-parsed when the file changes on disk (the
application makes well over a hundred reads during startup and preference changes).  All writes go to a temporary
file of their own which then replaces the real one (atomic_write_text), so a crash or power cut part way through can
never leave a truncated file.  A pfemame.ini save that fails (e.g. the file is read-only) is logged rather than
raised, and one hand-edited or saved by a text editor (BOM, ANSI, duplicate names, a single '%') is still read.
"""

# Import python & wxPython modules
import wx
import os
import configparser
import errno
import locale
import logging
import re
import stat
import tempfile
import threading
import time

# Import my own modules
import functions
import global_defaults as gd
from preferences_model import PFEMAME_DEFAULTS

_cache_lock = threading.Lock()
_write_lock = threading.Lock()                  # Held by set_ini_file_variables while it reads, changes and writes
# key = (path, mtime_ns, size).  parser is None if that version of the file couldn't be read; reported = the key of
# the last version a problem was logged for, so it is only logged once.
_cache: dict = {'key': None, 'parser': None, 'reported': None}
_reported_values: set = set()                   # (section, name, value) of bad numbers read_ini_int has logged
_PERCENT = re.compile('%%|%')                   # An escaped '%%', or a single '%' that still needs escaping
_UMASK = os.umask(0)                            # The process's umask (it can only be read by setting it) ...
os.umask(_UMASK)                                # ... so put it straight back


# ----------------------------------------------------------------------------------------------------------------------
def atomic_write_text(path: str, text: str, encoding: str = 'utf-8') -> None:
    """
    Write text to path via a temporary file + os.replace, so the file is either the old or the new version - never
    half written.  Windows can briefly refuse the replace while another process (e.g. a virus scanner) has the file
    open, so retry a few times before giving up.

    Each write has its own temporary file (two writes at once can't mix their text), removed again if the write
    fails.  A read-only file is refused with PermissionError on every system (Linux would otherwise replace it), and
    the file keeps its permissions.
    """
    path = os.path.realpath(path)   # Replace the real file if path is a symlink, not the link itself
    try:
        mode = stat.S_IMODE(os.stat(path).st_mode)
    except FileNotFoundError:
        mode = 0o666 & ~_UMASK      # As a file created with open() gets
    else:
        if not os.access(path, os.W_OK):
            raise PermissionError(errno.EACCES, 'The file is read-only', path)
    folder, name = os.path.split(path)
    fd, temp_path = tempfile.mkstemp(prefix=f'{name}.', suffix='.tmp', dir=folder)
    try:
        with open(fd, 'w', encoding=encoding) as handle:   # Text mode: platform line endings, as before
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_path, mode)   # mkstemp makes it private to the user
        for attempt in range(5):
            try:
                os.replace(temp_path, path)
                return
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.1 * (attempt + 1))
    except BaseException:
        try:
            os.remove(temp_path)
        except OSError:
            pass
        raise


def _pfemame_ini_path() -> str:
    return os.path.join(functions.data_dir(), 'pfemame.ini')


def _invalidate_cache() -> None:
    with _cache_lock:
        _cache['key'] = None
        _cache['parser'] = None


def _fallback_encoding() -> str:
    """The system's own encoding (e.g. cp1252 on Windows) - what a text editor may have saved pfemame.ini in."""
    return locale.getpreferredencoding(False)


def _read_pfemame_ini_text(ini_path: str) -> str:
    """
    The text of pfemame.ini.  pfeMAME writes it as UTF-8, but after a hand edit it may start with a BOM ("UTF-8 with
    BOM") or be in the system's encoding (Notepad's "ANSI") - both are read, and the next save writes UTF-8 again.
    Raises OSError if the file can't be read, or UnicodeDecodeError if it is in neither encoding.
    """
    with open(ini_path, 'rb') as f:
        data = f.read()
    try:
        text = data.decode('utf-8-sig')
    except UnicodeDecodeError:
        text = data.decode(_fallback_encoding())   # Strict - '?' replacements would be saved back into the file
    # Line ends become '\n' as when reading in text mode
    return text.replace('\r\n', '\n').replace('\r', '\n')


def _report_unreadable(key: tuple, error: Exception) -> None:
    """Log that pfemame.ini can't be used - once for each version of the file (call with _cache_lock held)."""
    if _cache['reported'] != key:
        _cache['reported'] = key
        logging.getLogger('>').error(f'Unable to read {key[0]}, so default settings are being used: {error}')


def _cached_parser(ini_path: str) -> configparser.ConfigParser | None:
    """Parsed pfemame.ini, re-read only when the file's modification time or size changes."""
    try:
        info = os.stat(ini_path)
    except OSError:
        return None
    key = (ini_path, info.st_mtime_ns, info.st_size)
    with _cache_lock:
        if _cache['key'] == key:
            return _cache['parser']
        # strict=False: a setting or section that appears twice (e.g. after a hand edit) is read with the last value
        # winning, as set_ini_file_variables does, instead of raising an error on every read
        parser = configparser.ConfigParser(allow_no_value=True, strict=False)
        try:
            parser.read_string(_read_pfemame_ini_text(ini_path), source=ini_path)
        except OSError as e:
            _report_unreadable(key, e)      # Not remembered: the file may only be locked for a moment
            return None
        except (UnicodeDecodeError, configparser.Error) as e:
            _report_unreadable(key, e)
            parser = None                   # Remembered, so this version of the file isn't parsed again on each read
        _cache['key'] = key
        _cache['parser'] = parser
        return parser


# ----------------------------------------------------------------------------------------------------------------------
def read_ini_file(group: str, field: str, default: str | None = None) -> str:
    """
    Read from the pfeMAME ini file.
    You can pass a default value to this function so that if no result is obtained from the read, the default
    value is passed back.

    :param group:    The group in the INI file that the field is stored within
    :param field:    The field name within the group to read the variable from
    :param default:  A default value to return if the field was not found.  Leave it out for the settings in
                     preferences_model.PFEMAME_DEFAULTS, so they get the same default everywhere ('' for others).

    :return:  Field value from INI file, or default if not found.  (For a whole number use read_ini_int.)
    """
    if default is None:
        default = PFEMAME_DEFAULTS.get(group, {}).get(field, '')
    parser = _cached_parser(_pfemame_ini_path())
    if parser is not None and parser.has_section(group) and parser.has_option(group, field):
        try:
            value = parser.get(group, field)
        except configparser.InterpolationError:
            # A single '%' (e.g. from a hand edit) - use the value as written.  It is escaped at the next save.
            value = parser.get(group, field, raw=True).replace('%%', '%')
        if value is not None:                       # None: a name without a value (e.g. a hand edit)
            return value
    return default


def read_ini_int(group: str, field: str, default: int | None = None, low: int | None = None,
                 high: int | None = None) -> int:
    """
    A whole number setting from pfemame.ini.  If it isn't one (e.g. 'abc' or '' after a hand edit) or is outside
    low..high, the default is used instead and a warning logged (once for each bad value), so a bad setting can't
    stop pfeMAME starting.

    :param default:  Leave it out for the settings in preferences_model.PFEMAME_DEFAULTS (as read_ini_file)
    """
    if default is None:
        default = int(PFEMAME_DEFAULTS[group][field])
    text = read_ini_file(group, field, str(default))
    try:
        value = int(text)
    except ValueError:
        problem = 'is not a whole number'
    else:
        if (low is None or value >= low) and (high is None or value <= high):
            return value
        problem = f'is outside {low} to {high}'
    with _cache_lock:
        report = (group, field, text) not in _reported_values
        _reported_values.add((group, field, text))
    if report:
        logging.getLogger('>').warning(f'pfemame.ini [{group}] {field} = {text!r} {problem}, so {default} is used')
    return default


# ----------------------------------------------------------------------------------------------------------------------
def _parse_keeping_comments(text: str) -> dict[str, dict[str, str | None]]:
    """
    pfemame.ini's text as {section: {name: value}}, read by the same rules as read_ini_file's configparser (so a save
    keeps everything the reader sees), but keeping the comments: they are stored under '#<n>' names as the whole
    comment line.  Names are lower case, values None for a name without one, and values continued on indented lines
    are joined with '\n'.  Values already escaped are kept, but a single '%' (e.g. from a hand edit) is escaped now.
    Comments above the first section are not kept - set_ini_file_variables writes its own header there.
    """
    ini_data: dict[str, dict[str, str | None]] = {}
    section = None
    option = None              # The setting an indented line would continue
    option_indent = 0
    for line in text.split('\n'):
        stripped = line.strip()
        if not stripped:
            continue                                # configparser lets a value continue after a blank line too
        if stripped.startswith(('#', ';')):         # configparser's full-line comment prefixes
            if section is not None:
                ini_data[section][f'#{len(ini_data[section])}'] = stripped
            continue
        indent = len(line) - len(line.lstrip())
        if section is not None and option is not None and indent > option_indent \
                and ini_data[section][option] is not None:
            ini_data[section][option] += '\n' + _PERCENT.sub('%%', stripped)
            continue
        option = None
        header = configparser.ConfigParser.SECTCRE.match(stripped)
        if header:
            section = header.group('header')
            ini_data.setdefault(section, {})
            continue
        match = configparser.ConfigParser.OPTCRE_NV.match(stripped)
        if section is None or not match:
            continue                                # configparser would refuse these lines - they can't be read
        # Lower case, as the reader ignores case in names: 'Language' and 'language' are one setting
        option = match.group('option').rstrip().lower()
        option_indent = indent
        value = match.group('value')
        ini_data[section][option] = None if value is None else _PERCENT.sub('%%', value.strip())
    return ini_data


# ----------------------------------------------------------------------------------------------------------------------
def set_ini_file_variables(data: list[tuple[str, str, str]]) -> bool:
    """
    Writes variables to the pfemame.ini file without removing comments.
    Updates values if they exist or adds them if missing.  If pfemame.ini doesn't exist yet it is created with the
    default settings first (previously the update was silently dropped).
    :param data: List of variables to write [section, variable_name, variable_value].  Pass values as they are:
                 '%' is doubled here, as read_ini_file's parser treats it as a special character.
    :return: True if saved.  If not (e.g. pfemame.ini is read-only or in use) the reason is logged and False
             returned - this never raises, so a failed save can't stop e.g. a window closing.
    """
    ini_path = _pfemame_ini_path()
    try:
        with _write_lock:           # One save at a time, so one can't undo another's change
            return _write_ini_file_variables(ini_path, data)
    except OSError as e:
        logging.getLogger('>').error(f'Unable to write {ini_path}, so these settings were not saved: {data} ({e})')
        return False


def _write_ini_file_variables(ini_path: str, data: list[tuple[str, str, str]]) -> bool:
    """set_ini_file_variables' work.  Raises OSError if pfemame.ini can't be written."""
    if not os.path.exists(ini_path):
        create_ini_file()

    try:
        text = _read_pfemame_ini_text(ini_path)
    except UnicodeDecodeError as e:
        # Writing would replace the user's file with just these settings, so leave it alone
        logging.getLogger('>').error(f'Unable to read {ini_path}, so these settings were not saved: {data} ({e})')
        return False

    ini_data = _parse_keeping_comments(text)

    # Apply updates to ini_data
    for section, key, value in data:
        if section not in ini_data:
            ini_data[section] = {}
        # Overwrite or add ('%' escaped for the reader)
        ini_data[section][key.lower()] = str(value).replace('%', '%%')

    # Write back with comments preserved
    atomic_write_text(ini_path, _ini_text(ini_data))
    _invalidate_cache()
    return True


def _ini_text(ini_data: dict[str, dict[str, str | None]]) -> str:
    """
    pfemame.ini's text for {section: {name: value}}, as _parse_keeping_comments returns it: names starting with '#'
    hold a whole comment line, a value of None is a name without a value, and a value with '\n' in it is continued on
    indented lines.  Used for every write, so a new file and a saved one look the same.
    """
    lines = ["# pfemame.ini - pfeMAME settings\n", "# Modify values as needed.\n\n"]
    for section, options in ini_data.items():
        lines.append(f"[{section}]\n")
        for key, value in options.items():
            if key.startswith("#"):
                lines.append(f"{value}\n")                  # The comment line as it was
            elif value is None:
                lines.append(f"{key}\n")                    # A name without a value
            else:
                value = value.replace('\n', '\n    ')       # A value continued on indented lines
                lines.append(f"{key} = {value}\n")
        lines.append("\n")
    return ''.join(lines)


# ----------------------------------------------------------------------------------------------------------------------
def convert_old_settings() -> None:
    """
    Move settings from older versions of pfemame.ini to the ones now used.  Called at startup; does nothing once done.
      * 'artworkdisable' (the Video tab's 'Disable the display of artwork', removed in v3.10.2) did the same as
        'disableartwork' ('Disable Artwork for all ROMs' on the pfeMAME tab), which now does it alone.
    """
    if read_ini_file('preferences', 'artworkdisable') == 'True':
        set_ini_file_variables([('preferences', 'disableartwork', 'True'), ('preferences', 'artworkdisable', 'False')])


# ----------------------------------------------------------------------------------------------------------------------
def get_from_mameini(variable: str, path_to_ini_file: str) -> str:
    """
    Read data from the mame.ini file.

    This function searches through the mame.ini file looking for the requested variable and returns its value
    if it is found. If the file or variable are not found, or if the variable doesn't have a value assigned, then
    return an empty string.

    :param variable: The name of the variable within the INI file holding the data we want to read
    :param path_to_ini_file:  The path to the mame.ini file

    :return: The value of the variable found, or an empty string if nothing was found
    """
    try:
        with open(path_to_ini_file, 'r', encoding='utf-8') as fp:
            for line in fp:
                # Strip whitespace and skip comments/blank lines
                line = line.strip()
                if not line or line.startswith(('#', ';')):
                    continue
                # As MAME reads it: the name ends at the first space or tab, and a value with spaces in it is written
                # by MAME in quotes, e.g. snapshot_directory "D:/My Snaps"
                key, *rest = line.split(None, 1)
                if key == variable:
                    value = rest[0] if rest else ''
                    if len(value) >= 2 and value[0] == value[-1] == '"':
                        value = value[1:-1]
                    return value
    except (FileNotFoundError, PermissionError, IsADirectoryError, UnicodeDecodeError):
        pass
    return ''


# ----------------------------------------------------------------------------------------------------------------------
def set_to_mameini_bulk(variables: list[tuple], path_to_ini_file: str) -> int:
    """
    Write settings to a MAME INI file (mame.ini or ui.ini), changing the lines that are there and adding the others
    at the end.  The rest of the file is kept as it is.  A file that doesn't exist is created; one that exists but
    can't be read is left alone (writing would replace it with just these settings).

    :param variables:         (value, name, convert) for each setting.  convert=True stores the value as MAME's
                              1 / 0 ('True' or 1 -> 1, anything else -> 0).
    :param path_to_ini_file:  The path to the INI file

    :return: 0 if the write was ok, -1 if the file couldn't be read or written
    """

    # A blank path would resolve to the current folder and leave a stray .tmp file beside it
    if not path_to_ini_file or not path_to_ini_file.strip():
        return -1

    # Firstly we need to read out the entire mame.ini file into a list
    try:
        # Try opening the mame.ini file at the specified standard path
        with open(path_to_ini_file, 'r', encoding='utf-8') as f:
            output = f.readlines()
    except FileNotFoundError:
        # File doesn't exist in the specified location.
        # Just ignore the error as the code below will essentially create a new file
        output = ['# INI file created by pfeMAME\n\n']
    except (OSError, UnicodeDecodeError):
        # The file is there but can't be read (locked, no permission, not UTF-8 ...).  Writing a new one would
        # replace the user's mame.ini with just these settings, so leave it alone and report the error.
        return -1

    # Now substitute the variable match for the new value.
    # If the variable doesn't currently exist in the file, then just add it at the end of the file.
    for variable in variables:
        variable_found = False
        variable_value = variable[0]
        variable_name = variable[1]
        variable_convert = variable[2]

        # If we have set 'convert' to True, then we need to correct the input 'value' as it may not be set right
        if variable_convert:
            variable_value = 1 if (variable_value == 'True' or variable_value == 1) else 0

        for index, line in enumerate(output):
            try:
                line_split = line.split()[0]
            except IndexError:
                line_split = ''

            if variable_name == line_split:
                # This is the line that needs to be changed
                output[index] = f'{variable_name}     {variable_value}\n'
                variable_found = True

        if not variable_found:
            # We never found the variable so just add it at the end - on a line of its own, even if the file's last
            # line has no line ending (e.g. after a hand edit)
            if output and not output[-1].endswith('\n'):
                output[-1] += '\n'
            output.append(f'{variable_name}     {variable_value}\n')

    # And now we can write out the new file, overwriting the existing one
    try:
        atomic_write_text(path_to_ini_file, ''.join(output))
        return 0
    except OSError:         # e.g. the folder doesn't exist, or the file is read-only
        return -1


# ----------------------------------------------------------------------------------------------------------------------
def color_to_str(color) -> str:
    """A wx.Colour as pfemame.ini stores it: '(red, green, blue, alpha)'"""
    return f'({color.Red()}, {color.Green()}, {color.Blue()}, {color.Alpha()})'


# ----------------------------------------------------------------------------------------------------------------------
def create_ini_file() -> None:
    """
    Write a new pfemame.ini with the default settings: when there is none (e.g. the first start), replacing any that
    is there.
    """
    path_to_me = functions.path_to_me()
    ini_path = _pfemame_ini_path()

    # Get defaults and convert to strings for INI.  Only the fixed colors: the ones that follow the system theme are
    # left out so the theme's current colors are used, and reading them would need wx.App, which doesn't exist yet
    # when pfemame --language creates the file on the first run.
    COLOR_DEFAULTS = gd.get_fixed_color_defaults()

    # Fonts, then the fixed colors
    fonts = {}
    for prefix, point_size, weight in (('global_font_bold', 10, wx.BOLD), ('global_font_bold_20', 20, None),
                                       ('global_font_normal', 10, wx.NORMAL), ('global_font_normal_8', 8, wx.NORMAL),
                                       ('global_font_normal_12', 12, wx.NORMAL)):
        fonts[f'{prefix}_pointsize'] = str(point_size)
        if weight is not None:
            fonts[f'{prefix}_family'] = str(wx.DEFAULT)
            fonts[f'{prefix}_style'] = str(wx.NORMAL)
            fonts[f'{prefix}_weight'] = str(weight)
    colors = {f'{name}_color' if name != 'ribbon_item_highlight' else name: color_to_str(color)
              for name, color in COLOR_DEFAULTS.items()}

    # Default config with a comment line at the top of each section ('#' names, as _ini_text writes them).  The
    # settings' defaults come from preferences_model.PFEMAME_DEFAULTS.
    default_config = {
        'preferences': {
            '#': "# Preferences section - UI, fonts, colors",
            **PFEMAME_DEFAULTS['preferences'],
            **fonts,
            **colors,
        },
        'folders': {
            '#': "# Folder locations for media",
            **PFEMAME_DEFAULTS['folders'],
        },
        'path': {
            '#': "# Executable and data file paths",
            **PFEMAME_DEFAULTS['path'],
            'catver_ini': os.path.join(path_to_me, 'catver.ini')
        }
    }
    atomic_write_text(ini_path, _ini_text(default_config))
    _invalidate_cache()
