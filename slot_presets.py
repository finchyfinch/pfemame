#!/usr/bin/env python3

# ----------------------------------------------------------------------------------------------------------------------
# slot_presets.py

"""
Named slot configurations per system, e.g. "IBM PC - dual 3.5in drives + mouse", so a hardware setup can be saved
once and switched back to quickly.  Stored in slot_presets.json in the user's data folder:

    {"ibm5150": {"Dual 3.5": {"slots": {"isa3": "fdc_xt", "isa3:fdc_xt:fdc:0": "35dd"}, "bios": "rev3"}}}

'slots' maps the full slot path to the option name ('' = empty), exactly what slot_model.SlotModel.build_rows()
takes.

This module has no wxPython dependency.
"""

import json
import os

FILE_NAME = 'slot_presets.json'


def load_all(path: str) -> dict:
    try:
        with open(path, encoding='utf-8') as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_all(path: str, data: dict) -> None:
    temp = path + '.tmp'
    with open(temp, 'w', encoding='utf-8') as handle:
        json.dump(data, handle, indent=1, sort_keys=True)
    os.replace(temp, path)


def names(path: str, system: str) -> list[str]:
    return sorted(load_all(path).get(system, {}), key=str.lower)


def get(path: str, system: str, name: str) -> dict | None:
    preset = load_all(path).get(system, {}).get(name)
    if not isinstance(preset, dict):
        return None
    return {'slots': dict(preset.get('slots', {})), 'bios': preset.get('bios', '')}


def save(path: str, system: str, name: str, slots: dict, bios: str = '') -> None:
    data = load_all(path)
    data.setdefault(system, {})[name] = {'slots': dict(slots), 'bios': bios}
    _save_all(path, data)


def delete(path: str, system: str, name: str) -> bool:
    data = load_all(path)
    if name not in data.get(system, {}):
        return False
    del data[system][name]
    if not data[system]:
        del data[system]
    _save_all(path, data)
    return True


def command_line(slots: dict, bios: str = '') -> str:
    """The MAME command-line options for a slot setup, e.g. '-bios rev3 -isa3 fdc_xt -isa3:fdc_xt:fdc:0 35dd'."""
    parts = [f'-bios {bios}'] if bios else []
    parts += [f'-{path} {option}' for path, option in slots.items() if option]
    return ' '.join(parts)
