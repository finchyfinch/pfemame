#!/usr/bin/env python3

# ----------------------------------------------------------------------------------------------------------------------
# aboutbox.py

"""
Show the pfeMAME about information.

The window is a single painted canvas: a big Pac-Man wanders around the background eating dots (chased by a ghost),
behind a see-through card holding the logo, version details and links.  Everything except the game sprites is drawn
in the application's own colour scheme.
"""

import math
import os
import random
import re
import sys

import wx

import functions
import global_defaults as gd
import iniFile
from custom_text_ctrl import CustomTextCtrl

_ = functions.set_up_language()

WEBSITE = 'https://sourceforge.net/projects/pfemame/'
EMAIL = 'pfemame@gmail.com'

FRAME_MS = 25                               # Animation timer interval (40 frames a second)
DOT_RESPAWN_FRAMES = 500                    # An eaten dot comes back after this many frames

PACMAN_YELLOW = wx.Colour(255, 204, 0)
PACMAN_OUTLINE = wx.Colour(150, 110, 0)
GHOST_PINK = wx.Colour(255, 120, 190, 215)
GHOST_PUPIL = wx.Colour(33, 33, 222)


def license_file_name(language: str) -> str:
    """The licence file for a language, falling back to English for languages without one."""
    return gd.get_language(language).license


def with_alpha(colour: wx.Colour, alpha: int) -> wx.Colour:
    return wx.Colour(colour.Red(), colour.Green(), colour.Blue(), alpha)


def is_dark(colour: wx.Colour) -> bool:
    return (colour.Red() * 299 + colour.Green() * 587 + colour.Blue() * 114) / 1000 < 128


# ----------------------------------------------------------------------------------------------------------------------
class Roamer:
    """
    Something that wanders around a rectangle: drifts in gentle random curves, bounces off the edges and, when given
    a threat, steers away from it.  Has no wx code so it can be tested on its own.
    """

    def __init__(self, width: float, height: float, radius: float, speed: float, rng=None):
        self.rng = rng or random.Random()
        self.width, self.height = width, height
        self.radius, self.speed = radius, speed
        self.x = self.rng.uniform(radius, max(radius, width - radius))
        self.y = self.rng.uniform(radius, max(radius, height - radius))
        self.angle = self.rng.uniform(0, 2 * math.pi)
        self.turn = 0.0

    def step(self, threat=None) -> None:
        roll = self.rng.random()
        if roll < 0.02:
            self.turn = self.rng.uniform(-0.05, 0.05)
        elif roll < 0.03:
            self.turn = 0.0
        self.angle += self.turn

        if threat is not None:
            dx, dy = self.x - threat[0], self.y - threat[1]
            if math.hypot(dx, dy) < self.radius * 4:
                away = math.atan2(dy, dx)
                difference = (away - self.angle + math.pi) % (2 * math.pi) - math.pi
                self.angle += difference * 0.08

        self.x += math.cos(self.angle) * self.speed
        self.y += math.sin(self.angle) * self.speed

        # Bounce off the edges
        if self.x < self.radius or self.x > self.width - self.radius:
            self.angle = math.pi - self.angle
            self.x = min(max(self.x, self.radius), self.width - self.radius)
        if self.y < self.radius or self.y > self.height - self.radius:
            self.angle = -self.angle
            self.y = min(max(self.y, self.radius), self.height - self.radius)
        self.angle %= 2 * math.pi


class Chaser:
    """Drifts towards a target, a little slower than the target moves so it never quite catches it."""

    def __init__(self, x: float, y: float, speed: float):
        self.x, self.y, self.speed = x, y, speed
        self.wobble = 0.0

    def step(self, target) -> None:
        self.wobble += 0.06
        dx, dy = target[0] - self.x, target[1] - self.y
        distance = math.hypot(dx, dy)
        if distance > 1:
            angle = math.atan2(dy, dx) + math.sin(self.wobble) * 0.5
            self.x += math.cos(angle) * self.speed
            self.y += math.sin(angle) * self.speed


def corner_alpha(x: int, y: int, width: int, height: int, radius: int) -> float:
    """How much of pixel (x, y) is inside a width x height rectangle with rounded corners (0 to 1)."""
    cx = min(max(x + 0.5, radius), width - radius)
    cy = min(max(y + 0.5, radius), height - radius)
    distance = math.hypot(x + 0.5 - cx, y + 0.5 - cy)
    return min(max(radius - distance + 0.5, 0.0), 1.0)


