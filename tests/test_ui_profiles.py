"""Смоук-тесты вкладки Profiles и связанных частей вкладки Convert (PySide6, offscreen, диалоги подменены)."""
import os
import shutil
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from midiremap.core.notemap import articulations, normalize_name  # noqa: E402
from midiremap.core.profile import Rule, legacy_profile  # noqa: E402
from midiremap.core.suggest import suggest_rules  # noqa: E402
from midiremap.storage import Storage, sanitize_id  # noqa: E402
from midiremap.templates import load_map_template  # noqa: E402
from midiremap.ui.main_window import PAGE_CONVERT, PAGE_PROFILES, MainWindow  # noqa: E402
from midiremap.ui.maps_page import REF_ROLE, SUBTITLE_ROLE, TEMPLATE, USER, MapRef  # noqa: E402
from midiremap.ui.profiles_page import COL_TARGET, DELETED_GROUP, Pick  # noqa: E402

SAMPLE = Path(__file__).resolve().parents[1] / "samples" / "midi" / "Groove 01.mid"
EZD3, SD3 = MapRef(TEMPLATE, "EZdrummer 3"), MapRef(TEMPLATE, "Superior Drummer 3")
LEGACY_ID = sanitize_id(legacy_profile().name)


@pytest.fixture(scope="module")
def app():
    app = QApplication.instance() or QApplication([])
    yield app
    app.clipboard().clear()


@pytest.fixture
def storage(tmp_path):
    return Storage(tmp_path / "store")


def stub_dialogs(page):
    page.answers = {"text": [], "confirm": True, "save_changes": "discard", "pick": None, "write_to": [],
                    "unassigned": set(), "number": None, "asked": []}
    a = page.answers
    page.ask_text = lambda *args: a["text"].pop(0) if a["text"] else None
    page.confirm = lambda *args: a["confirm"]
    page.ask_save_changes = lambda: a["asked"].append("save_changes") or a["save_changes"]
    page.show_error = lambda text: a.setdefault("errors", []).append(text)
    page.pick_target = lambda notes: a["pick"]
    page.ask_note_number = lambda notes: a["number"]

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
    assert window.profile_summary.text() == f"no maps · {len(legacy_profile().rules)} rules"
    combo.setCurrentIndex(combo.findData(pid))
    n = len(storage.load_profile(pid).rules)
    assert window.profile_summary.text() == f"EZdrummer 3 → Superior Drummer 3 · {n} rules"
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
    assert window.drop.name.text() == "groove.mid" and "Click or drop to replace" in window.drop.toolTip()
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
    pid = new_profile(page)
    w = page.work
    assert w.source_map.name == "EZdrummer 3" and w.target_map.name == "Superior Drummer 3"
    assert w.source_map.meta.source == load_map_template("EZdrummer 3").meta.source
    # по строке на каждую ноту исходной карты, под заголовками групп
    notes = [r.note for r in page.model.rows if not r.is_header]
    assert sorted(notes) == sorted(w.source_map.names)
    assert any(r.is_header for r in page.model.rows)
    n = next(iter(w.source_map.names))
    assert page.model.data(page.model.note_index(n, COL_TARGET)) == "kept as is"
    assert page.dirty and "●" in window.nav_profiles.text()


def test_accept_suggestions_counts(window):
    page = window.profiles_page
    new_profile(page)
    sugg = suggest_rules(load_map_template("EZdrummer 3"), load_map_template("Superior Drummer 3"))
    expected = (sum(s.kind in ("exact", "probable") for s in sugg),
                sum(s.kind == "ambiguous" for s in sugg), sum(s.kind == "none" for s in sugg))
    assert page.accept_suggestions() == expected
    assert page.status.text() == f"{expected[0]} mapped, {expected[1]} need a Write to choice, " \
                                 f"{expected[2]} without a match."
    assert len(page.work.rules) == expected[0]
    amb = next(s for s in sugg if s.kind == "ambiguous")
    assert page.model.status_text(amb.src) == "Needs a Write to choice"
    # повторно — ничего не перезаписывает
    custom = next(iter(page.work.rules))
    page.work.rules[custom] = Rule.delete()
    assert page.accept_suggestions()[0] == 0 and page.work.rules[custom] == Rule.delete()


