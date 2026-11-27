#!/usr/bin/env python3

# ----------------------------------------------------------------------------------------------------------------------
# search_help.py

"""
The search box's cheat sheet: a pop-up (from the '?' button beside the search box) listing every kind of search term
with an example of each.  Clicking an example adds it to the search.  The terms themselves are in search.CHEAT_SHEET.
"""

import wx

import functions
import search

_ = functions.set_up_language()  # localization


class SearchHelpPopup(wx.PopupTransientWindow):
    def __init__(self, parent, application_colors: dict, on_example):
        """
        :param application_colors: functions.get_application_colors()
        :param on_example: called with an example's search term when it is clicked (the pop-up then closes)
        """
        super().__init__(parent, flags=wx.BORDER_SIMPLE)
        self.on_example = on_example
        text_colour = application_colors['text']
        background = application_colors['text_background']
        self.SetBackgroundColour(background)

        panel = wx.Panel(self)
        panel.SetBackgroundColour(background)
        normal = wx.SystemSettings.GetFont(wx.SYS_DEFAULT_GUI_FONT)
        bold = normal.Bold()
        example_font = wx.Font(normal.GetPointSize(), wx.FONTFAMILY_TELETYPE, wx.FONTSTYLE_NORMAL,
                               wx.FONTWEIGHT_NORMAL, underline=True)
        link_colour = application_colors['selected_row_background']

        def label(text, font, colour):
            control = wx.StaticText(panel, label=text)
            control.SetFont(font)
            control.SetForegroundColour(colour)
            control.SetBackgroundColour(background)
            return control

        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(label(_('Search terms'), bold.Scaled(1.15), text_colour), 0, wx.BOTTOM, 6)
        self.examples = {}          # example term: its StaticText (for the tests)
        grid = wx.FlexGridSizer(cols=2, vgap=2, hgap=16)        # One grid, so the meanings line up in every section
        for number, (heading, rows) in enumerate(search.CHEAT_SHEET):
            grid.Add(label(_(heading), bold, text_colour), 0, wx.TOP | wx.BOTTOM, 4 if number == 0 else 8)
            grid.AddSpacer(0)
            for example, meaning in rows:
                link = label(example, example_font, link_colour)
                link.SetCursor(wx.Cursor(wx.CURSOR_HAND))
                link.SetToolTip(_('Click to add this to the search'))
                link.Bind(wx.EVT_LEFT_UP, lambda _event, term=example: self.choose(term))
                self.examples[example] = link
                grid.Add(link, 0, wx.LEFT | wx.ALIGN_CENTER_VERTICAL, 10)
                grid.Add(label(_(meaning), normal, text_colour), 0, wx.ALIGN_CENTER_VERTICAL)
        outer.Add(grid)
        outer.Add(label(_('Click an example to add it to the search.  Terms can be combined.'), normal.Italic(),
                        text_colour), 0, wx.TOP, 8)

        border = wx.BoxSizer(wx.VERTICAL)
        border.Add(outer, 1, wx.ALL, 10)
        panel.SetSizer(border)
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(panel, 1, wx.EXPAND)
        self.SetSizerAndFit(sizer)
        panel.Bind(wx.EVT_CHAR_HOOK, self.on_key)

    def choose(self, term: str) -> None:
        self.Dismiss()
        wx.CallAfter(self.on_example, term)          # After the pop-up has gone, so the search box gets the focus

    def on_key(self, event) -> None:
        if event.GetKeyCode() == wx.WXK_ESCAPE:
            self.Dismiss()
        else:
            event.Skip()

    def show_below(self, window: wx.Window) -> None:
        """Open the pop-up under window (the search box), kept on the screen."""
        position = window.ClientToScreen(wx.Point(0, window.GetSize().height))
        display = wx.Display(max(wx.Display.GetFromWindow(window), 0)).GetClientArea()
        size = self.GetSize()
        x = max(display.x, min(position.x, display.Right - size.width))
        y = position.y if position.y + size.height <= display.Bottom else \
            window.ClientToScreen(wx.Point(0, 0)).y - size.height
        self.Position(wx.Point(x, y), wx.Size(0, 0))
        self.Popup()
