#!/usr/bin/env python3

# ----------------------------------------------------------------------------------------------------------------------
# app_paths.py

"""
Where pfeMAME's files live.

  app_dir()   The application folder: images, locales, toolbar icons, the manual, catver.ini as shipped...
              (read-only as far as pfeMAME is concerned - an update may replace anything in it).

  data_dir()  The user's own data: pfemame.ini, favorites / ratings / runs / watchlist / categories, the online ROM
              source logins, the ROM database cache, the log file and backups.

Installed (frozen) builds keep the user's data in the normal per-user location for the operating system, so an
update can never overwrite or delete it, and a macOS app bundle isn't modified (which breaks its code signature):

    Windows  %APPDATA%\\pfeMAME
    macOS    ~/Library/Application Support/pfeMAME
    Linux    $XDG_DATA_HOME/pfemame   (normally ~/.local/share/pfemame)

The data stays in the application folder (the old behaviour) when:
  * pfeMAME is run from source (development), or
  * a file called 'portable.txt' exists in the application folder (e.g. a copy on a USB stick with MAME), or
  * the per-user folder cannot be created.
The environment variable PFEMAME_DATA_DIR overrides everything.

The first time an installed build uses the per-user folder, the existing data files are COPIED there from the
application folder (the originals are left where they are) and a note is written explaining where they went.

This module has no wxPython dependency.
"""

import glob
import os
import shutil
import sys
import threading

APP_NAME = 'pfeMAME'
PORTABLE_MARKER = 'portable.txt'
MOVED_NOTE = 'SETTINGS_MOVED.txt'

# The user's data files (see also BACKUP_FILES in pfemame.py, which is the subset that is backed up)
DATA_FILES = ['pfemame.ini', 'categories.dat', 'favorites.dat', 'watchlist.dat', 'ratings.dat', 'runs.dat',
              'non_mame_emulators.xml', 'rom_sources.dat', 'play_stats.json', 'slot_presets.json']
DATA_GLOBS = ['mylist.db*']     # ROM database cache (dbm may use several files) - copied to save a rebuild
DATA_FOLDERS = ['backups']

_lock = threading.Lock()
_data_dir: str | None = None


# ----------------------------------------------------------------------------------------------------------------------
def app_dir() -> str:
    """
    Determine the full path to my location - this is complex and has been tested
    under Linux & windows, from editors, command lines, pyinstaller, py2exe,
    and from desktop shortcuts.
    """
    basis = sys.executable if hasattr(sys, 'frozen') else sys.argv[0]
    path = os.path.split(basis)[0]
    # In command line execution of scripts under Linux this method fails so apply this fallback
    if path == '':
        path = os.path.abspath('./')

    # When frozen inside a macOS .app bundle the executable lives in <bundle>.app/Contents/MacOS while the bundled
    # data may sit in the adjacent Contents/Resources folder.  Return whichever of the two actually contains our
    # resources ('images' always ships with the app, so use it as the marker).
    if hasattr(sys, 'frozen') and sys.platform == 'darwin':
        parent, leaf = os.path.split(path)
        if leaf == 'MacOS' and os.path.basename(parent) == 'Contents':
            resources_dir = os.path.join(parent, 'Resources')
            if os.path.isdir(os.path.join(resources_dir, 'images')):
                return resources_dir
    return path


def platform_data_dir() -> str:
    """The per-user data folder for this operating system (not created here)."""
    if sys.platform == 'win32':
        base = os.environ.get('APPDATA') or os.path.join(os.path.expanduser('~'), 'AppData', 'Roaming')
        return os.path.join(base, APP_NAME)
    if sys.platform == 'darwin':
        return os.path.join(os.path.expanduser('~'), 'Library', 'Application Support', APP_NAME)
    base = os.environ.get('XDG_DATA_HOME') or os.path.join(os.path.expanduser('~'), '.local', 'share')
    return os.path.join(base, APP_NAME.lower())


def _choose_data_dir() -> str:
    override = os.environ.get('PFEMAME_DATA_DIR')
    if override:
        os.makedirs(override, exist_ok=True)
        return os.path.abspath(override)

    application = app_dir()
    if os.path.exists(os.path.join(application, PORTABLE_MARKER)) or not getattr(sys, 'frozen', False):
        return application

    target = platform_data_dir()
    try:
        os.makedirs(target, exist_ok=True)
    except OSError:
        return application      # Can't create it - keep working from the application folder
    return target


def migrate_data(source: str, target: str) -> list[str]:
    """
    Copy the user's data from the application folder to the data folder, the first time only (i.e. when the data
    folder has no pfemame.ini yet but the application folder does).  The originals are left in place.
    Returns the names copied.
    """
    if os.path.normcase(os.path.abspath(source)) == os.path.normcase(os.path.abspath(target)):
        return []
    if os.path.exists(os.path.join(target, 'pfemame.ini')) or not os.path.exists(os.path.join(source, 'pfemame.ini')):
        return []

    copied = []
    names = [n for n in DATA_FILES if os.path.isfile(os.path.join(source, n))]
    for pattern in DATA_GLOBS:
        names += [os.path.basename(p) for p in glob.glob(os.path.join(source, pattern)) if os.path.isfile(p)]
    for name in names:
        shutil.copy2(os.path.join(source, name), os.path.join(target, name))
        copied.append(name)
    for folder in DATA_FOLDERS:
        if os.path.isdir(os.path.join(source, folder)) and not os.path.exists(os.path.join(target, folder)):
            shutil.copytree(os.path.join(source, folder), os.path.join(target, folder))
            copied.append(folder + '/')

    note = (f'pfeMAME now keeps your settings, favourites, ratings and ROM database in:\n\n    {target}\n\n'
            f'They were copied there from this folder on first start, so that software updates can never '
            f'overwrite them.\nThe copies in this folder are no longer used and can be deleted.\n\n'
            f'To keep using this folder instead (e.g. a portable copy on a USB stick), create an empty file '
            f'called {PORTABLE_MARKER} here.\n')
    try:
        with open(os.path.join(source, MOVED_NOTE), 'w', encoding='utf-8') as handle:
            handle.write(note)
    except OSError:
        pass
    return copied


def data_dir() -> str:
    """The folder holding the user's data (created and, on first use, migrated - see the module notes)."""
    global _data_dir
    with _lock:
        if _data_dir is None:
            chosen = _choose_data_dir()
            try:
                copied = migrate_data(app_dir(), chosen)
                if copied:
                    print(f'pfeMAME: copied {len(copied)} data file(s) to {chosen}')
            except OSError as e:
                print(f'pfeMAME: unable to copy existing data to {chosen}: {e}')
            _data_dir = chosen
        return _data_dir


def data_path(*parts: str) -> str:
    """Full path of a file in the data folder, e.g. data_path('favorites.dat')."""
    return os.path.join(data_dir(), *parts)
