"""Preview video sound when PortAudio (needed by sounddevice) is missing: the video plays silently, logged once."""
import logging


def test_no_portaudio_means_silent_previews_logged_once(wx_app, tmp_path, monkeypatch, caplog):
    import video_class
    monkeypatch.setattr(video_class, 'sd', None)
    monkeypatch.setattr(video_class, 'SOUND_UNAVAILABLE', 'PortAudio library not found')
    video = tmp_path / 'pacman.mp4'
    video.write_bytes(b'not really a video')
    player = video_class.AudioPlayer(logging.getLogger('pfemame-test'))

    with caplog.at_level(logging.WARNING):
        assert player.prepare(str(video)) is None           # no sound session - the video plays without sound
        assert player.prepare(str(video)) is None
    warnings = [r.getMessage() for r in caplog.records if 'No sound for preview videos' in r.getMessage()]
    assert len(warnings) == 1                                # said once, not for every video
    assert 'PortAudio library not found' in warnings[0] and 'libportaudio2' in warnings[0]
