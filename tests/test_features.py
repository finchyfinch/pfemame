"""Phase 4 features: field search, play statistics, slot presets, software lists and the MAME upgrade report."""
import datetime
import io

import play_stats
import rom_database
import search
import slot_presets
import software_lists


def row(name, rom, program='', exists='1', rating='0', runs='0', fav='0', cat='Maze', year='1980', mfr='Namco'):
    return [name, rom, program, exists, rating, runs, fav, cat, '', '', year, mfr]


ROWS = [row('Pac-Man', 'pacman', rating='5', runs='12', fav='1'),
        row('Galaga', 'galaga', exists='0', cat='Shooter', year='1981'),
        row('Street Fighter II', 'sf2', cat='Fighter', year='1991', mfr='Capcom', rating='4'),
        row('Mahjong Kyou Jidai', 'mjkjidai', cat='Mahjong', year='198?', mfr='Sanritsu'),
        row('ZX Spectrum', 'spectrum', program='Jetpac.tzx', cat='Home Computer', year='1982', mfr='Sinclair',
            fav='2'),
        row('ZX Spectrum', 'spectrum', cat='Home Computer', year='1982', mfr='Sinclair')]


def found(text):
    query = search.parse_query(text)
    return [r[1] + (':' + r[2] if r[2] else '') for r in ROWS if search.matches(r, query)]


# --------------------------------------------------------------------------------------------------------------- search
def test_plain_words_behave_as_before():
    assert found('pac') == ['pacman', 'spectrum:Jetpac.tzx']      # program file names are searched too
    assert found('street fighter') == ['sf2']          # every word must match
    assert found('capcom 1991') == ['sf2']


def test_field_terms():
    assert found('cat:shooter') == ['galaga']
    assert found('mfr:"sinclair"') == ['spectrum:Jetpac.tzx', 'spectrum']
    assert found('year:198') == ['pacman', 'galaga', 'mjkjidai', 'spectrum:Jetpac.tzx', 'spectrum']
    assert found('year:1980-1981') == ['pacman', 'galaga']
    assert found('year:>1990') == ['sf2']              # '198?' is not a number - never matches a comparison
    assert found('rating:>=4') == ['pacman', 'sf2']
    assert found('runs:>10') == ['pacman']
    assert found('file:.tzx') == ['spectrum:Jetpac.tzx']


def test_flags_and_negation():
    assert found('is:fav') == ['pacman']
    assert found('is:watch') == ['spectrum:Jetpac.tzx']
    assert found('is:missing') == ['galaga']
    assert found('is:program') == ['spectrum:Jetpac.tzx']
    search.set_system_names({'spectrum'})
    assert found('is:system') == ['spectrum']
    assert found('-cat:mahjong -is:missing year:198') == ['pacman', 'spectrum:Jetpac.tzx', 'spectrum']


def test_unknown_fields_and_unfinished_quotes_are_plain_words():
    assert found('foo:bar') == []
    assert found('mfr:"data') == []                     # no crash while the user is still typing
    assert search.parse_query('').is_empty


# ----------------------------------------------------------------------------------------------------------- play stats
def test_play_stats(tmp_path):
    path = str(tmp_path / play_stats.FILE_NAME)
    stats = play_stats.PlayStats(path)
    assert not stats.record('pacman', 1.0)                         # too short - MAME probably failed to start
    day = datetime.datetime(2026, 9, 27, 20, 0)
    assert stats.record('pacman', 600, day)
    assert stats.record('pacman', 3000, day + datetime.timedelta(days=1))
    assert stats.record(play_stats.make_key('spectrum', 'Jetpac.tzx'), 120, day + datetime.timedelta(days=2))
    stats.save()

    again = play_stats.PlayStats(path)
    assert again.get('pacman')['plays'] == 2
    assert again.recent() == ['spectrum-->Jetpac.tzx', 'pacman']
    assert again.most_played() == ['pacman', 'spectrum-->Jetpac.tzx']
    assert again.describe('pacman') == 'Played 2 times, 1h 00m in total, last played 28 Sep 2026'
    assert again.describe('galaga') == ''
    assert play_stats.row_key(ROWS[4]) == 'spectrum-->Jetpac.tzx'


def test_corrupt_stats_file_is_ignored(tmp_path):
    path = tmp_path / play_stats.FILE_NAME
    path.write_text('{not json')
    assert play_stats.PlayStats(str(path)).entries == {}


