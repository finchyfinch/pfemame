"""
The full screen video player (screensaver): the video list, play order, headings, the play loop and window clean-up.

The window itself isn't built - its methods are run on stand-in objects so no full screen window or video is needed.
"""
import logging
import threading
import types

import pytest

import fullscreenplay
from fullscreenplay import FullScreenVideoPlayer
from rom_grid import index_rom_name, index_rom_file_name, index_system_program_file_name


def rom_row(description, file_name, program=''):
    row = [''] * 12
    row[index_rom_name] = description
    row[index_rom_file_name] = file_name
    row[index_system_program_file_name] = program
    return row


# ----------------------------------------------------------------------------------------------------------------------
def test_list_video_files_keeps_only_videos_in_the_folder_itself(tmp_path):
    for name in ('pacman.mp4', 'galaga.MKV', 'readme.txt', 'dkong.avi'):
        (tmp_path / name).write_bytes(b'')
    (tmp_path / 'sub').mkdir()
    (tmp_path / 'sub' / 'inner.mp4').write_bytes(b'')
    (tmp_path / 'folder.mp4').mkdir()                        # a folder with a video-like name is not a video

    assert fullscreenplay.list_video_files(str(tmp_path)) == ['dkong.avi', 'galaga.MKV', 'pacman.mp4']


def test_list_video_files_empty_and_missing_folders(tmp_path):
    assert fullscreenplay.list_video_files(str(tmp_path)) == []
    with pytest.raises(OSError):
        fullscreenplay.list_video_files(str(tmp_path / 'missing'))


# ----------------------------------------------------------------------------------------------------------------------
def test_shuffled_keeps_every_video_and_never_repeats_the_last_one_first():
    videos = ['a.mp4', 'b.mp4', 'c.mp4']
    for _ in range(200):
        order = fullscreenplay.shuffled(videos, last='a.mp4')
        assert sorted(order) == videos
        assert order[0] != 'a.mp4'
    assert videos == ['a.mp4', 'b.mp4', 'c.mp4']             # the list passed in is left alone
    assert fullscreenplay.shuffled(['only.mp4'], last='only.mp4') == ['only.mp4']


# ----------------------------------------------------------------------------------------------------------------------
def test_description_lookup_uses_rom_rows_but_not_system_programs():
    rom_list = [rom_row('Pac-Man (Midway)', 'pacman'),
                rom_row('Manic Miner', 'spectrum', program='manic.tap'),
                rom_row('ZX Spectrum 48K', 'Spectrum2'),
                ['broken row'],
                None]
    lookup = fullscreenplay.build_description_lookup(rom_list)
    assert lookup == {'pacman': 'Pac-Man (Midway)', 'spectrum2': 'ZX Spectrum 48K'}
    assert fullscreenplay.build_description_lookup(None) == {}


# ----------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize('output, title', [
    (b'{"format": {"tags": {"title": "AC/DC Live"}}}', 'AC/DC Live'),
    (b'{"format": {"tags": {"TITLE": " Street Fighter II \\\\ Champion Edition "}}}',
     'Street Fighter II \\ Champion Edition'),
    (b'{"format": {"tags": {"title": "None"}}}', None),
    (b'{"format": {"tags": {"encoder": "Lavf"}}}', None),
    (b'{"format": {}}', None),
    (b'', None),
    (b'not json', None),
])
def test_title_from_probe_output(output, title):
    assert fullscreenplay.title_from_probe_output(output) == title


def test_heading_prefers_the_title_tag_then_the_rom_description_then_the_file_name():
    player = types.SimpleNamespace(rom_descriptions={'pacman': 'Pac-Man (Midway)'}, get_video_title=lambda _p: None)
    assert FullScreenVideoPlayer.get_video_heading(player, '/videos/PacMan.mp4') == 'Pac-Man (Midway)'
    assert FullScreenVideoPlayer.get_video_heading(player, '/videos/galaga.mp4') == 'galaga'

    player.get_video_title = lambda _p: 'AC/DC'                # a title is shown whole, slashes and all
    assert FullScreenVideoPlayer.get_video_heading(player, '/videos/pacman.mp4') == 'AC/DC'


def test_no_ffprobe_means_no_title():
    player = types.SimpleNamespace(probe_cmd=None)
    assert FullScreenVideoPlayer.get_video_title(player, 'pacman.mp4') is None


# ----------------------------------------------------------------------------------------------------------------------
class FakeVideo:
    """Stands in for video_class.Video: 'plays' are recorded, and each video either starts or fails to load."""

    def __init__(self, playable):
        self.playable = playable
        self.played = []
        self.playback_started = False
        self.video_path = None

    def play(self, path):
        self.played.append(path)
        self.playback_started = self.playable(path)

    @staticmethod
    def is_playing():
        return False                                         # every video 'ends' straight away

    def stop(self, _caption=True):
        pass


