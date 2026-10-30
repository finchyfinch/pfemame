"""About box helpers: the roaming Pac-Man, the chasing ghost, text wrapping and licence file choice."""
import math
import random

from aboutbox import Roamer, Chaser, wrap_text, corner_alpha, license_file_name, unwrap_paragraphs


def test_pacman_stays_inside_the_window():
    pacman = Roamer(700, 460, 44, 2.2, rng=random.Random(1))
    ghost = Chaser(10, 10, 1.7)
    for _ in range(20000):
        pacman.step(threat=(ghost.x, ghost.y))
        ghost.step((pacman.x, pacman.y))
        assert 44 <= pacman.x <= 700 - 44
        assert 44 <= pacman.y <= 460 - 44


def test_pacman_wanders_all_over_the_window():
    pacman = Roamer(700, 460, 44, 2.2, rng=random.Random(2))
    visited = set()
    for _ in range(20000):
        pacman.step()
        visited.add((int(pacman.x // 175), int(pacman.y // 115)))
    assert len(visited) == 16       # every cell of a 4 x 4 grid


def test_pacman_turns_away_from_a_close_ghost():
    pacman = Roamer(700, 460, 44, 2.2, rng=random.Random(3))
    pacman.x, pacman.y, pacman.angle = 350, 230, 0.0     # heading right...
    pacman.rng.random = lambda: 1.0                         # ...with no random turns
    for _ in range(40):
        pacman.step(threat=(400, 230))                      # ...straight at a ghost
    assert math.cos(pacman.angle) < 0


def test_ghost_follows_but_is_slower():
    ghost = Chaser(0, 0, 1.7)
    for _ in range(100):
        ghost.step((300, 300))
    assert 0 < ghost.x < 300 and 0 < ghost.y < 300
    assert math.hypot(ghost.x, ghost.y) <= 1.7 * 100 + 0.001


def test_wrap_text_by_words_and_by_characters():
    measure = len
    assert wrap_text('one two three four', 9, measure) == ['one two', 'three', 'four']
    assert wrap_text('abcdefghij', 4, measure) == ['abcd', 'efgh', 'ij']
    assert wrap_text('short', 50, measure) == ['short']


def test_corner_alpha():
    assert corner_alpha(0, 0, 100, 100, 16) == 0.0          # the corner is cut off
    assert corner_alpha(50, 50, 100, 100, 16) == 1.0        # the middle is kept
    assert corner_alpha(0, 50, 100, 100, 16) == 1.0         # so are the straight edges


def test_license_file_falls_back_to_english():
    assert license_file_name('german') == 'license_de.txt'
    assert license_file_name('klingon') == 'license_en.txt'


def test_unwrap_paragraphs_joins_hard_wrapped_lines():
    text = ('Permitted provided\r\nthat these are met:\r\n\r\n'
            '1.  Not sold.\r\n2.  Include the source\r\n    code too.\r\n\r\n'
            'NO WARRANTY \r\nOF ANY KIND.')
    assert unwrap_paragraphs(text) == ('Permitted provided that these are met:\n\n'
                                       '1. Not sold.\n2. Include the source code too.\n\n'
                                       'NO WARRANTY OF ANY KIND.')


def test_unwrap_paragraphs_adds_no_space_inside_cjk_text():
    assert unwrap_paragraphs('本软\n件') == '本软件'
