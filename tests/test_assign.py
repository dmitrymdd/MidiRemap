"""Назначение нот на цель: совпадение номеров (assign_plan / assign_to_articulation) и группа (connect_same_numbers)."""
import pytest

from midiremap.core.notemap import NoteMap
from midiremap.core.profile import (
    RemapProfile, Rule, assign_plan, assign_to_articulation, connect_same_numbers, match_by_number, names_differ,
    number_matches,
)

SRC = NoteMap("src", {33: "Snare: Edge", 38: "Snare: Center", 39: "Snare: Center", 40: "Snare: Rim",
                      66: "Snare: Center", 70: "Snare: Center", 41: "Tom: Center", 43: "Tom: Center"})
# «Snare: Center» цели — на 38, 66, 125; Write to не выбран
TGT = NoteMap("tgt", {38: "Snare: Center", 66: "Snare: Center", 125: "Snare: Center", 40: "Snare: Rim",
                      41: "Tom: Center", 43: "Tom: Low"})


def profile(rules=None, tgt=TGT):
    return RemapProfile("p", SRC, tgt, rules or {})


def test_all_match_by_number_no_question():
    p = profile({38: Rule.delete()})
    plan = assign_plan(p, [38, 66], "snare: center")
    assert plan.same == (38, 66) and plan.others == () and not plan.ask
    out = assign_to_articulation(p, [38, 66], "Snare: Center")
    assert out.rules == {38: Rule.map_to(38), 66: Rule.map_to(66)}
    assert out.target_map.primary == set()  # Write to не понадобился — не выбирается
    assert p.rules == {38: Rule.delete()}   # вход не меняется


def test_partial_match_uses_existing_write_to():
    tgt = NoteMap("tgt", dict(TGT.names), primary={125})
    p = profile(tgt=tgt)
    plan = assign_plan(p, [38, 39, 70], "Snare: Center")
    assert plan.same == (38,) and plan.others == (39, 70) and plan.write_to == 125 and not plan.ask
    out = assign_to_articulation(p, [38, 39, 70], "Snare: Center")
    assert out.rules == {38: Rule.map_to(38), 39: Rule.map_to(125), 70: Rule.map_to(125)}
    assert out.target_map.primary == {125}


def test_single_match_becomes_write_to_silently():
    p = profile()
    plan = assign_plan(p, [39, 66, 70], "Snare: Center")
    assert plan.same == (66,) and plan.write_to == 66 and not plan.ask
    out = assign_to_articulation(p, [39, 66, 70], "Snare: Center")
    assert out.rules == {39: Rule.map_to(66), 66: Rule.map_to(66), 70: Rule.map_to(66)}
    assert out.target_map.primary == {66}
    assert p.target_map.primary == set()  # копия цели во входном профиле не меняется


def test_several_matches_ask_once_with_preselect():
    p = profile()
    plan = assign_plan(p, [70, 66, 38, 39], "Snare: Center")
    assert plan.same == (38, 66) and plan.others == (39, 70)
    assert plan.ask and plan.write_to is None and plan.preselect == 38
    with pytest.raises(ValueError):
        assign_to_articulation(p, [38, 39, 66, 70], "Snare: Center")  # без ответа нельзя
    with pytest.raises(ValueError):
        assign_to_articulation(p, [38, 39, 66, 70], "Snare: Center", write_to=40)  # не нота артикуляции
    out = assign_to_articulation(p, [38, 39, 66, 70], "Snare: Center", write_to=125)
    assert out.rules == {38: Rule.map_to(38), 66: Rule.map_to(66), 39: Rule.map_to(125), 70: Rule.map_to(125)}
    assert out.target_map.primary == {125}


def test_no_match_asks_without_preselect():
    plan = assign_plan(profile(), [39, 70], "Snare: Center")
    assert plan.same == () and plan.ask and plan.preselect is None


