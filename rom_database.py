#!/usr/bin/env python3

# ----------------------------------------------------------------------------------------------------------------------
# rom_database.py

"""
Builds the ROMs database (the 'mylist' rows shown in the ROM list).

Previously the whole of `mame -listxml` (about 330 MB for MAME 0.289) was kept as xmlcache.dat, read into memory as
~7 million lines on every rebuild and scanned twice with string splitting, all on the GUI thread with wx.Yield()
loops and an optional multiprocessing pool.

Now:
  * `mame -listxml` is streamed straight into xml.etree.iterparse, so it is never held in memory as a whole, and only
    the fields pfeMAME uses are kept (name, description, year, manufacturer, clone-of, software lists, whether it
    has loadable media, and the ROM file names of clones for the merged-set check).
  * That compact list is cached in machines.cache (a few MB) keyed on the MAME version.
  * The build is a plain function with no GUI code, so pfemame.py runs it in a background thread and the window
    stays responsive.  Progress is reported through a callback.

This module has no wxPython dependency, so it can be tested on its own.
"""

import os
import pickle
import subprocess
import time
import xml.etree.ElementTree as ET
import zipfile
from collections import defaultdict, namedtuple
from dataclasses import dataclass, field

import py7zr

import database_build
from mame_paths import NO_CONSOLE, find_in_folders, find_rom_sets, mame_working_dir

# mylist row layout (see pfemame.py)
INDEX_ROM_NAME = 0
INDEX_ROM_FILE_NAME = 1
INDEX_SYSTEM_PROGRAM_FILE_NAME = 2
INDEX_EXISTS = 3
INDEX_CATEGORY = 7
DISPLAY_COLUMNS = 12

MACHINE_CACHE_NAME = 'machines.cache'
MACHINE_CACHE_FORMAT = 2                    # 2 = also stores the driver status (for 'now working' reports)
SOFTWARE_CACHE_NAME = 'software.cache'
SOFTWARE_CACHE_FORMAT = 1
LEGACY_XML_CACHE_NAME = 'xmlcache.dat'      # The old raw -listxml cache (no longer used)
DATABASE_NAME = 'mylist.db'
DATABASE_FORMAT = 2                         # 2 = also stores system_rom_names

# status = MAME's driver status: 'good', 'imperfect' or 'preliminary' ('' if unknown - older caches)
# N_() marks a string for translation without translating it here (gettext's 'noop' convention) - the text is
# translated where it is displayed.  tools/create_language_files.py collects both _() and N_() strings.
def N_(text: str) -> str:
    return text


Machine = namedtuple('Machine', 'name description year manufacturer cloneof softwarelists has_media roms status',
                     defaults=('',))


class BuildCancelled(Exception):
    pass


# ----------------------------------------------------------------------------------------------------------------------
# Reading MAME's machine list

def _machine_from_element(element) -> Machine:
    cloneof = element.get('cloneof', '')
    roms = ()
    if cloneof:
        # Files this clone needs of its own (merged files live in the parent; undumped ones don't exist anywhere)
        roms = tuple(rom.get('name', '') for rom in element.iter('rom')
                     if rom.get('merge') is None and rom.get('status') != 'nodump')
    return Machine(name=element.get('name', ''),
                   description=element.findtext('description', ''),
                   year=element.findtext('year', ''),
                   manufacturer=element.findtext('manufacturer', ''),
                   cloneof=cloneof,
                   softwarelists=tuple(sl.get('name', '').lower() for sl in element.findall('softwarelist')),
                   has_media=element.find('.//instance') is not None,
                   roms=roms,
                   status=(element.find('driver').get('status', '') if element.find('driver') is not None else ''))


def parse_machines(stream, progress=None, cancel=None) -> tuple[list[Machine], str]:
    """
    Parse a -listxml stream (file object opened in binary mode) incrementally.
    Device-only entries are skipped.  Returns (machines, mame_version).
    """
    machines: list[Machine] = []
    version = ''
    root = None
    complete = False
    for event, element in ET.iterparse(stream, events=('start', 'end')):
        if event == 'start':
            if root is None:
                root = element
                version = (element.get('build') or '').split(' ')[0]
            continue
        if element.tag == 'machine':
            if element.get('isdevice') != 'yes':
                machines.append(_machine_from_element(element))
                if progress and len(machines) % 500 == 0:
                    progress(N_('Reading the MAME machine list ({:,} machines)'), len(machines), 0)
                if cancel is not None and cancel.is_set():
                    raise BuildCancelled()
            root.clear()                    # Free each machine once it has been read
        elif element is root:
            complete = True
    if not complete:
        raise ValueError('The MAME machine list ended unexpectedly')
    return machines, version


