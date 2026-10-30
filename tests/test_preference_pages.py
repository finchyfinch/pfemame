"""
The smaller Preferences pages (PanelSound.py ...): TAB order.  wx tabs through a window's children in the order they
were created, so each page sets the order to match its layout.
"""


def tab_order(panel, controls):
    """The given controls in the order TAB visits them (the order of the panel's children)"""
    return [child for child in panel.GetChildren() if child in controls]


def test_sound_page_tabs_top_to_bottom(wx_app, data_dir):
    import wx
    import functions
    import PanelSound
    frame = wx.Frame(None)
    try:
        page = PanelSound.PanelSound(frame, functions.get_application_colors(), 'default', 'windows',
                                     '48000', 'True', '0', 'auto', '2', '')
        expected = [page.cbSamples, page.cbVolume, page.cbLatency, page.cbSamplerate, page.cbSubsystem]
        # It used to be sample rate, volume, sub system, latency, then the samples checkbox at the top
        assert tab_order(page, expected) == expected
    finally:
        frame.Destroy()


def test_video_page_has_no_artwork_off_checkbox(wx_app, data_dir):
    # 'Disable the display of artwork' did the same as 'Disable Artwork for all ROMs' on the pfeMAME tab, and in ROM
    # preferences it did nothing - it was removed
    import wx
    import functions
    import PanelVideo
    frame = wx.Frame(None)
    try:
        for mode in ('default', 'game'):
            page = PanelVideo.PanelVideo(frame, functions.get_application_colors(), mode, 'windows',
                                         'True', 'auto', '', '', '', 'True', '')
            labels = [child.GetLabel() for child in page.GetChildren() if isinstance(child, wx.CheckBox)]
            assert labels == [PanelVideo._('Enable Window Mode'), PanelVideo._('Crop displayed artwork')]
    finally:
        frame.Destroy()
