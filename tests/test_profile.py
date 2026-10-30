import json
from pathlib import Path

import pytest

from remap.core.notemap import NoteMap
from remap.core.notenames import load_notenames
from remap.core.profile import ProfileFormatError, RemapProfile, Rule, legacy_profile

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / 'tests' / 'fixtures' / 'reaper_custom_with_order.txt'


def test_rule_validation():
    assert Rule.map_to(36) == Rule('map', 36)
    assert Rule.delete().dst is None and Rule.keep().dst is None
    for bad in [lambda: Rule('map'), lambda: Rule('map', 128), lambda: Rule('map', -1),
                lambda: Rule('map', True), lambda: Rule('keep', 36), lambda: Rule('delete', 1),
                lambda: Rule('move', 36)]:
        with pytest.raises(ValueError):
            bad()


def test_profile_validates_src_and_rule_type():
    with pytest.raises(ValueError):
        RemapProfile('p', rules={128: Rule.keep()})
    with pytest.raises(TypeError):
        RemapProfile('p', rules={36: 38})


def test_maps_are_embedded_copies():
    m = NoteMap('GM', {36: 'Kick'})
    p = RemapProfile('p', source_map=m)
    m.names[36] = 'changed'
    assert p.source_map.names == {36: 'Kick'}


def test_round_trip_without_maps():
    p = RemapProfile('Без карт', rules={60: Rule.delete(), 36: Rule.map_to(35), 38: Rule.keep()})
    text = p.to_json()
    data = json.loads(text)
    assert data['format'] == 2 and data['source_map'] is None and data['target_map'] is None
    assert data['rules'] == [{'src': 36, 'action': 'map', 'dst': 35},
                             {'src': 38, 'action': 'keep'},
                             {'src': 60, 'action': 'delete'}]
    assert RemapProfile.from_json(text) == p


def test_round_trip_with_maps_cyrillic_order_and_extra_lines():
    src, _ = load_notenames(FIXTURE)  # с NO-строками (order)
    tgt = NoteMap('Цель', {36: 'Бочка', 38: 'Малый', 51: 'Райд', 126: 'Райд'},
                  order=[38, 36, 200], extra_lines=['# комментарий', 'foo bar'])
    p = RemapProfile('Профиль «тест»', src, tgt, {n: Rule.map_to(36) for n in (35, 36)})
    text = p.to_json()
    assert 'Бочка' in text and '\\u' not in text  # ensure_ascii=False
    assert '"36": "Бочка"' in text  # ключи нот — строки в JSON
    back = RemapProfile.from_json(text)
    assert back == p
    assert back.target_map.order == [38, 36, 200] and back.source_map.order == src.order
    assert all(isinstance(k, int) for k in back.target_map.names)


def test_template_map_meta_survives_profile_round_trip(tmp_path):
    from remap.storage import Storage
    from remap.templates import load_map_template
    sd3 = load_map_template('Superior Drummer 3')
    assert sd3.meta.status == 'verified' and sd3.meta.source
    p = RemapProfile('GM → SD3', target_map=sd3, rules={35: Rule.map_to(36)})
    assert json.loads(p.to_json())['target_map']['meta']['status'] == 'verified'
    back = RemapProfile.from_json(p.to_json())
    assert back.target_map.meta == sd3.meta and back == p
    st = Storage(tmp_path / 'data')
    assert st.load_profile(st.save_profile(p)).target_map.meta == sd3.meta


def test_legacy_profile_round_trip():
    p = legacy_profile()
    assert RemapProfile.from_json(p.to_json()) == p


@pytest.mark.parametrize('version', [3, 0, '1', '2', None, True])
def test_unknown_format_version(version):
    with pytest.raises(ProfileFormatError, match='version'):
        RemapProfile.from_json(json.dumps({'format': version, 'name': 'x', 'rules': []}))


@pytest.mark.parametrize('text', [
    'not json',
    '[]',
    '{"name": "x", "rules": []}',                                                  # нет format
    '{"format": 1, "rules": []}',                                                   # нет name
    '{"format": 1, "name": "x", "rules": [{"src": 36, "action": "map"}]}',          # map без dst
    '{"format": 1, "name": "x", "rules": [{"src": 200, "action": "keep"}]}',
    '{"format": 1, "name": "x", "rules": [{"src": 36, "action": "keep"}, {"src": 36, "action": "delete"}]}',
    '{"format": 1, "name": "x", "rules": [], "source_map": {"name": "m", "names": {"abc": "Kick"}}}',
    '{"format": 1, "name": "x", "rules": [], "target_map": {"name": "m", "names": {"300": "Kick"}}}',
])
def test_bad_profiles_raise_format_error(text):
    with pytest.raises(ProfileFormatError):
        RemapProfile.from_json(text)
