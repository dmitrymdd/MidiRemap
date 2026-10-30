"""Двунаправленные профили: выведение обратных правил, reversed(), sync_reverse, формат 2, обратная
конвертация, совпадение основных кабелей со старым правилом показа."""
import json
from dataclasses import replace
from pathlib import Path

import mido
import pytest

from remap.core import FORWARD, REVERSE, ProfileFormatError, RemapProfile, Rule, analyze, convert, legacy_profile
from remap.core.legacy_map import NOTE_MAP
from remap.core.notemap import NoteMap
from remap.core.profile import derive_reverse, missing_rules, primary_pairs, sync_reverse
from remap.core.suggest import apply_suggested, suggestion_targets
from remap.templates import load_map_template
from remap.ui.cable_layout import build_layout

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = sorted(p for p in (ROOT / 'samples' / 'midi').glob('*.mid') if not p.stem.endswith('_remapped'))
M = Rule.map_to


def prof(rules, src=None, tgt=None, reverse=None):
    return RemapProfile('p', src, tgt, rules, reverse)


HATS = NoteMap('T', {42: 'Hat', 44: 'Hat', 46: 'Hat', 36: 'Kick', 38: 'Snare'})


# --- выведение ---

def test_many_to_one_reverse_goes_to_same_number_or_lowest():
    assert derive_reverse(prof({60: M(60), 121: M(60), 124: M(60)})) == {60: M(60)}
    assert derive_reverse(prof({124: M(60), 121: M(60)})) == {60: M(121)}
    # n -> n важнее наименьшей
    assert derive_reverse(prof({35: M(36), 36: M(36)})) == {36: M(36)}


def test_target_aliases_follow_write_to_or_lowest_with_rule():
    # Write to (44) без входящих кабелей — берётся наименьшая нота артикуляции с правилом (42)
    p = prof({10: M(42)}, tgt=replace(HATS, primary={44}))
    assert derive_reverse(p) == {42: M(10), 44: M(10), 46: M(10)}
    # Write to (46) с правилом — алиас без кабелей (44) идёт туда же, куда Write to
    p = prof({10: M(42), 11: M(46)}, tgt=replace(HATS, primary={46}))
    assert derive_reverse(p) == {42: M(10), 44: M(11), 46: M(11)}
    # Write to не выбран — наименьшая с правилом
    p = prof({10: M(42), 11: M(46)}, tgt=HATS)
    assert derive_reverse(p) == {42: M(10), 44: M(10), 46: M(11)}


def test_untouched_notes_get_no_reverse_rule():
    p = prof({36: M(36), 40: Rule.delete(), 38: Rule.keep()}, tgt=HATS)
    assert derive_reverse(p) == {36: M(36)}  # Snare (keep) и Hat (нет кабелей) — без правил
    assert derive_reverse(prof({})) == {}


def test_primary_pairs_one_per_target_note():
    p = prof({60: M(60), 121: M(60), 124: M(60), 35: M(36), 37: M(36)})
    assert primary_pairs(p) == {(60, 60), (35, 36)}
    # заданное обратное правило решает, какой кабель основной
    assert primary_pairs(replace(p, reverse_rules={60: M(124), 36: Rule.delete()})) == {(124, 60)}


# --- reversed / oriented / полнота ---

SRC = NoteMap('S', {35: 'Kick', 36: 'Kick', 38: 'Snare', 40: 'Rim'})
TGT = NoteMap('T', {36: 'Kick', 38: 'Snare', 37: 'Stick'})


def test_reversed_swaps_maps_and_rules():
    p = prof({35: M(36), 36: M(36), 40: M(38), 38: Rule.delete()}, SRC, TGT)
    r = p.reversed()
    assert r.source_map == TGT and r.target_map == SRC
    assert r.rules == {36: M(36), 38: M(40)} and r.reverse_rules == p.rules
    assert p.oriented(FORWARD) is p and p.oriented(REVERSE).to_dict() == r.to_dict()
    with pytest.raises(ValueError):
        p.oriented('sideways')


def test_reversed_is_an_involution_by_content():
    p = prof({35: M(36), 36: M(36), 40: M(38)}, SRC, TGT)
    back = p.reversed().reversed()
    assert back.reverse_rules == derive_reverse(p)  # выведенные стали заданными явно
    assert back != p and back.to_dict() == p.to_dict()
    q = replace(p, reverse_rules={36: M(35), 37: Rule.delete()})
    assert q.reversed().reversed() == q  # заданные — совпадает и объект


