"""Главное окно MidiRemap на PySide6: вкладки Convert (загрузка файла, выбор профиля, конвертация, отчёт,
вывод результата) и Maps (менеджер и редактор карт нот, ui/maps_page.py).

Запуск: python -m midiremap
Логики конвертации здесь нет — только вызов midiremap.core.convert и показ отчёта.
"""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QMimeData, QPoint, Qt, QUrl
from PySide6.QtGui import QDesktopServices, QDrag, QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QComboBox, QFileDialog, QFrame, QHBoxLayout, QLabel, QMainWindow, QMessageBox,
    QPlainTextEdit, QPushButton, QSizePolicy, QStackedWidget, QVBoxLayout, QWidget,
)

from ..core import ConversionReport, RemapProfile, convert, legacy_profile
from ..storage import Storage
from .maps_page import MapsPage
from .theme import repolish as _repolish, stylesheet

MIDI_EXTS = {".mid", ".midi"}
LEGACY_ID = None  # в комбобоксе legacy_profile() хранится с data=None, профили из хранилища — с их ID

PAGE_CONVERT, PAGE_MAPS = 0, 1

ACTION_LABELS = {"map": "remapped", "delete": "deleted", "keep": "kept as is"}


def is_midi(path: str | Path | None) -> bool:
    return bool(path) and Path(path).suffix.lower() in MIDI_EXTS and Path(path).is_file()


def midi_paths_from_mime(mime: QMimeData) -> list[Path]:
    """Локальные .mid/.midi из mime-данных (DnD или буфер обмена); иначе — путь в виде текста."""
    paths = [Path(u.toLocalFile()) for u in mime.urls() if u.isLocalFile()]
    if not paths and mime.hasText():
        paths = [Path(mime.text().strip().strip('"'))]
    return [p for p in paths if is_midi(p)]


def output_path_for(src: Path) -> Path:
    return src.with_name(src.stem + "_remapped.mid")


def format_report(report: ConversionReport) -> str:
    """Текст отчёта о конвертации для показа пользователю."""
    events = {a: 0 for a in ACTION_LABELS}
    notes = {a: 0 for a in ACTION_LABELS}
    for r in report.notes.values():
        events[r.action] += r.count
        notes[r.action] += 1
    lines = [f"{ACTION_LABELS[a].capitalize()}: {events[a]} hits ({notes[a]} notes)" for a in ACTION_LABELS]
    if report.unresolved_kept:
        lines.append("  no rule in the profile, kept: " + ", ".join(map(str, report.unresolved_kept)))
    lines.append(f"Merged duplicates (many-to-one, same tick): {report.merged} note_on, "
                 f"{report.merged_note_offs} note_off")
    lines.append(f"Overlaps of one target note on different ticks: {report.overlaps}")
    if report.orphan_note_offs:
        lines.append(f"note_off without note_on (kept): {report.orphan_note_offs}")
    if report.warnings:
        lines.append("")
        lines.append("Warnings:")
        lines.extend(f"  ⚠ {w}" for w in report.warnings)
    if report.notes:
        lines.append("")
        lines.append("Per note (source → result, hits):")
        for r in report.notes.values():
            target = "deleted" if r.action == "delete" else f"→ {r.dst}"
            origin = "" if r.origin == "profile" else f"  [{r.origin}]"
            lines.append(f"  {r.src:>3} {target:<8} ×{r.count}{origin}")
    return "\n".join(lines)