def test_accept_disabled_without_maps(window):
    page = window.profiles_page
    page.select(LEGACY_ID)
    assert not page.accept_btn.isEnabled()
    # без исходной карты — строка на правило, без групп
    assert not any(r.is_header and r.group != DELETED_GROUP for r in page.model.rows)
    assert {r.note for r in page.model.rows if not r.is_header} == {
        n for n, r in legacy_profile().rules.items() if r != Rule.delete()}
    # без целевой карты цель — номер ноты
    n = next(n for n, r in page.work.rules.items() if r.action == "map")
    page.select_notes([n])
    page.answers["number"] = 99
    assert page.assign_selected() and page.work.rules[n] == Rule.map_to(99)
    assert page.model.data(page.model.note_index(n, COL_TARGET)) == "→ 99"


def test_multi_select_assign_many_to_one(window):
    page = window.profiles_page
    new_profile(page)
    key, dst = single_note_articulation(page.work.target_map)
    srcs = sorted(page.work.source_map.names)[:5]
    page.select_notes(srcs)
    assert page.selected_notes() == srcs
    page.answers["pick"] = Pick(articulation=key)
    assert page.assign_selected()
    assert all(page.work.rules[n] == Rule.map_to(dst) for n in srcs)
    assert page.answers["asked"] == []  # одна нота — ничего не спрашиваем


def test_write_to_asked_once_and_stored_in_profile_copy(window, storage):
    sd3 = load_map_template("Superior Drummer 3")
    storage.save_map(sd3)  # карта пользователя — её Write to не должен меняться
    page = window.profiles_page
    new_profile(page, target=MapRef(USER, sanitize_id(sd3.name)))
    key, notes = multi_note_articulation(page.work.target_map)
    a, b = notes_off(page.work, notes, 2)
    page.answers["pick"] = Pick(articulation=key)
    page.answers["write_to"] = [notes[1]]
    page.select_notes([a])
    assert page.assign_selected()
    assert page.work.rules[a] == Rule.map_to(notes[1])
    assert page.work.target_map.primary & set(notes) == {notes[1]}
    page.select_notes([b])
    assert page.assign_selected()  # второй раз не спрашивает
    assert page.work.rules[b] == Rule.map_to(notes[1])
    assert [x for x in page.answers["asked"] if x[0] == "write_to"] == [
        ("write_to", page.work.target_map.names[notes[0]], tuple(notes))]
    # отдельная нота артикуляции (не Write to) — допустимо
    page.answers["pick"] = Pick(note=notes[0])
    assert page.assign_selected() and page.work.rules[b] == Rule.map_to(notes[0])
    assert page.save()
    assert storage.load_map(sanitize_id(sd3.name))[0].primary == set()
    assert notes[1] in storage.load_profile(page.current).target_map.primary


def test_cancel_write_to_choice_keeps_rule(window):
    page = window.profiles_page
    new_profile(page)
    key, notes = multi_note_articulation(page.work.target_map)
    (n,) = notes_off(page.work, notes, 1)
    page.select_notes([n])
    page.answers["pick"] = Pick(articulation=key)
    assert not page.assign_selected()
    assert n not in page.work.rules and not page.work.target_map.primary


def test_delete_and_clear_rules(window):
    page = window.profiles_page
    new_profile(page)
    a, b = sorted(page.work.source_map.names)[:2]
    page.delete_notes([a, b])
    assert page.work.rules[a] == Rule.delete()
    deleted_header = next(r for r in page.model.rows if r.group == DELETED_GROUP)
    assert deleted_header.label.endswith("Deleted (2)")
    assert not page.model.has_row(a)  # секция свёрнута
    page.model.toggle_deleted()
    assert page.model.has_row(a) and page.model.row_at(page.model.note_index(a, 0).row()).group == DELETED_GROUP
    assert page.model.data(page.model.note_index(a, 0), Qt.ItemDataRole.ForegroundRole) is not None  # приглушено
    page.clear_rules([a])
    assert a not in page.work.rules
    assert page.model.row_at(page.model.note_index(a, 0).row()).group != DELETED_GROUP


