"""Tile View navigation / paging rules (tile_grid_model)."""
from tile_grid_model import (TileGridModel, LruCache, HoldRepeater, shift_page,
                             UP, DOWN, LEFT, RIGHT, PAGE_UP, PAGE_DOWN, HOME, END, index_rom_file_name)


def make_row(rom_file_name, rom_name=None, program='', favorite='0', category='', folder=''):
    # Same 12 column layout as mylist
    return [rom_name or rom_file_name, rom_file_name, program, '1', '0', '0', favorite, category, '', folder, '', '']


def make_model(count, columns=6, rows=4, **kwargs):
    roms = [make_row(f'rom{i:03}') for i in range(count)]
    model = TileGridModel(roms, columns=columns, rows=rows, categories=[], ignore_categories=True, **kwargs)
    model.apply_filter('Exists')
    return model


def focused_name(model):
    return model.focused_row[index_rom_file_name]


def test_row_is_taken_from_the_tile_position_not_a_name_lookup():
    # Two systems with the same program file name - each tile must give its own row
    roms = [make_row('gameboy', program='tetris.zip', folder='gb'),
            make_row('nes', program='tetris.zip', folder='nes')]
    model = TileGridModel(roms, columns=6, rows=4, categories=[], ignore_categories=True)
    model.apply_filter('Exists')
    model.move(RIGHT)
    assert model.focused_row is roms[1]


def test_scrolling_down_onto_a_partial_row_pulls_focus_back_onto_a_rom():
    model = make_model(26)                       # 6x4 page, last row of the list has only 2 ROMs
    model.focused = 23                           # bottom right tile
    moved, scrolled = model.move(DOWN)
    assert scrolled and model.start_index == 6
    assert model.focused_row is not None
    assert focused_name(model) == 'rom025'      # last ROM in the list
    assert moved


def test_down_moves_within_the_page_without_scrolling():
    model = make_model(30)
    assert model.move(DOWN) == (True, False)
    assert model.focused == 6


def test_down_on_the_last_page_does_nothing():
    model = make_model(10)                       # fits on one page
    model.focused = 9
    assert model.move(DOWN) == (False, False)


def test_right_stops_at_the_end_of_the_list_and_the_row():
    model = make_model(3)
    model.focused = 2
    assert model.move(RIGHT) == (False, False)
    model = make_model(30)
    model.focused = 5                            # last column
    assert model.move(RIGHT) == (False, False)


def test_left_stops_at_the_first_column():
    model = make_model(30)
    model.focused = 6
    assert model.move(LEFT) == (False, False)


def test_up_scrolls_back_to_the_top_with_narrow_grids():
    # A 1 or 2 column grid used to get stuck one row from the top
    for columns in (1, 2, 3):
        model = make_model(20, columns=columns, rows=2)
        model.start_index = columns
        assert model.move(UP) == (False, True)
        assert model.start_index == 0


def test_filter_resets_position_and_focus():
    roms = [make_row(f'rom{i}', favorite='1' if i % 2 else '0') for i in range(40)]
    model = TileGridModel(roms, columns=6, rows=4, categories=[], ignore_categories=True)
    model.apply_filter('Exists')
    model.start_index, model.focused = 12, 20
    model.apply_filter('Favorites')
    assert (model.start_index, model.focused, model.size) == (0, 0, 20)
    assert all(row[6] == '1' for row in model.filtered)


def test_search_and_category_filters():
    roms = [make_row('pacman', 'Pac-Man', category='Maze'),
            make_row('mspacman', 'Ms. Pac-Man', category='Maze'),
            make_row('galaga', 'Galaga', category='Shooter'),
            make_row('nocat', 'Pac Nothing', category='')]
    model = TileGridModel(roms, columns=6, rows=4, categories=['Maze'], ignore_categories=False)
    model.apply_filter('Exists', search='  pac-MAN ')
    assert [row[1] for row in model.filtered] == ['pacman', 'mspacman']
    model.apply_filter('Exists')
    assert [row[1] for row in model.filtered] == ['pacman', 'mspacman', 'nocat']   # Uncategorised always shown


def test_empty_list_has_no_focused_row_and_does_not_move():
    model = make_model(0)
    assert model.focused_row is None
    for direction in (UP, DOWN, LEFT, RIGHT):
        assert model.move(direction) == (False, False)


def test_grid_size_is_at_least_one_tile():
    model = make_model(5, columns=0, rows=0)
    assert model.page_size == 1
    assert model.move(DOWN) == (False, True)


