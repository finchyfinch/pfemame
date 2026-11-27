#!/usr/bin/env python3

# ----------------------------------------------------------------------------------------------------------------------
# search.py

"""
The ROM list search box.

Plain words work as before: every word must appear somewhere in the ROM's name, ROM file name, program file name,
category, year or manufacturer.  On top of that, 'field:value' terms narrow the search:

    name:pac          title / description contains 'pac'
    rom:pacm          ROM (set) name contains 'pacm'
    file:.tzx         system program file name contains '.tzx'
    cat:shooter       category contains 'shooter'             (also category: / genre:)
    mfr:namco         manufacturer contains 'namco'           (also maker: / manufacturer:)
    year:1984         year starts with 1984 (year:198 = the 1980s)
    year:1980-1985    a range;  year:>1990  year:<=1985  also work
    rating:>=4        star rating;   runs:>10   number of runs
    is:fav  is:watch  is:missing  is:exists  is:program (system program files)  is:system

Put '-' in front of any term to exclude it (-cat:mahjong, -is:missing) and use quotes for values with spaces
(mfr:"data east").  Unknown fields are treated as ordinary words.

This module has no wxPython dependency.
"""

import re
import shlex
from dataclasses import dataclass, field

# N_() marks a string for translation without translating it here (gettext's 'noop' convention) - the text is
# translated where it is displayed.  tools/create_language_files.py collects both _() and N_() strings.
def N_(text: str) -> str:
    return text


# mylist columns (see pfemame.py)
INDEX_ROM_NAME = 0
INDEX_ROM_FILE_NAME = 1
INDEX_SYSTEM_PROGRAM_FILE_NAME = 2
INDEX_EXISTS = 3
INDEX_RATING = 4
INDEX_NUMBER_RUNS = 5
INDEX_FAVORITE = 6
INDEX_CATEGORY = 7
INDEX_YEAR = 10
INDEX_MANUFACTURER = 11

FIELDS = {'name': INDEX_ROM_NAME, 'title': INDEX_ROM_NAME, 'desc': INDEX_ROM_NAME,
          'rom': INDEX_ROM_FILE_NAME, 'set': INDEX_ROM_FILE_NAME,
          'file': INDEX_SYSTEM_PROGRAM_FILE_NAME, 'prog': INDEX_SYSTEM_PROGRAM_FILE_NAME,
          'program': INDEX_SYSTEM_PROGRAM_FILE_NAME,
          'cat': INDEX_CATEGORY, 'category': INDEX_CATEGORY, 'genre': INDEX_CATEGORY,
          'mfr': INDEX_MANUFACTURER, 'maker': INDEX_MANUFACTURER, 'manufacturer': INDEX_MANUFACTURER,
          'year': INDEX_YEAR, 'rating': INDEX_RATING, 'runs': INDEX_NUMBER_RUNS}
NUMERIC = {INDEX_YEAR, INDEX_RATING, INDEX_NUMBER_RUNS}
FLAGS = {'fav': 'fav', 'favorite': 'fav', 'favourite': 'fav', 'watch': 'watch', 'watchlist': 'watch',
         'missing': 'missing', 'exists': 'exists', 'have': 'exists', 'program': 'program', 'system': 'system',
         'parent': 'parent', 'clone': 'clone', 'working': 'working', 'imperfect': 'imperfect',
         'notworking': 'notworking', 'broken': 'notworking'}
WORD_COLUMNS = (INDEX_ROM_NAME, INDEX_ROM_FILE_NAME, INDEX_SYSTEM_PROGRAM_FILE_NAME, INDEX_CATEGORY, INDEX_YEAR,
                INDEX_MANUFACTURER)

HELP_TEXT = N_('Search:  words match the name, ROM, category, year or manufacturer.\n'
             'Fields:  name:  rom:  file:  cat:  mfr:  year:1984  year:1980-1985  year:>1990  rating:>=4  runs:>10\n'
             'Flags:   is:fav  is:watch  is:missing  is:exists  is:program  is:system\n'
             'Put - in front of a term to exclude it, and "quotes" around values with spaces.')

