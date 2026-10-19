"""Хранилище пользовательских карт и профилей на диске (без Qt и без UI).

Структура: <root>/maps/*.json (карты нот), <root>/profiles/*.json (RemapProfile).
ID записи — имя файла без расширения; отображаемое имя — внутри данных.
Старые карты <root>/maps/*.txt (REAPER MIDINoteNames) читаются как legacy (имя карты = ID);
если есть .json с тем же ID, .txt скрыт. Запись — всегда .json; при перезаписи legacy .txt удаляется.
"""
from __future__ import annotations

import os
import re
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .core.notemap import NoteMap, map_from_json, map_to_json
from .core.notenames import ParseIssue, load_notenames
from .core.profile import RemapProfile

APP_DIR_NAME = "MidiRemap"
MAP_EXT = ".json"
LEGACY_MAP_EXT = ".txt"
PROFILE_EXT = ".json"
MAX_ID_LEN = 100

_INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


def default_root() -> Path:
    """%APPDATA%\\MidiRemap на Windows, иначе ~/.midiremap."""
    appdata = os.environ.get("APPDATA")
    if sys.platform == "win32" and appdata:
        return Path(appdata) / APP_DIR_NAME
    return Path.home() / ".midiremap"


def sanitize_id(name: str) -> str:
    """Имя -> допустимое в Windows имя файла (без расширения)."""
    s = _INVALID_CHARS.sub("_", name).strip()
    s = s[:MAX_ID_LEN].rstrip(" .")  # Windows молча отрезает точки и пробелы в конце
    if not s:
        return "untitled"
    if s.split(".")[0].strip().upper() in _RESERVED:  # CON, nul.txt, "COM1 .x" и т.п.
        s = "_" + s
    return s


@dataclass(frozen=True)
class Entry:
    id: str
    name: str
    path: Path
    legacy: bool = False  # карта в старом формате .txt (REAPER MIDINoteNames)


@dataclass(frozen=True)
class StorageIssue:
    path: Path
    message: str


class Storage:
    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root) if root is not None else default_root()
        self.maps_dir = self.root / "maps"
        self.profiles_dir = self.root / "profiles"

    # --- карты нот (REAPER MIDINoteNames) ---

    def list_maps(self) -> tuple[list[Entry], list[StorageIssue]]:
        entries, issues = [], []
        json_files = _files(self.maps_dir, MAP_EXT)
        json_ids = {p.stem for p in json_files}
        for path in json_files:
            try:
                m = map_from_json(path.read_text(encoding="utf-8-sig"))
            except (OSError, ValueError) as e:  # MapFormatError и UnicodeDecodeError — тоже ValueError
                issues.append(StorageIssue(path, f"cannot read map: {e}"))
                continue
            entries.append(Entry(path.stem, m.name, path))
        for path in _files(self.maps_dir, LEGACY_MAP_EXT):
            if path.stem in json_ids:
                continue
            try:
                m, _ = load_notenames(path)
            except (OSError, ValueError) as e:
                issues.append(StorageIssue(path, f"cannot read map: {e}"))
                continue
            entries.append(Entry(path.stem, m.name, path, legacy=True))
        entries.sort(key=lambda e: e.id.casefold())
        return entries, issues

    def load_map(self, map_id: str) -> tuple[NoteMap, list[ParseIssue]]:
        """JSON, если есть; иначе legacy .txt (с замечаниями парсера). Нет ни того, ни другого — FileNotFoundError."""
        path = self._path(self.maps_dir, map_id, MAP_EXT)
        if path.is_file():
            return map_from_json(path.read_text(encoding="utf-8-sig")), []
        legacy = self._path(self.maps_dir, map_id, LEGACY_MAP_EXT)
        if legacy.is_file():
            return load_notenames(legacy)
        raise FileNotFoundError(f"map not found: {map_id}")

    def save_map(self, m: NoteMap, map_id: str | None = None, overwrite: bool = False) -> str:
        map_id = sanitize_id(m.name) if map_id is None else _check_id(map_id)
        path = self.maps_dir / (map_id + MAP_EXT)
        legacy = self.maps_dir / (map_id + LEGACY_MAP_EXT)
        if legacy.exists() and not overwrite:
            raise FileExistsError(f"file already exists: {legacy}")
        _atomic_write(path, map_to_json(m).encode("utf-8"), overwrite)
        if legacy.is_file():  # карта перенесена в JSON — старый .txt больше не нужен
            legacy.unlink()
        return map_id

    def delete_map(self, map_id: str) -> None:
        """Удаляет карту (и .json, и legacy .txt с этим ID). Нет ни того, ни другого — FileNotFoundError."""
        paths = [self._path(self.maps_dir, map_id, ext) for ext in (MAP_EXT, LEGACY_MAP_EXT)]
        existing = [p for p in paths if p.is_file()]
        if not existing:
            raise FileNotFoundError(f"map not found: {map_id}")
        for p in existing:
            p.unlink()

    # --- профили ремапа (JSON) ---

    def list_profiles(self) -> tuple[list[Entry], list[StorageIssue]]:
        entries, issues = [], []
        for path in _files(self.profiles_dir, PROFILE_EXT):
            try:
                p = RemapProfile.from_json(path.read_text(encoding="utf-8-sig"))
            except (OSError, ValueError) as e:  # ProfileFormatError и UnicodeDecodeError — тоже ValueError
                issues.append(StorageIssue(path, f"cannot read profile: {e}"))
                continue
            entries.append(Entry(path.stem, p.name, path))
        return entries, issues

    def load_profile(self, profile_id: str) -> RemapProfile:
        path = self._path(self.profiles_dir, profile_id, PROFILE_EXT)
        return RemapProfile.from_json(path.read_text(encoding="utf-8-sig"))

    def save_profile(self, p: RemapProfile, profile_id: str | None = None, overwrite: bool = False) -> str:
        profile_id = sanitize_id(p.name) if profile_id is None else _check_id(profile_id)
        path = self.profiles_dir / (profile_id + PROFILE_EXT)
        _atomic_write(path, p.to_json().encode("utf-8"), overwrite)
        return profile_id

    def delete_profile(self, profile_id: str) -> None:
        self._path(self.profiles_dir, profile_id, PROFILE_EXT).unlink()

    @staticmethod
    def _path(folder: Path, entry_id: str, ext: str) -> Path:
        return folder / (_check_id(entry_id) + ext)


def _check_id(entry_id: str) -> str:
    """ID должен уже быть безопасным именем файла (в т.ч. без ../ и разделителей пути)."""
    if sanitize_id(entry_id) != entry_id:
        raise ValueError(f"invalid entry ID: {entry_id!r}")
    return entry_id


def _files(folder: Path, ext: str) -> list[Path]:
    if not folder.is_dir():
        return []
    return sorted((p for p in folder.iterdir() if p.suffix.lower() == ext and p.is_file()),
                  key=lambda p: p.name.casefold())


def _atomic_write(path: Path, data: bytes, overwrite: bool) -> None:
    """Запись через временный файл + os.replace: при сбое старый файл остаётся целым."""
    if path.exists() and not overwrite:
        raise FileExistsError(f"file already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.stem}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
