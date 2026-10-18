from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class NoteMap:
    """Карта нот: номер ноты (0..127) -> имя.

    Одно имя на нескольких нотах — норма (одна артикуляция на нескольких нотах).
    """
    name: str
    names: dict[int, str] = field(default_factory=dict)
    order: list[int] | None = None  # из строк "NO <n>" (порядок строк piano roll REAPER, гипотеза)
    extra_lines: list[str] = field(default_factory=list)  # нераспознанные строки, как есть


def normalize_name(s: str) -> str:
    """Для сопоставления имён: регистр, повторные пробелы, края."""
    return " ".join(s.casefold().split())
