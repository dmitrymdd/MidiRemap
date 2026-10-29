"""Смоук-тесты главного окна PySide6 (без pytest-qt, платформа Qt offscreen)."""
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QMimeData, QUrl  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from midiremap.core import RemapProfile, Rule, convert, legacy_profile  # noqa: E402
from midiremap.storage import Storage  # noqa: E402
from midiremap.ui.main_window import (  # noqa: E402
    MainWindow, batch_summary, format_report, midi_paths_from_mime, report_summary,
)

SAMPLE = Path(__file__).resolve().parents[1] / "samples" / "midi" / "Groove 01.mid"


@pytest.fixture(scope="module")
def app():
    app = QApplication.instance() or QApplication([])
    yield app
    # платформа offscreen падает (segfault) при выходе, если в буфере обмена остались данные
    # (test_load_convert_and_copy кладёт туда файл); обычная платформа windows — нет
    app.clipboard().clear()


@pytest.fixture
def window(app, tmp_path):
    w = MainWindow(Storage(tmp_path / "store"))
    yield w
    w.close()
    w.deleteLater()


def test_window_constructs_with_seeded_legacy_profile(window):
    assert window.windowTitle() == "MidiRemap"
    assert window.profile_combo.count() == 1
    assert window.profile_combo.currentText() == legacy_profile().name
    assert window.selected_profile().rules == legacy_profile().rules


def test_profiles_from_storage_listed(app, tmp_path):
    storage = Storage(tmp_path / "store")
    storage.save_profile(RemapProfile(name="Мой профиль", rules={36: Rule.map_to(35)}))
    (storage.profiles_dir / "broken.json").write_text("{", encoding="utf-8")
    w = MainWindow(storage)  # папка профилей уже есть — legacy не засевается
    assert [w.profile_combo.itemText(i) for i in range(w.profile_combo.count())] == ["Мой профиль"]
    assert "broken.json" in w.status.text()
    assert w.selected_profile().rules == {36: Rule.map_to(35)}
    w.close()


def test_load_convert_and_copy(window, tmp_path, app):
    src = tmp_path / "groove.mid"
    shutil.copy(SAMPLE, src)
    window.load(src)
    assert window.source == src.resolve()
    window.convert()
    out = tmp_path / "groove_remapped.mid"
    assert out.is_file() and window.output == out.resolve()
    # секции REPORT нет: итог — под именем файла, полный отчёт — в окне Details
    for gone in ("report_view", "report_summary", "details_btn", "batch_area", "batch_box"):
        assert not hasattr(window, gone)
    assert window.drop.single_result.isVisibleTo(window.drop)
    assert window.drop.single_result.text().startswith("✓ ") and " hits · " in window.drop.single_result.text()
    dlg = window.details_dialog(src.resolve())
    assert "Moved:" in dlg.view.toPlainText() and dlg.view.isReadOnly()
    dlg.deleteLater()

    window.copy_output()
    urls = app.clipboard().mimeData().urls()
    assert [Path(u.toLocalFile()) for u in urls] == [out.resolve()]


def test_convert_without_file_does_not_crash(window):
    window.convert()
    assert window.output is None
    assert window.status.property("state") == "error"


def test_midi_paths_from_mime(tmp_path):
    mid, txt = tmp_path / "a.MID", tmp_path / "b.txt"
    mid.write_bytes(b"")
    txt.write_text("x")
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(txt)), QUrl.fromLocalFile(str(mid))])
    assert midi_paths_from_mime(mime) == [mid]
    text_only = QMimeData()
    text_only.setText(f'"{mid}"')
    assert midi_paths_from_mime(text_only) == [mid]


