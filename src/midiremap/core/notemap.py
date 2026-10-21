"""Карта нот: модель, проверка, JSON-формат (без Qt и без UI)."""
from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass, field
from typing import Any, Literal

MAP_FORMAT_VERSION = 1
MAP_KIND = "notemap"

Status = Literal["verified", "unverified"]
STATUSES: tuple[str, ...] = ("verified", "unverified")


class MapFormatError(ValueError):
    """JSON карты не читается: не JSON, другой kind, неизвестная версия формата, битые поля."""


@dataclass
class MapMeta:
    """Откуда раскладка и проверена ли она (для встроенных шаблонов — обязательно)."""
    source: str | None = None
    status: Status = "unverified"
    notes: str | None = None


@dataclass
class NoteMap:
    """Карта нот: номер ноты (0..127) -> имя.

    Одно имя на нескольких нотах — норма (одна артикуляция на нескольких нотах).
    primary — ноты, отмеченные как основная нота своей артикуляции (нужно при конвертации В плагин).
    """
    name: str
    names: dict[int, str] = field(default_factory=dict)
    order: list[int] | None = None  # из строк "NO <n>" (порядок строк piano roll REAPER, гипотеза)
    extra_lines: list[str] = field(default_factory=list)  # нераспознанные строки, как есть
    primary: set[int] = field(default_factory=set)
    meta: MapMeta = field(default_factory=MapMeta)


def normalize_name(s: str) -> str:
    """Для сопоставления имён: регистр, повторные пробелы, края."""
    return " ".join(s.casefold().split())


# Хвост «(артикуляция)» в конце имени: «Kick (hit)» -> «Kick».
_TRAILING_PARENS = re.compile(r"^(.*?)\s*\([^()]*\)\s*$")


def instrument_group(name: str) -> str | None:
    """Инструмент из имени ноты — ТОЛЬКО для показа строк под заголовками (не для сопоставления и подсказок).

    «Инструмент: артикуляция» -> текст до первого «:» (так названы все ноты шаблонов SD3 и EZD3);
    «Инструмент (артикуляция)» -> текст до завершающей скобки (все ноты Guitar Pro 8);
    иначе None (у имён General MIDI структуры нет — плоский список). Группы сравнивать через normalize_name.
    """
    head, colon, _ = name.partition(":")
    if colon:
        return head.strip() or None
    m = _TRAILING_PARENS.match(name.strip())
    if m:
        return m.group(1).strip() or None
    return None


# --- артикуляции и основные ноты ---

def articulations(m: NoteMap) -> dict[str, list[int]]:
    """Нормализованное имя -> ноты с этим именем (по возрастанию)."""
    groups: dict[str, list[int]] = {}
    for n in sorted(m.names):
        groups.setdefault(normalize_name(m.names[n]), []).append(n)
    return groups


def primary_note(m: NoteMap, name: str) -> int | None:
    """Основная нота артикуляции: единственная нота с этим именем или нота с флагом primary.

    None — имени нет в карте, либо нот несколько и основная не отмечена (или отмечено больше одной).
    """
    notes = articulations(m).get(normalize_name(name), [])
    if len(notes) == 1:
        return notes[0]
    flagged = [n for n in notes if n in m.primary]
    return flagged[0] if len(flagged) == 1 else None


@dataclass
class MapIssue:
    message: str
    notes: list[int] = field(default_factory=list)
    severity: Literal["warning", "error"] = "error"


def validate_map(m: NoteMap) -> list[MapIssue]:
    """В сообщениях primary называется «Write to» (термин UI).
    Ошибки: primary на несуществующей ноте, больше одной primary на артикуляцию.
    Предупреждения: артикуляция на нескольких нотах без основной (при экспорте «по одной ноте» её не будет)."""
    issues: list[MapIssue] = []
    bad = sorted(n for n in m.primary if n not in m.names)
    if bad:
        issues.append(MapIssue(f"Write to notes not in the map: {', '.join(map(str, bad))}", bad))
    for notes in articulations(m).values():
        if len(notes) < 2:
            continue
        label = m.names[notes[0]]
        flagged = [n for n in notes if n in m.primary]
        if len(flagged) > 1:
            issues.append(MapIssue(f'"{label}" has several Write to notes: {", ".join(map(str, flagged))}',
                                   flagged))
        elif not flagged:
            issues.append(MapIssue(f'"{label}" is on several notes ({", ".join(map(str, notes))}) '
                                   "and none is marked Write to", notes, "warning"))
    return issues


# --- копирование и редактирование ---

def duplicate_map(m: NoteMap, name: str, from_template: bool = False) -> NoteMap:
    """Копия карты под новым именем. meta копируется (source и status сохраняются);
    для копии встроенного шаблона в meta.notes дописывается «Based on template <имя>»."""
    c = copy.deepcopy(m)
    c.name = name
    if from_template:
        line = f"Based on template {m.name}"
        c.meta.notes = f"{c.meta.notes}\n{line}" if c.meta.notes else line
    return c


