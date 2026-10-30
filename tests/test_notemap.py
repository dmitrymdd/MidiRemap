import json

import pytest

from remap.core.notemap import (
    MapFormatError, MapMeta, NoteMap, articulations, duplicate_map, finalize_edit, map_from_json,
    map_to_dict, map_to_json, primary_note, set_note_name, validate_map,
)
from remap.core.pitch import OCTAVE_OFFSET, note_tip, pitch_name
from remap.core.profile import RemapProfile, Rule


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
    assert data['format'] == 2 and data['target_map']['primary'] == [51]
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
    from remap.core.profile import ProfileFormatError
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


def test_note_tip():
    assert note_tip([37]) == "Note 37 · C#1" and note_tip((37, 76)) == "Notes 37 · C#1, 76 · E4"


# --- копирование и правка ---

def verified_kit():
    m = kit(primary=[51])
    m.order = [126, 59, 51, 38, 36, 35, 200]  # 200 — номер вне карты, как бывает в файлах REAPER
    m.meta = MapMeta(source='SD3 window', status='verified', notes=None)
    return m


def test_duplicate_map_copies_meta():
    m = verified_kit()
    c = duplicate_map(m, 'copy')
    assert c.name == 'copy' and c.meta == m.meta and c.names == m.names and c.primary == m.primary
    c.names[1] = 'x'
    c.primary.add(36)
    assert 1 not in m.names and 36 not in m.primary  # глубокая копия


def test_duplicate_template_appends_note():
    m = verified_kit()
    assert duplicate_map(m, 'c', from_template=True).meta.notes == 'Based on template kit'
    m.meta.notes = 'Old note.'
    c = duplicate_map(m, 'c', from_template=True)
    assert c.meta.notes == 'Old note.\nBased on template kit'
    assert c.meta.source == 'SD3 window' and c.meta.status == 'verified'


def test_finalize_primary_only_edit_keeps_status():
    base = verified_kit()
    edited = duplicate_map(base, base.name)
    edited.primary = {59, 35}
    out = finalize_edit(base, edited)
    assert out.meta.status == 'verified' and out.primary == {59, 35}


@pytest.mark.parametrize('change', [
    lambda m: m.names.__setitem__(38, 'Snare hit'),  # правка имени
    lambda m: m.names.__setitem__(40, 'Rim'),  # добавление
    lambda m: m.names.pop(38),  # удаление
])
def test_finalize_name_edit_makes_unverified(change):
    base = verified_kit()
    edited = duplicate_map(base, base.name)
    change(edited)
    out = finalize_edit(base, edited)
    assert out.meta.status == 'unverified' and out.meta.source == 'SD3 window'
    assert base.meta.status == 'verified' and edited.meta.status == 'verified'  # аргументы не меняются


def test_finalize_drops_deleted_notes_from_order_and_primary():
    base = verified_kit()
    edited = duplicate_map(base, base.name)
    del edited.names[51], edited.names[38]
    edited.names[40] = 'Rim'  # новая нота в order не добавляется (порядок пока не редактируется)
    out = finalize_edit(base, edited)
    assert out.order == [126, 59, 36, 35, 200]
    assert out.primary == set()
    assert out.extra_lines == base.extra_lines


def test_finalize_clears_primary_of_single_note_names():
    base = kit(primary=[36, 51])
    edited = duplicate_map(base, base.name)
    edited.names[35] = 'Kick 2'  # Kick остался на одной ноте — флаг не нужен
    out = finalize_edit(base, edited)
    assert out.primary == {51}
    assert validate_map(out) == [i for i in validate_map(out) if i.severity == 'warning']


def test_set_note_name_drops_primary_only_when_articulation_changes():
    m = NoteMap('m', {38: 'Snare', 40: 'Snare', 42: 'Hat'}, primary={38})
    assert not set_note_name(m, 42, ' Hat ')  # то же имя (края обрезаются) — без изменений
    assert set_note_name(m, 38, '  SNARE ') and m.names[38] == 'SNARE' and m.primary == {38}  # та же артикуляция
    assert set_note_name(m, 38, 'Tom') and m.primary == set()  # другая артикуляция — флаг снят
    m.primary = {40}
    assert set_note_name(m, 40, '') and 40 not in m.names and m.primary == set()  # нота убрана
    assert set_note_name(m, 50, 'Ride') and m.names[50] == 'Ride'  # новая нота