def test_format_report_and_summary_use_one_vocabulary(tmp_path):
    """hits — note_on, notes — номера; категории moved / unchanged / deleted одинаковы в итоге и в Details."""
    profile = RemapProfile(name="p", rules={36: Rule.map_to(35), 38: Rule.delete(), 42: Rule.map_to(42)})
    report = convert(SAMPLE, tmp_path / "out.mid", profile)
    t = report.totals()
    text = format_report(report)
    for part in ("Total:", "Moved:", "Unchanged:", "Deleted:", "Merged duplicates", "Overlaps", "Warnings"):
        assert part in text
    assert "Remapped" not in text and "Kept as is" not in text
    assert f"Moved: {t.moved.hits} hits ({t.moved.notes} note" in text
    assert f"Unchanged: {t.unchanged.hits} hits ({t.unchanged.notes} notes)" in text
    assert f"Deleted: {t.deleted.hits} hit" in text
    w = len(report.warnings)
    tail = (f" · {w} warning" + ("" if w == 1 else "s")) if w else ""  # нет предупреждений — не пишется
    assert report_summary(report) == (f"{t.hits} hits · {t.moved.hits} moved · {t.unchanged.hits} unchanged"
                                      f" · {t.deleted.hits} deleted{tail}")
    assert t.moved.hits + t.unchanged.hits + t.deleted.hits == t.hits
    assert "notes converted" not in report_summary(report)  # «notes» — не про hits


def test_batch_summary_wording():
    assert batch_summary(3, 1) == "3 files converted, 1 failed"
    assert batch_summary(1, 0) == "1 file converted"
    assert batch_summary(0, 2) == "0 files converted, 2 failed"


def test_window_default_size_fits_screen(window):
    area = window.screen().availableGeometry()
    assert window.width() == max(min(1280, int(area.width() * 0.9)), window.minimumWidth())
    assert window.height() == max(min(800, int(area.height() * 0.9)), window.minimumHeight())
    assert (window.minimumWidth(), window.minimumHeight()) == (760, 580)


def test_core_does_not_import_qt():
    code = ("import sys, midiremap.core, midiremap.storage; "
            "sys.exit(any(m.startswith(('PySide6', 'shiboken6')) for m in sys.modules))")
    src = Path(__file__).resolve().parents[1] / "src"
    env = {**os.environ, "PYTHONPATH": str(src)}
    assert subprocess.run([sys.executable, "-c", code], env=env).returncode == 0


# --- пакетная конвертация на вкладке Convert ---

def _files(tmp_path, *names):
    out = []
    for name in names:
        f = tmp_path / name
        shutil.copy(SAMPLE, f)
        out.append(f)
    return out


def test_midi_paths_from_mime_expands_folder_without_recursion(tmp_path):
    folder = tmp_path / "set"
    (folder / "deep").mkdir(parents=True)
    for name in ("b.mid", "A.MIDI", "notes.txt"):
        (folder / name).write_bytes(b"")
    (folder / "deep" / "c.mid").write_bytes(b"")
    single = tmp_path / "x.mid"
    single.write_bytes(b"")
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(single)), QUrl.fromLocalFile(str(folder))])
    assert midi_paths_from_mime(mime) == [single, folder / "A.MIDI", folder / "b.mid"]


def test_several_files_list_remove_and_clear(window, tmp_path):
    a, b, c = _files(tmp_path, "a.mid", "b.mid", "c.mid")
    window._accept_files([a, b, c, a])  # повтор не добавляется
    assert window.sources == [a.resolve(), b.resolve(), c.resolve()]
    assert not window.drop.files_box.isHidden() and window.drop.name.isHidden()
    assert window.drop.count.text() == "3 files"
    assert window.out_card.name.text() == "3 files" and window.out_card.folder.text() == "Next to the source files"
    window.remove_source(b.resolve())
    assert window.sources == [a.resolve(), c.resolve()] and window.drop.count.text() == "2 files"
    window.remove_source(a.resolve())  # остался один — вид как у одного файла
    assert window.drop.files_box.isHidden() and window.drop.name.text() == "c.mid"
    window._accept_files([a, b])
    window.drop.clear_btn.click()
    assert window.sources == [] and window.drop.name.text() == "Drop a MIDI file here"