class FileCard(QFrame):
    """Карточка файла (источник или результат). Карточку результата можно вытащить в DAW/Проводник."""

    def __init__(self, title: str, placeholder: str, draggable: bool = False) -> None:
        super().__init__()
        self.setObjectName("card")
        self._title, self._placeholder = title, placeholder
        self.path: Path | None = None
        self._draggable = draggable
        self._press_pos: QPoint | None = None

        icon = QLabel("♫")
        icon.setObjectName("icon")
        self.name = QLabel(title)
        self.name.setObjectName("cardName")
        self.folder = QLabel(placeholder)
        self.folder.setObjectName("muted")
        for label in (self.name, self.folder):
            label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        text = QVBoxLayout()
        text.setSpacing(2)
        text.addWidget(self.name)
        text.addWidget(self.folder)
        row = QHBoxLayout(self)
        row.setContentsMargins(14, 10, 14, 10)
        row.addWidget(icon)
        row.addSpacing(8)
        row.addLayout(text, stretch=1)
        if draggable:
            self.drag_hint = QLabel("")
            self.drag_hint.setObjectName("hint")
            row.addWidget(self.drag_hint)

    def set_file(self, path: Path | None, ready: bool = False) -> None:
        self.path = path
        self.name.setText(path.name if path else self._title)
        self.folder.setText(str(path.parent) if path else self._placeholder)
        self.setToolTip(str(path) if path else "")
        _repolish(self, "state", "ok" if ready else "")
        if self._draggable:
            self.drag_hint.setText("⇱ drag into your DAW" if ready else "")
            self.setCursor(Qt.CursorShape.OpenHandCursor if ready else Qt.CursorShape.ArrowCursor)

    def _can_drag(self) -> bool:
        return self._draggable and self.property("state") == "ok" and self.path is not None and self.path.is_file()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._can_drag():
            self._press_pos = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if (self._press_pos is not None and event.buttons() & Qt.MouseButton.LeftButton
                and (event.position().toPoint() - self._press_pos).manhattanLength()
                >= QApplication.startDragDistance()):
            self._press_pos = None
            mime = QMimeData()
            mime.setUrls([QUrl.fromLocalFile(str(self.path))])
            drag = QDrag(self)
            drag.setMimeData(mime)
            drag.exec(Qt.DropAction.CopyAction)
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._press_pos = None
        super().mouseReleaseEvent(event)


class DropZone(QFrame):
    """Подсказка «перетащи сюда»; клик открывает диалог выбора файла. Сам drop принимает всё окно."""

    def __init__(self, on_click) -> None:
        super().__init__()
        self.setObjectName("drop")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._on_click = on_click

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self._on_click()
        super().mouseReleaseEvent(event)


