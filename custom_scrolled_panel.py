#!/usr/bin/env python3

# ----------------------------------------------------------------------------------------------------------------------
# custom_scrolled_panel.py

"""
Custom scrolled panel with full control over the scroll bar color and fade effect
"""

# Import wxpython and python modules
import wx

# Import my own modules
import custom_scrollbar


class CustomScrolledPanel(wx.Panel):
    def __init__(self, parent, size=wx.DefaultSize, hidden=True, **kwargs):
        super().__init__(parent, size=size, **kwargs)
        self.content_y = 0
        self.min_scroll = 0
        self.hidden = hidden

        self.track_color = wx.Colour(40, 40, 40)
        self.thumb_color = wx.Colour(100, 100, 100)

        # Create main sizer for the panel
        main_sizer = wx.BoxSizer(wx.HORIZONTAL)

        # Container panel inside for adding widgets
        self.content = wx.Panel(self)
        # Enable double buffering to reduce flicker
        self.content.SetDoubleBuffered(True)

        self.scrollbar = custom_scrollbar.UnifiedScrollbar(self, on_scroll=self.on_scrollbar_drag, track_color=self.track_color,
                                   thumb_color=self.thumb_color, hidden=self.hidden)

        self.content.SetBackgroundColour(wx.Colour(30, 30, 30))

        # Add content and scrollbar to main sizer
        main_sizer.Add(self.content, 1, wx.EXPAND)
        main_sizer.Add(self.scrollbar, 0, wx.EXPAND)

        self.SetSizer(main_sizer)

        self.content_sizer = wx.BoxSizer(wx.VERTICAL)
        self.content.SetSizer(self.content_sizer)

        self.Bind(wx.EVT_SIZE, self.on_resize)
        self.Bind(wx.EVT_MOUSEWHEEL, self.on_mousewheel)
        self.Bind(wx.EVT_CHILD_FOCUS, self.on_child_focus)

        # Checks whether the mouse has really left the panel, see on_mouse_leave
        self.leave_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.on_leave_timer, self.leave_timer)
        self.Bind(wx.EVT_WINDOW_DESTROY, self.on_destroy)

        # Improved mouse tracking for fade effect
        if self.hidden:
            # Bind to top-level events that are more reliable
            self.Bind(wx.EVT_ENTER_WINDOW, self.on_mouse_enter)
            self.Bind(wx.EVT_LEAVE_WINDOW, self.on_mouse_leave)
            self.content.Bind(wx.EVT_ENTER_WINDOW, self.on_mouse_enter)
            self.content.Bind(wx.EVT_LEAVE_WINDOW, self.on_mouse_leave)

    def SetBackgroundColour(self, colour):
        # The panel itself shows below the content when there is less than a panel's height of it
        self.content.SetBackgroundColour(colour)
        changed = super().SetBackgroundColour(colour)
        self.Refresh()
        return changed

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

    def SetScrollbarColor(self, thumb_color, track_color):
        """Set both scrollbar colours (same as the other custom controls)"""
        self.thumb_color = thumb_color
        self.track_color = track_color
        self.scrollbar.set_colors(thumb_color, track_color)

    def bind_mouse_events_recursive(self, widget):
        """Bind only enter events to child widgets - lighter approach"""
        widget.Bind(wx.EVT_ENTER_WINDOW, self.on_mouse_enter)
        # Don't bind leave events to every child - too many events

        for child in widget.GetChildren():
            self.bind_mouse_events_recursive(child)

    def on_mouse_enter(self, event):
        # The children only report entering, so the mouse can leave the panel straight off a child (e.g. a checkbox
        # that scrolled under it) without the panel being told.  So while the mouse is inside keep checking every
        # 300 ms (on_leave_timer) - the check stops itself once it has faded the scrollbar out
        if self.hidden:
            self.scrollbar.fade_in()
            if not self.leave_timer.IsRunning():
                self.leave_timer.StartOnce(300)
        event.Skip()

    def on_mouse_leave(self, event):
        # Check sooner when the panel itself reports the mouse leaving (one timer, restarted)
        if self.hidden:
            self.leave_timer.StartOnce(150)
        event.Skip()

    def on_leave_timer(self, _event):
        """Fade the scrollbar out once the mouse is outside the panel - until then keep checking"""
        if not self.GetScreenRect().Contains(wx.GetMousePosition()) and not self.scrollbar.dragging:
            self.scrollbar.fade_out()
        else:
            self.leave_timer.StartOnce(300)

    def on_destroy(self, event):
        # Destroy events from the child widgets come up here too - only stop the timer for this panel's own
        if event.GetEventObject() is self:
            self.leave_timer.Stop()
        event.Skip()

    def add_widget(self, widget):
        """
        Add a widget to the panel
        """
        self.add_widgets([widget])

    def add_widgets(self, widgets):
        """
        Add several widgets to the panel with a single layout - adding many one at a time lays the panel out each
        time, which gets slow with hundreds of widgets
        """
        for widget in widgets:
            self.content_sizer.Add(widget, 0, wx.ALL | wx.EXPAND, 1)

            # Bind mouse events to the new widget if fade is enabled
            if self.hidden:
                self.bind_mouse_events_recursive(widget)

        self.content_sizer.Layout()

        # Force recalculation of the content size
        self.content.SetSize(self.content_sizer.GetMinSize())
        self._update_scroll_limits()
        self._update_scrollbar()

    def _update_scroll_limits(self):
        visible_height = self.GetClientSize().height
        # Force the content to calculate its minimum size
        self.content_sizer.Layout()
        content_height = self.content_sizer.GetMinSize().height

        # Set the content panel to its actual required height
        self.content.SetSize((self.content.GetSize().width, content_height))

        self.min_scroll = min(0, visible_height - content_height)
        self.content_y = max(self.min_scroll, min(0, self.content_y))
        self.content.SetPosition((0, self.content_y))

    def _update_scrollbar(self):
        visible_height = self.GetClientSize().height
        # Use the sizer's minimum size for accurate content height
        content_height = self.content_sizer.GetMinSize().height
        self.scrollbar.update(visible_height, content_height, self.content_y)

    def on_resize(self, event):
        # Lay out first and don't Skip: wx's own layout would otherwise run after this handler and put the content
        # back at the top (at the panel's height) while content_y still holds the scroll position
        self.Layout()
        self._update_scroll_limits()
        self._update_scrollbar()

    def on_child_focus(self, event):
        """Scroll a widget that gets the focus (TAB, or a click on one half out of view) fully into view"""
        widget = event.GetWindow()
        while widget is not None and widget.GetParent() is not self.content:   # The widget added with add_widget
            widget = widget.GetParent()
        if widget is not None:
            self.scroll_into_view(widget)
        event.Skip()

    def scroll_into_view(self, widget):
        """Scroll so all of widget (a child of content) shows"""
        item = self.content_sizer.GetItem(widget)
        border = item.GetBorder() if item else 0                # Include the space round it (add_widget's border)
        top = widget.GetPosition().y - border                   # Relative to content, so from the top of the content
        bottom = widget.GetPosition().y + widget.GetSize().height + border
        visible_top = -self.content_y
        visible_height = self.GetClientSize().height
        if top < visible_top:
            self.content_y = -top
        elif bottom > visible_top + visible_height:
            self.content_y = -(bottom - visible_height)
        else:
            return
        self._update_scroll_limits()
        self._update_scrollbar()

    def on_mousewheel(self, event):
        # Scroll by the system setting (lines per notch, or a page) using the text height as the line height
        if event.IsPageScroll():
            step = self.GetClientSize().height
        else:
            step = event.GetLinesPerAction() * (self.content.GetCharHeight() + 2)
        self.content_y += int(event.GetWheelRotation() / max(1, event.GetWheelDelta()) * step)
        self._update_scroll_limits()
        self._update_scrollbar()

    def on_scrollbar_drag(self, scroll_ratio):
        visible = self.GetClientSize().height
        virtual = self.content_sizer.GetMinSize().height

        max_scroll = virtual - visible
        if max_scroll > 0:
            self.content_y = -int(scroll_ratio * max_scroll)
            # Use the same update method as mousewheel to ensure proper layout
            self._update_scroll_limits()
            self._update_scrollbar()