def test_drop_dialog_and_paste_add_to_the_list(window, tmp_path, app, monkeypatch):
    from PySide6.QtCore import QMimeData, QUrl
    from PySide6.QtWidgets import QFileDialog
    a, b, c = _files(tmp_path, "a.mid", "b.mid", "c.mid")
    window._accept_files([a])
    monkeypatch.setattr(QFileDialog, "getOpenFileNames", lambda *args: ([str(b), str(a)], ""))
    window.choose_file()  # диалог — добавляет, повтор a не дублируется
    assert window.sources == [a.resolve(), b.resolve()]
    assert window.status.text().startswith("Added 1 file · 2 in the list")
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(c))])
    app.clipboard().setMimeData(mime)
    window.paste_file()  # Ctrl+V — тоже добавляет
    assert window.sources == [a.resolve(), b.resolve(), c.resolve()]
    window._accept_files([c])
    assert window.status.text() == "Already in the list." and len(window.sources) == 3
    window.drop.clear_btn.click()  # «Clear all» — заново
    assert window.sources == []
    window._accept_files([b])
    assert window.sources == [b.resolve()]
    window.load(a)  # load() заменяет
    assert window.sources == [a.resolve()]


def test_copy_button_says_files_for_several_outputs(window, tmp_path):
    a, b = _files(tmp_path, "a.mid", "b.mid")
    assert window.copy_btn.text() == "Copy file  ⧉" and window.copy_btn.toolTip() == "Copy file (Ctrl+C)"
    window._accept_files([a, b])
    assert window.copy_btn.text() == "Copy files  ⧉" and window.copy_btn.toolTip() == "Copy files (Ctrl+C)"
    window.convert()
    assert len(window.outputs) == 2 and window.copy_btn.text() == "Copy files  ⧉"
    window.remove_source(b.resolve())
    assert window.copy_btn.text() == "Copy file  ⧉"


def test_failed_file_shows_first_error_line_under_its_name(window, tmp_path):
    from midiremap.core import FileResult
    from midiremap.ui.main_window import result_details, result_line
    res = FileResult(tmp_path / "x.mid", tmp_path / "x_remapped.mid", error="Bad header\nat byte 14\nchunk MThd")
    assert result_line(res) == "✗ Bad header" and result_details(res) == res.error
    a, b = _files(tmp_path, "a.mid", "b.mid")
    window._accept_files([a, b])
    window.results = {a.resolve(): res}
    window.drop.set_files(window.sources, window.results)
    first, second = window.drop.row_widgets()
    assert first.result.text() == "✗ Bad header" and first.result.property("state") == "error"
    assert first.result.toolTip() == res.error and not first.details.isHidden()  # видно без раскрытия
    assert second.result.isHidden() and second.details.isHidden()  # результата нет — строка как раньше


def test_single_file_zone_looks_as_before(window, tmp_path):
    (a,) = _files(tmp_path, "a.mid")
    window.load(a)
    assert window.drop.files_box.isHidden() and window.drop.name.text() == "a.mid"
    assert window.drop.folder.text() == str(a.resolve().parent)
    assert window.out_card.name.text() == "a_remapped.mid"


def test_convert_several_files_with_one_failure(window, tmp_path):
    a, c = _files(tmp_path, "a.mid", "c.mid")
    bad = tmp_path / "b.mid"
    bad.write_bytes(b"not midi")
    window._accept_files([a, bad, c])
    window.convert()
    assert [p.name for p in window.outputs] == ["a_remapped.mid", "c_remapped.mid"]
    assert window.status.text() == "2 files converted, 1 failed" and window.status.property("state") == "error"
    rows = window.drop.row_widgets()
    assert [r.name.text() for r in rows] == ["a.mid", "b.mid", "c.mid"]
    assert rows[0].result.text().startswith("✓ ") and " hits · " in rows[0].result.text()
    assert rows[1].result.text() == "✗ Not a MIDI file" and rows[1].result.property("state") == "error"
    assert all(not r.details.isHidden() for r in rows)  # у каждой строки — Details
    assert not (tmp_path / "b_remapped.mid").exists()
    dlg = window.details_dialog(a.resolve())
    assert dlg.view.toPlainText().startswith("Profile:") and "Moved:" in dlg.view.toPlainText()
    dlg.copy()
    assert QApplication.clipboard().text() == dlg.view.toPlainText()  # Copy — весь текст
    assert window.details_dialog(bad.resolve()).view.toPlainText() == NOT_MIDI_DETAILS
    assert window.out_card.property("state") == "ok" and window.out_card.name.text() == "2 files"
    # новая загрузка сбрасывает результаты
    window._accept_files([_files(tmp_path, "d.mid")[0]])
    assert window.results == {} and all(r.result.isHidden() for r in window.drop.row_widgets())


