"""Раскладка вида «кабелями» (ui/cable_layout.py): чистый Python, без Qt."""
import os
import subprocess
import sys
from pathlib import Path

from midiremap.core.notemap import NoteMap, articulations, normalize_name
from midiremap.core.profile import RemapProfile, Rule
from midiremap.templates import load_map_template
from midiremap.ui.cable_layout import (
    DELETE, KEEP, MAPPED, TARGET_PREFIX, UNASSIGNED, Header, OrderSnapshot, TargetRow, build_layout,
    fresh_order, slot_key, update_order,
)

SRC = NoteMap("Src", {36: "Kick: Hit", 37: "Kick: Soft", 38: "Snare: Center", 40: "Snare: Rim",
                      42: "Hat: Closed", 46: "Hat: Open", 49: "Crash: Hit"})
TGT = NoteMap("Tgt", {36: "Kick: Hit", 38: "Snare: Center", 39: "Snare: Center", 42: "Hat: Closed",
                      46: "Hat: Open", 57: "Crash: Hit"}, primary={38})


def profile(rules=None, src=SRC, tgt=TGT):
    return RemapProfile("p", src, tgt, rules or {})


def no_collapse():
    return set()


def rows_by_note(layout):
    return {r.note: r for r in layout.source_rows}


# --- колонка цели ---

def test_target_one_row_per_articulation_grouped():
    lay = build_layout(profile(), no_collapse())
    assert [r.label for r in lay.target_rows] == ["Kick: Hit", "Snare: Center", "Hat: Closed", "Hat: Open",
                                                  "Crash: Hit"]
    snare = lay.target_row("a:snare: center")
    assert snare.notes == (38, 39) and snare.write_to == 38
    assert [h.label for h in lay.target_headers] == ["Kick", "Snare", "Hat", "Crash"]
    hat = lay.header(TARGET_PREFIX + "hat")
    assert hat.count == 2 and hat.y + 1 == lay.target_row("a:hat: closed").y


def test_target_rows_from_real_template_match_articulations():
    sd3 = load_map_template("Superior Drummer 3")
    lay = build_layout(profile(src=None, tgt=sd3), no_collapse())
    assert {r.slot for r in lay.target_rows} == {"a:" + k for k in articulations(sd3)}
    assert lay.target_headers  # SD3 — с группами


def test_flat_target_without_groups():
    gm = NoteMap("GM", {35: "Acoustic Bass Drum", 36: "Bass Drum 1"})
    lay = build_layout(profile(src=None, tgt=gm), no_collapse())
    assert lay.target_headers == [] and len(lay.target_rows) == 2


def test_map_to_non_primary_note_shown_on_articulation_row():
    lay = build_layout(profile({38: Rule.map_to(39)}), no_collapse())
    (cable,) = lay.cables
    assert cable.dst == 39 and isinstance(cable.target, TargetRow) and cable.target.slot == "a:snare: center"
    assert rows_by_note(lay)[38].y == cable.target.y


def test_dst_outside_target_map_and_no_target_map():
    lay = build_layout(profile({36: Rule.map_to(99)}), no_collapse())
    row = lay.target_row("n:99")
    assert row is not None and not row.in_map and row.notes == (99,)
    assert lay.header(TARGET_PREFIX + "\0missing").label == "Not in the target map"
    lay = build_layout(profile({36: Rule.map_to(99), 38: Rule.map_to(99)}, tgt=None), no_collapse())
    assert [r.slot for r in lay.target_rows] == ["n:99"] and lay.target_rows[0].height == 2
    assert lay.target_headers == [] and len(lay.cables) == 2


# --- колонка источника ---

