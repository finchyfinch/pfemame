#!/usr/bin/env python3

# ----------------------------------------------------------------------------------------------------------------------
# program_cleanup.py

"""
Removes program files that older versions of pfeMAME left behind in the install folder's lib/ folder.

Updates never delete anything (neither the updater nor unzipping a new version over the old one), so files that a
newer build no longer ships stay behind - e.g. 3.10.2 dropped Qt / OpenCV's GUI libraries, pip, setuptools, reportlab,
unused wxPython modules and duplicate libraries, worth 100+ MB on Linux.

Leftovers can do more than waste space: they can stop the new version starting.  3.9.2 was built with Python 3.14 and
3.10.2 with Python 3.10, and 3.9.2's lib/backports/__init__.pyc (a Python 3.14 file that 3.10.2 doesn't ship) made
every start of 3.10.2 fail with "bad magic number in 'backports'".  So the cleanup runs before anything else is
imported.

How it works:
  * tools/setup.py writes lib/pfemame_files.txt (write_manifest) listing every file and folder the build ships in lib/.
  * The very first thing the installed (frozen) pfeMAME and pfemame_updater do is clean_before_imports(), which
    deletes everything in lib/ that isn't on that list.  It then writes lib/pfemame_files.done, so later starts skip
    the check until an update brings a new list.  pfemame.py logs what was removed (log_results) once its log is set
    up.

Only lib/ is ever touched - it holds nothing but program files (user data lives in the data folder, see app_paths.py,
or next to the program in portable mode, never in lib/).  Nothing happens when:
  * pfeMAME runs from source, or on macOS (changing an .app bundle breaks its code signature, and an update replaces
    the whole bundle anyway), or in a multiprocessing worker (the main process has already done it),
  * the list is missing (an older build), or doesn't look like a complete list (see _looks_complete).
Standard library only - this runs before any other package is imported.
"""

import logging
import os
import sys

MANIFEST_NAME = 'pfemame_files.txt'
DONE_NAME = 'pfemame_files.done'  # Written after a clean-up: the list's size and time, so the next start can skip it
_MANIFEST_HEADER = '# Files and folders (ending in /) shipped in lib/ - anything else there is deleted when pfeMAME starts'
_MINIMUM_ENTRIES = 50           # A real list has thousands of entries - fewer means it is damaged
_REQUIRED_ENTRY = 'library.zip'  # cx_Freeze's own archive of pfeMAME's Python code, in every build

_messages = []                  # (level, message) from clean_before_imports, logged later by log_results


def _key(relative_path: str) -> str:
    """The path as compared against the list.  Windows file names ignore case, so a renamed file is never deleted."""
    relative_path = relative_path.replace(os.sep, '/')
    return relative_path.casefold() if sys.platform == 'win32' else relative_path


def _entries(lib_dir: str):
    """(relative path, is a real folder) for everything in lib_dir.  Symbolic links count as files (never followed)."""
    for root, dirs, files in os.walk(lib_dir):
        for name in list(dirs):
            path = os.path.join(root, name)
            if os.path.islink(path):
                dirs.remove(name)               # Don't walk into a linked folder - the link itself is the entry
                files.append(name)
            else:
                yield os.path.relpath(path, lib_dir), True
        for name in files:
            yield os.path.relpath(os.path.join(root, name), lib_dir), False


def write_manifest(lib_dir: str) -> int:
    """Write the list of everything in lib_dir (run by tools/setup.py at the end of a build).  Returns the count."""
    lines = sorted(relative.replace(os.sep, '/') + ('/' if is_dir else '') for relative, is_dir in _entries(lib_dir))
    lines.append(MANIFEST_NAME)
    with open(os.path.join(lib_dir, MANIFEST_NAME), 'w', encoding='utf-8', newline='\n') as f:
        f.write(_MANIFEST_HEADER + '\n' + '\n'.join(sorted(set(lines))) + '\n')
    return len(lines)


def _read_manifest(path: str) -> tuple[set[str], set[str]]:
    """(files, folders) on the list, as _key()s."""
    files, folders = set(), set()
    with open(path, encoding='utf-8') as f:
        for line in f:
            line = line.rstrip('\n')
            if not line or line.startswith('#'):
                continue
            if line.endswith('/'):
                folders.add(_key(line[:-1]))
            else:
                files.add(_key(line))
    return files, folders


def _looks_complete(files: set[str]) -> bool:
    return len(files) >= _MINIMUM_ENTRIES and _key(_REQUIRED_ENTRY) in files


