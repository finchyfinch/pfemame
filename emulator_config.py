#!/usr/bin/env python3

# ----------------------------------------------------------------------------------------------------------------------
# emulator_config.py

"""
Reading and writing the alternate (non-MAME) emulator setup in non_mame_emulators.xml, and the defaults offered for
it in non_mame_defaults.xml.  No GUI: the Alternate Emulators window (alternate_emulators.py) and the game launcher
(rungame.py, via functions.load_other_emulators_detail) use this.

The emulators are held as rows, one per ROM, each carrying its emulator's settings as well (see EmulatorFields).

non_mame_emulators.xml looks like this, and must stay readable by older versions of pfeMAME:

    <pfemame author="gfinch">
        <machine name="..." pathToEmulator="..." romFolder="..." useThisEngine="True" includeExtension="False"
                 includeFolderPath="False">
            <description>...</description>
            <extraCommands>...</extraCommands>
            <extensions>zip 7z</extensions>
            <game name="..." fileName="..."/>
            ...
        </machine>
        ...
    </pfemame>
"""

import os
import shutil
import tempfile
import xml.etree.ElementTree as ET
from xml.dom import minidom

# The emulator setup file, in the user's data folder
EMULATORS_XML_FILE = 'non_mame_emulators.xml'


class EmulatorFields:
    """Indices for emulator configuration data"""
    NAME = 0
    PATH = 1
    ROM_FOLDER = 2
    DESCRIPTION = 3
    ENABLED = 4
    INCLUDE_EXTENSION = 5
    INCLUDE_FOLDER_PATH = 6
    EXTRA_COMMANDS = 7
    VALID_EXTENSIONS = 8
    ROM_NAME = 9
    ROM_FILE_NAME = 10


# The entry put in an emulator's ROM list when it is created (it must always have at least one)
PLACEHOLDER_ROM_ENTRY = ('rom_name', 'rom_file_name')


# ----------------------------------------------------------------------------------------------------------------------
# non_mame_emulators.xml
def load_emulators(xml_path: str) -> tuple[list, bool]:
    """
    Load the alternate emulators from non_mame_emulators.xml.

    :param xml_path: Full path to the file

    :returns:
    The rows, one per ROM (see EmulatorFields), and an error flag set if the file exists but couldn't be read.  A
    missing file is not an error: there are just no emulators.
    """
    if not os.path.exists(xml_path):
        return [], False

    non_mame_emulators = []
    error = False

    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()

        # Iterate through all <machine> elements
        for machine in root.findall('machine'):
            # Get machine attributes with defaults
            machine_name = machine.get('name', '')
            path_to_emulator = machine.get('pathToEmulator', '')
            rom_folder = machine.get('romFolder', '')
            use_this_engine = machine.get('useThisEngine', 'False') == 'True'
            include_extension = machine.get('includeExtension', 'False') == 'True'
            include_folder_path = machine.get('includeFolderPath', 'False') == 'True'

            # Get child elements with defaults
            emulator_description = machine.findtext('description', default='')
            extra_commands = machine.findtext('extraCommands', default='')
            extensions = machine.findtext('extensions', default='')

            # Process each game under this machine
            for game in machine.findall('game'):
                game_name = game.get('name', '')
                game_file_name = game.get('fileName', '')

                non_mame_emulators.append([
                    machine_name,
                    path_to_emulator,
                    rom_folder,
                    emulator_description,
                    use_this_engine,
                    include_extension,
                    include_folder_path,
                    extra_commands,
                    extensions,
                    game_name,
                    game_file_name
                ])

    except ET.ParseError as e:
        # XML is malformed
        print(f"XML parsing error: {e}")
        error = True
    except (FileNotFoundError, IOError, PermissionError) as e:
        # File access issues
        print(f"File access error: {e}")
        error = True
    except Exception as e:
        # Catch any other unexpected errors
        print(f"Unexpected error loading emulators: {e}")
        error = True

    return non_mame_emulators, error


