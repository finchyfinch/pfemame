#!/usr/bin/env python3

# ----------------------------------------------------------------------------------------------------------------------
# mame_paths.py

"""
Helpers for running MAME and for finding things in MAME's configured folders.

This module deliberately has no wxPython dependency so that it can be used from worker processes / threads and from
the test suite.  functions.py re-exports everything here, so existing code can keep using functions.<name>.
"""

import os
import re
import subprocess
import sys

# ----------------------------------------------------------------------------------------------------------------------
# Keyword arguments for every subprocess call that runs MAME or an emulator.
#
# pfeMAME used to pass shell=True on Windows, mostly because Python then hides the console window.  Going through
# cmd.exe also re-parsed the arguments: a file name without spaces containing & ^ | or %NAME% was mangled - e.g.
# 'Tom&Jerry.zip' reached MAME as 'Tom' and cmd.exe then tried to run 'Jerry.zip' as a command.
# CREATE_NO_WINDOW hides the console without involving a shell at all.
NO_CONSOLE: dict = {'creationflags': subprocess.CREATE_NO_WINDOW} if sys.platform == 'win32' else {}

ARCHIVE_EXTENSIONS = ('.zip', '.7z')


def mame_working_dir(path_mame_exe: str) -> str | None:
    """
    The folder MAME should be run from.  MAME resolves relative paths in mame.ini (e.g. 'rompath roms') against its
    working directory, so run it from its own folder.  Pass the result as subprocess cwd= - never os.chdir(), which
    changes the directory for the whole application, including other threads.
    Returns None (inherit) when MAME is found on the PATH rather than via a file path.
    """
    if path_mame_exe and os.path.isfile(path_mame_exe):
        return os.path.dirname(os.path.abspath(path_mame_exe))
    return None


def mame_version(path_mame_exe: str, timeout: int = 30) -> tuple[str, str]:
    """
    Ask MAME for its version ('<mame> -?' starts e.g. 'MAME v0.289 (mame0289)').  Safe to call from a worker thread.
    Returns (version, '') e.g. ('0.289', ''), or ('', what went wrong) if MAME couldn't be run or didn't say.
    """
    if not path_mame_exe:
        return '', 'no MAME executable is set'
    try:
        result = subprocess.run([path_mame_exe, '-?'], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                errors='replace', timeout=timeout, cwd=mame_working_dir(path_mame_exe), **NO_CONSOLE)
    except subprocess.TimeoutExpired:
        return '', f'no answer within {timeout} seconds'
    except (OSError, ValueError) as e:     # Not found, not a program (WinError 193), no permission...
        return '', str(e)
    match = re.search(r'v(\d+\.\d+)', result.stdout or '')
    return (match.group(1), '') if match else ('', 'it did not report a MAME version')


def split_mame_paths(value: str, path_mame_exe: str = '') -> list[str]:
    """
    Turn a mame.ini multi-path value into a list of usable folder paths, the way MAME itself reads it:
    ';' separated, optionally quoted, $VARIABLES / ~ expanded, and relative entries resolved against MAME's own
    folder.

        'roms;"D:\\More Roms"'  ->  ['C:\\MAME\\roms', 'D:\\More Roms']
    """
    base = mame_working_dir(path_mame_exe) or ''
    folders = []
    for entry in (value or '').strip().strip('"').split(';'):
        entry = entry.strip().strip('"')
        if not entry:
            continue
        entry = os.path.expanduser(os.path.expandvars(entry))
        if base and not os.path.isabs(entry):
            entry = os.path.join(base, entry)
        entry = os.path.normpath(entry)         # e.g. '$HOME/.mame' expanded on Windows
        if entry not in folders:
            folders.append(entry)
    return folders


def resolve_mame_folder(value: str, path_mame_exe: str = '') -> str:
    """
    A single-folder mame.ini value (e.g. cfg_directory 'cfg', or '$HOME/.mame/cfg' on Linux) as a usable path,
    resolved the way MAME reads it (see split_mame_paths).  '' if it isn't set.
    """
    folders = split_mame_paths(value, path_mame_exe)
    return folders[0] if folders else ''


def mame_ini_candidates(path_mame_exe: str, platform: str) -> list[str]:
    """
    The places mame.ini is usually kept, most likely first.  platform is 'windows', 'mac' or 'linux'
    (functions.get_platform()).  MAME itself looks in its own folder on Windows, and in
    ~/Library/Application Support/mame then ~/.mame on macOS / ~/.mame on Linux; ~/mame and ~ are common choices too.
    """
    home = os.path.expanduser('~')
    home = None if home == '~' else home        # No HOME and no password entry to fall back on
    exe_folder = mame_working_dir(path_mame_exe)

    def at_home(*parts):
        return os.path.join(home, *parts) if home else None

    if platform == 'windows':
        folders = [exe_folder]
    elif platform == 'mac':
        folders = [exe_folder, at_home('Library', 'Application Support', 'mame'), at_home('mame'),
                   at_home('.mame'), home]
    else:
        folders = [at_home('.mame'), at_home('mame'), at_home('Mame'), home, exe_folder]   # exe_folder: portable
    candidates = []
    for folder in folders:
        if folder and os.path.join(folder, 'mame.ini') not in candidates:
            candidates.append(os.path.join(folder, 'mame.ini'))
    return candidates


