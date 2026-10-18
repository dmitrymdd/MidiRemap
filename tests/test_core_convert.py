"""Ядро midiremap.core.convert_midi с произвольной картой нот."""
import mido

from midiremap.core import convert_midi


def test_custom_note_map(tmp_path):
    track = mido.MidiTrack([
        mido.Message('note_on', note=36, velocity=100, time=0),
        mido.Message('note_off', note=36, velocity=0, time=10),
        mido.Message('note_on', note=38, velocity=100, time=5),  # нет в карте -> удаляется
        mido.MetaMessage('end_of_track', time=5),
    ])
    midi = mido.MidiFile(type=1, ticks_per_beat=480)
    midi.tracks.append(track)
    src, dst = tmp_path / 'in.mid', tmp_path / 'out.mid'
    midi.save(str(src))

    stats = convert_midi(src, dst, {36: 40})

    assert stats == {'mapped': 2, 'removed': 1, 'other': 1}
    out = mido.MidiFile(str(dst))
    assert [(m.type, m.note, m.time) for m in out.tracks[0] if m.type.startswith('note')] == [
        ('note_on', 40, 0), ('note_off', 40, 10)]
    assert sum(m.time for m in out.tracks[0]) == 20
