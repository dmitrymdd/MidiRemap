"""Основной кабель: with_primary_cable (→), with_forward_primary (←), нормализация обратных правил,
тексты замечаний validate_profile в обратном направлении."""
import copy
from dataclasses import replace
from pathlib import Path

import pytest

from remap.core import profile as profile_module
from remap.core.notemap import NoteMap
from remap.core.profile import (
    REVERSE, DST_NOT_IN_TARGET, KEEP_DIFFERENT, SRC_NOT_IN_SOURCE, RemapProfile, Rule, derive_reverse,
    keep_old_target_reverse, normalized_reverse, pin_primary, primary_pairs, validate_profile, with_forward_primary, with_primary_cable,
)

M = Rule.map_to
FIXTURES = Path(__file__).resolve().parent / "fixtures"

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


def test_forward_primary_keeps_reverse_rule_of_old_target():
    # заданные обратные: выведенные + одно ручное (36 delete); 10 и 11 -> 42, ← кабель 44 -> 10
    p = prof({10: M(42), 11: M(42)}, HATS)
    p.reverse_rules = derive_reverse(p) | {36: Rule.delete()}
    out = with_forward_primary(p, 10, 44)
    assert out.rules == {10: M(44), 11: M(42)}
    # 42 и его алиас 46 (копия правила 42) — как были (42 -> 10), а не переехали на 11; ручное 36 — на месте
    assert out.effective_reverse() == {36: Rule.delete(), 42: M(10), 44: M(10), 46: M(10)}
    assert (10, 44) in primary_pairs(out)


def test_keep_old_target_reverse_fixes_only_old_target_and_its_alias_copies():
    p = prof({10: M(42), 11: M(42), 12: M(36)}, HATS)  # обратные — выведенные (None)
    out = with_forward_primary(p, 10, 44)
    eff, derived = out.effective_reverse(), derive_reverse(out)
    # заданы явно (отличаются от выведенных) только 42 и копия его правила у алиаса 46
    assert {n for n in eff if eff[n] != derived.get(n)} == {42, 46}
    assert eff[42] == eff[46] == M(10) and eff[36] == derived[36] == M(12)
    # сама функция: что зафиксировала
    after = prof({10: M(44), 11: M(42), 12: M(36)}, HATS)
    after.reverse_rules = profile_module.sync_reverse(p, after)
    assert keep_old_target_reverse(p, after, 10) == [42, 46]
    assert after.effective_reverse()[42] == M(10)
    # прямое правило не менялось или его не было — ничего
    assert keep_old_target_reverse(p, copy.deepcopy(p), 10) == []
    assert keep_old_target_reverse(p, prof({10: M(42), 11: M(42), 12: M(36), 13: M(44)}, HATS), 13) == []


def test_keep_old_target_reverse_leaves_manual_rule_alone():
    # обратное правило прежней цели задано вручную (42 -> 11, выведенное было бы 42 -> 10) — не фиксируется
    p = prof({10: M(42), 11: M(42)}, HATS, reverse={42: M(11), 44: M(10), 46: M(10)})
    out = with_forward_primary(p, 10, 44)
    assert out.effective_reverse()[42] == M(11)


def test_later_forward_edit_still_updates_other_derived_reverse_rules():
    # после двойного клика в ← прочие выведенные обратные правила по-прежнему следуют за прямыми
    p = prof({10: M(42), 11: M(42), 12: M(36)}, HATS)
    out = with_forward_primary(p, 10, 44)
    edited = copy.deepcopy(out)
    edited.rules[9] = M(36)  # теперь на 36 идут 9 и 12 — выведено 36 -> 9
    edited.reverse_rules = profile_module.sync_reverse(out, edited)
    eff = edited.effective_reverse()
    assert eff[36] == M(9)  # следует за прямыми (не заморожено)
    assert eff[42] == eff[46] == M(10)  # зафиксированное — на месте


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


# --- двойной клик по кабелю: прочие кабели не должны меняться ---

KICKS = NoteMap("T", {7: "Kick: A", 18: "Kick: B"})


