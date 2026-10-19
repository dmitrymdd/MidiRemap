import json

import pytest

from midiremap.core.notemap import (
    MapFormatError, MapMeta, NoteMap, articulations, map_from_json, map_to_dict, map_to_json,
    primary_note, validate_map,
)
from midiremap.core.pitch import OCTAVE_OFFSET, pitch_name
from midiremap.core.profile import RemapProfile, Rule


def kit(primary=()):
    # Ride на трёх нотах, Kick на двух (с разным регистром/пробелами), Snare — одна нота
    return NoteMap('kit', {36: 'Kick', 35: ' kick ', 38: 'Snare', 51: 'Ride', 59: 'Ride', 126: 'Ride'},
                   primary=set(primary))


# --- primary ---

def test_articulations_group_by_normalized_name():
    assert articulations(kit()) == {'kick': [35, 36], 'snare': [38], 'ride': [51, 59, 126]}


def test_primary_note():
    m = kit(primary=[51])
    assert primary_note(m, 'snare') == 38          # одна нота — флаг не нужен
    assert primary_note(m, 'RIDE') == 51
    assert primary_note(m, 'Kick') is None         # несколько нот, основная не отмечена
    assert primary_note(m, 'Tom') is None          # имени нет


def test_primary_note_ambiguous_flags():
    assert primary_note(kit(primary=[51, 59]), 'Ride') is None


def test_validate_clean_map():
    assert validate_map(kit(primary=[36, 51, 38])) == []  # флаг на одиночной ноте — допустим


def test_validate_issues():
    issues = validate_map(kit(primary=[51, 59, 100]))
    errors = [i for i in issues if i.severity == 'error']
    warnings = [i for i in issues if i.severity == 'warning']
    assert sorted(i.notes for i in errors) == [[51, 59], [100]]
    assert [i.notes for i in warnings] == [[35, 36]]  # Kick без основной ноты


# --- JSON карты ---

def test_map_json_round_trip():
    m = NoteMap('Моя карта', {36: 'Бочка', 38: 'Snare', 126: 'Ride', 51: 'Ride'}, order=[38, 36, 200],
                extra_lines=['# comment'], primary={51},
                meta=MapMeta(source='SD3 window', status='verified', notes='checked'))
    text = map_to_json(m)
    data = json.loads(text)
    assert data['format'] == 1 and data['kind'] == 'notemap'
    assert data['names'] == {'36': 'Бочка', '38': 'Snare', '51': 'Ride', '126': 'Ride'}
    assert data['primary'] == [51]
    assert data['meta'] == {'source': 'SD3 window', 'status': 'verified', 'notes': 'checked'}
    assert 'Бочка' in text  # ensure_ascii=False
    assert map_from_json(text) == m


def test_map_json_defaults():
    m = map_from_json('{"format": 1, "kind": "notemap", "name": "x"}')
    assert m == NoteMap('x')
    assert map_to_dict(m)['meta'] == {'source': None, 'status': 'unverified', 'notes': None}


@pytest.mark.parametrize('text', [
    '{not json',
    '[]',
    '{"format": 1, "name": "x"}',                                        # нет kind
    '{"format": 1, "kind": "profile", "name": "x"}',
    '{"format": 2, "kind": "notemap", "name": "x"}',
    '{"format": 1, "kind": "notemap"}',                                  # нет name
    '{"format": 1, "kind": "notemap", "name": "x", "names": {"200": "A"}}',
    '{"format": 1, "kind": "notemap", "name": "x", "primary": [128]}',
    '{"format": 1, "kind": "notemap", "name": "x", "primary": 36}',
    '{"format": 1, "kind": "notemap", "name": "x", "meta": {"status": "maybe"}}',
    '{"format": 1, "kind": "notemap", "name": "x", "meta": {"source": 5}}',
])
def test_bad_map_json(text):
    with pytest.raises(MapFormatError):
        map_from_json(text)


# --- карты, встроенные в профиль ---

def test_profile_embedded_map_keeps_primary_and_meta():
    target = kit(primary=[51])
    target.meta = MapMeta(source='SD3 window', status='verified', notes='n')
    p = RemapProfile('p', target_map=target, rules={36: Rule.map_to(36)})
    data = json.loads(p.to_json())
    assert data['format'] == 1 and data['target_map']['primary'] == [51]
    assert data['target_map']['meta'] == {'source': 'SD3 window', 'status': 'verified', 'notes': 'n'}
    back = RemapProfile.from_json(p.to_json())
    assert back == p and back.target_map.meta.status == 'verified'


def test_old_profile_without_primary_and_meta_loads():
    text = ('{"format": 1, "name": "old", "source_map": null, "rules": [],'
            ' "target_map": {"name": "m", "names": {"36": "Kick"}, "order": null, "extra_lines": []}}')
    p = RemapProfile.from_json(text)
    assert p.target_map.names == {36: 'Kick'} and p.target_map.primary == set()
    assert p.target_map.meta == MapMeta()


def test_profile_with_bad_embedded_meta_rejected():
    from midiremap.core.profile import ProfileFormatError
    text = ('{"format": 1, "name": "x", "rules": [],'
            ' "target_map": {"name": "m", "meta": {"status": "maybe"}}}')
    with pytest.raises(ProfileFormatError):
        RemapProfile.from_json(text)


# --- названия нот по высоте ---

@pytest.mark.parametrize('note, name', [(0, 'C-2'), (36, 'C1'), (37, 'C#1'), (60, 'C3'), (127, 'G8')])
def test_pitch_name(note, name):
    assert pitch_name(note) == name


def test_pitch_offset_constant():
    assert OCTAVE_OFFSET == -2


@pytest.mark.parametrize('bad', [-1, 128, True, 36.0])
def test_pitch_name_rejects_bad(bad):
    with pytest.raises(ValueError):
        pitch_name(bad)
