#!/usr/bin/env python3

# ----------------------------------------------------------------------------------------------------------------------
# pfemame_ribbon_bar.py

"""
Ribbon Bar for the main window menu.

This is a fully native wxPython implementation (no wx.html2 / WebView / webkit2gtk
dependency). It is drawn with wx.GraphicsContext and reproduces the look and feel
of the previous HTML/CSS ribbon: tabbed groups of icon buttons, an active-tab
underline, hover highlight with a springy scale-up and soft shadow, a click
scale-down, and a fade-in when switching tabs.

The public surface is unchanged so it remains a drop-in replacement:
    RibbonWebView(parent, main_frame)        # constructor (alias kept below)
    .set_button_background(handler, colour)  # recolour a button (e.g. flashing)
It is a wx.Panel, so SetMinSize()/sizer EXPAND continue to work as before.
"""

# Import wxpython and python modules
import wx
import os

# Import my own modules
import functions

_ = functions.set_up_language()  # Set up the application language

# ----------------------------------------------------------------------------------
# Tunables (animation feel + metrics). Adjust here to fine-tune the look.
# ----------------------------------------------------------------------------------
_ICON_SIZE = 36          # rendered icon size (CSS: .btn img 36x36)
_BTN_W = 60              # button width  (CSS: .btn width 60)
_BTN_H = 70              # button height (CSS: .btn height 70)
_BTN_RADIUS = 10         # button corner radius (CSS: .btn border-radius 10)
_BTN_GAP = 6             # gap between buttons in a group (CSS: .group gap 6)
_GROUP_GAP = 10          # gap between groups (CSS: .tab-content gap 10)
_GROUP_PAD_RIGHT = 10    # padding before a group separator (CSS: .group padding-right 10)
_CONTENT_PAD_X = 10      # left padding of the content row (CSS: .tab-content padding 6 10)

_TAB_PAD_X = 14          # tab horizontal padding (CSS: .tab padding 6 14)
_TAB_PAD_Y = 6           # tab vertical padding
_TAB_BAR_PAD_X = 10      # tab-bar left padding (CSS: .tab-bar padding 6 10)
_TAB_BAR_PAD_Y = 6
_TAB_RADIUS = 6
_UNDERLINE_H = 3         # active tab underline thickness (CSS height 3)
_UNDERLINE_INSET = 8     # active tab underline left/right inset (CSS left/right 8)
_ACCENT = wx.Colour(0, 120, 212)   # #0078D4 Windows accent underline

_HOVER_SCALE = 1.08      # CSS: .btn:hover transform scale(1.08)
_PRESS_SCALE = 0.95      # CSS: .btn:active transform scale(0.95)

# Spring constants for the hover/press scale. Slight overshoot to mimic the CSS
# cubic-bezier(0.34, 1.56, 0.64, 1) easing.
_SPRING_STIFFNESS = 0.28
_SPRING_DAMPING = 0.60
_ANIM_INTERVAL = 16      # ms per animation tick (~60fps)
_FADE_MS = 150           # tab-switch fade duration (CSS animation 0.15s)
_FADE_SLIDE = 3          # tab-switch slide distance in px (CSS translateY 3px)


# ----------------------------------------------------------------------------------
class _Button:
    """Lightweight render/animation state for a single ribbon button."""

    __slots__ = (
        "icon", "tooltip", "handler", "label", "bitmap",
        "x", "y", "w", "h",
        "scale", "vel", "target", "settled",
        "hovered", "pressed", "bg_override",
    )

    def __init__(self, icon, tooltip, handler, label, bitmap):
        self.icon = icon
        self.tooltip = tooltip or ""
        self.handler = handler
        self.label = label or ""
        self.bitmap = bitmap
        self.x = self.y = 0
        self.w = _BTN_W
        self.h = _BTN_H
        self.scale = 1.0
        self.vel = 0.0
        self.target = 1.0
        self.settled = True
        self.hovered = False
        self.pressed = False
        self.bg_override = None

    def rect(self):
        return wx.Rect(self.x, self.y, self.w, self.h)