class MainFrame(wx.Frame):
    def __init__(self):
        super().__init__(None, title="Custom Scrollbar with Fade Effect", size=(400, 300))

        # Create a panel to hold both scroll panels
        main_panel = wx.Panel(self)
        main_sizer = wx.BoxSizer(wx.HORIZONTAL)

        # Create the scrolled panel with hidden scrollbar (default)
        self.scroll_panel_hidden = CustomScrolledPanel(main_panel, hidden=True)

        # Create the scrolled panel with always visible scrollbar
        self.scroll_panel_visible = CustomScrolledPanel(main_panel, hidden=False)

        # Add some test widgets to demonstrate scrolling
        for i in range(20):
            btn1 = wx.Button(self.scroll_panel_hidden.content, label=f"Hidden {i + 1}")
            self.scroll_panel_hidden.add_widget(btn1)

            btn2 = wx.Button(self.scroll_panel_visible.content, label=f"Visible {i + 1}")
            self.scroll_panel_visible.add_widget(btn2)

        main_sizer.Add(self.scroll_panel_hidden, 1, wx.EXPAND | wx.ALL, 5)
        main_sizer.Add(self.scroll_panel_visible, 1, wx.EXPAND | wx.ALL, 5)

        main_panel.SetSizer(main_sizer)
        self.Show()


if __name__ == "__main__":
    app = wx.App(False)
    MainFrame()
    app.MainLoop()