class MainWindow(QMainWindow):
    def __init__(self, storage: Storage | None = None) -> None:
        super().__init__()
        self.storage = storage if storage is not None else Storage()
        self.source: Path | None = None
        self.output: Path | None = None  # готовый результат последней успешной конвертации

        self.setWindowTitle("MidiRemap")
        self.resize(900, 720)
        self.setMinimumSize(720, 560)
        self.setAcceptDrops(True)
        self.setStyleSheet(stylesheet())
        self._build_ui()
        self._bind_shortcuts()
        self.reload_profiles()

    # --- построение UI ---

    def _build_ui(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(24, 20, 24, 16)
        root.setSpacing(8)

        logo = QLabel("MR")
        logo.setObjectName("logo")
        logo.setFixedSize(44, 44)
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title = QLabel("MidiRemap")
        title.setObjectName("title")
        subtitle = QLabel("Drum MIDI note remapper")
        subtitle.setObjectName("subtitle")
        titles = QVBoxLayout()
        titles.setSpacing(0)
        titles.addWidget(title)
        titles.addWidget(subtitle)
        self.nav_convert = QPushButton("Convert")
        self.nav_maps = QPushButton("Maps")
        for i, b in enumerate((self.nav_convert, self.nav_maps)):
            b.setObjectName("navTab")
            b.setCheckable(True)
            b.setAutoExclusive(True)
            b.clicked.connect(lambda _=False, page=i: self.show_page(page))
        self.nav_convert.setChecked(True)
        head = QHBoxLayout()
        head.addWidget(logo)
        head.addSpacing(10)
        head.addLayout(titles, stretch=1)
        head.addWidget(self.nav_convert, alignment=Qt.AlignmentFlag.AlignBottom)
        head.addWidget(self.nav_maps, alignment=Qt.AlignmentFlag.AlignBottom)
        root.addLayout(head)

        self.pages = QStackedWidget()
        root.addWidget(self.pages, stretch=1)
        convert_page = QWidget()
        self.pages.addWidget(convert_page)
        self.maps_page = MapsPage(self.storage)
        self.maps_page.dirty_changed.connect(self._on_maps_dirty)
        self.pages.addWidget(self.maps_page)
        self._build_convert_page(convert_page)
        self.setCentralWidget(central)

    def _build_convert_page(self, page: QWidget) -> None:
        root = QVBoxLayout(page)
        root.setContentsMargins(0, 10, 0, 0)
        root.setSpacing(8)

        self.drop = DropZone(self.choose_file)
        arrow = QLabel("↓")
        arrow.setObjectName("icon")
        drop_title = QLabel("Drop a MIDI file here")
        drop_title.setObjectName("cardName")
        drop_hint = QLabel("or click to browse  ·  Ctrl+V to paste a copied file")
        drop_hint.setObjectName("muted")
        drop_box = QVBoxLayout(self.drop)
        drop_box.setContentsMargins(16, 14, 16, 14)
        for w in (arrow, drop_title, drop_hint):
            w.setAlignment(Qt.AlignmentFlag.AlignCenter)
            drop_box.addWidget(w)
        root.addWidget(self.drop)
        root.addSpacing(6)

        root.addWidget(self._section("REMAP PROFILE"))
        self.profile_combo = QComboBox()
        self.profile_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.reload_profiles)
        prow = QHBoxLayout()
        prow.addWidget(self.profile_combo, stretch=1)
        prow.addWidget(refresh)
        root.addLayout(prow)
        root.addSpacing(6)

        root.addWidget(self._section("SOURCE"))
        self.src_card = FileCard("Source file", "No file selected")
        root.addWidget(self.src_card)
        root.addWidget(self._section("OUTPUT"))
        self.out_card = FileCard("Output file", "Not converted yet", draggable=True)
        root.addWidget(self.out_card)
        root.addSpacing(6)

        self.convert_btn = QPushButton("Convert  →")
        self.convert_btn.setObjectName("primary")
        self.convert_btn.clicked.connect(self.convert)
        open_btn = QPushButton("Open file…")
        open_btn.clicked.connect(self.choose_file)
        folder_btn = QPushButton("Show in folder")
        folder_btn.clicked.connect(self.open_folder)
        copy_btn = QPushButton("Copy file  ⧉")
        copy_btn.clicked.connect(self.copy_output)
        actions = QHBoxLayout()
        for b in (self.convert_btn, open_btn, folder_btn):
            actions.addWidget(b)
        actions.addStretch(1)
        actions.addWidget(copy_btn)
        root.addLayout(actions)
        root.addSpacing(6)

        root.addWidget(self._section("REPORT"))
        self.report_view = QPlainTextEdit()
        self.report_view.setReadOnly(True)
        # без фокуса Ctrl+C всегда копирует файл результата; текст отчёта — через контекстное меню
        self.report_view.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.report_view.setPlaceholderText("The conversion report will appear here.")
        root.addWidget(self.report_view, stretch=1)

        self.status = QLabel("Ready. Supports .mid and .midi files.")
        self.status.setObjectName("status")
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        hint = QLabel("Enter: convert    Ctrl+V: paste file    Ctrl+C: copy output file    Esc: clear")
        hint.setObjectName("hint")
        root.addWidget(hint)

    @staticmethod
    def _section(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("section")
        return label

    def _bind_shortcuts(self) -> None:
        # горячие клавиши экрана Convert; на вкладке Maps выключены (там Enter/Ctrl+C нужны таблице)
        self._convert_shortcuts = [
            QShortcut(QKeySequence(keys), self, activated=slot)
            for keys, slot in ((QKeySequence.StandardKey.Paste, self.paste_file),
                               (QKeySequence.StandardKey.Copy, self.copy_output),
                               (Qt.Key.Key_Return, self.convert),
                               (Qt.Key.Key_Enter, self.convert),
                               (Qt.Key.Key_Escape, self.clear))]

    # --- вкладки ---

    def show_page(self, page: int) -> None:
        """Переключение вкладок. Несохранённые правки карты при этом не теряются (редактор остаётся как был)."""
        self.pages.setCurrentIndex(page)
        (self.nav_convert if page == PAGE_CONVERT else self.nav_maps).setChecked(True)
        for sc in self._convert_shortcuts:
            sc.setEnabled(page == PAGE_CONVERT)

    def _on_maps_dirty(self, dirty: bool) -> None:
        self.nav_maps.setText("Maps  ●" if dirty else "Maps")
        self.nav_maps.setToolTip("The map editor has unsaved changes" if dirty else "")

    def closeEvent(self, event) -> None:
        if self.maps_page.dirty:
            self.show_page(PAGE_MAPS)
            if not self.maps_page.maybe_leave():
                event.ignore()
                return
        super().closeEvent(event)

    # --- профили ---

    def reload_profiles(self) -> None:
        current = self.profile_combo.currentData() if self.profile_combo.count() else LEGACY_ID
        self.profile_combo.clear()
        self.profile_combo.addItem(legacy_profile().name, LEGACY_ID)
        try:
            entries, issues = self.storage.list_profiles()
        except OSError as e:
            entries, issues = [], []
            self.set_status(f"Cannot read the profiles folder: {e}", "error")
        for entry in entries:
            self.profile_combo.addItem(entry.name, entry.id)
            self.profile_combo.setItemData(self.profile_combo.count() - 1, str(entry.path),
                                           Qt.ItemDataRole.ToolTipRole)
        index = self.profile_combo.findData(current)
        self.profile_combo.setCurrentIndex(max(index, 0))
        if issues:
            names = ", ".join(i.path.name for i in issues)
            self.set_status(f"Skipped unreadable profiles ({len(issues)}): {names}", "error")

    def selected_profile(self) -> RemapProfile:
        profile_id = self.profile_combo.currentData()
        if profile_id is LEGACY_ID:
            return legacy_profile()
        return self.storage.load_profile(profile_id)

    # --- файлы ---

    def load(self, path: str | Path) -> None:
        if not is_midi(path):
            self.set_status("Choose an existing .mid or .midi file.", "error")
            return
        self.source = Path(path).resolve()
        self.output = None
        self.src_card.set_file(self.source)
        self.out_card.set_file(output_path_for(self.source))
        _repolish(self.drop, "active", "true")
        self.report_view.clear()
        self.set_status("File loaded. Click Convert or press Enter.")

    def clear(self) -> None:
        self.source = self.output = None
        self.src_card.set_file(None)
        self.out_card.set_file(None)
        _repolish(self.drop, "active", "false")
        self.report_view.clear()
        self.set_status("Cleared.")

    def choose_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Open MIDI file", "",
                                              "MIDI files (*.mid *.midi);;All files (*.*)")
        if path:
            self.load(path)

    def _accept_files(self, files: list[Path]) -> None:
        self.load(files[0])
        if len(files) > 1:
            self.set_status(f"Loaded the first of {len(files)} files. MidiRemap converts one file at a time.")

    def paste_file(self) -> None:
        files = midi_paths_from_mime(QGuiApplication.clipboard().mimeData())
        if files:
            self._accept_files(files)
        else:
            self.set_status("No MIDI file in the clipboard. Copy a file in Explorer and press Ctrl+V.", "error")

    def copy_output(self) -> None:
        if self.output is None or not self.output.is_file():
            self.set_status("Convert a file first.", "error")
            return
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(self.output))])  # на Windows Qt кладёт CF_HDROP
        mime.setText(str(self.output))
        # Проводнику: вставка = копирование (DROPEFFECT_COPY), а не перемещение
        mime.setData('application/x-qt-windows-mime;value="Preferred DropEffect"', b"\x01\x00\x00\x00")
        QGuiApplication.clipboard().setMimeData(mime)
        self.set_status("Output file copied. Paste it into a folder, or into a DAW that supports pasting files.", "ok")

    def open_folder(self) -> None:
        if self.output is None or not self.output.is_file():
            self.set_status("The output folder is available after conversion.", "error")
            return
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.output.parent))):
            self.set_status("Cannot open the output folder.", "error")

    # --- DnD внутрь окна ---

    def dragEnterEvent(self, event) -> None:
        if event.source() is None and midi_paths_from_mime(event.mimeData()):  # свой результат не принимаем
            event.acceptProposedAction()
            _repolish(self.drop, "active", "true")

    def dragLeaveEvent(self, event) -> None:
        _repolish(self.drop, "active", "true" if self.source else "false")

    def dropEvent(self, event) -> None:
        files = midi_paths_from_mime(event.mimeData())
        if files:
            event.acceptProposedAction()
            self.show_page(PAGE_CONVERT)
            self._accept_files(files)
        else:
            self.set_status("Drop an existing .mid or .midi file.", "error")

    # --- конвертация ---

    def convert(self) -> None:
        if self.source is None or not self.source.is_file():
            self.set_status("Drop a MIDI file or click Open file first.", "error")
            return
        dst = output_path_for(self.source)
        try:
            profile = self.selected_profile()
            report = convert(self.source, dst, profile)
        except Exception as exc:  # показываем любую ошибку ядра/хранилища, окно не падает
            QMessageBox.critical(self, "MidiRemap: error", f"Conversion failed:\n\n{exc}")
            self.set_status("Conversion failed.", "error")
            return
        self.output = dst
        self.out_card.set_file(dst, ready=True)
        self.report_view.setPlainText(f"Profile: {profile.name}\n\n" + format_report(report))
        warn = f" · warnings: {len(report.warnings)}" if report.warnings else ""
        self.set_status(f"Done · {dst.name}{warn}. Drag the output into your DAW or press Ctrl+C.", "ok")

    def set_status(self, text: str, state: str = "") -> None:
        self.status.setText(text)
        _repolish(self.status, "state", state)


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("MidiRemap")
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
