#!/usr/bin/env python3

# ----------------------------------------------------------------------------------------------------------------------
# starRating.py

"""
Provides a pop-up window to allow you to enter a STAR rating for the selected ROM
"""

# Import python & wxPython modules
import wx

# Import my own modules
import functions

class StarRatingPopup(wx.PopupTransientWindow):
    def __init__(self, parent, initial_rating=0, callback=None):
        super().__init__(parent)
        self.callback = callback
        # The margin round the stars (the sizer border below) - the same colour as the panel, not the system grey
        self.SetBackgroundColour(functions.get_application_colors()['text_background'])
        self.panel = StarPanel(self, initial_rating, self.on_rating_changed)
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self.panel, 1, wx.ALL, 5)
        self.SetSizerAndFit(sizer)

    def on_rating_changed(self, rating):
        if self.callback:
            self.callback(rating)
        self.Dismiss()

class StarPanel(wx.Panel):
    def __init__(self, parent, initial_rating, rating_callback):
        super().__init__(parent)
        self.popup = parent  # reference to popup
        self.rating_callback = rating_callback
        self.rating = initial_rating

        self.stars = []
        hbox = wx.BoxSizer(wx.HORIZONTAL)

        # Add a "clear rating" (0-star) option
        clear = wx.StaticText(self, label='❌', name='clear')
        clear.SetFont(wx.Font(14, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
        clear.SetToolTip("Clear rating")
        clear.SetForegroundColour(wx.Colour(200, 0, 0))  # Red
        clear.SetMinSize(wx.Size(30, 30))
        clear.Bind(wx.EVT_LEFT_DOWN, lambda evt: self.on_star_clicked(0))
        hbox.Add(clear, 0, wx.ALL, 2)

        for i in range(1, 6):
            star = wx.StaticText(self, label='☆')
            star.SetFont(wx.Font(18, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD))
            star.SetForegroundColour(wx.Colour(255, 215, 0))  # Gold/yellow color
            star.SetMinSize(wx.Size(30, 30))

            # Bind mouse events
            star.Bind(wx.EVT_ENTER_WINDOW, self.on_hover)
            star.Bind(wx.EVT_LEAVE_WINDOW, self.on_leave)

            hbox.Add(star, 0, wx.ALL, 2)
            self.stars.append(star)

            # Bind left click
            star.Bind(wx.EVT_LEFT_DOWN, lambda evt, rating=i: self.on_star_clicked(rating))

        # Set the correct application colors
        functions.set_colors(self, functions.get_application_colors(), [wx.StaticText])
        gold = wx.Colour(255, 215, 0)
        red = wx.Colour(200, 0, 0)

        for child in self.GetChildren():
            color = gold if isinstance(child, wx.StaticText) and child.GetName() != 'clear' else red
            child.SetForegroundColour(color)

        self.SetSizer(hbox)
        self.update_stars()

        # Bind ESC key on this panel to close popup
        self.Bind(wx.EVT_CHAR_HOOK, self.on_key)

        # Set focus so it can receive key events
        self.SetFocus()

    def on_hover(self, event):
        # star = event.GetEventObject()
        # star.SetForegroundColour(wx.Colour(255, 215, 0))  # Gold
        # star.SetFont(wx.Font(24, wx.DEFAULT, wx.NORMAL, wx.BOLD, underline=True))
        # star.Refresh()
        event.Skip()

    def on_leave(self, event):
        # star = event.GetEventObject()
        # star.SetForegroundColour(wx.Colour(255, 215, 0))  # Gold
        # star.SetFont(wx.Font(24, wx.DEFAULT, wx.NORMAL, wx.BOLD, underline=False))
        # star.Refresh()
        event.Skip()

    def on_star_clicked(self, rating):
        self.rating = rating
        self.update_stars()
        if self.rating_callback:
            self.rating_callback(rating)

    def update_stars(self):
        for i, star in enumerate(self.stars, start=1):
            if i <= self.rating:
                star.SetLabel('★')  # filled star
            else:
                star.SetLabel('☆')  # empty star

    def on_key(self, event):
        if event.GetKeyCode() == wx.WXK_ESCAPE:
            self.popup.Dismiss()
        else:
            event.Skip()

# Demo app to show usage
if __name__ == "__main__":
    class MyFrame(wx.Frame):
        def __init__(self):
            super().__init__(None, title="Star Popup Demo", size=wx.Size(300, 200))
            panel = wx.Panel(self)
            btn = wx.Button(panel, label="Right-click me", pos=wx.Point(50, 50))
            btn.Bind(wx.EVT_RIGHT_DOWN, self.on_right_click)
            self.current_rating = 3

        def on_right_click(self, event):
            popup = StarRatingPopup(self, initial_rating=self.current_rating, callback=self.on_rating_selected)
            pos = event.GetEventObject().ClientToScreen(event.GetPosition())
            popup.Position(pos, (0, 0))
            popup.Popup()

        def on_rating_selected(self, rating):
            self.current_rating = rating
            print(f"Rating selected: {rating}")

    app = wx.App()
    frame = MyFrame()
    frame.Show()
    app.MainLoop()
