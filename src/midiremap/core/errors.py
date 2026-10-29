"""Понятные сообщения об ошибках конвертации файла (без Qt): исключение → текст для пользователя + технические детали."""
from __future__ import annotations

import os
from pathlib import Path

DAMAGED = "The file is damaged or truncated"
NOT_MIDI = "Not a MIDI file"
UNSUPPORTED_TYPE = "Unsupported MIDI file type (only types 0, 1 and 2)"
NOT_FOUND = "File not found"
NO_ACCESS = "No access to the file (it may be open in another program)"
OUTPUT_FOLDER_MISSING = "Cannot write the result: the output folder does not exist"
OUTPUT_NO_ACCESS = "Cannot write the result (no access, or the file is open in another program)"
GENERIC = "Could not convert: {reason}"
REASON_MAX = 80


def _same(a, b: Path | None) -> bool:
    if a is None or b is None:
        return False
    try:
        return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))
    except (TypeError, ValueError):
        return False


def technical_details(exc: BaseException) -> str:
    """«EOFError» / «OSError: MThd not found…» — тип исключения и его текст (для окна Details)."""
    text = str(exc).strip()
    return f"{type(exc).__name__}: {text}" if text else type(exc).__name__


def describe_error(exc: BaseException, src: Path | None = None, dst: Path | None = None) -> str:
    """Текст для пользователя по исключению при конвертации src → dst.

    Узнаём: обрезанный/повреждённый файл (EOFError, плохие заголовки дорожек), не MIDI (нет «MThd»), тип файла
    не 0/1/2, нет файла / нет доступа — отдельно для исходника и для результата. Прочее — «Could not convert: …»
    с первой строкой текста исключения (или его типом)."""
    text = str(exc).strip()
    lower = text.casefold()
    if isinstance(exc, OSError) and exc.filename is not None:
        output = _same(exc.filename, dst) or (dst is not None and _same(exc.filename, dst.parent))
        if isinstance(exc, FileNotFoundError):
            return OUTPUT_FOLDER_MISSING if output else NOT_FOUND
        if isinstance(exc, (PermissionError, IsADirectoryError)):
            return OUTPUT_NO_ACCESS if output else NO_ACCESS
    if isinstance(exc, EOFError):
        return DAMAGED
    if isinstance(exc, OSError) and exc.filename is None:
        if "mthd not found" in lower:
            return NOT_MIDI
        if "mtrk" in lower or "header" in lower:
            return DAMAGED
    if isinstance(exc, ValueError):
        if "must be 0, 1 or 2" in lower:
            return UNSUPPORTED_TYPE
        if "must have exactly 1 track" in lower:
            return DAMAGED
    reason = text.splitlines()[0] if text else type(exc).__name__
    if len(reason) > REASON_MAX:
        reason = reason[:REASON_MAX - 1].rstrip() + "…"
    return GENERIC.format(reason=reason)
