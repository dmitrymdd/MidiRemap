"""Основной кабель (8b3b2): with_primary_cable (→), with_forward_primary (←), нормализация обратных правил,
тексты замечаний validate_profile в обратном направлении."""
from dataclasses import replace

import pytest

from midiremap.core import profile as profile_module
from midiremap.core.notemap import NoteMap
from midiremap.core.profile import (
    REVERSE, DST_NOT_IN_TARGET, KEEP_DIFFERENT, SRC_NOT_IN_SOURCE, RemapProfile, Rule, derive_reverse,
    normalized_reverse, pin_primary, primary_pairs, validate_profile, with_forward_primary, with_primary_cable,
)

M = Rule.map_to

# «Ride: Bell» на четырёх нотах (как в EZD3 — на 15), Write to — 53
RIDE = NoteMap("T", {53: "Ride: Bell", 60: "Ride: Bell", 61: "Ride: Bell", 62: "Ride: Bell", 36: "Kick"},
               primary={53})
HATS = NoteMap("T", {42: "Hat", 44: "Hat", 46: "Hat", 36: "Kick"})


def prof(rules, tgt=None, reverse=None, src=None):
    return RemapProfile("p", src, tgt, rules, reverse)


# --- → : with_primary_cable ---

def test_primary_cable_sets_reverse_rule():
    p = prof({60: M(60), 121: M(60), 124: M(60)})
    assert primary_pairs(p) == {(60, 60)}
    out = with_primary_cable(p, 121, 60)
    assert out.effective_reverse() == {60: M(121)} and primary_pairs(out) == {(121, 60)}
    assert out.rules == p.rules and p.reverse_rules is None  # прямые не меняются, вход не меняется


def test_primary_cable_moves_donor_aliases():
    # 53 -> 53 основной; алиасы Write to (60, 61, 62) без кабелей копируют его правило
    p = prof({53: M(53), 70: M(53)}, RIDE)
    assert derive_reverse(p) == {n: M(53) for n in (53, 60, 61, 62)}
    out = with_primary_cable(p, 70, 53)
    assert out.effective_reverse() == {n: M(70) for n in (53, 60, 61, 62)}
    assert (70, 53) in primary_pairs(out)


def test_primary_cable_leaves_aliases_of_other_donor_and_manual_rules():
    # донор артикуляции Hat — 42 (Write to нет, наименьшая с кабелями); 44 копирует его правило
    p = prof({10: M(42), 11: M(46), 12: M(46)}, HATS)
    assert derive_reverse(p) == {42: M(10), 44: M(10), 46: M(11)}
    out = with_primary_cable(p, 12, 46)  # 46 — не донор: алиас 44 остаётся
    assert out.effective_reverse() == {42: M(10), 44: M(10), 46: M(12)}
    # ручное правило алиаса (отличается от прежнего правила донора) не трогается
    p = prof({53: M(53), 70: M(53)}, RIDE, reverse={53: M(53), 60: M(53), 61: Rule.delete(), 62: M(53)})
    out = with_primary_cable(p, 70, 53)
    assert out.effective_reverse() == {53: M(70), 60: M(70), 61: Rule.delete(), 62: M(70)}


def test_primary_cable_noop_and_errors():
    p = prof({53: M(53), 70: M(53)}, RIDE)
    assert with_primary_cable(p, 53, 53).to_dict() == p.to_dict()  # уже основной
    with pytest.raises(ValueError):
        with_primary_cable(p, 70, 60)  # прямого правила 70 -> 60 нет


# --- ← : with_forward_primary ---

def test_forward_primary_aliases_follow_new_cable():
    # ← : цель 44 (алиас) ведёт назад на 10 — двойной клик делает прямым 10 -> 44
    p = prof({10: M(42)}, HATS)
    assert p.effective_reverse() == {42: M(10), 44: M(10), 46: M(10)}
    out = with_forward_primary(p, 10, 44)
    assert out.rules == {10: M(44)} and (10, 44) in primary_pairs(out)
    assert out.reverse_rules is None  # обратные по-прежнему выводятся
    assert out.effective_reverse() == {42: M(10), 44: M(10), 46: M(10)}


def test_forward_primary_rules_derived_for_old_target_follow():
    # заданные обратные: выведенные + одно ручное (36 delete); 10 и 11 -> 42, ← кабель 44 -> 10
    p = prof({10: M(42), 11: M(42)}, HATS)
    p.reverse_rules = derive_reverse(p) | {36: Rule.delete()}
    out = with_forward_primary(p, 10, 44)
    assert out.rules == {10: M(44), 11: M(42)}
    # 42 и его алиас 46 следуют за прямыми (теперь 42 <- 11), ручное 36 — на месте
    assert out.effective_reverse() == {36: Rule.delete(), 42: M(11), 44: M(10), 46: M(11)}
    assert (10, 44) in primary_pairs(out)


def test_forward_primary_pins_reverse_rule_if_sync_moves_it(monkeypatch):
    # постусловие: если синхронизация сдвинула правило b, b -> a ставится явно
    p = prof({10: M(42)}, HATS)
    monkeypatch.setattr(profile_module, "sync_reverse", lambda before, after: {44: M(99), 42: M(10)})
    out = with_forward_primary(p, 10, 44)
    assert out.effective_reverse()[44] == M(10) and (10, 44) in primary_pairs(out)
    # pin_primary сам по себе: уже основной — ничего не меняет
    q = prof({10: M(42)}, HATS)
    pin_primary(q, 10, 42)
    assert q.reverse_rules is None


def test_forward_primary_requires_reverse_cable():
    with pytest.raises(ValueError):
        with_forward_primary(prof({10: M(42)}, HATS), 11, 44)


# --- нормализация ---

def test_normalized_reverse():
    p = prof({10: M(42)}, HATS)
    p.reverse_rules = derive_reverse(p)
    assert normalized_reverse(p) is None
    p.reverse_rules = derive_reverse(p) | {36: Rule.delete()}
    assert normalized_reverse(p) == {36: Rule.delete(), 42: M(10), 44: M(10), 46: M(10)}
    # чтение JSON — та же нормализация
    assert RemapProfile.from_json(replace(p, reverse_rules=derive_reverse(p)).to_json()).reverse_rules is None


# --- замечания в обратном направлении ---

def test_validate_profile_reverse_names_profile_maps():
    src = NoteMap("S", {36: "Kick", 38: "Snare"})
    tgt = NoteMap("T", {36: "Kick", 40: "Snare"})
    p = prof({36: M(36)}, tgt, reverse={36: M(50), 41: M(36), 40: Rule.keep()}, src=src)
    issues = {(i.code, i.note): i.message for i in validate_profile(p, REVERSE)}
    assert issues[(DST_NOT_IN_TARGET, 36)] == "note 36 is mapped to 50, which is not in the source map"
    assert issues[(SRC_NOT_IN_SOURCE, 41)] == "rule for note 41, which is not in the target map"
    assert issues[("keep_not_in_target_map", 40)] == "note 40 is kept, but the source map has no note 40"
    # в прямом направлении — как раньше
    p2 = prof({38: Rule.keep()}, NoteMap("T", {38: "Tom"}), src=src)
    (issue,) = [i for i in validate_profile(p2) if i.code == KEEP_DIFFERENT]
    assert issue.message == 'note 38 is kept, but it is "Snare" in the source map and "Tom" in the target map'