def build_emulators_xml(engine_rows: list[list]) -> str:
    """
    The contents of non_mame_emulators.xml for the rows (see load_emulators), without a trailing newline.

    Each emulator is written once, with its settings from its first row and a <game> for each of its rows, in the
    order the emulators first appear.  (Rows for one emulator are normally together, but needn't be.)
    """
    if not engine_rows:
        # No emulators.  Write the closing tag on its own line rather than <pfemame ... /> as older versions of
        # pfeMAME read the file line by line looking for </pfemame>.
        return '<pfemame author="gfinch">\n</pfemame>'

    root = ET.Element('pfemame', author='gfinch')

    machines = {}
    for line in engine_rows:
        engine = line[EmulatorFields.NAME]

        # Create new machine element when we encounter a new engine
        if engine not in machines:
            machine = ET.SubElement(root, 'machine',
                                    name=line[EmulatorFields.NAME],
                                    pathToEmulator=line[EmulatorFields.PATH],
                                    romFolder=line[EmulatorFields.ROM_FOLDER],
                                    useThisEngine=str(line[EmulatorFields.ENABLED]),
                                    includeExtension=str(line[EmulatorFields.INCLUDE_EXTENSION]),
                                    includeFolderPath=str(line[EmulatorFields.INCLUDE_FOLDER_PATH])
                                    )

            # Add child elements (text content is automatically escaped)
            description = ET.SubElement(machine, 'description')
            description.text = line[EmulatorFields.DESCRIPTION]

            extra_commands = ET.SubElement(machine, 'extraCommands')
            extra_commands.text = line[EmulatorFields.EXTRA_COMMANDS]

            extensions = ET.SubElement(machine, 'extensions')
            extensions.text = line[EmulatorFields.VALID_EXTENSIONS]

            machines[engine] = machine

        # Add game element to its machine
        ET.SubElement(machines[engine], 'game',
                      name=line[EmulatorFields.ROM_NAME],
                      fileName=line[EmulatorFields.ROM_FILE_NAME]
                      )

    # Convert to pretty-printed string
    xml_string = minidom.parseString(ET.tostring(root, encoding='unicode')).toprettyxml(indent='    ')

    # Remove the XML declaration and empty lines
    xml_lines = [line for line in xml_string.split('\n') if line.strip()]
    return '\n'.join(xml_lines[1:])  # Skip <?xml...?> declaration


def save_emulators(xml_path: str, engine_rows: list[list]) -> None:
    """
    Save the rows (see load_emulators) to non_mame_emulators.xml, safely (see write_file_safely).

    :raises:
    OSError if the file can't be written; the existing file is then unchanged.
    """
    write_file_safely(xml_path, build_emulators_xml(engine_rows) + '\n')


def write_file_safely(path: str, text: str) -> None:
    """
    Write a text file without risking the existing one: the new contents go to a temporary file in the same folder,
    which then replaces the file in one step, so a crash, power cut or full disk part way through leaves the old file
    as it was.  The old file is first copied to <path>.bak.

    :param path: The file to write
    :param text: The new contents (written as UTF-8, with the platform's line endings as before)

    :raises:
    OSError if the file can't be written; the existing file is then unchanged.
    """
    folder = os.path.dirname(os.path.abspath(path))
    handle, temp_path = tempfile.mkstemp(prefix=os.path.basename(path) + '.', suffix='.tmp', dir=folder)
    try:
        with os.fdopen(handle, 'w', encoding='utf-8') as fp:
            fp.write(text)
            fp.flush()
            os.fsync(fp.fileno())  # Make sure it is really on disk before it replaces the old file

        if os.path.exists(path):
            try:
                shutil.copy2(path, path + '.bak')
            except OSError as e:  # The save itself is still safe, so carry on without the backup copy
                print(f'Unable to back up {path}: {e}')

        os.replace(temp_path, path)
    except BaseException:
        try:
            os.remove(temp_path)
        except OSError:
            pass
        raise


def emulator_names_in_order(engine_rows: list[list]) -> list[str]:
    """
    The distinct emulator engine names from the engine data rows, in first-seen order (i.e. XML file order).

    A set must not be used for this: its order is arbitrary and changes between runs, which put the emulators in a
    random order and could leave the window showing (and then overwriting) the wrong emulator after a new one was
    created.

    :param engine_rows: Rows as returned by load_emulators, one per ROM
    :returns: The engine names, each listed once
    """
    return list(dict.fromkeys(row[EmulatorFields.NAME] for row in engine_rows))


# ----------------------------------------------------------------------------------------------------------------------
# Finding an emulator's ROM files
def scan_rom_folders(folders: list[str], extensions: list[str]) -> list[str]:
    """
    Find the ROM files in the folders with one of the extensions.

    :param folders: Folders to look in (ones that don't exist or can't be read are skipped)
    :param extensions: Valid extensions, without dots (e.g. ['zip', '7z']).  Matched ignoring case.

    :returns:
    The file names without their extensions, sorted, each listed once.
    """
    wanted = {ext.lstrip('.').lower() for ext in extensions if ext.lstrip('.')}
    found = {}
    for folder in folders:
        try:
            with os.scandir(folder) as entries:
                for entry in entries:
                    name, ext = os.path.splitext(entry.name)
                    if ext[1:].lower() in wanted and name and entry.is_file():
                        found.setdefault(name.casefold(), name)
        except OSError:
            continue
    return sorted(found.values(), key=str.casefold)


