#!/usr/bin/env python3

# ----------------------------------------------------------------------------------------------------------------------
# PanelVideo.py

"""
Video and display options for MAME

"""

import wx
from functions import set_up_language, set_colors, PreferenceManager
from custom_drop_down import ModernDropdown, EVT_DROPDOWN_SELECTION

_ = set_up_language()  # Set up the application language


class PanelVideo(wx.Panel):
    # ----------------------------------------------------------------------
    def __init__(self,
                 parent,
                 application_colors: dict,
                 mode: str,
                 system: str,
                 pref_window: str,
                 pref_video: str,
                 pref_bgfx_backend: str,
                 pref_bgfx_screenchains: str,
                 pref_bgfx_shadowmask: str,
                 pref_artwork_crop: str,
                 path_to_mame_ini_file: str):
        wx.Panel.__init__(self, parent=parent)

        self.mode = mode
        self.system = system
        self.pref_window = pref_window
        self.pref_video = pref_video
        self.pref_bgfx_backend = pref_bgfx_backend
        self.pref_bgfx_screenchains = pref_bgfx_screenchains
        self.pref_bgfx_shadowmask = pref_bgfx_shadowmask
        self.pref_artwork_crop = pref_artwork_crop
        self.path_to_mame_ini_file = path_to_mame_ini_file

        self.startup_complete = False  # Don't allow the control values to be sent until after startup

        # Create the panel controls
        self.cbWindow = wx.CheckBox(self, -1, _('Enable Window Mode'))
        self.cbWindow.Bind(wx.EVT_CHECKBOX, self.on_control_changed)

        self.cbArtworkCrop = wx.CheckBox(self, -1, _('Crop displayed artwork'))
        self.cbArtworkCrop.Bind(wx.EVT_CHECKBOX, self.on_control_changed)

        # (Artwork can be turned off for all ROMs on the pfeMAME tab - 'Disable Artwork for all ROMs')

        views = ['gdi', 'ddraw', 'd3d', 'bgfx', 'auto'] if self.system == 'windows' else ['soft', 'opengl', 'bgfx', 'accel', 'auto']
        self.cbVideo = ModernDropdown(self, wx.ID_ANY, '', choices=views, size=wx.Size(110, 25))
        self.cbVideo.Bind(EVT_DROPDOWN_SELECTION, self.on_control_changed)
        self.cbVideoText = wx.StaticText(self, -1, _('Video System for Drawing'), style=wx.ALIGN_LEFT)

        views = ['d3d9', 'd3d11', 'd3d12', 'opengl', 'auto'] if self.system == 'windows' else ['opengl', 'auto']
        self.cbBgfxBackend = ModernDropdown(self, wx.ID_ANY, '', choices=views, size=wx.Size(110, 25))
        self.cbBgfxBackend.Bind(EVT_DROPDOWN_SELECTION, self.on_control_changed)
        self.cbBgfxBackendText = wx.StaticText(self, -1, _('BGFX Backend'), style=wx.ALIGN_LEFT)

        views = ['hlsl', 'unfiltered', 'crt-geom', 'default']
        self.cbBgfxScreenChains = ModernDropdown(self, wx.ID_ANY, '', choices=views, size=wx.Size(110, 25))
        self.cbBgfxScreenChains.Bind(EVT_DROPDOWN_SELECTION, self.on_control_changed)
        self.cbBgfxScreenChainsText = wx.StaticText(self, -1, _('BGFX Screen Chains'), style=wx.ALIGN_LEFT)

        views = ['aperture-grille.png', 'slot-mask.png', 'shadow-mask.png', 'scanlines.png']
        self.cbBgfxShadowMask = ModernDropdown(self, wx.ID_ANY, '', choices=views, size=wx.Size(110, 25))
        self.cbBgfxShadowMask.Bind(EVT_DROPDOWN_SELECTION, self.on_control_changed)
        self.cbBgfxShadowMaskText = wx.StaticText(self, -1, _('BGFX Shadow Mask'), style=wx.ALIGN_LEFT)

        # Add the tool tip information
        self.cbWindow.SetToolTip(wx.ToolTip(_('Select this to run the ROM in windowed mode, '
                                              'otherwise it will run fullscreen.')))
        self.cbArtworkCrop.SetToolTip(wx.ToolTip(_('Enable cropping of artwork to the system screen area only. '
                                                   'This means that vertically oriented systems running full screen '
                                                   'can display their artwork to the left and right sides of the '
                                                   'screen.')))
        self.cbVideo.SetToolTip(wx.ToolTip(_('Select the video system that is used for rendering the ROM.  In Linux: '
                                             'OpenGL can speed things up but may have compatibility issues.  '
                                             'OpenGL16 may be even faster.  In Windows:  recommend d3d for Direct3D '
                                             'performance.  Use soft for software rendering if you are having issues.')))
        self.cbBgfxBackend.SetToolTip(wx.ToolTip(_('Selects a rendering backend for BGFX to use.')))
        self.cbBgfxScreenChains.SetToolTip(wx.ToolTip(_('This dictates how to handle BGFX rendering on a per-display '
                                                        'basis.')))
        self.cbBgfxShadowMask.SetToolTip(wx.ToolTip(_('This specifies the shadow mask effect PNG file.')))

        # Create the sizers
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer_video = wx.BoxSizer(wx.HORIZONTAL)
        sizer_bgfx_backend = wx.BoxSizer(wx.HORIZONTAL)
        sizer_bgfx_screenchains = wx.BoxSizer(wx.HORIZONTAL)
        sizer_bgfx_shadowmask = wx.BoxSizer(wx.HORIZONTAL)

        # Add the controls to the sizer
        sizer_bgfx_backend.Add(self.cbBgfxBackend, 0, wx.ALL | wx.ALIGN_LEFT, 2)
        sizer_bgfx_backend.Add(self.cbBgfxBackendText, 0, wx.ALL | wx.ALIGN_LEFT | wx.ALIGN_CENTRE_VERTICAL, 2)
        sizer_video.Add(self.cbVideo, 0, wx.ALL | wx.ALIGN_LEFT, 2)
        sizer_video.Add(self.cbVideoText, 0, wx.ALL | wx.ALIGN_LEFT | wx.ALIGN_CENTRE_VERTICAL, 2)
        sizer_bgfx_screenchains.Add(self.cbBgfxScreenChains, 0, wx.ALL | wx.ALIGN_LEFT, 2)
        sizer_bgfx_screenchains.Add(self.cbBgfxScreenChainsText, 0, wx.ALL | wx.ALIGN_LEFT | wx.ALIGN_CENTRE_VERTICAL, 2)
        sizer_bgfx_shadowmask.Add(self.cbBgfxShadowMask, 0, wx.ALL | wx.ALIGN_LEFT, 2)
        sizer_bgfx_shadowmask.Add(self.cbBgfxShadowMaskText, 0, wx.ALL | wx.ALIGN_LEFT | wx.ALIGN_CENTRE_VERTICAL, 2)

        sizer.Add(self.cbWindow, 0, wx.ALL, 10)
        sizer.Add(self.cbArtworkCrop, 0, wx.ALL, 10)
        sizer.Add(sizer_video, 0, wx.ALL, 10)
        sizer.Add(sizer_bgfx_backend, 0, wx.ALL, 10)
        sizer.Add(sizer_bgfx_screenchains, 0, wx.ALL, 10)
        sizer.Add(sizer_bgfx_shadowmask, 0, wx.ALL, 10)

        self.SetSizer(sizer)
        sizer.Fit(self)

        # Ensure all controls have the system wide colors
        set_colors(self, application_colors)

        # Set the controls values from the INI files
        self.cbWindow.SetValue(pref_window == 'True')
        self.cbArtworkCrop.SetValue(pref_artwork_crop == 'True')
        self.cbVideo.SetValue(pref_video)
        self.cbBgfxBackend.SetValue(self.pref_bgfx_backend)
        self.cbBgfxScreenChains.SetValue(self.pref_bgfx_screenchains)
        self.cbBgfxShadowMask.SetValue(self.pref_bgfx_shadowmask)

        self.startup_complete = True

    # Process the controls change event and write its value out to the INI file
    def on_control_changed(self, _event):
        if self.startup_complete:
            # Create the preferences manager
            pref_manager = PreferenceManager(self, self.mode)

            # Register preferences
            pref_manager.add_boolean_preference('pref_window', self.cbWindow)
            pref_manager.add_boolean_preference('pref_artwork_crop', self.cbArtworkCrop)
            pref_manager.add_string_preference('pref_video', self.cbVideo)
            pref_manager.add_string_preference('pref_bgfx_backend', self.cbBgfxBackend)
            pref_manager.add_string_preference('pref_bgfx_screenchains', self.cbBgfxScreenChains)
            pref_manager.add_string_preference('pref_bgfx_shadowmask', self.cbBgfxShadowMask)

            # Update the preferences using the manager
            pref_manager.update_all()
