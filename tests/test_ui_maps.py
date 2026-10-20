"""Смоук-тесты менеджера/редактора карт (PySide6, платформа Qt offscreen, диалоги подменены)."""
import os
import shutil
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from midiremap.core.notemap import NoteMap  # noqa: E402
from midiremap.core.notenames import parse_notenames  # noqa: E402
from midiremap.storage import Storage  # noqa: E402
from midiremap.templates import load_map_template  # noqa: E402
from midiremap.ui.main_window import PAGE_MAPS, MainWindow  # noqa: E402
from midiremap.ui.maps_page import COL_NAME, COL_PRIMARY, REF_ROLE, TEMPLATE, USER, MapRef  # noqa: E402

FIXTURE = Path(__file__).parent / "fixtures" / "reaper_custom_with_order.txt"


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def storage(tmp_path):
    return Storage(tmp_path / "store")


@pytest.fixture
def window(app, storage):
    w = MainWindow(storage)
    w.show_page(PAGE_MAPS)
    page = w.maps_page
    # диалоги не открываем: тест задаёт ответы
    page.answers = {"text": [], "confirm": True, "save_changes": "discard"}
    page.ask_text = lambda *a: page.answers["text"].pop(0) if page.answers["text"] else None
    page.confirm = lambda *a: page.answers["confirm"]
    page.ask_save_changes = lambda: page.answers["save_changes"]
    page.show_error = lambda text: page.answers.setdefault("errors", []).append(text)
    yield w
    w.close()
    w.deleteLater()


def refs(page):
    return [page.list.item(i).data(REF_ROLE) for i in range(page.list.count())
            if page.list.item(i).data(REF_ROLE) is not None]


def first_shared(page):
    """Первая нота артикуляции, занимающей несколько нот."""
    return next(n for n in sorted(page.work.names) if len(page.model.group(n)) > 1)


def test_manager_lists_templates_and_opens_read_only(window):
    page = window.maps_page
    templates = [r for r in refs(page) if r.kind == TEMPLATE]
    assert {r.id for r in templates} >= {"Superior Drummer 3", "EZdrummer 3"}
    page.select(MapRef(TEMPLATE, "Superior Drummer 3"))
    assert page.current == MapRef(TEMPLATE, "Superior Drummer 3")
    assert page.model.read_only
    idx = page.model.index(36, COL_NAME)
    assert not page.model.flags(idx) & Qt.ItemFlag.ItemIsEditable
    assert not page.model.setData(idx, "X")
    assert not page.rename_btn.isEnabled() and not page.delete_btn.isEnabled()
    assert page.duplicate_btn.isEnabled()
    assert page.status_chip.text() == "VERIFIED"
    # у шаблона нет Save/Revert, вместо них подсказка; флажки primary неактивны
    assert page.save_btn.isHidden() and page.revert_btn.isHidden()
    assert not page.read_only_hint.isHidden()
    assert page.read_only_hint.text() == "Built-in template — Duplicate to edit"
    shared = first_shared(page)
    pflags = page.model.flags(page.model.index(shared, COL_PRIMARY))
    assert not pflags & Qt.ItemFlag.ItemIsEnabled and not pflags & Qt.ItemFlag.ItemIsUserCheckable


def test_duplicate_edit_primary_save_reload(window, storage, app):
    page = window.maps_page
    page.select(MapRef(TEMPLATE, "EZdrummer 3"))
    page.answers["text"] = ["My EZD3"]
    page.duplicate()
    assert page.current == MapRef(USER, "My EZD3") and not page.model.read_only
    assert not page.save_btn.isHidden() and not page.save_btn.isEnabled() and page.read_only_hint.isHidden()
    assert page.work.meta.notes.endswith("Based on template EZdrummer 3")
    assert page.work.meta.status == "verified"

    # только primary — статус прежний
    shared = first_shared(page)
    pidx = page.model.index(shared, COL_PRIMARY)
    assert page.model.flags(pidx) & Qt.ItemFlag.ItemIsUserCheckable
    assert page.model.setData(pidx, Qt.CheckState.Checked.value, Qt.ItemDataRole.CheckStateRole)
    assert page.dirty and window.nav_maps.text().startswith("Maps") and "●" in window.nav_maps.text()
    assert page.status_chip.text() == "VERIFIED"
    assert page.save()
    assert not page.dirty and "●" not in window.nav_maps.text()
    saved, _ = storage.load_map("My EZD3")
    assert shared in saved.primary and saved.meta.status == "verified"

    # правка имени — unverified
    assert page.model.setData(page.model.index(38, COL_NAME), "  Snare: Center X  ")
    assert page.status_chip.text() == "UNVERIFIED"
    assert page.save()
    saved, _ = storage.load_map("My EZD3")
    assert saved.names[38] == "Snare: Center X" and saved.meta.status == "unverified"
    assert saved.meta.source == load_map_template("EZdrummer 3").meta.source

    # перезагрузка окна: карта на месте
    w2 = MainWindow(storage)
    w2.maps_page.select(MapRef(USER, "My EZD3"))
    assert w2.maps_page.work.names[38] == "Snare: Center X"
    assert shared in w2.maps_page.work.primary
    assert w2.maps_page.status_chip.text() == "UNVERIFIED"
    w2.close()


