#!/usr/bin/python3

# ----------------------------------------------------------------------------------------------------------------------
# global_defaults.py

"""
Defaults that are used globally across various .py files
"""

from collections import namedtuple

import wx

def get_fixed_color_defaults():
    """
    The color defaults that are fixed values.  These don't need wx.App, so a new pfemame.ini can be written before
    the application starts (e.g. pfemame --language on the first run).
    """
    return {
        "row_alt_1": wx.Colour(255, 255, 255, 255),
        "row_alt_2": wx.Colour(173, 216, 230, 255),
        "missing_game": wx.Colour(255, 153, 153, 255),
        "scrollbar_track": wx.Colour(240, 240, 240, 255),
        "scrollbar_thumb": wx.Colour(200, 200, 200, 255),
    }


# The selection and highlight colours used before 3.11.1 (red text on bright green).  Hard to read, so pfemame.ini
# files still holding them are moved to the system's own colours (iniFile.convert_old_settings).
OLD_SELECTED_ROW = (255, 0, 0, 255)
OLD_SELECTED_ROW_BACKGROUND = (0, 255, 0, 255)
OLD_RIBBON_ITEM_HIGHLIGHT = (0, 255, 0, 255)


def mix_colors(first: wx.Colour, second: wx.Colour, amount: float) -> wx.Colour:
    """first blended into second: amount 1 is all first, 0 all second."""
    return wx.Colour(*(round(a * amount + b * (1 - amount)) for a, b in
                       zip((first.Red(), first.Green(), first.Blue()), (second.Red(), second.Green(), second.Blue()))))


def selection_colors(background: wx.Colour | None = None) -> dict:
    """
    The selected ROM's colours - the system's own selection colours (e.g. white on the Windows highlight blue) - and
    the highlight of a pointed-at item (e.g. a language in the language picker): a soft tint of the same colour on
    the given background (the window colour if none is given).  Call after wx.App is initialised.
    """
    highlight = wx.SystemSettings.GetColour(wx.SYS_COLOUR_HIGHLIGHT)
    background = background or wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOW)
    return {
        "selected_row": wx.SystemSettings.GetColour(wx.SYS_COLOUR_HIGHLIGHTTEXT),
        "selected_row_background": highlight,
        "ribbon_item_highlight": mix_colors(highlight, background, 0.35),
    }


def get_color_defaults():
    """Returns color defaults. Call this after wx.App is initialized."""
    # The rest follow the system theme, so they aren't written to a new pfemame.ini (a stored value wouldn't change
    # when the theme does, e.g. to dark mode)
    return {
        **get_fixed_color_defaults(),
        **selection_colors(),
        "text": wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOWTEXT),
        "text_background": wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOW),
        "window_background": wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOW),
        "control_bar": wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOW),
        "ribbon_bar": wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOW),
        "button_background": wx.SystemSettings.GetColour(wx.SYS_COLOUR_BTNFACE),
    }


# ----------------------------------------------------------------------------------------------------------------------
# The languages pfeMAME can be shown in.  Everything that needs the list (the language picker, gettext set-up, the
# --language option and the About box licence) reads it from here, so adding a language only means adding a line,
# a flag image, a licence file and a locales/<code> catalogue.  tests/test_languagepicker.py checks those all exist.

# N_() marks a string for translation without translating it here (gettext's 'noop' convention) - the text is
# translated where it is displayed.  tools/create_language_files.py collects both _() and N_() strings.
def N_(text: str) -> str:
    return text


# key: the value stored in pfemame.ini ([preferences] language)   code: the locales/<code> folder
# english: the name in English (translated when shown)              native: the name in the language itself
Language = namedtuple('Language', 'key code english native flag license')

LANGUAGES = (
    Language('english', 'en', N_('English'), 'English', 'flag_en.png', 'license_en.txt'),
    Language('german', 'de', N_('German'), 'Deutsch', 'flag_de.png', 'license_de.txt'),
    Language('spanish', 'es', N_('Spanish'), 'Español', 'flag_es.png', 'license_es.txt'),
    Language('french', 'fr', N_('French'), 'Français', 'flag_fr.png', 'license_fr.txt'),
    Language('japanese', 'ja', N_('Japanese'), '日本語', 'flag_ja.png', 'license_ja.txt'),
    Language('chinese', 'zh-CN', N_('Chinese'), '中文', 'flag_zh-cn.png', 'license_zh-cn.txt'),
    Language('russian', 'ru', N_('Russian'), 'Русский', 'flag_ru.png', 'license_ru.txt'),
)

LANGUAGE_KEYS = [language.key for language in LANGUAGES]


def get_language(key: str) -> Language:
    """The language stored in pfemame.ini as key (any case), or English for an empty or unknown one."""
    for language in LANGUAGES:
        if language.key == (key or '').lower():
            return language
    return LANGUAGES[0]
