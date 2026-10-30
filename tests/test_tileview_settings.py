"""Tile View saves its position in pfemame.ini - values with % in them must survive the round trip."""


def test_percent_in_a_saved_value_round_trips(data_dir):
    import iniFile
    name = 'Big 40 Poker (BWB) (S_Site Data + %-Key) (set 1) (MPU4 Video)'
    iniFile.set_ini_file_variables([('preferences', 'tileviewlastrom', name),
                                    ('preferences', 'tileviewcategory', 'Ball & Paddle')])
    assert iniFile.read_ini_file('preferences', 'tileviewlastrom') == name
    assert iniFile.read_ini_file('preferences', 'tileviewcategory') == 'Ball & Paddle'


def test_percent_values_survive_later_saves(data_dir):
    """Values already in the file (stored as %%) are kept as they are when other settings are saved."""
    import iniFile
    iniFile.set_ini_file_variables([('system', 'lastromselected', '100% Pure')])
    iniFile.set_ini_file_variables([('system', 'cachedate', '2026-10-18'), ('system', 'count', 3)])
    assert iniFile.read_ini_file('system', 'lastromselected') == '100% Pure'
    assert iniFile.read_ini_file('system', 'count') == '3'
    assert '100%% Pure' in (data_dir / 'pfemame.ini').read_text(encoding='utf-8')