# The search box's hint, and the cheat sheet its '?' button shows (search_help.py): (heading, [(example, meaning)]).
# Clicking an example adds it to the search, so every example must be a working search term - tests check that.
HINT_TEXT = N_('Search (try cat:shooter year:1985)')

CHEAT_SHEET = (
    (N_('Words'), (
        ('pac man', N_('every word is in the name, ROM, category, year or manufacturer')),
    )),
    (N_('Fields'), (
        ('name:pac', N_('the name contains pac')),
        ('rom:pacm', N_('the ROM (set) name contains pacm')),
        ('file:.tzx', N_('a system program file name contains .tzx')),
        ('cat:shooter', N_('the category contains shooter')),
        ('mfr:namco', N_('the manufacturer contains namco')),
        ('year:1984', N_('made in 1984')),
        ('year:198', N_('made in the 1980s')),
        ('year:1980-1985', N_('made from 1980 to 1985')),
        ('year:>1990', N_('made after 1990  (also <, >= and <=)')),
        ('rating:>=4', N_('rated 4 stars or more')),
        ('runs:>10', N_('played more than 10 times')),
    )),
    (N_('Flags'), (
        ('is:fav', N_('favorites')),
        ('is:watch', N_('on the watchlist')),
        ('is:missing', N_('ROMs you don\'t have')),
        ('is:exists', N_('ROMs you have')),
        ('is:program', N_('system program files')),
        ('is:system', N_('systems (computers and consoles)')),
        ('is:parent', N_('parent sets (not clones)')),
        ('is:clone', N_('clones (other versions of a game)')),
        ('is:working', N_('working in MAME (including imperfect)')),
        ('is:imperfect', N_('working, with some problems')),
        ('is:notworking', N_('not working in MAME')),
    )),
    (N_('Leaving things out'), (
        ('-cat:mahjong', N_('put - in front of any term to leave those ROMs out')),
        ('mfr:"data east"', N_('use quotes round a value with spaces')),
    )),
)


def add_term(text: str, term: str) -> str:
    """The search text with term added to the end (a space between them), for the cheat sheet's examples."""
    text = text.rstrip()
    return f'{text} {term}' if text else term


_COMPARISON = re.compile(r'^(>=|<=|>|<|=)?\s*(-?\d+(?:\.\d+)?)$')
_RANGE = re.compile(r'^(\d+)\s*-\s*(\d+)$')


@dataclass
class Condition:
    column: int
    value: str                  # Lower-cased text, or '' for numeric conditions
    negate: bool = False
    low: float | None = None    # Numeric range (inclusive); None = open
    high: float | None = None
    prefix: bool = False        # year:198 -> starts-with


@dataclass
class Query:
    words: list = field(default_factory=list)           # (word, negate)
    conditions: list = field(default_factory=list)      # Condition
    flags: list = field(default_factory=list)           # (flag, negate)

    @property
    def is_empty(self) -> bool:
        return not (self.words or self.conditions or self.flags)


def _tokens(text: str) -> list[str]:
    try:
        return shlex.split(text, posix=True)
    except ValueError:              # Unbalanced quote while the user is still typing
        return text.replace('"', ' ').split()


def _numeric_condition(column: int, value: str, negate: bool) -> Condition | None:
    match = _RANGE.match(value)
    if match:
        return Condition(column, '', negate, float(match.group(1)), float(match.group(2)))
    match = _COMPARISON.match(value)
    if not match:
        return None
    op, number = match.group(1) or '', float(match.group(2))
    if op == '' and column == INDEX_YEAR:
        return Condition(column, value, negate, prefix=True)            # year:198 -> the 1980s
    bounds = {'>': (number + 1e-9, None), '>=': (number, None), '<': (None, number - 1e-9), '<=': (None, number),
              '=': (number, number), '': (number, number)}[op]
    return Condition(column, '', negate, *bounds)


