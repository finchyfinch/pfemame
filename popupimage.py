#!/usr/bin/env python3

# ----------------------------------------------------------------------------------------------------------------------
# popupimage.py

"""
Pop Up Image Viewer.
This takes the currently displayed ROM image and pops it up onto the screen in a larger format.
Clicking or pressing escape closes the view.
"""

# Import python & wxPython modules
import wx
import os

# Import my own modules
import functions


# ----------------------------------------------------------------------------------------------------------------------
# Window for displaying the rom information
class PopUpImageViewer(wx.Frame):
    def __init__(self, rom_name, image_file_name):
        wx.Frame.__init__(self,
                          wx.GetApp().TopWindow,
                          -1,
                          rom_name,
                          size=wx.Size(-1, -1),
                          )

        # --------------------------------------------------------------------------------------------------------------
        # Get the absolute path to this application.  This is needed if we run via shortcut
        # or link otherwise we couldn't find relative files like icons etc
        path_to_me = functions.path_to_me()  # Get the absolute path to me

        # Redirect logging, so we don't get exceptions from incorrectly formatted images
        _nullTarget = wx.LogNull()  # Prevent a crash with malformed png files in windowsXP

        # Get the image that we want to display
        image = wx.Image(image_file_name, wx.BITMAP_TYPE_ANY).ConvertToBitmap()

        # --------------------------------------------------------------------------------------------------------------
        # Define the application icon
        self.SetIcon(wx.Icon(os.path.join(path_to_me, 'images', 'pfemame.ico'), wx.BITMAP_TYPE_ICO))

        if self.GetParent():  # Following will only be called if this window is running as a child
            self.CenterOnParent()
            self.GetParent().Disable()

        self.Bind(wx.EVT_CLOSE, self.on_close)
        self.Bind(wx.EVT_CHAR_HOOK, self.on_key_up)  # Use this to capture the escape key to close the window

        self.panel = wx.Panel(self)
        self.panel.SetFocus()

        # Define the sizers
        horizontal_sizer = wx.BoxSizer(wx.HORIZONTAL)
        vertical_sizer = wx.BoxSizer(wx.VERTICAL)
        horizontal_sizer.Add(self.panel, 1, flag=wx.EXPAND | wx.ALL, border=0)
        vertical_sizer.Add(horizontal_sizer, 1, flag=wx.EXPAND | wx.ALL, border=0)

        # Scale the image up while maintaining the aspect ratio and fit the panel to the image
        image = image.ConvertToImage()
        image_width = image.GetWidth()
        image_height = image.GetHeight()
        new_image_height = wx.DisplaySize()[1]
        image_height_ratio = new_image_height / image_height
        new_image_width = int(image_height_ratio * image_width)
        image = image.Scale(new_image_width, new_image_height)
        image = image.ConvertToBitmap()

        self.image = wx.StaticBitmap(self.panel, bitmap=image)
        self.image.Bind(wx.EVT_LEFT_DOWN, self.on_close)

        del _nullTarget

        self.SetSizer(vertical_sizer)
        vertical_sizer.Fit(self)

        # --------------------------------------------------------------------------------------------------------------
        # Display the window
        self.Centre()
        self.Show()

    # ------------------------------------------------------------------------------------------------------------------
    # Capture a key event on the panel and look for the escape key to close the window
    def on_key_up(self, event):
        if event.GetKeyCode() == wx.WXK_ESCAPE:
            self.on_close(-1)
        event.Skip()

    # --------------------------------------------------------------------------------------------------------------
    # Handle the close event and ensure the parent window is given back control
    def on_close(self, _event):
        if self.GetParent():  # Following will only be called if this window is running as a child
            self.GetParent().Enable()
            try:
                self.GetParent().list.SetFocus()
            except AttributeError:
                # We get here if the caller is Tileview as it doesn't have this list
                pass
            self.GetParent().inactivity_timer_start()  # Restart the inactivity timer in the caller
        self.Destroy()


if __name__ == '__main__':
    app = wx.App()
    # This data is just used for testing purposes
    # frame = PopUpImageViewer('Galaxian', 'C:/Mame/Snap/galaxian.png')
    frame = PopUpImageViewer('Galaxian', 'D:/Mame/snap/spectrm.png')
    frame.Show()
    app.MainLoop()