def test_missing_rules_per_direction():
    p = prof({35: M(36), 36: M(36)}, SRC, TGT)
    assert missing_rules(p, FORWARD) == [38, 40]
    assert missing_rules(p, REVERSE) == [37, 38]
    assert missing_rules(prof({35: M(36)}), REVERSE) == []  # без карты — пусто


# --- sync_reverse ---

def test_sync_reverse_follows_forward_edits():
    before = prof({35: M(36)}, SRC, TGT)
    stored = replace(before, reverse_rules=derive_reverse(before))
    after = replace(stored, rules={35: M(36), 40: M(38)})  # новый кабель
    assert sync_reverse(stored, after) == {36: M(35), 38: M(40)}
    after2 = replace(stored, rules={35: M(36), 36: M(36)})  # n -> n отбирает основной
    assert sync_reverse(stored, after2) == {36: M(36)}
    after3 = replace(stored, rules={})  # кабель снят — правило уходит
    assert sync_reverse(stored, after3) == {}


def test_sync_reverse_keeps_manual_rules_and_none():
    before = prof({35: M(36), 40: M(38)}, SRC, TGT, reverse={36: M(36), 38: M(40)})  # 36 -> 36 задано вручную
    after = replace(before, rules={35: M(36)})
    assert sync_reverse(before, after) == {36: M(36)}  # ручное 36 не тронуто, 38 ушло вслед за кабелем
    p = prof({35: M(36)}, SRC, TGT)
    assert sync_reverse(p, replace(p, rules={})) is None


# --- JSON ---

def test_json_format_2_round_trip_with_manual_reverse():
    src = replace(SRC, primary={36})
    p = prof({35: M(36), 36: M(36)}, src, TGT, reverse={36: M(35), 37: Rule.delete(), 38: Rule.keep()})
    data = json.loads(p.to_json())
    assert data['format'] == 2 and data['source_map']['primary'] == [36]
    assert data['reverse_rules'] == [{'src': 36, 'action': 'map', 'dst': 35}, {'src': 37, 'action': 'delete'},
                                     {'src': 38, 'action': 'keep'}]
    back = RemapProfile.from_json(p.to_json())
    assert back == p and back.source_map.primary == {36}


def test_derived_reverse_is_written_and_read_back_as_derived():
    p = prof({35: M(36), 40: M(38)}, SRC, TGT)
    data = json.loads(p.to_json())
    assert data['reverse_rules'] == [{'src': 36, 'action': 'map', 'dst': 35}, {'src': 38, 'action': 'map', 'dst': 40}]
    back = RemapProfile.from_json(p.to_json())
    assert back.reverse_rules is None and back == p  # равны выведенным — снова None


def test_format_1_still_reads():
    text = json.dumps({'format': 1, 'name': 'old', 'rules': [{'src': 35, 'action': 'map', 'dst': 36}],
                       'reverse_rules': [{'src': 36, 'action': 'delete'}]})  # у формата 1 поле не читается
    p = RemapProfile.from_json(text)
    assert p.reverse_rules is None and p.effective_reverse() == {36: M(35)}
    p2 = RemapProfile.from_json(json.dumps({'format': 2, 'name': 'x', 'rules': []}))  # формат 2 без поля
    assert p2.reverse_rules is None


@pytest.mark.parametrize('reverse', [
    {},                                                                        # не список
    [{'src': 36, 'action': 'keep'}, {'src': 36, 'action': 'delete'}],          # дубль
    [{'src': 200, 'action': 'keep'}],
    [{'src': 36, 'action': 'map'}],                                            # map без dst
])
def test_bad_reverse_rules_raise_format_error(reverse):
    with pytest.raises(ProfileFormatError):
        RemapProfile.from_json(json.dumps({'format': 2, 'name': 'x', 'rules': [], 'reverse_rules': reverse}))


# --- обратная конвертация ---

def note_events(path):
    out, now = [], 0
    for msg in mido.MidiFile(str(path)).tracks[0]:
        now += msg.time
        if msg.type in ('note_on', 'note_off'):
            out.append((now, msg.type, msg.note, msg.velocity))
    return out


