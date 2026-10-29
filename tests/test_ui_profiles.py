"""Смоук-тесты вкладки Profiles и связанных частей вкладки Convert (PySide6, offscreen, диалоги подменены)."""
import shutil
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from midiremap.core.notemap import NoteMap, articulations, normalize_name  # noqa: E402
from midiremap.core.profile import RemapProfile, Rule, legacy_profile  # noqa: E402
from midiremap.storage import sanitize_id  # noqa: E402
from midiremap.templates import load_map_template  # noqa: E402
from midiremap.ui import cable_view  # noqa: E402
from midiremap.ui.main_window import PAGE_CONVERT, PAGE_PROFILES, MainWindow  # noqa: E402
from midiremap.ui.maps_page import TEMPLATE, USER, MapRef  # noqa: E402
from midiremap.ui.profiles_page import ID_ROLE  # noqa: E402

SAMPLE = Path(__file__).resolve().parents[1] / "samples" / "midi" / "Groove 01.mid"
EZD3, SD3 = MapRef(TEMPLATE, "EZdrummer 3"), MapRef(TEMPLATE, "Superior Drummer 3")
LEGACY_ID = sanitize_id(legacy_profile().name)


def stub_dialogs(page):
    page.answers = {"text": [], "confirm": True, "save_changes": "discard", "write_to": [],
                    "unassigned": set(), "asked": []}
    a = page.answers
    page.ask_text = lambda *args: a["text"].pop(0) if a["text"] else None
    page.confirm = lambda *args: a["confirm"]
    page.ask_save_changes = lambda: a["asked"].append("save_changes") or a["save_changes"]
    page.show_error = lambda text: a.setdefault("errors", []).append(text)

    def write_to(name, notes, preselect=None):
        a["asked"].append(("write_to", name, tuple(notes)))
        a["preselect"] = preselect
        return a["write_to"].pop(0) if a["write_to"] else None
    page.ask_write_to = write_to

    def unassigned(notes):  # ответ — какие ноты оставить на своих номерах
        a["asked"].append(("unassigned", list(notes)))
        return a["unassigned"]
    page.ask_unassigned = unassigned


@pytest.fixture
def window(app, storage):
    w = MainWindow(storage)
    w.show_page(PAGE_PROFILES)
    stub_dialogs(w.profiles_page)
    w.maps_page.ask_save_changes = lambda: "discard"
    yield w
    w.close()
    w.deleteLater()


def new_profile(page, name="P", source=EZD3, target=SD3):
    page.answers["text"] = [name]
    page.new_profile()
    if source is not None:
        assert page.choose_map("source", source)
    if target is not None:
        assert page.choose_map("target", target)
    return page.current


def multi_note_articulation(m):
    return next((k, v) for k, v in articulations(m).items() if len(v) > 1)


def single_note_articulation(m):
    return next((k, v[0]) for k, v in articulations(m).items() if len(v) == 1)


def notes_off(p, notes, k):
    """k нот исходной карты, чьих номеров нет среди notes (назначение не совпадёт по номеру)."""
    return [n for n in sorted(p.source_map.names) if n not in notes][:k]


# --- засев legacy-профиля и вкладка Convert ---

def test_legacy_profile_seeded_once(app, storage):
    w = MainWindow(storage)
    assert [e.id for e in storage.list_profiles()[0]] == [LEGACY_ID]
    p = storage.load_profile(LEGACY_ID)
    assert p.rules == legacy_profile().rules and p.source_map is None and p.target_map is None
    assert w.profile_combo.count() == 1 and w.convert_btn.isEnabled()
    w.close()

    storage.delete_profile(LEGACY_ID)
    w2 = MainWindow(storage)  # папка уже есть — удалённый профиль не возвращается
    assert storage.list_profiles()[0] == []
    assert w2.profile_combo.count() == 0
    assert w2.profile_stack.currentIndex() == 1 and not w2.convert_btn.isEnabled()
    assert "No remap profiles yet" in w2.empty_label.text()
    w2.convert()
    assert w2.status.property("state") == "error"
    w2.close()


def test_summary_line_and_edit_jumps_to_profiles(window, storage):
    page = window.profiles_page
    pid = new_profile(page, "Kit")
    page.save()
    window.show_page(PAGE_CONVERT)
    combo = window.profile_combo
    assert [combo.itemData(i) for i in range(combo.count())] == sorted([LEGACY_ID, pid], key=str.casefold)
    combo.setCurrentIndex(combo.findData(LEGACY_ID))
    assert window.profile_summary.text() == "no maps"  # на Convert — без числа правил
    combo.setCurrentIndex(combo.findData(pid))
    assert window.profile_summary.text() == "EZdrummer 3 → Superior Drummer 3"
    window.show_page(PAGE_PROFILES)
    page.select(LEGACY_ID)
    window.show_page(PAGE_CONVERT)
    window.edit_selected_profile()
    assert window.pages.currentIndex() == PAGE_PROFILES and page.current == pid


def test_profile_list_refreshes_on_changes(window, storage):
    page = window.profiles_page
    pid = new_profile(page, "Fresh", None, None)
    assert window.profile_combo.findData(pid) >= 0  # без кнопки Refresh
    page.answers["text"] = ["Renamed"]
    page.rename()
    assert window.profile_combo.findData(pid) < 0 and window.profile_combo.findData("Renamed") >= 0
    page.delete()
    assert window.profile_combo.findData("Renamed") < 0


def test_source_zone_and_output_card(window, tmp_path):
    window.show_page(PAGE_CONVERT)
    assert window.drop.name.text() == "Drop a MIDI file here"
    src = tmp_path / "groove.mid"
    shutil.copy(SAMPLE, src)
    window.load(src)
    assert window.drop.name.text() == "groove.mid" and "Click or drop to add files" in window.drop.toolTip()
    assert not hasattr(window.drop, "hint") and not hasattr(window.out_card, "hint")
    assert window.drop.cursor().shape() == Qt.CursorShape.PointingHandCursor
    assert window.out_card.property("state") == "off"
    revealed = []
    window.reveal_in_explorer = lambda path: revealed.append(path) or True
    QTest.mouseClick(window.out_card, Qt.MouseButton.LeftButton)
    assert revealed == []  # результата ещё нет
    window.convert()
    assert window.out_card.property("state") == "ok"
    assert "Click to show in folder" in window.out_card.toolTip()
    assert window.out_card.cursor().shape() == Qt.CursorShape.PointingHandCursor
    QTest.mouseClick(window.out_card, Qt.MouseButton.LeftButton, pos=QPoint(10, 10))
    assert revealed == [window.output]


# --- редактор профилей ---

def test_create_profile_with_two_templates(window, storage):
    page = window.profiles_page
    new_profile(page)
    w = page.work
    assert w.source_map.name == "EZdrummer 3" and w.target_map.name == "Superior Drummer 3"
    assert w.source_map.meta.source == load_map_template("EZdrummer 3").meta.source
    # каждая нота исходной карты — в пуле или напротив цели (подсказки), таблицы больше нет
    lay = page.cables.current
    shown = {n for r in lay.pool.rows + lay.scene.source_rows for n in r.notes}
    assert shown == set(w.source_map.names) and lay.pool.headers
    assert not hasattr(page, "table") and not hasattr(page, "accept_btn") and not hasattr(page, "assign_btn")
    assert page.dirty and "●" in window.nav_profiles.text()


def test_suggestion_bar_and_apply(window, app):
    from midiremap.core.suggest import apply_suggested, plan_suggestions, suggestion_targets
    page = window.profiles_page
    new_profile(page)
    ed = page.cables
    st = suggestion_targets(page.work.source_map, page.work.target_map)
    planned = plan_suggestions(page.work, st)
    need = sum(v is None for v in planned.values())
    assert need > 0 and len(planned) > need
    # обе карты заданы — пунктир и панель, правил ещё нет, вопросов нет
    assert page.work.rules == {} and page.answers["asked"] == []
    assert not page.suggest_bar.isHidden() and page.suggest_label.text() == f"{len(planned)} matches"
    assert f"{need} need a Write to choice" in page.suggest_bar.toolTip()
    assert ed.suggestion_items and not ed.cable_items
    assert all(i.pen().style() != Qt.PenStyle.SolidLine for i in ed.suggestion_items)
    rows = [r for r in ed.current.scene.source_rows if r.suggested]
    assert {n for r in rows for n in r.notes} == set(planned)
    row = next(r for r in rows if not r.expanded)
    assert ed.source_items[row.note].opacity() == 1.0 and "Suggested:" in ed.source_items[row.note].toolTip()

    expected, done = apply_suggested(page.work, st)
    assert page.apply_suggestions() == len(done) == len(planned) - need
    assert page.work.rules == expected.rules and page.work.target_map.primary == expected.target_map.primary
    assert page.status.text() == f"{len(done)} notes connected."
    # нужен выбор Write to — остаются пунктиром, Apply больше нечего применить
    assert len(ed.suggestion_items) > 0 and ed.cable_items
    assert page.suggest_label.text() == f"{need} matches" and not page.apply_btn.isEnabled()
    # Apply — один шаг отмены, подсказки возвращаются
    assert page.undo() and page.work.rules == {} and page.suggest_label.text() == f"{len(planned)} matches"
    assert page.redo() and page.work.rules == expected.rules


def test_suggestions_follow_map_changes_and_dismiss(window):
    page = window.profiles_page
    pid = new_profile(page)
    page.answers["asked"].clear()
    assert not page.suggest_bar.isHidden()
    assert page.choose_map("target", MapRef(TEMPLATE, "General MIDI"))  # совпадений нет — панели нет
    assert page.suggest_bar.isHidden() and not page.cables.suggestion_items
    assert page.choose_map("target", SD3)  # снова есть
    assert not page.suggest_bar.isHidden() and page.answers["asked"] == []  # ни одного диалога
    # ✕ — скрыть для этой пары карт (до повторного открытия профиля)
    page.dismiss_suggestions()
    assert page.suggest_bar.isHidden() and not page.cables.suggestion_items
    assert not page.cables.current.scene.source_rows  # строки вернулись в пул
    page.choose_map("target", MapRef(TEMPLATE, "General MIDI"))
    page.choose_map("target", SD3)
    assert page.suggest_bar.isHidden()
    # нота, получившая правило, из подсказок выбывает: снятое правило подсказку не возвращает
    page.choose_map("source", MapRef(TEMPLATE, "Guitar Pro 8"))
    page.choose_map("source", EZD3)
    assert page.suggest_bar.isHidden()  # пара EZD3 → SD3 всё ещё скрыта
    page.answers["unassigned"] = set()
    page.save()
    page.open(pid)  # открытие существующего профиля панель не показывает
    assert page.suggest_bar.isHidden() and not page.cables.suggestion_items


def test_rule_removes_note_from_suggestions(window):
    page = window.profiles_page
    new_profile(page)
    n = next(r.note for r in page.cables.current.scene.source_rows if r.suggested and len(r.notes) == 1)
    page.delete_notes([n])
    assert n not in page.cables.suggested
    page.clear_rules([n])
    assert n not in page.cables.suggested and n not in page.work.rules


def test_profile_without_maps(window):
    page = window.profiles_page
    page.select(LEGACY_ID)
    assert page.suggest_bar.isHidden()
    lay = page.cables.current
    # без исходной карты — строка на правило, без групп; без целевой — цель по номерам
    shown = {n for r in lay.pool.rows + lay.scene.source_rows for n in r.notes}
    assert shown == set(legacy_profile().rules)  # удалённые — тоже, зачёркнутыми
    deleted = {n for n, r in legacy_profile().rules.items() if r == Rule.delete()}
    assert deleted and all(page.cables.pool_items[n].strike for n in deleted)
    assert lay.scene.target_rows and all(t.slot.startswith("n:") for t in lay.scene.target_rows)
    n, dst = next((n, r.dst) for n, r in sorted(page.work.rules.items()) if r.action == "map")
    other = next(t.notes[0] for t in lay.scene.target_rows if t.notes[0] != dst)
    assert page.connect_to([n], f"n:{other}") and page.work.rules[n] == Rule.map_to(other)


def test_many_to_one_single_note_target(window):
    page = window.profiles_page
    new_profile(page)
    key, dst = single_note_articulation(page.work.target_map)
    srcs = [n for n in sorted(page.work.source_map.names) if n != dst][:5]
    assert page.connect_to(srcs, "a:" + key)
    assert all(page.work.rules[n] == Rule.map_to(dst) for n in srcs)
    assert page.answers["asked"] == []  # одна нота — ничего не спрашиваем


def test_write_to_asked_once_and_stored_in_profile_copy(window, storage):
    sd3 = load_map_template("Superior Drummer 3")
    storage.save_map(sd3)  # карта пользователя — её Write to не должен меняться
    page = window.profiles_page
    new_profile(page, target=MapRef(USER, sanitize_id(sd3.name)))
    key, notes = multi_note_articulation(page.work.target_map)
    a, b = notes_off(page.work, notes, 2)
    page.answers["write_to"] = [notes[1]]
    assert page.connect_to([a], "a:" + key)
    assert page.work.rules[a] == Rule.map_to(notes[1])
    assert page.work.target_map.primary & set(notes) == {notes[1]}
    assert page.connect_to([b], "a:" + key)  # второй раз не спрашивает
    assert page.work.rules[b] == Rule.map_to(notes[1])
    assert [x for x in page.answers["asked"] if x[0] == "write_to"] == [
        ("write_to", page.work.target_map.names[notes[0]], tuple(notes))]
    # отдельная нота артикуляции (не Write to) — допустимо
    assert page.assign_note([b], notes[0]) and page.work.rules[b] == Rule.map_to(notes[0])
    assert page.save()
    assert storage.load_map(sanitize_id(sd3.name))[0].primary == set()
    assert notes[1] in storage.load_profile(page.current).target_map.primary


def test_cancel_write_to_choice_keeps_rule(window):
    page = window.profiles_page
    new_profile(page)
    key, notes = multi_note_articulation(page.work.target_map)
    (n,) = notes_off(page.work, notes, 1)
    assert not page.connect_to([n], "a:" + key)
    assert n not in page.work.rules and not page.work.target_map.primary


def test_delete_and_clear_rules(window):
    from midiremap.ui.cable_layout import DELETE, UNASSIGNED
    page = window.profiles_page
    new_profile(page)
    page.dismiss_suggestions()
    a, b = sorted(page.work.source_map.names)[:2]
    y = page.cables.current.source_row(a).y
    page.delete_notes([a, b])
    assert page.work.rules[a] == Rule.delete() and page.cables.pool_items[a].strike
    page.cables.refresh()  # после пересортировки — на том же месте в своей группе, зачёркнута
    row = page.cables.current.source_row(a)
    assert row.block == UNASSIGNED and row.state == DELETE and row.y == y and page.cables.pool_items[b].strike
    page.clear_rules([a])
    assert a not in page.work.rules and not page.cables.pool_items[a].strike


def test_issues_highlighted_in_rows(window):
    page = window.profiles_page
    new_profile(page)
    page.dismiss_suggestions()
    n = sorted(page.work.source_map.names)[0]
    missing = next(x for x in range(128) if x not in page.work.target_map.names)
    page.assign_note([n], missing)
    item = page.cables.source_items[n]
    assert item.warn and f"Note {n} is mapped to {missing}, which is not in the target map" in item.toolTip()
    assert not hasattr(page, "issues_label")  # панели замечаний под редактором нет
    # delete для ноты вне исходной карты — не замечание
    outside = next(x for x in range(128) if x not in page.work.source_map.names)
    page.delete_notes([outside])
    assert outside not in page.cables._issues
    assert sum(i.warn for i in page.cables.pool_rows + page.cables.scene_rows) == 1


def test_change_map_with_rules_confirms_and_keeps_rules(window):
    page = window.profiles_page
    new_profile(page)
    page.apply_suggestions()
    rules = dict(page.work.rules)
    page.answers["confirm"] = False
    assert not page.choose_map("target", MapRef(TEMPLATE, "General MIDI"))
    assert page.work.target_map.name == "Superior Drummer 3"
    page.answers["confirm"] = True
    assert page.choose_map("target", MapRef(TEMPLATE, "General MIDI"))
    assert page.work.rules == rules
    assert any(i.warn for i in page.cables.scene_rows)  # замечания — подсветкой строк


