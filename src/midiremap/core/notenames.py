"""Парсер и экспорт REAPER MIDINoteNames (без Qt и без UI)."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .notemap import NoteMap

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


def export_notenames(m: NoteMap) -> str:
    lines = [HEADER]
    lines += [f"{n} {m.names[n]}" for n in sorted(m.names, reverse=True)]
    lines += m.extra_lines
    if m.order is not None:
        lines += [f"NO {n}" for n in m.order]
    return "\r\n".join(lines) + "\r\n"


def save_notenames(m: NoteMap, path: str | Path) -> None:
    Path(path).write_bytes(export_notenames(m).encode("utf-8"))