def test_convert_several_files_to_output_folder_and_reset(window, tmp_path):
    d1, d2 = tmp_path / "one", tmp_path / "two"
    d1.mkdir()
    d2.mkdir()
    a, b = _files(d1, "groove.mid")[0], _files(d2, "groove.mid")[0]
    other = _files(tmp_path, "solo.mid")[0]
    out = tmp_path / "results"
    window.ask_output_folder = lambda start: str(out)
    window.choose_output_folder()
    assert window.output_dir == out and not window.folder_reset_btn.isHidden()
    window._accept_files([a, b, other])
    assert window.out_card.folder.text() == str(out)
    window.convert()
    # одинаковые имена в общей папке — ошибка, а не молчаливая перезапись
    assert window.status.text() == "2 files converted, 1 failed"
    rows = window.drop.row_widgets()
    assert "collides" in rows[1].result.text()
    assert sorted(p.name for p in out.iterdir()) == ["groove_remapped.mid", "solo_remapped.mid"]
    assert not (d1 / "groove_remapped.mid").exists()
    window.folder_reset_btn.click()
    assert window.output_dir is None and window.folder_reset_btn.isHidden() and window.outputs == []
    window.convert()
    assert (d1 / "groove_remapped.mid").is_file() and (d2 / "groove_remapped.mid").is_file()
    assert window.status.text() == "3 files converted"


def test_output_folder_applies_to_single_file(window, tmp_path):
    (a,) = _files(tmp_path, "a.mid")
    out = tmp_path / "res"
    window.set_output_dir(out)
    window.load(a)
    assert window.out_card.path == out / "a_remapped.mid"
    window.convert()
    assert (out / "a_remapped.mid").is_file() and not (tmp_path / "a_remapped.mid").exists()
    assert window.status.text() == "Converted: a_remapped.mid"


NOT_MIDI_DETAILS = "Not a MIDI file\n\nTechnical details:\nOSError: MThd not found. Probably not a MIDI file"


def test_single_file_failure_shows_in_its_row(window, tmp_path):
    bad = tmp_path / "bad.mid"
    bad.write_bytes(b"not midi")
    window.load(bad)
    shown = []
    window.show_error = shown.append
    window.convert()
    assert shown == [] and window.outputs == []  # как у пакета: без окна ошибки
    assert window.status.text() == "Conversion failed." and window.status.property("state") == "error"
    assert window.drop.single_result.text() == "✗ Not a MIDI file" and not window.drop.single_details.isHidden()
    assert window.details_dialog(bad.resolve()).view.toPlainText() == NOT_MIDI_DETAILS


def test_truncated_file_row_shows_plain_message_details_show_exception(window, tmp_path):
    (src,) = _files(tmp_path, "cut.mid")
    src.write_bytes(src.read_bytes()[:40])
    window.load(src)
    window.convert()
    assert window.drop.single_result.text() == "✗ The file is damaged or truncated"  # не «✗ EOFError»
    assert window.details_dialog(src.resolve()).view.toPlainText() == (
        "The file is damaged or truncated\n\nTechnical details:\nEOFError")


def test_copy_several_outputs_as_file_urls(window, tmp_path, app):
    a, b = _files(tmp_path, "a.mid", "b.mid")
    window._accept_files([a, b])
    window.convert()
    window.copy_output()
    urls = app.clipboard().mimeData().urls()
    assert [Path(u.toLocalFile()) for u in urls] == [tmp_path / "a_remapped.mid", tmp_path / "b_remapped.mid"]
    assert window.status.text().startswith("2 output files copied")
