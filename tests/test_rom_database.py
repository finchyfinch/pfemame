"""ROMs database: streaming -listxml parse, caches, build helpers and the saved database format."""
import io
import shelve

import pytest

import rom_database

LISTXML = b'''<?xml version="1.0"?>
<mame build="0.289 (mame0289)" debug="no" mameconfig="10">
  <machine name="pacman" sourcefile="pacman.cpp">
    <description>Pac-Man (Midway)</description><year>1980</year><manufacturer>Namco (Midway license)</manufacturer>
    <rom name="pacman.6e" size="4096" crc="c1e6ab10"/>
  </machine>
  <machine name="puckman" sourcefile="pacman.cpp" cloneof="pacman" romof="pacman">
    <description>Puck Man &amp; Friends</description><year>1980</year><manufacturer>Namco</manufacturer>
    <rom name="pacman.6e" merge="pacman.6e" size="4096"/>
    <rom name="puckman.6f" size="4096"/>
    <rom name="missing.1" size="4096" status="nodump"/>
  </machine>
  <machine name="z80" sourcefile="z80.cpp" isdevice="yes" runnable="no"><description>Zilog Z80</description></machine>
  <machine name="spectrum" sourcefile="spectrum.cpp">
    <description>ZX Spectrum</description><year>1982</year><manufacturer>Sinclair</manufacturer>
    <device type="cassette" tag="cassette"><instance name="cassette" briefname="cass"/></device>
    <softwarelist tag="cass_list" name="Spectrum_Cass" status="original"/>
  </machine>
</mame>
'''


def test_parse_machines_keeps_what_the_build_needs():
    machines, version = rom_database.parse_machines(io.BytesIO(LISTXML))
    assert version == '0.289'
    by_name = {m.name: m for m in machines}
    assert set(by_name) == {'pacman', 'puckman', 'spectrum'}           # device entries skipped
    assert by_name['puckman'].description == 'Puck Man & Friends'        # entities decoded
    assert by_name['puckman'].roms == ('puckman.6f',)                    # own, dumped files only
    assert by_name['pacman'].roms == ()                                   # only clones need the list
    assert by_name['spectrum'].softwarelists == ('spectrum_cass',)
    assert by_name['spectrum'].has_media and not by_name['pacman'].has_media


def test_truncated_listing_is_an_error():
    with pytest.raises(Exception):
        rom_database.parse_machines(io.BytesIO(LISTXML[:400]))


def test_machine_cache_round_trip_and_version_check(tmp_path):
    machines, _version = rom_database.parse_machines(io.BytesIO(LISTXML))
    path = str(tmp_path / 'machines.cache')
    rom_database.save_machine_cache(path, '0.289', machines)
    assert rom_database.load_machine_cache(path, '0.289') == machines
    assert rom_database.load_machine_cache(path, '0.290') is None
    assert rom_database.load_machine_cache(str(tmp_path / 'missing'), '0.289') is None


def row(name, file_name, exists='0', system=''):
    return [name, file_name, system, exists, '0', '0', '0', 'Maze', '', '', '1980', 'Namco']


def test_set_exists_flags(tmp_path):
    (tmp_path / 'pacman.zip').write_bytes(b'x')
    mylist = [row('Pac-Man', 'pacman'), row('Galaga', 'galaga')]
    assert rom_database.set_exists_flags(mylist, [str(tmp_path)]) == 1
    assert [r[3] for r in mylist] == ['1', '0']


def test_merged_set_clone_found_inside_parent_archive(tmp_path):
    import zipfile
    with zipfile.ZipFile(tmp_path / 'pacman.zip', 'w') as archive:
        archive.writestr('pacman.6e', b'x')
        archive.writestr('puckman.6f', b'x')
    machines, _version = rom_database.parse_machines(io.BytesIO(LISTXML))
    mylist = [row('Pac-Man', 'pacman', exists='1')]
    clones = rom_database.find_merged_clones(mylist, machines, [str(tmp_path)], {})
    assert [(c[1], c[3], c[7]) for c in clones] == [('puckman', '1', 'Maze')]   # category inherited


def test_remove_duplicates_prefers_existing_rows():
    rows = [row('Puck Man', 'puckman', '0'), row('Puck Man', 'puckman', '1'), row('Pac-Man', 'pacman', '0')]
    result = rom_database.remove_duplicates_by_first_two_fields(rows)
    assert sorted((r[1], r[3]) for r in result) == [('pacman', '0'), ('puckman', '1')]


def test_database_round_trip_and_old_format_rejected(tmp_path):
    path = str(tmp_path / 'mylist.db')
    rom_database.save_database(path, [row('Pac-Man', 'pacman')], {'spectrum'})
    mylist, systems = rom_database.load_database(path)
    assert mylist[0][1] == 'pacman' and systems == {'spectrum'}

    old = str(tmp_path / 'old.db')
    with shelve.open(old, flag='n') as db:          # What pfeMAME 3.9.1 and earlier wrote
        db['mylist'] = [row('Pac-Man', 'pacman')]
    with pytest.raises(ValueError):
        rom_database.load_database(old)
