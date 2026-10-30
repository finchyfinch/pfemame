#!/usr/bin/env python3

# ----------------------------------------------------------------------------------------------------------------------
# video_class.py

"""
This is a class that handles all video playback functions.

Video is decoded with OpenCV and drawn into an OpenGL canvas, or into a plain wx panel when OpenGL can't be used.
Audio is decoded by ffmpeg straight into a pipe and played with sounddevice.  It is all done by hand because the wx
media control and the VLC wrapper still don't embed reliably in a wxPython window on Linux / Wayland.

Threads used for each video:
    load worker      - opens the video and starts ffmpeg decoding the soundtrack   (Video._load_and_start)
    playback thread  - paces, decodes and hands over the video frames              (Video._playback_loop)
    audio thread     - copies ffmpeg's sound output to the sound device            (AudioPlayer._playback_thread)
Anything that touches a wx window is done on the UI thread.
"""

# Import wxpython & python modules
import wx
import os
import sys
import math
import time
import threading
import subprocess
import cv2
import numpy as np

# sounddevice needs the PortAudio system library, which some Linux distros (e.g. Arch) don't install by default.
# Without it pfeMAME still runs and preview videos play without sound (AudioPlayer.prepare logs why, once).
try:
    import sounddevice as sd
    SOUND_UNAVAILABLE = ''
except OSError as _e:                   # "PortAudio library not found"
    sd = None
    SOUND_UNAVAILABLE = str(_e)

# Import my own modules
import functions
import iniFile

_ = functions.set_up_language()

# Try to import OpenGL.  OPENGL_AVAILABLE stays False unless everything the OpenGL panel needs (the GL bindings and
# wx.glcanvas) imports cleanly.  Any exception counts, not just ImportError - a broken libGL / EGL install makes
# PyOpenGL raise other errors.  The OpenGL panel class is only defined when this works, so the software panel is used.
OPENGL_AVAILABLE = False
OPENGL_PLATFORM = ''  # Which PyOpenGL platform was picked (e.g. GLX or EGL on Linux) - logged to help with Wayland

try:
    import OpenGL
    # PyOpenGL calls glGetError() after every GL call by default.  That is only useful while debugging, so it is
    # turned off unless PFEMAME_GL_DEBUG=1 is set.
    OpenGL.ERROR_CHECKING = os.environ.get('PFEMAME_GL_DEBUG', '') == '1'
    from OpenGL.GL import *
    from wx import glcanvas
    try:
        OPENGL_PLATFORM = type(OpenGL.platform.PLATFORM).__name__
    except Exception:
        OPENGL_PLATFORM = 'unknown'
    OPENGL_AVAILABLE = True
except Exception as e:
    print(f"OpenGL not available, using software video rendering: {e}")

# OPENGL_AVAILABLE = False  # Just for testing the software decode if you want to

# Set once OpenGL has failed at run time, so video players created later in this session go straight to software
_opengl_failed_this_session = False

# How long the playback thread waits for the OpenGL panel to get ready before falling back to software rendering
GL_READY_TIMEOUT = 5.0

# How many frames in a row have to go unshown before it is reported.  One or two still in flight when playback stops
# is normal; a run of them means the frames aren't reaching the screen at all (OpenGLVideoPanel._note_dropped).
DROPPED_FRAME_REPORT = 10


def software_video_wanted() -> bool:
    """True if the user asked for software video rendering (preference, or the FORCE_SOFTWARE_VIDEO variable)."""
    if os.environ.get('FORCE_SOFTWARE_VIDEO', '').lower() == 'true':
        return True
    try:
        return iniFile.read_ini_file('preferences', 'softwarevideo') == 'True'
    except Exception:
        return False


def hidden_window_options() -> dict:
    """subprocess options that stop command line tools opening a console window on Windows."""
    if sys.platform == 'win32':
        return {'creationflags': subprocess.CREATE_NO_WINDOW}
    return {}


# ----------------------------------------------------------------------------------------------------------------------
class AudioSession:
    """
    One playback of one soundtrack: the ffmpeg process decoding it, the thread copying it to the sound device and the
    events used to talk to that thread.  A new one is made for every playback, so a thread that is slow to stop can
    never pick up (or clear) the next playback's state.
    """

    def __init__(self, process, first_chunk, samplerate):
        self.process = process
        self.first_chunk = first_chunk
        self.samplerate = samplerate
        self.stop_requested = threading.Event()
        self.started_event = threading.Event()   # Set once the output stream has started (or failed to)
        self.finished_event = threading.Event()  # Set once the audio thread has finished
        self.thread = None

        # A/V sync: when the stream started (time.monotonic(), 0 if it never did) and the stream's output latency.
        # The video clock is anchored to these so the first frame lands when the first sample becomes audible.
        self.audio_start_time = 0.0
        self.output_latency = 0.0

    def close_process(self):
        """Kill ffmpeg (if still running) and reap it.  Killing it also unblocks a read waiting on its pipe."""
        try:
            if self.process.poll() is None:
                self.process.kill()
        except Exception:
            pass
        try:
            self.process.wait(timeout=2)
        except Exception:
            pass

    def close_pipe(self):
        """Close our end of ffmpeg's output pipe.  Only call this from the thread that reads it (or when no thread
        ever started), never while another thread may be blocked reading it."""
        try:
            self.process.stdout.close()
        except Exception:
            pass


