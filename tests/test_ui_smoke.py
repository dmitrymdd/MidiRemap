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
from midiremap.ui.main_window import MainWindow, format_report, midi_paths_from_mime  # noqa: E402

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
    assert "Remapped" in window.report_view.toPlainText()

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


def test_format_report_mentions_all_parts(tmp_path):
    profile = RemapProfile(name="p", rules={36: Rule.map_to(35), 38: Rule.delete()})
    report = convert(SAMPLE, tmp_path / "out.mid", profile)
    text = format_report(report)
    for part in ("Remapped", "Deleted", "Kept as is", "Merged duplicates",
                 "Overlaps", "Warnings"):
        assert part in text


def test_core_does_not_import_qt():
    code = ("import sys, midiremap.core, midiremap.storage; "
            "sys.exit(any(m.startswith(('PySide6', 'shiboken6')) for m in sys.modules))")
    src = Path(__file__).resolve().parents[1] / "src"
    env = {**os.environ, "PYTHONPATH": str(src)}
    assert subprocess.run([sys.executable, "-c", code], env=env).returncode == 0