# ----------------------------------------------------------------------------------
class RibbonBar(wx.Panel):
    """Native ribbon bar - drop-in replacement for the old WebView ribbon."""

    def __init__(self, parent, main_frame):
        super().__init__(parent, style=wx.BORDER_NONE)

        self.main_frame = main_frame
        self.parent = parent
        self.icon_path = os.path.join(functions.path_to_me(), "toolbar_icons")
        self.application_colors = functions.get_application_colors()

        # Avoid background-erase flicker; we paint everything ourselves.
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)

        self._compute_colors()
        self._build_fonts()

        # A small off-screen DC purely for measuring text during layout.
        self._measure_dc = wx.MemoryDC()
        self._measure_dc.SelectObject(wx.Bitmap(1, 1))

        # Build the data model (tabs -> list of groups -> list of _Button).
        self.button_defs_by_tab = self._get_button_defs()
        self.tabs = list(self.button_defs_by_tab.keys())
        self.groups_by_tab = {t: self._build_groups(defs)
                              for t, defs in self.button_defs_by_tab.items()}
        self.active_tab = 0

        # Interaction / animation state.
        self.tab_rects = []          # list[wx.Rect] aligned with self.tabs
        self.hover_tab = None
        self.press_tab = None
        self.hover_btn = None
        self.press_btn = None
        self._tab_bar_h = 0
        self._content_top = 0
        self._separators = []        # x positions of group separators for active tab

        self._fade_alpha = 1.0
        self._fade_offset = 0.0

        self._timer = wx.Timer(self)

        self.SetBackgroundColour(self.c_ribbon)
        self.SetMinSize(wx.Size(-1, self._best_height()))

        # Event bindings.
        self.Bind(wx.EVT_PAINT, self.on_paint)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda e: None)
        self.Bind(wx.EVT_SIZE, self.on_size)
        self.Bind(wx.EVT_MOTION, self.on_motion)
        self.Bind(wx.EVT_LEAVE_WINDOW, self.on_leave)
        self.Bind(wx.EVT_LEFT_DOWN, self.on_left_down)
        self.Bind(wx.EVT_LEFT_UP, self.on_left_up)
        self.Bind(wx.EVT_TIMER, self.on_timer, self._timer)
        self.Bind(wx.EVT_WINDOW_DESTROY, self.on_destroy)

        self._layout()

    # ------------------------------------------------------------------------------
    # Colours / fonts
    # ------------------------------------------------------------------------------
    def _compute_colors(self):
        colors = self.application_colors

        self.c_ribbon = wx.Colour(colors.get("ribbon_bar", wx.Colour(255, 255, 255)))
        self.c_text = wx.Colour(colors.get("text", wx.Colour(0, 0, 0)))

        # Derive separator / hover / active colours from the ribbon brightness,
        # exactly like the old CSS did.
        r, g, b = self.c_ribbon.Red(), self.c_ribbon.Green(), self.c_ribbon.Blue()
        brightness = (r * 299 + g * 587 + b * 114) // 1000
        if brightness > 128:  # light ribbon
            self.c_separator = wx.Colour(0, 0, 0, 46)        # rgba(0,0,0,0.18)
            self.c_hover = wx.Colour(255, 255, 255, 153)     # rgba(255,255,255,0.6)
            self.c_shadow = wx.Colour(0, 0, 0, 26)           # rgba(0,0,0,0.1)
            self.c_tab_active = wx.Colour(255, 255, 255, 242)  # rgba(255,255,255,0.95)
        else:                 # dark ribbon
            self.c_separator = wx.Colour(255, 255, 255, 56)  # rgba(255,255,255,0.22)
            self.c_hover = wx.Colour(255, 255, 255, 38)      # rgba(255,255,255,0.15)
            self.c_shadow = wx.Colour(0, 0, 0, 102)          # rgba(0,0,0,0.4)
            self.c_tab_active = wx.Colour(255, 255, 255, 46)  # rgba(255,255,255,0.18)

    def _build_fonts(self):
        base = wx.SystemSettings.GetFont(wx.SYS_DEFAULT_GUI_FONT)

        self.tab_font = wx.Font(base)
        self.tab_font_active = wx.Font(base)
        self.tab_font_active.SetWeight(wx.FONTWEIGHT_BOLD)

        # Button label ~10px (CSS .btn span font-size 10px).
        self.label_font = wx.Font(base)
        self.label_font.SetPointSize(max(7, base.GetPointSize() - 2))

    # ------------------------------------------------------------------------------
    # Model building
    # ------------------------------------------------------------------------------
    def _load_icon(self, icon):
        if not icon:
            return None
        path = os.path.join(self.icon_path, icon)
        if not os.path.exists(path):
            print("Missing icon:", path)
            return None
        try:
            img = wx.Bitmap(path).ConvertToImage()
            img = img.Scale(_ICON_SIZE, _ICON_SIZE, wx.IMAGE_QUALITY_HIGH)
            return wx.Bitmap(img)
        except Exception as exc:
            print("Icon load error:", path, exc)
            return None

    def _build_groups(self, defs):
        """Split a tab's button defs into groups on 'Section:' markers."""
        groups = []
        current = []
        for icon, tooltip, handler, label in defs:
            if icon and icon.startswith("Section:"):
                if current:
                    groups.append(current)
                    current = []
                continue
            current.append(_Button(icon, tooltip, handler, label, self._load_icon(icon)))
        if current:
            groups.append(current)
        return groups

    # ------------------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------------------
    def _measure(self, text, font):
        self._measure_dc.SetFont(font)
        return self._measure_dc.GetTextExtent(text)

    def _best_height(self):
        th = self._measure("Ag", self.tab_font_active).height
        tab_bar_h = _TAB_BAR_PAD_Y + th + 2 * _TAB_PAD_Y
        return tab_bar_h + _BTN_H + 8

    def _layout(self):
        # --- Tab bar ---
        self.tab_rects = []
        x = _TAB_BAR_PAD_X
        y = _TAB_BAR_PAD_Y
        tab_h = 0
        for tab in self.tabs:
            tw, th = self._measure(tab, self.tab_font_active)  # measure bold (widest)
            w = tw + 2 * _TAB_PAD_X
            h = th + 2 * _TAB_PAD_Y
            tab_h = max(tab_h, h)
            self.tab_rects.append(wx.Rect(x, y, w, h))
            x += w
        self._tab_bar_h = _TAB_BAR_PAD_Y + tab_h
        self._content_top = self._tab_bar_h + 2

        # --- Active tab content (buttons + separators) ---
        self._separators = []
        size = self.GetClientSize()
        avail_h = max(size.height, self._content_top + _BTN_H)
        btn_y = self._content_top + (avail_h - self._content_top - _BTN_H) // 2

        bx = _CONTENT_PAD_X
        groups = self.groups_by_tab[self.tabs[self.active_tab]]
        for gi, group in enumerate(groups):
            for bi, btn in enumerate(group):
                btn.x = bx
                btn.y = btn_y
                bx += _BTN_W
                if bi < len(group) - 1:
                    bx += _BTN_GAP
            # Separator after each group except the last.
            if gi < len(groups) - 1:
                bx += _GROUP_PAD_RIGHT
                self._separators.append(bx)
                bx += 1 + _GROUP_GAP

    # ------------------------------------------------------------------------------
    # Painting
    # ------------------------------------------------------------------------------
    def on_size(self, event):
        self._layout()
        self.Refresh()
        event.Skip()

    def on_paint(self, _event):
        dc = wx.AutoBufferedPaintDC(self)
        dc.SetBackground(wx.Brush(self.c_ribbon))
        dc.Clear()

        gc = wx.GraphicsContext.Create(dc)
        if gc is None:
            return

        self._paint_tabs(gc)
        self._paint_content(gc)

    def _paint_tabs(self, gc):
        gc.SetPen(wx.TRANSPARENT_PEN)
        for i, (tab, rect) in enumerate(zip(self.tabs, self.tab_rects)):
            active = (i == self.active_tab)
            if active:
                gc.SetBrush(wx.Brush(self.c_tab_active))
                gc.DrawRoundedRectangle(rect.x, rect.y, rect.width, rect.height, _TAB_RADIUS)
            elif i == self.hover_tab:
                gc.SetBrush(wx.Brush(self.c_hover))
                gc.DrawRoundedRectangle(rect.x, rect.y, rect.width, rect.height, _TAB_RADIUS)

            font = self.tab_font_active if active else self.tab_font
            gc.SetFont(font, self.c_text)
            tw, th = self._measure(tab, font)
            gc.DrawText(tab, rect.x + (rect.width - tw) / 2, rect.y + (rect.height - th) / 2)

            if active:
                gc.SetBrush(wx.Brush(_ACCENT))
                gc.DrawRoundedRectangle(
                    rect.x + _UNDERLINE_INSET,
                    rect.y + rect.height - _UNDERLINE_H,
                    rect.width - 2 * _UNDERLINE_INSET,
                    _UNDERLINE_H,
                    _UNDERLINE_H / 2.0,
                )

    def _paint_content(self, gc):
        gc.PushState()
        if self._fade_offset:
            gc.Translate(0, self._fade_offset)

        layered = False
        if self._fade_alpha < 1.0:
            try:
                gc.BeginLayer(self._fade_alpha)
                layered = True
            except Exception:
                layered = False

        # Group separators.
        gc.SetPen(wx.TRANSPARENT_PEN)
        gc.SetBrush(wx.Brush(self.c_separator))
        for sx in self._separators:
            gc.DrawRectangle(sx, self._content_top + 4, 1, _BTN_H - 8)

        # Buttons.
        for group in self.groups_by_tab[self.tabs[self.active_tab]]:
            for btn in group:
                self._paint_button(gc, btn)

        if layered:
            gc.EndLayer()
        gc.PopState()

    def _paint_button(self, gc, btn):
        cx = btn.x + btn.w / 2.0
        cy = btn.y + btn.h / 2.0

        gc.PushState()
        gc.Translate(cx, cy)
        gc.Scale(btn.scale, btn.scale)
        gc.Translate(-cx, -cy)
        gc.SetPen(wx.TRANSPARENT_PEN)

        # Soft shadow, fading in with the hover scale (faux gaussian: stacked rects).
        raise_amt = max(0.0, min(1.0, (btn.scale - 1.0) / (_HOVER_SCALE - 1.0)))
        if raise_amt > 0.01:
            for grow, frac in ((6, 0.20), (3, 0.45), (0, 0.9)):
                a = int(self.c_shadow.Alpha() * frac * raise_amt)
                if a <= 0:
                    continue
                col = wx.Colour(self.c_shadow.Red(), self.c_shadow.Green(),
                                self.c_shadow.Blue(), a)
                gc.SetBrush(wx.Brush(col))
                gc.DrawRoundedRectangle(
                    btn.x - grow, btn.y - grow + 4,
                    btn.w + 2 * grow, btn.h + 2 * grow,
                    _BTN_RADIUS + grow,
                )

        # Button background: explicit override (e.g. flashing) or hover highlight.
        if btn.bg_override is not None:
            gc.SetBrush(wx.Brush(btn.bg_override))
            gc.DrawRoundedRectangle(btn.x, btn.y, btn.w, btn.h, _BTN_RADIUS)
        elif btn.hovered:
            gc.SetBrush(wx.Brush(self.c_hover))
            gc.DrawRoundedRectangle(btn.x, btn.y, btn.w, btn.h, _BTN_RADIUS)

        # Icon + label, vertically centred (CSS: flex column, centred).
        tw, th = self._measure(btn.label, self.label_font)
        content_h = _ICON_SIZE + 2 + th
        start_y = btn.y + (btn.h - content_h) / 2.0
        if btn.bitmap is not None:
            gc.DrawBitmap(btn.bitmap, cx - _ICON_SIZE / 2.0, start_y, _ICON_SIZE, _ICON_SIZE)
        gc.SetFont(self.label_font, self.c_text)
        gc.DrawText(btn.label, cx - tw / 2.0, start_y + _ICON_SIZE + 2)

        gc.PopState()

    # ------------------------------------------------------------------------------
    # Hit testing
    # ------------------------------------------------------------------------------
    def _hit_tab(self, pt):
        for i, rect in enumerate(self.tab_rects):
            if rect.Contains(pt):
                return i
        return None

    def _hit_button(self, pt):
        for group in self.groups_by_tab[self.tabs[self.active_tab]]:
            for btn in group:
                if btn.rect().Contains(pt):
                    return btn
        return None

    # ------------------------------------------------------------------------------
    # Mouse handling
    # ------------------------------------------------------------------------------
    def on_motion(self, event):
        pt = event.GetPosition()

        new_tab = self._hit_tab(pt)
        if new_tab != self.hover_tab:
            self.hover_tab = new_tab
            self.Refresh()

        new_btn = self._hit_button(pt)
        if new_btn is not self.hover_btn:
            if self.hover_btn is not None:
                self.hover_btn.hovered = False
                self._set_target(self.hover_btn, _PRESS_SCALE if self.hover_btn.pressed else 1.0)
            self.hover_btn = new_btn
            if new_btn is not None:
                new_btn.hovered = True
                self._set_target(new_btn, _PRESS_SCALE if new_btn.pressed else _HOVER_SCALE)
                self.SetToolTip(new_btn.tooltip)
            else:
                self.UnsetToolTip()

    def on_leave(self, _event):
        if self.hover_tab is not None:
            self.hover_tab = None
            self.Refresh()
        if self.hover_btn is not None:
            self.hover_btn.hovered = False
            self._set_target(self.hover_btn, 1.0)
            self.hover_btn = None
            self.UnsetToolTip()

    def on_left_down(self, event):
        pt = event.GetPosition()

        btn = self._hit_button(pt)
        if btn is not None:
            self.press_btn = btn
            btn.pressed = True
            self._set_target(btn, _PRESS_SCALE)
            return

        tab = self._hit_tab(pt)
        if tab is not None:
            self.press_tab = tab

    def on_left_up(self, event):
        pt = event.GetPosition()

        if self.press_btn is not None:
            btn = self.press_btn
            btn.pressed = False
            self.press_btn = None
            still_on = btn.rect().Contains(pt)
            self._set_target(btn, _HOVER_SCALE if still_on else 1.0)
            if still_on:
                self._invoke(btn.handler)
            return

        if self.press_tab is not None:
            tab = self.press_tab
            self.press_tab = None
            if self._hit_tab(pt) == tab:
                self.switch_tab(tab)

    def _invoke(self, handler):
        try:
            func = getattr(self.main_frame, handler, None)
            if callable(func):
                func(None)
            else:
                print(f"[DEBUG] No handler for {handler}")
        except Exception as exc:
            print("Ribbon handler error:", exc)

    # ------------------------------------------------------------------------------
    # Tab switching + animation
    # ------------------------------------------------------------------------------
    def switch_tab(self, index):
        if index == self.active_tab:
            return
        self.active_tab = index

        # Reset any per-button animation state on the newly shown tab.
        if self.hover_btn is not None:
            self.hover_btn.hovered = False
            self.hover_btn = None
        self.press_btn = None
        for group in self.groups_by_tab[self.tabs[index]]:
            for btn in group:
                btn.scale = 1.0
                btn.vel = 0.0
                btn.target = 1.0
                btn.settled = True
                btn.hovered = False
                btn.pressed = False

        self._layout()

        # Kick off the fade-in (opacity 0->1 + slide up), like the CSS keyframe.
        self._fade_alpha = 0.0
        self._fade_offset = float(_FADE_SLIDE)
        self._ensure_timer()
        self.Refresh()

    def _set_target(self, btn, target):
        btn.target = target
        btn.settled = False
        self._ensure_timer()

    def _ensure_timer(self):
        if not self._timer.IsRunning():
            self._timer.Start(_ANIM_INTERVAL)

    def on_timer(self, _event):
        active = False

        for group in self.groups_by_tab[self.tabs[self.active_tab]]:
            for btn in group:
                if btn.settled:
                    continue
                diff = btn.target - btn.scale
                btn.vel += diff * _SPRING_STIFFNESS
                btn.vel *= _SPRING_DAMPING
                btn.scale += btn.vel
                if abs(diff) < 0.001 and abs(btn.vel) < 0.001:
                    btn.scale = btn.target
                    btn.vel = 0.0
                    btn.settled = True
                else:
                    active = True

        if self._fade_alpha < 1.0:
            self._fade_alpha = min(1.0, self._fade_alpha + _ANIM_INTERVAL / _FADE_MS)
            active = True
        if self._fade_offset > 0.0:
            self._fade_offset = max(0.0, self._fade_offset - _FADE_SLIDE * _ANIM_INTERVAL / _FADE_MS)
            active = True

        self.Refresh()
        if not active:
            self._timer.Stop()

    def on_destroy(self, event):
        # A timer left running past its owner's destruction delivers its queued WM_TIMER
        # to a freed window, which corrupts the heap as the app shuts down.
        if self._timer.IsRunning():
            self._timer.Stop()
        event.Skip()

    # ------------------------------------------------------------------------------
    # Public API (preserved from the old WebView ribbon)
    # ------------------------------------------------------------------------------
    def set_button_background(self, handler_name, css_color):
        """
        Selectively change a button's background colour (used for the file-paths
        button flashing, but works for any button). Pass a falsy colour to clear.
        """
        colour = None
        if css_color:
            colour = css_color if isinstance(css_color, wx.Colour) else wx.Colour(css_color)
            if not colour.IsOk():
                colour = None

        for groups in self.groups_by_tab.values():
            for group in groups:
                for btn in group:
                    if btn.handler == handler_name:
                        btn.bg_override = colour
        self.Refresh()

    # ------------------------------------------------------------------------------
    def _get_button_defs(self):
        return {
            "File": [
                ("Section: ROM Launching", None, None, None),
                ("play.png", _("Play ROM"), "on_double_click", "Play"),
                ("play_random.png", "Random Play", "on_random", "Random"),

                # ("Section: Setup", None, None, None),
                # ("filepaths.png", _("File Paths"), "on_file_paths", "Paths"),

                ("Section: Database", None, None, None),
                ("refresh_database.png", _("Refresh ROMs Database"), "on_database_refresh", "Refresh"),

                ("Section: Alternate View", None, None, None),
                ("tile_view.png", _("Tile View"), "on_tile_view", "Tile"),

                ("Section: Record / Playback", None, None, None),
                ("record_rom_input.png", _("Record User Inputs"), "on_input_record", "Record"),
                ("playback_rom_input.png", _("Playback User Inputs"), "on_input_playback", "Playback"),

                ("Section: Backups", None, None, None),
                ("backup_all_settings.png", _("Backup All User Settings"), "on_backup", "Backup"),
                ("load_settings_from_backup.png", _("Restore All User Settings"), "on_restore", "Restore"),
                ("export_favorite_roms.png", _("Export Favorite ROMs"), "on_export_favorite", "Export"),

                ("Section: Exit", None, None, None),
                ("exit.png", _("Quit"), "on_close", "Quit")
            ],

            "Edit": [
                ("add_to_favorites.png", _("Add the selected ROM to Favorite list"), "on_add_favorite", "Favorite"),
                ("rom_rating.png", _("Set Rating for selected ROM"), "on_set_rating", "Rating"),
                ("clipboard.png", _("Copy image to clipboard"), "on_save_image", "Clipboard"),
                ("find_rom.png", _("Find"), "on_find", "Find"),
                ("clear_messages.png", _("Clear the messages window"), "on_clear_messages", "Clear"),
                ("messages_to_clipboard.png", _("Copy messages window to clipboard"), "on_copy_messages", "Copy"),
                ("reset_spacing.png", _("Reset the ROMs list column spacing to default"), "on_reset_spacing", "Columns"),
                ("alternate_emulators.png", _("Setup alternate emulator engines"), "on_alternate_emulators", "Emulators"),
            ],

            "Tools": [
                ("verifyrom.png", _("Verify the selected ROM files"), "on_verify_roms", "Verify"),
                ("check_all_roms.png", _("Check All ROMs"), "on_check_all", "Check"),
                ("check_artwork_files.png", _("Check the artwork files"), "on_check_artwork", "Artwork"),
                ("reset_ini.png", _("Reset the ROM specific INI file to its default settings"), "on_ini_file_reset", "Reset"),
                ("software_lists.png", _("Browse the software lists of the selected system"), "on_software_browser", "Software"),
            ],

            "View": [
                ("rom_info.png", _("Display ROM files information"), "on_rom_info", "Info"),
                ("fullscreen_player.png", _("Full screen video player"), "on_fullscreen_video_player", "Full"),
                ("view_log_file.png", _("View the pfeMAME log file"), "on_logfile_display", "Log"),
                ("media_types.png", _("View the selected file media types supported"), "on_view_media_types", "Media"),
                ("mame_changes.png", _("What's new in the latest MAME (new, now working and removed machines)"), "on_mame_changes", "New"),
            ],

            "Help": [
                ("view_controls.png", _("View MAME controls"), "on_controls_box_display", "Controls"),
                ("view_manual.png", _("View the pfeMAME manual"), "on_manual_display", "Manual"),
                ("check_for_updates.png", _("Check for pfeMAME updates"), "check_for_updates", "Updates"),
                ("web_page.png", _("Open the pfeMAME web page"), "open_web_page", "Web"),
                ("view_change_log.png", _("View the pfeMAME changelog"), "on_changelog_display", "Changelog"),
                ("about.png", _("About"), "on_about_box_display", "About"),
            ]
        }