def test_issues_highlighted_and_listed(window):
    page = window.profiles_page
    new_profile(page)
    n = sorted(page.work.source_map.names)[0]
    missing = next(x for x in range(128) if x not in page.work.target_map.names)
    page.select_notes([n])
    page.answers["number"] = None
    page.assign_note([n], missing)
    assert page.model.data(page.model.note_index(n, 0), Qt.ItemDataRole.BackgroundRole) is not None
    assert page.model.status_text(n).startswith("⚠")
    assert "not in the target map" in page.issues_label.text()
    assert "has no rule" not in page.issues_label.text()  # NO_RULE в панели не показываем


def test_change_map_with_rules_confirms_and_keeps_rules(window):
    page = window.profiles_page
    new_profile(page)
    page.accept_suggestions()
    rules = dict(page.work.rules)
    page.answers["confirm"] = False
    assert not page.choose_map("target", MapRef(TEMPLATE, "General MIDI"))
    assert page.work.target_map.name == "Superior Drummer 3"
    page.answers["confirm"] = True
    assert page.choose_map("target", MapRef(TEMPLATE, "General MIDI"))
    assert page.work.rules == rules and page.model.issues


def test_save_dialog_paths(window, storage):
    page = window.profiles_page
    pid = new_profile(page)
    page.accept_suggestions()
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


def test_ambiguous_suggestion_tooltip(window):
    page = window.profiles_page
    new_profile(page)
    amb = next(s for s in page.model.suggestions.values() if s.kind == "ambiguous")
    tip = page.model.data(page.model.note_index(amb.src, 0), Qt.ItemDataRole.ToolTipRole)
    assert normalize_name(amb.target_name) in normalize_name(tip)


def test_new_profile_without_maps_has_no_rows(window):
    page = window.profiles_page
    new_profile(page, "Empty", None, None)
    assert page.model.rows == [] and not page.accept_btn.isEnabled()


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

    def item(profile_id):
        return next(page.list.item(i) for i in range(page.list.count())
                    if page.list.item(i).data(REF_ROLE) == profile_id)
    assert item(pid).text() == "Mark"
    saved_subtitle = item(pid).data(SUBTITLE_ROLE)
    page.clear_rules([sorted(page.work.source_map.names)[0]])
    assert item(pid).text() == "• Mark" and item(LEGACY_ID).text() == legacy_profile().name
    assert item(pid).data(SUBTITLE_ROLE) == saved_subtitle  # подзаголовок — сохранённое состояние
    page.revert()
    assert item(pid).text() == "Mark"


def test_write_to_choice_shows_number_and_pitch(window, monkeypatch):
    from PySide6.QtWidgets import QDialog, QInputDialog
    from midiremap.core.pitch import pitch_name
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
    assert seen["items"] == [f"{n} · {pitch_name(n)}" for n in (11, 42, 61)]


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


# --- вид «кабелями» (8b2a) ---

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


def test_cables_view_toggle_keeps_edits(window):
    from midiremap.ui.cable_layout import DELETE
    from midiremap.ui.profiles_page import CABLES_VIEW, TABLE_VIEW
    page = window.profiles_page
    new_profile(page)
    page.accept_suggestions()
    rules = dict(page.work.rules)
    page.set_view(CABLES_VIEW)
    assert page.view == CABLES_VIEW and page.cables.active
    assert cabled_note_count(page.cables) == map_rule_count(page.work) > 0
    assert len(page.cables.cable_items) < map_rule_count(page.work)  # алиасы EZD3 — по кабелю на строку
    assert page.work.rules == rules and page.dirty
    # правка при показанных кабелях: строка без кабеля остаётся на месте до пересортировки
    n = unique_mapped_note(page.work)
    y = page.cables.current.source_row(n).y
    page.delete_notes([n])
    row = page.cables.current.source_row(n)
    assert row.y == y and row.block is None and not row.connected
    assert cabled_note_count(page.cables) == map_rule_count(page.work)
    page.set_view(TABLE_VIEW)
    assert page.work.rules[n] == Rule.delete() and page.dirty and not page.cables.active
    page.set_view(CABLES_VIEW)  # показ — пересортировка
    assert page.cables.current.source_row(n) is None  # блок Delete свёрнут по умолчанию
    assert page.cables.current.header(DELETE).count == 1


