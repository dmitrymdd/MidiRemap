"""Смоук-тесты менеджера/редактора карт (PySide6, платформа Qt offscreen, диалоги подменены)."""
import shutil
from pathlib import Path

import pytest

pytest.importorskip("PySide6")
pytestmark = pytest.mark.ui

from PySide6.QtCore import Qt

from midiremap.core.notemap import NoteMap
from midiremap.core.pitch import pitch_name
from midiremap.core.notenames import parse_notenames
from midiremap.templates import load_map_template
from midiremap.ui.main_window import PAGE_MAPS, MainWindow
from midiremap.ui.maps_page import COL_NAME, COL_NOTE, OTHERS_ROLE, REF_ROLE, TEMPLATE, USER, MapRef

FIXTURE = Path(__file__).parent / "fixtures" / "reaper_custom_with_order.txt"


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



def test_manager_lists_templates_and_opens_read_only(window):
    page = window.maps_page
    templates = [r for r in refs(page) if r.kind == TEMPLATE]
    assert {r.id for r in templates} >= {"Superior Drummer 3", "EZdrummer 3"}
    page.select(MapRef(TEMPLATE, "Superior Drummer 3"))
    assert page.current == MapRef(TEMPLATE, "Superior Drummer 3")
    assert page.model.read_only
    idx = page.model.note_index(36, COL_NAME)
    assert not page.model.flags(idx) & Qt.ItemFlag.ItemIsEditable
    assert not page.model.setData(idx, "X")
    assert not page.rename_btn.isEnabled() and not page.delete_btn.isEnabled()
    assert page.duplicate_btn.isEnabled()
    assert not hasattr(page, "status_chip")  # статус карты в UI не показывается
    assert "verified" not in page.list.currentItem().toolTip().casefold()
    # у шаблона нет Save/Revert, вместо них подсказка
    assert page.save_btn.isHidden() and page.revert_btn.isHidden()
    assert not page.edit_copy_btn.isHidden() and page.edit_copy_btn.text() == "Duplicate to edit"


def test_duplicate_edit_save_reload(window, storage, app):
    page = window.maps_page
    page.select(MapRef(TEMPLATE, "EZdrummer 3"))
    page.answers["text"] = ["My EZD3"]
    page.duplicate()
    assert page.current == MapRef(USER, "My EZD3") and not page.model.read_only
    assert not page.save_btn.isHidden() and not page.save_btn.isEnabled() and page.edit_copy_btn.isHidden()
    assert page.work.meta.notes.endswith("Based on template EZdrummer 3")
    assert page.work.meta.status == "verified"

    # правка имени — unverified
    assert page.model.setData(page.model.note_index(38, COL_NAME), "  Snare: Center X  ")
    assert page.dirty and window.nav_maps.text().startswith("Maps") and "●" in window.nav_maps.text()
    assert page.save()
    assert not page.dirty and "●" not in window.nav_maps.text()
    saved, _ = storage.load_map("My EZD3")
    assert saved.names[38] == "Snare: Center X" and saved.meta.status == "unverified"
    assert saved.meta.source == load_map_template("EZdrummer 3").meta.source

    # перезагрузка окна: карта на месте
    w2 = MainWindow(storage)
    w2.maps_page.select(MapRef(USER, "My EZD3"))
    assert w2.maps_page.work.names[38] == "Snare: Center X"
    w2.close()


def test_primary_kept_in_file_but_not_editable(window, storage):
    # Write to на вкладке Maps не правится, но в JSON остаётся (старые файлы читаются и сохраняются как есть)
    storage.save_map(NoteMap("Kit", {35: "Kick", 36: "Kick", 38: "Snare", 39: "Clap"}, primary={36}))
    page = window.maps_page
    page.reload_list()
    page.select(MapRef(USER, "Kit"))
    m = page.model
    assert all(not m.flags(m.index(r, c)) & Qt.ItemFlag.ItemIsUserCheckable
               for r in range(m.rowCount()) for c in range(m.columnCount()))
    m.set_name(38, "Snare 2")
    assert page.save()
    assert storage.load_map("Kit")[0].primary == {36}
    # переименование ноты Write to в другую артикуляцию снимает флаг
    m.set_name(36, "Something else")
    assert 36 not in page.work.primary


