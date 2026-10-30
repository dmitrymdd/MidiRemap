"""Итоги отчёта (hits / notes, moved / unchanged / deleted) и пакетная конвертация."""
import shutil
from pathlib import Path

import mido

from remap.core import (
    CategoryCount, ConversionReport, RemapProfile, Rule, analyze, convert, convert_batch, output_path_for,
)

SAMPLE = Path(__file__).resolve().parents[1] / "samples" / "midi" / "Groove 01.mid"


def _profile():
    notes = sorted(analyze(SAMPLE, RemapProfile(name="p")).note_counts)
    return notes, RemapProfile(name="p", rules={notes[0]: Rule.map_to((notes[0] + 1) % 128),
                                                notes[1]: Rule.delete(), notes[2]: Rule.map_to(notes[2])})


# --- итоги отчёта ---

def test_report_totals_categories(tmp_path):
    notes, profile = _profile()
    moved, deleted, same, default = notes[:4]
    counts = analyze(SAMPLE, profile).note_counts
    report = convert(SAMPLE, tmp_path / "o.mid", profile)
    t = report.totals()
    assert t.moved == CategoryCount(counts[moved], 1)
    assert t.deleted == CategoryCount(counts[deleted], 1)
    # тот же номер — и по явному правилу n -> n, и без правила (keep по умолчанию)
    assert t.unchanged == CategoryCount(sum(counts[n] for n in notes if n not in (moved, deleted)), len(notes) - 2)
    assert t.hits == sum(counts.values()) and t.notes == len(notes)
    assert report.notes[same].category == "unchanged" and report.notes[default].category == "unchanged"
    assert report.notes[moved].category == "moved" and report.notes[deleted].category == "deleted"


def test_report_totals_keep_rule_is_unchanged_and_empty_is_zero(tmp_path):
    notes, _ = _profile()
    report = convert(SAMPLE, tmp_path / "o.mid", RemapProfile(name="k", rules={notes[0]: Rule.keep()}))
    assert report.notes[notes[0]].category == "unchanged"
    assert ConversionReport().totals().hits == 0 and ConversionReport().totals().moved == CategoryCount()


# --- пакетная конвертация ---

def _bad(path: Path) -> Path:
    path.write_bytes(b"this is not a midi file")
    return path


def test_output_path_for():
    assert output_path_for(Path("a/b/x.mid")) == Path("a/b/x_remapped.mid")
    assert output_path_for(Path("a/b/x.MIDI"), Path("out")) == Path("out/x_remapped.mid")


def test_batch_next_to_sources_with_one_failure(tmp_path):
    _, profile = _profile()
    good1, good2 = tmp_path / "a.mid", tmp_path / "c.mid"
    shutil.copy(SAMPLE, good1)
    shutil.copy(SAMPLE, good2)
    bad = _bad(tmp_path / "b.mid")
    result = convert_batch([good1, bad, good2], profile)
    assert [f.ok for f in result.files] == [True, False, True]  # плохой файл не остановил остальные
    assert result.files[1].error and result.files[1].report is None
    assert result.outputs == [tmp_path / "a_remapped.mid", tmp_path / "c_remapped.mid"]
    assert all(p.is_file() for p in result.outputs) and not (tmp_path / "b_remapped.mid").exists()
    assert len(result.succeeded) == 2 and len(result.failed) == 1
    assert result.files[0].report.totals().hits > 0


def test_batch_output_folder_is_created(tmp_path):
    _, profile = _profile()
    a = tmp_path / "a.mid"
    shutil.copy(SAMPLE, a)
    out = tmp_path / "new" / "folder"
    result = convert_batch([a], profile, output_dir=out)
    assert result.outputs == [out / "a_remapped.mid"] and (out / "a_remapped.mid").is_file()
    assert not (tmp_path / "a_remapped.mid").exists()


def test_batch_name_collision_in_output_folder_is_an_error(tmp_path):
    _, profile = _profile()
    d1, d2 = tmp_path / "one", tmp_path / "two"
    d1.mkdir()
    d2.mkdir()
    first, second = d1 / "groove.mid", d2 / "groove.mid"
    shutil.copy(SAMPLE, first)
    shutil.copy(SAMPLE, second)
    out = tmp_path / "out"
    result = convert_batch([first, second], profile, output_dir=out)
    assert [f.ok for f in result.files] == [True, False]
    assert "collides" in result.files[1].error and "groove_remapped.mid" in result.files[1].error
    assert result.outputs == [out / "groove_remapped.mid"]
    # первый результат не затёрт вторым
    assert mido.MidiFile(str(out / "groove_remapped.mid")).length == mido.MidiFile(str(SAMPLE)).length


def test_batch_result_would_overwrite_another_source(tmp_path):
    _, profile = _profile()
    a, a_remapped = tmp_path / "a.mid", tmp_path / "a_remapped.mid"
    shutil.copy(SAMPLE, a)
    shutil.copy(SAMPLE, a_remapped)
    before = a_remapped.read_bytes()
    result = convert_batch([a, a_remapped], profile)
    assert not result.files[0].ok and "overwrite another source" in result.files[0].error
    assert a_remapped.read_bytes() != b"" and (tmp_path / "a_remapped_remapped.mid").is_file()
    assert result.files[1].ok and a_remapped.read_bytes() == before  # исходник не тронут


def test_batch_overwrites_existing_output_of_the_same_file(tmp_path):
    _, profile = _profile()
    a = tmp_path / "a.mid"
    shutil.copy(SAMPLE, a)
    (tmp_path / "a_remapped.mid").write_bytes(b"old")
    result = convert_batch([a], profile)  # как при одном файле: существующий результат перезаписывается
    assert result.files[0].ok and (tmp_path / "a_remapped.mid").read_bytes() != b"old"


def test_batch_unusable_output_folder_fails_every_file(tmp_path):
    _, profile = _profile()
    a = tmp_path / "a.mid"
    shutil.copy(SAMPLE, a)
    blocker = tmp_path / "file.txt"
    blocker.write_text("x")
    result = convert_batch([a], profile, output_dir=blocker / "sub")
    assert not result.files[0].ok and "output folder" in result.files[0].error


def test_batch_passes_direction_and_empty_input(tmp_path):
    seen = []

    def fake(src, dst, profile, direction):
        seen.append(direction)
        return ConversionReport()

    a = tmp_path / "a.mid"
    a.write_bytes(b"")
    assert convert_batch([], RemapProfile(name="p")).files == []
    assert convert_batch([a], RemapProfile(name="p"), direction="reverse", convert_fn=fake).files[0].ok
    assert seen == ["reverse"]