def test_shift_page_moves_tiles_with_the_scroll():
    page = list(range(12))                       # 4 columns x 3 rows
    assert shift_page(page, 1, 4) == [4, 5, 6, 7, 8, 9, 10, 11, None, None, None, None]    # scrolled down
    assert shift_page(page, -1, 4) == [None, None, None, None, 0, 1, 2, 3, 4, 5, 6, 7]     # scrolled up
    assert shift_page(page, 0, 4) == page
    assert shift_page(page[:4], 1, 4) == [None] * 4                                        # single row page


def test_lru_cache_drops_the_least_recently_used_item():
    cache = LruCache(2)
    cache.put('a', 1)
    cache.put('b', 2)
    assert cache.get('a') == 1                   # 'a' is now the most recently used
    cache.put('c', 3)
    assert 'b' not in cache and 'a' in cache and 'c' in cache
    assert len(cache) == 2
    assert cache.get('missing') is None


def test_page_down_moves_a_screen_and_stops_on_the_last_page():
    model = make_model(100)                      # 6x4 page = 24 tiles, list ends part way through row 17
    model.focused = 8
    assert model.move(PAGE_DOWN) == (False, True)
    assert (model.start_index, model.focused) == (24, 8)
    for _i in range(10):
        model.move(PAGE_DOWN)
    assert model.start_index == model.last_page_start == 78      # last page shows rows 13-16
    # On the last page PAGE DOWN drops to the bottom row in the same column
    assert focused_name(model) == 'rom098'
    model.move(LEFT), model.move(UP)
    model.focused = 5                            # Last column - its bottom tile is blank
    model.move(PAGE_DOWN)
    assert focused_name(model) == 'rom099'      # Pulled back onto the last ROM


def test_page_up_moves_a_screen_then_to_the_top_row():
    model = make_model(100)
    model.start_index, model.focused = 30, 15
    assert model.move(PAGE_UP) == (False, True)
    assert (model.start_index, model.focused) == (6, 15)
    model.move(PAGE_UP)
    assert (model.start_index, model.focused) == (0, 15)
    assert model.move(PAGE_UP) == (True, False)
    assert model.focused == 3                    # Same column, top row


def test_home_and_end():
    model = make_model(100)
    model.move(END)
    assert focused_name(model) == 'rom099'
    model.move(HOME)
    assert (model.start_index, model.focused) == (0, 0)
    small = make_model(5)
    small.move(END)
    assert (small.start_index, focused_name(small)) == (0, 'rom004')


def test_letter_jump_finds_the_next_match_and_wraps():
    names = ['Alpha', 'Beta', 'Bravo', 'Charlie', 'Bingo', 'delta']
    roms = [make_row(f'r{i}', name) for i, name in enumerate(names)]
    model = TileGridModel(roms, columns=2, rows=2, categories=[], ignore_categories=True)
    model.apply_filter('Exists')
    assert model.find_next_letter('b') == 1
    model.show_index(1)
    assert model.find_next_letter('B') == 2
    model.show_index(4)
    assert model.find_next_letter('B') == 1      # Wraps round to the top
    assert model.find_next_letter('D') == 5      # Case-insensitive
    assert model.find_next_letter('Z') is None


def test_show_index_scrolls_only_when_needed():
    model = make_model(100)
    assert model.show_index(5) == (True, False)  # Already on screen
    assert model.show_index(50) == (True, True)
    assert (model.start_index, focused_name(model)) == (48, 'rom050')
    model.show_index(99)
    assert (model.start_index, focused_name(model)) == (78, 'rom099')    # Can't scroll past the last page


def held_moves(repeater, direction, seconds, accelerate=True, step=0.02):
    """Times (from the first push) at which a direction held for `seconds` moves, polled every `step`."""
    moves = []
    for tick in range(round(seconds / step) + 1):
        now = tick * step
        if repeater.update(direction, now, accelerate):
            moves.append(round(now, 2))
    return moves


def test_hold_repeater_moves_at_once_then_repeats_and_speeds_up():
    moves = held_moves(HoldRepeater(), DOWN, 2.0)
    assert moves[:4] == [0.0, 0.4, 0.56, 0.72]   # Immediate, 0.4s delay, then every ~0.15s (one 20ms poll late)
    gaps = [round(b - a, 2) for a, b in zip(moves, moves[1:])]
    assert all(gap >= 0.15 for gap in gaps if gap > 0.1) and min(gaps[-5:]) < 0.1   # Faster after 1.5s held