def test_single_note_articulation_and_errors():
    p = profile()
    plan = assign_plan(p, [33, 40], "Snare: Rim")
    assert plan.same == (40,) and plan.write_to == 40 and not plan.ask
    out = assign_to_articulation(p, [33, 40], "Snare: Rim")
    assert out.rules == {33: Rule.map_to(40), 40: Rule.map_to(40)} and out.target_map.primary == set()
    with pytest.raises(ValueError):
        assign_plan(p, [33], "Cowbell")
    with pytest.raises(ValueError):
        assign_plan(RemapProfile("p", SRC, None), [33], "Snare: Rim")


def test_replaces_previous_rules_of_assigned_notes():
    p = profile({38: Rule.map_to(40), 39: Rule.keep(), 70: Rule.delete()})
    # одна совпавшая (38) — она и Write to; ответ на вопрос при этом не нужен и не используется
    out = assign_to_articulation(p, [38, 39, 70], "Snare: Center", write_to=66)
    assert out.rules == {38: Rule.map_to(38), 39: Rule.map_to(38), 70: Rule.map_to(38)}
    assert out.target_map.primary == {38}


def test_group_drop_connects_matching_numbers_only():
    group = [38, 66, 125, 40]  # ноты группы Snare цели
    p = profile({66: Rule.map_to(125), 40: Rule.delete(), 39: Rule.keep()})
    out, done = connect_same_numbers(p, [33, 38, 39, 40, 66, 70], group)
    assert done == [38, 40]
    assert out.rules == {38: Rule.map_to(38), 40: Rule.map_to(40),
                         66: Rule.map_to(125),   # уже подключена — не трогаем
                         39: Rule.keep()}        # номера нет в группе — не трогаем
    assert 33 not in out.rules and 70 not in out.rules
    assert p.rules[40] == Rule.delete()  # вход не меняется
    assert connect_same_numbers(p, [41, 43], group)[1] == []


def test_number_matches_only_notes_without_rule_with_number_in_target():
    # 33, 39, 70 — нет в цели; 38 — зачёркнута; 40 — уже подключена; 66, 41, 43 — без правила и есть в цели
    p = profile({38: Rule.delete(), 40: Rule.map_to(41)})
    assert number_matches(p) == [41, 43, 66]
    out, done, differ = match_by_number(p)
    assert done == [41, 43, 66]
    assert differ == [43]  # «Tom: Center» -> «Tom: Low»; 41 и 66 — те же имена
    assert out.rules == {38: Rule.delete(), 40: Rule.map_to(41), 41: Rule.map_to(41), 43: Rule.map_to(43),
                         66: Rule.map_to(66)}
    assert p.rules == {38: Rule.delete(), 40: Rule.map_to(41)}  # исходный профиль не меняется
    assert match_by_number(out)[1:] == ([], [])  # повторно — нечего


def test_names_differ_after_normalize_and_by_target_note_name():
    src = NoteMap("s", {1: "snare:  CENTER", 2: "Kick", 3: "Tom"})
    tgt = NoteMap("t", {1: "Snare: Center", 2: "Kick: Hit", 7: "Snare: Center", 8: "Snare: Center"})
    p = RemapProfile("p", src, tgt)
    assert not names_differ(p, 1, 1)                     # регистр и пробелы не в счёт
    assert not names_differ(p, 1, 8)                     # алиас: имя артикуляции ноты цели
    assert names_differ(p, 2, 2) and names_differ(p, 3, 7)
    assert not names_differ(p, 3, 99) and not names_differ(p, 50, 1)  # ноты нет — сравнивать нечего
    assert not names_differ(RemapProfile("p", src, None), 2, 2)
    assert names_differ(p.reversed(), 2, 2) and not names_differ(p.reversed(), 7, 1)  # ← — на reversed()


def test_match_by_number_without_maps_and_in_reverse():
    assert number_matches(RemapProfile("p", None, TGT)) == [] and match_by_number(RemapProfile("p", SRC, None))[1] == []
    # обратное направление — на reversed(): ноты цели без обратного правила, чей номер есть в исходной карте
    p = profile({38: Rule.map_to(38)})
    q = p.reversed()
    assert 38 not in number_matches(q) and number_matches(q) == [n for n in sorted(TGT.names)
                                                                   if n in SRC.names and n not in q.rules]
