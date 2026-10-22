"""Профиль ремапа: исходная карта + целевая карта + явные правила (без Qt и без UI)."""
from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from typing import Any, Literal

from .legacy_map import NOTE_MAP
from .notemap import (
    NoteMap, articulations, check_note, instrument_group, map_body_from_dict, map_body_to_dict, normalize_name,
)

FORMAT_VERSION = 1

Action = Literal["map", "delete", "keep"]
ACTIONS: tuple[str, ...] = ("map", "delete", "keep")


class ProfileFormatError(ValueError):
    """Профиль не читается: не JSON, неизвестная версия формата, битые поля."""


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
    return None if m is None else map_body_to_dict(m)


def _map_from_dict(data: Any, what: str) -> NoteMap | None:
    return None if data is None else map_body_from_dict(data, what)


# --- проверка профиля по картам ---

# Коды ProfileIssue. NO_RULE — не ошибка, а вопрос пользователю (по умолчанию нота остаётся на месте);
# остальные — предупреждения.
SRC_NOT_IN_SOURCE = "src_not_in_source_map"      # правило для ноты, которой нет в исходной карте
DST_NOT_IN_TARGET = "dst_not_in_target_map"      # map на ноту, которой нет в целевой карте
KEEP_NOT_IN_TARGET = "keep_not_in_target_map"    # keep, а этого номера нет в целевой карте
KEEP_DIFFERENT = "keep_different_articulation"   # keep, а на этом номере в целевой карте другая артикуляция
NO_RULE = "no_rule"                              # нота исходной карты без правила


@dataclass
class ProfileIssue:
    code: str
    note: int  # исходная нота, к которой относится замечание
    message: str


def keep_issue(source_map: NoteMap | None, target_map: NoteMap | None, note: int) -> ProfileIssue | None:
    """Что не так, если оставить ноту на том же номере (явный keep или keep по умолчанию).

    None — замечаний нет или проверить не по чему (нет целевой карты; для «другой артикуляции» нужны обе)."""
    if target_map is None:
        return None
    if note not in target_map.names:
        return ProfileIssue(KEEP_NOT_IN_TARGET, note, f"note {note} is kept, but the target map has no note {note}")
    if source_map is not None and note in source_map.names:
        src_name, dst_name = source_map.names[note], target_map.names[note]
        if normalize_name(src_name) != normalize_name(dst_name):
            return ProfileIssue(KEEP_DIFFERENT, note,
                                f'note {note} is kept, but it is "{src_name}" in the source map '
                                f'and "{dst_name}" in the target map')
    return None


def validate_profile(p: RemapProfile) -> list[ProfileIssue]:
    """Замечания к правилам профиля относительно его карт, по возрастанию исходной ноты.

    Каждая проверка — только если нужная карта есть; профиль без карт замечаний не получает.
    map на неосновную ноту артикуляции с несколькими нотами — допустимо, не проверяется.
    """
    src_map, tgt_map = p.source_map, p.target_map
    issues: list[ProfileIssue] = []
    for src in sorted(p.rules):
        rule = p.rules[src]
        if src_map is not None and src not in src_map.names:
            issues.append(ProfileIssue(SRC_NOT_IN_SOURCE, src, f"rule for note {src}, which is not in the source map"))
        if rule.action == "map" and tgt_map is not None and rule.dst not in tgt_map.names:
            issues.append(ProfileIssue(DST_NOT_IN_TARGET, src,
                                       f"note {src} is mapped to {rule.dst}, which is not in the target map"))
        elif rule.action == "keep":
            issue = keep_issue(src_map, tgt_map, src)
            if issue is not None:
                issues.append(issue)
    if src_map is not None:
        issues.extend(ProfileIssue(NO_RULE, n, f'note {n} "{src_map.names[n]}" has no rule (kept by default)')
                      for n in sorted(src_map.names) if n not in p.rules)
    issues.sort(key=lambda i: i.note)  # сортировка устойчива: порядок проверок внутри ноты сохраняется
    return issues


DIFFERENT_INSTRUMENT = "!"  # на этом номере в цели другой инструмент, нет ноты или у имени нет группы
SAME_INSTRUMENT = "≈"       # тот же инструмент, другое имя — скорее всего тот же звук, но стоит проверить


@dataclass(frozen=True)
class KeepWarning:
    """Неназначенная нота, которая при keep попадёт на другой звук или на отсутствующую ноту цели."""
    note: int
    marker: str              # DIFFERENT_INSTRUMENT / SAME_INSTRUMENT
    source_name: str
    target_name: str | None  # None — в целевой карте нет такой ноты


def unassigned_keep_warnings(p: RemapProfile) -> list[KeepWarning]:
    """Для диалога сохранения: ноты исходной карты без правила, у которых keep_issue() не пуст.

    Маркер только упорядочивает и подписывает предупреждение (сначала «!», затем «≈», внутри — по номеру);
    правил не создаёт и не меняет. Сравнение инструментов — instrument_group() через normalize_name."""
    src, tgt = p.source_map, p.target_map
    if src is None:
        return []
    out: list[KeepWarning] = []
    for n in sorted(src.names):
        if n in p.rules or keep_issue(src, tgt, n) is None:
            continue
        target_name = tgt.names.get(n) if tgt is not None else None
        g_src = instrument_group(src.names[n])
        g_tgt = instrument_group(target_name) if target_name is not None else None
        same = g_src is not None and g_tgt is not None and normalize_name(g_src) == normalize_name(g_tgt)
        out.append(KeepWarning(n, SAME_INSTRUMENT if same else DIFFERENT_INSTRUMENT, src.names[n], target_name))
    out.sort(key=lambda w: (w.marker != DIFFERENT_INSTRUMENT, w.note))
    return out


def with_explicit_keeps(p: RemapProfile) -> RemapProfile:
    """Новый профиль: каждой ноте исходной карты без правила — явный keep (входной профиль не меняется).

    При сохранении профиля так фиксируется решение «оставить на месте», и конвертация спрашивает
    только о нотах, которых нет в исходной карте. Без исходной карты — просто копия."""
    out = copy.deepcopy(p)
    if out.source_map is not None:
        for n in out.source_map.names:
            out.rules.setdefault(n, Rule.keep())
    out.validate()
    return out


def with_write_to(p: RemapProfile, note: int) -> RemapProfile:
    """Новый профиль: note — Write to своей артикуляции, и все правила map на ноты этой артикуляции
    переведены на note (входной профиль не меняется).

    primary ставится во ВСТРОЕННУЮ копию целевой карты профиля (карта в хранилище не меняется) и снимается
    с прочих нот артикуляции; у артикуляции на одной ноте флаг не нужен — не ставится."""
    tgt = p.target_map
    if tgt is None or note not in tgt.names:
        raise ValueError(f"note {note} is not in the target map")
    out = copy.deepcopy(p)
    notes = articulations(out.target_map)[normalize_name(tgt.names[note])]
    if len(notes) > 1:
        out.target_map.primary.difference_update(notes)
        out.target_map.primary.add(note)
    for src, rule in out.rules.items():
        if rule.action == "map" and rule.dst in notes:
            out.rules[src] = Rule.map_to(note)
    return out


def legacy_profile() -> RemapProfile:
    """Схема GM → SD3 из первой версии программы: NOTE_MAP + явное удаление всех остальных нот.

    Это ручная схема пользователя, а НЕ встроенный шаблон (не данные плагина) — только для кода и тестов.
    """
    rules = {n: Rule.map_to(NOTE_MAP[n]) if n in NOTE_MAP else Rule.delete() for n in range(128)}
    return RemapProfile(name="GM → SD3 (legacy)", rules=rules)
