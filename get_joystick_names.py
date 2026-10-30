#!/usr/bin/env python3

# ----------------------------------------------------------------------------------------------------------------------
# get_joystick_names.py
"""
This is a Windows only requirement.
I have found that getting the joystick name from Windows using wx.adv.joystick doesn't seem to work right.  I think
it is due to the joystick driver not putting things where the function expects to find it.  The work around below
is based on some work by others to look up general device information on a Windows system.
"""

import ctypes
import winreg
from ctypes.wintypes import WORD, UINT
from ctypes.wintypes import WCHAR as TCHAR


# Define constants
MAXPNAMELEN = 32
MAX_JOYSTICKOEMVXDNAME = 260

# Fetch function pointers
joyGetNumDevs = ctypes.windll.winmm.joyGetNumDevs
joyGetPos = ctypes.windll.winmm.joyGetPos
joyGetPosEx = ctypes.windll.winmm.joyGetPosEx
joyGetDevCaps = ctypes.windll.winmm.joyGetDevCapsW


# Define some structures from WinMM that we will use in function calls.
class JOYCAPS(ctypes.Structure):
    _fields_ = [
        ('wMid', WORD),
        ('wPid', WORD),
        ('szPname', TCHAR * MAXPNAMELEN),
        ('wXmin', UINT),
        ('wXmax', UINT),
        ('wYmin', UINT),
        ('wYmax', UINT),
        ('wZmin', UINT),
        ('wZmax', UINT),
        ('wNumButtons', UINT),
        ('wPeriodMin', UINT),
        ('wPeriodMax', UINT),
        ('wRmin', UINT),
        ('wRmax', UINT),
        ('wUmin', UINT),
        ('wUmax', UINT),
        ('wVmin', UINT),
        ('wVmax', UINT),
        ('wCaps', UINT),
        ('wMaxAxes', UINT),
        ('wNumAxes', UINT),
        ('wMaxButtons', UINT),
        ('szRegKey', TCHAR * MAXPNAMELEN),
        ('szOEMVxD', TCHAR * MAX_JOYSTICKOEMVXDNAME),
    ]


def get_joystick_names():
    joysticks = []  # Start with an empty list of joystick names

    # Get the number of supported devices (usually 16).
    num_devs = joyGetNumDevs()
    if num_devs == 0:
        return joysticks

    # Try opening each possible joystick and if it exists add its name to the list
    for joy_id in range(2):
        # Get device capabilities.
        caps = JOYCAPS()

        if joyGetDevCaps(joy_id, ctypes.pointer(caps), ctypes.sizeof(JOYCAPS)) == 0:
            # Fetch the name from registry.
            key = None
            if len(caps.szRegKey) > 0:
                try:
                    key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, "System\\CurrentControlSet\\Control\\MediaResources\\Joystick\\%s\\CurrentJoystickSettings" % caps.szRegKey)
                except WindowsError:
                    key = None

            if key:
                oem_name = winreg.QueryValueEx(key, "Joystick%dOEMName" % (joy_id + 1))
                if oem_name:
                    key2 = winreg.OpenKey(winreg.HKEY_CURRENT_USER, "System\\CurrentControlSet\\Control\\MediaProperties\\PrivateProperties\\Joystick\\OEM\\%s" % oem_name[0])
                    if key2:
                        oem_name = winreg.QueryValueEx(key2, "OEMName")[0]
                        joysticks.append(oem_name)
                    key2.Close()

    return joysticks