def test_reverse_conversion_uses_reverse_rules(tmp_path):
    src = tmp_path / 'in.mid'
    midi = mido.MidiFile(type=1, ticks_per_beat=480)
    track = mido.MidiTrack()
    for i, n in enumerate((36, 38, 50)):
        track += [mido.Message('note_on', note=n, velocity=100, time=0 if i == 0 else 10),
                  mido.Message('note_off', note=n, velocity=0, time=5)]
    midi.tracks.append(track)
    midi.save(str(src))
    p = prof({35: M(36), 36: M(36), 40: M(38)}, SRC, TGT)
    assert analyze(src, p, REVERSE).unresolved == [50]
    report = convert(src, tmp_path / 'out.mid', p, direction=REVERSE)
    assert [e[2] for e in note_events(tmp_path / 'out.mid')] == [36, 36, 40, 40, 50, 50]
    assert report.unresolved_kept == [50] and report.notes[38].dst == 40
    with pytest.raises(ValueError):
        convert(src, tmp_path / 'x.mid', p, direction='sideways')


@pytest.mark.parametrize('sample', SAMPLES, ids=lambda p: p.name)
def test_round_trip_on_samples(tmp_path, sample):
    """GM -> SD3 по схеме первой версии и обратно: основные ноты возвращаются на свои номера,
    прочие — на основную ноту своей цели."""
    p = legacy_profile()
    convert(sample, tmp_path / 'fwd.mid', p)
    convert(tmp_path / 'fwd.mid', tmp_path / 'back.mid', p, direction=REVERSE)
    rev = p.effective_reverse()
    expected = {a: rev[b].dst for a, b in NOTE_MAP.items()}
    original = [e for e in note_events(sample) if e[2] in NOTE_MAP]
    back = note_events(tmp_path / 'back.mid')
    assert {e[2] for e in back} == {expected[e[2]] for e in original}
    if all(expected[e[2]] == e[2] for e in original):  # все ноты файла — основные: файл возвращается как был
        assert back == original


# --- основной кабель: совпадение со старым правилом показа (_mark_primary) ---

def old_mark_primary(cables):
    """Эталон прежнего правила показа: на ноту цели — n -> n, иначе наименьшая из идущих на неё (по кабелям сцены)."""
    by_dst = {}
    for c in cables:
        if not c.suggested and c.dst is not None:
            by_dst.setdefault(c.dst, []).extend(c.notes)
    main = {(d if d in notes else min(notes), d) for d, notes in by_dst.items()}
    return [any((n, c.dst) in main for n in c.notes) for c in cables]


def suggested_profile(src_id, tgt_id):
    src, tgt = load_map_template(src_id), load_map_template(tgt_id)
    p, _ = apply_suggested(RemapProfile('p', src, tgt), suggestion_targets(src, tgt))
    return p


def with_many_to_one(p):
    """Все ноты без правила — на 38 и на 39 через одну (многие-в-одну, n -> n нет или есть)."""
    free = [n for n in sorted(p.source_map.names) if n not in p.rules]
    for i, n in enumerate(free):
        p.rules[n] = M(38 if i % 2 else 39)
    return p


@pytest.mark.parametrize('make', [
    legacy_profile,
    lambda: suggested_profile('EZdrummer 3', 'Superior Drummer 3'),
    lambda: suggested_profile('Superior Drummer 3', 'EZdrummer 3'),
    lambda: RemapProfile('p', load_map_template('General MIDI'), load_map_template('Superior Drummer 3'),
                         legacy_profile().rules),
    lambda: with_many_to_one(suggested_profile('EZdrummer 3', 'Superior Drummer 3')),
], ids=['legacy', 'ezd3-sd3', 'sd3-ezd3', 'legacy-gm-sd3', 'ezd3-sd3-many'])
def test_primary_cables_match_old_rule(make):
    p = make()
    assert any(r.action == 'map' for r in p.rules.values())
    cables = [c for c in build_layout(p, set()).scene.cables if not c.suggested]
    assert [c.primary for c in cables] == old_mark_primary(cables)
    # и по профилю: ровно один основной кабель на каждую ноту цели с кабелями
    pairs = primary_pairs(p)
    targets = {r.dst for r in p.rules.values() if r.action == 'map'}
    assert sorted(b for _, b in pairs) == sorted(targets)