def test_cables_view_toolbar(window):
    from midiremap.ui.profiles_page import CABLES_VIEW, REFRESH_TIP, TABLE_VIEW
    page = window.profiles_page
    new_profile(page)
    assert page.refresh_btn.isHidden() and page.assign_btn.isEnabled()
    page.set_view(CABLES_VIEW)
    assert not page.refresh_btn.isHidden() and page.refresh_btn.toolTip() == REFRESH_TIP == "Refresh layout"
    assert page.refresh_btn.text() == "↻"
    assert page.assign_btn.isEnabled()  # Assign target — для выделенных строк «кабелей»
    assert page.cables_view_btn.isChecked() and not page.table_view_btn.isChecked()
    page.table_view_btn.click()
    assert page.view == TABLE_VIEW and page.assign_btn.isEnabled()


def test_cables_resort_button_reflows(window):
    from midiremap.ui.cable_layout import UNASSIGNED
    from midiremap.ui.profiles_page import CABLES_VIEW
    page = window.profiles_page
    new_profile(page)
    page.accept_suggestions()
    page.set_view(CABLES_VIEW)
    n = unique_mapped_note(page.work)
    page.clear_rules([n])
    assert page.cables.current.source_row(n).block is None
    page.refresh_btn.click()
    assert page.cables.current.source_row(n).block == UNASSIGNED


def test_cables_header_click_collapses(window, app):
    from PySide6.QtCore import QPointF
    from midiremap.ui.cable_layout import UNASSIGNED
    from midiremap.ui.cable_view import PAD, ROW
    from midiremap.ui.profiles_page import CABLES_VIEW
    page = window.profiles_page
    window.resize(1200, 800)
    window.show()
    new_profile(page)
    page.set_view(CABLES_VIEW)
    head = page.cables.current.header(UNASSIGNED)
    assert head.y == 0 and not head.collapsed
    pool = page.cables.pool
    pos = pool.mapFromScene(QPointF(PAD + 30, PAD + ROW / 2))
    QTest.mouseClick(pool.viewport(), Qt.MouseButton.LeftButton, pos=pos)
    app.processEvents()
    head = page.cables.current.header(UNASSIGNED)
    assert head.collapsed and head.count == len(page.work.source_map.names)
    assert page.cables.current.pool.rows == []


def test_cables_view_saves_with_same_dialog(window, storage):
    from midiremap.ui.cable_layout import DELETE
    from midiremap.ui.profiles_page import CABLES_VIEW
    page = window.profiles_page
    pid = new_profile(page)
    page.set_view(CABLES_VIEW)
    page.accept_suggestions()
    assert cabled_note_count(page.cables) == map_rule_count(page.work)
    page.answers["unassigned"] = set()
    assert page.save() and page.answers["asked"][-1][0] == "unassigned"
    saved = storage.load_profile(pid)
    assert page.cables.profile is page.work and page.work.to_dict() == saved.to_dict()
    assert page.cables.current.header(DELETE).count == sum(r == Rule.delete() for r in saved.rules.values())


def test_cables_pool_is_separate_column(window):
    from midiremap.ui.profiles_page import CABLES_VIEW
    page = window.profiles_page
    window.resize(1300, 900)
    window.show()
    new_profile(page)
    page.accept_suggestions()
    page.set_view(CABLES_VIEW)
    ed = page.cables
    lay = ed.current
    # пул — своя view со своей прокруткой; сцена начинается сверху
    assert ed.pool is not ed.view and ed.splitter.count() == 2
    assert set(ed.pool_items) == {n for r in lay.pool.rows for n in r.notes}
    assert min(t.y for t in lay.scene.target_rows + lay.scene.target_headers) == 0
    assert ed.view.verticalScrollBar() is not ed.pool.verticalScrollBar()
    ed.pool.verticalScrollBar().setValue(ed.pool.verticalScrollBar().maximum())
    assert ed.view.verticalScrollBar().value() == 0
    # слой для кабеля-превью (8b2b): поверх обоих, мышь не перехватывает
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
    from midiremap.ui.profiles_page import CABLES_VIEW
    page = window.profiles_page
    new_profile(page)
    page.accept_suggestions()
    page.set_view(CABLES_VIEW)
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


def test_removed_cable_row_dimmed_in_scene(window):
    from midiremap.ui.cable_view import STALE
    from midiremap.ui.profiles_page import CABLES_VIEW
    page = window.profiles_page
    new_profile(page)
    page.accept_suggestions()
    page.set_view(CABLES_VIEW)
    n = unique_mapped_note(page.work)
    pool_count = len(page.cables.pool_items)
    page.clear_rules([n])
    assert page.cables.source_items[n].opacity() == STALE and n not in page.cables.pool_items
    assert len(page.cables.pool_items) == pool_count  # в пул — только после пересортировки
    page.refresh_btn.click()
    assert n in page.cables.pool_items and n not in page.cables.source_items


