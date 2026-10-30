#!/usr/bin/env python3

"""
This function builds the ROM database. It can be used with multiprocessing
or standard iteration to speed up the process.
"""

import os
import subprocess
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, astuple


@dataclass
class RomEntry:
    rom_name: str  # [0]
    rom_file_name: str  # [1]
    system_file_name: str = ''  # [2]
    rom_exists_flag: str = '0'  # [3]
    rom_rating: str = '0'  # [4]
    number_of_runs: str = '0'  # [5]
    favorite_flag: str = '0'  # [6]
    rom_category: str = ''  # [7]
    system_short_name: str = ''  # [8]
    system_programs_folder: str = ''  # [9]
    year: str = ''  # [10]
    manufacturer: str = ''  # [11]

    def to_list(self):
        return list(astuple(self))

from mame_paths import NO_CONSOLE, rom_set_present   # (no wx - this module runs in worker threads)

ROM_PATTERN = re.compile(r'<rom name="([^"]+)"')
SOFTWARE_PATTERN = re.compile(r'<software name="([^"]+)"')
SOFTWARELIST_PATTERN = re.compile(r'<softwarelist name="([^"]+)"')


def build_softlist_lookup(mame_output: str) -> dict[str, dict[str, str]]:
    """
    Build a nested dictionary {software_list_name: {rom_file_name: software_short_name}} from the output of a
    single ``mame -listsoftware`` call (which covers every software list at once).

    Keying by software list keeps the short-name resolution accurate even when the same file name appears in
    more than one list.  The input is expected to be lower-cased by the caller.
    """
    lookup: dict[str, dict[str, str]] = {}
    current_list = None
    current_short_name = None

    for line in mame_output.splitlines():
        list_match = SOFTWARELIST_PATTERN.search(line)
        if list_match:
            current_list = list_match.group(1)
            lookup.setdefault(current_list, {})
            continue

        sw_match = SOFTWARE_PATTERN.search(line)
        if sw_match:
            current_short_name = sw_match.group(1)

        rom_match = ROM_PATTERN.search(line)
        if rom_match and current_list is not None:
            lookup[current_list][rom_match.group(1).lower()] = current_short_name or ""

    return lookup


def get_software_lookup(path_mame_exe: str,
                        needed_lists: set[str] | None = None) -> dict[str, dict[str, str]]:
    """
    Resolve software short names for every software list in ONE ``mame -listsoftware`` call, returning
    {list_name: {rom_file_name: short_name}}.

    This replaces the previous approach of running ``mame -listsoftware <system>`` once per system ROM, which
    spawned hundreds of subprocesses.  When the HASH xml files are absent (e.g. a default Linux MAME install)
    the command produces no software, so this returns an empty mapping and short names are simply left blank -
    no error and no behavioural difference beyond the missing (optional) short names.

    :param needed_lists: If given, the result is trimmed to just these list names to save memory.
    The output (hundreds of MB for all software lists) is streamed through an XML parser rather than read into
    memory, lower-cased and split into lines as it used to be, which peaked at several hundred MB.  XML entities
    are decoded properly too, so names containing '&' now match the files on disk.
    """
    cmd = [path_mame_exe, '-listsoftware', '-nodtd']
    mame_folder = os.path.dirname(os.path.abspath(path_mame_exe)) if os.path.isfile(path_mame_exe) else None
    try:
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, cwd=mame_folder,
                                   **NO_CONSOLE)
    except OSError:
        return {}

    lookup: dict[str, dict[str, str]] = {}
    current = None
    try:
        for event, element in ET.iterparse(process.stdout, events=('start', 'end')):
            if event == 'start':
                if element.tag == 'softwarelist':
                    list_name = element.get('name', '').lower()
                    current = (lookup.setdefault(list_name, {})
                               if needed_lists is None or list_name in needed_lists else None)
                continue
            if element.tag == 'software':
                if current is not None:
                    short_name = element.get('name', '').lower()
                    for rom in element.iter('rom'):
                        rom_name = rom.get('name')
                        if rom_name:
                            current[rom_name.lower()] = short_name
                element.clear()
            elif element.tag == 'softwarelist':
                element.clear()
    except ET.ParseError:
        pass        # Keep whatever was read before the output went wrong
    finally:
        if process.poll() is None:
            process.kill()
        process.stdout.close()
        process.wait()

    return lookup

def append_files(
                rom_lookup: dict[str, str],
                folder_name_local: str,
                files: list[str],
                path_media_name: str,
                rom_name: str,
                rom_file_name: str,
                category: str
                ) -> list[list[str]]:
    """
    Build and return ROM entries for the files in folder_name_local.
    Always returns a list (empty if no files found).

    :param path_media_name: The on-disk media sub-folder name (original case) used later to build the launch
                            path; passed in pre-computed rather than derived here.
    """

    results: list[list[str]] = []

    for file_name in files or []:  # ensures files can be None
        file_str = str(file_name)
        short_name = rom_lookup.get(file_str.lower(), "")

        file_path = os.path.join(folder_name_local, file_str)
        if os.path.isfile(file_path):
            entry = RomEntry(
                rom_name=rom_name,
                rom_file_name=rom_file_name,
                system_file_name=file_str,
                rom_category=category,
                system_short_name=short_name,
                system_programs_folder=path_media_name
            )
            results.append(entry.to_list())

    return results  # always returns a list, even if empty


def get_info(systems_support: str,
             category: str,
             rom_name: str,
             rom_file_name: str,
             folders_roms: list[str],
             system_media: list[tuple],
             year: str,
             manufacturer: str) -> tuple[list[list[str]], str | None]:
    """
    Build the database entries for a single ROM.

    The ROM itself is always added.  If it is a system (``system_media`` non-empty) and systems support is
    enabled and its ROM set is present, each of its software files is added as a child entry.

    :param system_media: Pre-resolved media for this system: a list of
                         (folder_path, files, media_name, rom_lookup) tuples, where rom_lookup maps a file name
                         to its software short name.  Empty for non-systems.  All the expensive discovery
                         (detecting systems, finding their folders and resolving short names) is done once in
                         the caller, so this worker does no subprocess calls.
    """

    entry = RomEntry(
        rom_name=rom_name,  # [0]
        rom_file_name=rom_file_name,  # [1]
        rom_category=category,  # [7]
        year=year,  # [10]
        manufacturer=manufacturer  # [11]
    )

    output_result = [entry.to_list()]  # Add the ROM to the list
    error = None

    # Only continue if systems support is enabled and this ROM is a system with mapped media folders
    if systems_support == 'True' and system_media:
        # Only add software if we actually have the system's own ROM set (in any rompath folder, as an archive or
        # as a folder)
        if rom_set_present(folders_roms, rom_file_name):
            for folder_name, files, media_name, rom_lookup in system_media:
                results = append_files(
                    rom_lookup,
                    folder_name,
                    files,
                    media_name,
                    rom_name,
                    rom_file_name,
                    category
                )
                output_result.extend(results)

    return sorted(output_result, key=lambda x: x[2].lower()), error