def test_same_name_badge(window, storage, app):
    storage.save_map(NoteMap("Kit", {35: "Kick", 36: "kick ", 38: "Snare"}))
    page = window.maps_page
    page.reload_list()
    page.select(MapRef(USER, "Kit"))
    m = page.model
    assert m.data(m.note_index(36, COL_NAME), OTHERS_ROLE) == 1
    assert m.data(m.note_index(38, COL_NAME), OTHERS_ROLE) == 0
    assert "On notes 35, 36" in m.data(m.note_index(35, COL_NAME), Qt.ItemDataRole.ToolTipRole)
    # дубли без Write to больше не подсвечиваются и не попадают в замечания
    assert m.data(m.note_index(36, COL_NAME), Qt.ItemDataRole.BackgroundRole) is None
    assert "Write to" not in page.issues_label.text()
    from midiremap.ui.maps_page import NameDelegate
    assert isinstance(page.table.itemDelegateForColumn(COL_NAME), NameDelegate)
    window.resize(1000, 700)
    window.show()
    app.processEvents()
    assert not page.table.grab().isNull()  # бейдж рисуется без ошибок


def test_filter_named_only_and_search(window):
    page = window.maps_page
    page.select(MapRef(TEMPLATE, "Superior Drummer 3"))
    n_named = len(page.work.names)
    assert len(page.proxy.note_rows()) == n_named
    page.named_only.setChecked(False)
    assert sorted(page.proxy.note_rows()) == list(range(128))
    page.search.setText("36")
    assert page.proxy.note_rows() == [36] and page.proxy.rowCount() == 2  # нота + заголовок её группы
    page.search.setText("c1")  # название высоты
    assert page.proxy.note_rows() == [36]
    page.search.setText("kick")
    assert 0 < len(page.proxy.note_rows()) < n_named
    # пустые группы скрыты: видимые заголовки — только группы найденных нот
    headers = [page.model.row_at(page.proxy.mapToSource(page.proxy.index(r, 0)).row())
               for r in range(page.proxy.rowCount())]
    assert [h.label for h in headers if h.is_header] == ["Kick"]


def test_clearing_name_removes_note_and_prunes_order(window, storage):
    m, _ = parse_notenames(FIXTURE.read_text(encoding="utf-8"), "Ordered")
    assert m.order
    storage.save_map(m)
    page = window.maps_page
    page.reload_list()
    page.select(MapRef(USER, "Ordered"))
    victim = next(n for n in m.order if n in m.names)
    page.model.setData(page.model.note_index(victim, COL_NAME), "")
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


def test_export_full_map(window, storage, tmp_path):
    storage.save_map(NoteMap("Kit", {35: "Kick", 36: "Kick", 38: "Snare", 51: "Ride", 59: "Ride"},
                             primary={51}))
    page = window.maps_page
    page.reload_list()
    page.select(MapRef(USER, "Kit"))
    full = tmp_path / "full.txt"
    page.choose_save_file = lambda name: str(full)
    assert page.export_btn.menu() is None  # «Write to notes only» убран — кнопка сразу экспортирует
    page.export_btn.click()
    assert parse_notenames(full.read_text(encoding="utf-8"), "x")[0].names.keys() == {35, 36, 38, 51, 59}
    assert page.status.text() == f"Exported to {full}."


def test_maps_tab_disables_convert_shortcuts(window):
    assert not any(sc.isEnabled() for sc in window._convert_shortcuts)
    window.show_page(0)
    assert all(sc.isEnabled() for sc in window._convert_shortcuts)


def test_columns_without_write_to(window, storage):
    from midiremap.ui.maps_page import COLUMNS
    page = window.maps_page
    page.select(MapRef(TEMPLATE, "EZdrummer 3"))
    assert COLUMNS == ("NOTE", "NAME") and page.model.columnCount() == 2  # высоты (C#1) нет — только в подсказке
    m = page.model
    assert m.data(m.note_index(37, COL_NOTE), Qt.ItemDataRole.ToolTipRole) == "Note 37 · C#1"
    alias = m.data(m.note_index(37, COL_NAME), Qt.ItemDataRole.ToolTipRole)  # «Snare: Sidestick» — на 3 нотах
    assert alias == "Snare: Sidestick\nNote 37 · C#1\nOn notes 37, 67, 127"
    single = next(n for n in m.map.names if len(m.group(n)) == 1)
    assert m.data(m.note_index(single, COL_NAME), Qt.ItemDataRole.ToolTipRole) == f"Note {single} · {pitch_name(single)}"
    assert not any("C#1" in str(m.data(m.note_index(37, c))) for c in (COL_NOTE, COL_NAME))
    assert "+N" in page.model.headerData(COL_NAME, Qt.Orientation.Horizontal, Qt.ItemDataRole.ToolTipRole)