class AudioPlayer:
    """
    Plays a video's soundtrack.  ffmpeg decodes it to raw float32 PCM on a pipe and a dedicated thread writes that to
    its own sd.OutputStream (no sd.play()/sd.wait() global state, which caused PortAudio races).  Nothing is written
    to disk, and playback can start as soon as ffmpeg has produced its first chunk.
    """

    CHANNELS = 2
    FRAMES_PER_CHUNK = 4096        # ~90ms per write - small enough that a stop is noticed quickly
    BYTES_PER_FRAME = CHANNELS * 4  # float32 samples
    FIRST_CHUNK_TIMEOUT = 10.0     # ffmpeg is killed if it produces no sound at all within this time

    def __init__(self, logger):
        self.logger = logger
        self._lock = threading.Lock()
        self._current = None  # The AudioSession currently playing
        self._samplerate = None
        self._ffmpeg_missing_logged = False
        self._sound_missing_logged = False

    def _output_samplerate(self) -> int:
        """The default output device's own rate, so ffmpeg does the resampling rather than the sound system (and
        devices that only accept their native rate, such as some raw ALSA devices, still work)."""
        if self._samplerate is None:
            try:
                rate = int(sd.query_devices(kind='output')['default_samplerate'])
            except Exception:
                rate = 0
            self._samplerate = rate if 8000 <= rate <= 192000 else 48000
        return self._samplerate

    def prepare(self, video_path):
        """
        Start ffmpeg decoding the video's soundtrack and wait for its first chunk.  Runs on the load worker, so the
        start-up cost is paid before playback begins.

        :return: An AudioSession ready for play(), or None if the video has no sound (or ffmpeg isn't available)
        """
        if not video_path or not os.path.exists(video_path):
            return None

        if sd is None:                  # No PortAudio - the video plays silently
            if not self._sound_missing_logged:
                self.logger.warning(f"No sound for preview videos: {SOUND_UNAVAILABLE}.  Install PortAudio to hear "
                                    f"them (Ubuntu / Debian: libportaudio2, Arch: portaudio, Fedora: portaudio)")
                self._sound_missing_logged = True
            return None

        # ffmpeg is looked for in the pfeMAME folder, then on the PATH.
        ffmpeg_path = functions.find_tool('ffmpeg')
        if not ffmpeg_path:
            if not self._ffmpeg_missing_logged:
                self.logger.warning("ffmpeg not found (pfeMAME folder or PATH) - video preview will have no sound")
                self._ffmpeg_missing_logged = True
            return None

        samplerate = self._output_samplerate()
        cmd = [
            ffmpeg_path, '-nostdin', '-loglevel', 'error',
            '-i', video_path,
            '-map', '0:a:0',  # The first audio stream - ffmpeg exits straight away if there isn't one
            '-vn', '-sn', '-dn',
            '-f', 'f32le', '-acodec', 'pcm_f32le',
            '-ac', str(self.CHANNELS), '-ar', str(samplerate),
            'pipe:1'
        ]
        try:
            process = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                       stderr=subprocess.DEVNULL, **hidden_window_options())
        except OSError as e:
            self.logger.warning("ffmpeg could not be started: %s", e)
            return None

        # Kill ffmpeg if it hangs before producing anything, so this read can't block the load worker for ever.
        timer = threading.Timer(self.FIRST_CHUNK_TIMEOUT, self._kill_quietly, args=(process,))
        timer.daemon = True
        timer.start()
        try:
            first_chunk = process.stdout.read(self.FRAMES_PER_CHUNK * self.BYTES_PER_FRAME)
        except Exception:
            first_chunk = b''
        finally:
            timer.cancel()

        session = AudioSession(process, first_chunk, samplerate)
        if not first_chunk:
            # No audio stream, a decode error, or the timeout above
            session.close_process()
            session.close_pipe()
            return None
        return session

    @staticmethod
    def _kill_quietly(process):
        try:
            process.kill()
        except Exception:
            pass

    def discard(self, session):
        """Throw away a prepared session that will never be played."""
        if session is not None:
            session.close_process()
            session.close_pipe()

    def play(self, session):
        """Start playing a prepared session on its own thread (stopping anything already playing)."""
        if session is None:
            return False

        self.stop(wait=True, timeout=2.0)

        with self._lock:
            self._current = session
            session.thread = threading.Thread(target=self._playback_thread, args=(session,), daemon=True)
            session.thread.start()
        return True

    @staticmethod
    def wait_until_started(session, timeout=1.0):
        """
        Block until the session's output stream has started (or failed to start).

        Returns True if the started event fired within the timeout.  This only means the attempt completed - check
        session.audio_start_time > 0 to confirm it actually started.
        """
        return session.started_event.wait(timeout)

    def _playback_thread(self, session):
        """Copy ffmpeg's output to a dedicated OutputStream until the end of the sound or a stop request."""
        chunk_bytes = self.FRAMES_PER_CHUNK * self.BYTES_PER_FRAME
        stream = None
        try:
            stream = sd.OutputStream(samplerate=session.samplerate,
                                     channels=self.CHANNELS,
                                     dtype='float32',
                                     blocksize=self.FRAMES_PER_CHUNK)
            stream.start()

            session.audio_start_time = time.monotonic()
            try:
                # OutputStream.latency is the output buffer latency in seconds.
                session.output_latency = float(stream.latency)
            except Exception:
                session.output_latency = 0.0
            # Let the video thread anchor its clock to the audio now.
            session.started_event.set()

            chunk, session.first_chunk = session.first_chunk, None
            while chunk and not session.stop_requested.is_set():
                # A partial frame can only happen at the very end of the pipe
                usable = len(chunk) - len(chunk) % self.BYTES_PER_FRAME
                if usable:
                    samples = np.frombuffer(chunk, dtype=np.float32, count=usable // 4)
                    stream.write(samples.reshape(-1, self.CHANNELS))
                chunk = session.process.stdout.read(chunk_bytes)

            if session.stop_requested.is_set():
                # Throw away what is still buffered so a stop is heard straight away
                stream.abort()
            else:
                # End of the sound - let the last buffer play out
                stream.stop()

        except Exception as e:
            if not session.stop_requested.is_set():
                self.logger.error("Audio playback error: %s", e)
        finally:
            if stream is not None:
                try:
                    stream.close()
                except Exception:
                    pass
            session.close_process()
            session.close_pipe()
            # Make sure a video thread waiting on the start can never block here, even if the stream failed
            # before started_event was set above.
            session.started_event.set()
            session.finished_event.set()

    def stop(self, session=None, wait=True, timeout=1.0):
        """
        Stop playback - of the given session, or of whatever is playing.  Optionally wait for the audio thread to
        finish.
        """
        with self._lock:
            if session is None:
                session = self._current
            if session is None:
                return
            if session is self._current:
                self._current = None

        session.stop_requested.set()
        session.close_process()  # Unblocks the audio thread if it is waiting on ffmpeg

        if session.thread is None:
            # Prepared but never played
            session.close_pipe()
        elif wait and not session.finished_event.wait(timeout):
            self.logger.warning("Timeout waiting for audio thread to stop (%.2fs)", timeout)


# ----------------------------------------------------------------------------------------------------------------------
class FrameMailbox:
    """
    Hands decoded frames from the playback thread to the UI thread.  Only the newest frame is kept: if the UI thread
    falls behind (busy, or SwapBuffers waiting for vsync) the older frames are dropped here, rather than piling up in
    the wx event queue - which used to make the video lag behind the audio.
    """

    def __init__(self, deliver):
        self._deliver = deliver  # Called on the UI thread with each frame
        self._lock = threading.Lock()
        self._item = None
        self._scheduled = False

    def post(self, item):
        """Playback thread: replace the waiting frame, and ask the UI thread to take it if it hasn't been asked."""
        with self._lock:
            self._item = item
            if self._scheduled:
                return
            self._scheduled = True
        wx.CallAfter(self._take)

    def _take(self):
        with self._lock:
            item, self._item = self._item, None
            self._scheduled = False
        if item is not None:
            self._deliver(item)

    def clear(self):
        with self._lock:
            self._item = None


def fit_frame(frame_width, frame_height, panel_width, panel_height):
    """Largest size that fits the frame in the panel keeping its aspect ratio, centred.  Returns (x, y, w, h)."""
    panel_aspect = panel_width / panel_height
    frame_aspect = frame_width / frame_height

    if panel_aspect > frame_aspect:
        # Panel is wider than frame
        height = panel_height
        width = height * frame_aspect
    else:
        # Panel is taller than frame
        width = panel_width
        height = width / frame_aspect

    return (panel_width - width) / 2, (panel_height - height) / 2, width, height


# ----------------------------------------------------------------------------------------------------------------------
# Title overlay - text drawn over the top of the video (used by the full screen player)
OVERLAY_MARGIN = 10         # Gap between the top of the panel and the title band
OVERLAY_PADDING = (24, 8)   # Space around the text inside the band (x, y)
OVERLAY_ALPHA = 170         # How solid the dark band is (0 - 255)


def make_overlay_image(text, font, max_width):
    """
    UI thread: the text drawn in white on a see-through dark band, shortened with '...' to fit max_width.
    Returns a wx.Image with an alpha channel, or None if there is nothing to draw.
    """
    pad_x, pad_y = OVERLAY_PADDING
    if not text or max_width <= 2 * pad_x + 10:
        return None

    dc = wx.MemoryDC(wx.Bitmap(1, 1))
    dc.SetFont(font if font and font.IsOk() else wx.Font(wx.FontInfo(20).Bold()))
    text = wx.Control.Ellipsize(text, dc, wx.ELLIPSIZE_END, max_width - 2 * pad_x)
    text_width, text_height = dc.GetTextExtent(text)
    width, height = text_width + 2 * pad_x, text_height + 2 * pad_y

    bitmap = wx.Bitmap(width, height, 24)
    dc.SelectObject(bitmap)
    dc.SetBackground(wx.BLACK_BRUSH)
    dc.Clear()
    dc.SetTextForeground(wx.WHITE)
    dc.DrawText(text, pad_x, pad_y)
    dc.SelectObject(wx.NullBitmap)

    # White text on black: the brightness of each pixel is how much text is in it, so it sets the alpha too
    image = bitmap.ConvertToImage()
    rgb = np.frombuffer(bytes(image.GetData()), dtype=np.uint8).reshape(height, width, 3)
    alpha = np.maximum(rgb.max(axis=2), OVERLAY_ALPHA).astype(np.uint8)
    image.SetAlpha(alpha.tobytes())
    return image


class TitleOverlay:
    """The overlay state shared by both video panels.  The image is rebuilt only when the text or width changes."""

    def _init_overlay(self):
        self._overlay_text = None
        self._overlay_font = None
        self._overlay_key = None
        self._overlay_image = None

    def set_overlay(self, text, font=None):
        """UI thread: show text over the top of the video, or None to remove it"""
        self._overlay_text = text or None
        self._overlay_font = font
        self._overlay_key = None
        self._overlay_image = None
        if self:
            self.Refresh(eraseBackground=False)

    def _get_overlay_image(self, max_width):
        """The overlay image for this width, and whether it changed since last time"""
        key = (self._overlay_text, max_width)
        if key == self._overlay_key:
            return self._overlay_image, False
        self._overlay_key = key
        self._overlay_image = make_overlay_image(self._overlay_text, self._overlay_font, max_width)
        return self._overlay_image, True


if OPENGL_AVAILABLE:
    class OpenGLVideoPanel(TitleOverlay, glcanvas.GLCanvas):
        """OpenGL-accelerated video display panel.  All GL calls are made on the UI thread."""

        # How many times SetCurrent() may fail while the panel is on screen before OpenGL is treated as broken
        MAX_SET_CURRENT_FAILURES = 20

        def __init__(self, parent, logger):
            # No depth buffer - it is never used, and asking for one narrows the display configurations that can be
            # picked on some Linux / EGL setups.
            super().__init__(parent, attribList=[glcanvas.WX_GL_RGBA, glcanvas.WX_GL_DOUBLEBUFFER])
            self.logger = logger
            self.context = glcanvas.GLContext(self)
            if hasattr(self.context, 'IsOK') and not self.context.IsOK():
                self.Destroy()
                raise RuntimeError('could not create an OpenGL context')

            self._init_overlay()
            self.overlay_texture_id = None
            self.texture_id = None
            # Currently allocated texture dimensions (width, height).  Used to decide between a one-off glTexImage2D
            # (re)allocation and a cheap in-place glTexSubImage2D update on later frames of the same size.  The
            # texture is kept between videos and only reallocated when the frame size changes.
            self.texture_size = None
            self.frame_size = (640, 480)
            self.has_frame = False  # False until the current video's first frame is uploaded - draw black till then
            self.gl_initialized = False
            self.gl_failed = False
            self._set_current_failures = 0
            self._frames_dropped = 0        # Frames posted but not shown, in a row
            self._logged_errors = set()
            self._mailbox = FrameMailbox(self._show_frame)

            self.Bind(wx.EVT_PAINT, self.on_paint)
            self.Bind(wx.EVT_SIZE, self.on_size)
            self.Bind(wx.EVT_ERASE_BACKGROUND, self.on_erase_background)

        def _log_once(self, key, message):
            """Log an error the first time it happens, rather than for every frame."""
            if key not in self._logged_errors:
                self._logged_errors.add(key)
                self.logger.error(message)

        def _make_current(self) -> bool:
            if self.SetCurrent(self.context) is False:
                self._set_current_failures += 1
                if self._set_current_failures >= self.MAX_SET_CURRENT_FAILURES and not self.gl_failed:
                    self.gl_failed = True
                    self.logger.error("OpenGL: could not make the GL context current")
                return False
            self._set_current_failures = 0
            return True

        def is_ready(self) -> bool:
            return self.gl_initialized

        def has_failed(self) -> bool:
            return self.gl_failed

        def init_gl(self):
            """Initialize OpenGL settings (UI thread).  Does nothing until the panel is actually on screen."""
            if not self or self.gl_initialized or self.gl_failed:
                return
            if not self.IsShownOnScreen():
                return

            try:
                if not self._make_current():
                    return

                glClearColor(0.0, 0.0, 0.0, 1.0)
                glEnable(GL_TEXTURE_2D)

                if self.texture_id is None:
                    self.texture_id = glGenTextures(1)
                glBindTexture(GL_TEXTURE_2D, self.texture_id)
                glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
                glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
                # Clamp, so linear filtering doesn't bleed a line of the opposite edge in along the borders
                glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE)
                glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)

                # OpenCV frames are tightly packed BGR rows, whatever the width
                glPixelStorei(GL_UNPACK_ALIGNMENT, 1)
                glPixelStorei(GL_UNPACK_ROW_LENGTH, 0)

                self.texture_size = None
                self.gl_initialized = True

            except Exception as e:
                self.gl_failed = True
                self.logger.error(f"OpenGL initialization error: {e}")

        def invalidate_gl(self):
            """
            The panel has just been shown again (UI thread).

            A GL canvas that was hidden and re-shown may need its context making current against a new surface
            before anything drawn on it can reach the screen (GTK/EGL).  Marking the panel not-ready sends the
            playback thread back through _wait_for_display, which re-runs init_gl once the panel is really on
            screen - and falls back to the software panel if GL can never be made current.
            """
            if not self.gl_failed:
                self.gl_initialized = False

        def _note_dropped(self, key: str, reason: str) -> None:
            """A posted frame couldn't be shown.  Reported once a run of them says it isn't just the odd one."""
            self._frames_dropped += 1
            if self._frames_dropped >= DROPPED_FRAME_REPORT:
                self._log_once(key, f"OpenGL: {self._frames_dropped} frames in a row were not shown - {reason}")

        def cleanup_gl(self):
            """Clean up OpenGL resources (UI thread)"""
            self._mailbox.clear()
            if not self or not self.gl_initialized:
                return
            try:
                if self._make_current():
                    for texture in (self.texture_id, self.overlay_texture_id):
                        if texture is not None:
                            glDeleteTextures([texture])
            except Exception:
                pass
            self.texture_id = None
            self.overlay_texture_id = None
            self._overlay_key = None  # Upload the overlay again if GL is set up again
            self.texture_size = None
            self.gl_initialized = False

        def reset_cache(self):
            """Reset for a new video (UI thread) - forget the old frame and draw black"""
            self._mailbox.clear()
            self.has_frame = False
            if self.gl_initialized and self.IsShownOnScreen():
                try:
                    if self._make_current():
                        self._draw_scene()
                except Exception:
                    pass

        def post_frame(self, frame):
            """Playback thread: queue a decoded BGR frame for display.  Makes no wx or GL calls."""
            if frame is not None:
                self._mailbox.post(frame)

        def _show_frame(self, frame):
            """UI thread: upload the frame to the texture and draw it"""
            if not self:  # The panel has been destroyed
                return
            if not self.gl_initialized:
                self.init_gl()
                if not self.gl_initialized:
                    self._note_dropped('gl_not_ready', 'OpenGL could not be set up for this panel')
                    return
            if not self.IsShownOnScreen():
                self._note_dropped('panel_offscreen', 'the video panel is not on screen')
                return

            try:
                if not self._make_current():
                    self._note_dropped('gl_not_current', 'the GL context could not be made current')
                    return

                height, width = frame.shape[0], frame.shape[1]
                glBindTexture(GL_TEXTURE_2D, self.texture_id)

                # Upload the frame straight from OpenCV as BGR - the GPU does the BGR->RGB swizzle for free, so we
                # avoid a full-frame cv2.cvtColor on the UI thread for every frame.
                if self.texture_size != (width, height):
                    # Frame size changed (or first real frame): (re)allocate the texture storage once.
                    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGB, width, height, 0,
                                 GL_BGR, GL_UNSIGNED_BYTE, frame)
                    self.texture_size = (width, height)
                else:
                    # Same size: update the existing storage in place, which is far cheaper than reallocating.
                    glTexSubImage2D(GL_TEXTURE_2D, 0, 0, 0, width, height,
                                    GL_BGR, GL_UNSIGNED_BYTE, frame)

                self.frame_size = (width, height)
                self.has_frame = True
                self._frames_dropped = 0

                # Draw immediately rather than calling Refresh() and bouncing back through a paint event
                self._draw_scene()

            except Exception as e:
                self._log_once('texture', f"Texture update error: {e}")

        def _draw_scene(self):
            """
            Render the current texture as an aspect-correct quad and swap buffers.

            The caller must already have made the GL context current.  Shared by on_paint (expose/resize events) and
            _show_frame (per-frame draw) so there is a single draw path.
            """
            glClear(GL_COLOR_BUFFER_BIT)

            if self.texture_id is None or (not self.has_frame and not self._overlay_text):
                self.SwapBuffers()
                return

            # Determine the *drawable* (framebuffer) size in physical pixels and set the viewport from it on every
            # draw.  Relying on EVT_SIZE to set the viewport is unreliable across GTK/Wayland versions (the event
            # timing differs, and under fractional/HiDPI scaling the GL drawable is larger than the logical widget
            # size).  Recomputing here means the video always fills the canvas whether or not a size event fired.
            client = self.GetClientSize()
            scale = self.GetContentScaleFactor() or 1.0
            width = int(round(client.width * scale))
            height = int(round(client.height * scale))
            if width <= 0 or height <= 0:
                return

            glViewport(0, 0, width, height)

            # Set up orthographic projection in drawable-pixel space
            glMatrixMode(GL_PROJECTION)
            glLoadIdentity()
            glOrtho(0, width, height, 0, -1, 1)

            glMatrixMode(GL_MODELVIEW)
            glLoadIdentity()

            if self.has_frame:
                x_offset, y_offset, draw_width, draw_height = fit_frame(self.frame_size[0], self.frame_size[1],
                                                                        width, height)
                self._draw_quad(self.texture_id, x_offset, y_offset, draw_width, draw_height)

            if self._overlay_text:
                self._draw_overlay(client.width, scale)

            self.SwapBuffers()

        @staticmethod
        def _draw_quad(texture, x, y, width, height):
            """Draw a texture as a rectangle (drawable pixels, top left origin)"""
            glBindTexture(GL_TEXTURE_2D, texture)
            glBegin(GL_QUADS)
            glTexCoord2f(0, 0)
            glVertex2f(x, y)
            glTexCoord2f(1, 0)
            glVertex2f(x + width, y)
            glTexCoord2f(1, 1)
            glVertex2f(x + width, y + height)
            glTexCoord2f(0, 1)
            glVertex2f(x, y + height)
            glEnd()

        def _draw_overlay(self, logical_width, scale):
            """Blend the title over the top centre of the video.  The image is made in logical pixels."""
            image, changed = self._get_overlay_image(logical_width)
            if image is None:
                return
            image_width, image_height = image.GetWidth(), image.GetHeight()

            if self.overlay_texture_id is None:
                self.overlay_texture_id = glGenTextures(1)
                glBindTexture(GL_TEXTURE_2D, self.overlay_texture_id)
                glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
                glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
                glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE)
                glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)
                changed = True
            if changed:
                rgb = np.frombuffer(bytes(image.GetData()), dtype=np.uint8).reshape(image_height, image_width, 3)
                alpha = np.frombuffer(bytes(image.GetAlpha()), dtype=np.uint8).reshape(image_height, image_width, 1)
                rgba = np.ascontiguousarray(np.concatenate((rgb, alpha), axis=2))
                glBindTexture(GL_TEXTURE_2D, self.overlay_texture_id)
                glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, image_width, image_height, 0,
                             GL_RGBA, GL_UNSIGNED_BYTE, rgba)

            draw_width, draw_height = image_width * scale, image_height * scale
            glEnable(GL_BLEND)
            glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
            self._draw_quad(self.overlay_texture_id, round((logical_width * scale - draw_width) / 2),
                            round(OVERLAY_MARGIN * scale), draw_width, draw_height)
            glDisable(GL_BLEND)

        def on_paint(self, _event):
            """Handle paint events"""
            # A PaintDC must always be created in a paint handler, even though GL does the drawing - otherwise
            # Windows keeps sending paint events and burns CPU.
            dc = wx.PaintDC(self)  # noqa: F841 - must exist for the whole handler
            if not self.gl_initialized or not self.IsShownOnScreen():
                return

            try:
                if self._make_current():
                    self._draw_scene()
            except Exception as e:
                self._log_once('paint', f"Paint error: {e}")

        def on_size(self, event):
            """
            Handle resize events.

            The viewport/projection are recomputed from the real drawable size on every draw in _draw_scene, so here
            we only need to request a repaint so a resize while paused is reflected immediately.
            """
            self.Refresh(eraseBackground=False)
            event.Skip()

        def on_erase_background(self, _event):
            """GL paints the whole canvas, so skip the erase - it only causes flicker (mostly on Windows)"""
            pass


