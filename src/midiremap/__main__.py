"""Точка входа: python -m midiremap  (старый Tk-интерфейс: python -m midiremap --tk)."""
from __future__ import annotations

import runpy
import sys
from pathlib import Path

# Старый Tk-UI лежит в корне репозитория (временно, до удаления на этапе 6).
TK_SCRIPT = Path(__file__).resolve().parents[2] / "MidiRemap.py"


def run_tk() -> int:
    if not TK_SCRIPT.is_file():
        print(f"Legacy Tk interface not found: {TK_SCRIPT}", file=sys.stderr)
        return 1
    runpy.run_path(str(TK_SCRIPT), run_name="__main__")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if "--tk" in args:
        return run_tk()
    from .ui.main_window import main as qt_main
    return qt_main()


if __name__ == "__main__":
    sys.exit(main())
