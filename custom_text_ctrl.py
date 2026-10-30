#!/usr/bin/env python3

# ----------------------------------------------------------------------------------------------------------------------
# custom_text_ctrl.py

"""
Custom text ctrl with smooth scrolling implementation and fade scrollbar
"""

import wx

import custom_scrollbar


class CustomTextCtrl(wx.Panel):
    """
    Custom multiline text control with smooth scrolling and URL support
    """

    def __init__(self, parent, id=wx.ID_ANY, value='', style=0, hidden=True, *args, **kwargs):
        super().__init__(parent, id=id, *args, **kwargs)

        self.read_only = bool(style & wx.TE_READONLY)
        self.no_border = bool(style & wx.NO_BORDER)
        self.auto_url = bool(style & wx.TE_AUTO_URL)  # Check for URL detection flag
        self.word_wrap = bool(style & wx.TE_WORDWRAP)
        self.hidden = hidden
        self.max_lines = 0          # 0 = no limit, see SetMaxLines
        self.max_line_width = 0     # Widest line in pixels (no word wrap), so AppendText only measures the new lines
        self.updating_text = False  # This code is changing the text itself - on_text_change has nothing to do

        # Set border width
        self.border_width = 0 if self.no_border else self.FromDIP(2)

        self.bg_color = wx.Colour(30, 30, 30)
        self.fg_color = wx.Colour(220, 220, 220)
        self.track_color = wx.Colour(40, 40, 40)
        self.thumb_color = wx.Colour(100, 100, 100)
        self.border_color = wx.Colour(150, 150, 150)    # See SetBorderColour

        # Layout components with smaller scroll rate
        self.scrolled_area = wx.ScrolledWindow(self, style=wx.BORDER_NONE)
        self.scrolled_area.SetScrollRate(0, 1)  # 1 pixel per scroll unit for smooth scrolling
        self.scrolled_area.ShowScrollbars(wx.SHOW_SB_NEVER, wx.SHOW_SB_NEVER)
        self.scrolled_area.SetBackgroundColour(self.bg_color)

        # Create the actual text control for editing
        text_style = wx.TE_MULTILINE | wx.BORDER_NONE | wx.TE_NO_VSCROLL
        if self.read_only:
            text_style |= wx.TE_READONLY
        if self.auto_url:
            text_style |= wx.TE_AUTO_URL  # Enable URL detection on the underlying control

        self.text = wx.TextCtrl(self.scrolled_area, style=text_style)
        self.text.SetForegroundColour(self.fg_color)
        self.text.SetBackgroundColour(self.bg_color)
        self.text.SetPosition(wx.Point(0, 0))

        # Bind mouse wheel for smooth scrolling to both scrolled_area and text control
        self.scrolled_area.Bind(wx.EVT_MOUSEWHEEL, self.on_mouse_wheel)
        self.text.Bind(wx.EVT_MOUSEWHEEL, self.on_mouse_wheel)

        # Bind text events
        self.text.Bind(wx.EVT_TEXT, self.on_text_change)

        self.text.Bind(wx.EVT_TEXT_PASTE, self.on_paste)
        self.text.Bind(wx.EVT_KEY_DOWN, self.on_key_down)

        self.scrollbar = custom_scrollbar.UnifiedScrollbar(self, target_scroller=self.scrolled_area, track_color=self.track_color,
                                               thumb_color=self.thumb_color, hidden=self.hidden)

        self.sizer = wx.BoxSizer(wx.HORIZONTAL)
        # Add border space around the components
        self.sizer.Add(self.scrolled_area, 1, wx.EXPAND | wx.ALL, self.border_width)
        self.sizer.Add(self.scrollbar, 0, wx.EXPAND | wx.TOP | wx.BOTTOM | wx.RIGHT, self.border_width)
        self.SetSizer(self.sizer)

        self.Bind(wx.EVT_SIZE, self.on_resize)
        self.scrolled_area.Bind(wx.EVT_SCROLLWIN, self.on_scroll)

        self.Bind(wx.EVT_PAINT, self.on_paint)

        # Animation timer for smooth scrolling
        self.scroll_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.on_scroll_timer)
        self.Bind(wx.EVT_WINDOW_DESTROY, self.on_destroy)
        self.target_scroll_pos = 0
        self.current_scroll_pos = 0
        self.scroll_speed = 0.25

        # Bind mouse events for fade effect
        if self.hidden:
            self.Bind(wx.EVT_ENTER_WINDOW, self.on_mouse_enter)
            self.Bind(wx.EVT_LEAVE_WINDOW, self.on_mouse_leave)
            self.scrolled_area.Bind(wx.EVT_ENTER_WINDOW, self.on_mouse_enter)
            self.scrolled_area.Bind(wx.EVT_LEAVE_WINDOW, self.on_mouse_leave)
            self.text.Bind(wx.EVT_ENTER_WINDOW, self.on_mouse_enter)
            self.text.Bind(wx.EVT_LEAVE_WINDOW, self.on_mouse_leave)

        self.text_content = value
        if value != '':
            self.SetValue(value)

    def on_mouse_enter(self, event):
        if self.hidden:
            self.scrollbar.fade_in()
        event.Skip()

    def on_mouse_leave(self, event):
        if self.hidden:
            # Check if mouse is really leaving the control area
            mouse_pos = wx.GetMousePosition()
            control_rect = self.GetScreenRect()
            if not control_rect.Contains(mouse_pos):
                self.scrollbar.fade_out()
        event.Skip()

    def on_paste(self, event):
        """Make the text control big enough for the clipboard text before it is pasted (see _update_display)"""
        data = wx.TextDataObject()
        if not self.read_only and wx.TheClipboard.Open():
            got_text = wx.TheClipboard.GetData(data)
            wx.TheClipboard.Close()
            if got_text:
                lines = data.GetText().split('\n')
                dc = wx.ClientDC(self.text)
                dc.SetFont(self.text.GetFont())
                size = self.text.GetSize()
                width = size.width if self.word_wrap else max(size.width,
                                                              max(dc.GetTextExtent(line)[0] for line in lines) + 20)
                # Count each pasted line as two in case it wraps
                self.text.SetSize(wx.Size(width, size.height + 2 * len(lines) * self.text.GetCharHeight()))
        event.Skip()

    # Events that only the inner text control receives (it has the mouse and the keyboard focus, this panel doesn't),
    # so Bind sends handlers for them there.  The URL event's object is then the inner control, which has GetRange.
    TEXT_EVENTS = (wx.EVT_TEXT_URL,
                   wx.EVT_LEFT_DOWN, wx.EVT_LEFT_UP, wx.EVT_LEFT_DCLICK,
                   wx.EVT_RIGHT_DOWN, wx.EVT_RIGHT_UP, wx.EVT_RIGHT_DCLICK,
                   wx.EVT_MIDDLE_DOWN, wx.EVT_MIDDLE_UP, wx.EVT_MIDDLE_DCLICK,
                   wx.EVT_MOTION, wx.EVT_CONTEXT_MENU,
                   wx.EVT_KEY_DOWN, wx.EVT_KEY_UP, wx.EVT_CHAR,
                   wx.EVT_SET_FOCUS, wx.EVT_KILL_FOCUS)

    def Bind(self, event_type, handler, source=None, id=wx.ID_ANY, id2=wx.ID_ANY):
        """Override Bind to route the text control's own events (TEXT_EVENTS) to it."""
        if event_type in self.TEXT_EVENTS:
            self.text.Bind(event_type, handler, source, id, id2)
        else:
            super().Bind(event_type, handler, source, id, id2)

    def SetScrollbarTrackColor(self, track_color):
        """
        Set the track color of the scrollbar

        :param track_color:     The color to apply to the track
        """
        self.track_color = track_color
        self.scrollbar.set_colors(self.thumb_color, self.track_color)   # Converts tuples, repaints the scrollbar

    def SetScrollbarThumbColor(self, thumb_color):
        """
        Set the slider color of the scrollbar

        :param thumb_color:     The color to apply to the slider
        """
        self.thumb_color = thumb_color
        self.scrollbar.set_colors(self.thumb_color, self.track_color)

    def on_mouse_wheel(self, event):
        """Handle mouse wheel with smooth scrolling"""
        # Scroll by the system setting (lines per notch, or a page) using the text's line height
        if event.IsPageScroll():
            step = self.scrolled_area.GetClientSize().height
        else:
            step = event.GetLinesPerAction() * self.text.GetCharHeight()
        scroll_pixels = int(event.GetWheelRotation() / max(1, event.GetWheelDelta()) * step)
        self.scroll_smoothly_by(-scroll_pixels)     # Subtract for correct direction

    PAGE_UP_KEYS = (wx.WXK_PAGEUP, wx.WXK_NUMPAD_PAGEUP)
    PAGE_DOWN_KEYS = (wx.WXK_PAGEDOWN, wx.WXK_NUMPAD_PAGEDOWN)

    def on_key_down(self, event):
        """
        Keyboard scrolling.  The text control is as tall as its text (the scrolled area around it does the
        scrolling), so its own page / line keys don't move the view.
        Read-only: Up / Down scroll a line, Page Up / Down a page, Home / End (with or without CTRL) go to the top /
        end.  Editable: Page Up / Down move the caret a page and the view with it; every other key is handled by the
        text control as usual and the view then follows the caret.  SHIFT (selecting) keys always just follow the caret.
        """
        key = event.GetKeyCode()
        plain = not (event.ShiftDown() or event.AltDown())
        line = self.text.GetCharHeight()
        page_lines = max(1, self.scrolled_area.GetClientSize().height // line - 1)     # One line of overlap

        if plain and key in self.PAGE_UP_KEYS + self.PAGE_DOWN_KEYS:
            # Whole lines, so the caret and the view move together
            direction = -1 if key in self.PAGE_UP_KEYS else 1
            if not self.read_only:
                self._move_caret_lines(direction * page_lines)
            self.scroll_smoothly_by(direction * page_lines * line)
            return

        if self.read_only and plain:
            if key in (wx.WXK_UP, wx.WXK_NUMPAD_UP, wx.WXK_DOWN, wx.WXK_NUMPAD_DOWN) and not event.ControlDown():
                self.scroll_smoothly_by(-line if key in (wx.WXK_UP, wx.WXK_NUMPAD_UP) else line)
                return
            if key in (wx.WXK_HOME, wx.WXK_NUMPAD_HOME, wx.WXK_END, wx.WXK_NUMPAD_END):
                to_end = key in (wx.WXK_END, wx.WXK_NUMPAD_END)
                self.text.SetInsertionPoint(self.text.GetLastPosition() if to_end else 0)
                self.scroll_smoothly_to(self.scrolled_area.GetVirtualSize().height if to_end else 0)
                return

        event.Skip()
        wx.CallAfter(self.show_caret)       # Once the text control has moved the caret

    def _move_caret_lines(self, lines):
        """Move the caret up (negative) or down by a number of lines, keeping its column where it can"""
        found, column, row = self.text.PositionToXY(self.text.GetInsertionPoint())
        if found:
            row = max(0, min(row + lines, self.text.GetNumberOfLines() - 1))
            self.text.SetInsertionPoint(self.text.XYToPosition(min(column, self.text.GetLineLength(row)), row))

    def show_caret(self):
        """Scroll so the caret (insertion point) is in view"""
        if not self:                        # Closed before this ran
            return
        line = self.text.GetCharHeight()
        position = self.text.GetInsertionPoint()
        if self.word_wrap:
            y = self.text.PositionToCoords(position).y      # From the top of the text
        else:
            # Without word wrap every line is one line high.  (PositionToCoords isn't needed, and GTK gives (0, 0) for
            # it until the text has been drawn)
            found, _column, row = self.text.PositionToXY(position)
            y = row * line if found else -1
        if y < 0:
            return
        view_y = self.scrolled_area.GetViewStart()[1]
        client_h = self.scrolled_area.GetClientSize().height
        if y < view_y:
            target = y
        elif y + line > view_y + client_h:
            target = y + line - client_h
        else:
            return
        self.scroll_timer.Stop()
        self.scrolled_area.Scroll(0, target)
        self.scrollbar.Refresh()

    def scroll_smoothly_by(self, pixels):
        """
        Start (or extend) the smooth scrolling animation.  It carries on from where a running animation is heading,
        so quick wheel notches / key presses add up.
        """
        current_pos = self.scrolled_area.GetViewStart()[1]
        start_pos = self.target_scroll_pos if self.scroll_timer.IsRunning() else current_pos
        self.scroll_smoothly_to(start_pos + pixels)

    def scroll_smoothly_to(self, position):
        """Smoothly scroll to position (pixels from the top), kept in the valid range"""
        virtual_size = self.scrolled_area.GetVirtualSize().GetHeight()
        client_size = self.scrolled_area.GetClientSize().GetHeight()
        max_scroll = max(0, virtual_size - client_size)
        self.target_scroll_pos = max(0, min(position, max_scroll))

        # Start smooth scrolling animation
        if not self.scroll_timer.IsRunning():
            self.current_scroll_pos = self.scrolled_area.GetViewStart()[1]
            self.scroll_timer.Start(16)  # ~60 FPS

    def on_destroy(self, event):
        # A timer left running past its owner's destruction delivers its queued WM_TIMER
        # to a freed window, which corrupts the heap as the app shuts down.
        if self.scroll_timer.IsRunning():
            self.scroll_timer.Stop()
        event.Skip()

    def on_scroll_timer(self, event):
        """Animate smooth scrolling"""
        diff = self.target_scroll_pos - self.current_scroll_pos
        if abs(diff) < 1:
            self.current_scroll_pos = self.target_scroll_pos
            self.scroll_timer.Stop()
        else:
            self.current_scroll_pos += diff * self.scroll_speed

        self.scrolled_area.Scroll(0, int(self.current_scroll_pos))
        self.scrollbar.Refresh()    # Every frame, so the thumb moves with the text (the scrollbar paints buffered)

    def on_text_change(self, event):
        """Handle text changes and update display"""
        # Always allow the text change to happen in the control
        # We only block it at the input level (keyboard/paste events)
        if not self.updating_text:
            self.text_content = self.text.GetValue()
            self._update_display()
            if not self.read_only:
                wx.CallAfter(self.show_caret)       # The user typed or pasted (the right-click menu too)
        event.Skip()

    def SetValue(self, value):
        # The EVT_TEXT this sends still reaches the parent (as with wx.TextCtrl.SetValue), but on_text_change leaves
        # the display alone - it is updated once below
        self.text_content = str(value)
        self.updating_text = True
        try:
            self.text.SetValue(self.text_content)
        finally:
            self.updating_text = False
        self._update_display()

    def GetValue(self):
        return self.text.GetValue()

    def WriteText(self, text):
        self.text.WriteText(text)
        self.text_content = self.text.GetValue()
        self._update_display()

    def IsEmpty(self):
        return self.text.IsEmpty()

    def GetLastPosition(self):
        return self.text.GetLastPosition()

    def IsEditable(self):
        return not self.read_only

    def SetEditable(self, editable):
        # Read-only is enforced by the text control itself: it stops the user typing, cutting and pasting (including
        # the right-click menu) while SetValue / AppendText / WriteText from the code still work
        self.read_only = not editable
        self.text.SetEditable(editable)
        self._update_display()     # Editable boxes are given spare height

    def GetNumberOfLines(self):
        return self.text.GetNumberOfLines()

    GetLineCount = GetNumberOfLines     # The old name

    def IsModified(self):
        return self.text.IsModified()

    def SetInsertionPoint(self, pos):
        """Set cursor position"""
        self.text.SetInsertionPoint(pos)

    def GetInsertionPoint(self):
        """Get cursor position"""
        return self.text.GetInsertionPoint()

    def SetSelection(self, start, end):
        """Set text selection"""
        self.text.SetSelection(start, end)

    def GetSelection(self):
        """Get text selection"""
        return self.text.GetSelection()

    def SelectAll(self):
        """Select all text"""
        self.text.SelectAll()

    def CanCopy(self):
        """Check if text can be copied"""
        return self.text.CanCopy()

    def CanCut(self):
        """Check if text can be cut"""
        return self.text.CanCut()

    def CanPaste(self):
        """Check if text can be pasted"""
        return self.text.CanPaste()

    def Copy(self):
        """Copy selected text"""
        self.text.Copy()

    def Cut(self):
        """Cut selected text"""
        self.text.Cut()
        self.text_content = self.text.GetValue()
        self._update_display()

    def Paste(self):
        """Paste text from clipboard"""
        self.text.Paste()
        self.text_content = self.text.GetValue()
        self._update_display()

    def _update_display(self, appended_text=None):
        """
        Size the text control to its content and set the scrolled area to match.

        :param appended_text: The text just added to the end by AppendText - only the lines it touched are measured
        """
        available_width = max(100, self.GetSize().width - self.scrollbar.GetSize().width - 10)

        line_height = self.text.GetCharHeight()

        if self.word_wrap:
            text_width = available_width
            # Set a tall height first so wx can calculate wrapped line count
            self.text.SetSize(wx.Size(text_width, 32000))
            self.text.Update()
            line_count = max(1, self.text.GetNumberOfLines())
        else:
            dc = wx.ClientDC(self.text)
            dc.SetFont(self.text.GetFont())
            current_value = self.text_content     # Kept the same as the control's text, and quicker than GetValue
            if appended_text is not None:
                # The appended text can carry on the line that was last, so measure that whole line plus the new
                # ones.  (Lines trimmed off the top can leave max_line_width a little wide, which does no harm)
                parts = current_value.rsplit('\n', appended_text.count('\n'))
                touched = [parts[0].rsplit('\n', 1)[-1]] + parts[1:]
                self.max_line_width = max([self.max_line_width] + [dc.GetTextExtent(line)[0] for line in touched])
            elif current_value:
                self.max_line_width = max(dc.GetTextExtent(line)[0] for line in current_value.split("\n"))
            else:
                self.max_line_width = 100
            text_width = max(available_width - 20, self.max_line_width + 20)
            # Count from the text itself so Clear / SetValue / typing are always reflected (no wrapping here, the
            # control is made wider than the longest line)
            line_count = current_value.count('\n') + 1

        content_height = line_count * line_height

        # An editable box gets a page of spare height below the text: on Windows the edit control (created without
        # auto scroll because of TE_NO_VSCROLL) drops typing, ENTER and pastes that don't fit its height.  The spare
        # is outside the virtual size below, so it can't be scrolled to
        control_height = content_height
        if not self.read_only:
            control_height += max(self.scrolled_area.GetClientSize().height, 5 * line_height)
        self.text.SetSize(wx.Size(text_width, control_height))
        x, y = self.scrolled_area.CalcScrolledPosition(0, 0)
        self.text.SetPosition(wx.Point(x, y))
        self.scrolled_area.SetVirtualSize(wx.Size(text_width, content_height))
        self.text.Update()
        self.scrolled_area.Update()

    def SetMaxLines(self, max_lines: int) -> None:
        """
        Keep only the last max_lines lines when text is appended (0 = keep everything).  Once there are more, the
        oldest lines are dropped down to 90% of max_lines in one go (see AppendText).
        """
        self.max_lines = max_lines

    def AppendText(self, new_text):
        # Only follow the new text if the view is at the end already (within a line) - someone scrolled up to read
        # earlier text keeps their place.  A wheel scroll still moving counts from where it is heading.
        area = self.scrolled_area
        line_height = self.text.GetCharHeight()
        view_y = self.target_scroll_pos if self.scroll_timer.IsRunning() else area.GetViewStart()[1]
        at_end = view_y + area.GetClientSize().height >= area.GetVirtualSize().height - line_height

        # Add to the end of the control rather than setting the whole text again, which took ~50 ms per message once
        # the Messages window was full
        old_line_count = self.text_content.count('\n')
        self.text_content += new_text
        excess = self.text_content.count('\n') - self.max_lines if self.max_lines else 0
        if excess > 0:
            # Drop the oldest lines so the text doesn't grow for ever.  Removing text from the start costs as much
            # as setting the whole text (~45 ms for 5000 lines in a Windows edit control), so drop an extra tenth
            # of max_lines while at it - the next trim is then that many appends away
            excess += self.max_lines // 10
            self.text_content = self.text_content.split('\n', excess)[-1]

        self.updating_text = True
        try:
            if self.word_wrap or excess > old_line_count:
                # Word wrap sizes the control from its own (wrapped) text, so give it the text first
                self.text.SetValue(self.text_content)
                self._update_display()
            else:
                # Size the control for the new text first: on Windows the edit control (created without auto scroll
                # because of TE_NO_VSCROLL) silently drops text that doesn't fit its height
                self._update_display(new_text)
                if excess > 0:
                    # The position comes from the control: on Windows a line break can count as two positions
                    self.text.Remove(0, self.text.XYToPosition(0, excess))
                self.text.AppendText(new_text)
            self.text.SetInsertionPointEnd()
        finally:
            self.updating_text = False

        content_height = self.scrolled_area.GetVirtualSize().height    # Just set by _update_display
        client_h = self.scrolled_area.GetClientSize().height
        max_scroll = max(0, content_height - client_h)
        if at_end:
            scroll_to = max_scroll
            self.scroll_timer.Stop()
        else:
            # Keep the same text in view: lines dropped off the top moved it up
            removed = max(0, excess) * line_height
            if self.scroll_timer.IsRunning():
                # Let the wheel scroll carry on, shifted the same way
                self.target_scroll_pos = max(0, min(self.target_scroll_pos - removed, max_scroll))
                self.current_scroll_pos = max(0, min(self.current_scroll_pos - removed, max_scroll))
                scroll_to = int(self.current_scroll_pos)
            else:
                scroll_to = max(0, min(view_y - removed, max_scroll))

        self.scrolled_area.Scroll(0, scroll_to)
        x, y = self.scrolled_area.CalcScrolledPosition(0, 0)
        self.text.SetPosition(wx.Point(x, y))
        self.scrolled_area.Update()
        self.scrollbar.Refresh()

    def ShowPosition(self, pos: int):
        """
        Mimic wx.TextCtrl.ShowPosition for this wrapped control.
        For start/end we use the *same* logic as the custom scrollbar so the
        result is identical to dragging the thumb to the top/bottom.
        """
        last = self.text.GetLastPosition()
        pos = max(0, min(pos, last))

        # exact behaviors you asked for
        if pos == 0:
            self.scrollbar.scroll_to_top()  # uses scrolled_area.Scroll(0, 0)
            return
        if pos == last:
            # identical to dragging the custom scrollbar all the way down
            self.scrollbar.scroll_to_bottom()  # uses virtual_size - client_size
            return

        # (optional) middle positions: keep caret at pos and center it roughly
        self.text.SetInsertionPoint(pos)
        vsz_h = self.scrolled_area.GetVirtualSize().GetHeight()
        cli_h = self.scrolled_area.GetClientSize().GetHeight()
        # If you ever need true pixel mapping, you can drop in a y-from-pos here.
        target = max(0, min(self.scrolled_area.GetViewStart()[1], max(0, vsz_h - cli_h)))
        self.scrolled_area.Scroll(0, target)
        self.scrollbar.Refresh()

    def ShowStart(self):
        self.scroll_timer.Stop()        # A wheel scroll still moving would carry on from where it was heading
        self.scrollbar.scroll_to_top()

    def ShowEnd(self):
        self.scroll_timer.Stop()
        self.scrollbar.scroll_to_bottom()

    def Clear(self):
        self.text.Clear()
        self.text_content = ""
        self._update_display()
        self.scrolled_area.Scroll(0, 0)
        self.scrollbar.Refresh()

    def CopyAll(self):
        if wx.TheClipboard.Open():
            wx.TheClipboard.SetData(wx.TextDataObject(self.text.GetValue()))
            wx.TheClipboard.Close()

    def SetBackgroundColour(self, colour):
        self.bg_color = colour
        self.scrolled_area.SetBackgroundColour(colour)
        self.text.SetBackgroundColour(colour)
        if wx.Platform == '__WXGTK__':
            # wxGTK also puts the background colour into the multiline control's default text style, so text that is
            # already there keeps the colour it was inserted with and only the empty areas change (e.g. the alert
            # flash only flashed around the text).  Re-style the existing text so all of it takes the new colour.
            self.text.SetStyle(0, self.text.GetLastPosition(), wx.TextAttr(self.fg_color, colour))
        self.scrollbar.SetBackgroundColour(colour)
        changed = super().SetBackgroundColour(colour)
        self.Refresh()
        return changed

    def SetForegroundColour(self, colour):
        self.fg_color = colour
        self.text.SetForegroundColour(colour)
        changed = super().SetForegroundColour(colour)
        self.Refresh()
        return changed

    def SetFont(self, font):
        self.text.SetFont(font)
        self._update_display()

    def GetFont(self):
        return self.text.GetFont()

    def SetScrollbarColor(self, thumb_color, track_color):
        self.thumb_color = thumb_color
        self.track_color = track_color
        self.scrollbar.set_colors(thumb_color, track_color)

    def on_scroll(self, event):
        self.scrollbar.Refresh()
        event.Skip()

    def on_resize(self, event):
        self.Layout()  # sizer layout first
        if hasattr(self, 'text') and self.text.GetValue():
            self._update_display()  # then set virtual size
        self.scrollbar.Refresh()
        event.Skip()

    def on_paint(self, event):
        if not self.no_border:
            # The text and scrollbar sit border_width in from the edges (see the sizer) - fill that margin along the
            # four edges (not the gap between the text and the scrollbar)
            dc = wx.PaintDC(self)
            dc.SetPen(wx.TRANSPARENT_PEN)
            dc.SetBrush(wx.Brush(self.border_color))
            w, h = self.GetClientSize()
            b = self.border_width
            for rect in ((0, 0, w, b), (0, h - b, w, b), (0, 0, b, h), (w - b, 0, b, h)):
                dc.DrawRectangle(*rect)

        event.Skip()

    def SetBorderColour(self, colour):
        """Set the colour of the border (not drawn with the NO_BORDER style)"""
        self.border_color = colour
        self.Refresh()


# Demo usage
if __name__ == "__main__":
    app = wx.App(False)


    class TestFrame(wx.Frame):
        def __init__(self):
            super().__init__(None, title="Custom Text Control with Fade Scrollbar", size=wx.Size(600, 400))

            panel = wx.Panel(self)
            sizer = wx.BoxSizer(wx.HORIZONTAL)

            # Create text control with hidden scrollbar (fades in/out)
            self.text_ctrl_hidden = CustomTextCtrl(panel,
                                                   value="This is a test text control with a hidden scrollbar that fades in on hover.\n" * 20,
                                                   hidden=True)

            # Create text control with always visible scrollbar
            self.text_ctrl_visible = CustomTextCtrl(panel,
                                                    value="This is a test text control with an always visible scrollbar.\n" * 20,
                                                    hidden=False)

            sizer.Add(self.text_ctrl_hidden, 1, wx.EXPAND | wx.ALL, 5)
            sizer.Add(self.text_ctrl_visible, 1, wx.EXPAND | wx.ALL, 5)

            panel.SetSizer(sizer)
            self.Show()


    TestFrame()
    app.MainLoop()