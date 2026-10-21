"""Главное окно MidiRemap на PySide6: вкладки Convert (загрузка файла, выбор профиля, конвертация, отчёт,
вывод результата), Profiles (редактор профилей, ui/profiles_page.py) и Maps (менеджер и редактор карт нот,
ui/maps_page.py).

Запуск: python -m midiremap
Логики конвертации здесь нет — только вызов midiremap.core.convert и показ отчёта.
"""
from __future__ import annotations

import subprocess
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
from .profiles_page import ProfilesPage, profile_summary
from .theme import repolish as _repolish, stylesheet

MIDI_EXTS = {".mid", ".midi"}

PAGE_CONVERT, PAGE_PROFILES, PAGE_MAPS = 0, 1, 2

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


def _label(text: str, name: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName(name)
    return label


class SourceZone(QFrame):
    """Зона исходного файла. Пустая — «перетащи сюда»; с файлом — имя и папка файла.
    Клик открывает диалог выбора файла; сам drop и Ctrl+V принимает всё окно."""

    def __init__(self, on_click) -> None:
        super().__init__()
        self.setObjectName("drop")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._on_click = on_click
        self.icon = _label("↓", "icon")
        self.name = _label("", "cardName")
        self.folder = _label("", "muted")
        for w in (self.name, self.folder):
            w.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        box = QVBoxLayout(self)
        box.setContentsMargins(16, 14, 16, 14)
        box.setSpacing(2)
        for w in (self.icon, self.name, self.folder):
            w.setAlignment(Qt.AlignmentFlag.AlignCenter)
            box.addWidget(w)
        self.set_file(None)

    def set_file(self, path: Path | None) -> None:
        if path is None:
            self.icon.setText("↓")
            self.name.setText("Drop a MIDI file here")
            self.folder.setText("or click to browse  ·  Ctrl+V to paste a copied file")
        else:
            self.icon.setText("♫")
            self.name.setText(path.name)
            self.folder.setText(str(path.parent))
        self.setToolTip(f"{path}\nClick or drop to replace · Esc to clear" if path else "")
        _repolish(self, "loaded", "true" if path else "false")

    def set_active(self, active: bool) -> None:
        """Подсветка во время перетаскивания файла над окном."""
        _repolish(self, "active", "true" if active else "false")

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self._on_click()
        super().mouseReleaseEvent(event)


class OutputCard(QFrame):
    """Карточка результата: клик — показать файл в Проводнике, перетаскивание — в DAW/Проводник.
    Клик от перетаскивания отличается стандартным порогом startDragDistance."""

    def __init__(self, on_click) -> None:
        super().__init__()
        self.setObjectName("card")
        self._on_click = on_click
        self.path: Path | None = None
        self.ready = False
        self._press_pos: QPoint | None = None
        self.name = _label("Output file", "cardName")
        self.folder = _label("Not converted yet", "muted")
        for label in (self.name, self.folder):
            label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        text = QVBoxLayout()
        text.setSpacing(2)
        text.addWidget(self.name)
        text.addWidget(self.folder)
        row = QHBoxLayout(self)
        row.setContentsMargins(14, 10, 14, 10)
        row.addWidget(_label("♫", "icon"))
        row.addSpacing(8)
        row.addLayout(text, stretch=1)
        self.set_file(None)

    def set_file(self, path: Path | None, ready: bool = False) -> None:
        """path — где будет (или уже лежит) результат; ready — файл готов (можно открыть и перетащить)."""
        self.path, self.ready = path, ready
        self.name.setText(path.name if path else "Output file")
        self.folder.setText(str(path.parent) if path else "Not converted yet")
        self.setToolTip(f"{path}\nClick to show in folder · drag into your DAW" if ready else "")
        _repolish(self, "state", "ok" if ready else "off")
        for label in self.findChildren(QLabel):  # цвет подписей зависит от state карточки
            label.style().unpolish(label)
            label.style().polish(label)
        self.setCursor(Qt.CursorShape.PointingHandCursor if ready else Qt.CursorShape.ArrowCursor)

    def _available(self) -> bool:
        return self.ready and self.path is not None and self.path.is_file()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._available():
            self._press_pos = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if (self._press_pos is not None and event.buttons() & Qt.MouseButton.LeftButton
                and (event.position().toPoint() - self._press_pos).manhattanLength()
                >= QApplication.startDragDistance()):
            self._press_pos = None  # это перетаскивание, а не клик
            mime = QMimeData()
            mime.setUrls([QUrl.fromLocalFile(str(self.path))])
            drag = QDrag(self)
            drag.setMimeData(mime)
            drag.exec(Qt.DropAction.CopyAction)
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        clicked = self._press_pos is not None and event.button() == Qt.MouseButton.LeftButton
        self._press_pos = None
        super().mouseReleaseEvent(event)
        if clicked and self.rect().contains(event.position().toPoint()):
            self._on_click()


class MainWindow(QMainWindow):
    def __init__(self, storage: Storage | None = None) -> None:
        super().__init__()
        self.storage = storage if storage is not None else Storage()
        self.source: Path | None = None
        self.output: Path | None = None  # готовый результат последней успешной конвертации
        self._seed_error = ""
        try:  # первый запуск: схема первой версии — обычный профиль (удалённый не вернётся)
            self.storage.seed_profiles([legacy_profile()])
        except OSError as e:
            self._seed_error = f"Cannot create the profiles folder: {e}"

        self.setWindowTitle("MidiRemap")
        self.resize(980, 760)
        self.setMinimumSize(760, 580)
        self.setAcceptDrops(True)
        self.setStyleSheet(stylesheet())
        self._build_ui()
        self._bind_shortcuts()
        self.reload_profiles()
        if self._seed_error:
            self.set_status(self._seed_error, "error")

    # --- построение UI ---

    def _build_ui(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(24, 20, 24, 16)
        root.setSpacing(8)

        logo = _label("MR", "logo")
        logo.setFixedSize(44, 44)
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        titles = QVBoxLayout()
        titles.setSpacing(0)
        titles.addWidget(_label("MidiRemap", "title"))
        titles.addWidget(_label("Drum MIDI note remapper", "subtitle"))
        self.nav_convert = QPushButton("Convert")
        self.nav_profiles = QPushButton("Profiles")
        self.nav_maps = QPushButton("Maps")
        head = QHBoxLayout()
        head.addWidget(logo)
        head.addSpacing(10)
        head.addLayout(titles, stretch=1)
        for i, b in enumerate((self.nav_convert, self.nav_profiles, self.nav_maps)):
            b.setObjectName("navTab")
            b.setCheckable(True)
            b.setAutoExclusive(True)
            b.clicked.connect(lambda _=False, page=i: self.show_page(page))
            head.addWidget(b, alignment=Qt.AlignmentFlag.AlignBottom)
        self.nav_convert.setChecked(True)
        root.addLayout(head)

        self.pages = QStackedWidget()
        root.addWidget(self.pages, stretch=1)
        convert_page = QWidget()
        self.pages.addWidget(convert_page)
        self.profiles_page = ProfilesPage(self.storage)
        self.profiles_page.dirty_changed.connect(
            lambda d: self._mark_dirty(self.nav_profiles, "Profiles", d, "The profile editor has unsaved changes"))
        self.profiles_page.profiles_changed.connect(self.reload_profiles)
        self.pages.addWidget(self.profiles_page)
        self.maps_page = MapsPage(self.storage)
        self.maps_page.dirty_changed.connect(
            lambda d: self._mark_dirty(self.nav_maps, "Maps", d, "The map editor has unsaved changes"))
        self.pages.addWidget(self.maps_page)
        self._build_convert_page(convert_page)
        self.setCentralWidget(central)

    def _build_convert_page(self, page: QWidget) -> None:
        root = QVBoxLayout(page)
        root.setContentsMargins(0, 10, 0, 0)
        root.setSpacing(8)

        self.drop = SourceZone(self.choose_file)
        root.addWidget(self.drop)
        root.addSpacing(6)

        root.addWidget(self._section("REMAP PROFILE"))
        self.profile_stack = QStackedWidget()
        self.profile_stack.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        chooser = QWidget()
        self.profile_combo = QComboBox()
        self.profile_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.profile_combo.currentIndexChanged.connect(self._on_profile_changed)
        self.edit_profile_btn = QPushButton("Edit")
        self.edit_profile_btn.setToolTip("Open this profile in the Profiles tab")
        self.edit_profile_btn.clicked.connect(self.edit_selected_profile)
        prow = QHBoxLayout()
        prow.setContentsMargins(0, 0, 0, 0)
        prow.addWidget(self.profile_combo, stretch=1)
        prow.addWidget(self.edit_profile_btn)
        self.profile_summary = _label("", "muted")
        chooser_box = QVBoxLayout(chooser)
        chooser_box.setContentsMargins(0, 0, 0, 0)
        chooser_box.setSpacing(4)
        chooser_box.addLayout(prow)
        chooser_box.addWidget(self.profile_summary)
        empty = QWidget()
        self.empty_label = _label("No remap profiles yet — create one in the Profiles tab", "muted")
        go = QPushButton("Go to Profiles")
        go.clicked.connect(lambda: self.show_page(PAGE_PROFILES))
        erow = QHBoxLayout(empty)
        erow.setContentsMargins(0, 0, 0, 0)
        erow.addWidget(self.empty_label, stretch=1)
        erow.addWidget(go)
        self.profile_stack.addWidget(chooser)
        self.profile_stack.addWidget(empty)
        root.addWidget(self.profile_stack)
        root.addSpacing(6)

        root.addWidget(self._section("OUTPUT"))
        self.out_card = OutputCard(self.open_folder)
        root.addWidget(self.out_card)
        root.addSpacing(6)

        self.convert_btn = QPushButton("Convert  →")
        self.convert_btn.setObjectName("primary")
        self.convert_btn.setToolTip("Convert (Enter)")
        self.convert_btn.clicked.connect(self.convert)
        self.copy_btn = QPushButton("Copy file  ⧉")
        self.copy_btn.setToolTip("Copy file (Ctrl+C)")
        self.copy_btn.clicked.connect(self.copy_output)
        actions = QHBoxLayout()
        actions.addWidget(self.convert_btn)
        actions.addStretch(1)
        actions.addWidget(self.copy_btn)
        root.addLayout(actions)
        root.addSpacing(6)

        root.addWidget(self._section("REPORT"))
        self.report_view = QPlainTextEdit()
        self.report_view.setReadOnly(True)
        # без фокуса Ctrl+C всегда копирует файл результата; текст отчёта — через контекстное меню
        self.report_view.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.report_view.setPlaceholderText("The conversion report will appear here.")
        root.addWidget(self.report_view, stretch=1)

        self.status = QLabel("Supports .mid and .midi files.")
        self.status.setObjectName("status")
        self.status.setWordWrap(True)
        root.addWidget(self.status)

    @staticmethod
    def _section(text: str) -> QLabel:
        return _label(text, "section")

    def _bind_shortcuts(self) -> None:
        # горячие клавиши экрана Convert; на других вкладках выключены (там Enter/Ctrl+C нужны таблицам)
        self._convert_shortcuts = [
            QShortcut(QKeySequence(keys), self, activated=slot)
            for keys, slot in ((QKeySequence.StandardKey.Paste, self.paste_file),
                               (QKeySequence.StandardKey.Copy, self.copy_output),
                               (Qt.Key.Key_Return, self.convert),
                               (Qt.Key.Key_Enter, self.convert),
                               (Qt.Key.Key_Escape, self.clear))]

    # --- вкладки ---

    def show_page(self, page: int) -> None:
        """Переключение вкладок. Несохранённые правки карты и профиля при этом не теряются."""
        self.pages.setCurrentIndex(page)
        (self.nav_convert, self.nav_profiles, self.nav_maps)[page].setChecked(True)
        for sc in self._convert_shortcuts:
            sc.setEnabled(page == PAGE_CONVERT)

    @staticmethod
    def _mark_dirty(button: QPushButton, text: str, dirty: bool, tip: str) -> None:
        button.setText(f"{text}  ●" if dirty else text)
        button.setToolTip(tip if dirty else "")

    def closeEvent(self, event) -> None:
        for page_index, page in ((PAGE_PROFILES, self.profiles_page), (PAGE_MAPS, self.maps_page)):
            if page.dirty:
                self.show_page(page_index)
                if not page.maybe_leave():
                    event.ignore()
                    return
        super().closeEvent(event)

    # --- профили ---

    def reload_profiles(self) -> None:
        """Список профилей из хранилища (вызывается и при изменениях на вкладке Profiles)."""
        current = self.profile_combo.currentData()
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        try:
            entries, issues = self.storage.list_profiles()
        except OSError as e:
            entries, issues = [], []
            self.set_status(f"Cannot read the profiles folder: {e}", "error")
        for entry in entries:
            self.profile_combo.addItem(entry.name, entry.id)
            self.profile_combo.setItemData(self.profile_combo.count() - 1, str(entry.path),
                                           Qt.ItemDataRole.ToolTipRole)
        index = self.profile_combo.findData(current) if current is not None else -1
        self.profile_combo.setCurrentIndex(max(index, 0) if entries else -1)
        self.profile_combo.blockSignals(False)
        self.profile_stack.setCurrentIndex(0 if entries else 1)
        self.convert_btn.setEnabled(bool(entries))
        self._on_profile_changed()
        if issues:
            names = ", ".join(i.path.name for i in issues)
            self.set_status(f"Skipped unreadable profiles ({len(issues)}): {names}", "error")

    def _on_profile_changed(self, *_) -> None:
        profile_id = self.profile_combo.currentData()
        if profile_id is None:
            self.profile_summary.setText("")
            return
        try:
            text = profile_summary(self.storage.load_profile(profile_id))
        except (OSError, ValueError) as e:
            text = f"Cannot read the profile: {e}"
        self.profile_summary.setText(text)

    def selected_profile(self) -> RemapProfile:
        profile_id = self.profile_combo.currentData()
        if profile_id is None:
            raise ValueError("no remap profile selected: create one in the Profiles tab")
        return self.storage.load_profile(profile_id)

    def edit_selected_profile(self) -> None:
        profile_id = self.profile_combo.currentData()
        self.show_page(PAGE_PROFILES)
        if profile_id is not None:
            self.profiles_page.select(profile_id)

    # --- файлы ---

    def load(self, path: str | Path) -> None:
        if not is_midi(path):
            self.set_status("Choose an existing .mid or .midi file.", "error")
            return
        self.source = Path(path).resolve()
        self.output = None
        self.drop.set_file(self.source)
        self.out_card.set_file(output_path_for(self.source))
        self.report_view.clear()
        self.set_status("File loaded. Click Convert or press Enter.")

    def clear(self) -> None:
        self.source = self.output = None
        self.drop.set_file(None)
        self.out_card.set_file(None)
        self.report_view.clear()
        self.set_status("Cleared.")

    def choose_file(self) -> None:
        start = str(self.source.parent) if self.source else ""
        path, _ = QFileDialog.getOpenFileName(self, "Open MIDI file", start,
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
        """Показать файл результата в Проводнике (клик по карточке результата)."""
        if self.output is None or not self.output.is_file():
            self.set_status("The output file is available after conversion.", "error")
            return
        if not self.reveal_in_explorer(self.output):
            self.set_status("Cannot open the output folder.", "error")

    def reveal_in_explorer(self, path: Path) -> bool:
        """Открыть папку с выделенным файлом (на Windows); в других ОС — просто папку. Тесты подменяют."""
        if sys.platform == "win32":
            try:
                subprocess.Popen(["explorer", f"/select,{path}"])
                return True
            except OSError:
                pass
        return QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))

    # --- DnD внутрь окна ---

    def dragEnterEvent(self, event) -> None:
        if event.source() is None and midi_paths_from_mime(event.mimeData()):  # свой результат не принимаем
            event.acceptProposedAction()
            self.drop.set_active(True)

    def dragLeaveEvent(self, event) -> None:
        self.drop.set_active(False)

    def dropEvent(self, event) -> None:
        self.drop.set_active(False)
        files = midi_paths_from_mime(event.mimeData())
        if files:
            event.acceptProposedAction()
            self.show_page(PAGE_CONVERT)
            self._accept_files(files)
        else:
            self.set_status("Drop an existing .mid or .midi file.", "error")

    # --- конвертация ---

    def convert(self) -> None:
        if self.profile_combo.currentData() is None:
            self.set_status("Create a remap profile in the Profiles tab first.", "error")
            return
        if self.source is None or not self.source.is_file():
            self.set_status("Drop a MIDI file or click the area above to choose one.", "error")
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
        self.set_status(f"Converted: {dst.name}", "ok")

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