# --- вид «кабелями»: правка (8b2b) ---

def cables_page(window, accept=True, size=(1300, 900)):
    from midiremap.ui.profiles_page import CABLES_VIEW
    page = window.profiles_page
    window.resize(*size)
    window.show()
    new_profile(page)
    if accept:
        page.accept_suggestions()
    page.set_view(CABLES_VIEW)
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
    tgt = ed.profile.target_map
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
    assert row.model.alias and row.count == len(row.notes)
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
    assert tgt.highlighted and ed.overlay.preview and ed.overlay.valid
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


def test_autoscroll_near_edge(window, app):
    from PySide6.QtCore import QPointF
    page, ed = cables_page(window, accept=False, size=(1200, 600))
    bar = ed.pool.verticalScrollBar()
    assert bar.maximum() > 0 and bar.value() == 0
    vp = ed.pool.viewport()
    bottom = QPointF(vp.mapTo(ed, vp.rect().bottomLeft()))
    at = QPointF(bottom.x() + 40, bottom.y() - 4)
    ed.begin_drag({ed.pool_rows[0].notes[0]}, at)
    ed._tick()
    ed._tick()
    assert bar.value() > 0
    assert ed.view.verticalScrollBar().value() == 0  # прокручивается только колонка под курсором
    ed.cancel_drag()


def test_right_click_cable_removes_connection(window, app):
    from midiremap.ui.cable_view import STALE
    page, ed = cables_page(window)
    cable = ed.cable_items[0]
    notes = cable.cable.notes
    pos = ed.view.mapFromScene(cable.path().pointAtPercent(0.5))
    QTest.mouseClick(ed.view.viewport(), Qt.MouseButton.RightButton, pos=pos)
    app.processEvents()
    assert all(n not in page.work.rules for n in notes) and page.dirty
    assert ed.source_items[notes[0]].opacity() == STALE  # остаётся в колонке 2 до пересортировки


def test_right_click_pool_row_and_group_toggle_strike(window, app):
    from midiremap.ui.cable_layout import KEEP, UNASSIGNED
    page, ed = cables_page(window, accept=False)
    row = ed.pool_rows[0]
    notes = row.notes
    QTest.mouseClick(ed.pool.viewport(), Qt.MouseButton.RightButton, pos=ed.pool.mapFromScene(row.rect.center()))
    assert all(page.work.rules[n] == Rule.delete() for n in notes)
    row = ed.pool_items[notes[0]]
    assert row.strike and row.model.block == UNASSIGNED  # в Delete — только после пересортировки
    QTest.mouseClick(ed.pool.viewport(), Qt.MouseButton.RightButton, pos=ed.pool.mapFromScene(row.rect.center()))
    assert all(n not in page.work.rules for n in notes)
    # группа: зачеркнуть всю; если уже вся зачёркнута — вернуть
    head = next(h for h in ed.current.pool.headers if h.level == 1)
    page.delete_notes([head.notes[0]])
    item = header_item(ed.pool, head.key)
    QTest.mouseClick(ed.pool.viewport(), Qt.MouseButton.RightButton, pos=ed.pool.mapFromScene(item.rect.center()))
    assert all(page.work.rules[n] == Rule.delete() for n in head.notes)
    ed.right_click(header_item(ed.pool, head.key))
    assert all(n not in page.work.rules for n in head.notes)
    # явный keep (старые профили) — в Unassigned с маркером «=»; правый клик — delete ↔ без правила
    for n in notes:
        page.work.rules[n] = Rule.keep()
    page.refresh_btn.click()
    keep_row = ed.pool_items[notes[0]]
    assert keep_row.model.block == UNASSIGNED and keep_row.marker == "="
    assert "Kept on the same number" in keep_row.toolTip()
    assert ed.current.header(KEEP) is None
    ed.right_click(keep_row)
    assert all(page.work.rules[n] == Rule.delete() for n in notes)
    ed.right_click(ed.pool_items[notes[0]])
    assert all(n not in page.work.rules for n in notes)