def stream_machines_from_mame(mame_exe: str, progress=None, cancel=None) -> tuple[list[Machine], str]:
    """Run `mame -listxml` and parse its output as it arrives."""
    process = subprocess.Popen([mame_exe, '-listxml', '-nodtd'], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                               cwd=mame_working_dir(mame_exe), **NO_CONSOLE)
    try:
        machines, version = parse_machines(process.stdout, progress, cancel)
    finally:
        if process.poll() is None:
            process.kill()
        process.stdout.close()
        return_code = process.wait()
    if return_code not in (0, None) and not machines:
        raise RuntimeError(f'MAME -listxml failed (exit code {return_code})')
    return machines, version


def _same_version(a: str, b: str) -> bool:
    try:
        return [int(x) for x in a.split('.')] == [int(x) for x in b.split('.')]
    except ValueError:
        return a == b


def load_machine_cache(path: str, mame_version: str) -> list[Machine] | None:
    """The cached machine list, or None if missing, unreadable, an old format, or for another MAME version."""
    try:
        with open(path, 'rb') as handle:
            data = pickle.load(handle)
        if data.get('format') != MACHINE_CACHE_FORMAT or not _same_version(data.get('mame_version', ''), mame_version):
            return None
        return [Machine(*row) for row in data['machines']]
    except (OSError, pickle.UnpicklingError, EOFError, KeyError, TypeError, AttributeError, ValueError):
        return None


def save_machine_cache(path: str, mame_version: str, machines: list[Machine]) -> None:
    temp = path + '.tmp'
    with open(temp, 'wb') as handle:
        pickle.dump({'format': MACHINE_CACHE_FORMAT, 'mame_version': mame_version,
                     'machines': [tuple(m) for m in machines]}, handle, protocol=pickle.HIGHEST_PROTOCOL)
    os.replace(temp, path)


def load_software_cache(path: str, mame_version: str) -> dict | None:
    """Cached {software list: {file name: short name}} for this MAME version, or None."""
    try:
        with open(path, 'rb') as handle:
            data = pickle.load(handle)
        if data.get('format') != SOFTWARE_CACHE_FORMAT or not _same_version(data.get('mame_version', ''),
                                                                           mame_version):
            return None
        return data['lists']
    except (OSError, pickle.UnpicklingError, EOFError, KeyError, TypeError, AttributeError, ValueError):
        return None


def save_software_cache(path: str, mame_version: str, lookup: dict) -> None:
    temp = path + '.tmp'
    with open(temp, 'wb') as handle:
        pickle.dump({'format': SOFTWARE_CACHE_FORMAT, 'mame_version': mame_version, 'lists': lookup}, handle,
                    protocol=pickle.HIGHEST_PROTOCOL)
    os.replace(temp, path)


@dataclass
class MameChanges:
    """What changed between the MAME version pfeMAME last saw and the new one."""
    old_version: str
    new_version: str
    added: list = field(default_factory=list)          # (name, description)
    removed: list = field(default_factory=list)        # (name, description)
    now_working: list = field(default_factory=list)    # (name, description, old status, new status)

    @property
    def summary(self) -> str:
        text = (f'MAME {self.old_version} -> {self.new_version}: {len(self.added):,} new machine(s), '
                f'{len(self.removed):,} removed')
        if self.now_working:
            text += f', {len(self.now_working):,} now working'
        return text


def load_any_machine_cache(path: str) -> tuple[str, list[Machine]] | None:
    """The cached machine list whatever MAME version (or cache format) it is for: (mame_version, machines)."""
    try:
        with open(path, 'rb') as handle:
            data = pickle.load(handle)
        return data.get('mame_version', ''), [Machine(*row) for row in data['machines']]
    except (OSError, pickle.UnpicklingError, EOFError, KeyError, TypeError, AttributeError, ValueError):
        return None


def compare_machines(old: list[Machine], new: list[Machine], old_version: str, new_version: str) -> MameChanges:
    old_by_name = {m.name: m for m in old}
    new_by_name = {m.name: m for m in new}
    changes = MameChanges(old_version, new_version)
    changes.added = sorted((m.name, m.description) for name, m in new_by_name.items() if name not in old_by_name)
    changes.removed = sorted((m.name, m.description) for name, m in old_by_name.items() if name not in new_by_name)
    changes.now_working = sorted(
        (name, m.description, old_by_name[name].status, m.status) for name, m in new_by_name.items()
        if name in old_by_name and old_by_name[name].status == 'preliminary' and m.status in ('good', 'imperfect'))
    return changes


