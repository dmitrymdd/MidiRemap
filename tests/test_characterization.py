"""Характеризационные тесты: схема первой версии программы (NOTE_MAP, legacy_profile(): ноты вне NOTE_MAP
удаляются) — поведение первой версии на Tkinter как эталон, теперь через convert().
Сравнивается содержимое (абсолютное время в тиках + сообщение), не байты файлов.
"""
from collections import Counter
from pathlib import Path

import mido
import pytest

from remap.core import convert, legacy_profile
from remap.core.legacy_map import NOTE_MAP

ROOT = Path(__file__).resolve().parent.parent


def convert_legacy(src, dst):
    return convert(src, dst, legacy_profile()).stats

MIDI_DIR = ROOT / 'samples' / 'midi'
NOTE_TYPES = ('note_on', 'note_off')


def abs_events(track):
    """[(абсолютное время в тиках, сообщение с time=0)] — форма, не зависящая от delta-кодирования."""
    result, now = [], 0
    for msg in track:
        now += msg.time
        result.append((now, msg.copy(time=0)))
    return result


def track_length(track):
    return sum(m.time for m in track)


def note_on_counts(midi):
    return Counter(m.note for t in midi.tracks for m in t if m.type == 'note_on' and m.velocity > 0)


def non_note(events):
    return [(t, m) for t, m in events if m.type not in NOTE_TYPES]


def run(src, tmp_path):
    dst = tmp_path / 'out.mid'
    stats = convert_legacy(src, dst)
    return stats, mido.MidiFile(str(src)), mido.MidiFile(str(dst))


GROOVES = [
    ('Groove 01.mid', {'mapped': 104, 'removed': 0, 'other': 12},
     {36: 24, 38: 4, 57: 1, 117: 23}),
    ('Groove 03.mid', {'mapped': 60, 'removed': 0, 'other': 8},
     {36: 18, 38: 2, 41: 6, 47: 4}),
]


@pytest.mark.parametrize('name, stats_expected, notes_expected', GROOVES)
class TestSamples:
    def test_stats_and_note_counts(self, tmp_path, name, stats_expected, notes_expected):
        stats, _, out = run(MIDI_DIR / name, tmp_path)
        assert stats == stats_expected
        assert note_on_counts(out) == Counter(notes_expected)

    def test_structure_preserved(self, tmp_path, name, stats_expected, notes_expected):
        _, src, out = run(MIDI_DIR / name, tmp_path)
        assert out.type == src.type
        assert out.ticks_per_beat == src.ticks_per_beat
        assert len(out.tracks) == len(src.tracks)
        for s, o in zip(src.tracks, out.tracks, strict=True):
            assert len(o) == len(s)
            assert track_length(o) == track_length(s)

    def test_non_note_events_preserved(self, tmp_path, name, stats_expected, notes_expected):
        _, src, out = run(MIDI_DIR / name, tmp_path)
        for s, o in zip(src.tracks, out.tracks, strict=True):
            assert non_note(abs_events(o)) == non_note(abs_events(s))

    def test_unknown_meta_preserved(self, tmp_path, name, stats_expected, notes_expected):
        _, src, out = run(MIDI_DIR / name, tmp_path)

        def count(m):
            return sum(1 for t in m.tracks for x in t if x.type == 'unknown_meta')

        assert count(src) == 5
        assert count(out) == 5

    def test_note_events_are_source_with_mapped_note(self, tmp_path, name, stats_expected, notes_expected):
        _, src, out = run(MIDI_DIR / name, tmp_path)
        for s, o in zip(src.tracks, out.tracks, strict=True):
            s_notes = [(t, m) for t, m in abs_events(s) if m.type in NOTE_TYPES]
            o_notes = [(t, m) for t, m in abs_events(o) if m.type in NOTE_TYPES]
            assert len(o_notes) == len(s_notes)
            for (st, sm), (ot, om) in zip(s_notes, o_notes, strict=True):
                assert ot == st
                assert om == sm.copy(note=NOTE_MAP[sm.note])