def parse_query(text: str) -> Query:
    query = Query()
    for token in _tokens(text.lower()):
        negate = token.startswith('-') and len(token) > 1
        if negate:
            token = token[1:]
        name, sep, value = token.partition(':')
        if sep and name == 'is' and value in FLAGS:
            query.flags.append((FLAGS[value], negate))
        elif sep and name in FIELDS and value:
            column = FIELDS[name]
            condition = _numeric_condition(column, value, negate) if column in NUMERIC else None
            query.conditions.append(condition or Condition(column, value, negate))
        elif token:
            query.words.append((token, negate))
    return query


def _flag_true(row: list, flag: str) -> bool:
    if flag == 'fav':
        return row[INDEX_FAVORITE] == '1'
    if flag == 'watch':
        return row[INDEX_FAVORITE] == '2'
    if flag == 'missing':
        return row[INDEX_EXISTS] != '1'
    if flag == 'exists':
        return row[INDEX_EXISTS] == '1'
    if flag == 'program':
        return bool(row[INDEX_SYSTEM_PROGRAM_FILE_NAME])
    if flag == 'system':
        return not row[INDEX_SYSTEM_PROGRAM_FILE_NAME] and row[INDEX_ROM_FILE_NAME] in _SYSTEMS
    if flag in ('parent', 'clone'):
        return is_clone(row) == (flag == 'clone')
    if flag == 'working':
        return is_working(row)
    if flag == 'imperfect':
        return _status(row) == 'imperfect'
    if flag == 'notworking':
        return not is_working(row)
    return False


_SYSTEMS: set = set()
_MACHINE_INFO: dict = {}


def set_machine_info(info: dict) -> None:
    """{machine name: (parent, driver status)} from rom_database.machine_info - pfemame.py passes it."""
    global _MACHINE_INFO
    _MACHINE_INFO = dict(info)


# A system program row belongs to its system (a program listed under a clone system is a clone's), and a game of
# another emulator isn't a MAME machine at all, so it counts as a parent that works.
def is_clone(row: list) -> bool:
    return bool(_MACHINE_INFO.get(row[INDEX_ROM_FILE_NAME], ('', ''))[0])


def _status(row: list) -> str:
    return _MACHINE_INFO.get(row[INDEX_ROM_FILE_NAME], ('', ''))[1]


def is_working(row: list) -> bool:
    """MAME's driver status is good or imperfect (runs with some problems) - not preliminary."""
    return _status(row) != 'preliminary'


def keep_row(row: list, hide_clones: bool, working_only: bool) -> bool:
    """The main window's Hide clones / Working only tick boxes."""
    return not (hide_clones and is_clone(row)) and not (working_only and not is_working(row))


def set_system_names(names: set) -> None:
    """The ROM names that are systems (for is:system) - pfemame.py passes rom_database's list."""
    global _SYSTEMS
    _SYSTEMS = set(names)


def _condition_true(row: list, condition: Condition) -> bool:
    text = str(row[condition.column]).lower()
    if condition.low is not None or condition.high is not None:
        try:
            number = float(text)
        except ValueError:
            return False                            # e.g. year '198?' can't be compared
        return ((condition.low is None or number >= condition.low) and
                (condition.high is None or number <= condition.high))
    if condition.prefix:
        return text.startswith(condition.value)
    return condition.value in text


def matches(row: list, query: Query) -> bool:
    if query.words:
        haystack = '\n'.join(str(row[i]) for i in WORD_COLUMNS).lower()
        for word, negate in query.words:
            if (word in haystack) == negate:
                return False
    for condition in query.conditions:
        if _condition_true(row, condition) == condition.negate:
            return False
    for flag, negate in query.flags:
        if _flag_true(row, flag) == negate:
            return False
    return True