class LoopPlayer:
    """Just enough of FullScreenVideoPlayer to run play_loop() synchronously."""
    play_loop = FullScreenVideoPlayer.play_loop

    def __init__(self, videos, playable, stop_after=None):
        self.folders_video = 'videos'
        self.video_list = list(videos)
        self.video_index = 0
        self.close_selected = False
        self.skip_video = False
        self.my_logger = logging.getLogger('pfemame-test')
        self._play_requested = threading.Event()
        self.video_player = FakeVideo(playable)
        self.stop_after = stop_after
        self.closed = False

    def get_video_heading(self, path):
        return path

    def call_ui(self, function, *args):
        function(*args)

    def start_video(self, path, _heading):
        self.video_player.play(path)
        if self.stop_after and len(self.video_player.played) >= self.stop_after:
            self.close_selected = True
        self._play_requested.set()

    def on_close(self, _event):
        self.closed = True
        self.close_selected = True


@pytest.fixture
def no_sleep(monkeypatch):
    monkeypatch.setattr(fullscreenplay.time, 'sleep', lambda _seconds: None)


def test_play_loop_closes_when_no_video_can_be_played(no_sleep, caplog):
    player = LoopPlayer(['a.mp4', 'b.mp4', 'c.mp4'], playable=lambda _path: False)
    with caplog.at_level(logging.WARNING):
        player.play_loop()
    assert player.closed
    assert len(player.video_player.played) == 3              # one try each, then it gives up
    assert any('could be played' in r.getMessage() for r in caplog.records)


def test_play_loop_keeps_going_while_some_videos_play_and_reshuffles_each_pass(no_sleep):
    player = LoopPlayer(['a.mp4', 'b.mp4', 'c.mp4'], playable=lambda path: not path.endswith('c.mp4'), stop_after=30)
    player.play_loop()
    assert not player.closed
    played = [path[-5:] for path in player.video_player.played]
    assert len(played) == 30
    for start in range(0, 30, 3):                            # every pass plays each video once
        assert sorted(played[start:start + 3]) == ['a.mp4', 'b.mp4', 'c.mp4']
    for start in range(3, 30, 3):                            # and doesn't repeat the last video of the pass before
        assert played[start] != played[start - 1]


# ----------------------------------------------------------------------------------------------------------------------
class FakeTimer:
    def __init__(self):
        self.running = True

    def IsRunning(self):
        return self.running

    def Stop(self):
        self.running = False


class FakeEvent:
    def __init__(self, window):
        self.window = window
        self.skipped = False

    def GetEventObject(self):
        return self.window

    def Skip(self):
        self.skipped = True


def destroy_stub(closed):
    player = types.SimpleNamespace(close_selected=closed, _title_timer=FakeTimer(), joystick_pov_timer=FakeTimer(),
                                   video_player=types.SimpleNamespace(cleaned=False), handed_back=None)
    player.video_player.cleanup = lambda: setattr(player.video_player, 'cleaned', True)
    player.restore_input_handlers = lambda give_back=True: setattr(player, 'handed_back', give_back)
    return player


def test_destroy_of_a_child_window_is_ignored():
    player = destroy_stub(closed=False)
    event = FakeEvent(window=object())                       # e.g. the OpenGL panel being replaced
    FullScreenVideoPlayer.on_destroy(player, event)
    assert player.joystick_pov_timer.running                 # the D-pad still closes the player
    assert not player.close_selected
    assert event.skipped


def test_destroy_without_close_stops_everything():
    player = destroy_stub(closed=False)
    title_timer = player._title_timer
    FullScreenVideoPlayer.on_destroy(player, FakeEvent(window=player))
    assert player.close_selected                              # the play loop stops
    assert not player.joystick_pov_timer.running and not title_timer.running
    assert player.handed_back is False                       # capture released, not given to a parent that may be gone
    assert player.video_player.cleaned


def test_ui_calls_are_dropped_once_the_player_is_closing():
    calls = []

    class Window(types.SimpleNamespace):
        alive = True

        def __bool__(self):                                  # a destroyed wx window is False
            return self.alive

    player = Window(close_selected=False)
    FullScreenVideoPlayer._call_if_open(player, calls.append, ('first',))
    player.close_selected = True
    FullScreenVideoPlayer._call_if_open(player, calls.append, ('closing',))
    player.close_selected, player.alive = False, False
    FullScreenVideoPlayer._call_if_open(player, calls.append, ('destroyed',))
    assert calls == ['first']


# ----------------------------------------------------------------------------------------------------------------------
def test_title_overlay_image_fits_the_width_and_lets_the_video_show_through(wx_app):
    import numpy as np
    import video_class

    assert video_class.make_overlay_image(None, None, 1000) is None
    assert video_class.make_overlay_image('Pac-Man', None, 20) is None             # no room to draw anything

    short = video_class.make_overlay_image('Pac-Man', None, 1000)
    long = video_class.make_overlay_image('Pac-Man ' * 100, None, 600)
    assert short.HasAlpha() and short.GetWidth() < 600
    assert long.GetWidth() <= 600                                                   # shortened with '...' to fit

    alpha = np.frombuffer(bytes(short.GetAlpha()), dtype=np.uint8)
    assert alpha.min() == video_class.OVERLAY_ALPHA                                 # see-through band
    assert alpha.max() == 255                                                       # solid text
