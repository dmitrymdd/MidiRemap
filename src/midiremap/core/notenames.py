"""Парсер и экспорт REAPER MIDINoteNames (без Qt и без UI)."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .notemap import NoteMap, articulations, primary_note

HEADER = "# MIDI note/CC name map"

_NOTE_RE = re.compile(r"^(-?\d+)\s+(.*)$")
_BARE_NUM_RE = re.compile(r"^-?\d+$")
_NO_RE = re.compile(r"^NO\s+(-?\d+)$")


@dataclass
class ParseIssue:
    line: int  # 1-based; 0 — проблема относится ко всему файлу
    message: str
    severity: Literal["warning", "error"] = "warning"


def parse_notenames(text: str, name: str) -> tuple[NoteMap, list[ParseIssue]]:
    m = NoteMap(name=name)
    issues: list[ParseIssue] = []
    order: list[tuple[int, int]] = []  # (номер строки, нота)
    seen_content = False

    for lineno, raw in enumerate(re.split(r"\r\n|\n|\r", text), start=1):
        line = raw.rstrip()
        if not line.strip():
            continue
        first = not seen_content
        seen_content = True

        if line.startswith("#"):
            if not (first and line == HEADER):
                m.extra_lines.append(line)
            continue

        no = _NO_RE.match(line)
        if no:
            order.append((lineno, int(no.group(1))))
            continue

        note = _NOTE_RE.match(line)
        if note:
            n, label = int(note.group(1)), note.group(2).strip()
            if not 0 <= n <= 127:
                issues.append(ParseIssue(lineno, f"note number {n} is out of range 0..127"))
                m.extra_lines.append(line)
                continue
            if n in m.names:
                # Допущение: при дубликате номера побеждает ПОСЛЕДНЯЯ строка.
                issues.append(ParseIssue(lineno, f"duplicate note number {n}: the last name is used"))
            m.names[n] = label
            continue

        if _BARE_NUM_RE.match(line.strip()):
            issues.append(ParseIssue(lineno, "note without a name skipped"))
            continue

        issues.append(ParseIssue(lineno, f"unrecognized line kept as is: {line!r}"))
        m.extra_lines.append(line)

    if order:
        m.order = [n for _, n in order]
        for lineno, n in order:
            if not 0 <= n <= 127:
                issues.append(ParseIssue(lineno, f"NO {n}: number is out of range 0..127"))
            elif n not in m.names:
                issues.append(ParseIssue(lineno, f"NO {n}: no such note in the map"))
    return m, issues


def load_notenames(path: str | Path) -> tuple[NoteMap, list[ParseIssue]]:
    path = Path(path)
    data = path.read_bytes()  # если файл не прочитать — исключение
    extra: list[ParseIssue] = []
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("cp1251", errors="replace")
        extra.append(ParseIssue(0, "file is not UTF-8: read as cp1251"))
    m, issues = parse_notenames(text, path.stem)
    return m, extra + issues


def primary_only_notes(m: NoteMap) -> tuple[set[int], list[str]]:
    """Ноты для экспорта «одна нота на артикуляцию»: основная или единственная.

    Возвращает (ноты для экспорта, имена пропущенных артикуляций — на нескольких нотах без единственной primary).
    """
    keep: set[int] = set()
    skipped: list[str] = []
    for notes in articulations(m).values():
        wt = primary_note(m, m.names[notes[0]])
        if wt is not None:
            keep.add(wt)
        else:
            skipped.append(m.names[notes[0]])
    return keep, skipped


def export_notenames(m: NoteMap, primary_only: bool = False) -> str:
    """Текст MIDINoteNames. primary_only — одна нота на артикуляцию (что пропущено — см. primary_only_notes);
    строки NO при этом остаются только для экспортированных нот."""
    notes = set(m.names)
    order = m.order
    if primary_only:
        notes, _ = primary_only_notes(m)
        order = None if order is None else [n for n in order if n in notes]
    lines = [HEADER]
    lines += [f"{n} {m.names[n]}" for n in sorted(notes, reverse=True)]
    lines += m.extra_lines
    if order is not None:
        lines += [f"NO {n}" for n in order]
    return "\r\n".join(lines) + "\r\n"


def save_notenames(m: NoteMap, path: str | Path, primary_only: bool = False) -> None:
    Path(path).write_bytes(export_notenames(m, primary_only).encode("utf-8"))
