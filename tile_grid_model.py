#!/usr/bin/env python3

# ----------------------------------------------------------------------------------------------------------------------
# tile_grid_model.py

"""
Data / paging model for the Tile View.

Holds the filtered ROM list, the index of the first ROM on screen and the focused tile, and works out what each
navigation move does.  It has no wx dependency so the navigation rules can be unit tested on their own.

The ROM on any tile is always  filtered[start_index + slot]  - tiles past the end of the list are blank.
"""

import glob
import os
from collections import Counter, OrderedDict

import play_stats

# Indexes into a mylist row
index_rom_name = 0
index_rom_file_name = 1
index_system_program_file_name = 2
index_exists = 3
index_number_runs = 5
index_favorite = 6
index_category = 7
index_system_short_name = 8
index_system_folder_name = 9

UP, DOWN, LEFT, RIGHT = 'up', 'down', 'left', 'right'


# The entry a ROM has in favorites.dat / watchlist.dat (the same format as pfemame.get_rom_file_name)
def favorite_key(row: list) -> str:
    if row[index_system_program_file_name]:
        return f'{row[index_rom_file_name]}-->{row[index_rom_name]}-->{row[index_system_program_file_name]}'
    return row[index_rom_file_name]

PAGE_UP, PAGE_DOWN, HOME, END = 'page_up', 'page_down', 'home', 'end'

# Views, in the order the view key cycles through them.  The keys are the main window's (views.VIEW_KEYS).  Tile View
# only holds ROMs that exist, so the main window's All and Missing views have no Tile View equivalent.  The played
# views only show ROMs that have been played, in play statistics order.
VIEW_EXISTS, VIEW_FAVORITES, VIEW_WATCHLIST = 'Exists', 'Favorites', 'Watchlist'
VIEW_RECENT, VIEW_MOST_PLAYED = 'Recent', 'MostPlayed'
TILE_VIEWS = (VIEW_EXISTS, VIEW_FAVORITES, VIEW_WATCHLIST, VIEW_RECENT, VIEW_MOST_PLAYED)
PLAYED_VIEWS = (VIEW_RECENT, VIEW_MOST_PLAYED)


# The Tile View view for a main window view key (or a saved one).  All, Missing and anything unknown give Exists.
def tile_view_key(view: str) -> str:
    return view if view in TILE_VIEWS else VIEW_EXISTS


# Sort orders, in the order the sort key cycles through them.  They don't apply to the played views, which have their
# own order.  SORT_MOST_RUNS only shows ROMs that have been run.
SORT_NAME, SORT_MOST_RUNS = 'name', 'most_runs'
SORT_ORDERS = (SORT_NAME, SORT_MOST_RUNS)
MOVES = (UP, DOWN, LEFT, RIGHT, PAGE_UP, PAGE_DOWN, HOME, END)


# ----------------------------------------------------------------------------------------------------------------------
# Find a ROM's preview video (any file extension), or None.  Arcade ROMs use <video folder>\<rom>.*.  Software list
# programs look in <video folder>\<system>\ - by short name, then by program file name, the same as the
# snapshots - and then use the system's own video, <video folder>\<system>.*
def find_video(video_folder: str, row: list) -> str | None:
    rom_file_name = row[index_rom_file_name]
    program = row[index_system_program_file_name]

    candidates = []
    if program:
        system_folder = os.path.join(video_folder, rom_file_name)
        if os.path.isdir(system_folder):
            if row[index_system_short_name]:
                candidates.append((system_folder, row[index_system_short_name]))
            candidates.append((system_folder, os.path.splitext(program)[0]))
    candidates.append((video_folder, rom_file_name))

    for folder, name in candidates:
        matches = glob.glob(os.path.join(glob.escape(folder), f'{glob.escape(name)}.*'))
        match = next((path for path in sorted(matches) if os.path.isfile(path)), None)
        if match:
            return match
    return None


# ----------------------------------------------------------------------------------------------------------------------
# Move per-tile data along when the page scrolls by one row, so only the new row has to be loaded.
# row_delta is +1 when scrolling down (tiles move up) and -1 when scrolling up.  Vacated slots are set to None.
def shift_page(items: list, row_delta: int, columns: int) -> list:
    shift = row_delta * columns
    if shift == 0:
        return list(items)
    if abs(shift) >= len(items):
        return [None] * len(items)
    if shift > 0:
        return items[shift:] + [None] * shift
    return [None] * -shift + items[:shift]