def format_changes(changes: MameChanges) -> str:
    """A plain-text report of a MameChanges, for the report file / viewer."""
    lines = [changes.summary, '']
    for title, rows in (('NEW MACHINES', changes.added), ('NOW WORKING', changes.now_working),
                        ('REMOVED MACHINES', changes.removed)):
        lines.append(f'{title} ({len(rows):,})')
        lines.append('-' * 60)
        for row in rows:
            extra = f'   [{row[2]} -> {row[3]}]' if len(row) > 2 else ''
            lines.append(f'{row[0]:<20} {row[1]}{extra}')
        lines.append('')
    return '\n'.join(lines)


def get_machines(mame_exe: str, mame_version: str, data_dir: str, progress=None, cancel=None,
                 use_cache: bool = True) -> tuple[list[Machine], bool, MameChanges | None]:
    """
    Machine list from machines.cache if it matches this MAME version, otherwise from MAME (and cached).
    When the cache was for a different MAME version, also returns what changed between the two versions.
    """
    cache_path = os.path.join(data_dir, MACHINE_CACHE_NAME)
    if use_cache:
        cached = load_machine_cache(cache_path, mame_version)
        if cached:
            return cached, True, None
    previous = load_any_machine_cache(cache_path)
    if progress:
        progress(N_('Reading the MAME machine list'), 0, 0)
    machines, version = stream_machines_from_mame(mame_exe, progress, cancel)
    version = version or mame_version
    changes = None
    if previous and previous[1] and previous[0] and not _same_version(previous[0], version):
        changes = compare_machines(previous[1], machines, previous[0], version)
    save_machine_cache(cache_path, version, machines)
    # The old 330 MB raw XML cache is not used any more
    legacy = os.path.join(data_dir, LEGACY_XML_CACHE_NAME)
    if os.path.isfile(legacy):
        try:
            os.remove(legacy)
        except OSError:
            pass
    return machines, False, changes


# ----------------------------------------------------------------------------------------------------------------------
# Building the ROM list

@dataclass
class BuildSettings:
    mame_exe: str
    mame_version: str
    data_dir: str
    rom_folders: list[str]
    systems_folders: list[str]
    systems_support: bool
    category_dict: dict
    alternate_engines: list = field(default_factory=list)
    use_machine_cache: bool = True


@dataclass
class BuildResult:
    mylist: list
    available_roms: int
    system_rom_names: set
    errors: list = field(default_factory=list)       # Per-ROM build errors (written to build_errors.txt)
    messages: list = field(default_factory=list)     # Things to tell the user
    clones_added: int = 0
    machines_from_cache: bool = False
    timings: dict = field(default_factory=dict)
    mame_changes: MameChanges | None = None           # Set when MAME was upgraded since the last build


def _scan_system_folders(systems_folders: list[str]) -> dict[str, list[str]]:
    """{sub-folder path: [file names]} for every sub-folder below the systems (rompath) folders."""
    file_dictionary = {}
    for base_path in systems_folders:
        if not os.path.isdir(base_path):
            continue
        for root, _dirs, _files in os.walk(base_path):
            if root == base_path or root in file_dictionary:
                continue
            try:
                file_dictionary[root] = os.listdir(root)
            except OSError:
                continue
    return file_dictionary


def _alternate_engine_rows(engines: list) -> tuple[list, list]:
    """Rows for non-MAME emulators that have their own ROM folder (see non_mame_emulators.xml)."""
    rows, messages = [], []
    try:
        previous_engine = ''
        for line in engines:
            engine, rom_folder, description, extensions = line[0], line[2], line[3], line[8].split()
            if rom_folder == 'Default' or previous_engine == engine:
                continue            # Don't do duplicates
            previous_engine = engine
            if not os.path.exists(rom_folder):
                continue
            added = 0
            for file_name in os.listdir(rom_folder):
                if os.path.splitext(file_name)[1].lower()[1:] in extensions:
                    rows.append([engine, engine, os.path.splitext(file_name)[0], '1', '0', '0', '0',
                                 description, '', '', '', ''])
                    added += 1
            messages.append(('log', f'Added {added} {engine} files to ROMs list'))
    except IndexError:
        messages.append(('error', 'There was a problem processing the non_mame_emulators.xml file.  There is '
                                  'likely an error in this file.  Please check it out.'))
    return rows, messages


def set_exists_flags(mylist: list, rom_folders: list[str]) -> int:
    """Flag every row whose ROM set is present in a rompath folder.  Returns how many rows exist."""
    present = find_rom_sets(rom_folders)
    for row in mylist:
        if row[INDEX_ROM_FILE_NAME] in present:
            row[INDEX_EXISTS] = '1'
    return sum(1 for row in mylist if row[INDEX_EXISTS] == '1')