# --------------------------------------------------------------------------------------------------------- slot presets
def test_slot_presets(tmp_path):
    path = str(tmp_path / slot_presets.FILE_NAME)
    slots = {'isa3': 'fdc_xt', 'isa3:fdc_xt:fdc:0': '35dd', 'isa5': ''}
    slot_presets.save(path, 'ibm5150', 'Dual 3.5', slots, 'rev3')
    slot_presets.save(path, 'ibm5150', 'Basic', {'isa1': 'cga'})
    assert slot_presets.names(path, 'ibm5150') == ['Basic', 'Dual 3.5']
    assert slot_presets.get(path, 'ibm5150', 'Dual 3.5') == {'slots': slots, 'bios': 'rev3'}
    assert slot_presets.get(path, 'spectrum', 'Dual 3.5') is None
    assert slot_presets.command_line(slots, 'rev3') == '-bios rev3 -isa3 fdc_xt -isa3:fdc_xt:fdc:0 35dd'
    assert slot_presets.delete(path, 'ibm5150', 'Basic') and not slot_presets.delete(path, 'ibm5150', 'Basic')
    assert slot_presets.names(path, 'ibm5150') == ['Dual 3.5']


# ------------------------------------------------------------------------------------------------------ software lists
SOFTWARE_XML = b'''<?xml version="1.0"?>
<softwarelists>
  <softwarelist name="spectrum_cass" description="Sinclair ZX Spectrum cassettes">
    <software name="jetpac"><description>Jetpac</description><year>1983</year><publisher>Ultimate</publisher>
      <part name="cass" interface="spectrum_cass"><dataarea name="cass"><rom name="jetpac.tzx" size="1"/></dataarea></part>
    </software>
    <software name="jetpaca" cloneof="jetpac" supported="partial"><description>Jetpac (alt)</description>
      <year>1983</year><publisher>Ultimate &amp; Co</publisher></software>
  </softwarelist>
  <softwarelist name="spectrum_cart" description="Sinclair ZX Spectrum cartridges"/>
</softwarelists>'''


def test_software_list_parse():
    lists = software_lists.parse(io.BytesIO(SOFTWARE_XML))
    assert [(sl.name, len(sl.software)) for sl in lists] == [('spectrum_cass', 2), ('spectrum_cart', 0)]
    clone = lists[0].software[1]
    assert (clone.name, clone.supported, clone.cloneof, clone.publisher) == ('jetpaca', 'partial', 'jetpac',
                                                                           'Ultimate & Co')
    assert lists[0].software[0].supported == 'yes'


# ------------------------------------------------------------------------------------------------ MAME upgrade report
def test_mame_upgrade_report():
    M = rom_database.Machine
    old = [M('pacman', 'Pac-Man', '1980', 'Namco', '', (), False, (), 'good'),
           M('oldgame', 'Old Game', '1990', 'X', '', (), False, (), 'good'),
           M('wip', 'Work In Progress', '1985', 'Y', '', (), False, (), 'preliminary')]
    new = [M('pacman', 'Pac-Man', '1980', 'Namco', '', (), False, (), 'good'),
           M('wip', 'Work In Progress', '1985', 'Y', '', (), False, (), 'imperfect'),
           M('newgame', 'New Game', '2026', 'Z', '', (), False, (), 'good')]
    changes = rom_database.compare_machines(old, new, '0.289', '0.290')
    assert changes.added == [('newgame', 'New Game')]
    assert changes.removed == [('oldgame', 'Old Game')]
    assert changes.now_working == [('wip', 'Work In Progress', 'preliminary', 'imperfect')]
    assert changes.summary == 'MAME 0.289 -> 0.290: 1 new machine(s), 1 removed, 1 now working'
    report = rom_database.format_changes(changes)
    assert 'newgame' in report and 'NOW WORKING (1)' in report


def test_version_change_produces_a_report(tmp_path, monkeypatch):
    M = rom_database.Machine
    rom_database.save_machine_cache(str(tmp_path / rom_database.MACHINE_CACHE_NAME), '0.289',
                                    [M('pacman', 'Pac-Man', '1980', 'Namco', '', (), False, ())])  # old-style row
    monkeypatch.setattr(rom_database, 'stream_machines_from_mame',
                        lambda exe, progress=None, cancel=None: (
                            [M('pacman', 'Pac-Man', '1980', 'Namco', '', (), False, (), 'good'),
                             M('newgame', 'New Game', '2026', 'Z', '', (), False, (), 'good')], '0.290'))
    machines, from_cache, changes = rom_database.get_machines('mame', '0.290', str(tmp_path))
    assert not from_cache and changes.added == [('newgame', 'New Game')]
    # Next time the cache matches - no report
    assert rom_database.get_machines('mame', '0.290', str(tmp_path))[2] is None