def merge_scanned_roms(existing: list[tuple[str, str]],
                       found: list[str],
                       descriptions: dict[str, str] | None = None
                       ) -> tuple[list[tuple[str, str]], int, list[tuple[str, str]]]:
    """
    Merge the ROM files found by a scan into an emulator's ROM entries, keeping the existing entries and their names.

    :param existing: The current (rom name, rom file name) entries
    :param found: ROM file names (no extensions) found by scan_rom_folders
    :param descriptions: MAME machine names -> their descriptions, to name the new entries (see rom_name_for)

    :returns:
    The merged entries (existing ones first, then the new files), how many were added, and the existing entries with
    no matching file.  The placeholder entry of a new emulator is dropped.
    """
    existing = [row for row in existing if tuple(row) != PLACEHOLDER_ROM_ENTRY]
    known = {file_name.casefold() for _name, file_name in existing}
    new_rows = [(rom_name_for(file_name, descriptions), file_name) for file_name in found
                if file_name.casefold() not in known]
    found_names = {file_name.casefold() for file_name in found}
    missing = [row for row in existing if row[1].casefold() not in found_names]
    return list(existing) + new_rows, len(new_rows), missing


# ----------------------------------------------------------------------------------------------------------------------
# Naming ROM entries from MAME's machine list

# The name given to a ROM entry that hasn't been named
UNNAMED_ROM = '___'


def is_unnamed(rom_name: str) -> bool:
    """True for a ROM entry that hasn't been given a name: '___', blank, or a new emulator's placeholder."""
    return rom_name.strip() in (UNNAMED_ROM, '', PLACEHOLDER_ROM_ENTRY[0])


def rom_name_for(file_name: str, descriptions: dict[str, str] | None) -> str:
    """
    The name for a ROM entry: the description of the MAME machine with that file name (e.g. 'bel' -> 'Behind Enemy
    Lines'), or '___' if it isn't one.

    :param descriptions: MAME machine names (lower case, as MAME has them) -> their descriptions
    """
    if descriptions:
        return descriptions.get(file_name) or descriptions.get(file_name.lower()) or UNNAMED_ROM
    return UNNAMED_ROM


def fill_rom_names(entries: list[tuple[str, str]],
                   descriptions: dict[str, str]) -> tuple[list[tuple[str, str]], int, int]:
    """
    Name the unnamed ROM entries (see is_unnamed) that are MAME machines.  Names already given are kept.

    :returns:
    The entries, how many were named, and how many are still unnamed (not MAME machines).
    """
    filled, still_unnamed = 0, 0
    result = []
    for rom_name, file_name in entries:
        if is_unnamed(rom_name):
            new_name = rom_name_for(file_name, descriptions)
            if new_name != UNNAMED_ROM:
                rom_name = new_name
                filled += 1
            else:
                still_unnamed += 1
        result.append((rom_name, file_name))
    return result, filled, still_unnamed


# ----------------------------------------------------------------------------------------------------------------------
# non_mame_defaults.xml

# The fields each entry in non_mame_defaults.xml carries, besides its name.
DEFAULT_SETTING_FIELDS = ('validExtensions', 'includeExtension', 'includePath', 'defaultPath', 'extraCommands')


def load_default_emulator_settings(xml_path: str) -> dict[str, dict[str, str]]:
    """
    Read the recommended settings for each alternate emulator engine from non_mame_defaults.xml.

    Each engine is an <emulator> element holding <emulatorName> and the DEFAULT_SETTING_FIELDS.  Older copies of the
    file listed those elements flat, one after another, with no <emulator> wrapper; that layout is still read, each
    <emulatorName> starting a new entry, so an existing install's file keeps working.

    :param xml_path: Full path to non_mame_defaults.xml

    :returns:
    The settings keyed by emulator name, in file order.  Missing fields are absent from an entry's dict.

    :raises:
    ET.ParseError or OSError if the file cannot be read.
    """
    root = ET.parse(xml_path).getroot()
    emulators: dict[str, dict[str, str]] = {}

    wrapped = root.findall('.//emulator')
    if wrapped:
        for emulator in wrapped:
            name = (emulator.findtext('emulatorName') or '').strip()
            if name:
                emulators[name] = {field: (emulator.findtext(field) or '').strip()
                                   for field in DEFAULT_SETTING_FIELDS
                                   if emulator.find(field) is not None}
        return emulators

    # Legacy flat layout
    current = None
    for element in root:
        if element.tag == 'emulatorName':
            current = (element.text or '').strip()
            if current:
                emulators[current] = {}
        elif current and element.tag in DEFAULT_SETTING_FIELDS:
            emulators[current][element.tag] = (element.text or '').strip()
    return emulators