def test_status_blocks_order_and_groups():
    rules = {36: Rule.keep(), 40: Rule.delete(), 42: Rule.map_to(42), 37: Rule.keep()}
    lay = build_layout(profile(rules), no_collapse())
    blocks = [h for h in lay.source_headers if h.level == 0]
    assert [(h.key, h.count) for h in blocks] == [(UNASSIGNED, 3), (KEEP, 2), (DELETE, 1)]
    by = rows_by_note(lay)
    assert by[38].block == UNASSIGNED and by[38].state == UNASSIGNED
    assert by[36].block == KEEP and by[36].state == KEEP
    assert by[40].block == DELETE and by[40].state == DELETE
    # внутри блока — по группам исходной карты
    groups = [h.label for h in lay.source_headers if h.key.startswith(UNASSIGNED + "/")]
    assert groups == ["Snare", "Hat", "Crash"]
    # подключённые — ниже блоков, напротив цели
    assert by[42].block is None and by[42].connected and by[42].state == MAPPED
    assert by[42].y >= lay.connected_top > max(r.y for r in lay.source_rows if r.block is not None)
    assert by[42].y == lay.target_row("a:hat: closed").y


def test_many_into_one_tall_target_row():
    src = NoteMap("Src", {n: f"Tom {n}: Hit" for n in range(60, 70)})
    rules = {n: Rule.map_to(36) for n in range(60, 70)}
    lay = build_layout(profile(rules, src=src), no_collapse())
    kick = lay.target_row("a:kick: hit")
    assert kick.height == 10
    assert sorted(rows_by_note(lay)[n].y for n in range(60, 70)) == list(range(kick.y, kick.y + 10))
    assert len(lay.cables) == 10 and all(c.target == kick for c in lay.cables)
    # следующая строка цели — сразу под высокой
    nxt = min((r for r in lay.target_rows + lay.target_headers if r.y > kick.y), key=lambda r: r.y)
    assert nxt.y == kick.y + 10


def test_without_source_map_rows_are_rules():
    lay = build_layout(profile({5: Rule.delete(), 36: Rule.map_to(36)}, src=None), no_collapse())
    by = rows_by_note(lay)
    assert set(by) == {5, 36} and by[5].name is None and by[36].connected
    # без исходной карты групп в блоках нет
    assert [h.key for h in lay.source_headers] == [DELETE]


def test_empty_profile():
    lay = build_layout(profile(src=None, tgt=None))
    assert lay.source_rows == [] and lay.target_rows == [] and lay.height == 0
    assert build_layout(None).height == 0


# --- сворачивание ---

def test_collapsed_block_and_group_show_counts():
    rules = {36: Rule.keep(), 37: Rule.keep(), 42: Rule.map_to(42)}
    lay = build_layout(profile(rules), {KEEP, UNASSIGNED + "/snare"})
    keep = lay.header(KEEP)
    assert keep.collapsed and keep.count == 2
    assert not any(r.block == KEEP for r in lay.source_rows)
    assert not any(h.key.startswith(KEEP + "/") for h in lay.source_headers)
    snare = lay.header(UNASSIGNED + "/snare")
    assert snare.collapsed and snare.count == 2
    assert {r.note for r in lay.source_rows if r.block == UNASSIGNED} == {46, 49}


def test_default_collapsed_keep_and_delete():
    lay = build_layout(profile({36: Rule.keep(), 40: Rule.delete()}))
    assert lay.header(KEEP).collapsed and lay.header(DELETE).collapsed and not lay.header(UNASSIGNED).collapsed


def test_collapsed_target_group_cables_converge_on_header():
    rules = {42: Rule.map_to(42), 46: Rule.map_to(46), 36: Rule.map_to(42)}
    lay = build_layout(profile(rules), {TARGET_PREFIX + "hat"})
    head = lay.header(TARGET_PREFIX + "hat")
    assert head.collapsed and head.count == 2 and head.height == 3
    assert lay.target_row("a:hat: closed") is None
    hat_cables = [c for c in lay.cables if isinstance(c.target, Header)]
    assert {c.src for c in hat_cables} == {36, 42, 46} and all(c.target == head for c in hat_cables)
    assert sorted(rows_by_note(lay)[n].y for n in (36, 42, 46)) == [head.y, head.y + 1, head.y + 2]


# --- замороженный порядок ---