def test_forward_double_click_keeps_other_cables():
    # → : меняется только обратное правило b (и алиасы-«дублёры» b); прямые кабели все на месте
    p = prof({10: M(42), 11: M(42), 12: M(44)}, HATS)
    before = p.effective_reverse()
    out = with_primary_cable(p, 11, 42)
    assert out.rules == p.rules and (11, 42) in primary_pairs(out)
    after = out.effective_reverse()
    assert {b: r for b, r in after.items() if b not in (42, 46)} == {b: r for b, r in before.items()
                                                                    if b not in (42, 46)}
    assert after[42] == after[46] == M(11)  # 46 — алиас 42 без своего кабеля: следует за ним


def test_reverse_double_click_keeps_other_reverse_cables():
    # ← : кабели 7 -> 7 (основной) и 18 -> 7 (ручной). Двойной клик по 18 -> 7 — прямое 7 -> 18;
    # кабель 7 -> 7 остаётся (теперь неосновной), а не удаляется синхронизацией
    p = prof({7: M(7)}, KICKS, reverse={7: M(7), 18: M(7)})
    out = with_forward_primary(p, 7, 18)
    assert out.rules == {7: M(18)} and (7, 18) in primary_pairs(out)
    assert out.effective_reverse() == {7: M(7), 18: M(7)}


def test_reverse_double_click_does_not_move_old_target_to_another_source():
    # 10 и 11 -> 42; ← кабель 44 -> 10: 42 -> 10 и 46 -> 10 остаются, а не уходят на 11
    p = prof({10: M(42), 11: M(42)}, HATS)
    out = with_forward_primary(p, 10, 44)
    assert out.effective_reverse() == {42: M(10), 44: M(10), 46: M(10)}


def test_saved_ezd3_sd3_profile_reverse_double_click_loses_no_cable():
    # сохранённый профиль пользователя EZD3 – SD3: каждый неосновной кабель ← — двойной клик, прочие на месте
    p = RemapProfile.from_json((FIXTURES / "ezd3_sd3_saved.json").read_text(encoding="utf-8"))

    def cables(q):
        return {(b, r.dst) for b, r in q.effective_reverse().items() if r.action == "map"}

    prim = primary_pairs(p)
    cases = sorted((b, a) for b, a in cables(p) if (a, b) not in prim)
    assert len(cases) == 44
    for b, a in cases:
        out = with_forward_primary(p, a, b)
        assert cables(out) == cables(p), (b, a)  # ни один кабель не пропал и не переехал
        assert (a, b) in primary_pairs(out) and out.rules[a] == M(b)
        assert {n: r for n, r in out.rules.items() if n != a} == {n: r for n, r in p.rules.items() if n != a}


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


# --- двойной клик по Unassigned: занятый номер — прежний основной остаётся ---

def test_keep_existing_primary_on_occupied_number():
    from remap.core.profile import connect_same_numbers, keep_existing_primary, sync_reverse
    # 70 -> 53 основной (алиасы 60, 61, 62 копируют его); подключаем 53 -> 53 — номер занят
    p = prof({70: M(53)}, RIDE)
    assert primary_pairs(p) == {(70, 53)}
    new, done = connect_same_numbers(p, [53], list(RIDE.names))
    assert done == [53] and primary_pairs(new) == {(53, 53)}  # без фиксации выведение предпочло бы n -> n
    new.reverse_rules = sync_reverse(p, new)
    assert keep_existing_primary(p, new, done) == [53]
    assert primary_pairs(new) == {(70, 53)} and new.rules[53] == M(53)
    assert new.effective_reverse() == {n: M(70) for n in (53, 60, 61, 62)}
    # свободный номер — ничего не фиксируется, новый кабель основной
    q = prof({}, RIDE)
    new, done = connect_same_numbers(q, [36], list(RIDE.names))
    new.reverse_rules = sync_reverse(q, new)
    assert keep_existing_primary(q, new, done) == [] and primary_pairs(new) == {(36, 36)}