def test_save_dialog_paths(window, storage):
    page = window.profiles_page
    pid = new_profile(page)
    page.apply_suggestions()
    w = page.work
    old_keep = next(n for n in sorted(w.source_map.names) if n not in w.rules)
    w.rules[old_keep] = Rule.keep()  # явный keep старого профиля — не спрашиваем
    unassigned = [n for n in sorted(w.source_map.names) if n not in w.rules]
    assert unassigned

    before = storage.load_profile(pid).to_dict()
    page.answers["unassigned"] = None  # Cancel
    assert not page.save()
    assert storage.load_profile(pid).to_dict() == before and page.dirty
    assert page.answers["asked"][-1] == ("unassigned", unassigned)  # все ноты без правила, по номеру
    assert all(n not in page.work.rules for n in unassigned)  # отмена ничего не меняет

    kept = set(unassigned[:2])  # отмеченные — keep, остальные — delete
    page.answers["unassigned"] = kept
    assert page.save()
    saved = storage.load_profile(pid)
    assert all(saved.rules[n] == Rule.keep() for n in kept)
    assert all(saved.rules[n] == Rule.delete() for n in unassigned if n not in kept)
    assert saved.rules[old_keep] == Rule.keep()
    assert set(saved.source_map.names) <= set(saved.rules) and not page.dirty

    # всё назначено — диалога нет
    page.answers["asked"].clear()
    page.clear_rules([unassigned[-1]])
    page.work.rules[unassigned[-1]] = Rule.keep()
    assert page.save() and page.answers["asked"] == []


def test_save_default_removes_unassigned(window, storage):
    page = window.profiles_page
    pid = new_profile(page)
    page.answers["unassigned"] = set()
    assert page.save()
    saved = storage.load_profile(pid)
    assert saved.rules == {n: Rule.delete() for n in saved.source_map.names}


def test_unsaved_edits_prompts(window, storage):
    page = window.profiles_page
    pid = new_profile(page, "A")
    page.save()
    page.answers["asked"].clear()
    page.clear_rules([sorted(page.work.source_map.names)[0]])
    assert page.dirty

    # переключение вкладок — без вопроса, правки на месте
    window.show_page(PAGE_CONVERT)
    window.show_page(PAGE_PROFILES)
    assert page.dirty and page.answers["asked"] == []

    page.answers["save_changes"] = "cancel"
    page.select(LEGACY_ID)
    assert page.current == pid and page.dirty
    page.answers["text"] = ["B"]
    page.new_profile()
    assert page.current == pid
    page.duplicate()
    assert page.current == pid
    page.rename()
    assert page.current == pid
    assert page.answers["asked"].count("save_changes") == 4

    window.show()
    assert not window.close()
    page.answers["save_changes"] = "discard"
    assert window.close()
    assert storage.load_profile(pid).rules[sorted(page.base.source_map.names)[0]] == Rule.delete()


def test_profiles_tab_disables_convert_shortcuts(window):
    assert not any(sc.isEnabled() for sc in window._convert_shortcuts)
    nav = [window.nav_convert.text(), window.nav_profiles.text(), window.nav_maps.text()]
    assert nav == ["Convert", "Profiles", "Maps"]


def test_suggestion_needing_write_to_tooltip(window):
    from midiremap.ui.cable_view import SUGGESTED_WRITE_TO_HINT
    page = window.profiles_page
    new_profile(page)
    ed = page.cables
    cable = next(c for c in ed.current.scene.cables if c.suggested and c.dst is None)
    item = next(i for i in ed.scene_rows if i.model.y == cable.src_y)
    assert item.dashed and SUGGESTED_WRITE_TO_HINT in item.toolTip()
    assert normalize_name(cable.target.label) in normalize_name(item.toolTip())


def test_new_profile_without_maps_has_no_rows(window):
    page = window.profiles_page
    new_profile(page, "Empty", None, None)
    lay = page.cables.current
    assert lay.pool.rows == [] and lay.scene.source_rows == [] and page.suggest_bar.isHidden()


def test_unassigned_dialog_checkboxes(window):
    from PySide6.QtWidgets import QDialogButtonBox, QLabel
    from midiremap.core.profile import RemapProfile
    from midiremap.ui.profiles_page import UnassignedDialog
    p = RemapProfile("p", load_map_template("Guitar Pro 8"), load_map_template("Superior Drummer 3"))
    notes = sorted(p.source_map.names)
    dlg = UnassignedDialog(window, p, list(reversed(notes)))
    t = dlg.table
    assert t.rowCount() == len(notes) and t.columnCount() == 4  # без столбца маркеров «!»/«≈»
    assert [int(t.item(r, 1).text()) for r in range(t.rowCount())] == notes  # по номеру
    assert t.item(0, 2).text() == p.source_map.names[notes[0]]
    assert t.item(0, 3).text() == p.target_map.names.get(notes[0], "—")
    assert t.item(0, 0).toolTip() == "Keep on the same number"
    assert any(w.text() == f"{len(notes)} notes have no target and will be removed."
               for w in dlg.findChildren(QLabel))
    texts = {b.text().replace("&", "") for b in dlg.findChildren(QDialogButtonBox)[0].buttons()}
    assert texts == {"Save", "Cancel"}
    # по умолчанию ничего не отмечено: Save — удалить все
    assert dlg.checked() == set()
    dlg.save()
    assert dlg.to_keep == set()
    dlg.set_checked({notes[0], notes[-1]})
    dlg.save()
    assert dlg.to_keep == {notes[0], notes[-1]}
    dlg.deleteLater()


def test_dirty_profile_marked_in_list(window):
    page = window.profiles_page
    pid = new_profile(page, "Mark")
    page.answers["unassigned"] = set()
    page.save()
    combo = page.combo

    def index(profile_id):
        return next(i for i in range(combo.count()) if combo.itemData(i, ID_ROLE) == profile_id)
    assert combo.itemText(index(pid)) == "Mark" and combo.currentIndex() == index(pid)
    saved_tip = combo.itemData(index(pid), Qt.ItemDataRole.ToolTipRole)  # подсказка пункта — карты, без числа правил
    assert "EZdrummer 3 → Superior Drummer 3" in saved_tip and "rule" not in saved_tip
    page.clear_rules([sorted(page.work.source_map.names)[0]])
    assert combo.itemText(index(pid)) == "• Mark" and combo.itemText(index(LEGACY_ID)) == legacy_profile().name
    assert combo.currentText() == "• Mark"
    assert combo.itemData(index(pid), Qt.ItemDataRole.ToolTipRole) == saved_tip  # подсказка — сохранённое состояние
    page.revert()
    assert combo.itemText(index(pid)) == "Mark"


def test_rows_show_number_without_pitch_pitch_in_tooltip(window):
    from midiremap.core.pitch import note_tip
    page = window.profiles_page
    ed = page.cables
    new_profile(page)
    page.dismiss_suggestions()
    page.assign_note([37], 37)
    assert note_tip([37]) == "Note 37 · C#1" and note_tip([37, 76]) == "Notes 37 · C#1, 76 · E4"
    alias = ed.pool_items[38]  # «Snare: Center» на нескольких нотах — высоты всех в подсказке
    assert alias.number == "38" and not hasattr(alias, "pitch") and alias.lines == [(0, "38")]
    assert note_tip(alias.notes) in alias.toolTip() and "38 · D1, 39 · D#1" in alias.toolTip()
    single = next(i for i in ed.pool_rows if len(i.notes) == 1)
    assert note_tip(single.notes) in single.toolTip().splitlines()[:2]  # первая строка (или вторая — после имени)
    src = ed.source_items[37]
    assert "Note 37 · C#1" in src.toolTip().splitlines()[:2]
    tgt = next(t for t in ed.target_items.values() if 37 in t.notes)
    assert all(len(line) == 2 for line in tgt.lines) and "37 · C#1" in tgt.toolTip()


def test_write_to_choice_shows_numbers_only(window, monkeypatch):
    from PySide6.QtWidgets import QDialog, QInputDialog
    from midiremap.ui.profiles_page import ProfilesPage
    page = window.profiles_page
    new_profile(page)
    seen = {}

    def fake_exec(dlg):
        seen["items"] = dlg.comboBoxItems()
        dlg.setTextValue(seen["items"][1])
        return QDialog.DialogCode.Accepted
    monkeypatch.setattr(QInputDialog, "exec", fake_exec)
    assert ProfilesPage.ask_write_to(page, "Hi-Hat: Closed Tip", [11, 42, 61]) == 42
    assert seen["items"] == ["11", "42", "61"]  # высота ноты барабанам не нужна


def test_hotkeys_in_tooltips_and_short_status(window, tmp_path):
    from midiremap.ui.maps_page import COL_NAME
    window.show_page(PAGE_CONVERT)
    assert window.convert_btn.toolTip() == "Convert (Enter)"
    assert window.copy_btn.toolTip() == "Copy file (Ctrl+C)"
    src = tmp_path / "groove.mid"
    shutil.copy(SAMPLE, src)
    window.load(src)
    assert "Esc" in window.drop.toolTip()
    window.convert()
    assert window.status.text() == "Converted: groove_remapped.mid"
    # Maps: инструкция по правке — в подсказке заголовка NAME, только у редактируемой карты
    page = window.maps_page
    page.select(MapRef(TEMPLATE, "General MIDI"))
    tip = lambda: page.model.headerData(COL_NAME, Qt.Orientation.Horizontal, Qt.ItemDataRole.ToolTipRole)
    assert "Double-click" not in tip()
    page.ask_text = lambda *a: "GM copy"
    page.duplicate()
    assert "Double-click or type to edit a name" in tip()
    assert not hasattr(page, "edit_hint")


# --- вид «кабелями» ---

def map_rule_count(p):
    return sum(r.action == "map" for r in p.rules.values())


def cabled_note_count(editor):
    """Нот под кабелями (у строки алиасов один кабель на все её ноты)."""
    return sum(len(c.cable.notes) for c in editor.cable_items)


def unique_mapped_note(p):
    """Нота с правилом map, имя которой в исходной карте не повторяется (строка без алиасов)."""
    names = [normalize_name(v) for v in p.source_map.names.values()]
    return next(n for n, r in sorted(p.rules.items())
                if r.action == "map" and names.count(normalize_name(p.source_map.names[n])) == 1)


def test_cables_relayout_immediately_after_each_edit(window):
    from midiremap.ui.cable_layout import DELETE
    page = window.profiles_page
    new_profile(page)
    page.apply_suggestions()
    page.dismiss_suggestions()
    assert cabled_note_count(page.cables) == map_rule_count(page.work) > 0
    assert len(page.cables.cable_items) < map_rule_count(page.work)  # алиасы EZD3 — по кабелю на строку
    # зачеркнули подключённую ноту — она сразу в пуле, в своей группе, зачёркнута
    n = unique_mapped_note(page.work)
    page.delete_notes([n])
    row = page.cables.current.source_row(n)
    assert row.block is not None and row.state == DELETE and page.cables.pool_items[n].strike
    assert n not in page.cables.source_items
    assert cabled_note_count(page.cables) == map_rule_count(page.work)

def test_no_resort_button(window):
    page = window.profiles_page
    new_profile(page)
    for gone in ("refresh_btn", "more_btn", "table_view_btn", "cables_view_btn", "assign_btn", "accept_btn",
                 "views", "model"):
        assert not hasattr(page, gone)
    assert not hasattr(page.cables, "resort") and not hasattr(page.cables, "order")

def test_cleared_rule_returns_to_pool_at_once(window):
    from midiremap.ui.cable_layout import UNASSIGNED
    page = window.profiles_page
    new_profile(page)
    page.apply_suggestions()
    n = unique_mapped_note(page.work)
    page.clear_rules([n])
    assert page.cables.current.source_row(n).block == UNASSIGNED

def test_cables_header_click_collapses(window, app):
    from PySide6.QtCore import QPointF
    from midiremap.ui.cable_view import PAD, ROW
    page = window.profiles_page
    window.resize(1200, 800)
    window.show()
    new_profile(page)
    page.dismiss_suggestions()
    head = page.cables.current.pool.headers[0]  # первая группа пула (блоков состояний нет)
    assert head.y == 0 and not head.collapsed
    pool = page.cables.pool
    pos = pool.mapFromScene(QPointF(PAD + 30, PAD + ROW / 2))
    QTest.mouseClick(pool.viewport(), Qt.MouseButton.LeftButton, pos=pos)
    app.processEvents()
    lay = page.cables.current
    assert lay.header(head.key).collapsed and lay.header(head.key).count == head.count
    assert not {n for r in lay.pool.rows for n in r.notes} & set(head.notes)
    assert lay.pool.headers[1].y == 1  # следующая группа — сразу под свёрнутой


def test_cables_view_saves_with_same_dialog(window, storage):
    from midiremap.ui.cable_layout import DELETE
    page = window.profiles_page
    pid = new_profile(page)
    page.apply_suggestions()
    assert cabled_note_count(page.cables) == map_rule_count(page.work)
    page.answers["unassigned"] = set()
    assert page.save() and page.answers["asked"][-1][0] == "unassigned"
    saved = storage.load_profile(pid)
    assert page.cables.profile is page.work and page.work.to_dict() == saved.to_dict()
    struck = {n for r in page.cables.current.pool.rows if r.state == DELETE for n in r.notes}
    assert struck == {n for n, r in saved.rules.items() if r == Rule.delete()}  # зачёркнутые — в пуле


def test_cables_pool_is_separate_column(window):
    page = window.profiles_page
    window.resize(1300, 900)
    window.show()
    new_profile(page)
    page.apply_suggestions()
    ed = page.cables
    lay = ed.current
    # пул — своя view со своей прокруткой; сцена начинается сверху
    assert ed.pool is not ed.view and ed.splitter.count() == 2  # пул | сцена
    assert not hasattr(ed, "pool_right") and not hasattr(ed, "inactive_pool") and not hasattr(ed, "mirrored")
    assert set(ed.pool_items) == {n for r in lay.pool.rows for n in r.notes}
    assert min(t.y for t in lay.scene.target_rows + lay.scene.target_headers) == 0
    assert ed.view.verticalScrollBar() is not ed.pool.verticalScrollBar()
    ed.pool.verticalScrollBar().setValue(ed.pool.verticalScrollBar().maximum())
    assert ed.view.verticalScrollBar().value() == 0
    # слой для кабеля-превью: поверх обоих, мышь не перехватывает
    assert ed.overlay.geometry() == ed.rect()
    assert ed.overlay.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    a = ed.source_anchor(lay.pool.rows[0].note)
    b = ed.source_anchor(lay.scene.source_rows[0].note)
    assert a is not None and b is not None and a.x() < b.x()
    ed.overlay.show_preview([a], b)
    assert ed.overlay.preview is not None
    ed.overlay.clear_preview()


def test_cable_hover_highlights_and_dims(window):
    from midiremap.ui.cable_view import DIMMED
    page = window.profiles_page
    new_profile(page)
    page.apply_suggestions()
    ed = page.cables
    cable = ed.cable_items[0]
    ed.hover_cable(cable)
    assert cable.pen().widthF() > ed.cable_items[1].pen().widthF()
    assert cable.opacity() == 1.0 and ed.cable_items[1].opacity() == DIMMED
    assert ed.source_items[cable.cable.src].highlighted
    assert ed.target_items[cable.cable.target.slot].highlighted
    assert sum(r.highlighted for r in ed.scene_rows) == 1
    ed.hover_cable(None)
    assert all(c.opacity() == 1.0 for c in ed.cable_items)
    assert not any(r.highlighted for r in ed.scene_rows)


def test_removed_cable_row_goes_straight_to_pool(window):
    page = window.profiles_page
    new_profile(page)
    page.apply_suggestions()
    n = unique_mapped_note(page.work)
    pool_count = len(page.cables.pool_items)
    page.clear_rules([n])
    assert n in page.cables.pool_items and n not in page.cables.source_items
    assert len(page.cables.pool_items) == pool_count + 1
    assert page.undo() and n in page.cables.source_items and n not in page.cables.pool_items  # отмена — тоже сразу

# --- вид «кабелями»: правка ---

