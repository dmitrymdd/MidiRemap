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
    return {r.note: r for r in layout.pool.rows + layout.scene.source_rows}


def show_all(p):
    """Все группы цели в режиме «все»."""
    return {h.key for h in build_layout(p, no_collapse()).scene.target_headers}


# --- колонка цели ---

def test_target_one_row_per_articulation_grouped():
    lay = build_layout(profile(), no_collapse(), show_all=show_all(profile()))
    assert [r.label for r in lay.scene.target_rows] == ["Kick: Hit", "Snare: Center", "Hat: Closed", "Hat: Open",
                                                  "Crash: Hit"]
    snare = lay.target_row("a:snare: center")
    assert snare.notes == (38, 39) and snare.write_to == 38
    assert [h.label for h in lay.scene.target_headers] == ["Kick", "Snare", "Hat", "Crash"]
    hat = lay.header(TARGET_PREFIX + "hat")
    assert hat.count == 2 and hat.y + 1 == lay.target_row("a:hat: closed").y


def test_target_rows_from_real_template_match_articulations():
    sd3 = load_map_template("Superior Drummer 3")
    p = profile(src=None, tgt=sd3)
    lay = build_layout(p, no_collapse(), show_all=show_all(p))
    assert {r.slot for r in lay.scene.target_rows} == {"a:" + k for k in articulations(sd3)}
    assert lay.scene.target_headers  # SD3 — с группами


def test_flat_target_without_groups():
    gm = NoteMap("GM", {35: "Acoustic Bass Drum", 36: "Bass Drum 1"})
    lay = build_layout(profile(src=None, tgt=gm), no_collapse())
    assert lay.scene.target_headers == [] and len(lay.scene.target_rows) == 2


def test_map_to_non_primary_note_shown_on_articulation_row():
    lay = build_layout(profile({38: Rule.map_to(39)}), no_collapse())
    (cable,) = lay.scene.cables
    assert cable.dst == 39 and isinstance(cable.target, TargetRow) and cable.target.slot == "a:snare: center"
    assert rows_by_note(lay)[38].y == cable.target.y


def test_dst_outside_target_map_and_no_target_map():
    lay = build_layout(profile({36: Rule.map_to(99)}), no_collapse())
    row = lay.target_row("n:99")
    assert row is not None and not row.in_map and row.notes == (99,)
    assert lay.header(TARGET_PREFIX + "\0missing").label == "Not in the target map"
    lay = build_layout(profile({36: Rule.map_to(99), 38: Rule.map_to(99)}, tgt=None), no_collapse())
    assert [r.slot for r in lay.scene.target_rows] == ["n:99"] and lay.scene.target_rows[0].height == 2
    assert lay.scene.target_headers == [] and len(lay.scene.cables) == 2


# --- колонка источника ---

def test_status_blocks_order_and_groups():
    rules = {36: Rule.keep(), 40: Rule.delete(), 42: Rule.map_to(42), 37: Rule.keep()}
    lay = build_layout(profile(rules), no_collapse())
    blocks = [h for h in lay.pool.headers if h.level == 0]
    assert [(h.key, h.count) for h in blocks] == [(UNASSIGNED, 3), (KEEP, 2), (DELETE, 1)]
    by = rows_by_note(lay)
    assert by[38].block == UNASSIGNED and by[38].state == UNASSIGNED
    assert by[36].block == KEEP and by[36].state == KEEP
    assert by[40].block == DELETE and by[40].state == DELETE
    # внутри блока — по группам исходной карты
    groups = [h.label for h in lay.pool.headers if h.key.startswith(UNASSIGNED + "/")]
    assert groups == ["Snare", "Hat", "Crash"]
    # подключённые — не в пуле, а в сцене напротив цели
    assert by[42].block is None and by[42].connected and by[42].state == MAPPED
    assert 42 not in {r.note for r in lay.pool.rows}
    assert [r.note for r in lay.scene.source_rows] == [42]
    assert by[42].y == lay.target_row("a:hat: closed").y


def test_many_into_one_tall_target_row():
    src = NoteMap("Src", {n: f"Tom {n}: Hit" for n in range(60, 70)})
    rules = {n: Rule.map_to(36) for n in range(60, 70)}
    lay = build_layout(profile(rules, src=src), no_collapse())
    kick = lay.target_row("a:kick: hit")
    assert kick.height == 10
    assert sorted(rows_by_note(lay)[n].y for n in range(60, 70)) == list(range(kick.y, kick.y + 10))
    assert len(lay.scene.cables) == 10 and all(c.target == kick for c in lay.scene.cables)
    # следующая строка цели — сразу под высокой
    nxt = min((r for r in lay.scene.target_rows + lay.scene.target_headers if r.y > kick.y), key=lambda r: r.y)
    assert nxt.y == kick.y + 10


