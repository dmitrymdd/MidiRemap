"""Настройки интерфейса между запусками (ширины колонок, свёрнутый список профилей).

INI-файл в папке хранилища (%APPDATA%\\MidiRemap\\ui.ini), а не реестр: у каждого Storage — свои настройки,
тесты с временной папкой не трогают настройки пользователя.
"""
from __future__ import annotations

from PySide6.QtCore import QSettings

from ..storage import Storage


def ui_settings(storage: Storage) -> QSettings:
    return QSettings(str(storage.root / "ui.ini"), QSettings.Format.IniFormat)


def setting_bool(settings: QSettings, key: str, default: bool = False) -> bool:
    """QSettings в INI хранит bool строкой ("true"/"false")."""
    value = settings.value(key)
    if value is None:
        return default
    return value if isinstance(value, bool) else str(value).lower() == "true"