def _archive_file_names(rom_folders: list[str], rom_name: str) -> set[str]:
    """Lower-case names of the files inside rom_name's .zip / .7z / folder (plus base names of nested files)."""
    names: set[str] = set()

    def add(entries):
        for name in entries:
            names.add(name.lower())
            base = name.replace('\\', '/').split('/')[-1]
            if base:
                names.add(base.lower())

    zip_path = find_in_folders(rom_folders, rom_name + '.zip')
    if zip_path and os.path.isfile(zip_path):
        try:
            with zipfile.ZipFile(zip_path) as archive:
                add(archive.namelist())
        except (OSError, zipfile.BadZipFile):
            pass
    z7_path = find_in_folders(rom_folders, rom_name + '.7z')
    if z7_path and os.path.isfile(z7_path):
        try:
            with py7zr.SevenZipFile(z7_path, 'r') as archive:
                add(archive.getnames())
        except Exception:
            pass
    folder = find_in_folders(rom_folders, rom_name)
    if folder and os.path.isdir(folder):
        # The folder itself and one level of sub-folders (as before)
        try:
            with os.scandir(folder) as entries:
                for entry in entries:
                    if entry.is_file():
                        add([entry.name])
                    elif entry.is_dir():
                        try:
                            add([sub.name for sub in os.scandir(entry.path) if sub.is_file()])
                        except OSError:
                            continue
        except OSError:
            pass
    return names


def find_merged_clones(mylist: list, machines: list[Machine], rom_folders: list[str], category_dict: dict,
                       progress=None, cancel=None) -> list[list]:
    """
    Merged ROM sets keep a parent's clones inside the parent's archive.  For each existing parent, add a row for
    every clone whose own files are all present in the parent's archive / folder.
    """
    clones_by_parent = defaultdict(list)
    for machine in machines:
        if machine.cloneof and machine.roms:
            clones_by_parent[machine.cloneof].append(machine)

    existing_parents = [row for row in mylist if row[INDEX_EXISTS] == '1' and not row[INDEX_SYSTEM_PROGRAM_FILE_NAME]
                        and row[INDEX_ROM_FILE_NAME] in clones_by_parent]
    new_rows = []
    for count, parent in enumerate(existing_parents):
        if cancel is not None and cancel.is_set():
            raise BuildCancelled()
        if progress and count % 25 == 0:
            progress(N_('Checking merged ROM sets for clones'), count, len(existing_parents))
        contents = _archive_file_names(rom_folders, parent[INDEX_ROM_FILE_NAME])
        for clone in clones_by_parent[parent[INDEX_ROM_FILE_NAME]]:
            if {name.lower() for name in clone.roms} <= contents:
                new_rows.append([clone.description, clone.name, '', '1', '0', '0', '0',
                                 category_dict.get(clone.name, parent[INDEX_CATEGORY]), '', '',
                                 clone.year, clone.manufacturer])
    return new_rows


def remove_duplicates_by_first_two_fields(data: list) -> list:
    """
    Remove duplicate rows (same description and ROM name) created when a merged-set clone was also listed as not
    existing.  For duplicates, rows flagged as not existing are dropped; if they all are, one is kept.
    """
    groups: dict = {}
    for line in data:
        if len(line) >= 5:
            groups.setdefault((line[0], line[1]), []).append(line)
    result = []
    for lines in groups.values():
        if len(lines) == 1:
            result.append(lines[0])
        else:
            existing = [line for line in lines if line[INDEX_EXISTS] != '0']
            result.extend(existing if existing else lines[:1])
    return result


