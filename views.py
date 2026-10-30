#!/usr/bin/env python3

# ----------------------------------------------------------------------------------------------------------------------
# views.py

"""
The ROM list views (All / Favorites / Exists / Missing / Watchlist).

The view drop-down shows translated labels, but everything else - filtering and the value saved in pfemame.ini -
uses the language-neutral keys below.  (Comparing the translated label with English names broke every view except
'Missing' in the German, French, Spanish, Japanese, Russian and Chinese translations.)

This module has no wxPython dependency.
"""

# N_() marks a string for translation without translating it here (gettext's 'noop' convention) - the text is
# translated where it is displayed.  tools/create_language_files.py collects both _() and N_() strings.
def N_(text: str) -> str:
    return text


# mylist columns used by the view filters (see pfemame.py)
INDEX_EXISTS = 3
INDEX_FAVORITE = 6

# Special 'columns' for views that are ordered by play statistics rather than filtered on a mylist column
RECENT = 'recent'
MOST_PLAYED = 'most_played'

VIEW_KEYS = ['All', 'Favorites', 'Exists', 'Missing', 'Watchlist', 'Recent', 'MostPlayed']   # Drop-down order
VIEW_FILTERS = {'All': (-1, ''),
                'Favorites': (INDEX_FAVORITE, '1'),
                'Exists': (INDEX_EXISTS, '1'),
                'Missing': (INDEX_EXISTS, '0'),
                'Watchlist': (INDEX_FAVORITE, '2'),
                'Recent': (RECENT, ''),                 # Most recently played first (see play_stats.py)
                'MostPlayed': (MOST_PLAYED, '')}        # Most play time first


VIEW_LABELS = [N_('All'), N_('Favorites'), N_('Exists'), N_('Missing'), N_('Watchlist'), N_('Recently Played'),
               N_('Most Played')]      # English labels, in VIEW_KEYS order


def view_labels(translate) -> list[str]:
    """Translated labels for the drop-down, in VIEW_KEYS order.  translate is the gettext function."""
    return [translate(label) for label in VIEW_LABELS]


def normalize_view_key(value: str, translate) -> str:
    """A view key, or a translated label (older pfemame.ini files stored those), as a VIEW_KEYS key."""
    if value in VIEW_KEYS:
        return value
    labels = view_labels(translate)
    return VIEW_KEYS[labels.index(value)] if value in labels else 'All'
