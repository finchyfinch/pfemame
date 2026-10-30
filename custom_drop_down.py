#!/usr/bin/env python3

# ----------------------------------------------------------------------------------------------------------------------
# custom_drop_down.py

"""
This is my custom drop-down box with full control over background and foreground colors
"""

import time

import wx
import wx.lib.newevent

from functions import set_up_language

_ = set_up_language()  # Set up the application language

# Custom event for selection change
DropdownSelectionEvent, EVT_DROPDOWN_SELECTION = wx.lib.newevent.NewEvent()


class ModernDropdown(wx.Panel):
    """
    A modern, customizable dropdown component with full theme support.
    Drop-in replacement for wx.ComboBox with enhanced styling.
    """

    def __init__(self, parent, id=wx.ID_ANY, value="", pos=wx.DefaultPosition,
                 size=wx.DefaultSize, choices=None, style=0, name="ModernDropdown"):
        super().__init__(parent, id, pos, size, style, name)

        # Tooltip, see UpdateToolTip
        self.app_tooltip = ''
        self.applied_tooltip = ''

        # Initialize choices
        self.choices = choices or []
        self.selected_index = -1
        self.current_value = value
        self.hint = _('Select an option...')  # Shown while there is no value, see SetHint

        # Dropdown state
        self.is_dropdown_open = False
        self.dropdown_popup = None
        self.popup_dismissed_at = 0.0   # When a click outside last closed the popup, see OnLeftDown
        self.typed = ''                 # Type-ahead, see OnChar
        self.typed_at = 0.0

        # Store the size
        self.size = size

        # Theme colours set by the application (SetScrollbarColor, SetAccentColour) - these win over the colours
        # worked out from the background / foreground (GenerateThemeColors)
        self.color_overrides = {}

        # Initialize with default system colors
        self.SetBackgroundColour(wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOW))
        self.SetForegroundColour(wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOWTEXT))

        # UI state
        self.is_hovered = False
        self.is_focused = False
        self.arrow_hovered = False

        # Measurements - scaled for the screen's DPI like the rest of the app (lines stay 1 pixel)
        self.border_width = 1
        self.corner_radius = self.FromDIP(6)
        self.arrow_size = self.FromDIP(8)
        self.padding = self.FromDIP(8)
        self.item_height = self.FromDIP(32)       # Rows in the popup list
        self.popup_max_height = self.FromDIP(400)
        self.popup_min_width = self.FromDIP(150)
        self.popup_scrollbar_width = self.FromDIP(12)
        self.popup_text_x = self.FromDIP(24)      # Item text inset in the list, after the check mark column

        # Setup and bind the UI
        self.SetupUI()
        self.BindEvents()

    def DoGetBestSize(self):
        """Return the best size for the control"""
        # Calculate based on font and content
        font_height = self.GetTextExtent("Ag")[1]
        best_height = font_height + (self.padding * 2) + (self.border_width * 2) + 4

        # Calculate width based on longest choice
        best_width = self.FromDIP(120)  # Minimum width
        if self.choices:
            for choice in self.choices:
                text_width = self.GetTextExtent(choice)[0]
                content_width = text_width + (self.padding * 2) + self.arrow_size + self.FromDIP(16)
                best_width = max(best_width, content_width)

        # If explicit size was provided, use it instead of calculated size
        if self.size != wx.DefaultSize:
            if self.size.width != -1:
                best_width = self.size.width
            if self.size.height != -1:
                best_height = self.size.height

        return wx.Size(best_width, best_height)

    def SetupUI(self):
        """Initialize the UI components"""
        self.SetBackgroundStyle(wx.BG_STYLE_CUSTOM)

        # Set initial value if provided
        if self.current_value and self.current_value in self.choices:
            self.selected_index = self.choices.index(self.current_value)

    def BindEvents(self):
        """Bind all necessary events"""
        self.Bind(wx.EVT_PAINT, self.OnPaint)
        self.Bind(wx.EVT_SIZE, self.OnSize)
        self.Bind(wx.EVT_LEFT_DOWN, self.OnLeftDown)
        self.Bind(wx.EVT_ENTER_WINDOW, self.OnMouseEnter)
        self.Bind(wx.EVT_LEAVE_WINDOW, self.OnMouseLeave)
        self.Bind(wx.EVT_MOTION, self.OnMouseMotion)
        self.Bind(wx.EVT_SET_FOCUS, self.OnSetFocus)
        self.Bind(wx.EVT_KILL_FOCUS, self.OnKillFocus)
        # CHAR_HOOK comes before a dialog uses the arrow keys / TAB to move between controls (and before a window's
        # own CHAR_HOOK closes it on ESC) - keys OnKeyDown doesn't use carry on as usual
        self.Bind(wx.EVT_CHAR_HOOK, self.OnKeyDown)
        self.Bind(wx.EVT_CHAR, self.OnChar)

    def SetHint(self, hint: str):
        """Set the text shown (greyed) while the dropdown has no value - like wx.ComboBox.SetHint"""
        self.hint = hint
        self.Refresh()

    def GetHint(self) -> str:
        return self.hint

    def SetBackgroundColour(self, colour):
        """Override to update theme colors when background changes"""
        super().SetBackgroundColour(colour)
        self.UpdateThemeColors()
        self.Refresh()
        return True

    def SetForegroundColour(self, colour):
        """Override to update theme colors when foreground changes"""
        super().SetForegroundColour(colour)
        self.UpdateThemeColors()
        self.Refresh()
        return True

    def UpdateThemeColors(self):
        """Update theme colors based on current background/foreground colors"""
        bg_color = self.GetBackgroundColour()
        fg_color = self.GetForegroundColour()

        # Determine if we're in dark mode by checking background brightness
        bg_brightness = (bg_color.Red() + bg_color.Green() + bg_color.Blue()) / 3
        self.is_dark_mode = bg_brightness < 128

        # Update cached theme colors
        self._theme_colors = self.GenerateThemeColors(bg_color, fg_color)
        self._theme_colors.update(self.color_overrides)

    def SetScrollbarColor(self, thumb_color, track_color):
        """Set the colours of the popup list's scrollbar slider and track (same as the other custom controls)"""
        thumb_color = wx.Colour(thumb_color)
        self.color_overrides['scrollbar_thumb'] = thumb_color
        self.color_overrides['scrollbar_thumb_hover'] = self.BlendColors(thumb_color, wx.WHITE, 0.75)
        self.color_overrides['scrollbar_bg'] = wx.Colour(track_color)
        self.UpdateThemeColors()

    def SetScrollbarThumbColor(self, thumb_color):
        self.SetScrollbarColor(thumb_color, self.GetThemeColor('scrollbar_bg'))

    def SetScrollbarTrackColor(self, track_color):
        self.SetScrollbarColor(self.GetThemeColor('scrollbar_thumb'), track_color)

    def SetAccentColour(self, colour):
        """
        Set the highlight colour: the selected item in the list and the border while the dropdown has the focus or
        the mouse.  The selected item's text is drawn in black or white, whichever reads better on it.
        """
        colour = wx.Colour(colour)
        brightness = 0.299 * colour.Red() + 0.587 * colour.Green() + 0.114 * colour.Blue()
        self.color_overrides.update({'item_selected_bg': colour,
                                     'item_selected_text': wx.BLACK if brightness > 128 else wx.WHITE,
                                     'border_focus_color': colour,
                                     'border_hover_color': colour})
        self.UpdateThemeColors()
        self.Refresh()

    def GenerateThemeColors(self, bg_color, fg_color):
        """Generate theme colors based on background and foreground colors"""
        colors = {}

        # Base colors
        colors['bg_color'] = bg_color
        colors['text_color'] = fg_color

        if self.is_dark_mode:
            # Dark theme colors
            # colors['border_color'] = self.LightenColor(bg_color, 25)
            colors['border_color'] = wx.Colour(255, 255, 255)
            colors['border_hover_color'] = wx.Colour(100, 150, 200)
            colors['border_focus_color'] = wx.Colour(100, 150, 200)
            colors['placeholder_color'] = self.BlendColors(fg_color, bg_color, 0.6)
            colors['arrow_color'] = self.BlendColors(fg_color, bg_color, 0.7)
            colors['arrow_hover_color'] = fg_color
            colors['dropdown_bg'] = self.LightenColor(bg_color, 10)
            colors['dropdown_border'] = colors['border_color']
            colors['item_hover_bg'] = self.LightenColor(bg_color, 20)
            colors['item_selected_bg'] = wx.Colour(0, 120, 215)
            colors['item_selected_text'] = wx.Colour(255, 255, 255)
            colors['scrollbar_bg'] = self.LightenColor(bg_color, 15)
            colors['scrollbar_thumb'] = self.LightenColor(bg_color, 40)
            colors['scrollbar_thumb_hover'] = self.LightenColor(bg_color, 60)
        else:
            # Light theme colors
            colors['border_color'] = self.DarkenColor(bg_color, 55)
            colors['border_hover_color'] = wx.Colour(100, 150, 200)
            colors['border_focus_color'] = wx.Colour(0, 120, 215)
            colors['placeholder_color'] = self.BlendColors(fg_color, bg_color, 0.5)
            colors['arrow_color'] = self.BlendColors(fg_color, bg_color, 0.6)
            colors['arrow_hover_color'] = fg_color
            colors['dropdown_bg'] = bg_color
            colors['dropdown_border'] = colors['border_color']
            colors['item_hover_bg'] = wx.Colour(240, 248, 255)
            colors['item_selected_bg'] = wx.Colour(0, 120, 215)
            colors['item_selected_text'] = wx.Colour(255, 255, 255)
            colors['scrollbar_bg'] = wx.Colour(245, 245, 245)
            colors['scrollbar_thumb'] = wx.Colour(200, 200, 200)
            colors['scrollbar_thumb_hover'] = wx.Colour(166, 166, 166)

        return colors

    def LightenColor(self, color, amount):
        """Lighten a color by the specified amount"""
        r = min(255, color.Red() + amount)
        g = min(255, color.Green() + amount)
        b = min(255, color.Blue() + amount)
        return wx.Colour(r, g, b)

    def DarkenColor(self, color, amount):
        """Darken a color by the specified amount"""
        r = max(0, color.Red() - amount)
        g = max(0, color.Green() - amount)
        b = max(0, color.Blue() - amount)
        return wx.Colour(r, g, b)

    def BlendColors(self, color1, color2, ratio):
        """Blend two colors with the specified ratio (0.0 = color2, 1.0 = color1)"""
        r = int(color1.Red() * ratio + color2.Red() * (1 - ratio))
        g = int(color1.Green() * ratio + color2.Green() * (1 - ratio))
        b = int(color1.Blue() * ratio + color2.Blue() * (1 - ratio))
        return wx.Colour(r, g, b)

    def GetThemeColor(self, color_key: str) -> wx.Colour:
        """Get a color from the current theme"""
        if not hasattr(self, '_theme_colors'):
            self.UpdateThemeColors()
        return self._theme_colors.get(color_key, wx.Colour(0, 0, 0))

    def SetChoices(self, choices: list[str]):
        """Set the dropdown choices"""
        self.choices = choices
        if self.selected_index >= len(self.choices):
            self.selected_index = -1
            self.current_value = ""
        self.Refresh()

    def GetChoices(self) -> list[str]:
        """Get the current choices"""
        return self.choices.copy()

    def SetSelection(self, index: int):
        """Set the selected item by index"""
        if 0 <= index < len(self.choices):
            self.selected_index = index
            self.current_value = self.choices[index]
            self.UpdateToolTip()
            self.Refresh()
            self.PostSelectionEvent()

    def Enable(self, enable: bool = True) -> bool:
        """Enable or disable the control - it is drawn greyed out while disabled"""
        changed = super().Enable(enable)
        if changed:
            self.Refresh()
        return changed

    def GetSelection(self) -> int:
        """Get the selected index"""
        return self.selected_index

    def SetValue(self, value: str):
        """Set the current value"""
        if value in self.choices:
            self.selected_index = self.choices.index(value)
        else:
            self.selected_index = -1
        self.current_value = value
        self.UpdateToolTip()
        self.Refresh()

    def GetValue(self) -> str:
        """Get the current value"""
        return self.current_value

    def PostSelectionEvent(self):
        """Post a selection change event"""
        event = DropdownSelectionEvent()
        event.SetEventObject(self)
        event.selection = self.selected_index
        event.value = self.current_value
        wx.PostEvent(self, event)

    def OnPaint(self, event):
        """Handle paint events"""
        dc = wx.AutoBufferedPaintDC(self)
        self.DrawDropdown(dc)

    def DrawDropdown(self, dc: wx.DC):
        """Draw the dropdown control"""
        size = self.GetSize()

        # Clear background with parent background to avoid artifacts
        parent_bg = self.GetParent().GetBackgroundColour()
        dc.SetBackground(wx.Brush(parent_bg))
        dc.Clear()

        # Create graphics context for smooth drawing
        gc = wx.GraphicsContext.Create(dc)
        if not gc:
            # Fallback to regular DC if graphics context fails
            self.DrawDropdownFallback(dc, size)
            return

        # Enable antialiasing for smooth curves
        gc.SetAntialiasMode(wx.ANTIALIAS_DEFAULT)

        # Determine border color based on state
        if self.is_focused:
            border_color = self.GetThemeColor('border_focus_color')
        elif self.is_hovered:
            border_color = self.GetThemeColor('border_hover_color')
        else:
            border_color = self.GetThemeColor('border_color')

        # Draw background with rounded corners
        bg_brush = gc.CreateBrush(wx.Brush(self.GetThemeColor('bg_color')))
        border_pen = gc.CreatePen(wx.Pen(border_color, self.border_width))

        gc.SetBrush(bg_brush)
        gc.SetPen(border_pen)

        # Ensure proper rounded rectangle drawing
        rect_x, rect_y = 0.5, 0.5  # Offset by half pixel for crisp lines
        rect_width = size.width - 1
        rect_height = size.height - 1

        # Draw rounded rectangle
        gc.DrawRoundedRectangle(rect_x, rect_y, rect_width, rect_height, self.corner_radius)

        # Draw text
        self.DrawText(gc, size)

        # Draw arrow
        self.DrawArrow(gc, size)

    def DrawDropdownFallback(self, dc: wx.DC, size: wx.Size):
        """Fallback drawing method without graphics context"""
        # Determine border color based on state
        if self.is_focused:
            border_color = self.GetThemeColor('border_focus_color')
        elif self.is_hovered:
            border_color = self.GetThemeColor('border_hover_color')
        else:
            border_color = self.GetThemeColor('border_color')

        # Draw background
        dc.SetBrush(wx.Brush(self.GetThemeColor('bg_color')))
        dc.SetPen(wx.Pen(border_color, self.border_width))
        dc.DrawRoundedRectangle(0, 0, size.width, size.height, self.corner_radius)

        # Draw text (simplified)
        if self.current_value:
            dc.SetTextForeground(self.GetThemeColor('text_color' if self.IsEnabled() else 'placeholder_color'))
            text = self.current_value
        else:
            dc.SetTextForeground(self.GetThemeColor('placeholder_color'))
            text = self.hint

        text_x = self.padding
        text_y = (size.height - dc.GetTextExtent(text)[1]) / 2
        dc.DrawText(text, int(text_x), int(text_y))

        # Draw simple arrow
        arrow_color = (self.GetThemeColor('arrow_hover_color') if self.arrow_hovered and self.IsEnabled()
                       else self.GetThemeColor('arrow_color'))
        dc.SetPen(wx.Pen(arrow_color, 2))

        arrow_x = size.width - self.padding - self.arrow_size
        arrow_y = size.height / 2

        if self.is_dropdown_open:
            # Up arrow
            points = [
                wx.Point(int(arrow_x), int(arrow_y + self.arrow_size / 3)),
                wx.Point(int(arrow_x + self.arrow_size / 2), int(arrow_y - self.arrow_size / 3)),
                wx.Point(int(arrow_x + self.arrow_size), int(arrow_y + self.arrow_size / 3))
            ]
        else:
            # Down arrow
            points = [
                wx.Point(int(arrow_x), int(arrow_y - self.arrow_size / 3)),
                wx.Point(int(arrow_x + self.arrow_size / 2), int(arrow_y + self.arrow_size / 3)),
                wx.Point(int(arrow_x + self.arrow_size), int(arrow_y - self.arrow_size / 3))
            ]

        dc.DrawLines(points)

    def DrawText(self, gc: wx.GraphicsContext, size: wx.Size):
        """Draw the text content"""
        font = self.GetFont()
        if self.current_value:
            text_color = self.GetThemeColor('text_color')
            text = self.current_value
        else:
            text_color = self.GetThemeColor('placeholder_color')
            text = self.hint

        if not self.IsEnabled():
            text_color = self.GetThemeColor('placeholder_color')  # Greyed out

        gc.SetFont(font, text_color)

        # Calculate text position
        text_width, text_height = gc.GetTextExtent(text)
        text_x = self.padding
        text_y = (size.height - text_height) / 2

        # Ensure text doesn't overlap with arrow
        max_text_width = size.width - self.padding * 2 - self.arrow_size - self.FromDIP(8)
        if text_width > max_text_width:
            # Truncate text with ellipsis
            while text_width > max_text_width and len(text) > 3:
                text = text[:-4] + "..."
                text_width, _ = gc.GetTextExtent(text)

        gc.DrawText(text, text_x, text_y)

    def SetToolTip(self, tip):
        """Keep the application's tooltip - UpdateToolTip adds the full value to it when the value is cut off"""
        self.app_tooltip = tip.GetTip() if isinstance(tip, wx.ToolTip) else (tip or '')
        self.UpdateToolTip()

    def IsValueCutOff(self) -> bool:
        """Is the value too wide to show in full (so DrawText cuts it off with "...")?"""
        if not self.current_value:
            return False
        dc = wx.ClientDC(self)
        dc.SetFont(self.GetFont())
        max_text_width = self.GetSize().width - self.padding * 2 - self.arrow_size - self.FromDIP(8)
        return dc.GetTextExtent(self.current_value)[0] > max_text_width

    def UpdateToolTip(self):
        """Tooltip: the full value when it is cut off with "...", above the application's own tooltip"""
        tip = self.app_tooltip
        if self.IsValueCutOff():
            tip = self.current_value + ('\n\n' + tip if tip else '')
        if tip != self.applied_tooltip:
            self.applied_tooltip = tip
            if tip:
                super().SetToolTip(tip)
            else:
                self.UnsetToolTip()

    def DrawArrow(self, gc: wx.GraphicsContext, size: wx.Size):
        """Draw the dropdown arrow"""
        arrow_color = (self.GetThemeColor('arrow_hover_color') if self.arrow_hovered and self.IsEnabled()
                       else self.GetThemeColor('arrow_color'))

        # Arrow position
        arrow_x = size.width - self.padding - self.arrow_size
        arrow_y = size.height / 2

        # Create arrow path
        path = gc.CreatePath()
        if self.is_dropdown_open:
            # Up arrow
            path.MoveToPoint(arrow_x, arrow_y + self.arrow_size / 3)
            path.AddLineToPoint(arrow_x + self.arrow_size / 2, arrow_y - self.arrow_size / 3)
            path.AddLineToPoint(arrow_x + self.arrow_size, arrow_y + self.arrow_size / 3)
        else:
            # Down arrow
            path.MoveToPoint(arrow_x, arrow_y - self.arrow_size / 3)
            path.AddLineToPoint(arrow_x + self.arrow_size / 2, arrow_y + self.arrow_size / 3)
            path.AddLineToPoint(arrow_x + self.arrow_size, arrow_y - self.arrow_size / 3)

        gc.SetPen(gc.CreatePen(wx.Pen(arrow_color, 2)))
        gc.StrokePath(path)

    def GetArrowRect(self) -> wx.Rect:
        """Get the arrow clickable area"""
        size = self.GetSize()
        arrow_area = self.FromDIP(24)
        return wx.Rect(size.width - arrow_area, 0, arrow_area, size.height)

    def OnLeftDown(self, event):
        """Handle left mouse button down"""
        self.SetFocus()
        if self.is_dropdown_open:
            self.CloseDropdown()
        elif time.monotonic() - self.popup_dismissed_at > 0.3:
            self.OpenDropdown()
        # else this is the click that just closed the popup from outside - don't open it straight back up

    def OnMouseEnter(self, event):
        """Handle mouse enter"""
        self.is_hovered = True
        self.Refresh()

    def OnMouseLeave(self, event):
        """Handle mouse leave"""
        self.is_hovered = False
        self.arrow_hovered = False
        self.Refresh()

    def OnMouseMotion(self, event):
        """Handle mouse motion - repaint only when the mouse moves on or off the arrow"""
        arrow_hovered = self.GetArrowRect().Contains(event.GetPosition())
        if arrow_hovered != self.arrow_hovered:
            self.arrow_hovered = arrow_hovered
            self.Refresh()

    def OnSetFocus(self, event):
        """Handle focus gained"""
        self.is_focused = True
        self.Refresh()
        event.Skip()

    def OnKillFocus(self, event):
        """Handle focus lost"""
        self.is_focused = False
        self.Refresh()
        event.Skip()

    UP_KEYS = (wx.WXK_UP, wx.WXK_NUMPAD_UP)
    DOWN_KEYS = (wx.WXK_DOWN, wx.WXK_NUMPAD_DOWN)
    PAGE_UP_KEYS = (wx.WXK_PAGEUP, wx.WXK_NUMPAD_PAGEUP)
    PAGE_DOWN_KEYS = (wx.WXK_PAGEDOWN, wx.WXK_NUMPAD_PAGEDOWN)
    HOME_KEYS = (wx.WXK_HOME, wx.WXK_NUMPAD_HOME)
    END_KEYS = (wx.WXK_END, wx.WXK_NUMPAD_END)

    def OnKeyDown(self, event):
        """
        Keyboard use, like a Windows drop-down list.
        Closed: Up / Down / Page Up / Page Down / Home / End change the choice straight away; SPACE, F4 or ALT+Down
        open the list.  Open: the same keys move the highlight, ENTER chooses it, ESC (or TAB) closes the list.
        Typing jumps to a matching item in both (see OnChar).
        """
        key = event.GetKeyCode()
        if self.is_dropdown_open and self.dropdown_popup:
            popup = self.dropdown_popup
            if key == wx.WXK_ESCAPE:
                self.CloseDropdown()
            elif key in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
                if 0 <= popup.hover_index < len(self.choices):
                    self.OnDropdownSelection(popup.hover_index)
                else:
                    self.CloseDropdown()
            elif key == wx.WXK_TAB:
                # Move on to the next (SHIFT: previous) control.  Done here as on Linux the open list has the
                # keyboard, so the dialog wouldn't see the TAB
                self.CloseDropdown()
                self.Navigate(wx.NavigationKeyEvent.IsBackward if event.ShiftDown()
                              else wx.NavigationKeyEvent.IsForward)
            else:
                index = self.KeyMove(key, popup.page_rows(), popup.highlight_or_selection())
                if index is None:
                    event.Skip()                # Typing (OnChar)
                else:
                    popup.SetHighlight(index)
            return

        if key in (wx.WXK_SPACE, wx.WXK_F4) or (event.AltDown() and key in self.UP_KEYS + self.DOWN_KEYS):
            self.OpenDropdown()
            return
        index = self.KeyMove(key, 10, self.selected_index)
        if index is None:
            event.Skip()
        elif index != self.selected_index:
            self.SetSelection(index)

    def KeyMove(self, key, page_rows, current):
        """The item a navigation key moves to from current (-1 = none), or None if it isn't a navigation key"""
        last = len(self.choices) - 1
        if last < 0:
            return None
        if key in self.HOME_KEYS:
            return 0
        if key in self.END_KEYS:
            return last
        steps = {**dict.fromkeys(self.UP_KEYS, -1), **dict.fromkeys(self.DOWN_KEYS, 1),
                 **dict.fromkeys(self.PAGE_UP_KEYS, -page_rows), **dict.fromkeys(self.PAGE_DOWN_KEYS, page_rows)}
        if key not in steps:
            return None
        if current < 0:
            return 0
        return max(0, min(current + steps[key], last))

    def OnChar(self, event):
        """Typing jumps to the next item starting with what was typed (typed within a second counts as one word)"""
        code = event.GetUnicodeKey()
        if code == wx.WXK_NONE or code < 32 or event.ControlDown() or event.AltDown():
            event.Skip()
            return
        now = time.monotonic()
        if now - self.typed_at > 1.0:
            self.typed = ''
        self.typed_at = now
        self.typed += chr(code).lower()

        open_popup = self.dropdown_popup if self.is_dropdown_open else None
        current = open_popup.highlight_or_selection() if open_popup else self.selected_index
        index = self.FindTyped(self.typed, current)
        if index is None and len(self.typed) > 1:
            self.typed = self.typed[-1]                     # No match: start again from the last letter typed
            index = self.FindTyped(self.typed, current)
        if index is None:
            return
        if open_popup:
            open_popup.SetHighlight(index)
        elif index != self.selected_index:
            self.SetSelection(index)

    def FindTyped(self, typed: str, current: int):
        """The item type-ahead text picks, or None"""
        if len(set(typed)) == 1:
            prefix, start = typed[0], current + 1           # The same letter again: the next item with it
        else:
            prefix, start = typed, max(current, 0)          # More letters: the current item may still match
        count = len(self.choices)
        for offset in range(count):
            index = (start + offset) % count
            if self.choices[index].lower().startswith(prefix):
                return index
        return None

    def OnSize(self, event):
        """Handle size changes"""
        self.UpdateToolTip()        # More or less of the value may fit now
        self.Refresh()
        event.Skip()

    def OpenDropdown(self):
        """Open the dropdown list"""
        if not self.choices or self.is_dropdown_open:
            return

        self.is_dropdown_open = True
        self.CreateDropdownPopup()
        self.Refresh()

    def OnPopupDismissed(self):
        """The popup closed itself (click outside it, the application lost focus...)"""
        if self.GetScreenRect().Contains(wx.GetMousePosition()):
            self.popup_dismissed_at = time.monotonic()
        self.CloseDropdown()

    def GetPopupRect(self) -> tuple[wx.Point, wx.Size]:
        """
        Screen position and size for the popup list: below the control, up to popup_max_height tall, kept inside the
        usable area of the screen the control is on (not under the taskbar).  When there isn't room below and there
        is more room above, it opens upwards; otherwise it is made shorter and scrolls.
        """
        top_left = self.ClientToScreen((0, 0))
        control_height = self.GetSize().height
        full_height = len(self.choices) * self.item_height + 4
        height = min(full_height, self.popup_max_height)

        display = wx.Display.GetFromWindow(self)
        area = wx.Display(display if display != wx.NOT_FOUND else 0).GetClientArea()
        room_below = area.GetBottom() + 1 - (top_left.y + control_height)
        room_above = top_left.y - area.GetTop()

        if height <= room_below or room_below >= room_above:
            y = top_left.y + control_height
            height = min(height, room_below)
        else:
            height = min(height, room_above)
            y = top_left.y - height
        height = max(height, self.item_height + 4)      # At least one item, even on a tiny screen

        # Wide enough for the longest item (with the check mark column and, if it scrolls, the scrollbar), at least as
        # wide as the drop-down, at most as wide as the screen
        dc = wx.ClientDC(self)
        dc.SetFont(self.GetFont())
        longest = max((dc.GetTextExtent(choice)[0] for choice in self.choices), default=0)
        needed = (self.popup_text_x + longest + self.padding + 4 +
                  (self.popup_scrollbar_width if full_height > height else 0))
        width = min(max(self.GetSize().width, self.popup_min_width, needed), area.GetWidth())

        # Keep it on the screen sideways too (a narrow screen or a control near the right edge)
        x = max(area.GetLeft(), min(top_left.x, area.GetRight() + 1 - width))
        return wx.Point(x, y), wx.Size(width, height)

    def CreateDropdownPopup(self):
        """Create and show the dropdown popup"""
        pos, size = self.GetPopupRect()

        # Create popup window
        self.dropdown_popup = DropdownPopup(self, pos, size,
                                            self.choices, self.selected_index, self)
        self.dropdown_popup.Popup(focus=self)   # Keep the keyboard focus here (ESC closes the list)

    def CloseDropdown(self):
        """Close the dropdown list"""
        popup = self.dropdown_popup
        self.dropdown_popup = None
        if popup:
            popup.Dismiss()
            # This can run inside one of the popup's own event handlers, so destroy it once they are done
            wx.CallAfter(lambda: popup and popup.Destroy())

        self.is_dropdown_open = False
        self.Refresh()

    def OnDropdownSelection(self, index: int):
        """Handle selection from dropdown popup"""
        self.SetSelection(index)
        self.CloseDropdown()

    def Clear(self):
        """Clear all choices from the dropdown"""
        self.choices = []
        self.selected_index = -1
        self.current_value = ""

        # Close dropdown if it's open
        if self.is_dropdown_open:
            self.CloseDropdown()

        self.Refresh()