def round_corners(image: wx.Image, radius: int) -> wx.Image:
    """Make the corners of an image transparent, smoothed at the edge."""
    image = image.Copy()
    if not image.HasAlpha():
        image.InitAlpha()
    width, height = image.GetWidth(), image.GetHeight()
    for y in list(range(radius)) + list(range(height - radius, height)):
        for x in list(range(radius)) + list(range(width - radius, width)):
            image.SetAlpha(x, y, int(image.GetAlpha(x, y) * corner_alpha(x, y, width, height, radius)))
    return image


def unwrap_paragraphs(text: str) -> str:
    """
    Join hard-wrapped lines back into paragraphs so the text control can wrap them to its own width.  Blank lines
    and numbered items ("1.", "2." ...) still start a new line.  No space is added when joining CJK text.
    """
    paragraphs = []
    for block in re.split(r'\n\s*\n', text.replace('\r\n', '\n').strip()):
        lines = []
        for line in (line.strip() for line in block.split('\n')):
            if not line:
                continue
            if lines and not re.match(r'\d+\.\s', line):
                joiner = '' if is_cjk(lines[-1][-1]) or is_cjk(line[0]) else ' '
                lines[-1] = lines[-1] + joiner + line
            else:
                lines.append(line)
        paragraphs.append('\n'.join(re.sub(r'[ \t]+', ' ', line) for line in lines))
    return '\n\n'.join(paragraphs)


def is_cjk(character: str) -> bool:
    """Chinese, Japanese or Korean characters (and full-width punctuation), which are not separated by spaces."""
    return '\u2e80' <= character <= '\u9fff' or '\uf900' <= character <= '\ufaff' or '\uff00' <= character <= '\uffef'


def wrap_text(text: str, max_width: float, measure) -> list:
    """Split text into lines no wider than max_width.  Words too long to fit (or CJK text) are split by character."""
    lines, line = [], ''
    for word in text.split(' '):
        candidate = f'{line} {word}' if line else word
        if measure(candidate) <= max_width:
            line = candidate
            continue
        if line:
            lines.append(line)
        line = ''
        for character in word:
            if line and measure(line + character) > max_width:
                lines.append(line)
                line = ''
            line += character
    if line:
        lines.append(line)
    return lines