def finalize_edit(base: NoteMap, edited: NoteMap) -> NoteMap:
    """Карта для сохранения после правки base -> edited (возвращается копия, аргументы не меняются).

    - имена нот изменились (правка, добавление, удаление) -> meta.status = "unverified";
      изменились только флаги primary — статус прежний;
    - удалённые ноты убираются из order (прочие номера order — как в файле REAPER — не трогаем);
    - primary остаётся только на существующих нотах артикуляций, занимающих несколько нот.
    """
    out = copy.deepcopy(edited)
    if out.names != base.names:
        out.meta.status = "unverified"
    removed = set(base.names) - set(out.names)
    if out.order is not None and removed:
        out.order = [n for n in out.order if n not in removed]
    groups = articulations(out)
    out.primary = {n for n in out.primary
                   if n in out.names and len(groups[normalize_name(out.names[n])]) > 1}
    return out


# --- JSON ---

def map_body_to_dict(m: NoteMap) -> dict[str, Any]:
    """Поля карты без format/kind (так карта встраивается в профиль)."""
    return {
        "name": m.name,
        "names": {str(n): m.names[n] for n in sorted(m.names)},
        "primary": sorted(m.primary),
        "order": None if m.order is None else list(m.order),
        "extra_lines": list(m.extra_lines),
        "meta": {"source": m.meta.source, "status": m.meta.status, "notes": m.meta.notes},
    }


def map_body_from_dict(data: Any, what: str = "map") -> NoteMap:
    """Обратное к map_body_to_dict. Ошибки — ValueError/KeyError (вызывающий оборачивает в свой тип)."""
    if not isinstance(data, dict):
        raise ValueError(f"'{what}' must be an object or null")
    name = data["name"]
    raw_names = data.get("names", {})
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
    primary = data.get("primary", [])  # нет в старых профилях
    if not isinstance(primary, list):
        raise ValueError(f"'{what}': 'primary' must be a list of note numbers")
    for n in primary:
        check_note(n, f"{what}.primary")
    # order — как в файле REAPER (там встречаются и номера вне карты), поэтому только проверка типа
    order = data.get("order")
    if order is not None and not (isinstance(order, list)
                                  and all(isinstance(n, int) and not isinstance(n, bool) for n in order)):
        raise ValueError(f"'{what}': 'order' must be a list of integers or null")
    extra = data.get("extra_lines", [])
    if not (isinstance(extra, list) and all(isinstance(s, str) for s in extra)):
        raise ValueError(f"'{what}': 'extra_lines' must be a list of strings")
    meta = _meta_from_dict(data.get("meta"))  # нет в старых профилях
    return NoteMap(name=name, names=names, order=order, extra_lines=list(extra), primary=set(primary),
                   meta=meta)


def map_to_dict(m: NoteMap) -> dict[str, Any]:
    return {
        "format": MAP_FORMAT_VERSION,
        "kind": MAP_KIND,
        **map_body_to_dict(m),
    }


def map_to_json(m: NoteMap) -> str:
    return json.dumps(map_to_dict(m), ensure_ascii=False, indent=2) + "\n"


def map_from_dict(data: Any) -> NoteMap:
    if not isinstance(data, dict):
        raise MapFormatError("a map must be a JSON object")
    if data.get("kind") != MAP_KIND:
        raise MapFormatError(f"not a MidiRemap note map (kind = {data.get('kind')!r})")
    version = data.get("format")
    if version != MAP_FORMAT_VERSION or isinstance(version, bool):
        raise MapFormatError(f"unsupported map format version: {version!r} (supported: {MAP_FORMAT_VERSION})")
    try:
        return map_body_from_dict(data)
    except KeyError as e:
        raise MapFormatError(f"required field {e.args[0]!r} is missing") from e
    except (ValueError, TypeError) as e:
        raise MapFormatError(f"invalid map: {e}") from e


def map_from_json(text: str) -> NoteMap:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise MapFormatError(f"map file is not valid JSON: {e}") from e
    return map_from_dict(data)


def _meta_from_dict(data: Any) -> MapMeta:
    if data is None:
        return MapMeta()
    if not isinstance(data, dict):
        raise ValueError("'meta' must be an object or null")
    source, status, notes = data.get("source"), data.get("status", "unverified"), data.get("notes")
    for key, value in (("source", source), ("notes", notes)):
        if value is not None and not isinstance(value, str):
            raise ValueError(f"'meta.{key}' must be a string or null")
    if status not in STATUSES:
        raise ValueError(f"'meta.status' must be one of {STATUSES}, got {status!r}")
    return MapMeta(source=source, status=status, notes=notes)


def check_note(n: Any, what: str = "note") -> None:
    if isinstance(n, bool) or not isinstance(n, int) or not 0 <= n <= 127:
        raise ValueError(f"{what}: note number must be an integer 0..127, got {n!r}")
