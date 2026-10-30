"""Понятные сообщения об ошибках конвертации — на настоящих битых файлах."""
import os
import struct
from pathlib import Path

import pytest

from remap.core import convert_batch, legacy_profile
from remap.core.errors import (
    DAMAGED, NO_ACCESS, NOT_FOUND, NOT_MIDI, OUTPUT_FOLDER_MISSING, UNSUPPORTED_TYPE, describe_error,
    technical_details,
)

SAMPLE = Path(__file__).resolve().parent.parent / "samples" / "midi" / "Groove 01.mid"


def _one(src: Path, output_dir: Path | None = None):
    res = convert_batch([src], legacy_profile(), output_dir=output_dir).files[0]
    assert not res.ok
    return res


def _write(tmp_path, name, data: bytes) -> Path:
    f = tmp_path / name
    f.write_bytes(data)
    return f


def test_truncated_file_is_damaged(tmp_path):
    good = SAMPLE.read_bytes()
    res = _one(_write(tmp_path, "half.mid", good[:len(good) // 2]))
    assert res.error == DAMAGED and res.details == "EOFError"  # голое имя исключения — только в деталях


@pytest.mark.parametrize("data", [b"", SAMPLE.read_bytes()[:10]])
def test_empty_or_header_only_is_damaged(tmp_path, data):
    assert _one(_write(tmp_path, "x.mid", data)).error == DAMAGED


def test_random_bytes_are_not_midi(tmp_path):
    res = _one(_write(tmp_path, "noise.mid", b"\x00\xffjunk" + os.urandom(200)))
    assert res.error == NOT_MIDI and res.details.startswith("OSError: MThd not found")


def test_text_file_renamed_to_mid_is_not_midi(tmp_path):
    assert _one(_write(tmp_path, "notes.mid", b"just some text, not music")).error == NOT_MIDI


def test_broken_track_chunk_is_damaged(tmp_path):
    good = SAMPLE.read_bytes()
    assert _one(_write(tmp_path, "t.mid", good[:14] + b"XXXX" + good[18:])).error == DAMAGED


def test_unknown_midi_type_is_unsupported(tmp_path):
    good = SAMPLE.read_bytes()
    res = _one(_write(tmp_path, "t5.mid", good[:8] + struct.pack(">H", 5) + good[10:]))
    assert res.error == UNSUPPORTED_TYPE and res.details.startswith("ValueError: ")


def test_missing_file(tmp_path):
    res = _one(tmp_path / "gone.mid")
    assert res.error == NOT_FOUND and res.details.startswith("FileNotFoundError: ")


def test_source_is_a_folder_means_no_access(tmp_path):
    folder = tmp_path / "folder.mid"
    folder.mkdir()
    assert _one(folder).error == NO_ACCESS


def test_output_folder_missing_is_about_the_result(tmp_path):
    src = tmp_path / "a.mid"
    src.write_bytes(SAMPLE.read_bytes())
    exc = FileNotFoundError(2, "No such file or directory", str(tmp_path / "out" / "a_remapped.mid"))
    assert describe_error(exc, src, tmp_path / "out" / "a_remapped.mid") == OUTPUT_FOLDER_MISSING


def test_unknown_error_falls_back_to_short_reason():
    assert describe_error(RuntimeError("tempo map exploded\nline 2")) == "Could not convert: tempo map exploded"
    assert describe_error(KeyError()) == "Could not convert: KeyError"
    long = describe_error(ValueError("x" * 300))
    assert long.startswith("Could not convert: xxx") and long.endswith("…") and len(long) < 120


def test_technical_details_type_and_text():
    assert technical_details(EOFError()) == "EOFError"
    assert technical_details(ValueError("bad byte")) == "ValueError: bad byte"
