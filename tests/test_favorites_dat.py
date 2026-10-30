"""favorites.dat / watchlist.dat helpers shared by the main window and Tile View."""
import functions
from tile_grid_model import favorite_key


def make_row(rom_file_name, rom_name, program=''):
    return [rom_name, rom_file_name, program, '1', '0', '0', '0', '', '', '', '', '']


def test_favorite_key_matches_the_main_window_format():
    assert favorite_key(make_row('pacman', 'Pac-Man')) == 'pacman'
    assert favorite_key(make_row('3dobios', '3DO BIOS', 'Captain Quazar (US).cue')) == \
        '3dobios-->3DO BIOS-->Captain Quazar (US).cue'


def test_add_keeps_the_file_sorted_without_duplicates(tmp_path):
    path = str(tmp_path / 'favorites.dat')
    functions.add_dat_entry(path, 'pacman')          # File doesn't exist yet
    functions.add_dat_entry(path, 'galaga')
    functions.add_dat_entry(path, 'pacman')
    assert open(path).read() == 'galaga\npacman\n'
    assert functions.dat_file_contains(path, 'galaga')
    assert not functions.dat_file_contains(path, 'gal')


def test_remove_leaves_the_other_entries(tmp_path):
    path = tmp_path / 'favorites.dat'
    path.write_text('galaga\nnes-->Super Mario Bros.-->smb.zip\npacman\n')
    functions.remove_dat_entry(str(path), 'nes-->Super Mario Bros.-->smb.zip')
    assert path.read_text() == 'galaga\npacman\n'


def test_missing_file(tmp_path):
    path = str(tmp_path / 'missing.dat')
    assert not functions.dat_file_contains(path, 'pacman')
    try:
        functions.remove_dat_entry(path, 'pacman')
        assert False, 'expected FileNotFoundError'
    except FileNotFoundError:
        pass
