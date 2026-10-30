#!/usr/bin/env python3

# ----------------------------------------------------------------------------------------------------------------------
# slot_model.py

"""
Slot / sub-slot model for a MAME system, built from the output of `mame <system> -listxml -nodtd`.

How MAME describes slots (checked against MAME 0.289):
  * The system's own <machine> block lists its slots AND the complete *default* device tree using full paths, e.g.
        isa3                  (default option 'fdc_xt', device 'isa8_fdc_xt')
        isa3:fdc_xt:fdc:0     (default option '525dd')
  * Every device that can be plugged in has its own <machine isdevice="yes"> block listing the slots it exposes,
    named relative to the device with a leading colon (':fdc:0', ':serport0').
  * A sub-slot's full path is  <parent slot path>:<chosen option name><device relative slot name>
        'isa3' + ':fdc_xt' + ':fdc:0'  ->  'isa3:fdc_xt:fdc:0'
  * A colon in a slot name does NOT always mean a sub-slot.  On cpc6128, 'upd765:0' is a floppy connector on a
    built-in controller - it belongs to the machine itself.  A slot is only a sub-slot when its path starts with
    '<another slot>:<one of that slot's options>:'.

The model walks that tree recursively, so default slots, slots loaded from a ROM INI file and slots changed by the
user all produce their sub-slots the same way, at any depth.

Rows map directly onto the ROM INI format written by preferences.py:
    top-level row:  slot_name='isa3'    option='fdc_xt'  parent=''              ->  isa3 fdc_xt
    sub-slot row :  slot_name=':fdc:0'  option='525dd'   parent='isa3:fdc_xt'   ->  isa3:fdc_xt:fdc:0 525dd #(SUB)(PARENT=isa3:fdc_xt)
"""

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

MAX_DEPTH = 4   # Guards against self-referencing chains such as spectrum exp -> melodik -> exp -> fuller -> ...


@dataclass
class SlotOption:
    name: str               # Option name used on the MAME command line / in the INI file (e.g. 'fdc_xt')
    devname: str            # Device machine name (e.g. 'isa8_fdc_xt')
    default: bool = False


@dataclass
class Slot:
    name: str
    options: list[SlotOption] = field(default_factory=list)

    @property
    def default(self) -> SlotOption | None:
        return next((option for option in self.options if option.default), None)

    def option(self, name: str) -> SlotOption | None:
        return next((option for option in self.options if option.name == name), None)


@dataclass
class SlotRow:
    level: int              # 0 = top-level slot, 1+ = sub-slot depth
    slot_name: str          # 'isa3' or ':fdc:0'
    option: str             # Selected option name ('' = empty)
    devname: str            # Selected device name ('' = empty)
    parent: str             # '' or 'isa3:fdc_xt'
    choices: list[SlotOption]

    @property
    def full_path(self) -> str:
        return f'{self.parent}{self.slot_name}' if self.parent else self.slot_name