# ----------------------------------------------------------------------------------------------------------------------
class OnAboutBox(wx.Frame):
    def __init__(self, version: str, copy_right: str):
        style = (wx.DEFAULT_DIALOG_STYLE | wx.CLOSE_BOX | wx.STAY_ON_TOP | wx.CLIP_CHILDREN)
        super().__init__(wx.GetApp().TopWindow, -1, _('About pfeMAME'), style=style)

        self.version = version
        self.copy_right = copy_right
        self.path_to_me = functions.path_to_me()
        self.application_colors = functions.get_application_colors()
        self.language = iniFile.read_ini_file('preferences', 'language', 'english')
        self.showing_license = False
        self.link_rects = {}

        self.SetIcon(wx.Icon(os.path.join(self.path_to_me, 'images', 'pfemame.ico')))
        self.Bind(wx.EVT_CLOSE, self.on_close)
        self.Bind(wx.EVT_CHAR_HOOK, self.on_key_up)

        # Following will only be called if this window is running as a child
        if self.GetParent():
            self.GetParent().Disable()

        self._init_colours()
        self._init_fonts()
        self._init_ui()

        self.Centre()
        self.Show()

        self.timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.on_timer, self.timer)
        self.Bind(wx.EVT_WINDOW_DESTROY, self.on_destroy)
        self.timer.Start(FRAME_MS)

    def _init_colours(self):
        # The colours may come back as tuples, so make them all wx.Colour
        colours = {key: wx.Colour(value) for key, value in self.application_colors.items()}
        self.application_colors = colours
        self.background = colours['window_background']
        self.text_colour = colours['text']
        self.muted_text = with_alpha(self.text_colour, 170)
        self.card_colour = with_alpha(self.background, 155)
        self.card_border = with_alpha(self.text_colour, 60)
        self.dot_colour = with_alpha(self.text_colour, 80)
        self.link_colour = wx.Colour(110, 180, 255) if is_dark(self.background) else wx.Colour(0, 102, 204)

    def _init_fonts(self):
        self.FONT_TITLE = wx.Font(wx.FontInfo(28).Bold())
        self.FONT_VERSION = wx.Font(wx.FontInfo(12).Bold())
        self.FONT_BODY = wx.Font(wx.FontInfo(10))
        self.FONT_SMALL = wx.Font(wx.FontInfo(9))
        self.FONT_LINK = wx.Font(wx.FontInfo(10).Underlined())

    def _init_ui(self):
        self.canvas = wx.Panel(self, style=wx.CLIP_CHILDREN)
        self.canvas.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.canvas.SetBackgroundColour(self.background)
        self.canvas.Bind(wx.EVT_PAINT, self.on_paint)
        self.canvas.Bind(wx.EVT_MOTION, self.on_mouse_move)
        self.canvas.Bind(wx.EVT_LEFT_UP, self.on_mouse_click)

        self.SetClientSize(self.FromDIP(wx.Size(720, 460)))
        width, height = self.GetClientSize()

        # The card in the middle that holds all the information
        card_width, card_height = self.FromDIP(500), self.FromDIP(310)
        self.card = wx.Rect((width - card_width) // 2, (height - card_height) // 2, card_width, card_height)
        self.padding = self.FromDIP(26)

        logo_path = os.path.join(self.path_to_me, 'images', 'pfemame_logo_new.png')
        logo_size = self.FromDIP(124)
        self.logo = None
        if os.path.exists(logo_path):
            logo = functions.load_and_scale_bitmap(logo_path, logo_size, logo_size, 'LANCZOS')
            self.logo = wx.Bitmap(round_corners(logo.ConvertToImage(), self.FromDIP(16)))

        # Buttons along the bottom of the card
        button_size = self.FromDIP(wx.Size(100, 32))
        self.license_button = functions.build_one_button(self.canvas, _('License'), self.on_license,
                                                         background_color=self.application_colors['button_background'],
                                                         foreground_color=self.text_colour,
                                                         horizontal_size=button_size.width,
                                                         vertical_size=button_size.height)
        ok_button = functions.build_one_button(self.canvas, _('OK'), self.on_ok,
                                               background_color=self.application_colors['button_background'],
                                               foreground_color=self.text_colour,
                                               horizontal_size=button_size.width,
                                               vertical_size=button_size.height)
        buttons_y = self.card.Bottom - self.padding - button_size.height + 1
        self.license_button.SetPosition((self.card.Left + self.padding, buttons_y))
        ok_button.SetPosition((self.card.Right - self.padding - button_size.width + 1, buttons_y))

        # The licence text takes over the card while it is shown
        self.license_text = CustomTextCtrl(self.canvas,
                                           value=self._read_license(),
                                           pos=(self.card.Left + self.padding, self.card.Top + self.padding),
                                           size=wx.Size(self.card.Width - 2 * self.padding,
                                                        buttons_y - self.card.Top - 2 * self.padding),
                                           style=wx.TE_MULTILINE | wx.TE_READONLY | wx.BORDER_NONE | wx.TE_WORDWRAP)
        self.license_text.SetBackgroundColour(self.application_colors['text_background'])
        self.license_text.SetForegroundColour(self.text_colour)
        self.license_text.SetScrollbarThumbColor(self.application_colors['scrollbar_thumb'])
        self.license_text.SetScrollbarTrackColor(self.application_colors['scrollbar_track'])
        self.license_text.SetFont(self.FONT_SMALL)
        self.license_text.Hide()

        # The game in the background
        scale = self.GetDPIScaleFactor()
        self.pacman = Roamer(width, height, 44 * scale, 2.2 * scale)
        self.ghost = Chaser(width - self.pacman.x, height - self.pacman.y, 1.7 * scale)
        spacing = self.FromDIP(34)
        self.dots = [[x, y, 0]
                     for x in range(spacing // 2, width, spacing)
                     for y in range(spacing // 2, height, spacing)]
        self.mouth_phase = 0.0

    def _read_license(self) -> str:
        license_path = os.path.join(self.path_to_me, 'license', license_file_name(self.language))
        try:
            with open(license_path, 'r', encoding='utf-8') as f:
                return unwrap_paragraphs(f.read())
        except (FileNotFoundError, IOError):
            return _('License file not found.')

    # ------------------------------------------------------------------------------------------------------------------
    # Animation

    def on_timer(self, _event):
        self.pacman.step(threat=(self.ghost.x, self.ghost.y))
        self.ghost.step((self.pacman.x, self.pacman.y))
        self.mouth_phase += 0.25

        reach = self.pacman.radius * 0.6
        for dot in self.dots:
            if dot[2]:
                dot[2] -= 1
            elif abs(dot[0] - self.pacman.x) < reach and abs(dot[1] - self.pacman.y) < reach:
                dot[2] = DOT_RESPAWN_FRAMES
        self.canvas.Refresh(False)

    def on_paint(self, _event):
        self._render(wx.AutoBufferedPaintDC(self.canvas))

    def _render(self, dc):
        dc.SetBackground(wx.Brush(self.background))
        dc.Clear()
        gc = wx.GraphicsContext.Create(dc)
        if not gc:
            return
        gc.SetAntialiasMode(wx.ANTIALIAS_DEFAULT)

        self._draw_dots(gc)
        self._draw_ghost(gc)
        self._draw_pacman(gc)
        self._draw_card(gc)

    def _draw_dots(self, gc):
        size = self.FromDIP(4)
        gc.SetPen(wx.NullGraphicsPen)
        gc.SetBrush(wx.Brush(self.dot_colour))
        for x, y, eaten in self.dots:
            if not eaten:
                gc.DrawRectangle(x - size / 2, y - size / 2, size, size)

    def _draw_pacman(self, gc):
        p = self.pacman
        mouth = (math.sin(self.mouth_phase) + 1) / 2 * 0.75 + 0.03
        path = gc.CreatePath()
        path.MoveToPoint(p.x, p.y)
        path.AddArc(p.x, p.y, p.radius, p.angle + mouth, p.angle + 2 * math.pi - mouth, True)
        path.CloseSubpath()
        gc.SetPen(wx.Pen(PACMAN_OUTLINE, max(1, self.FromDIP(1))))
        gc.SetBrush(wx.Brush(PACMAN_YELLOW))
        gc.DrawPath(path)

        # Keep the eye on top of his head whichever way he is going
        side = -math.pi / 2 if math.cos(p.angle) >= 0 else math.pi / 2
        eye_x = p.x + math.cos(p.angle + side) * p.radius * 0.5 + math.cos(p.angle) * p.radius * 0.1
        eye_y = p.y + math.sin(p.angle + side) * p.radius * 0.5 + math.sin(p.angle) * p.radius * 0.1
        eye = p.radius * 0.12
        gc.SetPen(wx.NullGraphicsPen)
        gc.SetBrush(wx.Brush(wx.Colour(30, 30, 30)))
        gc.DrawEllipse(eye_x - eye, eye_y - eye, eye * 2, eye * 2)

    def _draw_ghost(self, gc):
        g = self.ghost
        r = self.FromDIP(30)
        path = gc.CreatePath()
        path.MoveToPoint(g.x - r, g.y)
        path.AddArc(g.x, g.y, r, math.pi, 2 * math.pi, True)
        path.AddLineToPoint(g.x + r, g.y + r)
        # Wavy skirt, rippling as it moves
        waves = 4
        ripple = math.sin(g.wobble * 3) * r * 0.08
        for i in range(waves):
            x_right = g.x + r - i * 2 * r / waves
            path.AddLineToPoint(x_right - r / waves, g.y + r * 0.7 + ripple)
            path.AddLineToPoint(x_right - 2 * r / waves, g.y + r)
        path.CloseSubpath()
        gc.SetPen(wx.NullGraphicsPen)
        gc.SetBrush(wx.Brush(GHOST_PINK))
        gc.DrawPath(path)

        # Eyes that follow Pac-Man
        look = math.atan2(self.pacman.y - g.y, self.pacman.x - g.x)
        for offset in (-r * 0.35, r * 0.35):
            ex, ey = g.x + offset, g.y - r * 0.15
            gc.SetBrush(wx.Brush(wx.WHITE))
            gc.DrawEllipse(ex - r * 0.22, ey - r * 0.28, r * 0.44, r * 0.56)
            px, py = ex + math.cos(look) * r * 0.1, ey + math.sin(look) * r * 0.14
            gc.SetBrush(wx.Brush(GHOST_PUPIL))
            gc.DrawEllipse(px - r * 0.11, py - r * 0.11, r * 0.22, r * 0.22)

    def _draw_card(self, gc):
        card = self.card
        corner = self.FromDIP(16)
        gc.SetPen(wx.Pen(self.card_border, max(1, self.FromDIP(1))))
        gc.SetBrush(wx.Brush(self.card_colour))
        gc.DrawRoundedRectangle(card.x, card.y, card.width, card.height, corner)

        self.link_rects = {}
        if self.showing_license:
            return

        left, top = card.Left + self.padding, card.Top + self.padding

        # Logo with rounded corners
        text_left = left
        if self.logo:
            gc.DrawBitmap(self.logo, left, top, self.logo.GetWidth(), self.logo.GetHeight())
            text_left = left + self.logo.GetWidth() + self.FromDIP(24)

        y = top + self.FromDIP(4)
        y = self._draw_line(gc, 'pfeMAME', self.FONT_TITLE, self.text_colour, text_left, y)
        y = self._draw_line(gc, f'Version {self.version}', self.FONT_VERSION, self.text_colour, text_left, y + 2)
        y += self.FromDIP(8)
        versions = f'Python {sys.version.split()[0]}   ·   wxPython {wx.VERSION_STRING}'
        y = self._draw_line(gc, versions, self.FONT_SMALL, self.muted_text, text_left, y)
        self._draw_line(gc, self.copy_right, self.FONT_SMALL, self.muted_text, text_left, y + 2)

        # Description, centred under the logo row
        y = top + (self.logo.GetHeight() if self.logo else self.FromDIP(124)) + self.FromDIP(24)
        gc.SetFont(self.FONT_BODY, self.text_colour)
        width = card.Width - 2 * self.padding
        for line in wrap_text(_('pfeMAME is a front end for the MAME emulation system'), width,
                              lambda s: gc.GetTextExtent(s)[0]):
            y = self._draw_centred(gc, line, self.FONT_BODY, self.text_colour, y)

        # Links
        y += self.FromDIP(14)
        gc.SetFont(self.FONT_LINK, self.link_colour)
        website_label = _('Visit Website')
        separator = '     ·     '
        website_width = gc.GetTextExtent(website_label)[0]
        email_width = gc.GetTextExtent(EMAIL)[0]
        separator_width = gc.GetTextExtent(separator)[0]
        x = card.Left + (card.Width - website_width - separator_width - email_width) / 2
        height = gc.GetTextExtent(website_label)[1]
        gc.DrawText(website_label, x, y)
        self.link_rects[WEBSITE] = wx.Rect(int(x), int(y), int(website_width), int(height))
        gc.SetFont(self.FONT_BODY, self.muted_text)
        gc.DrawText(separator, x + website_width, y)
        gc.SetFont(self.FONT_LINK, self.link_colour)
        x += website_width + separator_width
        gc.DrawText(EMAIL, x, y)
        self.link_rects[f'mailto:{EMAIL}'] = wx.Rect(int(x), int(y), int(email_width), int(height))

    @staticmethod
    def _draw_line(gc, text, font, colour, x, y) -> float:
        gc.SetFont(font, colour)
        gc.DrawText(text, x, y)
        return y + gc.GetTextExtent(text)[1]

    def _draw_centred(self, gc, text, font, colour, y) -> float:
        gc.SetFont(font, colour)
        width, height = gc.GetTextExtent(text)
        gc.DrawText(text, self.card.Left + (self.card.Width - width) / 2, y)
        return y + height

    # ------------------------------------------------------------------------------------------------------------------
    # Events

    def _link_at(self, position):
        for url, rect in self.link_rects.items():
            if rect.Contains(position):
                return url
        return None

    def on_mouse_move(self, event):
        cursor = wx.CURSOR_HAND if self._link_at(event.GetPosition()) else wx.CURSOR_ARROW
        self.canvas.SetCursor(wx.Cursor(cursor))
        event.Skip()

    def on_mouse_click(self, event):
        url = self._link_at(event.GetPosition())
        if url:
            wx.LaunchDefaultBrowser(url)
        event.Skip()

    def on_license(self, _event):
        self.showing_license = not self.showing_license
        self.license_text.Show(self.showing_license)
        if self.showing_license:
            # It was laid out while hidden, so lay the text out again now it has its real size
            self.license_text.Layout()
            self.license_text.SetValue(self.license_text.GetValue())
        self.license_button.SetLabel(_('Back') if self.showing_license else _('License'))
        self.license_button.Refresh()
        self.canvas.Refresh(False)

    def on_key_up(self, event):
        if event.GetKeyCode() == wx.WXK_ESCAPE:
            self.on_close(-1)
            return
        event.Skip()

    def on_destroy(self, event):
        if event.GetEventObject() is self:
            self.timer.Stop()
        event.Skip()

    def on_close(self, _event):
        self.timer.Stop()
        parent = self.GetParent()
        if parent is not None:
            parent.Enable()
            if hasattr(parent, 'list'):
                parent.list.SetFocus()
        self.Destroy()

    def on_ok(self, _event):
        self.on_close(-1)


if __name__ == '__main__':
    app = wx.App(False)
    OnAboutBox("3.10", "© 2025 Gareth Finch")
    app.MainLoop()
