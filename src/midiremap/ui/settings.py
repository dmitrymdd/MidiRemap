"""Настройки интерфейса между запусками (ширины колонок, направление конвертации).

INI-файл в папке хранилища (%APPDATA%\\MidiRemap\\ui.ini), а не реестр: у каждого Storage — свои настройки,
тесты с временной папкой не трогают настройки пользователя.
"""
from __future__ import annotations

from PySide6.QtCore import QSettings

from ..storage import Storage


def ui_settings(storage: Storage) -> QSettings:
    return QSettings(str(storage.root / "ui.ini"), QSettings.Format.IniFormat)
