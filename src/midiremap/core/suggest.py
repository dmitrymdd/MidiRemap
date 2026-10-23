"""Подсказки сопоставления нот исходной карты с целевой (без Qt и без UI).

Только совпадение имён: точное или после normalize_name (регистр/пробелы).
Никакого нечёткого поиска (расстояние редактирования, подстроки, синонимы): ложная подсказка хуже пустой.

Подсказки в редакторе профиля (8b2d): suggestion_targets() — нота -> артикуляция цели (совпало имя);
куда они лягут и применение — по логике назначения 8b2c (assign_plan): plan_suggestions() / apply_suggested().
"""
from __future__ import annotations

import copy
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Literal

from .notemap import NoteMap, articulations, normalize_name, primary_note
from .profile import RemapProfile, Rule, assign_plan, assign_to_articulation

Kind = Literal["exact", "probable", "ambiguous", "none"]
KINDS: tuple[str, ...] = ("exact", "probable", "ambiguous", "none")


@dataclass(frozen=True)
class Suggestion:
    """Подсказка для одной исходной ноты.

    exact     — имя совпало с именем ноты dst символ в символ, probable — только после normalize_name;
                dst — основная нота
                артикуляции в целевой карте (primary_note);
    ambiguous — имя совпало, но у целевой артикуляции несколько нот и основная не выбрана: dst = None,
                target_name заполнено (пользователь выбирает ноту сам);
    none      — совпадений нет: dst = None, target_name = None.
    """
    src: int
    dst: int | None
    kind: Kind
    target_name: str | None


def suggest_rules(source_map: NoteMap, target_map: NoteMap) -> list[Suggestion]:
    """По подсказке на каждую ноту исходной карты, по возрастанию номера."""
    groups = articulations(target_map)
    out: list[Suggestion] = []
    for src in sorted(source_map.names):
        name = source_map.names[src]
        key = normalize_name(name)
        notes = groups.get(key) if key else None  # пустое имя ни с чем не сопоставляем
        if not notes:
            out.append(Suggestion(src, None, "none", None))
            continue
        dst = primary_note(target_map, name)
        if dst is None:
            out.append(Suggestion(src, None, "ambiguous", target_map.names[notes[0]]))
            continue
        # точное — по имени именно предлагаемой ноты (в целевой карте у артикуляции бывают варианты написания)
        kind: Kind = "exact" if target_map.names[dst] == name else "probable"
        out.append(Suggestion(src, dst, kind, target_map.names[dst]))
    return out


def apply_suggestions(profile: RemapProfile, suggestions: Iterable[Suggestion],
                      kinds: Iterable[str] = ("exact", "probable")) -> RemapProfile:
    """Новый профиль: добавлены правила map из подсказок выбранных видов — только для исходных нот,
    у которых правила ещё нет. Существующие правила не меняются; входной профиль не меняется.
    ambiguous и none правил не дают никогда."""
    allowed = set(kinds) & {"exact", "probable"}
    out = copy.deepcopy(profile)
    for s in suggestions:
        if s.kind in allowed and s.dst is not None and s.src not in out.rules:
            out.rules[s.src] = Rule.map_to(s.dst)
    out.validate()
    return out


# --- подсказки в редакторе профиля (логика назначения 8b2c) ---

def suggestion_targets(source_map: NoteMap, target_map: NoteMap) -> dict[int, str]:
    """Нота исходной карты -> артикуляция целевой карты (ключ normalize_name), если имя совпало
    (exact, probable или ambiguous). Ноты без совпадения не попадают."""
    return {s.src: normalize_name(s.target_name) for s in suggest_rules(source_map, target_map)
            if s.target_name is not None}


def _by_articulation(p: RemapProfile, suggested: Mapping[int, str]) -> dict[str, list[int]]:
    """Подсказки нот БЕЗ правила, по артикуляциям цели (артикуляции, которых нет в цели, пропускаются)."""
    arts = articulations(p.target_map) if p.target_map is not None else {}
    out: dict[str, list[int]] = {}
    for n in sorted(suggested):
        if n not in p.rules and suggested[n] in arts:
            out.setdefault(suggested[n], []).append(n)
    return out


def plan_suggestions(p: RemapProfile, suggested: Mapping[int, str]) -> dict[int, int | None]:
    """Куда легла бы каждая подсказка (только ноты без правила), если назначить все подсказки артикуляции
    разом (assign_plan): нота с номером среди нот артикуляции — n -> n; остальные — на Write to (выбранный
    или молча — единственная совпавшая по номеру нота). None — нужен вопрос о Write to."""
    out: dict[int, int | None] = {}
    for art, notes in _by_articulation(p, suggested).items():
        plan = assign_plan(p, notes, art)
        out.update({n: n for n in plan.same})
        out.update({n: None if plan.ask else plan.write_to for n in plan.others})
    return out


def apply_suggested(p: RemapProfile, suggested: Mapping[int, str]) -> tuple[RemapProfile, list[int]]:
    """Новый профиль: применены подсказки, для которых вопрос не нужен (plan_suggestions не None), через
    assign_to_articulation (Write to, выбранный молча, — в копию целевой карты). Подсказки, которым нужен
    выбор Write to, пропускаются. Возвращает профиль и применённые ноты (по возрастанию)."""
    out = copy.deepcopy(p)
    done: list[int] = []
    for art, notes in _by_articulation(p, suggested).items():
        plan = assign_plan(out, notes, art)
        take = list(plan.same) if plan.ask else notes
        if take:
            out = assign_to_articulation(out, take, art)
            done.extend(take)
    return out, sorted(done)
