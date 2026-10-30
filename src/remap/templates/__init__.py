"""Встроенные шаблоны карт (только чтение): данные пакета templates/maps/*.json.

Генерируются скриптом tools/build_map_templates.py из samples/maps/*.txt.
"""
from __future__ import annotations

from importlib.resources import files

from ..core.notemap import NoteMap, map_from_json

_MAPS = files(__name__) / "maps"


def list_map_templates() -> list[tuple[str, NoteMap]]:
    """(ID шаблона = имя файла без .json, карта), по алфавиту."""
    ids = sorted((f.name[:-5] for f in _MAPS.iterdir() if f.name.endswith(".json")), key=str.casefold)
    return [(i, load_map_template(i)) for i in ids]


def load_map_template(template_id: str) -> NoteMap:
    f = _MAPS / (template_id + ".json")
    if "/" in template_id or "\\" in template_id or not f.is_file():
        raise KeyError(f"no built-in map template {template_id!r}")
    return map_from_json(f.read_text(encoding="utf-8"))