def find_mame_ini(path_mame_exe: str, platform: str, current: str = '') -> str:
    """
    Where mame.ini is for this MAME executable: the current mame.ini if it still exists in one of the usual places
    (so a deliberate choice such as ~/mame is kept), otherwise the first usual place that has one, otherwise where
    one would normally be created (MAME's folder on Windows / macOS, ~/.mame on Linux).  '' if there is nowhere.
    """
    candidates = mame_ini_candidates(path_mame_exe, platform)

    def same(path):
        return os.path.normcase(os.path.abspath(path))

    if current and os.path.isfile(current) and same(current) in {same(c) for c in candidates}:
        return current
    for candidate in candidates:
        if os.path.isfile(candidate):
            return candidate
    return candidates[0] if candidates else ''


def _same_folder(first: str, second: str) -> bool:
    return os.path.normcase(os.path.abspath(first)) == os.path.normcase(os.path.abspath(second))


def ini_search_folders(inipath: str, path_mame_exe: str = '', path_mame_ini: str = '') -> list[str]:
    """
    The folders MAME looks in for a ROM's own INI file (e.g. pacman.ini) when pfeMAME runs a game, in MAME's order:
    the mame.ini file's folder (pfeMAME runs MAME with '-inipath <that folder>;<inipath>'), then each inipath folder
    resolved the way MAME reads it (relative to the MAME folder, $VARIABLES and ~ expanded).  Existing folders only.
    """
    candidates = [os.path.dirname(os.path.abspath(path_mame_ini))] if path_mame_ini else []
    candidates += split_mame_paths(inipath, path_mame_exe)
    folders = []
    for folder in candidates:
        if os.path.isdir(folder) and not any(_same_folder(folder, seen) for seen in folders):
            folders.append(folder)
    return folders


def rom_ini_folder(inipath: str, path_mame_exe: str = '') -> str:
    """
    Where a new ROM INI file is saved: the first existing inipath folder that isn't MAME's own folder (so 'ini' for
    MAME's Windows default '.;ini;ini/presets', ~/.mame for the Linux default), otherwise the first existing one.
    '' if none of the inipath folders exist.
    """
    folders = [folder for folder in split_mame_paths(inipath, path_mame_exe) if os.path.isdir(folder)]
    mame_folder = mame_working_dir(path_mame_exe)
    for folder in folders:
        if not mame_folder or not _same_folder(folder, mame_folder):
            return folder
    return folders[0] if folders else ''


def find_rom_ini(file_name: str, inipath: str, path_mame_exe: str = '', path_mame_ini: str = '') -> str:
    """
    The ROM INI file called file_name (e.g. 'pacman.ini' or 'spectrum_system_game.tzx.ini') that MAME will use - the
    first one in ini_search_folders - so that an existing file is always read and updated where it is.  If there is
    none yet, where a new one goes (rom_ini_folder).  '' if there is nowhere to put one.
    """
    for folder in ini_search_folders(inipath, path_mame_exe, path_mame_ini):
        if os.path.isfile(os.path.join(folder, file_name)):
            return os.path.join(folder, file_name)
    folder = rom_ini_folder(inipath, path_mame_exe)
    return os.path.join(folder, file_name) if folder else ''


def find_ui_ini(inipath: str, path_mame_exe: str = '') -> str:
    """
    Where MAME keeps ui.ini, given the mame.ini 'inipath' value (a ';' separated list such as '.;ini;ini/presets',
    relative to MAME's own folder).  That is the first inipath folder that already has a ui.ini, otherwise the first
    inipath folder that exists (where it would be created).  Returns '' if none of the folders exist.
    """
    folders = split_mame_paths(inipath, path_mame_exe)
    for folder in folders:
        if os.path.isfile(os.path.join(folder, 'ui.ini')):
            return os.path.join(folder, 'ui.ini')
    for folder in folders:
        if os.path.isdir(folder):
            return os.path.join(folder, 'ui.ini')
    return ''


def _looks_like_rom_set_folder(path: str, max_entries: int = 500) -> bool:
    """
    MAME accepts a ROM set as a folder (roms/pacman/<rom files>) and CHD games as roms/<game>/<disk>.chd.  Software
    list folders (roms/nes/*.zip) must not be mistaken for a machine's ROM set, so a folder only counts if it holds
    a CHD or at least one file that isn't an archive.
    """
    try:
        with os.scandir(path) as entries:
            for count, entry in enumerate(entries):
                if count >= max_entries:
                    break
                if entry.is_file() and not entry.name.lower().endswith(ARCHIVE_EXTENSIONS):
                    return True
    except OSError:
        pass
    return False


def find_rom_sets(folders: list[str]) -> set[str]:
    """
    Lower-case names of every ROM set found in the rompath folders: 'pacman' for pacman.zip / pacman.7z, and for a
    pacman/ folder of ROM files or CHDs.
    """
    names = set()
    for folder in folders:
        try:
            with os.scandir(folder) as entries:
                for entry in entries:
                    lower = entry.name.lower()
                    if entry.is_file():
                        names.add(os.path.splitext(lower)[0])
                    elif entry.is_dir() and lower not in names and _looks_like_rom_set_folder(entry.path):
                        names.add(lower)
        except OSError:
            continue
    return names


def rom_set_present(folders: list[str], rom_name: str) -> bool:
    """True if the ROM set exists in any rompath folder as a .zip, .7z or ROM folder."""
    for folder in folders:
        if any(os.path.isfile(os.path.join(folder, rom_name + ext)) for ext in ARCHIVE_EXTENSIONS):
            return True
        candidate = os.path.join(folder, rom_name)
        if os.path.isdir(candidate) and _looks_like_rom_set_folder(candidate):
            return True
    return False


def find_in_folders(folders: list[str], *names: str) -> str | None:
    """Return the first existing path folder/name for any of the folders and names given, or None."""
    for folder in folders:
        for name in names:
            candidate = os.path.join(folder, name)
            if os.path.exists(candidate):
                return candidate
    return None