def test_write_to_badge_repoints_rules(window, app, storage):
    page, ed = cables_page(window)
    key, notes = multi_note_articulation(page.work.target_map)
    slot = "a:" + key
    srcs = [n for n in sorted(page.work.source_map.names) if n not in page.work.rules and n not in notes][:2]
    page.answers["write_to"] = [notes[0]]
    assert page.connect_to(srcs, slot)
    assert all(page.work.rules[n] == Rule.map_to(notes[0]) for n in srcs)
    item = ed.target_items[slot]
    assert item.badge and item.marker == f"+{len(notes) - 1}"
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
    assert heads and all(h.collapsed and not h.shown for h in heads)
    assert ed.current.scene.target_rows == []  # без связей — только заголовки
    head = heads[0]
    item = header_item(ed.view, head.key)
    QTest.mouseClick(ed.view.viewport(), Qt.MouseButton.LeftButton, pos=ed.view.mapFromScene(item.rect.center()))
    app.processEvents()
    assert head.key in ed.show_all and not ed.current.header(head.key).collapsed
    assert len(ed.current.scene.target_rows) == head.count
    # без режима «все» видны только подключённые артикуляции
    page.accept_suggestions()
    ed.show_all.clear()
    page.refresh_btn.click()
    lay = ed.current.scene
    assert any(h.shown for h in lay.target_headers)
    assert len(lay.target_rows) == sum(h.shown for h in lay.target_headers)


def test_spring_loaded_group_opens_while_dragging(window, app):
    page, ed = cables_page(window, accept=False)
    head = ed.current.scene.target_headers[0]
    item = header_item(ed.view, head.key)
    at = editor_point(ed, ed.view, item.rect.center())
    ed.begin_drag({ed.pool_rows[0].notes[0]}, at)
    ed.drag_to(at)
    assert ed._spring.isActive() and item.highlighted
    ed._spring_open()  # ~500 мс наведения
    assert head.key in ed.show_all and ed.dragging
    assert len(ed.current.scene.target_rows) == head.count
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
    from midiremap.ui.cable_layout import UNASSIGNED
    page, ed = cables_page(window)
    scene_items = list(ed.scene_rows)
    ed.toggle_pool(UNASSIGNED)
    assert ed.current.header(UNASSIGNED).collapsed and ed.scene_rows == scene_items


def test_assign_target_uses_cable_selection(window, app):
    page, ed = cables_page(window, accept=False)
    slot, dst = single_note_articulation(page.work.target_map)
    row = ed.pool_rows[0]
    ed.set_selection(set(row.notes))
    page.answers["pick"] = Pick(note=dst)
    assert page.assign_selected()
    assert all(page.work.rules[n] == Rule.map_to(dst) for n in row.notes)


# --- назначение по номерам, группа, номера цели, отмена (8b2c) ---

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
    assert item.marker == f"+{len(notes) - 2}"


def test_drop_single_match_becomes_write_to_silently(window, app):
    page, ed = cables_page(window, accept=False)
    key, notes = three_note_articulation(page.work)
    (other,) = notes_off(page.work, notes, 1)
    assert page.connect_to([other, notes[1]], "a:" + key)
    assert page.work.rules == {other: Rule.map_to(notes[1]), notes[1]: Rule.map_to(notes[1])}
    assert page.work.target_map.primary & set(notes) == {notes[1]} and page.answers["asked"] == []
    item = ed.target_items["a:" + key]
    assert [(line[1], line[3]) for line in item.lines] == [(str(notes[1]), True)]  # Write to отмечен
    assert f"Write to: {notes[1]}" in item.toolTip()


def test_drop_several_matches_asks_once_with_preselect(window, app):
    page, ed = cables_page(window, accept=False)
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
    from midiremap.ui.cable_layout import TARGET_PREFIX, UNASSIGNED
    page, ed = cables_page(window, accept=False)
    head = ed.current.header(UNASSIGNED + "/snare")
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
    assert ed.profile is page.work and page.model.profile is page.work
    # новое действие сбрасывает повтор
    page.clear_rules(notes[:1])
    assert not page.redo()
    # горячие клавиши (в подсказках) — на странице
    assert "Ctrl+Z" in page.revert_btn.toolTip() and "Ctrl+Y" in page.cables_view_btn.toolTip()
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
