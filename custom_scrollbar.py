#!/usr/bin/env python3

# ----------------------------------------------------------------------------------------------------------------------
# custom_scrollbar.py

# Import wxpython and python modules
import wx


class UnifiedScrollbar(wx.Panel):
    """
    A unified, customizable wxPython scrollbar with two operational modes and a fade effect.

    This class can function in one of two ways, determined by the arguments provided
    during initialization:

    1.  **'target' mode**: When a `target_scroller` (e.g., a wx.ScrolledWindow) is
        provided, the scrollbar directly manipulates the target's scroll position.
        The thumb's size and position are automatically calculated based on the
        target's virtual and visible dimensions.

    2.  **'callback' mode**: When an `on_scroll` callback function is provided,
        the scrollbar does not control an external window. Instead, it calls the
        callback with a float value between 0.0 and 1.0 representing the
        thumb's position relative to the track's height. This mode is useful for
        scrolling custom, non-standard content.

    The scrollbar also supports a fade-in/fade-out effect, which can be enabled
    to hide the bar until the mouse hovers over it.
    """

    def __init__(self, parent, target_scroller=None, on_scroll=None,
                 track_color=wx.Colour(40, 40, 40), thumb_color=wx.Colour(100, 100, 100),
                 hidden=True):
        """
                The scrollbar's mode is determined by whether `target_scroller` or `on_scroll` is provided.
                These two parameters are mutually exclusive; providing one will cause a ValueError if the
                other is also provided.

                :param parent: The parent window for this scrollbar.
                :param target_scroller: (Optional) A `wx.ScrolledWindow` or similar object to be controlled.
                                        Required for 'target' mode.
                :param on_scroll: (Optional) A callable function that takes one argument, `scroll_ratio` (float),
                                  representing the thumb's vertical position from 0.0 to 1.0. Required for
                                  'callback' mode.
                :param track_color: (Optional) The color of the scrollbar's track. Can be a `wx.Colour` object
                                    or an RGB tuple. Defaults to a dark gray.
                :param thumb_color: (Optional) The color of the scrollbar's thumb. Can be a `wx.Colour` object
                                    or an RGB tuple. Defaults to a light gray.
                :param hidden: (Optional) A boolean indicating whether the scrollbar should be initially hidden
                               and fade in on mouse hover. Defaults to True.
                :return: None
                :raises ValueError: If both `target_scroller` and `on_scroll` are provided, or if neither is provided.
                """
        if (target_scroller is None) == (on_scroll is None):
            raise ValueError("Give either target_scroller or on_scroll (exactly one of them)")
        super().__init__(parent, size=wx.Size(parent.FromDIP(10), -1), style=wx.NO_BORDER)   # Width scaled for DPI

        # Determine mode based on parameters
        self.target_scroller = target_scroller
        self.on_scroll_callback = on_scroll
        self.mode = 'target' if target_scroller is not None else 'callback'

        # Ensure colors are wx.Colour objects
        self.track_color = self._ensure_color(track_color)
        self.thumb_color = self._ensure_color(thumb_color)

        self.hidden = hidden
        self.dragging = False
        self.drag_offset = 0

        # Smallest thumb, so it can still be grabbed with a lot of content (scaled for DPI)
        self.min_thumb_target = self.FromDIP(30)
        self.min_thumb_callback = self.FromDIP(20)

        # For callback mode
        self.thumb_pos = 0
        self.thumb_size = 50
        self.virtual_height = 1
        self.view_height = 1

        # Fade effect properties
        self.opacity = 0.0 if hidden else 1.0
        self.target_opacity = self.opacity
        self.fade_timer = wx.Timer(self)
        self.fade_step = 0.1
        self.leave_timer = wx.Timer(self)     # Callback mode: checks the mouse has really left, see on_mouse_leave

        # Overlay style: a thin rounded thumb that widens (and the track shows) while the mouse is over the bar itself
        # or the thumb is being dragged.  expand goes 0 (thin) to 1 (full width), animated by the fade timer.
        self.hovered = False
        self.expand = 0.0
        self.target_expand = 0.0
        self.expand_step = 0.2
        self.thin_width = self.FromDIP(4)
        self.margin = self.FromDIP(1)

        # Set background style for better painting
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)

        # Bind events
        self.Bind(wx.EVT_PAINT, self.on_paint)
        self.Bind(wx.EVT_LEFT_DOWN, self.on_mouse_down)
        self.Bind(wx.EVT_LEFT_UP, self.on_mouse_up)
        self.Bind(wx.EVT_MOTION, self.on_mouse_move)
        self.Bind(wx.EVT_MOUSE_CAPTURE_LOST, self.on_capture_lost)
        self.Bind(wx.EVT_TIMER, self.on_fade_timer, self.fade_timer)
        self.Bind(wx.EVT_TIMER, self._delayed_fade_check, self.leave_timer)
        self.Bind(wx.EVT_WINDOW_DESTROY, self.on_destroy)
        self.Bind(wx.EVT_ENTER_WINDOW, self.on_mouse_enter)
        self.Bind(wx.EVT_LEAVE_WINDOW, self.on_mouse_leave)

    # ------------------------------------------------------------------------------------------------------------------
    # The bar is only used with the mouse - it must never be a TAB stop (the control it scrolls handles the keys)
    def AcceptsFocus(self):
        return False

    def AcceptsFocusFromKeyboard(self):
        return False

    # ------------------------------------------------------------------------------------------------------------------
    def _ensure_color(self, color):
        """Ensure color is a wx.Colour object"""
        if isinstance(color, tuple):
            return wx.Colour(*color)
        elif isinstance(color, wx.Colour):
            return color
        else:
            return wx.Colour(color)

    # ------------------------------------------------------------------------------------------------------------------
    def _get_background_color(self):
        """The colour behind the scrollbar, which a faded scrollbar blends into"""
        parent = self.GetParent()
        if getattr(parent, 'bg_color', None) is not None:     # CustomTextCtrl
            return self._ensure_color(parent.bg_color)
        if getattr(parent, 'content', None) is not None:      # CustomScrolledPanel
            return parent.content.GetBackgroundColour()
        return parent.GetBackgroundColour()

    # ------------------------------------------------------------------------------------------------------------------
    def fade_in(self):
        """Start fading in the scrollbar"""
        self.target_opacity = 1.0
        if not self.fade_timer.IsRunning():
            self.fade_timer.Start(16)  # ~60 FPS

    # ------------------------------------------------------------------------------------------------------------------
    def fade_out(self):
        """Start fading out the scrollbar"""
        if not self.dragging:  # Don't fade out while dragging
            self.target_opacity = 0.0
            if not self.fade_timer.IsRunning():
                self.fade_timer.Start(16)  # ~60 FPS

    # ------------------------------------------------------------------------------------------------------------------
    def update_expand(self):
        """Widen the thumb while the mouse is over the bar or it is being dragged, else go back to thin"""
        self.target_expand = 1.0 if self.hovered or self.dragging else 0.0
        if self.expand != self.target_expand and not self.fade_timer.IsRunning():
            self.fade_timer.Start(16)  # ~60 FPS

    # ------------------------------------------------------------------------------------------------------------------
    @staticmethod
    def _step_towards(value, target, step):
        if abs(value - target) <= step:
            return target
        return value + step if value < target else value - step

    # ------------------------------------------------------------------------------------------------------------------
    def on_fade_timer(self, _event):
        """Handle the fade and widen / narrow animations"""
        self.opacity = self._step_towards(self.opacity, self.target_opacity, self.fade_step)
        self.expand = self._step_towards(self.expand, self.target_expand, self.expand_step)
        if self.opacity == self.target_opacity and self.expand == self.target_expand:
            self.fade_timer.Stop()
        self.Refresh()

    # ------------------------------------------------------------------------------------------------------------------
    def on_mouse_enter(self, event):
        self.hovered = True
        self.update_expand()
        if self.hidden:
            self.fade_in()
        event.Skip()

    # ------------------------------------------------------------------------------------------------------------------
    def on_mouse_leave(self, event):
        self.hovered = False
        self.update_expand()
        if self.hidden and not self.dragging:
            if self.mode == 'callback':
                # Use delayed fade check for callback mode
                self.leave_timer.StartOnce(50)
            elif not self.GetParent().GetScreenRect().Contains(wx.GetMousePosition()):
                self.fade_out()     # Off the whole control - moving onto its text keeps the bar showing
        event.Skip()

    # ------------------------------------------------------------------------------------------------------------------
    def _delayed_fade_check(self, _event):
        """Double-check mouse position before fading out (callback mode)"""
        if self.hidden and not self.dragging:
            mouse_pos = wx.GetMousePosition()
            scrollbar_rect = self.GetScreenRect()
            parent_rect = self.GetParent().GetScreenRect()

            if not scrollbar_rect.Contains(mouse_pos) and not parent_rect.Contains(mouse_pos):
                self.fade_out()

    # ------------------------------------------------------------------------------------------------------------------
    def apply_opacity(self, color, opacity, bg_color=None):
        """Apply opacity to a color by blending with background (looked up if not given)"""
        if bg_color is None:
            bg_color = self._get_background_color()
        color = self._ensure_color(color)

        r = int(bg_color.Red() * (1 - opacity) + color.Red() * opacity)
        g = int(bg_color.Green() * (1 - opacity) + color.Green() * opacity)
        b = int(bg_color.Blue() * (1 - opacity) + color.Blue() * opacity)
        return wx.Colour(r, g, b)

    # ------------------------------------------------------------------------------------------------------------------
    def on_paint(self, _event):
        # Buffered in both modes: the whole bar is redrawn, so an unbuffered paint flickers when it is refreshed every
        # frame of a smooth scroll
        dc = wx.AutoBufferedPaintDC(self)
        w, h = self.GetClientSize()
        bg_color = self._get_background_color()

        if self.opacity > 0:
            # The track only shows as the bar widens; the thumb lightens a little while hovered, more while dragged
            track_color = self.apply_opacity(self.track_color, self.opacity * self.expand, bg_color)
            lighten = 0.35 if self.dragging else 0.2 * self.expand
            thumb_color = self.apply_opacity(self.apply_opacity(wx.WHITE, lighten, self.thumb_color),
                                             self.opacity, bg_color)

            # Draw track
            dc.SetBrush(wx.Brush(track_color))
            dc.SetPen(wx.TRANSPARENT_PEN)
            dc.DrawRectangle(0, 0, w, h)

            # Calculate thumb position and size based on mode
            if self.mode == 'target':
                thumb_y, thumb_height, _max_scroll = self._target_geometry()
            else:
                thumb_y, thumb_height = self.thumb_pos, self.thumb_size

            # Draw thumb - rounded, from thin to the full width less a margin, centred
            if thumb_height < h:  # Only draw if scrolling is needed
                full_width = max(self.thin_width, w - 2 * self.margin)
                thumb_width = self.thin_width + (full_width - self.thin_width) * self.expand
                x = (w - thumb_width) / 2
                radius = thumb_width / 2
                gc = wx.GraphicsContext.Create(dc)
                if gc:
                    gc.SetBrush(wx.Brush(thumb_color))
                    gc.SetPen(wx.TRANSPARENT_PEN)
                    gc.DrawRoundedRectangle(x, thumb_y, thumb_width, thumb_height, radius)
                else:
                    dc.SetBrush(wx.Brush(thumb_color))
                    dc.DrawRoundedRectangle(int(x), thumb_y, int(thumb_width), thumb_height, int(radius))
        else:
            # When fully transparent, draw with background color
            dc.SetBrush(wx.Brush(bg_color))
            dc.SetPen(wx.TRANSPARENT_PEN)
            dc.DrawRectangle(0, 0, w, h)

    # ------------------------------------------------------------------------------------------------------------------
    def _target_geometry(self):
        """
        Thumb position and size for target mode, plus how far the target can scroll (all in pixels).
        The thumb travels over the track minus its own height, so it ends exactly at the bottom of the track
        when the target is scrolled to the end - the same mapping callback mode uses.

        :return: (thumb_y, thumb_height, max_scroll) - max_scroll is 0 when there is nothing to scroll
        """
        h = self.GetClientSize().height
        if not self.target_scroller or h <= 0:
            return 0, h, 0

        virtual = self.target_scroller.GetVirtualSize().height
        visible = self.target_scroller.GetClientSize().height
        max_scroll = virtual - visible
        if max_scroll <= 0:
            return 0, h, 0

        thumb_height = min(h, max(int(visible / virtual * h), self.min_thumb_target))
        scroll = min(self._target_scroll_pixels(), max_scroll)
        thumb_y = int(scroll / max_scroll * (h - thumb_height))

        return thumb_y, thumb_height, max_scroll

    # ------------------------------------------------------------------------------------------------------------------
    def _target_scroll_pixels(self):
        """The target's scroll position in pixels (GetViewStart is in scroll units)"""
        return self.target_scroller.GetViewStart()[1] * max(1, self.target_scroller.GetScrollPixelsPerUnit()[1])

    # ------------------------------------------------------------------------------------------------------------------
    def _scroll_target_to(self, pixels):
        """Scroll the target to a position in pixels (Scroll clamps it to the valid range)"""
        pixels_per_unit = max(1, self.target_scroller.GetScrollPixelsPerUnit()[1])
        self.target_scroller.Scroll(0, max(0, round(pixels / pixels_per_unit)))

    # ------------------------------------------------------------------------------------------------------------------
    def on_mouse_down(self, event):
        y = event.GetY()

        if self.mode == 'target':
            thumb_y, thumb_height, max_scroll = self._target_geometry()
            if max_scroll > 0:
                if thumb_y <= y < thumb_y + thumb_height:
                    # On the thumb: drag it from the point it was grabbed
                    self.dragging = True
                    self.drag_offset = y - thumb_y
                    if not self.HasCapture():
                        self.CaptureMouse()
                else:
                    # On the track: move one page towards the click
                    page = self.target_scroller.GetClientSize().height
                    current = self._target_scroll_pixels()
                    self._scroll_target_to(current - page if y < thumb_y else current + page)
                    self.Refresh()
        else:
            # Callback mode: check if clicking on thumb
            if self.thumb_pos <= y <= self.thumb_pos + self.thumb_size:
                self.dragging = True
                self.drag_offset = y - self.thumb_pos
                if not self.HasCapture():
                    self.CaptureMouse()
            elif self.virtual_height > self.view_height:
                # On the track: move one page towards the click
                h = self.GetClientSize().height
                travel = max(1, h - self.thumb_size)
                page = (self.view_height / (self.virtual_height - self.view_height)) * travel
                new_thumb_pos = self.thumb_pos - page if y < self.thumb_pos else self.thumb_pos + page
                self.thumb_pos = int(max(0, min(new_thumb_pos, travel)))
                self.on_scroll_callback(self.thumb_pos / travel)
                self.Refresh()

        # Keep scrollbar visible (and wide) while dragging
        self.update_expand()
        if self.hidden:
            self.fade_in()

    # ------------------------------------------------------------------------------------------------------------------
    def _drag_ended(self):
        """
        The mouse may have left the bar during the drag (no leave event while it was captured): narrow the bar if it
        is off the bar, and fade it out if it is off the whole control (the text box / list the bar belongs to)
        """
        self.dragging = False
        mouse = wx.GetMousePosition()
        self.hovered = self.GetScreenRect().Contains(mouse)
        self.update_expand()
        if self.hidden and not self.GetParent().GetScreenRect().Contains(mouse):
            self.fade_out()

    # ------------------------------------------------------------------------------------------------------------------
    def on_capture_lost(self, _event):
        """The mouse capture was taken away mid-drag (Alt-Tab, a dialog popping up...) - end the drag"""
        self._drag_ended()

    # ------------------------------------------------------------------------------------------------------------------
    def on_mouse_up(self, _event):
        if self.dragging:
            if self.HasCapture():
                self.ReleaseMouse()
            self._drag_ended()

    # ------------------------------------------------------------------------------------------------------------------
    def on_mouse_move(self, event):
        if self.dragging and event.Dragging() and event.LeftIsDown():
            y = event.GetY()

            if self.mode == 'target':
                # Target mode: map the thumb's travel over the track onto the target's scroll range
                _thumb_y, thumb_height, max_scroll = self._target_geometry()
                travel = self.GetClientSize().height - thumb_height
                if max_scroll > 0 and travel > 0:
                    pos = max(0, min(y - self.drag_offset, travel))
                    self._scroll_target_to(pos / travel * max_scroll)
            else:
                # Callback mode: update thumb position and call callback
                new_thumb_pos = y - self.drag_offset
                h = self.GetClientSize().height
                new_thumb_pos = max(0, min(new_thumb_pos, h - self.thumb_size))
                self.thumb_pos = new_thumb_pos

                scroll_ratio = self.thumb_pos / max(1, h - self.thumb_size)
                self.on_scroll_callback(scroll_ratio)

            self.Refresh()

    # ------------------------------------------------------------------------------------------------------------------
    def set_colors(self, thumb_color, track_color):
        """Update scrollbar colors"""
        self.thumb_color = self._ensure_color(thumb_color)
        self.track_color = self._ensure_color(track_color)
        self.Refresh()

    # ------------------------------------------------------------------------------------------------------------------
    # Methods for callback mode
    def update(self, view_height, virtual_height, scroll_position):
        """Update scrollbar state (callback mode only)"""
        if self.mode != 'callback':
            return

        self.view_height = view_height
        self.virtual_height = virtual_height

        h = self.GetClientSize().height
        if virtual_height <= view_height:
            self.thumb_size = h
            self.thumb_pos = 0
        else:
            self.thumb_size = max(self.min_thumb_callback, int(h * (view_height / virtual_height)))
            max_thumb_pos = h - self.thumb_size
            # Convert scroll_position (negative) to positive scroll amount
            scroll_amount = abs(scroll_position)
            max_scroll = virtual_height - view_height
            if max_scroll > 0:
                self.thumb_pos = int((scroll_amount / max_scroll) * max_thumb_pos)
            else:
                self.thumb_pos = 0

        self.Refresh()

    # ------------------------------------------------------------------------------------------------------------------
    # Methods for target mode
    def scroll_to_bottom(self):
        """Scroll target to bottom (target mode only)"""
        if self.mode != 'target' or not self.target_scroller:
            return

        vsz = self.target_scroller.GetVirtualSize()
        client_size = self.target_scroller.GetClientSize()
        scroll_range = max(0, vsz.height - client_size.height)
        self.target_scroller.Scroll(0, scroll_range)
        self.Refresh()

    # ------------------------------------------------------------------------------------------------------------------
    def scroll_to_top(self):
        """Scroll target to top (target mode only)"""
        if self.mode != 'target' or not self.target_scroller:
            return

        self.target_scroller.Scroll(0, 0)
        self.Refresh()

    # ------------------------------------------------------------------------------------------------------------------
    def on_destroy(self, event):
        if event.GetEventObject() is self:
            self.fade_timer.Stop()
            self.leave_timer.Stop()
        event.Skip()

# Usage examples:

# Target mode (as CustomTextCtrl uses it) - scrolls a wx.ScrolledWindow:
# scrollbar = UnifiedScrollbar(parent, target_scroller=my_scrolled_window)

# Callback mode (as CustomScrolledPanel uses it) - reports the thumb position, call update() when the content changes:
# def handle_scroll(ratio):
#     # Scroll the content to ratio (0.0 = top, 1.0 = bottom)
#     pass
# scrollbar = UnifiedScrollbar(parent, on_scroll=handle_scroll)
