"""Названия нот по высоте для UI: номер MIDI-ноты -> «C3» (без Qt и без UI)."""

# Соглашение Toontrack: 60 = C3 (SD3 показывает ноту 36 как C1). Октава = n // 12 + OCTAVE_OFFSET.
OCTAVE_OFFSET = -2

PITCH_CLASSES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")


def pitch_name(note: int) -> str:
    """0 -> C-2, 36 -> C1, 60 -> C3, 127 -> G8."""
    if isinstance(note, bool) or not isinstance(note, int) or not 0 <= note <= 127:
        raise ValueError(f"note number must be an integer 0..127, got {note!r}")
    return f"{PITCH_CLASSES[note % 12]}{note // 12 + OCTAVE_OFFSET}"
