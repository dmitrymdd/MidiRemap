r"""Генерирует встроенные шаблоны карт src/midiremap/templates/maps/*.json из samples/maps/*.txt.

Запуск (из корня репозитория): .venv\Scripts\python tools\build_map_templates.py
Метаданные — только по фактам из CLAUDE.md. Флаги primary не ставятся: исходных данных для них нет.
tests/test_templates.py проверяет, что файлы шаблонов совпадают с результатом этого скрипта.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from midiremap.core.notemap import MapMeta, NoteMap, map_to_json
from midiremap.core.notenames import load_notenames

SAMPLES = ROOT / "samples" / "maps"
OUT = ROOT / "src" / "midiremap" / "templates" / "maps"

# имя шаблона -> (файл в samples/maps, метаданные)
TEMPLATES: dict[str, tuple[str, MapMeta]] = {
    "Superior Drummer 3": ("Superior Drummer 3.txt", MapMeta(
        source='Superior Drummer 3 core library, default preset. Transcribed from the SD3 '
               '"MIDI Mapping Keys" view.',
        status="verified",
    )),
    "EZdrummer 3": ("EZdrummer 3.txt", MapMeta(
        source='EZdrummer 3 library loaded inside Superior Drummer 3, default preset. Transcribed from the SD3 '
               '"MIDI Mapping Keys" view.',
        status="verified",
        notes="This is the layout of the EZdrummer 3 library inside SD3, not of the EZdrummer 3 plugin itself.",
    )),
    "General MIDI": ("General_MIDI_GM1.txt", MapMeta(status="verified")),
    "Guitar Pro 8": ("Guitar_Pro_8.txt", MapMeta(status="verified")),
}


def build() -> dict[str, str]:
    """Имя файла шаблона -> его JSON-текст."""
    result: dict[str, str] = {}
    for name, (sample, meta) in TEMPLATES.items():
        parsed, issues = load_notenames(SAMPLES / sample)
        if issues:
            raise ValueError(f"{sample}: {issues}")
        m = NoteMap(name=name, names=parsed.names, order=parsed.order,
                    extra_lines=parsed.extra_lines, meta=meta)
        result[name + ".json"] = map_to_json(m)
    return result


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for filename, text in build().items():
        (OUT / filename).write_bytes(text.encode("utf-8"))
        print(f"written {OUT / filename}")


if __name__ == "__main__":
    main()