class DropdownPopup(wx.PopupTransientWindow):
    """
    Popup window for dropdown items with scrolling support.  As a transient popup it closes itself when the user
    clicks anywhere outside it or switches to another application (OnDismiss tells the dropdown).
    """

    def __init__(self, parent, pos, size, choices, selected_index, dropdown_parent):
        super().__init__(parent)

        self.parent_dropdown = parent
        self.dropdown_parent = dropdown_parent
        self.choices = choices
        self.selected_index = selected_index
        self.hover_index = -1
        self.item_height = parent.item_height
        self.scrollbar_width = parent.popup_scrollbar_width
        self.text_x = parent.popup_text_x               # Item text inset (the check mark is to its left)
        self.min_thumb_height = parent.FromDIP(20)

        # Scrolling state
        self.scroll_offset = 0
        self.max_scroll = 0
        self.scrollbar_visible = False
        self.scrollbar_dragging = False
        self.drag_start_y = 0
        self.drag_start_scroll = 0
        self.scrollbar_thumb_hover = False

        self.SetPosition(pos)
        self.SetSize(size)

        # Calculate scrolling parameters
        self.CalculateScrolling()

        # Create panel for content
        self.panel = wx.Panel(self)
        self.panel.SetSize(size)
        self.panel.SetBackgroundStyle(wx.BG_STYLE_CUSTOM)

        self.BindEvents()

        # Auto-scroll to selected item if it exists
        if self.selected_index >= 0:
            self.ScrollToItem(self.selected_index)

    def CalculateScrolling(self):
        """Calculate scrolling parameters"""
        content_height = len(self.choices) * self.item_height
        visible_height = self.GetSize().height - 4  # Account for border

        self.scrollbar_visible = content_height > visible_height
        if self.scrollbar_visible:
            self.max_scroll = max(0, content_height - visible_height)
        else:
            self.max_scroll = 0
            self.scroll_offset = 0

    def ScrollToItem(self, item_index):
        """Scroll to make the specified item visible"""
        if not self.scrollbar_visible:
            return

        item_y = item_index * self.item_height
        visible_height = self.GetSize().height - 4

        # Check if item is above visible area
        if item_y < self.scroll_offset:
            self.scroll_offset = item_y
        # Check if item is below visible area
        elif item_y + self.item_height > self.scroll_offset + visible_height:
            self.scroll_offset = item_y + self.item_height - visible_height

        # Clamp scroll offset
        self.scroll_offset = max(0, min(self.scroll_offset, self.max_scroll))

    def BindEvents(self):
        """Bind popup events"""
        self.panel.Bind(wx.EVT_PAINT, self.OnPaint)
        self.panel.Bind(wx.EVT_LEFT_DOWN, self.OnLeftDown)
        self.panel.Bind(wx.EVT_LEFT_UP, self.OnLeftUp)
        self.panel.Bind(wx.EVT_MOUSE_CAPTURE_LOST, self.OnCaptureLost)
        self.panel.Bind(wx.EVT_MOTION, self.OnMouseMotion)
        self.panel.Bind(wx.EVT_LEAVE_WINDOW, self.OnMouseLeave)
        self.panel.Bind(wx.EVT_MOUSEWHEEL, self.OnMouseWheel)
        # On Linux (GTK) the open popup takes the keyboard, so keys arrive here rather than at the dropdown
        for window in (self, self.panel):
            window.Bind(wx.EVT_KEY_DOWN, self.OnKeyDown)
            window.Bind(wx.EVT_CHAR, self.OnChar)

    def OnKeyDown(self, event):
        """Keys are handled by the dropdown (see ModernDropdown.OnKeyDown)"""
        self.parent_dropdown.OnKeyDown(event)

    def OnChar(self, event):
        self.parent_dropdown.OnChar(event)

    def highlight_or_selection(self) -> int:
        """The item the keyboard moves from: the highlighted one, else the selected one (-1 = none)"""
        return self.hover_index if self.hover_index >= 0 else self.selected_index

    def page_rows(self) -> int:
        """Items in a page of the list (Page Up / Page Down)"""
        return max(1, (self.GetSize().height - 4) // self.item_height)

    def SetHighlight(self, index: int):
        """Highlight an item (keyboard) and scroll it into view"""
        self.hover_index = index
        self.ScrollToItem(index)
        self.panel.Refresh()

    def OnDismiss(self):
        """Called by wx when the popup closed itself (not when the dropdown closes it)"""
        if self.parent_dropdown and self.parent_dropdown.dropdown_popup is self:
            self.parent_dropdown.OnPopupDismissed()

    def GetThemeColor(self, color_key: str) -> wx.Colour:
        """Get a color from the dropdown's theme"""
        return self.dropdown_parent.GetThemeColor(color_key)

    def OnPaint(self, event):
        """Paint the popup"""
        dc = wx.AutoBufferedPaintDC(self.panel)
        self.DrawPopup(dc)

    def DrawPopup(self, dc: wx.DC):
        """Draw the popup content"""
        size = self.GetSize()

        # Background
        dc.SetBackground(wx.Brush(self.GetThemeColor('dropdown_bg')))
        dc.Clear()

        # Border
        dc.SetPen(wx.Pen(self.GetThemeColor('dropdown_border'), 1))
        dc.SetBrush(wx.Brush(wx.Colour(0, 0, 0, 0), wx.BRUSHSTYLE_TRANSPARENT))
        dc.DrawRectangle(0, 0, size.width, size.height)

        # Calculate content area (excluding scrollbar if visible)
        content_width = size.width - (self.scrollbar_width if self.scrollbar_visible else 0) - 4

        # Set clipping region for content
        dc.SetClippingRegion(2, 2, int(content_width), size.height - 4)

        # Draw visible items
        dc.SetFont(self.parent_dropdown.GetFont())
        visible_height = size.height - 4

        # Calculate which items are visible
        first_visible = max(0, int(self.scroll_offset // self.item_height))
        last_visible = min(len(self.choices),
                           int((self.scroll_offset + visible_height + self.item_height - 1) // self.item_height))

        for i in range(first_visible, last_visible):
            choice = self.choices[i]
            y = int(i * self.item_height + 2 - self.scroll_offset)

            # Skip if item is not in visible area
            if y + self.item_height <= 2 or y >= size.height - 2:
                continue

            # Item background - the selected item keeps the selection colour (a little lighter while the mouse is
            # over it) so its text, drawn in the selected text colour, stays readable
            if i == self.selected_index:
                item_bg = self.GetThemeColor('item_selected_bg')
                if i == self.hover_index:
                    item_bg = self.dropdown_parent.LightenColor(item_bg, 25)
            elif i == self.hover_index:
                item_bg = self.GetThemeColor('item_hover_bg')
            else:
                item_bg = None
            if item_bg is not None:
                dc.SetBrush(wx.Brush(item_bg))
                dc.SetPen(wx.Pen(item_bg))
                dc.DrawRectangle(2, y, int(content_width), self.item_height)

            # Item text
            if i == self.selected_index:
                dc.SetTextForeground(self.GetThemeColor('item_selected_text'))
            else:
                dc.SetTextForeground(self.GetThemeColor('text_color'))

            text_y = int(y + (self.item_height - dc.GetTextExtent(choice)[1]) // 2)
            dc.DrawText(choice, self.text_x, text_y)

            if i == self.selected_index:
                self.DrawCheckMark(dc, y)

        # Remove clipping
        dc.DestroyClippingRegion()

        # Draw scrollbar if needed
        if self.scrollbar_visible:
            self.DrawScrollbar(dc, size)

    def DrawCheckMark(self, dc: wx.DC, item_y: int):
        """A tick to the left of the selected item's text (drawn, so it doesn't depend on the font having one)"""
        unit = self.parent_dropdown.FromDIP(1)
        x = self.parent_dropdown.FromDIP(7)
        middle = item_y + self.item_height / 2
        points = [(x, middle), (x + 3.5 * unit, middle + 3.5 * unit), (x + 10 * unit, middle - 4 * unit)]
        pen = wx.Pen(self.GetThemeColor('item_selected_text'), max(2, int(1.6 * unit)))
        pen.SetCap(wx.CAP_ROUND)
        pen.SetJoin(wx.JOIN_ROUND)
        gc = wx.GraphicsContext.Create(dc)
        if gc:
            gc.SetPen(pen)
            gc.StrokeLines(points)
        else:
            dc.SetPen(pen)
            dc.DrawLines([wx.Point(int(px), int(py)) for px, py in points])

    def DrawScrollbar(self, dc: wx.DC, size: wx.Size):
        """Draw the scrollbar"""
        scrollbar_x = size.width - self.scrollbar_width - 2
        scrollbar_y = 2
        scrollbar_height = size.height - 4

        # Scrollbar background
        dc.SetBrush(wx.Brush(self.GetThemeColor('scrollbar_bg')))
        dc.SetPen(wx.Pen(self.GetThemeColor('scrollbar_bg')))
        dc.DrawRectangle(scrollbar_x, scrollbar_y, self.scrollbar_width, scrollbar_height)

        # Calculate thumb size and position
        content_height = len(self.choices) * self.item_height
        visible_height = size.height - 4

        thumb_height = max(self.min_thumb_height, int(scrollbar_height * visible_height / content_height))
        thumb_y = int(scrollbar_y + scrollbar_height * self.scroll_offset / content_height)

        # Ensure thumb doesn't go beyond scrollbar
        if thumb_y + thumb_height > scrollbar_y + scrollbar_height:
            thumb_y = scrollbar_y + scrollbar_height - thumb_height

        # Scrollbar thumb
        thumb_color = (self.GetThemeColor('scrollbar_thumb_hover') if self.scrollbar_thumb_hover
                       else self.GetThemeColor('scrollbar_thumb'))
        dc.SetBrush(wx.Brush(thumb_color))
        dc.SetPen(wx.Pen(thumb_color))
        dc.DrawRoundedRectangle(scrollbar_x + 2, thumb_y, self.scrollbar_width - 4, thumb_height, 2)

    def GetScrollbarThumbRect(self) -> wx.Rect:
        """Get the scrollbar thumb rectangle"""
        if not self.scrollbar_visible:
            return wx.Rect()

        size = self.GetSize()
        scrollbar_x = size.width - self.scrollbar_width - 2
        scrollbar_y = 2
        scrollbar_height = size.height - 4

        # Calculate thumb size and position
        content_height = len(self.choices) * self.item_height
        visible_height = size.height - 4

        thumb_height = max(self.min_thumb_height, int(scrollbar_height * visible_height / content_height))
        thumb_y = int(scrollbar_y + scrollbar_height * self.scroll_offset / content_height)

        # Ensure thumb doesn't go beyond scrollbar
        if thumb_y + thumb_height > scrollbar_y + scrollbar_height:
            thumb_y = int(scrollbar_y + scrollbar_height - thumb_height)

        return wx.Rect(scrollbar_x + 2, thumb_y, self.scrollbar_width - 4, thumb_height)

    def OnMouseWheel(self, event):
        """Handle mouse wheel scrolling"""
        if not self.scrollbar_visible:
            return

        # Scroll 3 items per wheel step
        scroll_amount = 3 * self.item_height

        if event.GetWheelRotation() > 0:
            # Scroll up
            self.scroll_offset = max(0, self.scroll_offset - scroll_amount)
        else:
            # Scroll down
            self.scroll_offset = min(self.max_scroll, self.scroll_offset + scroll_amount)

        self.panel.Refresh()

    def OnMouseMotion(self, event):
        """Handle mouse motion in popup"""
        if self.scrollbar_dragging:
            # Handle scrollbar dragging
            delta_y = event.GetY() - self.drag_start_y
            size = self.GetSize()
            scrollbar_height = size.height - 4
            content_height = len(self.choices) * self.item_height

            # Convert pixel delta to scroll offset delta
            scroll_delta = delta_y * content_height / scrollbar_height
            new_scroll = self.drag_start_scroll + scroll_delta
            self.scroll_offset = max(0, min(self.max_scroll, new_scroll))

            self.panel.Refresh()
            return

        # Check if mouse is over scrollbar
        if self.scrollbar_visible:
            scrollbar_rect = wx.Rect(self.GetSize().width - self.scrollbar_width - 2, 2,
                                     self.scrollbar_width, self.GetSize().height - 4)
            thumb_rect = self.GetScrollbarThumbRect()

            old_thumb_hover = self.scrollbar_thumb_hover
            self.scrollbar_thumb_hover = thumb_rect.Contains(event.GetPosition())

            if old_thumb_hover != self.scrollbar_thumb_hover:
                self.panel.Refresh()

            if scrollbar_rect.Contains(event.GetPosition()):
                return  # Don't process item hover if over scrollbar

        # Handle item hovering
        content_width = self.GetSize().width - (self.scrollbar_width if self.scrollbar_visible else 0) - 4
        if event.GetX() <= content_width:
            y = event.GetY() + self.scroll_offset
            new_hover = (y - 2) // self.item_height

            if 0 <= new_hover < len(self.choices) and new_hover != self.hover_index:
                self.hover_index = new_hover
                self.panel.Refresh()

    def OnMouseLeave(self, event):
        """Handle mouse leaving popup"""
        self.hover_index = -1
        self.scrollbar_thumb_hover = False
        self.panel.Refresh()

    def OnLeftDown(self, event):
        """Handle click in popup"""
        # Check if clicking on scrollbar
        if self.scrollbar_visible:
            scrollbar_rect = wx.Rect(self.GetSize().width - self.scrollbar_width - 2, 2,
                                     self.scrollbar_width, self.GetSize().height - 4)
            thumb_rect = self.GetScrollbarThumbRect()

            if scrollbar_rect.Contains(event.GetPosition()):
                if thumb_rect.Contains(event.GetPosition()):
                    # Start dragging scrollbar thumb
                    self.scrollbar_dragging = True
                    self.drag_start_y = event.GetY()
                    self.drag_start_scroll = self.scroll_offset
                    self.panel.CaptureMouse()
                else:
                    # Click on scrollbar track - jump scroll
                    click_y = event.GetY()
                    thumb_center_y = thumb_rect.y + thumb_rect.height // 2

                    if click_y < thumb_center_y:
                        # Scroll up by one page
                        self.scroll_offset = max(0, self.scroll_offset - (self.GetSize().height - 4))
                    else:
                        # Scroll down by one page
                        self.scroll_offset = min(self.max_scroll,
                                                 self.scroll_offset + (self.GetSize().height - 4))

                    self.panel.Refresh()
                return

        # Handle item selection
        content_width = self.GetSize().width - (self.scrollbar_width if self.scrollbar_visible else 0) - 4
        if event.GetX() <= content_width:
            y = event.GetY() + self.scroll_offset
            clicked_index = int((y - 2) // self.item_height)

            if 0 <= clicked_index < len(self.choices):
                self.parent_dropdown.OnDropdownSelection(clicked_index)
            else:
                self.parent_dropdown.CloseDropdown()
        else:
            self.parent_dropdown.CloseDropdown()

    def OnLeftUp(self, event):
        """Handle mouse button up"""
        if self.scrollbar_dragging:
            self.scrollbar_dragging = False
            if self.panel.HasCapture():
                self.panel.ReleaseMouse()

    def OnCaptureLost(self, event):
        """The mouse capture was taken away mid-drag (Alt-Tab, a dialog popping up...) - end the drag"""
        self.scrollbar_dragging = False