class SoftwareVideoPanel(TitleOverlay, wx.Panel):
    """Software-based video display panel (fallback when OpenGL can't be used)"""

    def __init__(self, parent, logger):
        super().__init__(parent)
        self.logger = logger

        # BG_STYLE_PAINT: we paint every pixel ourselves, and it lets AutoBufferedPaintDC skip its extra copy on
        # platforms that already double buffer (GTK3, macOS)
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.SetBackgroundColour(wx.BLACK)
        self._black_brush = wx.Brush(wx.BLACK)

        self._init_overlay()
        self._overlay_bitmap = None
        self.bitmap = None
        self.bitmap_position = None  # (x, y) the bitmap was scaled for, or None to centre it at paint time

        # Copy of GetClientSize() for the playback thread, which mustn't call wx.  Updated on the UI thread.
        self._client_size = self.GetClientSize().Get()
        self._mailbox = FrameMailbox(self._show_frame)

        self.logger.warning('Using software video rendering')

        self.Bind(wx.EVT_PAINT, self.on_paint)
        self.Bind(wx.EVT_SIZE, self.on_size)

    @staticmethod
    def is_ready() -> bool:
        return True

    @staticmethod
    def has_failed() -> bool:
        return False

    def post_frame(self, frame):
        """
        Playback thread: scale and colour-convert the frame here (off the UI thread), then queue it for display.
        Makes no wx calls - creating bitmaps or reading window sizes off the UI thread isn't safe on GTK or macOS.
        """
        if frame is None:
            return

        height, width = frame.shape[:2]
        panel_width, panel_height = self._client_size
        position = None

        if panel_width > 0 and panel_height > 0:
            x, y, scale_width, scale_height = fit_frame(width, height, panel_width, panel_height)
            scale_width, scale_height = max(int(scale_width), 1), max(int(scale_height), 1)
            position = (max(0, int(x)), max(0, int(y)))
            if (scale_width, scale_height) != (width, height):
                # OpenCV scaling is much faster than wx.Image.Scale.  INTER_LINEAR is a good quality/speed balance.
                frame = cv2.resize(frame, (scale_width, scale_height), interpolation=cv2.INTER_LINEAR)

        # Convert BGR to RGB after scaling (smaller image).  In place - the frame is ours (cap.read() and
        # cv2.resize() both return a new array).
        cv2.cvtColor(frame, cv2.COLOR_BGR2RGB, dst=frame)

        self._mailbox.post((frame, position))

    def _show_frame(self, item):
        """UI thread: copy the frame into the bitmap and repaint"""
        if not self:  # The panel has been destroyed
            return

        rgb, position = item
        height, width = rgb.shape[:2]

        # Reuse the bitmap while the size stays the same - no wx.Image and no new bitmap for every frame
        if self.bitmap is not None and self.bitmap.IsOk() and self.bitmap.GetSize().Get() == (width, height):
            self.bitmap.CopyFromBuffer(rgb)
        else:
            self.bitmap = wx.Bitmap.FromBuffer(width, height, rgb)

        self.bitmap_position = position
        self.Refresh(eraseBackground=False)

    def on_paint(self, _event):
        """Handle paint events"""
        dc = wx.AutoBufferedPaintDC(self)
        self.draw(dc)

    def draw(self, dc):
        """Draw the video frame"""
        dc.SetBackground(self._black_brush)
        dc.Clear()

        if self.bitmap and self.bitmap.IsOk():
            if self.bitmap_position:
                x, y = self.bitmap_position
            else:
                # Not scaled for the panel yet (it had no size) - just centre it
                panel_size = self.GetClientSize()
                bitmap_size = self.bitmap.GetSize()
                x = max(0, (panel_size.width - bitmap_size.width) // 2)
                y = max(0, (panel_size.height - bitmap_size.height) // 2)
            dc.DrawBitmap(self.bitmap, x, y, False)

        if self._overlay_text:
            panel_width = self.GetClientSize().width
            image, changed = self._get_overlay_image(panel_width)
            if image is None:
                return
            if changed or self._overlay_bitmap is None:
                self._overlay_bitmap = wx.Bitmap(image)
            dc.DrawBitmap(self._overlay_bitmap, (panel_width - image.GetWidth()) // 2, OVERLAY_MARGIN, True)

    def on_size(self, event):
        """Handle resize events - the next frame is scaled to the new size"""
        self._client_size = self.GetClientSize().Get()
        self.Refresh(eraseBackground=False)
        event.Skip()

    def reset_cache(self):
        """Reset for a new video (UI thread) - clear the old frame to prevent a flash of the previous video"""
        self._mailbox.clear()
        self._client_size = self.GetClientSize().Get()
        self.bitmap = None
        self.bitmap_position = None
        self.Refresh(eraseBackground=False)


# ----------------------------------------------------------------------------------------------------------------------
class Video:
    """
    Video player.  The public interface (play, stop, is_playing, cleanup, video_path, video_panel...) is used by the
    main view, Tile View and the full screen player.

    Each play() gets a new generation number.  The load worker, the UI-thread start and the playback thread all
    carry the number they were started for, and give up as soon as a newer play() or a stop() has replaced it.
    """

    def __init__(self, parent_panel, logger, image_panel, horizontal_size, vertical_size,
                 video_caption_label, use_video_caption=False,
                 video_path=None):
        self.panel = parent_panel
        self.logger = logger
        self.image_panel = image_panel

        self.video_caption_label = video_caption_label
        self.use_video_caption = use_video_caption

        self.media_player_available = True
        self.video_path = video_path

        self.horizontal_size = horizontal_size
        self.vertical_size = vertical_size

        self.close_selected = False
        self.video_playing = False  # True from play() until the video ends or stop() is called
        self.playback_started = False  # True once the video since the last play() actually started playing
        self.video_panel = None

        self.audio_player = AudioPlayer(logger)

        self._generation = 0
        self._generation_lock = threading.Lock()
        self._load_lock = threading.Lock()  # Serialises loads so two workers never run at once
        self._stop_event = threading.Event()  # A new one per playback; set to end that playback thread
        self._playback_thread = None
        self._panel_bindings = []  # (event, handler) pairs, re-applied if the panel is replaced
        self._overlay = (None, None)  # (text, font) drawn over the video, re-applied if the panel is replaced

        self._initialize_backend()

    # ------------------------------------------------------------------------------------------------------------------
    # Set up
    def _initialize_backend(self):
        """Create the video panel"""
        try:
            self.video_panel = self._create_video_panel()

            # For windowed mode, use specified dimensions.
            # SetMinSize is required so that the sizer (proportion=0) allocates the correct height - mirrors how
            # ImagePanel handles its fixed size.
            if self.horizontal_size > 0 and self.vertical_size > 0:
                size = wx.Size(self.horizontal_size, self.vertical_size)
                self.video_panel.SetMinSize(size)
                self.video_panel.SetSize(size)

            # Add to parent's sizer if it exists
            sizer = self.panel.GetSizer()
            if sizer:
                sizer.Add(self.video_panel, 1, wx.EXPAND)
                self.panel.Layout()

            self.logger.info(_("OpenCV video player with audio support initialized"))

        except Exception as e:
            self.logger.error(_("Failed to initialize OpenCV video player: {}").format(e))
            self.media_player_available = False

    def _create_video_panel(self):
        """OpenGL panel if possible, otherwise the software one"""
        if not OPENGL_AVAILABLE:
            self.logger.info("Using software video panel (OpenGL not available)")
        elif software_video_wanted():
            self.logger.info("Using software video panel (selected in preferences)")
        elif _opengl_failed_this_session:
            self.logger.info("Using software video panel (OpenGL failed earlier)")
        else:
            try:
                panel = OpenGLVideoPanel(self.panel, self.logger)
                self.logger.info(f"Using OpenGL video panel (PyOpenGL platform: {OPENGL_PLATFORM})")
                return panel
            except Exception as e:
                self.logger.warning(f"OpenGL failed, falling back to software: {e}")
        return SoftwareVideoPanel(self.panel, self.logger)

    def bind_panel_event(self, event, handler):
        """Bind an event on the video panel.  Use this rather than video_panel.Bind() so the binding survives a
        switch to the software panel."""
        self._panel_bindings.append((event, handler))
        if self.video_panel:
            self.video_panel.Bind(event, handler)

    def set_overlay_text(self, text, font=None):
        """UI thread: draw text (e.g. a title) over the top of the video, or None to remove it"""
        self._overlay = (text, font)
        if self.video_panel:
            self.video_panel.set_overlay(text, font)

    def _fall_back_to_software(self, done, only_if_visible):
        """
        UI thread: replace the OpenGL panel with a software one, in the same place, size and sizer.

        :param done: Event set when finished, whatever happened
        :param only_if_visible: If True (GL just didn't get ready in time) only switch when the window is really on
                                screen - a minimised or hidden window is a good reason for GL not being ready.
        """
        global _opengl_failed_this_session
        try:
            old_panel = self.video_panel
            if not old_panel or isinstance(old_panel, SoftwareVideoPanel):
                return
            if only_if_visible:
                top = wx.GetTopLevelParent(old_panel)
                if (not old_panel.IsShown() or not top or not top.IsShown()
                        or (hasattr(top, 'IsIconized') and top.IsIconized())):
                    return

            self.logger.warning("OpenGL video did not start - switching to software video rendering")
            _opengl_failed_this_session = True

            new_panel = SoftwareVideoPanel(old_panel.GetParent(), self.logger)
            new_panel.SetMinSize(old_panel.GetMinSize())
            new_panel.SetSize(old_panel.GetSize())
            new_panel.SetPosition(old_panel.GetPosition())
            for event, handler in self._panel_bindings:
                new_panel.Bind(event, handler)
            new_panel.set_overlay(*self._overlay)

            sizer = old_panel.GetContainingSizer()
            if sizer:
                sizer.Replace(old_panel, new_panel)

            was_shown = old_panel.IsShown()
            self.video_panel = new_panel
            old_panel.cleanup_gl()
            old_panel.Destroy()

            new_panel.Show(was_shown)
            if was_shown:
                new_panel.Raise()
            if sizer:
                new_panel.GetParent().Layout()
            new_panel.reset_cache()
        except Exception as e:
            self.logger.error(f"Could not switch to software video rendering: {e}")
        finally:
            done.set()

    # ------------------------------------------------------------------------------------------------------------------
    # Generation numbers
    def _new_generation(self) -> int:
        with self._generation_lock:
            self._generation += 1
            return self._generation

    def _is_current(self, token) -> bool:
        return token == self._generation and not self.close_selected

    # ------------------------------------------------------------------------------------------------------------------
    # Play
    def play(self):
        """
        Play the video.

        Only the lightweight UI preparation happens here on the calling (UI) thread.  The expensive load - opening
        the capture and starting the ffmpeg audio decode - is handed to a worker thread so the UI never freezes while
        a video is being prepared.
        """
        if not self.media_player_available or not self.video_path:
            return

        # Claim this playback request.  This also cancels any playback or load in progress.
        token = self._new_generation()
        self._stop_playback()

        if self.image_panel is not None:
            # Pre-position the video panel before showing it to avoid a brief positional flash on Linux/GTK between
            # Show() and the sizer layout.
            self.video_panel.SetPosition(self.image_panel.GetPosition())
            self.image_panel.Hide()

        # Clear the old frame for the new playback session
        self.video_panel.reset_cache()

        # Show the video panel.  One that has been hidden since the last video needs OpenGL setting up again
        # before its first frame (see OpenGLVideoPanel.invalidate_gl).
        was_hidden = not self.video_panel.IsShown()
        self.video_panel.Show()
        self.video_panel.Raise()
        self.panel.Refresh()
        if was_hidden and hasattr(self.video_panel, 'invalidate_gl'):
            self.video_panel.invalidate_gl()

        # Optimistically report "playing" so external pollers (e.g. the fullscreen play_loop and is_playing()) see
        # the request immediately, even though the actual decode starts once the worker has loaded.
        self.video_playing = True
        self.playback_started = False
        self.set_video_caption(_("Loading video..."))

        # Hand the heavy load off to a worker thread.
        threading.Thread(target=self._load_and_start, args=(self.video_path, token), daemon=True).start()

    def _open_capture(self, video_path):
        """Open the video with OpenCV.  Returns (capture, fps), or (None, 0) if it can't be opened."""
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            cap.release()
            return None, 0

        # Some files report nonsense (0, nan, or thousands) - fall back to 30fps rather than fail
        fps = cap.get(cv2.CAP_PROP_FPS)
        if not (math.isfinite(fps) and 1 <= fps <= 240):
            self.logger.info(f"Video reports an unusable frame rate ({fps}) - assuming 30fps")
            fps = 30.0

        self.logger.info(f"Video loaded: {video_path}, FPS: {fps}, "
                         f"Frames: {int(cap.get(cv2.CAP_PROP_FRAME_COUNT))}")
        return cap, fps

    def _load_and_start(self, video_path, token):
        """
        Worker: open the capture and start the audio decode, then hand over to the UI thread to start playback.

        Serialised by _load_lock so loads never overlap, and checked against the generation number at each step so a
        newer play() or a stop() cancels this one - including while it was waiting for the lock.
        """
        with self._load_lock:
            if not self._is_current(token):
                return

            try:
                cap, fps = self._open_capture(video_path)
            except Exception as e:
                self.logger.error(_("Error loading media: {}").format(e))
                cap, fps = None, 0

            if cap is None:
                wx.CallAfter(self._load_failed, token, video_path)
                return

            if not self._is_current(token):
                cap.release()
                return

            # Start ffmpeg decoding the soundtrack (the slow step, especially on first access to the file)
            try:
                audio_session = self.audio_player.prepare(video_path)
            except Exception as e:
                self.logger.warning(f"Audio could not be prepared: {e}")
                audio_session = None

            if audio_session:
                self.logger.info(_("Audio extracted from video"))
            else:
                self.logger.info(_("No audio found in video or extraction failed"))

            if not self._is_current(token):
                cap.release()
                self.audio_player.discard(audio_session)
                return

            # Start the actual playback back on the UI thread
            wx.CallAfter(self._begin_playback, token, cap, fps, audio_session)

    def _load_failed(self, token, video_path):
        """UI thread: the video couldn't be opened - put the image back and say so"""
        if not self._is_current(token):
            return
        self.logger.error(_("Failed to load video: {}").format(video_path))
        self.stop()
        self.set_video_caption(_("Failed to load video"))

    def _begin_playback(self, token, cap, fps, audio_session):
        """UI thread: start the playback thread, unless a newer request superseded us between load and now."""
        if not self._is_current(token) or not self.video_playing:
            cap.release()
            self.audio_player.discard(audio_session)
            return

        self._stop_event = threading.Event()
        self._playback_thread = threading.Thread(target=self._playback_loop,
                                                 args=(token, cap, fps, audio_session, self._stop_event),
                                                 daemon=True)
        self._playback_thread.start()
        self.playback_started = True
        self.set_video_caption(_("Playing Video - Click To Stop"))

    def _wait_for_display(self, stop_event) -> bool:
        """
        Playback thread: wait until the video panel can show frames.

        On Linux the panel may not be mapped on screen straight after Show(), so the OpenGL set-up has to be retried
        until it works.  If OpenGL fails, or isn't ready in time while the window is visible, switch to the software
        panel.  Returns False if a stop was requested while waiting.
        """
        panel = self.video_panel
        deadline = time.monotonic() + GL_READY_TIMEOUT

        while panel and not panel.is_ready():
            if stop_event.is_set():
                return False

            if panel.has_failed() or time.monotonic() >= deadline:
                done = threading.Event()
                wx.CallAfter(self._fall_back_to_software, done, not panel.has_failed())
                while not done.is_set():
                    if stop_event.wait(0.05):
                        return False
                return True

            wx.CallAfter(panel.init_gl)
            if stop_event.wait(0.1):
                return False
        return True

    def _playback_loop(self, token, cap, fps, audio_session, stop_event):
        """
        Playback thread.  It owns the capture and always releases it itself, so the capture can never be released
        while it is still inside cap.read() / cap.grab() (which can crash the native OpenCV backend).
        """
        frame_duration = 1.0 / fps
        ended = False

        try:
            if not self._wait_for_display(stop_event):
                return

            # Start audio now - at the moment the video is actually ready to present frame 0 - so the two stay in
            # sync even when the GL set-up above was slow (Linux).  Check for a stop first, so a stop during that
            # wait can't leave the sound playing on its own.
            if stop_event.is_set():
                return

            # Pace playback against a fixed reference rather than a rolling per-frame timestamp.  This lets us
            # (a) sleep for the whole remaining frame interval, and (b) genuinely *drop* frames we fell behind on (via
            # cap.grab(), which demuxes without decoding) so video stays aligned to real time / audio.
            #
            # Anchor the video clock to when audio becomes *audible* - the moment the output stream started plus its
            # buffer (output) latency.  Starting the clock at "now" instead would run the video ahead of the audio by
            # that latency.  time.monotonic() is used throughout, so a system clock change can't skip or freeze video.
            start_time = time.monotonic()
            if audio_session is not None:
                self.audio_player.play(audio_session)
                if (AudioPlayer.wait_until_started(audio_session, timeout=2.0)
                        and audio_session.audio_start_time > 0):
                    # Clamp the latency offset so a pathological backend reading can't stall the first frame (or
                    # skip a large chunk of video) for long.
                    latency_offset = max(0.0, min(audio_session.output_latency, 0.5))
                    start_time = audio_session.audio_start_time + latency_offset
                else:
                    start_time = time.monotonic()

            frames_consumed = 0  # number of frames already pulled from the capture

            while not stop_event.is_set():
                elapsed = time.monotonic() - start_time

                # Index of the frame that should be on screen by now, and how many frames we still need to pull to
                # reach it.  floor() rather than int() so a negative elapsed time (clock anchored slightly in the
                # future) doesn't show the first frame early.
                target_index = math.floor(elapsed / frame_duration)
                frames_needed = (target_index + 1) - frames_consumed

                if frames_needed <= 0:
                    # Ahead of schedule: wait until the next frame is due.  Waiting on the stop event means a stop
                    # request is honoured immediately.
                    sleep_time = frames_consumed * frame_duration - elapsed
                    if sleep_time > 0:
                        stop_event.wait(sleep_time)
                    continue

                # Skip (grab only, no decode) any frames we fell behind on, then decode + present the one we
                # actually want to show.
                ret = True
                for _skip in range(frames_needed - 1):
                    ret = cap.grab()
                    frames_consumed += 1
                    if not ret:
                        break

                frame = None
                if ret:
                    ret, frame = cap.read()
                    frames_consumed += 1

                if not ret:
                    self.logger.info("Video playback ended")
                    ended = True
                    break

                panel = self.video_panel
                if panel:
                    panel.post_frame(frame)

        except Exception as e:
            self.logger.error(f"Playback error: {e}")
            ended = True
        finally:
            cap.release()
            if audio_session is not None:
                self.audio_player.stop(audio_session)
            if ended and not stop_event.is_set():
                wx.CallAfter(self._on_playback_ended, token)

    def _on_playback_ended(self, token):
        """UI thread: the video reached its end (or failed) - put the image back"""
        if self._is_current(token) and self.video_playing:
            self.stop()

    # ------------------------------------------------------------------------------------------------------------------
    # Stop
    def _stop_playback(self):
        """Stop the playback thread and the sound.  Doesn't touch any panels."""
        self._stop_event.set()
        self.audio_player.stop()

        thread = self._playback_thread
        self._playback_thread = None
        if thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=2)
            if thread.is_alive():
                # It releases the capture itself when it finally finishes
                self.logger.warning("Playback thread did not stop in time")

    def stop(self, caption=True):
        """
        Stop video playback.

        :param caption: Show 'Video Stopped' on the caption.  Pass False when the caller sets the caption itself -
                        the caption is set with CallAfter, so it would otherwise replace the caller's text.
        """
        if not self.media_player_available:
            return

        # Cancels any load in progress, so it won't start playback after we've torn down
        self._new_generation()
        self.video_playing = False

        # Stop the video playback and the audio playback
        self._stop_playback()

        # Put the image back in place of the video.  Where there is no image panel (the full screen player) the
        # video panel stays up: hiding and re-showing a GL canvas between videos can leave GTK/EGL drawing to a
        # surface that no longer reaches the screen, so the next video played its sound over a frozen picture.
        # play() blanks the panel for the next video, and callers that own the panel (tile view) still hide it.
        if self.image_panel is not None:
            if self.video_panel:
                self.video_panel.Hide()
            self.image_panel.Show()

        if caption:
            self.set_video_caption(_("Video Stopped"))

    # ------------------------------------------------------------------------------------------------------------------
    def set_video_caption(self, caption):
        """Set the video caption text"""
        if self.use_video_caption:
            wx.CallAfter(self._set_caption, caption)

    def _set_caption(self, caption):
        if self.video_caption_label:  # Not destroyed
            self.video_caption_label.SetLabel(caption)

    def set_video_path(self, path):
        """Set the video file path"""
        self.video_path = path

    def is_playing(self):
        """Check if video is currently playing"""
        return self.video_playing

    def cleanup(self):
        """Clean up resources"""
        self.close_selected = True
        self._new_generation()
        self.video_playing = False
        self._stop_playback()

        # Clean up OpenGL resources
        if self.video_panel and hasattr(self.video_panel, 'cleanup_gl'):
            self.video_panel.cleanup_gl()
