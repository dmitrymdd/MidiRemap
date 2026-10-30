# PyInstaller spec для пробной сборки PySide6 (этап 5). Сборка папкой (onedir).
# Запуск: .venv\Scripts\pyinstaller remap_smoke.spec --noconfirm
# Результат: dist\REMAPSmoke\REMAPSmoke.exe
#
# При переходе на настоящее приложение (этап 9) в Analysis нужно добавить данные пакета —
# встроенные шаблоны карт src/remap/templates/maps/*.json:
#   from PyInstaller.utils.hooks import collect_data_files
#   datas=collect_data_files("remap.templates")

a = Analysis(
    ["src/remap/ui/smoke.py"],
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
    name="REMAPSmoke",
    console=False,
    upx=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    name="REMAPSmoke",
    upx=False,
)

# Отладочный вариант с консолью: видны print/traceback и сообщения Qt
# (например, с QT_DEBUG_PLUGINS=1). Результат: dist\REMAPSmoke-debug\REMAPSmoke-debug.exe
exe_debug = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="REMAPSmoke-debug",
    console=True,
    upx=False,
)
coll_debug = COLLECT(
    exe_debug,
    a.binaries,
    a.datas,
    name="REMAPSmoke-debug",
    upx=False,
)