class SlotModel:
    def __init__(self, xml_text: str, rom_name: str):
        self.rom_name = rom_name
        self.descriptions: dict[str, str] = {}
        self.machine_slots: dict[str, list[Slot]] = {}
        self.biossets: list[tuple[str, str, bool]] = []     # (name, description, is_default)
        self.error = ''

        start = xml_text.find('<mame')
        if start == -1:
            self.error = 'No XML returned by MAME'
        else:
            try:
                root = ET.fromstring(xml_text[start:])
            except ET.ParseError as e:
                root = None
                self.error = f'Unable to parse the MAME XML: {e}'
            if root is not None:
                for machine in root.iter('machine'):
                    name = machine.get('name', '')
                    self.descriptions[name] = machine.findtext('description', '')
                    self.machine_slots[name] = [
                        Slot(slot.get('name', ''),
                             [SlotOption(opt.get('name', ''), opt.get('devname', ''), opt.get('default') == 'yes')
                              for opt in slot.iter('slotoption')])
                        for slot in machine.findall('slot')]
                    if name == rom_name:
                        self.biossets = [(bios.get('name', ''), bios.get('description', ''),
                                          bios.get('default') == 'yes')
                                         for bios in machine.findall('biosset')]

        self.main_slots = {slot.name: slot for slot in self.machine_slots.get(rom_name, [])}
        self._selected: dict[str, str] = {}

    # ------------------------------------------------------------------------------------------------------------------
    def top_level_slots(self) -> list[Slot]:
        """Slots that belong to the machine itself (see the module notes about names containing a colon)."""
        slots = self.machine_slots.get(self.rom_name, [])
        prefixes = tuple(f'{slot.name}:{option.name}:' for slot in slots for option in slot.options)
        return [slot for slot in slots if not (prefixes and slot.name.startswith(prefixes))]

    def top_level_slot(self, name: str) -> Slot | None:
        return next((slot for slot in self.top_level_slots() if slot.name == name), None)

    def sub_slots_of(self, devname: str) -> list[Slot]:
        """Slots exposed by a device, with names normalised to a single leading ':'."""
        return [Slot(':' + slot.name.lstrip(':'), slot.options) for slot in self.machine_slots.get(devname, [])]

    def label(self, option: SlotOption) -> str:
        """Friendly drop-down text, e.g. 'ISA 8bits XT FDC hookup (fdc_xt)'."""
        description = self.descriptions.get(option.devname, '')
        return f'{description} ({option.name})' if description else option.name

    # ------------------------------------------------------------------------------------------------------------------
    def default_rows(self) -> list[SlotRow]:
        """All slots set to MAME's defaults, including the sub-slots of every default device."""
        return self.build_rows(None)

    def build_rows(self, selected: dict[str, str] | None) -> list[SlotRow]:
        """
        Walk the slot tree.

        :param selected: {full slot path: option name} as saved in the ROM INI, e.g.
                         {'isa3': 'fdc_xt', 'isa3:fdc_xt:fdc:0': '35dd'}.  An empty option name means empty.
                         Paths that are not in `selected` get MAME's default - which is exactly what MAME itself
                         does for slots the INI file doesn't mention.  None = pure defaults.
        """
        self._selected = selected or {}
        rows: list[SlotRow] = []
        for slot in self.top_level_slots():
            chosen = self._choose(slot.name, slot, slot.default)
            rows.append(SlotRow(0, slot.name, chosen.name if chosen else '', chosen.devname if chosen else '', '',
                                slot.options))
            if chosen:
                self._expand(slot.name, chosen, 1, rows)
        return rows

    def expand_rows(self, parent_path: str, option: SlotOption, level: int) -> list[SlotRow]:
        """Rows to insert beneath a row whose device has just been changed (its sub-slots, set to defaults)."""
        self._selected = {}
        rows: list[SlotRow] = []
        self._expand(parent_path, option, level, rows)
        return rows

    def _choose(self, full_path: str, slot: Slot, default: SlotOption | None) -> SlotOption | None:
        if full_path in self._selected:
            return slot.option(self._selected[full_path])
        return default

    def _expand(self, parent_path: str, option: SlotOption, level: int, rows: list[SlotRow]) -> None:
        if level > MAX_DEPTH:
            return
        prefix = f'{parent_path}:{option.name}'
        for sub in self.sub_slots_of(option.devname):
            full = prefix + sub.name
            # The system's own block lists the real default tree with full paths - prefer its default, and fall
            # back to the default declared by the device itself.
            main_entry = self.main_slots.get(full)
            default = (main_entry.default if main_entry else None) or sub.default
            chosen = self._choose(full, sub, default)
            rows.append(SlotRow(level, sub.name, chosen.name if chosen else '', chosen.devname if chosen else '',
                                prefix, sub.options))
            if chosen:
                self._expand(full, chosen, level + 1, rows)


# ----------------------------------------------------------------------------------------------------------------------
def parse_ini_slots(content: list[str]) -> dict[str, str] | None:
    """
    Read the '# SLOT DEVICES' section of a pfeMAME ROM INI file into {full slot path: option name}.
    Returns None if the file has no slot section.

    Lines look like:   isa3 fdc_xt
                       isa3:fdc_xt:fdc:0 525dd #(SUB)(PARENT=isa3:fdc_xt)
    """
    try:
        start = content.index('# SLOT DEVICES\n')
        end = content.index('# END OF SLOT DEVICES\n')
    except ValueError:
        return None

    selected: dict[str, str] = {}
    for line in content[start + 1:end]:
        line = line.split('#', 1)[0].strip()
        if not line:
            continue
        parts = line.split()
        selected[parts[0]] = parts[1] if len(parts) > 1 else ''
    return selected


# ----------------------------------------------------------------------------------------------------------------------
# Command line test:  python slot_model.py <path to mame> <system> [<system> ...]
if __name__ == '__main__':
    import subprocess
    import sys

    for system in sys.argv[2:]:
        output = subprocess.run([sys.argv[1], system, '-listxml', '-nodtd'], capture_output=True, text=True,
                                encoding='utf-8', errors='replace').stdout
        model = SlotModel(output, system)
        print(f'== {system} {model.error}')
        for row in model.default_rows():
            print(f'  {"    " * row.level}{row.slot_name:<14} {row.option or "(empty)":<16} {row.full_path}')
