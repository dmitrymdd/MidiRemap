"""Движок convert/analyze: профиль, overrides, слияние многие-в-одну, отчёт и предупреждения."""
from pathlib import Path

import mido
import pytest

from legacy_reference import reference_convert_midi
from midiremap.core import RemapProfile, Rule, analyze, convert, convert_midi, legacy_profile
from midiremap.core.legacy_map import NOTE_MAP
from midiremap.core.notemap import NoteMap

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = sorted((ROOT / 'samples' / 'midi').glob('*.mid'))
ON, OFF, CC = 'note_on', 'note_off', 'control_change'


def on(note, vel=100, ch=0):
    return mido.Message(ON, note=note, velocity=vel, channel=ch)


def off(note, ch=0):
    return mido.Message(OFF, note=note, velocity=0, channel=ch)


def make_midi(path, *tracks, end_at=None):
    """tracks: списки [(абсолютное время, сообщение)]; end_at — абс. время end_of_track каждой дорожки."""
    midi = mido.MidiFile(type=1, ticks_per_beat=480)
    for events in tracks:
        track, now = mido.MidiTrack(), 0
        for t, msg in events:
            track.append(msg.copy(time=t - now))
            now = t
        if end_at is not None:
            track.append(mido.MetaMessage('end_of_track', time=end_at - now))
        midi.tracks.append(track)
    midi.save(str(path))
    return path


def abs_events(track):
    result, now = [], 0
    for msg in track:
        now += msg.time
        result.append((now, msg.copy(time=0)))
    return result


def run(tmp_path, events, profile, end_at=200, **kw):
    src = make_midi(tmp_path / 'in.mid', events, end_at=end_at)
    report = convert(src, tmp_path / 'out.mid', profile, **kw)
    return report, mido.MidiFile(str(tmp_path / 'out.mid')).tracks[0]


def notes_of(track):
    """[(абс. время, тип, нота, velocity, канал)] нотных событий."""
    return [(t, m.type, m.note, m.velocity, m.channel) for t, m in abs_events(track) if m.type in (ON, OFF)]


def profile(rules=None, source=None, target=None):
    return RemapProfile('test', source_map=source, target_map=target, rules=rules or {})


def nmap(name, **names):
    return NoteMap(name, {int(k[1:]): v for k, v in names.items()})


# --- совместимость с первой версией ---

@pytest.mark.parametrize('src', SAMPLES, ids=lambda p: p.name)
def test_legacy_profile_matches_reference_on_samples(tmp_path, src):
    ref_stats = reference_convert_midi(src, tmp_path / 'ref.mid', NOTE_MAP)
    report = convert(src, tmp_path / 'new.mid', legacy_profile())
    wrapper_stats = convert_midi(src, tmp_path / 'wrap.mid', NOTE_MAP)

    ref = (tmp_path / 'ref.mid').read_bytes()
    assert (tmp_path / 'new.mid').read_bytes() == ref
    assert (tmp_path / 'wrap.mid').read_bytes() == ref
    assert report.stats == wrapper_stats == ref_stats
    assert report.merged == report.overlaps == report.orphan_note_offs == 0


def test_legacy_profile_shape():
    p = legacy_profile()
    assert set(p.rules) == set(range(128))
    assert {n: r.dst for n, r in p.rules.items() if r.action == 'map'} == NOTE_MAP
    assert all(r.action == 'delete' for n, r in p.rules.items() if n not in NOTE_MAP)
    assert p.source_map is None and p.target_map is None


def test_analyze_sample():
    src = ROOT / 'samples' / 'midi' / 'Groove 01.mid'
    a = analyze(src, legacy_profile())
    assert a.note_counts == {36: 24, 38: 4, 53: 23, 57: 1}
    assert a.note_tracks == [0] and a.note_channels == [0] and not a.multi_location
    assert a.unresolved == []
    assert analyze(src, profile({36: Rule.keep()})).unresolved == [38, 53, 57]


# --- многие-в-одну ---

def test_many_to_one_same_tick_merged(tmp_path):
    report, track = run(tmp_path, [
        (0, on(51, 80)), (0, on(59, 100)),
        (100, off(51)),
        (110, mido.Message(CC, control=4, value=10)),
        (120, off(59)),
    ], profile({51: Rule.map_to(116), 59: Rule.map_to(116)}))

    assert notes_of(track) == [(0, ON, 116, 100, 0), (120, OFF, 116, 0, 0)]
    assert [(t, m.type) for t, m in abs_events(track)] == [
        (0, ON), (110, CC), (120, OFF), (200, 'end_of_track')]
    assert sum(m.time for m in track) == 200
    assert report.merged == 1 and report.merged_note_offs == 1
    assert report.stats == {'mapped': 2, 'removed': 2, 'other': 2}