def test_removed_cable_row_stays_in_place_until_resort():
    p = profile({38: Rule.map_to(38), 40: Rule.map_to(38)})
    first = build_layout(p, no_collapse())
    y40 = rows_by_note(first)[40].y
    p.rules[40] = Rule.delete()
    lay = build_layout(p, no_collapse(), first.order)
    row = rows_by_note(lay)[40]
    assert row.y == y40 and row.block is None and not row.connected and row.state == DELETE
    assert {c.src for c in lay.cables} == {38}
    assert lay.target_row("a:snare: center").height == 2  # строка всё ещё напротив
    resorted = build_layout(p, no_collapse(), None)
    assert rows_by_note(resorted)[40].block == DELETE
    assert resorted.target_row("a:snare: center").height == 1


def test_cleared_rule_row_stays_in_place():
    p = profile({38: Rule.map_to(38)})
    first = build_layout(p, no_collapse())
    del p.rules[38]
    lay = build_layout(p, no_collapse(), first.order)
    assert rows_by_note(lay)[38].block is None and rows_by_note(lay)[38].state == UNASSIGNED
    assert lay.order.place_of(38) == ("slot", "a:snare: center")


def test_newly_connected_row_moves_opposite_target_immediately():
    p = profile()
    first = build_layout(p, no_collapse())
    assert rows_by_note(first)[40].block == UNASSIGNED
    p.rules[40] = Rule.map_to(39)
    lay = build_layout(p, no_collapse(), first.order)
    row, tgt = rows_by_note(lay)[40], lay.target_row("a:snare: center")
    assert row.block is None and row.connected and row.y == tgt.y
    # остальные неназначенные — в прежнем порядке
    assert [n for n in first.order.blocks[UNASSIGNED] if n != 40] == list(lay.order.blocks[UNASSIGNED])


def test_reconnected_row_moves_to_new_target_and_appends():
    p = profile({36: Rule.map_to(38), 38: Rule.map_to(38), 40: Rule.map_to(42)})
    first = build_layout(p, no_collapse())
    p.rules[36] = Rule.map_to(42)
    lay = build_layout(p, no_collapse(), first.order)
    assert lay.order.slots[slot_key(TGT, 42)] == (40, 36)  # новая связь — в конец
    assert lay.order.slots[slot_key(TGT, 38)] == (38,)


def test_state_change_inside_blocks_stays_in_block():
    p = profile()
    first = build_layout(p, no_collapse())
    p.rules[38] = Rule.delete()
    lay = build_layout(p, no_collapse(), first.order)
    row = rows_by_note(lay)[38]
    assert row.block == UNASSIGNED and row.state == DELETE and row.y == rows_by_note(first)[38].y
    assert lay.header(DELETE) is None


def test_order_is_stable_without_changes():
    p = profile({36: Rule.map_to(36), 38: Rule.keep()})
    order = fresh_order(p)
    assert update_order(p, order) == order
    assert update_order(p, None) == order


def test_stale_snapshot_is_tolerated():
    p = profile({36: Rule.map_to(36)})
    stale = OrderSnapshot({UNASSIGNED: (1, 2, 38)}, {"a:gone": (36, 3), "n:57": (40,)})
    order = update_order(p, stale)
    notes = [n for v in (*order.blocks.values(), *order.slots.values()) for n in v]
    assert sorted(notes) == sorted(SRC.names)  # каждая нота ровно один раз, лишних нет
    assert order.place_of(36) == ("slot", "a:kick: hit")
    assert "n:57" not in order.slots  # 57 теперь есть в целевой карте


def test_slot_keys_compare_names_normalized():
    tgt = NoteMap("T", {10: "Ride: Bell", 11: "ride:  BELL"})
    assert slot_key(tgt, 10) == slot_key(tgt, 11) == "a:" + normalize_name("Ride: Bell")
    assert slot_key(tgt, 12) == "n:12" and slot_key(None, 10) == "n:10"


def test_no_qt_imports():
    code = ("import sys, midiremap.ui.cable_layout; "
            "assert not [m for m in sys.modules if m.startswith('PySide6')], 'Qt imported'")
    src = str(Path(__file__).resolve().parents[1] / "src")
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(filter(None, [src, os.environ.get("PYTHONPATH")]))}
    subprocess.run([sys.executable, "-c", code], check=True, env=env)