def test_without_source_map_rows_are_rules():
    lay = build_layout(profile({5: Rule.delete(), 36: Rule.map_to(36)}, src=None), no_collapse())
    by = rows_by_note(lay)
    assert set(by) == {5, 36} and by[5].name is None and by[36].connected
    # без исходной карты групп в блоках нет
    assert [h.key for h in lay.pool.headers] == [DELETE]


def test_empty_profile():
    lay = build_layout(profile(src=None, tgt=None))
    assert lay.pool.rows == [] and lay.scene.target_rows == [] and lay.pool.height == lay.scene.height == 0
    assert build_layout(None).scene.height == 0


# --- сворачивание ---

def test_collapsed_block_and_group_show_counts():
    rules = {36: Rule.keep(), 37: Rule.keep(), 42: Rule.map_to(42)}
    lay = build_layout(profile(rules), {KEEP, UNASSIGNED + "/snare"})
    keep = lay.header(KEEP)
    assert keep.collapsed and keep.count == 2
    assert not any(r.block == KEEP for r in lay.pool.rows)
    assert not any(h.key.startswith(KEEP + "/") for h in lay.pool.headers)
    snare = lay.header(UNASSIGNED + "/snare")
    assert snare.collapsed and snare.count == 2
    assert {r.note for r in lay.pool.rows if r.block == UNASSIGNED} == {46, 49}


def test_default_collapsed_keep_and_delete():
    lay = build_layout(profile({36: Rule.keep(), 40: Rule.delete()}))
    assert lay.header(KEEP).collapsed and lay.header(DELETE).collapsed and not lay.header(UNASSIGNED).collapsed


# --- замороженный порядок ---

def test_removed_cable_row_stays_in_place_until_resort():
    p = profile({38: Rule.map_to(38), 40: Rule.map_to(38)})
    first = build_layout(p, no_collapse())
    y40 = rows_by_note(first)[40].y
    p.rules[40] = Rule.delete()
    lay = build_layout(p, no_collapse(), first.order)
    row = rows_by_note(lay)[40]
    assert row.y == y40 and row.block is None and not row.connected and row.state == DELETE
    assert {c.src for c in lay.scene.cables} == {38}
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


# --- пул и сцена (8b2a.1) ---

def test_scene_starts_at_top_regardless_of_pool():
    lay = build_layout(profile({42: Rule.map_to(42)}), no_collapse())
    assert len(lay.pool.rows) == len(SRC.names) - 1  # 6 неназначенных — в пуле
    first = min(lay.scene.target_headers + lay.scene.target_rows, key=lambda r: r.y)
    assert first.y == 0
    assert lay.scene.height == sum(r.height for r in lay.scene.target_rows) + len(lay.scene.target_headers)
    assert lay.pool.height == len(lay.pool.headers) + len(lay.pool.rows)


def test_connecting_leaves_pool_and_removing_returns_after_resort():
    p = profile()
    first = build_layout(p, no_collapse())
    assert rows_by_note(first)[46].block == UNASSIGNED
    p.rules[46] = Rule.map_to(46)
    lay = build_layout(p, no_collapse(), first.order)
    assert 46 not in {r.note for r in lay.pool.rows}
    assert lay.header(UNASSIGNED).count == len(SRC.names) - 1
    row = rows_by_note(lay)[46]
    assert row.connected and not row.stale and row.y == lay.target_row("a:hat: open").y
    # кабель убрали — строка в сцене на месте, «устаревшая»
    del p.rules[46]
    lay2 = build_layout(p, no_collapse(), lay.order)
    row = rows_by_note(lay2)[46]
    assert row.stale and row.block is None and row.y == lay.source_row(46).y
    assert 46 not in {r.note for r in lay2.pool.rows}
    # пересортировка — обратно в пул
    lay3 = build_layout(p, no_collapse(), None)
    assert rows_by_note(lay3)[46].block == UNASSIGNED and lay3.scene.source_rows == []


def test_pool_collapse_does_not_move_scene():
    p = profile({42: Rule.map_to(42)})
    a = build_layout(p, no_collapse())
    b = build_layout(p, {UNASSIGNED})
    assert b.pool.rows == [] and b.header(UNASSIGNED).collapsed
    assert a.scene == b.scene


# --- группы цели: «только подключённые» / «все» (8b2b) ---