def test_hold_repeater_no_speed_up_when_asked():
    moves = held_moves(HoldRepeater(), DOWN, 3.0, accelerate=False)
    gaps = [round(b - a, 2) for a, b in zip(moves[1:], moves[2:])]
    assert min(gaps) >= 0.15


def test_hold_repeater_resets_on_release_and_direction_change():
    repeater = HoldRepeater()
    assert repeater.update(DOWN, 0.0)
    assert not repeater.update(DOWN, 0.1)
    assert not repeater.update(None, 0.2)        # Released
    assert repeater.update(DOWN, 0.25)           # Pushed again - moves at once
    assert repeater.update(RIGHT, 0.3)           # New direction - moves at once
    assert not repeater.update(RIGHT, 0.5)       # ... and waits the full delay again
    assert repeater.update(RIGHT, 0.7)


def test_matching_previews_a_filter_without_applying_it():
    roms = [make_row('pacman', 'Pac-Man'), make_row('galaga', 'Galaga')]
    model = TileGridModel(roms, columns=6, rows=4, categories=[], ignore_categories=True)
    model.apply_filter('Exists', search='pac')
    model.focused = 0
    assert [row[1] for row in model.matching('Exists', search='GAL')] == ['galaga']
    assert model.matching('Exists', search='xyz') == []
    assert (model.search, model.size) == ('pac', 1)     # Unchanged


def played_model(tmp_path):
    import datetime
    import play_stats
    roms = [make_row(name, name.title()) for name in ('alpha', 'bravo', 'charlie', 'delta')]
    roms[1][5], roms[3][5], roms[0][5] = '7', '2', '0'           # Number of runs
    roms[1][6], roms[2][6], roms[3][6] = '1', '2', '1'           # bravo, delta favorites; charlie on the watchlist
    stats = play_stats.PlayStats(str(tmp_path / 'play_stats.json'))
    stats.record('charlie', 600, datetime.datetime(2026, 1, 1))
    stats.record('alpha', 60, datetime.datetime(2026, 3, 1))
    model = TileGridModel(roms, columns=6, rows=4, categories=[], ignore_categories=True)
    model.play_stats = stats
    model.apply_filter('Exists')
    return model


def test_views_cycle_and_wrap_round(tmp_path):
    model = played_model(tmp_path)
    names = lambda: [row[1] for row in model.filtered]
    assert model.view == 'Exists' and names() == ['alpha', 'bravo', 'charlie', 'delta']
    model.cycle_view()
    assert model.view == 'Favorites' and names() == ['bravo', 'delta']
    model.cycle_view()
    assert model.view == 'Watchlist' and names() == ['charlie']
    model.cycle_view()
    assert model.view == 'Recent' and names() == ['alpha', 'charlie']        # Newest first, unplayed left out
    model.cycle_view()
    assert model.view == 'MostPlayed' and names() == ['charlie', 'alpha']    # Most play time first
    assert model.next_view == 'Exists'
    model.cycle_view()
    assert model.view == 'Exists' and names() == ['alpha', 'bravo', 'charlie', 'delta']


def test_sort_orders_cycle_and_do_not_apply_to_the_played_views(tmp_path):
    model = played_model(tmp_path)
    names = lambda: [row[1] for row in model.filtered]
    model.cycle_sort()
    assert model.sort == 'most_runs' and names() == ['bravo', 'delta']       # Most runs first, unplayed left out
    model.apply_filter('Recent')
    assert not model.sort_applies and names() == ['alpha', 'charlie']        # The view's order, not most runs
    model.cycle_sort()
    assert model.sort == 'name'
    model.apply_filter('Exists')
    assert model.sort_applies and names() == ['alpha', 'bravo', 'charlie', 'delta']


def test_cycling_the_view_keeps_the_search_and_category():
    model = category_model()
    model.apply_filter('Exists', search='a', category='Shooter')
    model.cycle_view()
    assert (model.view, model.search, model.category) == ('Favorites', 'a', 'Shooter')
    assert [row[1] for row in model.filtered] == ['galaga']


def test_tile_view_key_maps_main_window_views():
    from tile_grid_model import tile_view_key
    for view in ('Exists', 'Favorites', 'Watchlist', 'Recent', 'MostPlayed'):
        assert tile_view_key(view) == view
    for view in ('All', 'Missing', '', 'Rubbish'):     # Tile View only holds ROMs that exist
        assert tile_view_key(view) == 'Exists'