def test_merge_keeps_latest_note_off_even_if_from_first_note(tmp_path):
    _, track = run(tmp_path, [
        (0, on(51, 100)), (0, on(59, 60)), (40, off(59)), (150, off(51)),
    ], profile({51: Rule.map_to(116), 59: Rule.map_to(116)}))
    assert notes_of(track) == [(0, ON, 116, 100, 0), (150, OFF, 116, 0, 0)]


def test_same_target_at_different_ticks_not_merged(tmp_path):
    events = [(0, on(51)), (10, on(59)), (50, off(51)), (60, off(59))]
    report, track = run(tmp_path, events, profile({51: Rule.map_to(116), 59: Rule.map_to(116)}))
    assert [n[:3] for n in notes_of(track)] == [(0, ON, 116), (10, ON, 116), (50, OFF, 116), (60, OFF, 116)]
    assert report.merged == 0 and report.overlaps == 1


def test_merge_is_per_channel(tmp_path):
    report, track = run(tmp_path, [
        (0, on(51, ch=0)), (0, on(59, ch=1)), (50, off(51, ch=0)), (50, off(59, ch=1)),
    ], profile({51: Rule.map_to(116), 59: Rule.map_to(116)}))
    assert len(notes_of(track)) == 4
    assert report.merged == 0 and report.overlaps == 0


def test_velocity_zero_note_on_is_note_off(tmp_path):
    report, track = run(tmp_path, [
        (0, on(51, 90)), (0, on(59, 70)), (80, on(59, 0)), (100, on(51, 0)),
    ], profile({51: Rule.map_to(116), 59: Rule.map_to(116)}))
    # note_on vel=0 не участвует в слиянии как note_on и сохраняет свою форму
    assert notes_of(track) == [(0, ON, 116, 90, 0), (100, ON, 116, 0, 0)]
    assert report.merged == 1 and report.merged_note_offs == 1
    assert report.notes[51].count == 1 and report.notes[59].count == 1


def test_orphan_note_off_remapped_and_counted(tmp_path):
    report, track = run(tmp_path, [(5, off(51)), (10, on(51)), (20, off(51))],
                        profile({51: Rule.map_to(116)}))
    assert [n[:3] for n in notes_of(track)] == [(5, OFF, 116), (10, ON, 116), (20, OFF, 116)]
    assert report.orphan_note_offs == 1


# --- правила ---

def test_default_keep_for_unresolved(tmp_path):
    report, track = run(tmp_path, [(0, on(60)), (10, off(60)), (20, on(36)), (30, off(36))],
                        profile({36: Rule.map_to(35)}))
    assert [n[:3] for n in notes_of(track)] == [(0, ON, 60), (10, OFF, 60), (20, ON, 35), (30, OFF, 35)]
    assert report.unresolved_kept == [60]
    r = report.notes[60]
    assert (r.count, r.action, r.dst, r.origin) == (1, 'keep', 60, 'default')
    r = report.notes[36]
    assert (r.count, r.action, r.dst, r.origin) == (1, 'map', 35, 'profile')


def test_explicit_delete_preserves_timing(tmp_path):
    report, track = run(tmp_path, [
        (0, on(36)), (10, on(60)), (20, off(60)), (25, mido.Message(CC, control=1, value=1)), (30, off(36)),
    ], profile({60: Rule.delete(), 36: Rule.keep()}))
    assert [(t, m.type) for t, m in abs_events(track)] == [
        (0, ON), (25, CC), (30, OFF), (200, 'end_of_track')]
    assert report.deleted == 1 and report.unresolved_kept == []
    assert report.notes[60].action == 'delete' and report.notes[60].dst is None
    assert report.stats == {'mapped': 2, 'removed': 2, 'other': 2}


def test_overrides_beat_profile_rules(tmp_path):
    p = profile({60: Rule.map_to(61), 62: Rule.map_to(63)})
    report, track = run(tmp_path, [(0, on(60)), (0, on(62)), (0, on(64))], p,
                        overrides={60: Rule.map_to(70), 62: Rule.delete(), 64: Rule.map_to(65)})
    assert [n[2] for n in notes_of(track)] == [70, 65]
    assert {n: r.origin for n, r in report.notes.items()} == {60: 'override', 62: 'override', 64: 'override'}
    assert report.unresolved_kept == []
    assert p.rules == {60: Rule.map_to(61), 62: Rule.map_to(63)}  # ядро не пишет overrides в профиль