def test_primary_is_exclusive_and_only_for_shared_names(window):
    page = window.maps_page
    page.select(MapRef(TEMPLATE, "EZdrummer 3"))
    page.answers["text"] = ["Copy"]
    page.duplicate()
    m = page.model
    shared = first_shared(page)
    others = [n for n in m.group(shared) if n != shared]
    m.set_primary(shared, True)
    m.set_primary(others[0], True)
    assert page.work.primary & set(m.group(shared)) == {others[0]}
    assert m.group_state(shared) == ""
    single = next(n for n in sorted(page.work.names) if len(m.group(n)) == 1)
    assert not m.flags(m.index(single, COL_PRIMARY)) & Qt.ItemFlag.ItemIsEnabled
    assert not m.set_primary(single, True)
    # переименование отмеченной ноты в другую артикуляцию снимает флаг
    m.set_name(others[0], "Something else")
    assert others[0] not in page.work.primary


def test_highlight_duplicates_without_primary(window, storage):
    storage.save_map(NoteMap("Kit", {35: "Kick", 36: "Kick", 38: "Snare"}))
    page = window.maps_page
    page.reload_list()
    page.select(MapRef(USER, "Kit"))
    m = page.model
    assert m.group_state(36) == "warning" and m.group_state(38) == ""
    assert m.data(m.index(36, COL_NAME), Qt.ItemDataRole.BackgroundRole) is not None
    assert m.data(m.index(38, COL_NAME), Qt.ItemDataRole.BackgroundRole) is None
    assert "without a primary note" in page.issues_label.text()


def test_filter_named_only_and_search(window):
    page = window.maps_page
    page.select(MapRef(TEMPLATE, "Superior Drummer 3"))
    n_named = len(page.work.names)
    assert page.proxy.rowCount() == n_named
    page.named_only.setChecked(False)
    assert page.proxy.rowCount() == 128
    page.search.setText("36")
    assert page.proxy.rowCount() == 1
    page.search.setText("c1")  # название высоты
    assert page.proxy.mapToSource(page.proxy.index(0, 0)).row() == 36
    page.search.setText("kick")
    assert 0 < page.proxy.rowCount() < n_named


def test_clearing_name_removes_note_and_prunes_order(window, storage):
    m, _ = parse_notenames(FIXTURE.read_text(encoding="utf-8"), "Ordered")
    assert m.order
    storage.save_map(m)
    page = window.maps_page
    page.reload_list()
    page.select(MapRef(USER, "Ordered"))
    victim = next(n for n in m.order if n in m.names)
    page.model.setData(page.model.index(victim, COL_NAME), "")
    assert victim not in page.work.names
    assert page.save()
    saved, _ = storage.load_map("Ordered")
    assert victim not in saved.names and victim not in saved.order
    assert saved.extra_lines == m.extra_lines
    assert [n for n in saved.order] == [n for n in m.order if n != victim]


def test_unsaved_prompt_on_switch(window, storage):
    page = window.maps_page
    storage.save_map(NoteMap("A", {36: "Kick"}))
    storage.save_map(NoteMap("B", {38: "Snare"}))
    page.reload_list()
    page.select(MapRef(USER, "A"))
    page.model.set_name(36, "Kick 2")

    page.answers["save_changes"] = "cancel"
    page.select(MapRef(USER, "B"))
    assert page.current == MapRef(USER, "A") and page.dirty
    assert page.list.currentItem().data(REF_ROLE) == MapRef(USER, "A")

    page.answers["save_changes"] = "save"
    page.select(MapRef(USER, "B"))
    assert page.current == MapRef(USER, "B")
    assert storage.load_map("A")[0].names[36] == "Kick 2"

    page.model.set_name(38, "Snare 2")
    page.answers["save_changes"] = "discard"
    page.select(MapRef(USER, "A"))
    assert storage.load_map("B")[0].names[38] == "Snare"