def test_target_groups_connected_only_by_default():
    p = profile({42: Rule.map_to(42), 36: Rule.map_to(42)})
    lay = build_layout(p, no_collapse())
    heads = {h.label: h for h in lay.scene.target_headers}
    assert set(heads) == {"Kick", "Snare", "Hat", "Crash"}  # все группы — хотя бы заголовком
    hat = heads["Hat"]
    assert hat.collapsed and hat.count == 2 and hat.shown == 1
    assert [r.slot for r in lay.scene.target_rows] == ["a:hat: closed"]
    assert heads["Kick"].collapsed and heads["Kick"].shown == 0
    assert lay.scene.height == len(heads) + 2  # заголовки + высокая строка Hat: Closed (две строки напротив)
    # «все» — только для выбранной группы
    lay = build_layout(p, no_collapse(), show_all={TARGET_PREFIX + "hat"})
    hat = lay.header(TARGET_PREFIX + "hat")
    assert not hat.collapsed and hat.shown == 1
    assert [r.slot for r in lay.scene.target_rows] == ["a:hat: closed", "a:hat: open"]


def test_target_row_stays_while_row_without_cable_is_opposite():
    p = profile({42: Rule.map_to(42)})
    first = build_layout(p, no_collapse())
    del p.rules[42]
    lay = build_layout(p, no_collapse(), first.order)
    assert lay.target_row("a:hat: closed") is not None and rows_by_note(lay)[42].stale
    assert build_layout(p, no_collapse()).target_row("a:hat: closed") is None  # после пересортировки — скрыта


def test_flat_target_shows_all_rows():
    gm = NoteMap("GM", {35: "Acoustic Bass Drum", 36: "Bass Drum 1"})
    lay = build_layout(profile(src=None, tgt=gm))
    assert len(lay.scene.target_rows) == 2


# --- алиасы источника (8b2b) ---

ALIAS_SRC = NoteMap("Src", {36: "Kick: Hit", 38: "Snare: Center", 39: "Snare: Center", 40: "snare:  center",
                            42: "Hat: Closed"})


def test_aliases_collapse_into_one_row_in_pool():
    lay = build_layout(profile(src=ALIAS_SRC), no_collapse())
    snare = lay.source_row(39)
    assert snare.notes == (38, 39, 40) and snare.alias == "unassigned|snare: center" and not snare.expanded
    assert lay.source_row(38) is snare and lay.source_row(40) is snare
    assert len(lay.pool.rows) == 3
    group = lay.header(UNASSIGNED + "/snare")
    assert group.count == 3 and group.notes == (38, 39, 40)  # заголовок считает ноты


def test_aliases_one_cable_per_row():
    rules = {n: Rule.map_to(38) for n in (38, 39, 40)}
    lay = build_layout(profile(rules, src=ALIAS_SRC), no_collapse())
    (row,) = lay.scene.source_rows
    assert row.notes == (38, 39, 40) and row.connected
    (cable,) = lay.scene.cables
    assert cable.notes == (38, 39, 40) and cable.src == 38 and cable.target.height == 1


def test_aliases_with_different_rules_shown_expanded():
    rules = {38: Rule.map_to(38), 39: Rule.map_to(39), 40: Rule.map_to(38)}
    lay = build_layout(profile(rules, src=ALIAS_SRC), no_collapse())
    head, *children = lay.scene.source_rows
    assert head.expanded and head.mixed and head.notes == (38, 39, 40) and head.state == "mixed"
    assert [c.notes for c in children] == [(38,), (39,), (40,)] and all(c.child for c in children)
    assert len(lay.scene.cables) == 3  # у заголовка кабеля нет
    assert lay.target_row("a:snare: center").height == 4
    assert lay.source_row(39) == children[1]


def test_alias_expanded_by_key_only_in_its_place():
    p = profile({38: Rule.map_to(38), 39: Rule.map_to(38)}, src=ALIAS_SRC)
    lay = build_layout(p, no_collapse(), expanded={"a:snare: center|snare: center"})
    head, *children = lay.scene.source_rows
    assert head.expanded and not head.mixed and [c.note for c in children] == [38, 39]
    assert lay.source_row(40).notes == (40,) and lay.source_row(40).block == UNASSIGNED  # в пуле — отдельно
    # тот же ключ для пула ничего не раскрывает в сцене
    lay = build_layout(p, no_collapse(), expanded={"unassigned|snare: center"})
    assert [r.notes for r in lay.scene.source_rows] == [(38, 39)]


def test_connecting_alias_row_moves_all_notes_together():
    p = profile(src=ALIAS_SRC)
    first = build_layout(p, no_collapse())
    for n in first.source_row(38).notes:
        p.rules[n] = Rule.map_to(39)
    lay = build_layout(p, no_collapse(), first.order)
    assert [r.notes for r in lay.scene.source_rows] == [(38, 39, 40)]
    assert [r.notes for r in lay.pool.rows] == [(36,), (42,)]
