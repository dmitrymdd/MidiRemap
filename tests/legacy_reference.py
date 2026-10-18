"""Замороженная копия convert_midi до этапа 4 — эталон для сравнения с новым движком. Не менять."""
import mido


def reference_convert_midi(src, dst, note_map):
    midi = mido.MidiFile(str(src))
    out = mido.MidiFile(type=midi.type, ticks_per_beat=midi.ticks_per_beat)
    out.charset = midi.charset
    stats = {'mapped': 0, 'removed': 0, 'other': 0}
    for track in midi.tracks:
        new_track = mido.MidiTrack()
        out.tracks.append(new_track)
        carry = 0
        for msg in track:
            carry += msg.time
            if msg.type in ('note_on', 'note_off'):
                target = note_map.get(msg.note)
                if target is None:
                    stats['removed'] += 1
                    continue
                new_track.append(msg.copy(note=target, time=carry))
                stats['mapped'] += 1
            else:
                new_track.append(msg.copy(time=carry))
                stats['other'] += 1
            carry = 0
        if carry:
            if new_track and new_track[-1].type == 'end_of_track':
                new_track[-1].time += carry
            else:
                new_track.append(mido.MetaMessage('end_of_track', time=carry))
    out.save(str(dst))
    return stats
