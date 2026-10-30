#!/usr/bin/env python3

# ----------------------------------------------------------------------------------------------------------------------
# scrolledwindow.py

"""
This presents a pop-up window with a single scrollable text control.
You can send it a string to be displayed.  This replaces the built-in scrolledwindow which doesn't seem to like
very long strings.
"""

# Import python & wxPython modules
import os
import sys
import wx

import functions
from custom_text_ctrl import CustomTextCtrl

_ = functions.set_up_language()


class DisplayScrolledDialog(wx.Frame):
    style = (wx.SYSTEM_MENU | wx.CAPTION | wx.CLOSE_BOX | wx.CLIP_CHILDREN | wx.STAY_ON_TOP)

    def __init__(self, title, file_path='', text_to_display='', scroll=True, size=wx.Size(800, 500)):
        wx.Frame.__init__(self, wx.GetApp().TopWindow, -1, title,  size=size)
        # super().__init__(parent, title=title, size=size,
        #                  style=wx.CAPTION | wx.CLOSE_BOX | wx.CLIP_CHILDREN | wx.STAY_ON_TOP)

        self.application_colors = functions.get_application_colors()
        self.system = sys.platform

        self.SetBackgroundColour(self.application_colors['window_background'])
        self.SetForegroundColour(self.application_colors['text'])

        # Following will only be called if this window is running as a child
        if self.GetParent():
            self.CenterOnParent()
            self.GetParent().Disable()

        self.Bind(wx.EVT_CHAR_HOOK, self.on_key_up)
        self.Bind(wx.EVT_CLOSE, self.on_close)

        self.panel = wx.Panel(self)
        self.text_ctrl = self.create_text_ctrl(size)

        self.build_ui()

        functions.set_colors(self, self.application_colors)

        self.populate_text(file_path, text_to_display, scroll)
        self.text_ctrl.SetFocus()
        self.Centre()
        self.Show()

    def create_text_ctrl(self, size):
        ctrl = CustomTextCtrl(self.panel, size=size,
                              style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_AUTO_URL |
                                    wx.TE_RICH2 | wx.NO_BORDER | wx.EXPAND)

        ctrl.SetBackgroundColour(self.application_colors['text_background'])
        ctrl.SetForegroundColour(self.application_colors['text'])
        return ctrl

    def build_ui(self):
        ok_button = functions.build_one_button(
            self.panel, 'OK', self.on_ok,
        )

        button_sizer = wx.BoxSizer(wx.HORIZONTAL)
        button_sizer.Add(ok_button, 0, wx.ALL, 5)

        content_sizer = wx.BoxSizer(wx.VERTICAL)
        content_sizer.Add(self.text_ctrl, 1, wx.EXPAND | wx.ALL, 5)
        content_sizer.Add(wx.StaticLine(self.panel), 0, wx.EXPAND | wx.ALL, 5)
        content_sizer.Add(button_sizer, 0, wx.ALIGN_RIGHT)

        self.panel.SetSizer(content_sizer)

    def populate_text(self, file_path, text_to_display, scroll):
        if file_path:
            try:
                with open(file_path, 'r', encoding='utf8') as f:
                    data = f.read()
            except FileNotFoundError:
                data = _('Unable to find or open the specified file.')
                wx.MessageDialog(self, data, _('ERROR'), wx.OK | wx.ICON_ERROR).ShowModal()
        else:
            data = text_to_display or _('ERROR - nothing to display')

        # --- Limit to last 2000 lines if too big ---
        lines = data.splitlines()
        MAX_LINES = 2000
        if len(lines) > MAX_LINES:
            # keep only the last N lines
            lines = lines[-MAX_LINES:]
            data = "\n".join(lines)

        self.text_ctrl.Freeze()
        self.text_ctrl.Clear()
        self.text_ctrl.WriteText(data)

        def set_position(position):
            self.text_ctrl.ShowPosition(position)

        if scroll:
            wx.CallAfter(set_position, self.text_ctrl.GetLastPosition())
        else:
            wx.CallAfter(set_position, 0)
        self.text_ctrl.Thaw()

    def on_ok(self, _event):
        self.on_close(-1)

    # ------------------------------------------------------------------------------------------------------------------
    # Capture a key event on the panel and look for the escape key to close the window
    def on_key_up(self, event):
        if event.GetKeyCode() == wx.WXK_ESCAPE:
            self.on_close(-1)
        event.Skip()

    # ------------------------------------------------------------------------------------------------------------------
    # Handle the close event and ensure the parent window is given back control
    def on_close(self, _event):
        if self.GetParent():  # Following will only be called if this window is running as a child
            self.GetParent().Enable()
            self.GetParent().list.SetFocus()
        self.Destroy()



if __name__ == '__main__':
    app = wx.App()
    dlg = DisplayScrolledDialog(None, "View Log",
                                file_path=os.path.join(functions.path_to_me(), "logfile.log"),
                                scroll=True, size=(800, 500))
    dlg.ShowModal()
    dlg.Destroy()
    app.MainLoop()
