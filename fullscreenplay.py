#!/usr/bin/env python3

# ----------------------------------------------------------------------------------------------------------------------
# fullscreenplay.py

"""
Full screen random video player (the screensaver) using the shared Video class.
"""
import wx
import json
import random
import subprocess
import sys
import time
import logging.handlers
from threading import Thread, Event
from os.path import join
from pathlib import Path

import iniFile

from functions import path_to_me, set_up_language, get_font_info, setup_logging, find_tool
from rom_grid import index_rom_name, index_rom_file_name, index_system_program_file_name
from video_class import Video, hidden_window_options

_ = set_up_language()

VIDEO_FILE_TYPES = frozenset({'.mpeg', '.avi', '.asf', '.wmv', '.mp4', '.mov', '.3gp', '.ogg', '.ogm',
                              '.mkv', '.m4v'})

TITLE_SHOW_MS = 5000        # How long the title shows at the start of each video when it is set to hide
PROBE_TIMEOUT = 10          # Seconds to wait for ffprobe to read a video's title


# ----------------------------------------------------------------------------------------------------------------------
# The names of the playable video files in a folder (not its sub folders).  Raises OSError if the folder can't be read.
def list_video_files(folder: str) -> list:
    return sorted(f.name for f in Path(folder).iterdir()
                  if f.is_file() and f.suffix.lower() in VIDEO_FILE_TYPES)


# ----------------------------------------------------------------------------------------------------------------------
# A new random play order.  'last' is the video that has just played, so it doesn't play again straight away.
def shuffled(videos: list, last: str | None = None) -> list:
    order = list(videos)
    random.shuffle(order)
    if last is not None and len(order) > 1 and order[0] == last:
        swap = random.randrange(1, len(order))
        order[0], order[swap] = order[swap], order[0]
    return order


# ----------------------------------------------------------------------------------------------------------------------
# {ROM file name (lower case): ROM description} for the ROMs list rows.  ROM videos are named after the ROM file name
# (e.g. pacman.mp4).  System program rows are left out - their videos are in sub folders, which aren't played here.
def build_description_lookup(rom_list) -> dict:
    lookup = {}
    for row in rom_list or ():
        try:
            if row[index_system_program_file_name]:
                continue
            name, description = row[index_rom_file_name], row[index_rom_name]
        except (IndexError, TypeError, KeyError):
            continue
        if name and description:
            lookup.setdefault(str(name).lower(), str(description))
    return lookup


# ----------------------------------------------------------------------------------------------------------------------
# The 'title' tag from ffprobe's JSON output, or None.  The tag name's case varies between containers (MKV: TITLE).
def title_from_probe_output(output) -> str | None:
    try:
        tags = json.loads(output or '{}').get('format', {}).get('tags', {})
    except (ValueError, AttributeError):
        return None
    for key, value in tags.items():
        if key.lower() == 'title' and isinstance(value, str):
            value = value.strip()
            if value and value.lower() != 'none':
                return value
    return None