def test_merge_window_not_supported(tmp_path):
    src = make_midi(tmp_path / 'in.mid', [(0, on(36))])
    with pytest.raises(ValueError, match='not supported yet'):
        convert(src, tmp_path / 'out.mid', profile(), merge_window_ticks=10)
    with pytest.raises(ValueError):
        convert(src, tmp_path / 'out.mid', profile(), merge_window_ticks=-1)
    assert not (tmp_path / 'out.mid').exists()


@pytest.mark.parametrize('bad', [{128: Rule.keep()}, {60: 61}])
def test_bad_overrides_rejected(tmp_path, bad):
    src = make_midi(tmp_path / 'in.mid', [(0, on(60))])
    with pytest.raises((ValueError, TypeError)):
        convert(src, tmp_path / 'out.mid', profile(), overrides=bad)


# --- предупреждения ---

def warnings_for(tmp_path, notes, p, overrides=None):
    events = [(i * 10, on(n)) for i, n in enumerate(notes)]
    report, _ = run(tmp_path, events, p, overrides=overrides)
    return report.warnings


def test_missing_target_map_single_warning(tmp_path):
    w = warnings_for(tmp_path, [36, 38, 60], profile({36: Rule.map_to(99)}))
    assert len(w) == 1 and 'no target map' in w[0]


def test_keep_onto_differently_named_note_warns(tmp_path):
    src = nmap('GM', n38='Acoustic Snare', n40='Electric Snare', n42='Closed Hi-Hat')
    tgt = nmap('SD3', n38='Tom 1', n40='  electric   SNARE ', n42='Closed Hi-Hat')
    w = warnings_for(tmp_path, [38, 40, 42], profile({38: Rule.keep()}, src, tgt))
    assert len(w) == 1 and '38' in w[0] and 'Tom 1' in w[0]  # 40 и 42 совпали после нормализации


def test_keep_with_unknown_source_name_warns(tmp_path):
    tgt = nmap('SD3', n38='Snare')
    w = warnings_for(tmp_path, [38], profile(target=tgt))  # нет исходной карты, keep по умолчанию
    assert len(w) == 1 and 'unknown' in w[0]
    w = warnings_for(tmp_path, [38], profile(source=nmap('GM', n36='Kick'), target=tgt))
    assert len(w) == 1 and 'unknown' in w[0]


def test_keep_onto_note_absent_from_target_warns(tmp_path):
    tgt = nmap('SD3', n38='Snare')
    src = nmap('GM', n29='Scratch', n38='Snare')
    # 29 — keep по умолчанию, 60 — явный keep; 38 есть в обеих картах с тем же именем
    w = warnings_for(tmp_path, [29, 38, 60], profile({60: Rule.keep()}, src, tgt))
    assert w == [
        'Note 29 is kept as is, but the target map has no note 29. It will probably not sound.',
        'Note 60 is kept as is, but the target map has no note 60. It will probably not sound.',
    ]


def test_map_to_note_absent_from_target_warns(tmp_path):
    tgt = nmap('SD3', n36='Kick')
    w = warnings_for(tmp_path, [35, 37], profile({35: Rule.map_to(36), 37: Rule.map_to(99)}, target=tgt))
    assert len(w) == 1 and '99' in w[0]


def test_delete_never_warns(tmp_path):
    tgt = nmap('SD3', n36='Kick')
    assert warnings_for(tmp_path, [38], profile({38: Rule.delete()}, target=tgt)) == []


def test_multi_track_warning(tmp_path):
    src = make_midi(tmp_path / 'in.mid', [(0, on(36)), (10, off(36))], [(0, on(38)), (10, off(38))], end_at=20)
    p = profile(target=nmap('T', n36='Kick', n38='Snare'), source=nmap('S', n36='Kick', n38='Snare'))
    assert analyze(src, p).note_tracks == [0, 1]
    report = convert(src, tmp_path / 'out.mid', p)
    assert len(report.warnings) == 1 and 'tracks' in report.warnings[0]
    assert len(mido.MidiFile(str(tmp_path / 'out.mid')).tracks) == 2


def test_multi_channel_warning(tmp_path):
    p = profile(target=nmap('T', n36='Kick'), source=nmap('S', n36='Kick'))
    report, _ = run(tmp_path, [(0, on(36, ch=0)), (10, on(36, ch=9))], p)
    assert len(report.warnings) == 1 and 'channels: 1, 10' in report.warnings[0]
    report, _ = run(tmp_path, [(0, on(36, ch=9)), (10, on(36, ch=9))], p)
    assert report.warnings == []