def cables_page(window, accept=True, size=(1300, 900)):
    """Новый профиль EZD3 → SD3; accept — применить подсказки; подсказки затем скрыты (✕)."""
    page = window.profiles_page
    window.resize(*size)
    window.show()
    new_profile(page)
    if accept:
        page.apply_suggestions()
    page.dismiss_suggestions()
    QApplication.processEvents()  # отложенные resize окна перерисовывают колонки
    return page, page.cables


def editor_point(ed, view, scene_pt):
    """Точка сцены view в координатах CableEditor."""
    from PySide6.QtCore import QPointF
    return QPointF(view.viewport().mapTo(ed, view.mapFromScene(scene_pt)))


def target_point(ed, slot):
    return editor_point(ed, ed.view, ed.target_items[slot].rect.center())


def show_target_group(ed, slot):
    """Режим «все» для группы цели, в которой лежит артикуляция slot."""
    from midiremap.core.notemap import instrument_group
    from midiremap.ui.cable_layout import TARGET_PREFIX
    if slot in ed.target_items:
        return
    tgt = ed.shown.target_map  # в ← — исходная карта (цель обратного профиля)
    name = next(v for v in tgt.names.values() if "a:" + normalize_name(v) == slot)
    ed.toggle_target(TARGET_PREFIX + normalize_name(instrument_group(name)))
    assert slot in ed.target_items


def pool_row(ed, pred):
    return next(item for item in ed.pool_rows if not item.model.expanded and pred(item))


def header_item(view, key):
    return next(i for i in view.scene().items() if getattr(i, "header", None) is not None and i.header.key == key)


def drop(app, ed, notes, at):
    ed.begin_drag(set(notes), at)
    ed.drag_to(at)
    ed.end_drag(drop=True)
    app.processEvents()


def test_drag_pool_alias_row_onto_target_maps_all_its_notes(window, app):
    page, ed = cables_page(window, accept=False)
    ezd = page.work.source_map
    row = pool_row(ed, lambda i: len(i.notes) > 1)  # строка алиасов EZD3
    assert row.model.alias and row.pill == f"+{len(row.notes) - 1}"
    assert len({normalize_name(ezd.names[n]) for n in row.notes}) == 1
    slot, dst = single_note_articulation(page.work.target_map)
    show_target_group(ed, "a:" + slot)
    drop(app, ed, row.notes, target_point(ed, "a:" + slot))
    assert all(page.work.rules[n] == Rule.map_to(dst) for n in row.notes) and page.dirty
    moved = ed.current.source_row(row.notes[0])
    assert moved.block is None and moved.connected and moved.notes == row.notes
    assert len([c for c in ed.cable_items if c.cable.notes == row.notes]) == 1  # один кабель на строку
    assert not ed.selection


def test_drag_with_real_mouse_events(window, app):
    from PySide6.QtCore import QEvent, QPointF
    from PySide6.QtGui import QMouseEvent
    page, ed = cables_page(window, accept=False)
    slot, dst = single_note_articulation(page.work.target_map)
    show_target_group(ed, "a:" + slot)
    row = pool_row(ed, lambda i: len(i.notes) == 1)
    note = row.notes[0]

    def send(kind, pos, buttons):
        vp = ed.pool.viewport()
        ev = QMouseEvent(kind, pos, QPointF(vp.mapToGlobal(pos.toPoint())), Qt.MouseButton.LeftButton, buttons,
                         Qt.KeyboardModifier.NoModifier)
        QApplication.sendEvent(vp, ev)

    start = QPointF(ed.pool.mapFromScene(row.rect.center()))
    send(QEvent.Type.MouseButtonPress, start, Qt.MouseButton.LeftButton)
    assert ed.selected_notes() == [note]
    send(QEvent.Type.MouseMove, start + QPointF(30, 0), Qt.MouseButton.LeftButton)
    assert ed.dragging
    # курсор над строкой цели: события идут в viewport пула (захват мыши), координаты — за его пределами
    tgt = ed.target_items["a:" + slot]
    at = QPointF(ed.pool.viewport().mapFrom(ed, target_point(ed, "a:" + slot).toPoint()))
    send(QEvent.Type.MouseMove, at, Qt.MouseButton.LeftButton)
    ed._tick()
    assert tgt.drop_zone == ("row",) and ed.overlay.preview and ed.overlay.valid  # середина строки — зона назначения
    send(QEvent.Type.MouseButtonRelease, at, Qt.MouseButton.NoButton)
    app.processEvents()
    assert not ed.dragging and ed.overlay.preview is None
    assert page.work.rules[note] == Rule.map_to(dst)


def test_multi_select_drag_asks_write_to_once(window, app):
    page, ed = cables_page(window, accept=False)
    key, notes = multi_note_articulation(page.work.target_map)
    show_target_group(ed, "a:" + key)
    rows = [i for i in ed.pool_rows if not i.model.expanded and not set(i.notes) & set(notes)][:3]
    no, shift, ctrl = (Qt.KeyboardModifier.NoModifier, Qt.KeyboardModifier.ShiftModifier,
                       Qt.KeyboardModifier.ControlModifier)
    ed._press_row(ed.pool, rows[0], no, rows[0].rect.center())
    ed._press_row(ed.pool, rows[2], shift, rows[2].rect.center())
    sel = {n for r in rows for n in r.notes}
    assert set(ed.selected_notes()) == sel and all(r.selected for r in rows)
    ed._press_row(ed.pool, rows[1], ctrl, rows[1].rect.center())
    sel -= set(rows[1].notes)
    assert set(ed.selected_notes()) == sel and not rows[1].selected
    # Cancel в вопросе о Write to — ничего не меняется
    before = dict(page.work.rules)
    drop(app, ed, ed.selected_notes(), target_point(ed, "a:" + key))
    assert page.work.rules == before and page.answers["asked"][-1][0] == "write_to"
    # выбор — один вопрос на всё перетаскивание
    asked = len(page.answers["asked"])
    page.answers["write_to"] = [notes[-1]]
    drop(app, ed, sel, target_point(ed, "a:" + key))
    assert len(page.answers["asked"]) == asked + 1
    assert all(page.work.rules[n] == Rule.map_to(notes[-1]) for n in sel)
    assert notes[-1] in page.work.target_map.primary


def test_drop_replaces_previous_rule_and_esc_cancels(window, app):
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QKeyEvent
    page, ed = cables_page(window, accept=False)
    slot, dst = single_note_articulation(page.work.target_map)
    show_target_group(ed, "a:" + slot)
    row = pool_row(ed, lambda i: len(i.notes) == 1)
    n = row.notes[0]
    page.delete_notes([n])
    assert ed.current.source_row(n).state == "delete"
    at = target_point(ed, "a:" + slot)
    ed.begin_drag({n}, at)
    ed.drag_to(at)
    QApplication.sendEvent(ed.pool, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape,
                                              Qt.KeyboardModifier.NoModifier))
    app.processEvents()
    assert not ed.dragging and ed.overlay.preview is None and page.work.rules[n] == Rule.delete()
    # отпустили мимо цели — ничего
    drop(app, ed, [n], editor_point(ed, ed.pool, ed.pool_items[n].rect.center()))
    assert page.work.rules[n] == Rule.delete()
    drop(app, ed, [n], at)
    assert page.work.rules[n] == Rule.map_to(dst)


def test_preview_spring_follows_cursor():
    from PySide6.QtCore import QPointF
    from midiremap.ui.cable_view import _Drag
    d = _Drag((1,), QPointF(200, 100), QPointF(0, 0), QPointF(0, 0))
    d.step()
    assert 0 < d.pos.x() < 200  # запаздывает
    for _ in range(60):
        d.step()
    assert abs(d.pos.x() - 200) < 1 and abs(d.pos.y() - 100) < 1


@pytest.mark.parametrize("reverse", [False, True])
def test_first_cable_does_not_collapse_target_groups(window, app, reverse):
    """Новый профиль: группы цели раскрыты. Первый кабель (drag) ничего не сворачивает; режим групп меняет только
    пользователь (клик по заголовку), и он сохраняется при следующих правках."""
    from midiremap.core.profile import REVERSE
    page, ed = cables_page(window, accept=False)
    if reverse:
        page.set_direction(REVERSE)
    keys = {h.key for h in ed.current.scene.target_headers}
    assert keys and ed.show_all == keys and not any(h.collapsed for h in ed.current.scene.target_headers)
    rows = {r.slot for r in ed.current.scene.target_rows}
    top = ed.view.verticalScrollBar().value() + ed.view.viewport().height()
    slot = next(s for s in sorted(rows, key=lambda s: ed.target_items[s].rect.top())
                if s.startswith("a:") and len(ed.target_items[s].notes) == 1
                and ed.target_items[s].rect.bottom() < top)  # одна нота (без вопроса Write to), видна
    note = pool_row(ed, lambda i: len(i.notes) == 1).notes[0]
    drop(app, ed, [note], target_point(ed, slot))
    assert page.work.oriented(page.direction).rules[note].action == "map"
    assert ed.show_all == keys and {r.slot for r in ed.current.scene.target_rows} == rows  # ничего не свернулось
    # пользователь свернул группу — так и остаётся после следующих правок
    head = next(h.key for h in ed.current.scene.target_headers if h.shown < h.count)  # есть что скрыть
    ed.toggle_target(head)
    assert head not in ed.show_all and ed.current.header(head).collapsed
    page.toggle_strike([pool_row(ed, lambda i: True).notes[0]])
    page.undo()
    assert head not in ed.show_all and (ed.show_all | {head}) == keys


def test_existing_profile_opens_with_connected_only_groups(window, app):
    page, ed = cables_page(window)  # с кабелями
    pid = page.current
    page.answers["unassigned"] = set()
    assert page.save()
    page.open(pid)
    assert ed.show_all == set() and any(h.collapsed for h in ed.current.scene.target_headers)


def test_autoscroll_near_edge(window, app):
    from PySide6.QtCore import QPointF
    _page, ed = cables_page(window, accept=False, size=(1200, 600))
    pool_bar, scene_bar = ed.pool.verticalScrollBar(), ed.view.verticalScrollBar()
    assert pool_bar.maximum() > 0 and scene_bar.maximum() > 0 and pool_bar.value() == scene_bar.value() == 0
    # у нижнего края пула — пул НЕ прокручивается (в него не бросают; строки пула не уезжают)
    vp = ed.pool.viewport()
    bottom = QPointF(vp.mapTo(ed, vp.rect().bottomLeft()))
    ed.begin_drag({ed.pool_rows[0].notes[0]}, QPointF(bottom.x() + 40, bottom.y() - 4))
    ed._tick()
    ed._tick()
    assert pool_bar.value() == 0 and scene_bar.value() == 0
    # у нижнего края сцены — сцена прокручивается
    vp = ed.view.viewport()
    bottom = QPointF(vp.mapTo(ed, vp.rect().bottomLeft()))
    ed.drag_to(QPointF(bottom.x() + 40, bottom.y() - 4))
    ed._tick()
    ed._tick()
    assert scene_bar.value() > 0 and pool_bar.value() == 0
    ed.cancel_drag()


