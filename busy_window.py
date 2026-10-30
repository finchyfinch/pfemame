#!/usr/bin/env python3

# ----------------------------------------------------------------------------------------------------------------------
# busy_window.py

"""
Display a 'please wait' message. Use this rather than 'busyinfo' as for starters it works in Linux / macOS, and it
also doesn't block the main window, and you can close it.
"""

# Import python & wxPython modules
import wx
import os

import functions

_ = functions.set_up_language()

class BusyWindow(wx.Dialog):
    """
    A busy window dialog that displays a logo image with "Please Wait..." text underneath.
    The window is sized to fit the image and centered on screen.
    """

    def __init__(self, parent=None, on_cancel=None):
        """
        Initialize the BusyWindow.

        Args:
            parent: Parent window (None for top-level)
            on_cancel: Optional callable.  If given, a Cancel button is shown and on_cancel() is called when it is
                       clicked, along with a line for progress messages (see set_message).
        """
        super().__init__(parent,
                         title="",
                         style=wx.BORDER_NONE | wx.STAY_ON_TOP)

        self.path_to_me = functions.path_to_me()
        self.on_cancel = on_cancel
        self.message_text = None
        self.cancel_button = None
        self.setup_ui()
        self.center_on_screen()

    def setup_ui(self):
        """Set up the user interface elements."""
        # Create main panel
        panel = wx.Panel(self)
        panel.SetBackgroundColour(wx.Colour(240, 240, 240))

        # Create main sizer
        main_sizer = wx.BoxSizer(wx.VERTICAL)

        # Load and display the image
        try:
            # Load the image
            logo_path = os.path.join(self.path_to_me, 'images', 'pfemame_logo_new.png')

            # Scale image to fit within constraints while maintaining aspect ratio
            scaled_image = functions.load_and_scale_bitmap(logo_path, 280, 240)
            bitmap = wx.Bitmap(scaled_image)

            # Create static bitmap control
            image_ctrl = wx.StaticBitmap(panel, bitmap=wx.BitmapBundle.FromBitmap(bitmap))
            main_sizer.Add(image_ctrl, 0, wx.ALL | wx.CENTER, 10)

            # Store scaled image size for window sizing
            self.image_size = scaled_image.GetSize()

        except Exception as e:
            # Error loading image - show error message
            error_text = wx.StaticText(panel, -1, f"Error loading image:\n{str(e)}")
            error_text.SetFont(wx.Font(10, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
            main_sizer.Add(error_text, 0, wx.ALL | wx.CENTER, 10)
            self.image_size = wx.Size(250, 80)

        # Add "Please Wait..." text
        wait_text = wx.StaticText(panel, -1, _("Please Wait..."))
        font = wx.Font(14, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD)
        wait_text.SetFont(font)
        wait_text.SetForegroundColour(wx.Colour(50, 50, 50))
        main_sizer.Add(wait_text, 0, wx.ALL | wx.CENTER, 10)

        if self.on_cancel:
            self.message_text = wx.StaticText(panel, -1, '', style=wx.ALIGN_CENTRE_HORIZONTAL | wx.ST_NO_AUTORESIZE
                                              | wx.ST_ELLIPSIZE_END)
            self.message_text.SetForegroundColour(wx.Colour(50, 50, 50))
            main_sizer.Add(self.message_text, 0, wx.LEFT | wx.RIGHT | wx.EXPAND, 10)
            self.cancel_button = wx.Button(panel, wx.ID_CANCEL, _('Cancel'))
            self.cancel_button.Bind(wx.EVT_BUTTON, self._on_cancel)
            main_sizer.Add(self.cancel_button, 0, wx.ALL | wx.CENTER, 10)

        # Set the sizer for the panel
        panel.SetSizer(main_sizer)

        # Create dialog sizer and add panel
        dialog_sizer = wx.BoxSizer(wx.VERTICAL)
        dialog_sizer.Add(panel, 1, wx.EXPAND)
        self.SetSizer(dialog_sizer)

        # Size the dialog to fit content
        self.size_to_content()

    def size_to_content(self):
        """Size the dialog to fit the image and text with some padding, limited to 300x300."""
        # Calculate required size based on image size plus padding for text
        text_height = 40  # Approximate height for "Please Wait..." text and padding
        padding = 40  # Extra padding around the content

        required_width = min(self.image_size[0] + padding, 300)
        required_height = min(self.image_size[1] + text_height + padding, 300)
        if self.on_cancel:  # Room for the message line and the Cancel button
            required_width = max(required_width, 360)
            required_height += self.message_text.GetCharHeight() + self.cancel_button.GetBestSize().height + 30

        self.SetSize(wx.Size(required_width, required_height))

    def set_message(self, message: str) -> None:
        """Show a progress message under 'Please Wait...' (only when created with on_cancel)."""
        if self and self.message_text:
            self.message_text.SetLabel(message)
            self.message_text.SetToolTip(message)

    def _on_cancel(self, _event) -> None:
        self.cancel_button.Disable()
        self.set_message(_('Cancelling...'))
        self.on_cancel()

    def center_on_screen(self):
        """Center the dialog on the screen."""
        self.Center(wx.BOTH)

    def show(self):
        """Show the busy window."""
        self.Show()
        wx.GetApp().Yield()  # Process pending events to ensure window is drawn

    def close(self):
        """Close and destroy the busy window."""
        if self:
            self.Destroy()


if __name__ == "__main__":
    app = wx.App()

    # Basic usage
    busy = BusyWindow()
    busy.show()

    # Simulate some work (in real usage, this would be your time-consuming operation)
    wx.CallLater(3000, busy.close)  # Close after 3 seconds

    app.MainLoop()