def test_rows_grouped_by_instrument(window):
    from midiremap.core.notemap import instrument_group
    page = window.maps_page
    page.select(MapRef(TEMPLATE, "Superior Drummer 3"))
    m = page.model
    headers = [r for r in m.rows if r.is_header]
    assert m.grouped and "Kick" in [h.label for h in headers]
    # каждая нота стоит под заголовком своей группы
    current = None
    for r in m.rows:
        if r.is_header:
            current = r.label
        elif r.note in page.work.names:
            assert instrument_group(page.work.names[r.note]) == current
    # строка-заголовок на всю ширину и не выделяется
    h = page.proxy.index(0, 0)
    assert page.table.columnSpan(0, 0) == 2
    assert not page.proxy.flags(h) & Qt.ItemFlag.ItemIsSelectable
    # General MIDI — группы по ключевым словам (префиксов нет)
    page.select(MapRef(TEMPLATE, "General MIDI"))
    labels = [r.label for r in page.model.rows if r.is_header]
    assert page.model.grouped and {"Kick", "Snare", "Toms", "Percussion"} <= set(labels)


def test_renamed_note_moves_to_its_group_after_save(window):
    page = window.maps_page
    page.select(MapRef(TEMPLATE, "EZdrummer 3"))
    page.answers["text"] = ["Mine"]
    page.duplicate()
    m = page.model
    m.set_name(38, "Cowbell: Hit")
    assert m.row_at(m.note_index(38, 0).row()).group == "snare"  # строка не уезжает при правке
    assert page.save()
    assert m.rows[m.note_index(38, 0).row()].group == "cowbell"


def test_note_table_sort_cycle_every_column(window, app):
    """Клик по заголовку: по возрастанию → по убыванию → снова группы; стрелка показывает состояние."""
    page = window.maps_page
    page.select(MapRef(TEMPLATE, "Superior Drummer 3"))
    m, header = page.model, page.table.horizontalHeader()
    assert m.grouped and m.sort is None and not header.isSortIndicatorShown()
    page.table.setCurrentIndex(page.proxy.mapFromSource(m.note_index(38, COL_NAME)))

    def current():
        return m.note_at(page.proxy.mapToSource(page.table.currentIndex()).row())

    names = page.work.names
    for col in (COL_NOTE,):  # колонки PITCH нет
        header.sectionClicked.emit(col)
        notes = page.proxy.note_rows()
        assert m.sort == (col, False) and not m.grouped and notes == sorted(names)
        assert header.isSortIndicatorShown() and header.sortIndicatorSection() == col
        assert header.sortIndicatorOrder() == Qt.SortOrder.AscendingOrder
        header.sectionClicked.emit(col)
        assert m.sort == (col, True) and page.proxy.note_rows() == sorted(names, reverse=True)
        assert header.sortIndicatorOrder() == Qt.SortOrder.DescendingOrder and current() == 38  # выбор сохранён
        header.sectionClicked.emit(col)
        assert m.sort is None and m.grouped and not header.isSortIndicatorShown()  # третий клик — группы
    header.sectionClicked.emit(COL_NAME)
    by_name = sorted(names, key=lambda n: (names[n].casefold(), n))
    assert m.sort == (COL_NAME, False) and page.proxy.note_rows() == by_name
    header.sectionClicked.emit(COL_NAME)
    assert page.proxy.note_rows() == by_name[::-1]
    header.sectionClicked.emit(COL_NOTE)  # другая колонка — сразу по возрастанию
    assert m.sort == (COL_NOTE, False)
    header.sectionClicked.emit(COL_NOTE)
    header.sectionClicked.emit(COL_NOTE)
    assert m.grouped and current() == 38
    # ноты без имени — в конце при любом направлении
    page.named_only.setChecked(False)
    header.sectionClicked.emit(COL_NAME)
    header.sectionClicked.emit(COL_NAME)
    rows = page.proxy.note_rows()
    assert len(rows) == 128 and all(n not in names for n in rows[len(names):])