def remove_old_program_files(lib_dir: str, logger: logging.Logger | None = None) -> list[str]:
    """
    Delete every file and folder in lib_dir that isn't on its pfemame_files.txt list.

    :param lib_dir: The install folder's lib folder
    :param logger: Where to log what was removed (or couldn't be)
    :return: The relative paths removed
    """
    logger = logger or logging.getLogger(__name__)
    manifest = os.path.join(lib_dir, MANIFEST_NAME)
    if not os.path.isfile(manifest):
        return []
    try:
        files, folders = _read_manifest(manifest)
    except (OSError, UnicodeDecodeError) as e:
        logger.warning(f'Old program file cleanup skipped - could not read {manifest}: {e}')
        return []
    if not _looks_complete(files):
        logger.warning(f'Old program file cleanup skipped - {manifest} looks incomplete ({len(files)} files listed)')
        return []

    global _last_failed
    _last_failed = 0
    removed, freed, failed = [], 0, 0
    for relative, is_dir in list(_entries(lib_dir)):
        if is_dir or _key(relative) in files or _key(relative) == _key(DONE_NAME):
            continue
        path = os.path.join(lib_dir, relative)
        try:
            size = os.lstat(path).st_size
            os.remove(path)
            removed.append(relative)
            freed += size
        except OSError as e:
            failed += 1
            logger.debug(f'Could not remove old program file {path}: {e}')

    # Then the folders left empty (deepest first) that the build doesn't ship
    for root, dirs, _files in os.walk(lib_dir, topdown=False):
        for name in dirs:
            path = os.path.join(root, name)
            relative = os.path.relpath(path, lib_dir)
            if os.path.islink(path) or _key(relative) in folders:
                continue
            try:
                os.rmdir(path)                  # Only succeeds if it is empty
                removed.append(relative + os.sep)
            except OSError:
                pass

    if removed:
        logger.info(f'Removed {len(removed)} program file(s) / folder(s) left in {lib_dir} by an older version '
                    f'({freed / 1048576:.1f} MB)')
    if failed:
        logger.warning(f'{failed} old program file(s) in {lib_dir} could not be removed (see the debug log)')
    _last_failed = failed
    return removed


_last_failed = 0                # Files the last remove_old_program_files couldn't delete


class _Recorder:
    """Stands in for a logger before pfeMAME's log exists - log_results passes the messages on later."""
    def debug(self, message):
        _messages.append((logging.DEBUG, message))

    def info(self, message):
        _messages.append((logging.INFO, message))

    def warning(self, message):
        _messages.append((logging.WARNING, message))


def _manifest_stamp(manifest: str) -> str:
    """
    The list's size and time AND the folder it is in.  The folder matters: a marker written somewhere else (e.g. by
    the release script's start check in build/) and copied in with the files must not count - cp -a / rsync -a keep
    the list's time exactly, so size and time alone matched and the clean-up was skipped.
    """
    status = os.stat(manifest)
    return f'{status.st_size} {status.st_mtime_ns} {os.path.realpath(os.path.dirname(manifest))}'


def clean_before_imports() -> None:
    """
    Remove the files an older version left in lib/ - installed (frozen) Windows / Linux builds only.  Called first
    thing by pfemame.py and pfemame_updater.py, before anything a stale file could break is imported.  Skipped once
    it has completed for the current list (pfemame_files.done), so normal starts don't pay for the check.
    """
    if not getattr(sys, 'frozen', False) or sys.platform == 'darwin' or '--multiprocessing-fork' in sys.argv:
        return
    lib_dir = os.path.join(os.path.dirname(os.path.abspath(sys.executable)), 'lib')
    manifest = os.path.join(lib_dir, MANIFEST_NAME)
    done = os.path.join(lib_dir, DONE_NAME)
    try:
        stamp = _manifest_stamp(manifest)
        with open(done, encoding='utf-8') as f:
            if f.read().strip() == stamp:
                return                          # Already cleaned for this version
    except OSError:
        pass                                    # No list (older build), or not cleaned yet
    try:
        remove_old_program_files(lib_dir, _Recorder())
        if _last_failed == 0 and os.path.isfile(manifest):
            with open(done, 'w', encoding='utf-8') as f:
                f.write(_manifest_stamp(manifest) + '\n')
    except Exception as e:                      # Never stop pfeMAME starting
        _messages.append((logging.WARNING, f'Old program file cleanup failed: {e}'))


def log_results(logger: logging.Logger) -> None:
    """Log what clean_before_imports did, once pfeMAME's log is set up."""
    while _messages:
        level, message = _messages.pop(0)
        logger.log(level, message)