def build(settings: BuildSettings, progress=None, cancel=None) -> BuildResult:
    """
    Build the complete ROM list.  No GUI code - safe to run in a background thread.

    :param progress: progress(message_format, done, total) - total 0 means 'unknown'.  Called from this thread.
    :param cancel:   optional threading.Event; setting it raises BuildCancelled at the next checkpoint.
    """
    timings = {}
    started = time.monotonic()

    def lap(name):
        nonlocal started
        now = time.monotonic()
        timings[name] = round(now - started, 2)
        started = now

    machines, from_cache, mame_changes = get_machines(settings.mame_exe, settings.mame_version, settings.data_dir, progress,
                                        cancel, settings.use_machine_cache)
    lap('machine list')

    system_rom_names = {m.name for m in machines if m.softwarelists or m.has_media}

    # Index the systems-folder sub-directories by software-list name so each system maps straight to its media
    if progress:
        progress(N_('Scanning system folders'), 0, 0)
    file_dictionary = _scan_system_folders(settings.systems_folders)

    def media_name_for(folder_path: str) -> str:
        for base in settings.systems_folders:
            relative = os.path.relpath(folder_path, base)
            if relative != '.' and not relative.startswith('..'):
                return relative.split(os.sep)[0]
        return os.path.basename(folder_path)

    folders_by_list = defaultdict(list)
    for folder_path, files in file_dictionary.items():
        media_name = media_name_for(folder_path)
        for key in {os.path.basename(folder_path).lower(), os.path.basename(os.path.dirname(folder_path)).lower()}:
            folders_by_list[key].append((folder_path, files, media_name))
    lap('system folders')

    # Software short names (for HASH-based launching) from ONE -listsoftware call, cached per MAME version
    needed_lists = {name for m in machines for name in m.softwarelists}
    software_lookup = {}
    if settings.systems_support and needed_lists:
        software_cache = os.path.join(settings.data_dir, SOFTWARE_CACHE_NAME)
        software_lookup = load_software_cache(software_cache, settings.mame_version) if settings.use_machine_cache \
            else None
        if software_lookup is None:
            if progress:
                progress(N_('Reading the software lists'), 0, 0)
            software_lookup = database_build.get_software_lookup(settings.mame_exe, needed_lists)
            save_software_cache(software_cache, settings.mame_version, software_lookup)
    lap('software lists')

    mylist: list = []
    errors: list = []
    systems_support = 'True' if settings.systems_support else 'False'
    total = len(machines)
    for count, machine in enumerate(machines):
        if count % 2000 == 0:
            if cancel is not None and cancel.is_set():
                raise BuildCancelled()
            if progress:
                progress(N_('Building the ROM list'), count, total)
        media = []
        if machine.softwarelists:
            seen = set()
            for list_name in machine.softwarelists:
                for folder_path, files, media_name in folders_by_list.get(list_name, []):
                    if folder_path not in seen:
                        seen.add(folder_path)
                        media.append((folder_path, files, media_name, software_lookup.get(list_name, {})))
        rows, error = database_build.get_info(systems_support,
                                              settings.category_dict.get(machine.name, 'Not Classified'),
                                              machine.description, machine.name, settings.rom_folders, media,
                                              machine.year, machine.manufacturer)
        mylist.extend(rows)
        if error is not None:
            errors.append(str(error))
    lap('rom rows')

    alternate_rows, messages = _alternate_engine_rows(settings.alternate_engines or [])
    mylist.extend(alternate_rows)

    if progress:
        progress(N_('Checking which ROMs exist'), 0, 0)
    set_exists_flags(mylist, settings.rom_folders)
    lap('exists flags')

    clones = find_merged_clones(mylist, machines, settings.rom_folders, settings.category_dict, progress, cancel)
    mylist.extend(clones)
    lap('merged sets')

    mylist.sort(key=lambda x: (x[INDEX_ROM_NAME].lower(), x[INDEX_ROM_NAME]))
    mylist = remove_duplicates_by_first_two_fields(mylist)
    lap('sort')

    available = sum(1 for row in mylist if row[INDEX_EXISTS] == '1')
    return BuildResult(mylist=mylist, available_roms=available, system_rom_names=system_rom_names, errors=errors,
                       messages=messages, clones_added=len(clones), machines_from_cache=from_cache, timings=timings,
                       mame_changes=mame_changes)


# ----------------------------------------------------------------------------------------------------------------------
# The saved database (mylist.db)

def save_database(path: str, mylist: list, system_rom_names: set) -> None:
    import shelve
    with shelve.open(path, flag='n') as db:
        db['format'] = DATABASE_FORMAT
        db['mylist'] = mylist
        db['system_rom_names'] = sorted(system_rom_names)


def load_database(path: str) -> tuple[list, set]:
    """
    (mylist, system_rom_names) from mylist.db.  Raises ValueError for a database written by an older pfeMAME, which
    didn't store system_rom_names (without them the Slots tab can't be offered) - the caller then rebuilds.
    """
    import shelve
    with shelve.open(path, flag='r') as db:
        if db.get('format') != DATABASE_FORMAT:
            raise ValueError('The ROMs database was written by an older version of pfeMAME')
        mylist = db.get('mylist', [])
        system_rom_names = set(db.get('system_rom_names', []))
    if mylist and len(mylist[0]) != DISPLAY_COLUMNS:
        raise ValueError('ROMs database columns count mismatch')
    return mylist, system_rom_names
