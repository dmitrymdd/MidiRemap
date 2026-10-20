"""Подсказки сопоставления нот исходной карты с целевой (без Qt и без UI).

Только совпадение имён: точное или после normalize_name (регистр/пробелы).
Никакого нечёткого поиска (расстояние редактирования, подстроки, синонимы): ложная подсказка хуже пустой.
"""
from __future__ import annotations

import copy
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from .notemap import NoteMap, articulations, normalize_name, primary_note
from .profile import RemapProfile, Rule

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