# Backwards-compatible alias: the rest of the app constructs
# pfemame_ribbon_bar.RibbonWebView(...). Keeping the name avoids touching callers.
RibbonWebView = RibbonBar


# ----------------------------------------------------------------------------------
# Main Frame (TEST HARNESS)
# ----------------------------------------------------------------------------------

class MainFrame(wx.Frame):
    def __init__(self):
        super().__init__(None, title="Native Ribbon Test", size=wx.Size(1000, 600))

        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)

        self.ribbon = RibbonBar(panel, self)
        self.ribbon.SetMinSize(wx.Size(-1, 100))

        self.content = wx.Panel(panel)
        self.content.SetBackgroundColour(wx.Colour(240, 240, 240))

        sizer.Add(self.ribbon, 0, wx.EXPAND)
        sizer.Add(self.content, 1, wx.EXPAND)

        panel.SetSizer(sizer)

        self.Centre()
        self.Show()

    # Test handlers ----------------------------------------------------------------
    def on_double_click(self, event): print("Play clicked")
    def on_random(self, event): print("Random clicked")
    def on_database_refresh(self, event): print("Refresh clicked")
    def on_tile_view(self, event): print("Tile clicked")
    def on_close(self, event): print("Quit clicked")


# ----------------------------------------------------------------------------------

if __name__ == '__main__':
    app = wx.App(False)
    MainFrame()
    app.MainLoop()