def test_sort_keeps_the_favorites_and_search_filter():
    roms = [make_row('pacman', 'Pac-Man', favorite='1'), make_row('mspacman', 'Ms. Pac-Man'),
            make_row('galaga', 'Galaga', favorite='1')]
    for row, runs in zip(roms, ('3', '9', '5')):
        row[5] = runs
    model = TileGridModel(roms, columns=6, rows=4, categories=[], ignore_categories=True)
    model.apply_filter('Favorites')
    model.sort = 'most_runs'
    model.apply_filter('Favorites')
    assert [row[1] for row in model.filtered] == ['galaga', 'pacman']
    model.apply_filter('Exists', search='pac')
    assert [row[1] for row in model.filtered] == ['mspacman', 'pacman']


def test_played_views_without_play_stats_show_nothing():
    model = make_model(5)
    model.apply_filter('Recent')
    assert model.size == 0 and model.focused_row is None


def category_model():
    roms = [make_row('pacman', 'Pac-Man', category='Maze', favorite='1'),
            make_row('digdug', 'Dig Dug', category='Maze'),
            make_row('galaga', 'Galaga', category='Shooter', favorite='1'),
            make_row('xevious', 'Xevious', category='Shooter'),
            make_row('1942', '1942', category='Shooter'),
            make_row('pong', 'Pong', category='Ball & Paddle')]
    model = TileGridModel(roms, columns=6, rows=4, categories=[], ignore_categories=True)
    model.apply_filter('Exists')
    return model


def test_category_counts_largest_first_for_the_current_view():
    model = category_model()
    assert model.category_counts() == [('Shooter', 3), ('Maze', 2), ('Ball & Paddle', 1)]
    model.apply_filter('Favorites')
    assert model.category_counts() == [('Maze', 1), ('Shooter', 1)]      # Ties in name order, empty ones left out


def test_category_filter_combines_with_favorites_and_search_and_is_kept():
    model = category_model()
    model.apply_filter('Exists', category='Shooter')
    assert [row[1] for row in model.filtered] == ['galaga', 'xevious', '1942']
    model.apply_filter('Favorites')                     # Category kept when the view changes
    assert [row[1] for row in model.filtered] == ['galaga']
    model.apply_filter('Exists', search='x')
    assert [row[1] for row in model.filtered] == ['xevious']
    assert model.category_counts() == [('Shooter', 1)]    # Counts ignore the chosen category
    model.apply_filter('Exists', category='')
    assert model.size == 6


def test_find_key_locates_a_saved_rom():
    roms = [make_row('pacman', 'Pac-Man'), make_row('nes', 'Nintendo', program='smb.zip')]
    model = TileGridModel(roms, columns=6, rows=4, categories=[], ignore_categories=True)
    model.apply_filter('Exists')
    assert model.find_key('nes-->Nintendo-->smb.zip') == 1
    assert model.find_key('pacman') == 0
    assert model.find_key('missing') is None and model.find_key('') is None


def test_find_video_for_arcade_roms_and_software_list_programs(tmp_path):
    from tile_grid_model import find_video
    video = tmp_path / 'video [hd]'                          # [ ] in the folder name must not upset the lookup
    (video / 'nes').mkdir(parents=True)
    for name in ('pacman.mp4', 'nes.mp4', 'spectrum.m4v', 'nes/smb.mp4', 'nes/Tetris (USA).mp4'):
        (video / name).write_text('x')
    folder = str(video)

    def row(rom_file_name, program='', short_name=''):
        r = make_row(rom_file_name, program=program)
        r[8] = short_name
        return r

    assert find_video(folder, row('pacman')) == str(video / 'pacman.mp4')
    assert find_video(folder, row('galaga')) is None
    assert find_video(folder, row('nes', 'Super Mario Bros.zip', 'smb')) == str(video / 'nes' / 'smb.mp4')       # Short name
    assert find_video(folder, row('nes', 'Tetris (USA).zip')) == str(video / 'nes' / 'Tetris (USA).mp4')         # File name
    assert find_video(folder, row('nes', 'Zelda.zip', 'zelda')) == str(video / 'nes.mp4')                         # System video
    assert find_video(folder, row('spectrum', 'Jetpac.tzx')) == str(video / 'spectrum.m4v')                       # No sub-folder
    assert find_video(folder, row('amiga', 'Barbarian.adf')) is None