def test_pool_items_never_move_during_drag_and_keep_place_after_drop(window, app):
    """Тащат строку у нижнего края пула вдоль края и через весь экран: ни одна строка пула не двигается
    (ни прокрутки, ни перестройки); после drop пул держит прокрутку (строка ушла — соседние на месте)."""
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QMouseEvent
    page, ed = cables_page(window, accept=False, size=(1200, 600))
    bar = ed.pool.verticalScrollBar()
    bar.setValue(bar.maximum() // 2)
    vp = ed.pool.viewport()
    top = bar.value()
    row = max((i for i in ed.pool_rows if i.rect.bottom() < top + vp.height() - 2), key=lambda i: i.rect.top())
    note = row.notes[0]

    def send(kind, pos, buttons):
        QApplication.sendEvent(vp, QMouseEvent(kind, pos, QPointF(vp.mapToGlobal(pos.toPoint())),
                                               Qt.MouseButton.LeftButton, buttons, Qt.KeyboardModifier.NoModifier))

    def pool_state():
        return bar.value(), [(i.notes, i.rect.top()) for i in ed.pool_rows]

    before = pool_state()
    start = QPointF(ed.pool.mapFromScene(row.rect.center()))
    send(QEvent.Type.MouseButtonPress, start, Qt.MouseButton.LeftButton)
    for k in range(1, 25):  # вдоль нижнего края пула (зона автопрокрутки) и дальше в сцену
        send(QEvent.Type.MouseMove, start + QPointF(k * 30, 0), Qt.MouseButton.LeftButton)
        ed._tick()
        assert pool_state() == before
    slot, dst = single_note_articulation(page.work.target_map)
    at = QPointF(vp.mapFrom(ed, target_point(ed, "a:" + slot).toPoint()))
    send(QEvent.Type.MouseMove, at, Qt.MouseButton.LeftButton)
    ed._tick()
    assert pool_state() == before
    neighbours = {i.notes[0]: i.rect.top() - bar.value() for i in ed.pool_rows if i.notes[0] != note
                  and top <= i.rect.top() < top + vp.height() - cable_view.ROW}
    send(QEvent.Type.MouseButtonRelease, at, Qt.MouseButton.NoButton)
    app.processEvents()
    assert page.work.rules[note] == Rule.map_to(dst)
    after = {i.notes[0]: i.rect.top() - bar.value() for i in ed.pool_rows if i.notes[0] in neighbours}
    above = {n: y for n, y in neighbours.items() if y < row.rect.top() - top}
    assert above and all(after[n] == y for n, y in above.items())  # строки выше ушедшей — на тех же местах


def test_right_click_cable_removes_connection(window, app):
    from midiremap.ui.cable_layout import UNASSIGNED
    page, ed = cables_page(window)
    cable = ed.cable_items[0]
    notes = cable.cable.notes
    pos = ed.view.mapFromScene(cable.path().pointAtPercent(0.5))
    QTest.mouseClick(ed.view.viewport(), Qt.MouseButton.RightButton, pos=pos)
    app.processEvents()
    assert all(n not in page.work.rules for n in notes) and page.dirty
    # сразу обратно в свою группу пула
    assert notes[0] in ed.pool_items and notes[0] not in ed.source_items
    assert ed.current.source_row(notes[0]).block == UNASSIGNED

def _swipe_page(window, reverse=False):
    from midiremap.core.profile import REVERSE
    page, ed = cables_page(window)  # подсказки применены — много кабелей
    if reverse:
        page.set_direction(REVERSE)
        page.apply_suggestions()
    QApplication.processEvents()
    assert len(ed.cable_items) > 6
    return page, ed


def _gap_x(ed):
    """x середины промежутка между колонками (там проходят все кабели)."""
    c = ed.cable_items[0]
    return (c.src.rect.right() + c.dst.rect.left()) / 2


def _crossing(ed, x, y0, y1):
    """Кабели, чья линия пересекает вертикаль x между y0 и y1 (по самому пути кабеля)."""
    out = set()
    for c in ed.cable_items:
        path = c.path()
        ys = [path.pointAtPercent(t / 200).y() for t in range(201)
              if abs(path.pointAtPercent(t / 200).x() - x) < 1.5]
        if ys and y0 <= min(ys) <= y1:
            out.add(c.ends)
    return out


def _right(view, kind, pt):
    from PySide6.QtCore import QEvent
    send_mouse(view, getattr(QEvent.Type, kind), pt, Qt.MouseButton.RightButton)


@pytest.mark.parametrize("reverse", [False, True])
def test_swipe_marks_crossed_cables_and_deletes_them_in_one_undo_step(window, app, reverse):
    page, ed = _swipe_page(window, reverse)
    x = _gap_x(ed)
    cables = sorted(ed.cable_items, key=lambda c: c.path().pointAtPercent(0.5).y())
    y0, y1 = cables[1].src.rect.top() - 2, cables[5].src.rect.bottom() + 2
    expected = _crossing(ed, x, y0, y1)
    assert len(expected) >= 3
    before_items, before_rules = list(ed.cable_items), page.work.to_dict()
    steps = len(page._undo)
    _right(ed.view, "MouseButtonPress", QPointF(x, y0))
    assert ed.swiping and not ed.swiped_cables()
    for k in range(1, 9):  # протяжка вниз через кабели
        _right(ed.view, "MouseMove", QPointF(x + (k % 2) * 3, y0 + (y1 - y0) * k / 8))
    marked = {c.ends for c in ed.swiped_cables()}
    assert marked == expected  # отмечено ровно то, что пересёк путь
    assert all(c.pen().color().name() == cable_view.TOKENS["error"].lower() for c in ed.swiped_cables())
    # во время росчерка — ни перестройки, ни правки
    assert ed.cable_items == before_items and page.work.to_dict() == before_rules
    _right(ed.view, "MouseButtonRelease", QPointF(x, y1))
    app.processEvents()
    oriented = page.work.oriented(page.direction)
    gone = {n for c in before_items if c.ends in marked for n in c.cable.notes}
    assert gone and all(oriented.rules.get(n) is None or oriented.rules[n].action != "map" for n in gone)
    assert not ed.swiping and not ed.swiped_cables()
    assert len(page._undo) == steps + 1  # один шаг отмены на весь росчерк
    assert page.undo() and page.work.to_dict() == before_rules
    assert {c.ends for c in ed.cable_items} >= marked


def test_fast_swipe_hits_cables_between_mouse_events(window, app):
    """Одно движение через много кабелей (между событиями мыши нет промежуточных точек) — отмечены все."""
    _page, ed = _swipe_page(window)
    x = _gap_x(ed)
    cables = sorted(ed.cable_items, key=lambda c: c.path().pointAtPercent(0.5).y())
    y0, y1 = cables[0].src.rect.top() - 2, cables[6].src.rect.bottom() + 2
    _right(ed.view, "MouseButtonPress", QPointF(x - 20, y0))
    _right(ed.view, "MouseMove", QPointF(x + 20, y1))  # один длинный отрезок
    assert {c.ends for c in ed.swiped_cables()} == _crossing(ed, x, y0, y1) and len(ed.swiped_cables()) >= 5
    ed.cancel_swipe()


def test_swipe_esc_cancels_and_plain_right_click_deletes_one(window, app):
    page, ed = _swipe_page(window)
    x = _gap_x(ed)
    cables = sorted(ed.cable_items, key=lambda c: c.path().pointAtPercent(0.5).y())
    y0, y1 = cables[0].src.rect.top() - 2, cables[4].src.rect.bottom() + 2
    before, steps = page.work.to_dict(), len(page._undo)
    _right(ed.view, "MouseButtonPress", QPointF(x, y0))
    _right(ed.view, "MouseMove", QPointF(x, y1))
    assert ed.swiped_cables()
    QTest.keyClick(ed.view, Qt.Key.Key_Escape)
    assert not ed.swiping and not ed.swiped_cables()
    _right(ed.view, "MouseButtonRelease", QPointF(x, y1))  # отпускание после Esc — ничего
    app.processEvents()
    assert page.work.to_dict() == before and len(page._undo) == steps
    # правый клик без сдвига — как раньше: один кабель
    one = cables[2]
    notes = one.cable.notes
    pt = one.path().pointAtPercent(0.5)
    _right(ed.view, "MouseButtonPress", pt)
    _right(ed.view, "MouseButtonRelease", pt)
    app.processEvents()
    assert all(n not in page.work.rules for n in notes) and len(page._undo) == steps + 1
    assert len(ed.cable_items) == len(cables) - 1


def test_right_click_pool_row_and_group_toggle_strike(window, app):
    from midiremap.ui.cable_layout import KEEP, UNASSIGNED
    page, ed = cables_page(window, accept=False)
    row = ed.pool_rows[0]
    notes = row.notes
    QTest.mouseClick(ed.pool.viewport(), Qt.MouseButton.RightButton, pos=ed.pool.mapFromScene(row.rect.center()))
    assert all(page.work.rules[n] == Rule.delete() for n in notes)
    row = ed.pool_items[notes[0]]
    assert row.strike and row.model.block == UNASSIGNED
    page.cables.refresh()  # и после пересортировки — на месте, зачёркнута
    row = ed.pool_items[notes[0]]
    assert row.strike and row.model.block == UNASSIGNED and row.rect.top() == ed.pool_rows[0].rect.top()
    QTest.mouseClick(ed.pool.viewport(), Qt.MouseButton.RightButton, pos=ed.pool.mapFromScene(row.rect.center()))
    assert all(n not in page.work.rules for n in notes)
    # группа: зачеркнуть всю; если уже вся зачёркнута — вернуть
    head = ed.current.pool.headers[0]
    page.delete_notes([head.notes[0]])
    item = header_item(ed.pool, head.key)
    QTest.mouseClick(ed.pool.viewport(), Qt.MouseButton.RightButton, pos=ed.pool.mapFromScene(item.rect.center()))
    assert all(page.work.rules[n] == Rule.delete() for n in head.notes)
    ed.right_click(header_item(ed.pool, head.key))
    assert all(n not in page.work.rules for n in head.notes)
    # явный keep (старые профили) — в Unassigned с маркером «=»; правый клик — delete ↔ без правила
    for n in notes:
        page.work.rules[n] = Rule.keep()
    page.cables.refresh()
    keep_row = ed.pool_items[notes[0]]
    assert keep_row.model.block == UNASSIGNED and keep_row.marker == "="
    assert "Kept on the same number" in keep_row.toolTip()
    assert ed.current.header(KEEP) is None
    ed.right_click(keep_row)
    assert all(page.work.rules[n] == Rule.delete() for n in notes)
    ed.right_click(ed.pool_items[notes[0]])
    assert all(n not in page.work.rules for n in notes)


def test_write_to_badge_repoints_rules(window, app, storage):
    page, ed = cables_page(window, accept=False)
    key, notes = multi_note_articulation(page.work.target_map)
    slot = "a:" + key
    srcs = [n for n in sorted(page.work.source_map.names) if n not in page.work.rules and n not in notes][:2]
    page.answers["write_to"] = [notes[0]]
    assert page.connect_to(srcs, slot)
    assert all(page.work.rules[n] == Rule.map_to(notes[0]) for n in srcs)
    item = ed.target_items[slot]
    assert item.badge and item.pill == f"+{len(notes) - 1}"
    ed.pick_write_to = lambda t, at: notes[-1]
    QTest.mouseClick(ed.view.viewport(), Qt.MouseButton.LeftButton,
                     pos=ed.view.mapFromScene(item.badge_rect().center()))
    app.processEvents()
    assert page.work.target_map.primary & set(notes) == {notes[-1]}
    assert all(page.work.rules[n] == Rule.map_to(notes[-1]) for n in srcs)
    assert ed.current.target_row(slot).write_to == notes[-1]
    page.answers["unassigned"] = set()
    assert page.save()
    assert storage.load_profile(page.current).target_map.primary & set(notes) == {notes[-1]}
    assert not load_map_template("Superior Drummer 3").primary  # шаблон не тронут


def test_target_groups_connected_only_and_toggle(window, app):
    page, ed = cables_page(window, accept=False)
    heads = ed.current.scene.target_headers
    # без связей (новый профиль) — все группы раскрыты
    assert heads and not any(h.collapsed or h.shown for h in heads)
    assert len(ed.current.scene.target_rows) == sum(h.count for h in heads)
    key, notes = three_note_articulation(page.work)
    assert page.connect_to(notes[:1], "a:" + key)  # первый кабель режим групп не меняет — всё ещё раскрыты
    heads = [h for h in ed.current.scene.target_headers if not h.shown]
    assert heads and not any(h.collapsed for h in ed.current.scene.target_headers)
    # клик по заголовку — «только подключённые» (группа без кабелей — один заголовок), ещё клик — снова «все»
    ed.show_all.clear()
    ed.refresh()
    head = heads[0]
    assert ed.current.header(head.key).collapsed
    item = header_item(ed.view, head.key)
    QTest.mouseClick(ed.view.viewport(), Qt.MouseButton.LeftButton, pos=ed.view.mapFromScene(item.rect.center()))
    app.processEvents()
    assert head.key in ed.show_all and not ed.current.header(head.key).collapsed
    assert len(ed.current.scene.target_rows) == head.count + 1  # + подключённая артикуляция другой группы
    # без режима «все» видны только подключённые артикуляции
    page.group_drop(sorted(page.work.source_map.names), sorted(page.work.target_map.names))
    ed.show_all.clear()
    page.cables.refresh()
    lay = ed.current.scene
    assert any(h.shown for h in lay.target_headers)
    assert len(lay.target_rows) == sum(h.shown for h in lay.target_headers)


def test_spring_loaded_group_opens_while_dragging(window, app):
    _page, ed = cables_page(window)
    ed.show_all.clear()  # пользователь перевёл группы в «только подключённые»
    ed.refresh()
    head = next(h for h in ed.current.scene.target_headers if h.collapsed)
    item = header_item(ed.view, head.key)
    at = editor_point(ed, ed.view, item.rect.center())
    ed.begin_drag({ed.pool_rows[0].notes[0]}, at)
    ed.drag_to(at)
    assert ed._spring.isActive() and item.highlighted
    ed._spring_open()  # ~500 мс наведения
    assert head.key in ed.show_all and ed.dragging
    assert not ed.current.header(head.key).collapsed
    ed.cancel_drag()


def test_alias_expand_in_pool_leaves_scene_untouched(window, app):
    page, ed = cables_page(window)
    row = pool_row(ed, lambda i: len(i.notes) > 1)
    notes = row.notes
    scene_items = list(ed.scene_rows)
    QTest.mouseClick(ed.pool.viewport(), Qt.MouseButton.LeftButton,
                     pos=ed.pool.mapFromScene(row.chevron_rect().center()))
    app.processEvents()
    head = next(i for i in ed.pool_rows if i.model.expanded and i.notes == notes)
    children = [i for i in ed.pool_rows if i.model.child and i.notes[0] in notes]
    assert len(children) == len(notes) and head.chevron == "expanded"
    assert ed.scene_rows == scene_items  # сцена не перестраивалась
    # тащим одну ноту из раскрытых — разделение алиасов
    slot, dst = single_note_articulation(page.work.target_map)
    show_target_group(ed, "a:" + slot)
    drop(app, ed, [notes[0]], target_point(ed, "a:" + slot))
    assert page.work.rules[notes[0]] == Rule.map_to(dst)
    assert all(page.work.rules.get(n) != Rule.map_to(dst) for n in notes[1:])


def test_pool_collapse_rebuilds_only_pool(window, app):
    _page, ed = cables_page(window)
    scene_items = list(ed.scene_rows)
    key = ed.current.pool.headers[0].key
    ed.toggle_pool(key)
    assert ed.current.header(key).collapsed and ed.scene_rows == scene_items





# --- назначение по номерам, группа, номера цели, отмена ---

def three_note_articulation(p):
    """Артикуляция цели на трёх+ нотах, все номера которых есть в исходной карте."""
    return next((k, v) for k, v in articulations(p.target_map).items()
                if len(v) > 2 and all(n in p.source_map.names for n in v))


def test_drop_same_numbers_need_no_question(window, app):
    page, ed = cables_page(window, accept=False)
    key, notes = three_note_articulation(page.work)
    assert page.connect_to(notes[:2], "a:" + key)
    assert all(page.work.rules[n] == Rule.map_to(n) for n in notes[:2])
    assert page.answers["asked"] == [] and not page.work.target_map.primary & set(notes)
    # строка цели показывает оба номера — каждый кабель на своём
    t = ed.current.target_row("a:" + key)
    assert sorted(n for _, n in t.lines) == notes[:2] and t.hidden == len(notes) - 2
    for c in ed.cable_items:
        if c.cable.target.slot == "a:" + key:
            assert c.cable.dst_y == c.cable.src_y
    item = ed.target_items["a:" + key]
    assert [line[1] for line in item.lines] == [str(n) for _, n in t.lines]
    assert item.pill == f"+{len(notes) - 2}"


def test_drop_single_match_becomes_write_to_silently(window, app):
    page, ed = cables_page(window, accept=False)
    key, notes = three_note_articulation(page.work)
    (other,) = notes_off(page.work, notes, 1)
    assert page.connect_to([other, notes[1]], "a:" + key)
    assert page.work.rules == {other: Rule.map_to(notes[1]), notes[1]: Rule.map_to(notes[1])}
    assert page.work.target_map.primary & set(notes) == {notes[1]} and page.answers["asked"] == []
    item = ed.target_items["a:" + key]
    assert [line[1] for line in item.lines] == [str(notes[1])]
    assert f"Write to: {notes[1]}" in item.toolTip()  # Write to — в подсказке (и галочкой в меню «+N»)


def test_drop_several_matches_asks_once_with_preselect(window, app):
    page, _ed = cables_page(window, accept=False)
    key, notes = three_note_articulation(page.work)
    (other,) = notes_off(page.work, notes, 1)
    page.answers["write_to"] = [notes[2]]
    assert page.connect_to([other, notes[0], notes[1]], "a:" + key)
    assert [x[0] for x in page.answers["asked"]] == ["write_to"] and page.answers["preselect"] == notes[0]
    assert page.work.rules == {notes[0]: Rule.map_to(notes[0]), notes[1]: Rule.map_to(notes[1]),
                               other: Rule.map_to(notes[2])}
    # смена Write to через «+N» переводит только правила на прежний Write to (n → n остаются)
    assert page.set_write_to(notes[1])
    assert page.work.rules == {notes[0]: Rule.map_to(notes[0]), notes[1]: Rule.map_to(notes[1]),
                               other: Rule.map_to(notes[1])}


def test_group_drop_on_target_header(window, app):
    from midiremap.ui.cable_layout import TARGET_PREFIX
    page, ed = cables_page(window, accept=False)
    snare = ed.current.header(TARGET_PREFIX + "snare")
    src = page.work.source_map
    dropped = sorted(n for n in src.names if src.names[n].startswith("Snare")) + [36]
    page.work.rules[dropped[0]] = Rule.map_to(36)  # уже подключена — не трогаем
    item = header_item(ed.view, snare.key)
    drop(app, ed, dropped, editor_point(ed, ed.view, item.rect.center()))
    matched = [n for n in dropped[1:] if n in snare.notes]
    assert matched and page.answers["asked"] == []
    assert all(page.work.rules[n] == Rule.map_to(n) for n in matched)
    assert page.work.rules[dropped[0]] == Rule.map_to(36) and 36 not in page.work.rules
    assert page.status.text() == f"{len(matched)} of {len(dropped)} connected"


def test_drag_pool_group_header(window, app):
    from PySide6.QtCore import QEvent, QPointF
    from PySide6.QtGui import QMouseEvent
    from midiremap.ui.cable_layout import POOL_PREFIX, TARGET_PREFIX
    page, ed = cables_page(window, accept=False)
    head = ed.current.header(POOL_PREFIX + "snare")
    pool_item = ed.pool_headers[head.key]
    target = header_item(ed.view, TARGET_PREFIX + "snare")
    vp = ed.pool.viewport()

    def send(kind, pos, buttons):
        QApplication.sendEvent(vp, QMouseEvent(kind, pos, QPointF(vp.mapToGlobal(pos.toPoint())),
                                               Qt.MouseButton.LeftButton, buttons, Qt.KeyboardModifier.NoModifier))
    start = QPointF(ed.pool.mapFromScene(pool_item.rect.center()))
    send(QEvent.Type.MouseButtonPress, start, Qt.MouseButton.LeftButton)
    send(QEvent.Type.MouseMove, start + QPointF(30, 0), Qt.MouseButton.LeftButton)
    assert ed.dragging and set(ed._drag.notes) == set(head.notes)
    ed._tick()
    assert len(ed.overlay.preview) == 1  # один кабель — от заголовка
    at = QPointF(vp.mapFrom(ed, editor_point(ed, ed.view, target.rect.center()).toPoint()))
    send(QEvent.Type.MouseMove, at, Qt.MouseButton.LeftButton)
    ed._tick()
    assert target.highlighted and ed.overlay.valid
    send(QEvent.Type.MouseButtonRelease, at, Qt.MouseButton.NoButton)
    app.processEvents()
    snare_notes = ed.current.header(TARGET_PREFIX + "snare").notes
    assert {n for n in head.notes if n in snare_notes} == {n for n, r in page.work.rules.items()
                                                           if r == Rule.map_to(n)}
    assert not ed.current.header(head.key) or not ed.current.header(head.key).collapsed  # не свернулся


def test_undo_redo_stack(window, app, storage):
    page, ed = cables_page(window, accept=False)
    key, notes = three_note_articulation(page.work)
    n = notes_off(page.work, notes, 1)[0]
    assert len(page._undo) == 2  # выбор исходной и целевой карты при создании — тоже шаги
    page.connect_to(notes[:1], "a:" + key)           # 1: подключить
    page.toggle_strike([n])                           # 2: зачеркнуть
    page.answers["confirm"] = True
    page.choose_map("target", MapRef(TEMPLATE, "General MIDI"))  # 3: смена карты
    assert page.work.target_map.name == "General MIDI"
    assert page.undo() and page.work.target_map.name == "Superior Drummer 3"
    assert page.undo() and n not in page.work.rules
    assert page.redo() and page.work.rules[n] == Rule.delete()
    assert page.undo() and page.undo() and page.work.rules == {} and len(page._undo) == 2
    assert page.undo() and page.work.target_map is None  # до выбора целевой карты
    assert page.redo() and page.redo() and page.work.rules == {notes[0]: Rule.map_to(notes[0])}
    assert ed.profile is page.work
    # новое действие сбрасывает повтор
    page.clear_rules(notes[:1])
    assert not page.redo()
    # горячие клавиши (в подсказках) — на странице
    assert "Ctrl+Z" in page.revert_btn.toolTip() and "Ctrl+Y" in page.revert_btn.toolTip()
    ed.view.setFocus()
    QTest.keyClick(ed.view, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    assert page.work.rules == {notes[0]: Rule.map_to(notes[0])}
    QTest.keyClick(ed.view, Qt.Key.Key_Y, Qt.KeyboardModifier.ControlModifier)
    assert page.work.rules == {}
    # Save стек не очищает; открытие другого профиля — очищает
    page.connect_to(notes[:1], "a:" + key)
    page.answers["unassigned"] = set()
    assert page.save() and page.undo()
    assert page.work.rules == {notes[0]: Rule.map_to(notes[0])} and page.dirty
    page.answers["save_changes"] = "discard"
    page.select(LEGACY_ID)
    assert not page.undo() and not page.redo()


# --- полировка: «+N» у алиасов, список профилей, ширины колонок, полные имена ---

def test_alias_row_badge_and_shown_number(window, app):
    _page, ed = cables_page(window)
    # свёрнутая строка алиасов: «+N» и номер ноты n → n
    item = next((i for i in ed.scene_rows if len(i.notes) > 1 and not i.model.expanded and i.model.same), None)
    assert item is not None
    row = item.model
    assert item.pill == f"+{len(row.notes) - 1}" and not item.badge  # бейдж источника не кликабелен
    assert item.number == str(row.shown)
    assert all(str(n) in item.toolTip() for n in row.notes)  # номера — в подсказке
    pool = next(i for i in ed.pool_rows if len(i.notes) > 1 and not i.model.expanded)
    assert pool.number == str(min(pool.notes))


def test_two_row_header_with_visible_profile_buttons(window, app, storage):
    """Верхняя строка: профиль (слева) и New / Duplicate / Rename / Delete … статус, Revert, Save; меню «⋯» и ↻
    нет. Строка над колонками: Unassigned + Match by number | карта «from», направление, карта «to»."""
    page = window.profiles_page
    assert not hasattr(page, "list") and not hasattr(page, "sidebar_btn") and not hasattr(page, "title")
    assert not hasattr(page, "more_btn") and not hasattr(page, "refresh_btn")
    assert page.combo.currentIndex() == -1 and page.combo.placeholderText() == "Select a profile"
    assert page.new_btn.isEnabled()
    assert not page.rename_btn.isEnabled() and not page.delete_btn.isEnabled() and not page.duplicate_btn.isEnabled()
    pid = new_profile(page, "Kit")
    assert page.combo.currentData(ID_ROLE) == pid and page.combo.currentText() == "• Kit"  # карты выбраны — правка
    assert page.rename_btn.isEnabled() and page.duplicate_btn.isEnabled() and page.delete_btn.isEnabled()
    assert [b.text() for b in (page.new_btn, page.duplicate_btn, page.rename_btn, page.delete_btn)] == [
        "New", "Duplicate", "Rename", "Delete"]
    top = (page.combo, page.new_btn, page.duplicate_btn, page.rename_btn, page.delete_btn, page.status,
           page.revert_btn, page.save_btn)
    window.resize(1300, 900)
    window.show()
    QApplication.processEvents()
    centers = {w.mapTo(page, w.rect().center()).y() for w in top}
    assert max(centers) - min(centers) <= 2  # одна строка
    assert len({w.height() for w in page.header_controls}) == 1
    xs = [w.mapTo(page, w.rect().topLeft()).x() for w in top]
    assert xs == sorted(xs) and xs[0] <= 2  # профиль — слева, Save — справа
    # строка над колонками
    ed = page.cables
    assert ed.pool_head.indexOf(ed.pool_title) >= 0 and ed.pool_head.indexOf(page.match_btn) >= 0
    assert page.match_btn.text() == "Match by number"
    assert ed.from_head.indexOf(page.source_btn) >= 0 and ed.to_head.indexOf(page.target_btn) >= 0
    assert ed.gap_head.indexOf(page.direction_btn) >= 0
    assert not hasattr(page, "summary") and ed.to_head.indexOf(page.suggest_bar) >= 0
    assert page.source_btn.text() == "EZdrummer 3" and page.target_btn.text() == "Superior Drummer 3"
    second = (ed.pool_title, page.match_btn, page.from_btn, page.direction_btn, page.to_btn)
    assert len({w.mapTo(page, w.rect().center()).y() for w in second}) <= 2
    assert min(w.mapTo(page, w.rect().topLeft()).y() for w in second) > max(
        w.mapTo(page, w.rect().bottomLeft()).y() for w in top)  # ниже верхней строки
    # Delete — то же подтверждение
    page.answers["confirm"] = False
    page.delete_btn.click()
    assert storage.load_profile(pid) is not None
    page.answers["confirm"] = True
    page.delete_btn.click()
    assert page.current is None and page.combo.currentIndex() == -1
    assert page.combo.findData(pid, ID_ROLE) == -1

def test_switching_profile_in_combo_asks_about_unsaved(window, app):
    page = window.profiles_page
    a = new_profile(page, "A")
    page.answers["unassigned"] = set()
    page.save()
    page.clear_rules([sorted(page.work.source_map.names)[0]])
    assert page.dirty
    page.answers["save_changes"] = "cancel"
    page.combo.setCurrentIndex(page.combo.findData(LEGACY_ID, ID_ROLE))
    assert page.current == a and page.combo.currentData(ID_ROLE) == a and page.combo.currentText() == "• A"
    page.answers["save_changes"] = "save"
    page.combo.setCurrentIndex(page.combo.findData(LEGACY_ID, ID_ROLE))
    assert page.current == LEGACY_ID and page.combo.currentData(ID_ROLE) == LEGACY_ID and not page.dirty
    assert page.answers["asked"].count("save_changes") == 2


def test_old_sidebar_key_is_ignored(app, storage):
    from midiremap.ui.settings import ui_settings
    s = ui_settings(storage)
    s.setValue("profiles/sidebar_collapsed", True)
    s.sync()
    w = MainWindow(storage)
    assert w.profiles_page.combo.isVisibleTo(w.profiles_page)
    w.close()


def test_scene_columns_resize_and_persist(window, app, storage):
    from PySide6.QtCore import QEvent, QPointF
    from PySide6.QtGui import QMouseEvent
    from midiremap.ui.cable_view import COLUMNS_KEY, POOL_KEY, PORT, SCENE_MIN
    page, ed = cables_page(window)
    vp = ed.view.viewport()
    width = ed.view.width_px(SCENE_MIN)

    def send(kind, x, buttons):
        pos = QPointF(x, 40)
        QApplication.sendEvent(vp, QMouseEvent(kind, pos, QPointF(vp.mapToGlobal(pos.toPoint())),
                                               Qt.MouseButton.LeftButton, buttons, Qt.KeyboardModifier.NoModifier))

    def drag_edge(edge, dx):
        x = ed._boundaries(width)[edge] + (PORT + 3 if edge != 1 else -PORT - 3)
        send(QEvent.Type.MouseMove, x, Qt.MouseButton.NoButton)
        assert ed.view.guide_x is not None and vp.cursor().shape() == Qt.CursorShape.SplitHCursor
        send(QEvent.Type.MouseButtonPress, x, Qt.MouseButton.LeftButton)
        send(QEvent.Type.MouseMove, x + dx, Qt.MouseButton.LeftButton)
        send(QEvent.Type.MouseButtonRelease, x + dx, Qt.MouseButton.NoButton)

    b2, b3, end = ed._boundaries(width)
    rules = dict(page.work.rules)
    drag_edge(0, -60)  # колонка 2 уже, промежуток шире, цель на месте
    nb2, nb3, nend = ed._boundaries(width)
    assert abs(nb2 - (b2 - 60)) < 1 and abs(nb3 - b3) < 1 and abs(nend - end) < 1
    drag_edge(1, 40)  # промежуток шире, колонка 3 уже (правый край на месте)
    drag_edge(2, -30)  # колонка 3 ещё уже, справа — свободное место
    nb2, nb3, nend = ed._boundaries(width)
    assert abs(nb3 - (b3 + 40)) < 1 and abs(nend - (end - 30)) < 1
    t = next(iter(ed.target_items.values()))
    assert abs(t.rect.left() - nb3) < 1 and abs(t.rect.right() - nend) < 1
    # кнопки карт над колонками — следуют за границами
    lx, rx, col2, col3 = ed._scene_columns(width)
    off = ed.scene_head.mapFromGlobal(vp.mapToGlobal(QPoint(0, 0))).x()
    assert abs(ed.from_slot.x() - (off + lx)) <= 1 and abs(ed.from_slot.width() - col2) <= 1
    assert abs(ed.to_slot.x() - (off + rx)) <= 1 and abs(ed.to_slot.width() - col3) <= 1
    assert page.work.rules == rules and not ed.dragging  # граница — не перетаскивание кабеля
    assert page.settings.value(COLUMNS_KEY)
    ed.splitter.setSizes([300, 900])
    ed.splitter.splitterMoved.emit(300, 1)
    sizes = ed.splitter.sizes()
    assert int(page.settings.value(POOL_KEY)) == sizes[0]
    w2 = MainWindow(storage)  # ширины — между запусками
    assert w2.profiles_page.cables.columns == pytest.approx(ed.columns, abs=1e-3)
    w2.resize(window.size())
    w2.show_page(PAGE_PROFILES)
    w2.show()
    QApplication.processEvents()
    assert w2.profiles_page.cables.splitter.sizes()[0] == sizes[0]
    w2.close()


def test_old_column_width_keys_are_ignored(app, storage):
    from midiremap.ui.cable_view import POOL_WIDTH
    from midiremap.ui.settings import ui_settings
    s = ui_settings(storage)
    s.setValue("cables/pool_width", 420)  # ключи прежней раскладки с двумя пулами
    s.setValue("cables/pool_right_width", 380)
    s.setValue("cables/columns", "0.2,0.5,0.2")
    s.sync()
    w = MainWindow(storage)
    w.resize(1300, 900)
    w.show_page(PAGE_PROFILES)
    w.show()
    QApplication.processEvents()
    ed = w.profiles_page.cables
    assert ed.columns is None and ed.splitter.sizes()[0] == POOL_WIDTH
    w.close()


def test_truncated_names_in_tooltips(window, app):
    _page, ed = cables_page(window, size=(900, 700))
    ed.columns = (0.2, 0.6, 0.2)  # узкие колонки — длинные имена обрезаются
    ed.refresh()
    from midiremap.ui.cable_view import _font
    from PySide6.QtGui import QFontMetrics
    fm = QFontMetrics(_font(ed.view.font()))
    cut = [i for i in ed.target_items.values() if fm.horizontalAdvance(i.name) > i.name_room()]
    fits = [i for i in ed.target_items.values() if fm.horizontalAdvance(i.name) <= i.name_room()]
    assert cut and all(i.toolTip().startswith(i.name) for i in cut)
    assert all(not i.toolTip().startswith(i.name) for i in fits if i.toolTip())


def test_primary_cable_thicker_others_thinner(window):
    src = NoteMap("S", {12: "Hat", 13: "Hat", 15: "Hat", 20: "Tom"})
    tgt = NoteMap("T", {12: "Hat", 45: "Hat", 78: "Hat", 30: "Tom"}, primary={12})
    rules = {n: Rule.map_to(12) for n in (13, 15)} | {12: Rule.map_to(12), 20: Rule.map_to(30)}
    ed = window.profiles_page.cables
    ed.set_profile(RemapProfile("p", src, tgt, rules))
    ed.toggle_alias("a:hat|hat", in_pool=False)
    width = {item.cable.notes: item.pen().widthF() for item in ed.cable_items}
    assert width == {(12,): cable_view.CABLE_PRIMARY_W, (13,): cable_view.CABLE_THIN_W,
                     (15,): cable_view.CABLE_THIN_W, (20,): cable_view.CABLE_PRIMARY_W}
    assert cable_view.CABLE_PRIMARY_W == cable_view.CABLE_W and cable_view.CABLE_THIN_W == cable_view.CABLE_W / 2


def test_drag_preview_thin_from_unassigned_notes(window):
    src = NoteMap("S", {36: "Kick", 38: "Snare"})
    tgt = NoteMap("T", {36: "Kick", 38: "Snare"})
    ed = window.profiles_page.cables
    ed.set_profile(RemapProfile("p", src, tgt, {36: Rule.map_to(36)}))
    ed.begin_drag({38}, QPointF(0, 0))
    assert ed.overlay.width == cable_view.CABLE_THIN_W
    ed.cancel_drag()
    ed.begin_drag({36}, QPointF(0, 0))  # подключённая строка — обычный кабель
    assert ed.overlay.width == cable_view.CABLE_W
    ed.cancel_drag()


# --- двунаправленные профили ---

def test_reverse_rules_follow_connect_with_undo_redo(window, app):
    from midiremap.core.profile import derive_reverse
    page, _ed = cables_page(window, accept=False)
    page.work.reverse_rules = derive_reverse(page.work)  # заданы явно (как после сохранения формата 2)
    key, notes = three_note_articulation(page.work)
    n = notes[0]
    assert n not in page.work.reverse_rules
    assert page.connect_to([n], "a:" + key)
    rev = page.work.effective_reverse()
    assert rev[n] == Rule.map_to(n)
    assert all(rev[m] == Rule.map_to(n) for m in notes)  # алиасы цели — туда же
    assert page.work.reverse_rules is None  # следуют за прямыми и равны выведенным — хранятся как None
    assert page.undo()
    assert not set(notes) & set(page.work.effective_reverse())
    assert page.redo()
    assert page.work.effective_reverse()[n] == Rule.map_to(n)


def test_map_change_resets_reverse_rules_in_one_undo_step(window, app):
    page, _ed = cables_page(window)
    manual = {36: Rule.delete(), 38: Rule.map_to(40)}
    page.work.reverse_rules = dict(manual)
    assert page.choose_map("target", EZD3)
    assert page.work.reverse_rules is None  # снова выводятся из прямых
    assert page.undo()
    assert page.work.reverse_rules == manual and page.work.target_map.name == "Superior Drummer 3"
    assert page.redo() and page.work.reverse_rules is None


def test_convert_direction_toggle(app, storage, tmp_path):
    from midiremap.core.profile import FORWARD, REVERSE
    from midiremap.ui.main_window import DIRECTION_KEY
    w = MainWindow(storage)
    page = w.profiles_page
    stub_dialogs(page)
    pid = new_profile(page, "Kit")
    page.apply_suggestions()
    assert page.save()
    w.show_page(PAGE_CONVERT)
    w.profile_combo.setCurrentIndex(w.profile_combo.findData(pid))
    assert w.direction_btn.text() == "⇄" and w.direction_btn.toolTip() == "Swap source and target"
    assert w.direction_btn.property("dir") == FORWARD
    assert w.profile_summary.text() == "EZdrummer 3 → Superior Drummer 3"
    w.direction_btn.click()
    assert w.direction == REVERSE and w.direction_btn.text() == "⇄" and w.direction_btn.property("dir") == REVERSE
    assert w.profile_summary.text() == "Superior Drummer 3 → EZdrummer 3"
    assert w.settings.value(DIRECTION_KEY) == REVERSE
    src = tmp_path / "groove.mid"
    shutil.copy(SAMPLE, src)
    w.load(src)
    w.convert()
    assert w.status.text() == "Converted: groove_remapped.mid"
    assert w.details_dialog(src.resolve()).view.toPlainText().startswith("Profile: Kit (reverse)")
    assert w.drop.single_result.text().startswith("✓ ")  # итог — под именем файла, полный — в Details
    w.close()
    w2 = MainWindow(storage)  # направление — между запусками
    assert w2.direction == REVERSE and w2.direction_btn.property("dir") == REVERSE
    w2.direction_btn.click()
    w2.close()
    assert MainWindow(storage).direction_btn.property("dir") == FORWARD


# --- обратное направление в редакторе ---

def reverse_page(window, accept=True):
    """EZD3 → SD3 (подсказки применены, если accept), вид — в ←."""
    from midiremap.core.profile import REVERSE
    page, ed = cables_page(window, accept=accept)
    page.set_direction(REVERSE)
    QApplication.processEvents()
    return page, ed


def send_mouse(view, kind, scene_pt, button=Qt.MouseButton.LeftButton):
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QMouseEvent
    vp = view.viewport()
    pos = QPointF(view.mapFromScene(scene_pt))
    buttons = Qt.MouseButton.NoButton if kind == QEvent.Type.MouseButtonRelease else button
    QApplication.sendEvent(vp, QMouseEvent(kind, pos, QPointF(vp.mapToGlobal(pos.toPoint())), button, buttons,
                                           Qt.KeyboardModifier.NoModifier))


def double_click(app, view, scene_pt):
    from PySide6.QtCore import QEvent
    for kind in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease, QEvent.Type.MouseButtonDblClick,
                 QEvent.Type.MouseButtonRelease):
        send_mouse(view, kind, scene_pt)
    app.processEvents()


def secondary_cable(ed):
    """Неосновной кабель: раскрыть подключённую строку алиасов (её ноты идут на одну ноту цели)."""
    row = next(r for r in ed.current.scene.source_rows if r.connected and r.alias and len(r.notes) > 1)
    ed.toggle_alias(row.alias, in_pool=False)
    return next(c for c in ed.cable_items if not c.cable.primary)


def test_reverse_uses_forward_layout(window, app):
    """← — тот же код рисования, что →, по профилю oriented(REVERSE): слева пул и подключённые ноты цели,
    справа артикуляции исходной карты; поток слева направо."""
    from midiremap.core.profile import REVERSE, missing_rules
    from midiremap.ui.cable_view import _Bundle

    def geometry(ed):
        lx, rx, col2, col3 = ed._scene_columns(ed.view.width_px(cable_view.SCENE_MIN))
        assert all(i.rect.right() <= lx + col2 + 0.5 for i in ed.scene_rows)  # «from» — слева
        assert all(i.rect.left() == rx and i.rect.width() == col3 for i in ed.target_items.values())
        assert {i.port for i in ed.scene_rows if i.port} == {"right"}
        assert {i.port for i in ed.target_items.values() if i.port} == {"left"}
        bundles = [i for i in ed.view.scene().items() if isinstance(i, _Bundle)]
        assert bundles and all(b.rect.right() <= lx + col2 + 4 for b in bundles)  # рамка связки — у «from»
        c = ed.cable_items[0]
        assert c.path().pointAtPercent(0).x() == c.src.rect.right() and c.path().pointAtPercent(1).x() == rx
        a = ed.source_anchor(ed.pool_rows[0].notes[0])
        assert a is not None and a.x() < ed.view.viewport().mapTo(ed, QPoint(0, 0)).x()  # пул — левее сцены
        return c

    page, ed = cables_page(window)
    w = page.work
    c = geometry(ed)
    assert c.pen().color().name().upper() == cable_view.TOKENS["accent"].upper()
    assert ed.from_head.indexOf(page.from_btn) >= 0 and page.from_btn.text() == w.source_map.name
    assert page.to_btn.text() == w.target_map.name and page.source_btn is page.from_btn

    page.set_direction(REVERSE)
    assert ed.direction == REVERSE and ed.shown.to_dict() == w.reversed().to_dict()
    # пул — ноты цели без обратного правила
    pool_notes = {n for r in ed.current.pool.rows for n in r.notes}
    assert pool_notes == set(missing_rules(w, REVERSE)) and pool_notes <= set(w.target_map.names)
    assert ed.pool_rows[0].scene() is ed.pool.scene()
    # слева — подключённые ноты цели, справа — артикуляции исходной карты
    ezd = {"a:" + normalize_name(v) for v in w.source_map.names.values()}
    assert set(ed.target_items) <= ezd
    assert {n for i in ed.scene_rows for n in i.notes} <= set(w.target_map.names)
    c = geometry(ed)
    assert c.pen().color().name().upper() == cable_view.TOKENS["reverse"].upper()
    assert "  →  " in c.toolTip()  # подсказка — как на картинке, слева направо
    # кнопки на местах, но выбирают другую карту: над «from» — цель, над «to» — источник
    assert page.from_btn.text() == w.target_map.name and page.to_btn.text() == w.source_map.name
    assert page.target_btn is page.from_btn and page.source_btn is page.to_btn
    assert "Target map" in page.from_btn.toolTip() and "Source map" in page.to_btn.toolTip()
    assert page._side_of(page.from_btn) == "target"


def test_suggestion_bar_over_to_column_yields_to_map_button(window, app):
    from midiremap.ui.profiles_page import MAP_BTN_MIN
    page = window.profiles_page
    wide = (2400, 900)  # offscreen без системных шрифтов текст шире обычного — с запасом
    window.resize(*wide)
    window.show()
    new_profile(page)  # обе карты — подсказки и панель
    app.processEvents()
    ed = page.cables
    assert page.suggest_bar.isVisibleTo(page) and ed.to_head.indexOf(page.suggest_bar) >= 0
    assert page.suggest_label.isVisibleTo(page) and page.suggest_label.text().endswith("matches")
    window.resize(900, 700)  # узкая колонка «to»: остаются Apply и ✕, кнопка карты не сжимается в ноль
    app.processEvents()
    assert not page.suggest_label.isVisibleTo(page) and page.apply_btn.isVisibleTo(page)
    assert page.to_btn.width() >= MAP_BTN_MIN and "matches" in page.suggest_bar.toolTip()
    window.resize(*wide)
    app.processEvents()
    assert page.suggest_label.isVisibleTo(page)


def test_empty_from_column_shows_hint(window, app):
    from midiremap.core.profile import FORWARD, REVERSE
    page, ed = cables_page(window, accept=False)
    lx, _rx, col2, _col3 = ed._scene_columns(ed.view.width_px(cable_view.SCENE_MIN))
    assert ed.current.scene.source_rows == []
    assert ed.view.hint == (lx, col2, "Drag notes from Unassigned onto the target map")
    page.set_direction(REVERSE)
    assert ed.view.hint is None  # пунктирные подсказки — тоже строки в «from»
    page.dismiss_suggestions()
    assert ed.view.hint[2] == "Drag notes from Unassigned onto the source map"
    page.set_direction(FORWARD)
    key, notes = three_note_articulation(page.work)
    assert page.connect_to(notes[:1], "a:" + key)
    assert ed.view.hint is None  # первый кабель — подсказка исчезает
    assert page.undo()
    ed.refresh()  # строка без кабеля вернулась в пул — колонка снова пуста
    assert ed.view.hint is not None
    new_profile(page, "Bare", None, None)  # нечего тащить — подсказки нет
    assert ed.view.hint is None


def test_direction_button_flips_and_is_not_an_undo_step(window, app):
    from midiremap.core.profile import FORWARD, REVERSE
    page = window.profiles_page
    btn = page.direction_btn
    assert not btn.isEnabled() and btn.toolTip() == ""  # профиля нет
    new_profile(page, "Bare", None, None)
    assert btn.toolTip() == "Swap source and target"
    page, ed = cables_page(window)
    assert btn.isEnabled() and btn.text() == "⇄" and btn.property("dir") == FORWARD
    steps = len(page._undo)
    btn.click()
    assert page.direction == REVERSE and ed.direction == REVERSE and len(page._undo) == steps and not page.redo()
    assert btn.text() == "⇄" and btn.property("dir") == REVERSE  # направление видно цветом ←
    assert btn.toolTip() == "Swap source and target"
    page.toggle_strike([ed.pool_rows[0].notes[0]])  # правка в ←
    btn.click()
    assert page.direction == FORWARD and btn.property("dir") == FORWARD
    btn.click()
    # открытие профиля — снова в →
    page.answers["unassigned"] = set()
    assert page.save() and page.direction == REVERSE
    page.select(LEGACY_ID)
    assert page.direction == FORWARD and btn.property("dir") == FORWARD and ed.direction == FORWARD


def test_reverse_assign_write_to_goes_to_source_copy(window, app, storage):
    from midiremap.core.profile import REVERSE
    page, ed = reverse_page(window, accept=False)
    rp = page.work.reversed()
    key, notes = three_note_articulation(rp)  # артикуляция EZD3, все номера которой есть в SD3
    (other,) = notes_off(rp, notes, 1)
    sd3_primary = set(page.work.target_map.primary)
    page.answers["write_to"] = [notes[2]]
    assert page.connect_to([other, notes[0], notes[1]], "a:" + key)
    assert [x[0] for x in page.answers["asked"]] == ["write_to"] and page.answers["preselect"] == notes[0]
    assert page.work.reverse_rules == {notes[0]: Rule.map_to(notes[0]), notes[1]: Rule.map_to(notes[1]),
                                       other: Rule.map_to(notes[2])}
    assert page.work.rules == {}  # прямые не тронуты
    assert page.work.source_map.primary & set(notes) == {notes[2]}  # Write to — в копии ИСХОДНОЙ карты
    assert page.work.target_map.primary == sd3_primary
    assert not load_map_template("EZdrummer 3").primary  # шаблон не меняется
    # «+N» на строке источника (в ← — строка цели вида): Write to переводит обратные правила
    item = ed.target_items["a:" + key]
    assert item.badge and item.port == "left"  # как в →: точка строки цели — со стороны кабелей
    assert page.set_write_to(notes[1])
    assert page.work.reverse_rules[other] == Rule.map_to(notes[1])
    assert page.work.source_map.primary & set(notes) == {notes[1]}
    # перетаскивание из пула — тот же путь, что в →; превью — цветом ←
    single = next(n for n in sorted(page.work.target_map.names)
                  if n not in page.work.effective_reverse() and n in ed.pool_items)
    slot, dst = single_note_articulation(page.work.source_map)
    show_target_group(ed, "a:" + slot)
    ed.begin_drag({single}, target_point(ed, "a:" + slot))
    assert ed.overlay.tone == cable_view.TONES[REVERSE] and ed.overlay.preview
    ed.end_drag(drop=True)
    app.processEvents()
    assert page.work.effective_reverse()[single] == Rule.map_to(dst) and single not in page.work.rules


def test_reverse_right_click_strike_and_group_drop(window, app):
    from midiremap.ui.cable_layout import TARGET_PREFIX
    page, ed = reverse_page(window)
    w = page.work
    # правый клик по подключённой строке (нота цели) — обратное правило снято, строка приглушена
    row = next(i for i in ed.scene_rows if i.model.connected and len(i.notes) == 1)
    note = row.notes[0]
    ed.right_click(row)
    app.processEvents()
    assert note not in w.effective_reverse() and ed.current.source_row(note).block is not None  # сразу в пул
    assert w.reverse_rules is not None  # отличается от выведенных — ручное
    # правый клик по строке пула — зачеркнуть (delete) / вернуть
    pool = ed.pool_rows[0]
    n = pool.notes[0]
    ed.right_click(pool)
    assert w.effective_reverse()[n] == Rule.delete()
    ed.right_click(ed.pool_items[n])
    assert n not in w.effective_reverse()
    # drop на заголовок группы (группы исходной карты): n → n для совпавших номеров
    ed.refresh()
    header = next(h for h in ed.current.scene.target_headers if h.notes)
    free = [m for m in header.notes if m in w.target_map.names and m not in w.effective_reverse()]
    assert free
    assert page.group_drop(free, list(header.notes)) == len(free)
    assert all(w.effective_reverse()[m] == Rule.map_to(m) for m in free)
    assert header.key.startswith(TARGET_PREFIX)


def test_reverse_suggestions_bar(window, app):
    from midiremap.core.profile import FORWARD, REVERSE
    page = window.profiles_page
    new_profile(page)
    fwd = dict(page._suggest[FORWARD])
    assert fwd and page._suggest[REVERSE]
    page.set_direction(REVERSE)
    assert page.cables.suggested == page._suggest[REVERSE] and page.suggest_bar.isVisibleTo(page)
    total, ready = page.suggestion_counts()
    assert total == len(page._suggest[REVERSE]) and ready
    assert page.apply_suggestions() == ready
    rev = page.work.effective_reverse()
    assert ready == sum(1 for n in rev if rev[n].action == "map") and page.work.rules == {}
    # ✕ — только для этого направления
    page.dismiss_suggestions()
    assert page._suggest[REVERSE] == {} and page._suggest[FORWARD] == fwd
    page.set_direction(FORWARD)
    assert page.cables.suggested == fwd and page.suggest_bar.isVisibleTo(page)
    # снимок отмены хранит подсказки обоих направлений
    assert page.undo()  # Apply в ←
    assert page.direction == REVERSE and page._suggest[REVERSE] and page.work.reverse_rules is None


def test_double_click_forward_makes_cable_primary(window, app):
    from midiremap.core.profile import FORWARD, primary_pairs
    from midiremap.ui.cable_view import PRIMARY_HINT
    page, ed = cables_page(window)
    item = secondary_cable(ed)
    primary = next(c for c in ed.cable_items if c.cable.primary)
    assert PRIMARY_HINT in item.toolTip() and PRIMARY_HINT not in primary.toolTip()
    a, b = item.ends
    old = page.work.effective_reverse()[b]
    sel = set(ed.selection)
    point = item.path().pointAtPercent(0.5)
    double_click(app, ed.view, point)
    assert not ed.dragging and ed.selection == sel  # первое нажатие ничего не делает
    assert (a, b) in primary_pairs(page.work) and page.work.effective_reverse()[b] == Rule.map_to(a)
    assert page.status.text() == f"Reverse: {b} → {a} (was {b} → {old.dst})"
    assert any(c.cable.primary and c.ends == (a, b) for c in ed.cable_items)
    # уже основной — ничего (не шаг отмены)
    steps = len(page._undo)
    assert not page.make_primary(a, b) and len(page._undo) == steps
    assert page.undo() and page.work.effective_reverse()[b] == old and page.direction == FORWARD


def test_double_click_reverse_sets_forward_rule(window, app):
    from midiremap.core.profile import REVERSE, primary_pairs
    page, ed = reverse_page(window)
    item = secondary_cable(ed)
    b, a = item.ends  # в ←: нота цели b ведёт назад на исходную a
    old = page.work.rules[a]
    assert old != Rule.map_to(b)
    double_click(app, ed.view, item.path().pointAtPercent(0.5))
    w = page.work
    assert w.rules[a] == Rule.map_to(b) and (a, b) in primary_pairs(w)
    assert page.status.text() == f"Forward: {a} → {b} (was {a} → {old.dst})"
    assert any(c.cable.primary and c.ends == (b, a) for c in ed.cable_items)
    # было без правила — «was unassigned»
    assert page.undo()
    p = page.work
    p.rules.pop(a)
    p.reverse_rules = {b: Rule.map_to(a)}
    page._changed()
    assert page.make_primary(b, a)
    assert page.status.text() == f"Forward: {a} → {b} (was unassigned)" and (a, b) in primary_pairs(page.work)
    assert page.direction == REVERSE


def _scene_cables(ed):
    return {c.ends for c in ed.cable_items}


def test_double_click_forward_keeps_every_other_cable(window, app):
    # → : у каждой ноты цели с несколькими кабелями — двойной клик по неосновному; прочие кабели на месте
    page, ed = cables_page(window)
    item = secondary_cable(ed)
    before, rules = _scene_cables(ed), dict(page.work.rules)
    double_click(app, ed.view, item.path().pointAtPercent(0.5))
    assert any(c.cable.primary and c.ends == item.ends for c in ed.cable_items)
    assert _scene_cables(ed) == before and page.work.rules == rules


def test_double_click_reverse_keeps_every_other_cable(window, app):
    from midiremap.core.profile import REVERSE
    page, ed = cables_page(window, accept=False)
    page.assign_note([38], 38)              # → 38 «Snare: Center» -> 38; в ← выведено 38 -> 38 (основной)
    page.set_direction(REVERSE)
    page.assign_note([40], 38)               # ← 40 «Snare: Rimshot» -> 38 (неосновной)
    QApplication.processEvents()
    item = next(c for c in ed.cable_items if c.ends == (40, 38))
    assert not item.cable.primary
    before = _scene_cables(ed)
    double_click(app, ed.view, item.path().pointAtPercent(0.5))
    assert page.work.rules[38] == Rule.map_to(40)  # основной сменился
    assert _scene_cables(ed) == before  # кабель ← 38 -> 38 остаётся (неосновным)
    assert any(c.cable.primary and c.ends == (40, 38) for c in ed.cable_items)
    assert not any(c.cable.primary and c.ends == (38, 38) for c in ed.cable_items)


def test_reverse_double_click_undo_restores_exactly(window, app):
    from midiremap.core.profile import REVERSE
    page, ed = cables_page(window, accept=False)
    page.assign_note([38], 38)
    page.set_direction(REVERSE)
    page.assign_note([40], 38)
    QApplication.processEvents()
    snapshot, cables = page.work.to_dict(), _scene_cables(ed)
    item = next(c for c in ed.cable_items if c.ends == (40, 38))
    double_click(app, ed.view, item.path().pointAtPercent(0.5))
    assert page.work.to_dict() != snapshot
    assert page.undo()
    assert page.work.to_dict() == snapshot and _scene_cables(ed) == cables  # в точности как было
    assert page.redo() and page.work.rules[38] == Rule.map_to(40)


def test_undo_redo_switch_to_direction_of_the_step(window, app):
    from midiremap.core.profile import FORWARD, REVERSE
    page, ed = reverse_page(window)
    note = ed.pool_rows[0].notes[0]
    page.toggle_strike([note])  # шаг в ←
    assert page.work.effective_reverse()[note] == Rule.delete()
    page.set_direction(FORWARD)
    src = min(page.work.rules)
    page.clear_rules([src])  # шаг в →
    page.set_direction(REVERSE)
    assert page.undo() and page.direction == FORWARD and ed.direction == FORWARD and src in page.work.rules
    assert page.undo() and page.direction == REVERSE and ed.direction == REVERSE
    assert note not in page.work.effective_reverse()
    assert page.direction_btn.property("dir") == REVERSE
    page.set_direction(FORWARD)
    assert page.redo() and page.direction == REVERSE and page.work.effective_reverse()[note] == Rule.delete()
    assert page.redo() and page.direction == FORWARD and src not in page.work.rules


def test_reverse_edits_normalize_to_none(window, app):
    page, ed = reverse_page(window)
    w = page.work
    assert w.reverse_rules is None
    row = next(i for i in ed.scene_rows if i.model.connected and len(i.notes) == 1)
    note, dst = row.notes[0], w.effective_reverse()[row.notes[0]].dst
    page.clear_rules([note])
    assert w.reverse_rules is not None and note not in w.reverse_rules
    page.assign_note([note], dst)  # вернули то же — снова равно выведенным
    assert w.reverse_rules is None


def test_save_dialog_forward_only_in_reverse(window, app, storage):
    page, ed = reverse_page(window)
    forward_missing = [n for n in sorted(page.work.source_map.names) if n not in page.work.rules]
    assert ed.current.pool.rows  # в ← есть ноты цели без обратного правила — о них не спрашивают
    page.answers["unassigned"] = set()
    assert page.save()
    assert page.answers["asked"] == [("unassigned", forward_missing)]
    saved = storage.load_profile(page.current)
    rev = saved.effective_reverse()
    assert any(n not in rev for n in saved.target_map.names)  # остались без правила


def test_direction_switch_keeps_group_and_own_collapse_state(window, app):
    from midiremap.core.profile import FORWARD, REVERSE
    from midiremap.ui.cable_layout import TARGET_PREFIX
    page, ed = cables_page(window, size=(1300, 600))
    hat = ed.current.header(TARGET_PREFIX + "hi-hat")
    ed.view.verticalScrollBar().setValue(hat.y * cable_view.ROW)
    assert ed._top_group() == TARGET_PREFIX + "hi-hat"
    page.set_direction(REVERSE)
    assert ed._top_group() == TARGET_PREFIX + "hi-hat"
    assert ed.view.verticalScrollBar().value() == ed.current.header(TARGET_PREFIX + "hi-hat").y * cable_view.ROW
    # свёрнутость — своя у направления (ключи групп двух карт могут совпасть)
    key = ed.current.pool.headers[0].key
    ed.toggle_pool(key)
    assert key in ed.collapsed and ed.current.header(key).collapsed
    page.set_direction(FORWARD)
    assert key not in ed.collapsed
    page.set_direction(REVERSE)
    assert key in ed.collapsed


# --- основной кабель и вид: основной первым, двойной клик по Unassigned, заголовок, комбобоксы ---

def shared_numbers(p, k):
    """k номеров, которые есть в обеих картах и принадлежат разным артикуляциям цели (и источника)."""
    out, seen_t, seen_s = [], set(), set()
    for n in sorted(set(p.source_map.names) & set(p.target_map.names)):
        t, s = normalize_name(p.target_map.names[n]), normalize_name(p.source_map.names[n])
        if t in seen_t or s in seen_s:
            continue
        seen_t.add(t)
        seen_s.add(s)
        out.append(n)
    return out[:k]


def bare_page(window, rules=None, reverse=None):
    """EZD3 → SD3 с заданными правилами (подсказки скрыты)."""
    page, ed = cables_page(window, accept=False)
    page.work.rules = dict(rules or {})
    page.work.reverse_rules = reverse
    page._changed()
    ed.refresh()
    return page, ed


def dbl_pool_row(app, ed, note):
    item = ed.pool_items[note]
    double_click(app, ed.pool, item.rect.center())


def test_primary_row_moves_first_after_double_click(window, app):
    from midiremap.core.profile import REVERSE
    for direction in ("forward", REVERSE):
        page, ed = cables_page(window) if direction == "forward" else reverse_page(window)
        item = secondary_cable(ed)
        src, dst = item.ends
        slot = item.cable.target.slot
        assert ed.current.placement.slots[slot][0] != src
        double_click(app, ed.view, item.path().pointAtPercent(0.5))
        assert ed.current.placement.slots[slot][0] == src  # связка пересортирована сразу
        row = ed.current.target_row(slot)
        assert row.lines[0][1] == dst  # номер основного кабеля — верхний (у раскрытых алиасов — под заголовком)
        first = min((c for c in ed.cable_items if c.cable.target.slot == slot), key=lambda c: c.cable.src_y)
        assert first.cable.primary and first.ends == (src, dst)
        page.answers["save_changes"] = "discard"
        page.select(LEGACY_ID)


def test_kick_bundle_primary_first_in_reverse(window, app):
    page, ed = reverse_page(window)
    ezd = page.work.source_map
    slot = "a:" + normalize_name(ezd.names[35])
    assert page.connect_to([34, 36], slot)  # SD3 Kick: Open -> EZD3 Kick: Hit (номера совпали: 34 -> 34, 36 -> 36)
    ed.refresh()
    assert ed.current.placement.slots[slot][0] == 35
    rows = [i for i in ed.scene_rows if set(i.notes) <= {34, 35, 36}]
    assert rows[0].notes == (35,) and rows[0].port == "right"
    assert ed.current.target_row(slot).lines[0] == (0, 35)


def test_double_click_unassigned_free_number_is_primary(window, app):
    from midiremap.core.profile import primary_pairs
    from midiremap.ui.cable_view import SAME_NUMBER_HINT
    page, ed = bare_page(window)
    (t,) = shared_numbers(page.work, 1)
    item = ed.pool_items[t]
    assert SAME_NUMBER_HINT in item.toolTip()
    steps = len(page._undo)
    dbl_pool_row(app, ed, t)
    assert not ed.dragging
    assert page.work.rules == {t: Rule.map_to(t)} and (t, t) in primary_pairs(page.work)
    assert len(page._undo) == steps + 1
    assert t in ed.source_items and t not in ed.pool_items  # строка ушла из пула напротив цели
    assert page.status.text() == "1 note connected to the same number"
    assert page.undo() and page.work.rules == {}


def test_double_click_unassigned_occupied_number_stays_secondary_forward(window, app):
    from midiremap.core.profile import primary_pairs
    page, ed = bare_page(window)
    t, u = shared_numbers(page.work, 2)
    page.work.rules = {u: Rule.map_to(t)}  # на номер t уже идёт кабель от u — он основной
    page._changed()
    ed.refresh()
    assert primary_pairs(page.work) == {(u, t)}
    dbl_pool_row(app, ed, t)
    w = page.work
    assert w.rules == {u: Rule.map_to(t), t: Rule.map_to(t)}
    assert primary_pairs(w) == {(u, t)} and w.effective_reverse()[t] == Rule.map_to(u)
    assert w.reverse_rules is not None  # зафиксировано явно: выведение выбрало бы t -> t
    thick = {c.ends: c.cable.primary for c in ed.cable_items if c.cable.dst == t}
    assert thick == {(u, t): True, (t, t): False}


def test_double_click_unassigned_occupied_number_stays_secondary_reverse(window, app):
    from midiremap.core.profile import REVERSE, primary_pairs
    page, ed = bare_page(window)
    t, u = shared_numbers(page.work, 2)
    page.work.rules = {t: Rule.map_to(u)}  # прямое t -> u; обратно u -> t — основной кабель на исходную t
    page._changed()
    page.set_direction(REVERSE)
    assert t in ed.pool_items  # нота цели t без обратного правила
    dbl_pool_row(app, ed, t)
    w = page.work
    assert w.rules == {t: Rule.map_to(u)}  # прямые не тронуты
    assert w.effective_reverse()[t] == Rule.map_to(t) and w.effective_reverse()[u] == Rule.map_to(t)
    assert primary_pairs(w) == {(t, u)}  # основной по-прежнему u -> t, новый t -> t — неосновной
    thick = {c.ends: c.cable.primary for c in ed.cable_items if c.cable.dst == t}
    assert thick == {(u, t): True, (t, t): False}


def test_double_click_unassigned_missing_number_and_partial_alias_row(window, app):
    from midiremap.core.profile import REVERSE
    gm = MapRef(TEMPLATE, "General MIDI")  # GM — только 35–81: у EZD3 есть ноты без пары
    page = window.profiles_page
    new_profile(page, "EZD3 to GM", EZD3, gm)
    page.dismiss_suggestions()
    ed = page.cables
    w = page.work
    missing = next(n for n in sorted(ed.pool_items) if n not in w.target_map.names
                   and len(ed.pool_items[n].notes) == 1)
    dbl_pool_row(app, ed, missing)
    assert w.rules == {} and page.status.text() == f"No note {missing} in the target map"
    # строка «+N»: ноты с номером в цели подключаются, остальные остаются в пуле
    row = next(i for i in ed.pool_rows if len(i.notes) > 1 and not i.model.expanded
               and 0 < sum(n in w.target_map.names for n in i.notes) < len(i.notes))
    hit = [n for n in row.notes if n in w.target_map.names]
    miss = [n for n in row.notes if n not in w.target_map.names]
    double_click(app, ed.pool, row.rect.center())
    assert set(page.work.rules) == set(hit) and all(page.work.rules[n] == Rule.map_to(n) for n in hit)
    assert all(n in ed.pool_items for n in miss)
    assert page.status.text().endswith(f"not in the target map: {', '.join(map(str, miss))}")
    # ←: «… in the source map» (GM → EZD3: в правом пуле — ноты EZD3, которых нет в GM)
    new_profile(page, "GM to EZD3", gm, EZD3)
    page.dismiss_suggestions()
    page.set_direction(REVERSE)
    gone = next(n for n in sorted(ed.pool_items) if n not in page.work.source_map.names
                and len(ed.pool_items[n].notes) == 1)
    dbl_pool_row(app, ed, gone)
    assert page.status.text() == f"No note {gone} in the source map" and gone not in page.work.effective_reverse()


def test_double_click_struck_row_does_nothing(window, app):
    from midiremap.ui.cable_view import SAME_NUMBER_HINT
    page, ed = bare_page(window)
    (t,) = shared_numbers(page.work, 1)
    page.toggle_strike([t])
    ed.refresh()
    assert ed.pool_items[t].strike and SAME_NUMBER_HINT not in ed.pool_items[t].toolTip()
    dbl_pool_row(app, ed, t)
    assert page.work.rules == {t: Rule.delete()}


def test_double_click_unassigned_scrolls_row_into_view(window, app):
    page, ed = bare_page(window)
    window.resize(1300, 600)
    app.processEvents()
    t = shared_numbers(page.work, 40)[-1]  # нота в конце списка — её цель внизу сцены
    calls = []
    reveal = ed.reveal
    ed.reveal = lambda note: calls.append(note) or reveal(note)
    bar = ed.view.verticalScrollBar()
    bar.setValue(0)
    dbl_pool_row(app, ed, t)
    assert calls == [t]
    visible = ed.view.mapToScene(ed.view.viewport().rect()).boundingRect()
    assert visible.contains(ed.source_items[t].rect)
    # уже видна — прокрутка не двигается
    before = bar.value()
    ed.reveal(t)
    assert bar.value() == before


def test_direction_button_centered_between_map_buttons(window, app):
    from midiremap.core.profile import REVERSE
    page, _ed = cables_page(window)
    for size in ((1300, 900), (1500, 900)):
        window.resize(*size)
        app.processEvents()
        btn, a, b = page.direction_btn, page.from_btn, page.to_btn
        right_of_a = a.mapTo(page, a.rect().topRight()).x()
        left_of_b = b.mapTo(page, b.rect().topLeft()).x()
        center = btn.mapTo(page, btn.rect().center()).x()
        assert right_of_a < btn.mapTo(page, btn.rect().topLeft()).x() and btn.mapTo(page, btn.rect().topRight()).x() < left_of_b
        assert abs(center - (right_of_a + left_of_b) / 2) <= 3  # по центру промежутка для кабелей
    page.set_direction(REVERSE)  # кнопки карт меняются местами по смыслу, направление — на месте
    assert page.from_btn.text() == page.work.target_map.name and page.direction_btn.property("dir") == REVERSE

def test_comboboxes_draw_own_arrow_and_style_popup(window, app):
    from midiremap.ui.combo import ComboBox
    page = window.profiles_page
    assert isinstance(page.combo, ComboBox) and isinstance(window.profile_combo, ComboBox)
    assert "QComboBox::drop-down" in window.styleSheet() and "border: none" in window.styleSheet()
    window.show()
    page.combo.showPopup()
    app.processEvents()
    assert "background" in page.combo.view().window().styleSheet()  # без белых полей у списка
    page.combo.hidePopup()


# --- drop ровно на ноту строки цели (номер / бейдж / остальное) ---

def line_point(ed, slot, note):
    """Точка номера note на строке цели slot (координаты CableEditor)."""
    item = ed.target_items[slot]
    off = next(o for o, n in item.model.numbers if n == note)
    ed.view.ensureVisible(item.number_rect(off))  # drop засчитывается только в видимой части сцены
    return editor_point(ed, ed.view, item.number_rect(off).center())


def badge_point(ed, slot):
    ed.view.ensureVisible(ed.target_items[slot].badge_rect())
    return editor_point(ed, ed.view, ed.target_items[slot].badge_rect().center())


def test_drop_zones_feedback_and_tooltip(window, app):
    from midiremap.ui.cable_view import NUMBER_DROP_HINT
    page, ed = cables_page(window, accept=False)
    key, notes = three_note_articulation(page.work)
    slot = "a:" + key
    assert page.connect_to(notes[:2], slot)
    item = ed.target_items[slot]
    assert NUMBER_DROP_HINT in item.toolTip()
    (x,) = notes_off(page.work, notes, 1)
    ed.begin_drag({x}, line_point(ed, slot, notes[1]))
    item = ed.target_items[slot]
    off = next(o for o, n in item.model.numbers if n == notes[1])
    assert item.drop_zone == ("line", off, notes[1]) and ed._drag.zone == item.drop_zone
    ed.drag_to(badge_point(ed, slot))
    assert item.drop_zone == ("badge",)
    ed.drag_to(target_point(ed, slot))
    assert item.drop_zone == ("row",)
    ed.cancel_drag()
    assert item.drop_zone is None


def test_drop_on_number_line_maps_exactly_forward(window, app):
    from midiremap.core.profile import primary_pairs
    page, ed = cables_page(window, accept=False)
    key, notes = three_note_articulation(page.work)
    slot = "a:" + key
    assert page.connect_to(notes[:2], slot)  # n -> n: на строке цели номера notes[0] и notes[1]
    primary = set(page.work.target_map.primary)
    pairs = primary_pairs(page.work)
    x, y = notes_off(page.work, notes, 2)
    steps = len(page._undo)
    drop(app, ed, [x], line_point(ed, slot, notes[1]))
    drop(app, ed, [y], line_point(ed, slot, notes[0]))
    w = page.work
    assert w.rules[x] == Rule.map_to(notes[1]) and w.rules[y] == Rule.map_to(notes[0])
    assert page.answers["asked"] == [] and w.target_map.primary == primary  # ни вопроса, ни Write to
    assert primary_pairs(w) == pairs  # основные — n -> n, новые кабели неосновные
    assert len(page._undo) == steps + 2
    # тот же ряд — на другой номер той же артикуляции: перенацелен, основной не тронут
    drop(app, ed, [x], line_point(ed, slot, notes[0]))
    assert w.rules[x] == Rule.map_to(notes[0]) and primary_pairs(w) == pairs
    assert page.undo() and page.work.rules[x] == Rule.map_to(notes[1])


def test_drop_alias_row_on_number_line_sends_all_notes(window, app):
    page, ed = cables_page(window, accept=False)
    row = pool_row(ed, lambda i: len(i.notes) > 1)
    key, _notes = three_note_articulation(page.work)
    slot = "a:" + key
    show_target_group(ed, slot)
    target = ed.target_items[slot].model.numbers[0][1]  # без кабелей — Write to или первая нота
    drop(app, ed, row.notes, line_point(ed, slot, target))
    assert all(page.work.rules[n] == Rule.map_to(target) for n in row.notes)
    assert page.answers["asked"] == []


def test_drop_on_badge_menu_pick_and_cancel(window, app):
    page, ed = cables_page(window, accept=False)
    key, notes = three_note_articulation(page.work)
    slot = "a:" + key
    show_target_group(ed, slot)
    (x,) = notes_off(page.work, notes, 1)
    primary = set(page.work.target_map.primary)
    shown = []
    ed.pick_destination = lambda t, at: shown.append(t.notes) or None  # Esc / клик мимо
    steps = len(page._undo)
    drop(app, ed, [x], badge_point(ed, slot))
    app.processEvents()
    assert shown == [tuple(notes)] and x not in page.work.rules and len(page._undo) == steps
    ed.pick_destination = lambda t, at: notes[2]
    drop(app, ed, [x], badge_point(ed, slot))
    app.processEvents()
    assert page.work.rules[x] == Rule.map_to(notes[2]) and page.work.target_map.primary == primary
    assert page.answers["asked"] == []
    # меню — то же оформление, что у Write to: все ноты, текущий Write to отмечен
    t = ed.current.target_row(slot)
    menu = ed.notes_menu("Connect to", t)
    actions = menu.actions()
    assert actions[0].text() == "Connect to" and [a.data() for a in actions[1:]] == list(notes)
    assert [a.isChecked() for a in actions[1:]] == [n == t.write_to for n in notes]


def test_zone3_row_drop_unchanged(window, app):
    page, ed = cables_page(window, accept=False)
    key, notes = three_note_articulation(page.work)
    slot = "a:" + key
    show_target_group(ed, slot)
    (x,) = notes_off(page.work, notes, 1)
    page.answers["write_to"] = [notes[1]]
    drop(app, ed, [x], target_point(ed, slot))  # имя / пустое место — логика назначения (assign_plan): вопрос о Write to
    assert [a[0] for a in page.answers["asked"]] == ["write_to"]
    assert page.work.rules[x] == Rule.map_to(notes[1]) and notes[1] in page.work.target_map.primary


def test_crash_bow_case_exact_notes_in_reverse(window, app):
    """← : EZD3 «Crash 1: Bow» на 84 и 87; SD3 84 и 87 подключены n -> n (номера 84 и 87 на строке).
    SD3 88 и 85 по логике назначения (assign_plan) легли бы оба на Write to (87); drop на номер — 88 -> 84, 85 -> 87."""
    page, ed = reverse_page(window, accept=False)
    ezd = page.work.source_map
    slot = "a:" + normalize_name(ezd.names[84])
    assert sorted(n for n in ezd.names if "a:" + normalize_name(ezd.names[n]) == slot) == [84, 87]
    show_target_group(ed, slot)
    assert page.connect_to([84, 87], slot) and page.answers["asked"] == []
    assert sorted(n for _, n in ed.current.target_row(slot).lines) == [84, 87]
    drop(app, ed, [88], line_point(ed, slot, 84))
    drop(app, ed, [85], line_point(ed, slot, 87))
    rev = page.work.effective_reverse()
    assert rev[88] == Rule.map_to(84) and rev[85] == Rule.map_to(87)
    assert page.work.rules == {} and page.answers["asked"] == []  # прямые не тронуты, вопросов нет
    assert not page.work.source_map.primary & {84, 87}  # Write to исходной карты не выбирался
    # для сравнения — зона 3 (строка): прежняя логика, обе ноты на Write to
    assert page.undo() and page.undo()
    page.answers["write_to"] = [87]
    drop(app, ed, [85, 88], target_point(ed, slot))
    rev = page.work.effective_reverse()
    assert rev[85] == rev[88] == Rule.map_to(87)


# --- drop ровно на ноту: номер Write to, первая строка, артикуляция из одной ноты (оба направления) ---

def oriented_page(window, direction):
    """EZD3 → SD3 без подсказок (скрыты в обоих направлениях); вид — в направлении direction."""
    if direction == "forward":
        return cables_page(window, accept=False)
    page, ed = reverse_page(window, accept=False)
    page.dismiss_suggestions()
    return page, ed


def drop_articulation(q):
    """Артикуляция цели вида на трёх+ нотах, все номера которых есть в карте источника вида, причём у первой и
    последней ноты в карте источника разные имена (строки напротив — не алиасы, номер на первой строке)."""
    src = q.source_map.names
    return next((k, v) for k, v in articulations(q.target_map).items()
                if len(v) > 2 and all(n in src for n in v) and normalize_name(src[v[0]]) != normalize_name(src[v[-1]]))


@pytest.mark.parametrize("direction", ["forward", "reverse"])
def test_drop_on_write_to_number_without_cables(window, app, direction):
    page, ed = oriented_page(window, direction)
    key, notes = drop_articulation(page._oriented())
    slot, wt = "a:" + key, notes[-1]
    show_target_group(ed, slot)
    assert page.set_write_to(wt)
    assert ed.current.target_row(slot).numbers == ((0, wt),)  # Write to — на первой строке, без кабелей
    x = notes[0]  # номер x есть среди нот артикуляции: логика назначения (assign_plan) дала бы x -> x
    ed.begin_drag({x}, line_point(ed, slot, wt))
    assert ed._drag.zone == ("line", 0, wt)
    ed.cancel_drag()
    steps = len(page._undo)
    drop(app, ed, [x], line_point(ed, slot, wt))
    q = page._oriented()
    assert q.rules[x] == Rule.map_to(wt) and q.target_map.primary & set(notes) == {wt}
    assert page.answers["asked"] == [] and len(page._undo) == steps + 1


@pytest.mark.parametrize("direction", ["forward", "reverse"])
def test_drop_on_write_to_number_with_cables_and_on_first_line(window, app, direction):
    page, ed = oriented_page(window, direction)
    key, notes = drop_articulation(page._oriented())
    slot, wt = "a:" + key, notes[-1]
    show_target_group(ed, slot)
    assert page.set_write_to(wt)
    assert page.connect_to([notes[0], wt], slot)  # n -> n: кабели на notes[0] и на Write to
    ed.refresh()
    lines = ed.current.target_row(slot).lines
    assert lines[0] == (0, notes[0]) and wt in [n for _, n in lines] and lines[-1][0] > 0
    (y,) = notes_off(page._oriented(), notes, 1)
    drop(app, ed, [y], line_point(ed, slot, wt))  # номер Write to, к нему уже идёт кабель
    assert page._oriented().rules[y] == Rule.map_to(wt)
    drop(app, ed, [y], line_point(ed, slot, notes[0]))  # номер на первой строке (рядом с именем)
    q = page._oriented()
    assert q.rules[y] == Rule.map_to(notes[0]) and q.target_map.primary & set(notes) == {wt}
    assert page.answers["asked"] == []


@pytest.mark.parametrize("direction", ["forward", "reverse"])
def test_drop_on_single_note_articulation_number(window, app, direction):
    page, ed = oriented_page(window, direction)
    q = page._oriented()
    key, n = single_note_articulation(q.target_map)
    slot = "a:" + key
    show_target_group(ed, slot)
    (x,) = notes_off(q, [n], 1)
    ed.begin_drag({x}, line_point(ed, slot, n))
    assert ed._drag.zone == ("line", 0, n) and ed.target_items[slot].badge_rect() is None
    ed.cancel_drag()
    drop(app, ed, [x], line_point(ed, slot, n))
    assert page._oriented().rules[x] == Rule.map_to(n) and page.answers["asked"] == []



# --- полировка: Match by number, статус, горячие клавиши, прокрутка ---

def test_match_by_number_button_one_undo_step(window, app):
    from midiremap.core.profile import REVERSE, number_matches, primary_pairs
    page, ed = bare_page(window)
    t, u = shared_numbers(page.work, 2)
    page.work.rules = {u: Rule.map_to(t)}  # номер t уже занят кабелем от u
    page.toggle_strike([shared_numbers(page.work, 3)[2]])  # зачёркнутая — не трогается
    struck = shared_numbers(page.work, 3)[2]
    expected = number_matches(page.work)
    assert t in expected and u not in expected and struck not in expected
    steps = len(page._undo)
    page.match_btn.click()
    w = page.work
    assert all(w.rules[n] == Rule.map_to(n) for n in expected) and w.rules[u] == Rule.map_to(t)
    assert w.rules[struck] == Rule.delete()
    assert (u, t) in primary_pairs(w)  # как двойной клик: занятый номер — новый кабель неосновной
    assert page.status.text() == f"Matched {len(expected)} notes by number"
    assert len(page._undo) == steps + 1 and all(n in ed.source_items for n in expected)
    page.match_btn.click()
    assert page.status.text() == "No notes match by number" and len(page._undo) == steps + 1
    assert page.undo() and all(n not in page.work.rules for n in expected)
    # ←: ноты цели без обратного правила — на тот же номер исходной карты
    page.set_direction(REVERSE)
    rev = number_matches(page.work.reversed())
    assert rev and page.match_by_number() == len(rev)
    assert all(page.work.effective_reverse()[n] == Rule.map_to(n) for n in rev)


def test_names_differ_tooltip_on_real_maps(window):
    page = window.profiles_page
    new_profile(page)  # EZD3 -> SD3
    page.dismiss_suggestions()
    assert page.match_by_number() == 122
    assert page.status.text() == "Matched 122 notes by number"  # без числа разных имён
    # подсказка кабеля — у любого кабеля с разными именами, в обоих направлениях
    from midiremap.core.profile import REVERSE, names_differ
    for direction in (None, REVERSE):
        if direction:
            page.set_direction(direction)
        shown, items = page.cables.shown, page.cables.cable_items
        differ = [c for c in items if names_differ(shown, *c.ends)]
        assert differ and len(differ) < len(items)
        for c in items:
            src, dst = shown.source_map.names[c.ends[0]], shown.target_map.names[c.ends[1]]
            assert c.toolTip().startswith(f"Names differ: {src} → {dst}\n") == (c in differ)


def test_status_fades_after_last_message(window, app):
    from midiremap.ui.profiles_page import STATUS_MS
    page = window.profiles_page
    page.set_status("One")
    assert page.status.text() == "One" and page._status_fx.opacity() == 1.0
    assert page._status_timer.isActive() and page._status_timer.interval() == STATUS_MS == 4000
    page._status_timer.stop()
    page._status_timer.timeout.emit()  # прошло ~4 с — гаснет
    page._status_fade.setCurrentTime(page._status_fade.duration())
    assert page._status_fx.opacity() == 0.0
    page.set_status("Two")  # новое сообщение — снова видно, отсчёт заново
    assert page._status_fx.opacity() == 1.0 and page._status_timer.isActive()


def test_undo_redo_hotkeys_work_with_focus_anywhere_on_profiles(window, app):
    from PySide6.QtGui import QKeySequence
    page, _ed = cables_page(window, accept=False)
    assert "Ctrl+Z" in page.revert_btn.toolTip() and "Ctrl+Y" in page.revert_btn.toolTip()
    assert "Ctrl+Shift+Z" in page.revert_btn.toolTip()
    n = sorted(page.work.source_map.names)[0]
    page.toggle_strike([n])
    window.activateWindow()
    page.combo.setFocus()  # фокус — не в сцене
    app.processEvents()
    QTest.keySequence(window, QKeySequence("Ctrl+Z"))
    assert n not in page.work.rules
    QTest.keySequence(window, QKeySequence("Ctrl+Shift+Z"))
    assert page.work.rules[n] == Rule.delete()
    QTest.keySequence(window, QKeySequence("Ctrl+Z"))
    QTest.keySequence(window, QKeySequence("Ctrl+Y"))
    assert page.work.rules[n] == Rule.delete()
    window.show_page(PAGE_CONVERT)  # на других вкладках — выключены
    assert not any(sc.isEnabled() for sc in page._shortcuts)
    window.show_page(PAGE_PROFILES)
    assert all(sc.isEnabled() for sc in page._shortcuts)


def test_scroll_stays_put_across_relayouts(window, app):
    page, ed = cables_page(window, size=(1300, 600))
    bar = ed.view.verticalScrollBar()
    bar.setValue(bar.maximum() // 2)
    app.processEvents()
    top = ed.view.mapToScene(QPoint(0, 0)).y()
    anchor = min((i for i in ed.target_items.values() if i.rect.top() >= top), key=lambda i: i.rect.top())
    slot, offset = anchor.model.slot, anchor.rect.top() - bar.value()
    # правка выше видимой части — строки над якорем меняют высоту, якорь остаётся на месте
    cable = min(ed.cable_items, key=lambda c: c.src.rect.top())
    page.clear_rules(list(cable.cable.notes))
    assert ed.target_items[slot].rect.top() - bar.value() == offset
    # пул: верхняя видимая строка остаётся на месте, когда строку над ней подключают
    pbar = ed.pool.verticalScrollBar()
    pbar.setValue(pbar.maximum() // 2)
    rows = sorted(ed.pool_rows, key=lambda i: i.rect.top())
    first = next(i for i in rows if i.rect.top() >= pbar.value())
    above = next(i for i in reversed(rows) if i.rect.top() < first.rect.top() and len(i.notes) == 1
                 and i.notes[0] in page.work.target_map.names)
    key, poff = first.notes[0], first.rect.top() - pbar.value()
    page.assign_note([above.notes[0]], above.notes[0])
    assert ed.pool_items[key].rect.top() - pbar.value() == poff
