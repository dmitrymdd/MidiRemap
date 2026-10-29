"""Пакетная конвертация нескольких файлов одним профилем (без Qt и без UI)."""
from __future__ import annotations

import os
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

from .convert import ConversionReport, convert
from .errors import describe_error, technical_details
from .profile import FORWARD, RemapProfile

SUFFIX = "_remapped"


def output_path_for(src: Path, output_dir: Path | None = None) -> Path:
    """Куда пишется результат: рядом с исходником или в output_dir, имя — «<имя>_remapped.mid»."""
    return (output_dir if output_dir is not None else src.parent) / (src.stem + SUFFIX + ".mid")


@dataclass
class FileResult:
    src: Path
    dst: Path
    report: ConversionReport | None = None
    error: str | None = None    # понятный текст (describe_error)
    details: str | None = None  # технические детали: тип исключения и его текст

    @property
    def ok(self) -> bool:
        return self.error is None


@dataclass
class BatchResult:
    files: list[FileResult] = field(default_factory=list)

    @property
    def succeeded(self) -> list[FileResult]:
        return [f for f in self.files if f.ok]

    @property
    def failed(self) -> list[FileResult]:
        return [f for f in self.files if not f.ok]

    @property
    def outputs(self) -> list[Path]:
        return [f.dst for f in self.succeeded]


def _key(path: Path) -> str:
    return os.path.normcase(os.path.abspath(path))


def convert_batch(sources: Iterable[Path], profile: RemapProfile, direction: str = FORWARD,
                  output_dir: Path | None = None,
                  convert_fn: Callable[..., ConversionReport] = convert) -> BatchResult:
    """Конвертирует файлы по порядку; ошибка одного файла не останавливает остальные.

    Существующий файл результата перезаписывается (как при одном файле). Исключение — конфликты внутри самой
    пачки: два результата с одним именем (файлы из разных папок при общей output_dir) или результат, совпадающий
    с другим исходником пачки, — такой файл не пишется и попадает в отчёт ошибкой (первый занявший имя пишется).
    """
    sources = list(sources)
    source_keys = {_key(s) for s in sources}
    claimed: dict[str, Path] = {}
    result = BatchResult()
    folder_error = None
    if output_dir is not None:
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            folder_error = f"Cannot create the output folder: {e}"
    for src in sources:
        dst = output_path_for(src, output_dir)
        key = _key(dst)
        error = folder_error
        if error is None and key in claimed:
            error = f"Output name collides with the result of {claimed[key].name}: {dst.name}"
        elif error is None and key in source_keys:
            error = f"Output would overwrite another source file: {dst.name}"
        if error is not None:
            result.files.append(FileResult(src, dst, error=error))
            continue
        claimed[key] = src
        try:
            report = convert_fn(src, dst, profile, direction=direction)
        except Exception as exc:  # любая ошибка файла (битый MIDI, доступ) — в отчёт, пачка продолжается
            result.files.append(FileResult(src, dst, error=describe_error(exc, src, dst),
                                           details=technical_details(exc)))
        else:
            result.files.append(FileResult(src, dst, report))
    return result
