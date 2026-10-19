# PyInstaller spec для пробной сборки PySide6 (этап 5). Сборка папкой (onedir).
# Запуск: .venv\Scripts\pyinstaller midiremap_smoke.spec --noconfirm
# Результат: dist\MidiRemapSmoke\MidiRemapSmoke.exe
#
# При переходе на настоящее приложение (этап 9) в Analysis нужно добавить данные пакета —
# встроенные шаблоны карт src/midiremap/templates/maps/*.json:
#   from PyInstaller.utils.hooks import collect_data_files
#   datas=collect_data_files("midiremap.templates")

a = Analysis(
    ["src/midiremap/ui/smoke.py"],
    pathex=["src"],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "tkinterdnd2"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="MidiRemapSmoke",
    console=False,
    upx=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    name="MidiRemapSmoke",
    upx=False,
)

# Отладочный вариант с консолью: видны print/traceback и сообщения Qt
# (например, с QT_DEBUG_PLUGINS=1). Результат: dist\MidiRemapSmoke-debug\MidiRemapSmoke-debug.exe
exe_debug = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="MidiRemapSmoke-debug",
    console=True,
    upx=False,
)
coll_debug = COLLECT(
    exe_debug,
    a.binaries,
    a.datas,
    name="MidiRemapSmoke-debug",
    upx=False,
)
