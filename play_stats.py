#!/usr/bin/env python3

# ----------------------------------------------------------------------------------------------------------------------
# play_stats.py

"""
Play statistics: how often and for how long each ROM / system program has been played, and when it was last played.
Stored in play_stats.json in the user's data folder:

    {"pacman": {"plays": 12, "seconds": 7431.5, "last": "2026-09-27T20:14:03"},
     "spectrum-->Jetpac.tzx": {...}}

Runs shorter than MIN_SECONDS (MAME failed to start, missing ROM...) are not counted.

This module has no wxPython dependency.
"""

import datetime
import json
import os
import threading

# N_() marks a string for translation without translating it here (gettext's 'noop' convention) - the text is
# translated where it is displayed.  tools/create_language_files.py collects both _() and N_() strings.
def N_(text: str) -> str:
    return text


FILE_NAME = 'play_stats.json'
MIN_SECONDS = 3.0


def make_key(rom_file_name: str, system_file_name: str = '') -> str:
    """'pacman' for a ROM, 'spectrum-->Jetpac.tzx' for a system program."""
    return f'{rom_file_name}-->{system_file_name}' if system_file_name else rom_file_name


def row_key(row: list) -> str:
    """The key for a mylist row (column 1 = ROM file name, column 2 = system program file name)."""
    return make_key(row[1], row[2])


def format_duration(seconds: float) -> str:
    seconds = int(seconds)
    if seconds < 60:
        return f'{seconds}s'
    minutes = seconds // 60
    if minutes < 60:
        return f'{minutes}m'
    return f'{minutes // 60}h {minutes % 60:02d}m'


class PlayStats:
    def __init__(self, path: str):
        self.path = path
        self._lock = threading.Lock()
        self.entries: dict[str, dict] = {}
        try:
            with open(path, encoding='utf-8') as handle:
                data = json.load(handle)
            if isinstance(data, dict):
                self.entries = {k: v for k, v in data.items() if isinstance(v, dict)}
        except (OSError, ValueError):
            pass

    def record(self, key: str, seconds: float, when: datetime.datetime | None = None) -> bool:
        """Add one play of `seconds`.  Returns False (nothing recorded) for runs shorter than MIN_SECONDS."""
        if not key or seconds < MIN_SECONDS:
            return False
        with self._lock:
            entry = self.entries.setdefault(key, {'plays': 0, 'seconds': 0.0, 'last': ''})
            entry['plays'] = int(entry.get('plays', 0)) + 1
            entry['seconds'] = round(float(entry.get('seconds', 0.0)) + seconds, 1)
            entry['last'] = (when or datetime.datetime.now()).isoformat(timespec='seconds')
        return True

    def get(self, key: str) -> dict | None:
        return self.entries.get(key)

    def save(self) -> None:
        with self._lock:
            text = json.dumps(self.entries, indent=1, sort_keys=True)
        temp = self.path + '.tmp'
        with open(temp, 'w', encoding='utf-8') as handle:
            handle.write(text)
        os.replace(temp, self.path)

    def recent(self, limit: int = 100) -> list[str]:
        """Keys of the most recently played, newest first."""
        played = [(entry.get('last', ''), key) for key, entry in self.entries.items() if entry.get('last')]
        return [key for _last, key in sorted(played, reverse=True)[:limit]]

    def most_played(self, limit: int = 100) -> list[str]:
        """Keys with the most play time, then the most plays."""
        ranked = sorted(self.entries.items(),
                        key=lambda item: (item[1].get('seconds', 0), item[1].get('plays', 0)), reverse=True)
        return [key for key, entry in ranked[:limit] if entry.get('plays', 0) > 0]

    def describe(self, key: str, translate=lambda text: text) -> str:
        """
        'Played 12 times, 2h 03m in total, last played 27 Sep 2026' - or '' if never played.
        translate is the gettext function (the default leaves the text in English).
        """
        entry = self.entries.get(key)
        if not entry or not entry.get('plays'):
            return ''
        plays = int(entry['plays'])
        duration = format_duration(entry.get('seconds', 0))
        text = (translate(N_('Played once, {1} in total')) if plays == 1 else
                translate(N_('Played {0} times, {1} in total'))).format(plays, duration)
        try:
            last = datetime.datetime.fromisoformat(entry.get('last', ''))
            text += translate(N_(', last played {}')).format(f"{last.day} {last.strftime('%b %Y')}")
        except ValueError:
            pass
        return text