# ----------------------------------------------------------------------------------------------------------------------
# Decides when a held joystick / D-pad direction should move again.  The first push moves straight away, then after
# a short delay it repeats, speeding up the longer the direction is held.  Times are in seconds.
class HoldRepeater:

    def __init__(self,
                 initial_delay: float = 0.4,
                 repeat_interval: float = 0.15,
                 fast_interval: float = 0.06,
                 fast_after: float = 1.5):
        self.initial_delay = initial_delay
        self.repeat_interval = repeat_interval
        self.fast_interval = fast_interval
        self.fast_after = fast_after
        self.direction = None
        self._pressed_at = 0.0
        self._next_at = 0.0

    # Call regularly with the direction currently held (None when centred).  Returns True when a move is due.
    def update(self, direction: str | None, now: float, accelerate: bool = True) -> bool:
        if direction != self.direction:
            self.direction = direction
            if direction is None:
                return False
            self._pressed_at = now
            self._next_at = now + self.initial_delay
            return True

        if direction is None or now < self._next_at:
            return False

        held_for = now - self._pressed_at
        fast = accelerate and held_for >= self.fast_after
        self._next_at = now + (self.fast_interval if fast else self.repeat_interval)
        return True


# ----------------------------------------------------------------------------------------------------------------------
# A small least-recently-used cache (used for the tile images)
class LruCache:

    def __init__(self, max_items: int):
        self.max_items = max_items
        self._items = OrderedDict()

    def __len__(self) -> int:
        return len(self._items)

    def __contains__(self, key) -> bool:
        return key in self._items

    def get(self, key):
        value = self._items.get(key)
        if value is not None:
            self._items.move_to_end(key)
        return value

    def put(self, key, value) -> None:
        self._items[key] = value
        self._items.move_to_end(key)
        while len(self._items) > self.max_items:
            self._items.popitem(last=False)


