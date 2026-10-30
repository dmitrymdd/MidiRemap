from pathlib import Path

import pytest

from remap.core.notemap import normalize_name
from remap.core.notenames import (
    export_notenames, load_notenames, parse_notenames, save_notenames,
)

ROOT = Path(__file__).resolve().parent.parent
GM = ROOT / 'samples' / 'maps' / 'General_MIDI_GM1.txt'
GP8 = ROOT / 'samples' / 'maps' / 'Guitar_Pro_8.txt'
FIXTURE = ROOT / 'tests' / 'fixtures' / 'reaper_custom_with_order.txt'
SAMPLES = [GM, GP8, FIXTURE]


def parse(text):
    return parse_notenames(text, 't')


@pytest.mark.parametrize('path', SAMPLES, ids=lambda p: p.name)
def test_no_issues_and_round_trip(path):
    m, issues = load_notenames(path)
    assert issues == []
    assert export_notenames(m).encode('utf-8') == path.read_bytes()


def test_gm_counts():
    m, _ = load_notenames(GM)
    assert len(m.names) == 47 and min(m.names) == 35 and max(m.names) == 81


def test_gp8_counts_and_duplicate_name_is_valid():
    m, issues = load_notenames(GP8)
    assert len(m.names) == 94 and min(m.names) == 29 and max(m.names) == 127
    assert m.names[51] == m.names[126] == 'Ride (middle)'
    assert issues == []


def test_fixture_order():
    m, _ = load_notenames(FIXTURE)
    assert len(m.names) == 50
    assert len(m.order) == 50 and set(m.order) == set(m.names)


def test_lf_and_crlf_equal():
    a, ia = parse('# MIDI note/CC name map\n36 Kick\n38 Snare\n')
    b, ib = parse('# MIDI note/CC name map\r\n36 Kick\r\n38 Snare\r\n')
    assert a.names == b.names == {36: 'Kick', 38: 'Snare'}
    assert ia == ib == []
    assert export_notenames(a) == '# MIDI note/CC name map\r\n38 Snare\r\n36 Kick\r\n'


def test_duplicate_number_last_wins():
    m, issues = parse('36 A\n36 B\n')
    assert m.names == {36: 'B'}
    assert len(issues) == 1 and issues[0].line == 2 and issues[0].severity == 'warning'


@pytest.mark.parametrize('line', ['128 X', '-1 X', 'abc'])
def test_bad_lines_warn_and_are_preserved(line):
    m, issues = parse(f'36 Kick\n{line}\n')
    assert m.names == {36: 'Kick'}
    assert [i.line for i in issues] == [2]
    assert m.extra_lines == [line]
    assert export_notenames(m).endswith(f'36 Kick\r\n{line}\r\n')


def test_note_without_name_skipped():
    m, issues = parse('36\n38 Snare\n')
    assert m.names == {38: 'Snare'}
    assert [i.line for i in issues] == [1] and m.extra_lines == []


def test_unknown_line_preserved_before_order_block():
    m, issues = parse('# MIDI note/CC name map\n36 Kick\nfoo bar\nNO 36\n')
    assert len(issues) == 1
    assert export_notenames(m) == '# MIDI note/CC name map\r\n36 Kick\r\nfoo bar\r\nNO 36\r\n'


def test_no_line_to_missing_note_kept_in_order():
    m, issues = parse('36 Kick\nNO 36\nNO 99\nNO 200\n')
    assert m.order == [36, 99, 200]
    assert [i.line for i in issues] == [3, 4]
    assert export_notenames(m).endswith('NO 36\r\nNO 99\r\nNO 200\r\n')


def test_empty_file():
    m, issues = parse('')
    assert m.names == {} and m.order is None and issues == []
    assert export_notenames(m) == '# MIDI note/CC name map\r\n'


def test_cp1251_fallback_and_save_as_utf8(tmp_path):
    src = tmp_path / 'ru.txt'
    src.write_bytes('# MIDI note/CC name map\r\n36 Бас-бочка\r\n'.encode('cp1251'))
    m, issues = load_notenames(src)
    assert m.names == {36: 'Бас-бочка'}
    assert len(issues) == 1 and 'cp1251' in issues[0].message
    dst = tmp_path / 'out.txt'
    save_notenames(m, dst)
    raw = dst.read_bytes()
    assert not raw.startswith(b'\xef\xbb\xbf')
    assert raw.decode('utf-8') == '# MIDI note/CC name map\r\n36 Бас-бочка\r\n'


def test_normalize_name():
    assert normalize_name('  Ride   (Middle) ') == normalize_name('ride (middle)')


# --- экспорт «одна нота на артикуляцию» ---

def _kit():
    from remap.core.notemap import NoteMap
    return NoteMap('kit', {36: 'Kick', 35: 'Kick', 38: 'Snare', 51: 'Ride', 126: 'ride', 42: 'HH', 22: 'HH'},
                   order=[38, 36, 35, 51, 126, 42, 22, 200], extra_lines=['# keep me'], primary={36, 126})


def test_primary_only_notes():
    from remap.core.notenames import primary_only_notes
    keep, skipped = primary_only_notes(_kit())
    assert keep == {36, 38, 126} and skipped == ['HH']


def test_export_primary_only_keeps_no_lines_consistent():
    m = _kit()
    assert export_notenames(m, primary_only=True) == (
        '# MIDI note/CC name map\r\n126 ride\r\n38 Snare\r\n36 Kick\r\n# keep me\r\n'
        'NO 38\r\nNO 36\r\nNO 126\r\n')
    assert export_notenames(m) == export_notenames(m, primary_only=False)
    assert '42 HH' in export_notenames(m)


def test_export_primary_only_without_order():
    from remap.core.notemap import NoteMap
    m = NoteMap('x', {36: 'Kick', 38: 'Snare'})
    assert export_notenames(m, primary_only=True) == export_notenames(m)