def test_close_with_unsaved_changes_can_be_cancelled(window, storage):
    page = window.maps_page
    storage.save_map(NoteMap("A", {36: "Kick"}))
    page.reload_list()
    page.select(MapRef(USER, "A"))
    page.model.set_name(36, "Kick 2")
    page.answers["save_changes"] = "cancel"
    window.show()
    assert not window.close()
    page.answers["save_changes"] = "discard"
    assert window.close()


def test_revert(window, storage):
    page = window.maps_page
    storage.save_map(NoteMap("A", {36: "Kick"}))
    page.reload_list()
    page.select(MapRef(USER, "A"))
    page.model.set_name(37, "Stick")
    page.revert()
    assert not page.dirty and page.work.names == {36: "Kick"}


def test_new_rename_delete(window, storage):
    page = window.maps_page
    page.answers["text"] = ["Fresh"]
    page.new_map()
    assert page.current == MapRef(USER, "Fresh") and not page.named_only.isChecked()

    storage.save_map(NoteMap("Taken"))
    page.reload_list()
    page.answers["text"] = ["Taken", "Renamed"]  # первое имя занято — спросит ещё раз
    page.rename()
    assert page.answers["errors"] and "already exists" in page.answers["errors"][0]
    assert page.current == MapRef(USER, "Renamed")
    ids = [e.id for e in storage.list_maps()[0]]
    assert "Fresh" not in ids and "Renamed" in ids

    page.answers["confirm"] = False
    page.delete()
    assert "Renamed" in [e.id for e in storage.list_maps()[0]]
    page.answers["confirm"] = True
    page.delete()
    assert "Renamed" not in [e.id for e in storage.list_maps()[0]]
    assert page.current is None


def test_legacy_txt_map_marked_and_saved_as_json(window, storage):
    storage.maps_dir.mkdir(parents=True)
    shutil.copy(FIXTURE, storage.maps_dir / "Old.txt")
    page = window.maps_page
    page.reload_list()
    item = next(page.list.item(i) for i in range(page.list.count())
                if page.list.item(i).data(REF_ROLE) == MapRef(USER, "Old"))
    assert "legacy" in item.data(Qt.ItemDataRole.UserRole + 1)
    page.select(MapRef(USER, "Old"))
    assert page.legacy and not page.kind_chip.isHidden() and page.kind_chip.text() == "LEGACY .TXT"
    n = next(iter(page.work.names))
    page.model.set_name(n, "Renamed note")
    assert page.save()
    assert (storage.maps_dir / "Old.json").is_file() and not (storage.maps_dir / "Old.txt").exists()
    assert not page.legacy


def test_import_shows_issues_and_can_be_cancelled(window, storage, tmp_path):
    src = tmp_path / "broken.txt"
    src.write_text("# MIDI note/CC name map\n36 Kick\n300 Bad\nwhat is this\n", encoding="utf-8")
    page = window.maps_page
    page.choose_open_file = lambda: str(src)
    page.answers["confirm"] = False
    page.import_txt()
    assert storage.list_maps()[0] == []

    page.answers["confirm"] = True
    page.answers["text"] = ["Imported"]
    page.import_txt()
    m, _ = storage.load_map("Imported")
    assert m.names == {36: "Kick"} and m.meta.status == "unverified"
    assert page.current == MapRef(USER, "Imported")


def test_export_full_and_primary_only(window, storage, tmp_path):
    storage.save_map(NoteMap("Kit", {35: "Kick", 36: "Kick", 38: "Snare", 51: "Ride", 59: "Ride"},
                             primary={51}))
    page = window.maps_page
    page.reload_list()
    page.select(MapRef(USER, "Kit"))
    full, prim = tmp_path / "full.txt", tmp_path / "prim.txt"
    page.choose_save_file = lambda name: str(full)
    page.export(primary_only=False)
    assert parse_notenames(full.read_text(encoding="utf-8"), "x")[0].names.keys() == {35, 36, 38, 51, 59}

    page.choose_save_file = lambda name: str(prim)
    page.export(primary_only=True)
    assert parse_notenames(prim.read_text(encoding="utf-8"), "x")[0].names.keys() == {38, 51}
    assert "Skipped (1): Kick" in page.status.text()


def test_maps_tab_disables_convert_shortcuts(window):
    assert not any(sc.isEnabled() for sc in window._convert_shortcuts)
    window.show_page(0)
    assert all(sc.isEnabled() for sc in window._convert_shortcuts)
