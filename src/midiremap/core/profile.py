"""Профиль ремапа: исходная карта + целевая карта + явные правила (без Qt и без UI)."""
from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from typing import Any, Literal

from .legacy_map import NOTE_MAP
from .notemap import NoteMap

FORMAT_VERSION = 1

Action = Literal["map", "delete", "keep"]
ACTIONS: tuple[str, ...] = ("map", "delete", "keep")


class ProfileFormatError(ValueError):
    """Профиль не читается: не JSON, неизвестная версия формата, битые поля."""


def check_note(n: Any, what: str = "note") -> None:
    if isinstance(n, bool) or not isinstance(n, int) or not 0 <= n <= 127:
        raise ValueError(f"{what}: note number must be an integer 0..127, got {n!r}")


@dataclass(frozen=True)
class Rule:
    """Что сделать с исходной нотой: map — на ноту dst, delete — удалить, keep — оставить на том же номере."""
    action: Action
    dst: int | None = None

    def __post_init__(self) -> None:
        if self.action not in ACTIONS:
            raise ValueError(f"unknown action {self.action!r}, expected one of {ACTIONS}")
        if self.action == "map":
            check_note(self.dst, "dst")
        elif self.dst is not None:
            raise ValueError(f"dst is only allowed for the 'map' action, not for {self.action!r}")

    @classmethod
    def map_to(cls, dst: int) -> Rule:
        return cls("map", dst)

    @classmethod
    def delete(cls) -> Rule:
        return cls("delete")

    @classmethod
    def keep(cls) -> Rule:
        return cls("keep")


@dataclass
class RemapProfile:
    """Профиль ремапа. Одно правило на исходную ноту (ключ rules — исходная нота).

    Карты — ВСТРОЕННЫЕ КОПИИ (профиль самодостаточен): при создании они копируются,
    поэтому последующая правка карты в менеджере карт профиль не меняет.
    Обе карты необязательны (например, проверенной раскладки SD3 пока нет).
    """
    name: str
    source_map: NoteMap | None = None
    target_map: NoteMap | None = None
    rules: dict[int, Rule] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.source_map = copy.deepcopy(self.source_map)
        self.target_map = copy.deepcopy(self.target_map)
        self.rules = dict(self.rules)
        self.validate()

    def validate(self) -> None:
        for src, rule in self.rules.items():
            check_note(src, "src")
            if not isinstance(rule, Rule):
                raise TypeError(f"rule for note {src} must be a Rule, got {type(rule).__name__}")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        rules = []
        for src in sorted(self.rules):
            rule = self.rules[src]
            item: dict[str, Any] = {"src": src, "action": rule.action}
            if rule.action == "map":
                item["dst"] = rule.dst
            rules.append(item)
        return {
            "format": FORMAT_VERSION,
            "name": self.name,
            "source_map": _map_to_dict(self.source_map),
            "target_map": _map_to_dict(self.target_map),
            "rules": rules,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2) + "\n"

    @classmethod
    def from_dict(cls, data: Any) -> RemapProfile:
        if not isinstance(data, dict):
            raise ProfileFormatError("a profile must be a JSON object")
        if "format" not in data:
            raise ProfileFormatError("no 'format' field: this is not a MidiRemap profile")
        version = data["format"]
        if version != FORMAT_VERSION or isinstance(version, bool):
            raise ProfileFormatError(
                f"unsupported profile format version: {version!r} (supported: {FORMAT_VERSION})")
        try:
            name = data["name"]
            if not isinstance(name, str):
                raise ValueError("'name' must be a string")
            raw_rules = data.get("rules", [])
            if not isinstance(raw_rules, list):
                raise ValueError("'rules' must be a list")
            rules: dict[int, Rule] = {}
            for item in raw_rules:
                if not isinstance(item, dict):
                    raise ValueError(f"a rule must be an object: {item!r}")
                src = item["src"]
                check_note(src, "src")
                if src in rules:
                    raise ValueError(f"two rules for source note {src}")
                rules[src] = Rule(item["action"], item.get("dst"))
            return cls(
                name=name,
                source_map=_map_from_dict(data.get("source_map"), "source_map"),
                target_map=_map_from_dict(data.get("target_map"), "target_map"),
                rules=rules,
            )
        except KeyError as e:
            raise ProfileFormatError(f"required field {e.args[0]!r} is missing") from e
        except (ValueError, TypeError) as e:
            raise ProfileFormatError(f"invalid profile: {e}") from e

    @classmethod
    def from_json(cls, text: str) -> RemapProfile:
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            raise ProfileFormatError(f"profile file is not valid JSON: {e}") from e
        return cls.from_dict(data)


def _map_to_dict(m: NoteMap | None) -> dict[str, Any] | None:
    if m is None:
        return None
    return {
        "name": m.name,
        "names": {str(n): label for n, label in m.names.items()},
        "order": None if m.order is None else list(m.order),
        "extra_lines": list(m.extra_lines),
    }


def _map_from_dict(data: Any, what: str) -> NoteMap | None:
    if data is None:
        return None
    if not isinstance(data, dict):
        raise ValueError(f"'{what}' must be an object or null")
    name = data["name"]
    raw_names = data.get("names", {})
    order = data.get("order")
    extra = data.get("extra_lines", [])
    if not isinstance(name, str) or not isinstance(raw_names, dict):
        raise ValueError(f"'{what}': invalid name/names fields")
    names: dict[int, str] = {}
    for key, label in raw_names.items():
        if not (isinstance(key, str) and key.isdigit()):
            raise ValueError(f"'{what}': note key must be a number, got {key!r}")
        check_note(int(key), f"{what}.names")
        if not isinstance(label, str):
            raise ValueError(f"'{what}': name of note {key} must be a string")
        names[int(key)] = label
    # order — как в файле REAPER (там встречаются и номера вне карты), поэтому только проверка типа
    if order is not None and not (isinstance(order, list)
                                  and all(isinstance(n, int) and not isinstance(n, bool) for n in order)):
        raise ValueError(f"'{what}': 'order' must be a list of integers or null")
    if not (isinstance(extra, list) and all(isinstance(s, str) for s in extra)):
        raise ValueError(f"'{what}': 'extra_lines' must be a list of strings")
    return NoteMap(name=name, names=names, order=order, extra_lines=list(extra))


def legacy_profile() -> RemapProfile:
    """Схема GM → SD3 из первой версии программы: NOTE_MAP + явное удаление всех остальных нот.

    Это ручная схема пользователя, а НЕ встроенный шаблон (не данные плагина) — только для кода и тестов.
    """
    rules = {n: Rule.map_to(NOTE_MAP[n]) if n in NOTE_MAP else Rule.delete() for n in range(128)}
    return RemapProfile(name="GM → SD3 (legacy)", rules=rules)
