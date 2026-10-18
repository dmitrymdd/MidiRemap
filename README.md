# MidiRemap

Конвертер барабанных MIDI-партий из одной раскладки нот в другую
(например, Guitar Pro 8 / General MIDI → Superior Drummer 3, EZdrummer 3 и другие VST).

> Проект в ранней разработке. Ядро конвертации вынесено в пакет `midiremap.core`, UI пока старый (Tkinter) с жёстко заданной схемой GM → SD3.

## Запуск (Windows)

```
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m pip install -e .
.venv\Scripts\python MidiRemap.py
```

## Структура

- `MidiRemap.py` — текущее приложение (Tkinter).
- `src/midiremap/core/` — ядро конвертации без UI (`convert.py`, временная карта `legacy_map.py`).
- `tests/` — тесты (`pytest`).
- `samples/maps/` — карты имён нот в формате REAPER `MIDINoteNames`.
- `samples/midi/` — примеры барабанных MIDI для тестов.
- `samples/sd3_presets/` — примеры пресетов MIDI In/E-Drums из Superior Drummer 3.
- `CLAUDE.md` — контекст проекта и принятые решения.