def test_groove01_source_note_53_is_gone(tmp_path):
    _, src, out = run(MIDI_DIR / 'Groove 01.mid', tmp_path)
    assert any(m.note == 53 for t in src.tracks for m in t if m.type in NOTE_TYPES)
    assert not any(m.note == 53 for t in out.tracks for m in t if m.type in NOTE_TYPES)


def build_midi(path, events, end_at=None):
    """events: [(абсолютное время, сообщение)]; end_at — абсолютное время end_of_track (None — без него)."""
    track = mido.MidiTrack()
    now = 0
    for t, msg in events:
        track.append(msg.copy(time=t - now))
        now = t
    if end_at is not None:
        track.append(mido.MetaMessage('end_of_track', time=end_at - now))
    midi = mido.MidiFile(type=1, ticks_per_beat=480)
    midi.tracks.append(track)
    midi.save(str(path))


def synthetic_events():
    msg = mido.Message
    return [
        (10, msg('note_on', note=60, velocity=90)),      # не в NOTE_MAP, первое событие
        (20, msg('note_on', note=36, velocity=100)),
        (30, msg('note_off', note=36, velocity=0)),
        (40, msg('note_on', note=54, velocity=80)),      # не в NOTE_MAP, посреди
        (50, msg('control_change', control=7, value=64)),
        (55, msg('note_on', note=54, velocity=70)),      # два удалённых подряд
        (60, msg('note_on', note=38, velocity=110)),
        (70, msg('note_off', note=38, velocity=0)),
        (90, msg('note_off', note=60, velocity=0)),      # не в NOTE_MAP, последнее перед end_of_track
    ]


def test_synthetic_unmapped_notes_removed_without_time_shift(tmp_path):
    assert 60 not in NOTE_MAP and 54 not in NOTE_MAP
    src_path = tmp_path / 'in.mid'
    events = synthetic_events()
    build_midi(src_path, events, end_at=100)
    stats = convert_legacy(src_path, tmp_path / 'out.mid')
    out = mido.MidiFile(str(tmp_path / 'out.mid'))

    assert stats == {'mapped': 4, 'removed': 4, 'other': 2}  # other = control_change + end_of_track
    expected = [
        (20, events[1][1].copy(note=36)),
        (30, events[2][1].copy(note=36)),
        (50, events[4][1]),
        (60, events[6][1].copy(note=NOTE_MAP[38])),
        (70, events[7][1].copy(note=NOTE_MAP[38])),
        (100, mido.MetaMessage('end_of_track')),
    ]
    assert abs_events(out.tracks[0]) == expected
    assert track_length(out.tracks[0]) == 100


def test_known_behavior_all_channels_remapped_and_unmapped_removed(tmp_path):
    """Схема первой версии: ноты на ЛЮБОМ канале ремапятся; ноты, которых нет в NOTE_MAP, удаляются
    (явный delete в legacy_profile; без правила по умолчанию — keep, см. test_convert_engine.py).
    """
    src_path = tmp_path / 'in.mid'
    build_midi(src_path, [
        (0, mido.Message('note_on', channel=0, note=39, velocity=100)),
        (10, mido.Message('note_on', channel=9, note=51, velocity=100)),
        (20, mido.Message('note_on', channel=5, note=53, velocity=100)),
        (30, mido.Message('note_on', channel=3, note=60, velocity=100)),
    ], end_at=40)
    stats = convert_legacy(src_path, tmp_path / 'out.mid')
    out = mido.MidiFile(str(tmp_path / 'out.mid'))
    notes = [(t, m.channel, m.note) for t, m in abs_events(out.tracks[0]) if m.type == 'note_on']
    assert notes == [(0, 0, 40), (10, 9, 116), (20, 5, 117)]
    assert stats['removed'] == 1
