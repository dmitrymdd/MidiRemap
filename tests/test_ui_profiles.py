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
from midiremap.core.profile import Rule, keep_issue, legacy_profile  # noqa: E402
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

    def write_to(name, notes):
        a["asked"].append(("write_to", name, tuple(notes)))
        return a["write_to"].pop(0) if a["write_to"] else None
    page.ask_write_to = write_to

    def unassigned(total, warnings):
        a["asked"].append(("unassigned", total, list(warnings)))
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
    a, b = sorted(page.work.source_map.names)[:2]
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
    n = sorted(page.work.source_map.names)[0]
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
    unassigned = [n for n in sorted(w.source_map.names) if n not in w.rules]
    problems = [n for n in unassigned if keep_issue(w.source_map, w.target_map, n) is not None]
    assert problems

    before = storage.load_profile(pid).to_dict()
    page.answers["unassigned"] = None  # Cancel
    assert not page.save()
    assert storage.load_profile(pid).to_dict() == before and page.dirty
    assert page.answers["asked"][-1][:2] == ("unassigned", len(unassigned))
    assert sorted(x.note for x in page.answers["asked"][-1][2]) == problems

    checked = set(problems[:2])  # удаляются только отмеченные
    page.answers["unassigned"] = checked
    assert page.save()
    saved = storage.load_profile(pid)
    assert all(saved.rules[n] == Rule.delete() for n in checked)
    assert all(saved.rules[n] == Rule.keep() for n in unassigned if n not in checked)
    assert set(saved.source_map.names) <= set(saved.rules) and not page.dirty

    # всё назначено — диалога нет
    page.answers["asked"].clear()
    page.delete_notes([unassigned[0]])
    assert page.save() and page.answers["asked"] == []


def test_save_keep_all(window, storage):
    page = window.profiles_page
    pid = new_profile(page)
    page.answers["unassigned"] = set()
    assert page.save()
    saved = storage.load_profile(pid)
    assert saved.rules == {n: Rule.keep() for n in saved.source_map.names}


def test_unsaved_edits_prompts(window, storage):
    page = window.profiles_page
    pid = new_profile(page, "A")
    page.save()
    page.answers["asked"].clear()
    page.delete_notes([sorted(page.work.source_map.names)[0]])
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
    assert storage.load_profile(pid).rules[sorted(page.base.source_map.names)[0]] == Rule.keep()


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


def test_unassigned_dialog_checkboxes_and_markers(window):
    from midiremap.core.profile import DIFFERENT_INSTRUMENT, RemapProfile, unassigned_keep_warnings
    from midiremap.ui.profiles_page import UnassignedDialog
    for src_id in ("EZdrummer 3", "Guitar Pro 8"):
        p = RemapProfile("p", load_map_template(src_id), load_map_template("Superior Drummer 3"))
        warnings = unassigned_keep_warnings(p)
        dlg = UnassignedDialog(window, len(p.source_map.names), warnings, "Superior Drummer 3")
        t = dlg.table
        assert t.rowCount() == len(warnings)
        assert [t.item(r, 1).text() for r in range(t.rowCount())] == [w.marker for w in warnings]
        assert all(t.item(r, 1).toolTip() for r in range(t.rowCount()))
        assert t.item(0, 1).text() == DIFFERENT_INSTRUMENT  # «!» сверху
        # по умолчанию ничего не отмечено, «Delete checked» неактивна
        assert dlg.checked() == set() and not dlg.delete_btn.isEnabled()
        dlg.keep_all()
        assert dlg.to_delete == set()
        dlg.set_checked({warnings[0].note, warnings[-1].note})
        assert dlg.delete_btn.isEnabled()
        dlg.delete_checked()
        assert dlg.to_delete == {warnings[0].note, warnings[-1].note}
        dlg.deleteLater()


def test_save_without_checks_deletes_nothing(window, storage):
    page = window.profiles_page
    pid = new_profile(page, source=MapRef(TEMPLATE, "Guitar Pro 8"))
    page.answers["unassigned"] = set()
    assert page.save()
    saved = storage.load_profile(pid)
    assert not any(r == Rule.delete() for r in saved.rules.values())


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
    page.delete_notes([sorted(page.work.source_map.names)[0]])
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


def test_cables_view_toggle_keeps_edits(window):
    from midiremap.ui.cable_layout import DELETE
    from midiremap.ui.profiles_page import CABLES_VIEW, TABLE_VIEW
    page = window.profiles_page
    new_profile(page)
    page.accept_suggestions()
    rules = dict(page.work.rules)
    page.set_view(CABLES_VIEW)
    assert page.view == CABLES_VIEW and page.cables.active
    assert len(page.cables.cable_items) == map_rule_count(page.work) > 0
    assert page.work.rules == rules and page.dirty
    # правка при показанных кабелях: строка без кабеля остаётся на месте до пересортировки
    n = next(n for n, r in sorted(page.work.rules.items()) if r.action == "map")
    y = page.cables.current.source_row(n).y
    page.delete_notes([n])
    row = page.cables.current.source_row(n)
    assert row.y == y and row.block is None and not row.connected
    assert len(page.cables.cable_items) == map_rule_count(page.work)
    page.set_view(TABLE_VIEW)
    assert page.work.rules[n] == Rule.delete() and page.dirty and not page.cables.active
    page.set_view(CABLES_VIEW)  # показ — пересортировка
    assert page.cables.current.source_row(n) is None  # блок Delete свёрнут по умолчанию
    assert page.cables.current.header(DELETE).count == 1


def test_cables_view_toolbar(window):
    from midiremap.ui.profiles_page import CABLES_VIEW, RESORT_TIP, TABLE_VIEW
    page = window.profiles_page
    new_profile(page)
    assert page.resort_btn.isHidden() and page.assign_btn.isEnabled()
    page.set_view(CABLES_VIEW)
    assert not page.resort_btn.isHidden() and page.resort_btn.toolTip() == RESORT_TIP
    assert not page.assign_btn.isEnabled()
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
    n = next(n for n, r in sorted(page.work.rules.items()) if r.action == "map")
    page.clear_rules([n])
    assert page.cables.current.source_row(n).block is None
    page.resort_btn.click()
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
    pos = page.cables.mapFromScene(QPointF(PAD + 30, PAD + ROW / 2))
    QTest.mouseClick(page.cables.viewport(), Qt.MouseButton.LeftButton, pos=pos)
    app.processEvents()
    head = page.cables.current.header(UNASSIGNED)
    assert head.collapsed and head.count == len(page.work.source_map.names)
    assert page.cables.current.source_rows == []


def test_cables_view_saves_with_same_dialog(window, storage):
    from midiremap.ui.cable_layout import KEEP
    from midiremap.ui.profiles_page import CABLES_VIEW
    page = window.profiles_page
    pid = new_profile(page)
    page.set_view(CABLES_VIEW)
    page.accept_suggestions()
    assert len(page.cables.cable_items) == map_rule_count(page.work)
    page.answers["unassigned"] = set()
    assert page.save() and page.answers["asked"][-1][0] == "unassigned"
    saved = storage.load_profile(pid)
    assert page.cables.profile is page.work and page.work.to_dict() == saved.to_dict()
    assert page.cables.current.header(KEEP).count == sum(r == Rule.keep() for r in saved.rules.values())