# ----------------------------------------------------------------------------------------------------------------------
class TileGridModel:

    def __init__(self, roms: list, columns: int, rows: int, categories: list, ignore_categories: bool):
        self.columns = max(1, columns)
        self.rows = max(1, rows)
        self.page_size = self.columns * self.rows
        self.roms = roms                                # Only ROMs that exist
        self.categories = list(categories) + ['']       # ROMs with no category are always allowed
        self.ignore_categories = ignore_categories

        self.filtered: list = []
        self.view = VIEW_EXISTS
        self.search = ''
        self.sort = SORT_NAME
        self.category = ''              # Show only this category ('' = all categories)
        self.play_stats = None          # play_stats.PlayStats, needed for the played views
        self.start_index = 0
        self.focused = 0

    # ------------------------------------------------------------------------------------------------------------------
    @property
    def size(self) -> int:
        return len(self.filtered)

    # ------------------------------------------------------------------------------------------------------------------
    # Rebuild the filtered list and go back to the first ROM
    def apply_filter(self, view: str, search: str = '', category: str | None = None) -> None:
        self.view = view
        self.search = search.strip()
        if category is not None:
            self.category = category
        self.filtered = self.matching(view, self.search)
        self.start_index = 0
        self.focused = 0

    # ------------------------------------------------------------------------------------------------------------------
    # Move on to the next view and rebuild the list (keeping the search and category)
    def cycle_view(self) -> None:
        self.apply_filter(self.next_view, self.search)

    # The view the view key changes to next
    @property
    def next_view(self) -> str:
        return TILE_VIEWS[(TILE_VIEWS.index(self.view) + 1) % len(TILE_VIEWS)]

    # ------------------------------------------------------------------------------------------------------------------
    # True when the sort key changes the order of the current view (the played views have their own order)
    @property
    def sort_applies(self) -> bool:
        return self.view not in PLAYED_VIEWS

    # ------------------------------------------------------------------------------------------------------------------
    # Move on to the next sort order and rebuild the list (keeping the view / search filter)
    def cycle_sort(self) -> None:
        self.sort = SORT_ORDERS[(SORT_ORDERS.index(self.sort) + 1) % len(SORT_ORDERS)]
        self.apply_filter(self.view, self.search)

    # ------------------------------------------------------------------------------------------------------------------
    # The ROMs a filter would show (in the current sort order), without applying it.  category=None means the
    # current category.
    def matching(self, view: str, search: str = '', category: str | None = None) -> list:
        search_lower = search.strip().lower()
        category = self.category if category is None else category
        flag = {VIEW_FAVORITES: '1', VIEW_WATCHLIST: '2'}.get(view)

        def rom_matches(line: list) -> bool:
            return ((flag is None or line[index_favorite] == flag)
                    and (self.ignore_categories or line[index_category] in self.categories)
                    and (not category or line[index_category] == category)
                    and (not search_lower or search_lower in line[index_rom_name].lower()))

        return self._sorted([line for line in self.roms if rom_matches(line)], view)

    # ------------------------------------------------------------------------------------------------------------------
    # How many ROMs each category has in the current view (view / search / sort, any category), largest first.
    # Categories with no ROMs are left out.
    def category_counts(self) -> list[tuple[str, int]]:
        counts = Counter(line[index_category] for line in self.matching(self.view, self.search, category=''))
        return sorted(counts.items(), key=lambda item: (-item[1], item[0].lower()))

    # ------------------------------------------------------------------------------------------------------------------
    # Put ROMs in the view's order (played views) or the current sort order.  The ROM list is already in name order,
    # and the sorts are stable, so ROMs that tie keep their name order.
    def _sorted(self, rows: list, view: str) -> list:
        if view in PLAYED_VIEWS:
            if self.play_stats is None:
                return []
            keys = self.play_stats.recent() if view == VIEW_RECENT else self.play_stats.most_played()
            position = {key: number for number, key in enumerate(keys)}
            played = [row for row in rows if play_stats.row_key(row) in position]
            return sorted(played, key=lambda row: position[play_stats.row_key(row)])

        if self.sort == SORT_MOST_RUNS:
            def runs(row: list) -> int:
                try:
                    return int(row[index_number_runs])
                except ValueError:
                    return 0
            return sorted((row for row in rows if runs(row) > 0), key=runs, reverse=True)

        return rows

    # ------------------------------------------------------------------------------------------------------------------
    # The ROM row shown on a tile, or None for a blank tile
    def row_at(self, slot: int) -> list | None:
        if not 0 <= slot < self.page_size:
            return None
        list_index = self.start_index + slot
        if list_index >= self.size or self.filtered[list_index][index_rom_name] == '':
            return None
        return self.filtered[list_index]

    @property
    def focused_row(self) -> list | None:
        return self.row_at(self.focused)

    # ------------------------------------------------------------------------------------------------------------------
    # Pull the focus back onto the last ROM if it is sitting on a blank tile
    def clamp_focus(self) -> None:
        while self.focused > 0 and self.row_at(self.focused) is None:
            self.focused -= 1

    # ------------------------------------------------------------------------------------------------------------------
    # Move the focus one step.  Returns (focus_moved, page_scrolled); the old focus index is the caller's to keep.
    def move(self, direction: str) -> tuple[bool, bool]:
        cols = self.columns
        focused = self.focused

        if direction == LEFT:
            if focused % cols != 0:
                self.focused -= 1
                return True, False

        elif direction == RIGHT:
            if (focused + 1) % cols != 0 and self.row_at(focused + 1) is not None:
                self.focused += 1
                return True, False

        elif direction == UP:
            if focused >= cols:
                self.focused -= cols
                return True, False
            if self.start_index > 0:
                self.start_index -= cols
                return False, True

        elif direction == DOWN:
            if self.row_at(focused + cols) is not None:
                self.focused += cols
                return True, False
            if self.start_index + self.page_size < self.size:
                self.start_index += cols
                self.clamp_focus()  # The new bottom row may be partly blank
                return self.focused != focused, True

        elif direction == PAGE_DOWN:
            if self.start_index < self.last_page_start:
                return self._set_position(min(self.start_index + self.page_size, self.last_page_start), focused)
            return self._set_position(self.start_index, focused % cols + (self.rows - 1) * cols)  # Bottom row

        elif direction == PAGE_UP:
            if self.start_index > 0:
                return self._set_position(max(self.start_index - self.page_size, 0), focused)
            return self._set_position(0, focused % cols)  # Top row

        elif direction == HOME:
            return self._set_position(0, 0)

        elif direction == END:
            return self._set_position(self.last_page_start, self.page_size - 1)

        return False, False

    # ------------------------------------------------------------------------------------------------------------------
    # The start index of the page that shows the end of the list
    @property
    def last_page_start(self) -> int:
        last_row = (self.size - 1) // self.columns if self.size else 0
        return max(0, last_row - self.rows + 1) * self.columns

    # ------------------------------------------------------------------------------------------------------------------
    # Show a page and focus a tile on it (pulled back onto a ROM if the tile is blank).
    # Returns (focus_moved, page_scrolled) like move().
    def _set_position(self, start_index: int, focused: int) -> tuple[bool, bool]:
        old_start, old_focused = self.start_index, self.focused
        self.start_index = start_index
        self.focused = min(max(focused, 0), self.page_size - 1)
        self.clamp_focus()
        return self.focused != old_focused, self.start_index != old_start

    # ------------------------------------------------------------------------------------------------------------------
    # Show the ROM at a position in the filtered list, scrolling so that its row is at the top where possible.
    # Returns (focus_moved, page_scrolled) like move().
    def show_index(self, index: int) -> tuple[bool, bool]:
        if self.start_index <= index < self.start_index + self.page_size:
            return self._set_position(self.start_index, index - self.start_index)  # Already on screen
        start = min((index // self.columns) * self.columns, self.last_page_start)
        return self._set_position(start, index - start)

    # ------------------------------------------------------------------------------------------------------------------
    # The position in the filtered list of the ROM with a favorite_key(), or None if it isn't in the list
    def find_key(self, key: str) -> int | None:
        if not key:
            return None
        return next((index for index, row in enumerate(self.filtered) if favorite_key(row) == key), None)

    # ------------------------------------------------------------------------------------------------------------------
    # Find the next ROM after the focused one whose name starts with a letter, wrapping round to the top of the list.
    # Returns its index in the filtered list, or None if no ROM starts with that letter.
    def find_next_letter(self, letter: str) -> int | None:
        if not self.size:
            return None
        letter = letter.upper()
        current = self.start_index + self.focused
        for offset in range(1, self.size + 1):
            index = (current + offset) % self.size
            if self.filtered[index][index_rom_name][:1].upper() == letter:
                return index
        return None