class FullScreenVideoPlayer(wx.Frame):
    def __init__(self, folders_video, caller, caller_parent,
                 my_logger: logging.Logger, rom_list=None):

        wx.Frame.__init__(self, caller_parent, -1, 'Full Screen video player',
                          size=wx.DisplaySize(), style=wx.NO_BORDER)

        self.folders_video = folders_video
        self.caller = caller
        self.caller_parent = caller_parent
        self.my_logger = my_logger
        self.close_selected = False
        self.skip_video = False
        self.message_sent = False
        self._title_timer = None
        self._play_requested = Event()  # Set on the UI thread once the next video has been asked to play

        # Input capture state (mouse / joystick) - see setup_input_handlers()
        self.joystick = None
        self.joystick_pov_timer = None
        self._input_handlers_active = False
        self._mouse_origin = None

        self.my_logger.info(_('Running Fullscreen video player'))
        self.probe_cmd = find_tool('ffprobe')   # pfeMAME folder first, then the PATH
        if not self.probe_cmd:
            self.my_logger.info(_('ffmpeg not available'))

        self.hide_title = iniFile.read_ini_file('preferences', 'screensaverhidetitle') == 'True'
        self.rom_descriptions = build_description_lookup(rom_list)

        self.Bind(wx.EVT_CLOSE, self.on_close)
        self.Bind(wx.EVT_CHAR_HOOK, self.on_keypress)
        self.Bind(wx.EVT_WINDOW_DESTROY, self.on_destroy)

        self.panel = wx.Panel(self)
        self.panel.SetBackgroundColour(wx.BLACK)

        # Load the video file names and shuffle them
        try:
            self.video_list = shuffled(list_video_files(self.folders_video))
        except OSError as e:
            self.video_list = []
            self.my_logger.warning(_('No video files found that can be played or folder error: {}').format(e))
        else:
            if not self.video_list:
                self.my_logger.warning(_('No video files found that can be played or folder error: {}')
                                       .format(self.folders_video))
        if not self.video_list:
            self.on_close(None)
            return
        self.video_index = 0
        self.title_font = get_font_info().global_font_bold_20

        # The title is drawn over the top of the video, so showing or hiding it never changes the video's size
        self.video_player = Video(
                                  parent_panel=self.panel,
                                  logger=self.my_logger,
                                  image_panel=None,
                                  horizontal_size=-1,
                                  vertical_size=-1,
                                  video_caption_label=None,
                                  use_video_caption=False,
                                 )

        self.sizer = wx.BoxSizer(wx.VERTICAL)
        self.sizer.Add(self.video_player.video_panel, 1, wx.EXPAND)

        self.panel.SetSizerAndFit(self.sizer)
        self.panel.SetFocus()

        self.Show()
        self.ShowFullScreen(True, wx.FULLSCREEN_NOCAPTION)

        self.hide_pointer()
        self.setup_input_handlers()

        Thread(target=self.play_loop, daemon=True).start()

    # ------------------------------------------------------------------------------------------------------------------
    # The play loop runs on a worker thread.  Everything it does to the window goes through here, so nothing reaches
    # the window once it is closing or has been destroyed.
    def call_ui(self, function, *args) -> None:
        wx.CallAfter(self._call_if_open, function, args)

    def _call_if_open(self, function, args) -> None:
        if not self or self.close_selected:  # A destroyed wx window is False
            return
        function(*args)

    # ------------------------------------------------------------------------------------------------------------------
    def play_loop(self) -> None:
        failures = 0  # Videos in a row that didn't start
        while not self.close_selected:
            self.skip_video = False
            file_to_play = join(self.folders_video, self.video_list[self.video_index])
            heading = self.get_video_heading(file_to_play)

            self._play_requested.clear()
            self.call_ui(self.start_video, file_to_play, heading)
            while not self.close_selected and not self._play_requested.wait(0.1):
                pass

            time.sleep(0.5)  # Give the player time to start before watching for the end of the video

            while not self.close_selected and not self.skip_video and self.video_player.is_playing():
                time.sleep(0.1)

            if self.close_selected:
                break

            failures = 0 if self.skip_video or self.video_player.playback_started else failures + 1
            if failures >= len(self.video_list):
                self.my_logger.warning(_('None of the videos in {} could be played - closing the full screen video '
                                         'player').format(self.folders_video))
                self.call_ui(self.on_close, None)
                break

            # Stop the video playback so that if we are trying to play the next video, we don't get any
            # audio decode issues (mostly a problem with macOS)
            self.call_ui(self.video_player.stop, False)
            time.sleep(0.5)

            self.video_index += 1
            if self.video_index >= len(self.video_list):  # Played them all - new order for the next pass
                self.video_list = shuffled(self.video_list, last=self.video_list[-1])
                self.video_index = 0

    # ------------------------------------------------------------------------------------------------------------------
    # UI thread: show the title and play the video
    def start_video(self, file_to_play: str, heading: str) -> None:
        try:
            self.video_player.set_overlay_text(heading, self.title_font)
            if self._title_timer:
                self._title_timer.Stop()
                self._title_timer = None
            if self.hide_title:
                self._title_timer = wx.CallLater(TITLE_SHOW_MS, self.hide_title_ctrl)

            if self.caller == 'mainview':
                self.caller_parent.messages_append(_('Playing video {}\n').format(file_to_play), False)

            self.video_player.video_path = file_to_play
            self.video_player.play()
            self.hide_pointer()  # Again, in case the video panel was replaced by the software one
        finally:
            self._play_requested.set()

    def hide_title_ctrl(self) -> None:
        self._title_timer = None
        if self and not self.close_selected:
            self.video_player.set_overlay_text(None)

    # ------------------------------------------------------------------------------------------------------------------
    # The heading for a video: its own title tag, otherwise the ROM description, otherwise the file name
    def get_video_heading(self, file_path: str) -> str:
        title = self.get_video_title(file_path)
        if title:
            return title
        stem = Path(file_path).stem
        return self.rom_descriptions.get(stem.lower(), stem)

    # The video's title tag (read with ffprobe), or None
    def get_video_title(self, file_path: str) -> str | None:
        if not self.probe_cmd:
            return None
        try:
            result = subprocess.run([self.probe_cmd, '-v', 'error', '-print_format', 'json',
                                     '-show_entries', 'format_tags', file_path],
                                    capture_output=True, timeout=PROBE_TIMEOUT, **hidden_window_options())
            return title_from_probe_output(result.stdout)
        except Exception as e:
            if not self.message_sent:
                self.my_logger.info(_('Metadata error: {}').format(e))
                self.message_sent = True
        return None

    # ------------------------------------------------------------------------------------------------------------------
    # Hide the mouse pointer over the player
    def hide_pointer(self) -> None:
        cursor = wx.Cursor(wx.CURSOR_BLANK)
        for window in (self, self.panel, self.video_player.video_panel):
            if window:
                window.SetCursor(cursor)

    # ------------------------------------------------------------------------------------------------------------------
    # Skip to next video or close the window
    def on_keypress(self, event):
        if event.GetKeyCode() != wx.WXK_SPACE:
            self.on_close(-1)
        else:
            self.skip_video = True

    # ------------------------------------------------------------------------------------------------------------------
    # Capture mouse and joystick input.  Joystick button 1 behaves like the spacebar (skip to the next video);
    # any other joystick activity (other buttons, stick movement, POV / DPAD) or any mouse activity closes the player.
    def setup_input_handlers(self) -> None:
        # Mouse - any real movement or button / wheel action closes the player
        self.panel.Bind(wx.EVT_MOUSE_EVENTS, self.on_mouse)
        # Bound through the player so the binding survives a switch to software video rendering
        self.video_player.bind_panel_event(wx.EVT_MOUSE_EVENTS, self.on_mouse)

        # Joystick - reuse the main window's joystick so we can map button 1 to 'skip'
        self.joystick = getattr(self.caller_parent, 'joystick', None)
        if self.joystick is None:
            return

        # Directional extents (reuse the values the main window calculated for navigation)
        self.joystickXMin = getattr(self.caller_parent, 'joystickXMin', -1)
        self.joystickXMax = getattr(self.caller_parent, 'joystickXMax', -1)
        self.joystickYMin = getattr(self.caller_parent, 'joystickYMin', -1)
        self.joystickYMax = getattr(self.caller_parent, 'joystickYMax', -1)

        # Stop the main window from acting on joystick input while we own the screen, and
        # remember its previous setting so we can restore it on close.
        self._prev_joystick_block = getattr(self.caller_parent, 'joystick_block', False)
        self.caller_parent.joystick_block = True

        # Redirect joystick events to this window
        self._joystick_polling_freq = iniFile.read_ini_int('preferences', 'joystick_polling_freq', low=1, high=1000)
        self.joystick.SetCapture(self, pollingFreq=self._joystick_polling_freq)
        self.Bind(wx.EVT_JOYSTICK_EVENTS, self.on_joystick)

        # The POV hat / DPAD does not raise events, so poll it like the main window does
        if self.joystick.HasPOV():
            self.joystick_pov_timer = wx.Timer(self)
            self.Bind(wx.EVT_TIMER, self.on_joystick_pov, self.joystick_pov_timer)
            self.joystick_pov_timer.Start(200)

        self._input_handlers_active = True

    # ------------------------------------------------------------------------------------------------------------------
    def on_joystick(self, event) -> None:
        # Ignore button releases so letting go of button 1 doesn't close the player
        if event.ButtonUp():
            return

        if event.ButtonDown():
            if event.GetButtonState() == 1:  # Button 1 only - same effect as the spacebar
                self.skip_video = True
            else:                            # Any other button closes the player
                self.on_close(-1)
            return

        # Not a button event - a real directional push counts as 'any other event'
        if self._joystick_moved(event.GetPosition()):
            self.on_close(-1)

    # ------------------------------------------------------------------------------------------------------------------
    def _joystick_moved(self, position) -> bool:
        # True if the stick is pushed beyond the centre dead zone (mirrors the navigation logic)
        x_pos, y_pos = position
        x_center = ((self.joystickXMax - self.joystickXMin) // 2) // 2
        y_center = ((self.joystickYMax - self.joystickYMin) // 2) // 2
        if x_pos < (self.joystickXMin + x_center) or x_pos > (self.joystickXMax - x_center):
            return True
        if y_pos < (self.joystickYMin + y_center) or y_pos > (self.joystickYMax - y_center):
            return True
        return False

    # ------------------------------------------------------------------------------------------------------------------
    def on_joystick_pov(self, _event) -> None:
        # A POV hat / DPAD direction is 'any other event' and closes the player (65535 == centred)
        if self.joystick and self.joystick.GetPOVPosition() != 65535:
            self.on_close(-1)

    # ------------------------------------------------------------------------------------------------------------------
    def on_mouse(self, event) -> None:
        # Ignore enter / leave so simply showing the window under the pointer doesn't close it
        if event.Entering() or event.Leaving():
            event.Skip()
            return

        pos = wx.GetMousePosition()
        if event.Moving() or event.Dragging():
            # Tolerate tiny jitter so the player doesn't close on a stray pixel of movement at startup
            if self._mouse_origin is None:
                self._mouse_origin = pos
                return
            if abs(pos.x - self._mouse_origin.x) < 5 and abs(pos.y - self._mouse_origin.y) < 5:
                return

        self.on_close(-1)

    # ------------------------------------------------------------------------------------------------------------------
    def restore_input_handlers(self, give_back: bool = True) -> None:
        """
        Hand joystick capture and the navigation block back to the main window.

        :param give_back: False when the main window may be going too (we were destroyed without being closed) - the
                          capture is then just released.
        """
        if not self._input_handlers_active:
            return
        self._input_handlers_active = False

        if self.joystick_pov_timer:
            self.joystick_pov_timer.Stop()

        if self.joystick:
            if give_back and self.caller_parent:
                self.joystick.SetCapture(self.caller_parent, pollingFreq=self._joystick_polling_freq)
            else:
                self.joystick.ReleaseCapture()

        if give_back and self.caller_parent is not None:
            self.caller_parent.joystick_block = self._prev_joystick_block

    # ------------------------------------------------------------------------------------------------------------------
    def on_destroy(self, event):
        # Destroy events of child windows (e.g. the OpenGL video panel when it is replaced by the software one) bubble
        # up to here - only act on our own.
        if event.GetEventObject() is self:
            closed = self.close_selected
            self.close_selected = True  # Stops the play loop if we were destroyed without on_close()
            if self._title_timer:
                self._title_timer.Stop()
                self._title_timer = None
            # A timer left running past its owner's destruction delivers its queued WM_TIMER to a
            # freed window, which corrupts the heap.  restore_input_handlers() normally stops this
            # one; this covers the paths where it never ran.
            timer = self.joystick_pov_timer
            if timer is not None and timer.IsRunning():
                timer.Stop()
            if not closed:
                self.restore_input_handlers(give_back=False)
                if getattr(self, 'video_player', None):
                    self.video_player.cleanup()
        event.Skip()

    # ------------------------------------------------------------------------------------------------------------------
    def on_close(self, _event):
        if self.close_selected:  # Guard against re-entry - on_close can fire from several inputs at once
            return
        self.close_selected = True
        if self._title_timer:
            self._title_timer.Stop()
            self._title_timer = None
        self.restore_input_handlers()
        if getattr(self, 'video_player', None):  # may not exist yet if we close during construction
            self.video_player.cleanup()  # replaces stop() — exits watchdog, joins threads, cleans GL

        parent = self.GetParent()
        if parent:
            list_ctrl = getattr(parent, "list", None)
            if list_ctrl and isinstance(list_ctrl, wx.Window):
                list_ctrl.SetFocus()
            parent.inactivity_timer_start()
        self.Destroy()


if __name__ == '__main__':
    # Try the player on its own:  python fullscreenplay.py <videos folder>
    if len(sys.argv) != 2:
        sys.exit('Usage: python fullscreenplay.py <videos folder>')
    app = wx.App()
    logger = setup_logging(path_to_me())
    FullScreenVideoPlayer(sys.argv[1], 'None', None, my_logger=logger)
    app.MainLoop()
