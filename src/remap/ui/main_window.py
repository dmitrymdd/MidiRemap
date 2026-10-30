"""Главное окно REMAP на PySide6: вкладки Convert (загрузка файла, выбор профиля, конвертация, отчёт,
вывод результата), Profiles (редактор профилей, ui/profiles_page.py) и Maps (менеджер и редактор карт нот,
ui/maps_page.py).

Запуск: python -m remap
Логики конвертации здесь нет — только вызов remap.core.convert и показ отчёта.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QMimeData, QPoint, Qt, QUrl
from PySide6.QtGui import QDesktopServices, QDrag, QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QDialog, QDialogButtonBox, QFileDialog, QFrame, QHBoxLayout, QLabel, QMainWindow, QMessageBox,
    QPlainTextEdit, QPushButton, QScrollArea, QSizePolicy, QStackedWidget, QVBoxLayout, QWidget,
)

from ..core import ConversionReport, FileResult, RemapProfile, convert_batch, legacy_profile, output_path_for
from ..core.profile import FORWARD, REVERSE
from ..storage import Storage
from .maps_page import MapsPage
from .profiles_page import SWAP_TEXT, SWAP_TIP, ProfilesPage, profile_summary
from .settings import ui_settings
from .combo import ComboBox
from .metal import MetalBody
from .theme import load_fonts, stylesheet
from .theme import repolish as _repolish

MIDI_EXTS = {".mid", ".midi"}

PAGE_CONVERT, PAGE_PROFILES, PAGE_MAPS = 0, 1, 2

DIRECTION_KEY = "convert/direction"  # ui.ini: направление конвертации, общее для всех профилей


def is_midi(path: str | Path | None) -> bool:
    return bool(path) and Path(path).suffix.lower() in MIDI_EXTS and Path(path).is_file()


def expand_midi_paths(paths: list[Path]) -> list[Path]:
    """Файлы .mid/.midi из списка; папка заменяется своими .mid/.midi верхнего уровня (без рекурсии), по имени."""
    files: list[Path] = []
    for p in paths:
        if p.is_dir():
            try:
                files.extend(sorted((c for c in p.iterdir() if is_midi(c)), key=lambda c: c.name.casefold()))
            except OSError:
                continue
        elif is_midi(p):
            files.append(p)
    return files


def midi_paths_from_mime(mime: QMimeData) -> list[Path]:
    """Локальные .mid/.midi (и содержимое папок) из mime-данных (DnD или буфер обмена); иначе — пути в тексте."""
    paths = [Path(u.toLocalFile()) for u in mime.urls() if u.isLocalFile()]
    if not paths and mime.hasText():
        paths = [Path(line.strip().strip('"')) for line in mime.text().splitlines() if line.strip()]
    return expand_midi_paths(paths)


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" + ("" if n == 1 else "s")


def _counts(hits: int, notes: int) -> str:
    return f"{_plural(hits, 'hit')} ({_plural(notes, 'note')})"


def format_report(report: ConversionReport) -> str:
    """Полный текст отчёта. hits — note_on, notes — различные номера нот; категории: moved (номер изменился),
    unchanged (тот же номер — по правилу или без правила), deleted."""
    t = report.totals()
    lines = [f"Total: {_counts(t.hits, t.notes)}",
             f"  Moved: {_counts(t.moved.hits, t.moved.notes)}",
             f"  Unchanged: {_counts(t.unchanged.hits, t.unchanged.notes)}",
             f"  Deleted: {_counts(t.deleted.hits, t.deleted.notes)}"]
    if report.unresolved_kept:
        lines.append("  no rule in the profile, unchanged: " + ", ".join(map(str, report.unresolved_kept)))
    lines.append(f"Merged duplicates (many-to-one, same tick): {_plural(report.merged, 'hit')}, "
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


def report_summary(report: ConversionReport) -> str:
    """Итог одной строкой в той же терминологии, что и format_report; предупреждения — только если есть."""
    t = report.totals()
    w = len(report.warnings)
    text = f"{_plural(t.hits, 'hit')} · {t.moved.hits} moved · {t.unchanged.hits} unchanged · {t.deleted.hits} deleted"
    return text + (f" · {_plural(w, 'warning')}" if w else "")


def result_line(res: FileResult) -> str:
    """Строка результата под именем файла: «✓ 52 hits · …» или «✗ <первая строка ошибки>»."""
    if res.ok:
        return f"✓ {report_summary(res.report)}"
    error = (res.error or "").strip()
    return f"✗ {error.splitlines()[0] if error else 'Failed'}"


def result_details(res: FileResult, head: str = "") -> str:
    """Полный текст для окна Details: отчёт (с заголовком «Profile: …») или ошибка + технические детали."""
    if res.ok:
        return head + format_report(res.report)
    text = (res.error or "Failed").strip()
    return f"{text}\n\nTechnical details:\n{res.details}" if res.details else text


def batch_summary(ok: int, failed: int) -> str:
    """«3 files converted, 1 failed»."""
    text = f"{_plural(ok, 'file')} converted"
    return text + (f", {failed} failed" if failed else "")


def _label(text: str, name: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName(name)
    return label


class SourceZone(QFrame):
    """Зона исходных файлов. Пустая — «перетащи сюда»; один файл — имя и папка; несколько — компактный список
    (имя и кнопка удаления, «Clear all»). После конвертации у каждого файла (и у одного) — строка результата
    (result_line: ✓ итог / ✗ ошибка) и «Details» (полный отчёт в окне). Клик открывает диалог выбора файлов;
    сам drop и Ctrl+V принимает всё окно."""

    ROW_H, RESULT_ROW_H = 26, 44  # строка списка; с результатом под именем
    LIST_MAX_H = 4 * RESULT_ROW_H + 2  # длиннее — прокрутка внутри списка

    def __init__(self, on_click, on_remove=None, on_clear=None, on_details=None) -> None:
        super().__init__()
        self.setObjectName("drop")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._on_click = on_click
        self._on_remove = on_remove or (lambda path: None)
        self._on_clear = on_clear or (lambda: None)
        self._on_details = on_details or (lambda path: None)
        self.paths: list[Path] = []
        self.results: dict[Path, FileResult] = {}
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
        # один файл: строка результата и Details под папкой
        self.single = QWidget()
        self.single_result, self.single_details = self._result_widgets(lambda: self._details_of_single())
        single = QHBoxLayout(self.single)
        single.setContentsMargins(0, 4, 0, 0)
        single.addStretch(1)
        single.addWidget(self.single_result)
        single.addWidget(self.single_details)
        single.addStretch(1)
        box.addWidget(self.single)
        # несколько файлов: заголовок «N files · Clear all» и список строк с кнопками удаления
        self.files_box = QWidget()
        self.count = _label("", "cardName")
        self.clear_btn = QPushButton("Clear all")
        self.clear_btn.setObjectName("link")
        self.clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clear_btn.setToolTip("Remove all files (Esc)")
        self.clear_btn.clicked.connect(lambda: self._on_clear())
        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.addWidget(self.count, stretch=1)
        head.addWidget(self.clear_btn)
        self.rows = QWidget()
        self.rows_box = QVBoxLayout(self.rows)
        self.rows_box.setContentsMargins(0, 0, 0, 0)
        self.rows_box.setSpacing(0)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setWidget(self.rows)
        files = QVBoxLayout(self.files_box)
        files.setContentsMargins(0, 0, 0, 0)
        files.setSpacing(4)
        files.addLayout(head)
        files.addWidget(self.scroll)
        box.addWidget(self.files_box)
        self.set_files([])

    def _result_widgets(self, on_details) -> tuple[QLabel, QPushButton]:
        result = _label("", "status")
        result.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        details = QPushButton("Details")
        details.setObjectName("link")
        details.setCursor(Qt.CursorShape.PointingHandCursor)
        details.setToolTip("Show the full report")
        details.clicked.connect(lambda _=False: on_details())
        return result, details

    def _details_of_single(self) -> None:
        if self.paths:
            self._on_details(self.paths[0])

    @staticmethod
    def _show_result(label: QLabel, details: QPushButton, res: FileResult | None) -> None:
        label.setText(result_line(res) if res is not None else "")
        label.setToolTip("" if res is None or res.ok else (res.error or ""))
        _repolish(label, "state", "" if res is None else "ok" if res.ok else "error")
        for w in (label, details):
            w.setVisible(res is not None)

    def set_files(self, paths: list[Path], results: dict[Path, FileResult] | None = None) -> None:
        """Список файлов и (после конвертации) их результаты."""
        self.paths, self.results = list(paths), dict(results or {})
        many = len(paths) > 1
        self.files_box.setVisible(many)
        for w in (self.icon, self.name, self.folder):
            w.setVisible(not many)
        self.single.setVisible(len(paths) == 1 and paths[0] in self.results)
        if not paths:
            self.icon.setText("↓")
            self.name.setText("Drop a MIDI file here")
            self.folder.setText("or click to browse  ·  Ctrl+V to paste a copied file")
        elif not many:
            self.icon.setText("♫")
            self.name.setText(paths[0].name)
            self.folder.setText(str(paths[0].parent))
            self._show_result(self.single_result, self.single_details, self.results.get(paths[0]))
        else:
            self.count.setText(f"{len(paths)} files")
            while self.rows_box.count():
                item = self.rows_box.takeAt(0)
                if item.widget() is not None:  # прежняя строка — скрыть сразу (удалится в цикле событий)
                    item.widget().hide()
                    item.widget().deleteLater()
            height = 0
            for path in paths:
                row = self._row(path)
                height += row.height()
                self.rows_box.addWidget(row)
            self.scroll.setFixedHeight(min(height, self.LIST_MAX_H))
        self.setToolTip((f"{paths[0]}\n" if len(paths) == 1 else "")
                        + "Click or drop to add files · Esc to clear" if paths else "")
        _repolish(self, "loaded", "true" if paths else "false")
        self.updateGeometry()

    def row_widgets(self) -> list[QWidget]:
        """Строки списка (несколько файлов) в порядке файлов."""
        return [self.rows_box.itemAt(i).widget() for i in range(self.rows_box.count())]

    def _row(self, path: Path) -> QWidget:
        res = self.results.get(path)
        row = QWidget()
        row.setFixedHeight(self.RESULT_ROW_H if res is not None else self.ROW_H)
        row.name = name = _label(path.name, "muted")
        name.setToolTip(str(path))
        name.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        remove = QPushButton("✕")
        remove.setObjectName("remove")
        remove.setFixedSize(24, 22)
        remove.setCursor(Qt.CursorShape.PointingHandCursor)
        remove.setToolTip("Remove from the list")
        remove.clicked.connect(lambda _=False, p=path: self._on_remove(p))
        row.result, row.details = self._result_widgets(lambda p=path: self._on_details(p))
        self._show_result(row.result, row.details, res)
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.addWidget(name, stretch=1)
        top.addWidget(remove)
        bottom = QHBoxLayout()
        bottom.setContentsMargins(0, 0, 28, 0)
        bottom.addWidget(row.result, stretch=1)
        bottom.addWidget(row.details)
        box = QVBoxLayout(row)
        box.setContentsMargins(2, 0, 2, 0)
        box.setSpacing(0)
        box.addLayout(top)
        if res is not None:
            box.addLayout(bottom)
        return row

    def set_active(self, active: bool) -> None:
        """Подсветка во время перетаскивания файла над окном."""
        _repolish(self, "active", "true" if active else "false")

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self._on_click()
        super().mouseReleaseEvent(event)


class OutputCard(QFrame):
    """Карточка результата: клик — показать файл в Проводнике, перетаскивание — в DAW/Проводник (все файлы).
    Клик от перетаскивания отличается стандартным порогом startDragDistance."""

    def __init__(self, on_click) -> None:
        super().__init__()
        self.setObjectName("card")
        self._on_click = on_click
        self.paths: list[Path] = []
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
        self.set_files([])

    @property
    def path(self) -> Path | None:
        return self.paths[0] if self.paths else None

    def set_files(self, paths: list[Path], ready: bool = False, where: str = "") -> None:
        """Несколько файлов — «N files» и where (папка результатов); один — имя и папка файла."""
        self.paths, self.ready = list(paths), ready
        if not paths:
            self.name.setText("Output file")
            self.folder.setText("Not converted yet")
        elif len(paths) == 1:
            self.name.setText(paths[0].name)
            self.folder.setText(str(paths[0].parent))
        else:
            self.name.setText(f"{len(paths)} files")
            self.folder.setText(where)
        tip = "\n".join(map(str, paths)) + "\nClick to show in folder · drag into your DAW" if ready else ""
        self.setToolTip(tip)
        _repolish(self, "state", "ok" if ready else "off")
        for label in self.findChildren(QLabel):  # цвет подписей зависит от state карточки
            label.style().unpolish(label)
            label.style().polish(label)
        self.setCursor(Qt.CursorShape.PointingHandCursor if ready else Qt.CursorShape.ArrowCursor)

    def _available(self) -> bool:
        return self.ready and any(p.is_file() for p in self.paths)

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
            mime.setUrls([QUrl.fromLocalFile(str(p)) for p in self.paths if p.is_file()])
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


class ReportDialog(QDialog):
    """Полный отчёт файла (или текст ошибки): только чтение, текст выделяется и копируется; Copy — весь текст."""

    def __init__(self, parent, title: str, text: str) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(640, 480)
        self.view = QPlainTextEdit(text)
        self.view.setReadOnly(True)
        self.view.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse
                                          | Qt.TextInteractionFlag.TextSelectableByKeyboard)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self.copy_btn = buttons.addButton("Copy", QDialogButtonBox.ButtonRole.ActionRole)
        self.copy_btn.setToolTip("Copy the whole report")
        self.copy_btn.clicked.connect(self.copy)
        buttons.rejected.connect(self.reject)
        box = QVBoxLayout(self)
        box.addWidget(self.view, stretch=1)
        box.addWidget(buttons)

    def copy(self) -> None:
        QGuiApplication.clipboard().setText(self.view.toPlainText())


class MainWindow(QMainWindow):
    def __init__(self, storage: Storage | None = None) -> None:
        super().__init__()
        self.storage = storage if storage is not None else Storage()
        self.sources: list[Path] = []     # исходные файлы (один или несколько)
        self.outputs: list[Path] = []     # готовые результаты последней конвертации (только успешные)
        self.results: dict[Path, FileResult] = {}  # результаты последней конвертации по исходному файлу
        self.report_head = ""             # «Profile: … » — заголовок окна Details
        self.output_dir: Path | None = None  # None — результаты рядом с исходниками
        self.settings = ui_settings(self.storage)
        saved = self.settings.value(DIRECTION_KEY)
        self.direction = saved if saved in (FORWARD, REVERSE) else FORWARD
        self._seed_error = ""
        try:  # первый запуск: схема первой версии — обычный профиль (удалённый не вернётся)
            self.storage.seed_profiles([legacy_profile()])
        except OSError as e:
            self._seed_error = f"Cannot create the profiles folder: {e}"

        self.setWindowTitle("REMAP")
        self.setMinimumSize(760, 580)
        self._default_size()
        self.setAcceptDrops(True)
        self.setStyleSheet(stylesheet())
        self._build_ui()
        self._bind_shortcuts()
        self.reload_profiles()
        if self._seed_error:
            self.set_status(self._seed_error, "error")

    @property
    def source(self) -> Path | None:
        """Первый исходный файл (при одном файле — он же)."""
        return self.sources[0] if self.sources else None

    @property
    def output(self) -> Path | None:
        """Первый готовый результат."""
        return self.outputs[0] if self.outputs else None

    def _default_size(self) -> None:
        """~1280×800, но не больше 90 % доступной области экрана (и не меньше минимального размера)."""
        width, height = 1280, 800
        screen = self.screen() or QApplication.primaryScreen()
        if screen is not None:
            area = screen.availableGeometry()
            width, height = min(width, int(area.width() * 0.9)), min(height, int(area.height() * 0.9))
        self.resize(max(width, self.minimumWidth()), max(height, self.minimumHeight()))

    # --- построение UI ---

    def _build_ui(self) -> None:
        central = MetalBody()
        root = QVBoxLayout(central)
        root.setContentsMargins(24, 20, 24, 16)
        root.setSpacing(8)

        logo = _label("R", "logo")
        logo.setFixedSize(44, 44)
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        titles = QVBoxLayout()
        titles.setSpacing(0)
        titles.addWidget(_label("REMAP", "title"))
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

        self.drop = SourceZone(self.choose_file, self.remove_source, self.clear, self.show_details)
        root.addWidget(self.drop)
        root.addSpacing(6)

        root.addWidget(self._section("REMAP PROFILE"))
        self.profile_stack = QStackedWidget()
        self.profile_stack.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        chooser = QWidget()
        self.profile_combo = ComboBox()
        self.profile_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.profile_combo.currentIndexChanged.connect(self._on_profile_changed)
        self.direction_btn = QPushButton()
        self.direction_btn.setObjectName("direction")
        self.direction_btn.setFixedWidth(44)
        self.direction_btn.clicked.connect(self.toggle_direction)
        self._show_direction()
        self.edit_profile_btn = QPushButton("Edit")
        self.edit_profile_btn.setToolTip("Open this profile in the Profiles tab")
        self.edit_profile_btn.clicked.connect(self.edit_selected_profile)
        prow = QHBoxLayout()
        prow.setContentsMargins(0, 0, 0, 0)
        prow.addWidget(self.profile_combo, stretch=1)
        prow.addWidget(self.direction_btn)
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

        self.folder_btn = QPushButton("Output folder…")
        self.folder_btn.setObjectName("link")
        self.folder_btn.setToolTip("Write all results into one folder")
        self.folder_btn.clicked.connect(self.choose_output_folder)
        self.folder_reset_btn = QPushButton("Next to sources")
        self.folder_reset_btn.setObjectName("link")
        self.folder_reset_btn.setToolTip("Write each result next to its source file")
        self.folder_reset_btn.clicked.connect(lambda: self.set_output_dir(None))
        self.folder_reset_btn.setVisible(False)
        out_head = QHBoxLayout()
        out_head.setContentsMargins(0, 0, 0, 0)
        out_head.addWidget(self._section("OUTPUT"))
        out_head.addStretch(1)
        out_head.addWidget(self.folder_reset_btn)
        out_head.addWidget(self.folder_btn)
        root.addLayout(out_head)
        self.out_card = OutputCard(self.open_folder)
        root.addWidget(self.out_card)
        root.addSpacing(6)

        self.convert_btn = QPushButton("Convert  →")
        self.convert_btn.setObjectName("primary")
        self.convert_btn.setToolTip("Convert (Enter)")
        self.convert_btn.clicked.connect(self.convert)
        self.copy_btn = QPushButton()
        self.copy_btn.clicked.connect(self.copy_output)
        self._show_copy()
        actions = QHBoxLayout()
        actions.addWidget(self.convert_btn)
        actions.addStretch(1)
        actions.addWidget(self.copy_btn)
        root.addLayout(actions)
        root.addSpacing(6)

        root.addStretch(1)

        self.status = QLabel("Supports .mid and .midi files.")
        self.status.setObjectName("status")
        self.status.setWordWrap(True)
        root.addWidget(self.status)

    @staticmethod
    def _section(text: str) -> QLabel:
        return _label(text, "section")

    def _bind_shortcuts(self) -> None:
        # горячие клавиши экрана Convert; на других вкладках выключены (там Enter/Ctrl+C нужны редакторам)
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
            text = profile_summary(self.storage.load_profile(profile_id), self.direction)
        except (OSError, ValueError) as e:
            text = f"Cannot read the profile: {e}"
        self.profile_summary.setText(text)

    def _show_direction(self) -> None:
        self.direction_btn.setText(SWAP_TEXT)  # как на Profiles; карты направления — в строке под профилем
        self.direction_btn.setToolTip(SWAP_TIP)
        _repolish(self.direction_btn, "dir", self.direction)  # в ← — цвет reverse

    def toggle_direction(self) -> None:
        """«⇄»: прямое или обратное направление конвертации (запоминается в ui.ini)."""
        self.direction = FORWARD if self.direction == REVERSE else REVERSE
        self.settings.setValue(DIRECTION_KEY, self.direction)
        self._show_direction()
        self._on_profile_changed()

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

    def set_sources(self, paths: list[Path]) -> None:
        """Заменить список исходных файлов (повторы убираются, порядок сохраняется); результат и отчёт сбрасываются.
        Drop, диалог и Ctrl+V добавляют к списку (add_sources), load() и «Clear all» — заменяют."""
        files: list[Path] = []
        for path in paths:
            path = Path(path).resolve()
            if path not in files:
                files.append(path)
        self.sources, self.outputs, self.results = files, [], {}
        self.drop.set_files(files)
        self._show_planned_outputs()
        self._show_copy()

    def _show_copy(self) -> None:
        """«Copy files», когда результатов несколько (готовых, а до конвертации — будущих)."""
        n = len(self.outputs) if self.outputs else len(self.sources)
        what = "Copy files" if n > 1 else "Copy file"
        self.copy_btn.setText(f"{what}  ⧉")
        self.copy_btn.setToolTip(f"{what} (Ctrl+C)")

    def _where(self) -> str:
        return str(self.output_dir) if self.output_dir is not None else "Next to the source files"

    def _show_planned_outputs(self) -> None:
        """Карточка результата до конвертации: куда лягут файлы."""
        planned = [output_path_for(s, self.output_dir) for s in self.sources]
        self.out_card.set_files(planned, ready=False, where=self._where())

    def load(self, path: str | Path) -> None:
        if not is_midi(path):
            self.set_status("Choose an existing .mid or .midi file.", "error")
            return
        self.set_sources([Path(path)])
        self.set_status("File loaded. Click Convert or press Enter.")

    def clear(self) -> None:
        self.set_sources([])
        self.set_status("Cleared.")

    def remove_source(self, path: Path) -> None:
        """Кнопка ✕ в списке файлов."""
        self.set_sources([p for p in self.sources if p != path])
        self.set_status(f"Removed {path.name}." if self.sources else "Cleared.")

    def choose_file(self) -> None:
        start = str(self.sources[0].parent) if self.sources else ""
        paths, _ = QFileDialog.getOpenFileNames(self, "Open MIDI files", start,
                                                "MIDI files (*.mid *.midi);;All files (*.*)")
        files = [Path(p) for p in paths if is_midi(p)]
        if files:
            self._accept_files(files)

    def _accept_files(self, files: list[Path]) -> None:
        """Drop, диалог, Ctrl+V: файлы добавляются к списку (уже добавленные не повторяются)."""
        before = len(self.sources)
        self.set_sources(self.sources + list(files))
        added = len(self.sources) - before
        if not added:
            self.set_status("Already in the list.")
        elif len(self.sources) == 1:
            self.set_status("File loaded. Click Convert or press Enter.")
        elif before:
            self.set_status(f"Added {_plural(added, 'file')} · {len(self.sources)} in the list. "
                            "Click Convert or press Enter.")
        else:
            self.set_status(f"{len(self.sources)} files loaded. Click Convert or press Enter.")

    def paste_file(self) -> None:
        files = midi_paths_from_mime(QGuiApplication.clipboard().mimeData())
        if files:
            self._accept_files(files)
        else:
            self.set_status("No MIDI file in the clipboard. Copy a file in Explorer and press Ctrl+V.", "error")

    def ask_output_folder(self, start: str) -> str:
        """Диалог выбора папки результатов (пустая строка — отмена). Тесты подменяют."""
        return QFileDialog.getExistingDirectory(self, "Output folder", start)

    def choose_output_folder(self) -> None:
        start = str(self.output_dir) if self.output_dir else (str(self.sources[0].parent) if self.sources else "")
        folder = self.ask_output_folder(start)
        if folder:
            self.set_output_dir(Path(folder))

    def set_output_dir(self, folder: Path | None) -> None:
        """Папка для всех результатов; None — каждый рядом со своим исходником."""
        self.output_dir = folder
        self.outputs, self.results = [], {}
        self.drop.set_files(self.sources)
        self.folder_reset_btn.setVisible(folder is not None)
        self._show_planned_outputs()
        self._show_copy()
        self.set_status(f"Results go to {folder}" if folder is not None
                        else "Each result is written next to its source file.")

    def copy_output(self) -> None:
        files = [p for p in self.outputs if p.is_file()]
        if not files:
            self.set_status("Convert a file first.", "error")
            return
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(p)) for p in files])  # на Windows Qt кладёт CF_HDROP
        mime.setText("\n".join(map(str, files)))
        # Проводнику: вставка = копирование (DROPEFFECT_COPY), а не перемещение
        mime.setData('application/x-qt-windows-mime;value="Preferred DropEffect"', b"\x01\x00\x00\x00")
        QGuiApplication.clipboard().setMimeData(mime)
        what = "Output file" if len(files) == 1 else f"{len(files)} output files"
        self.set_status(f"{what} copied. Paste into a folder, or into a DAW that supports pasting files.", "ok")

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
            self.set_status("Drop .mid or .midi files, or a folder with them.", "error")

    # --- конвертация ---

    def show_error(self, text: str) -> None:
        """Диалог ошибки (тесты подменяют)."""
        QMessageBox.critical(self, "REMAP: error", text)

    def convert(self) -> None:
        """Конвертация всех исходных файлов выбранным профилем и направлением; ошибка файла не останавливает остальные."""
        if self.profile_combo.currentData() is None:
            self.set_status("Create a remap profile in the Profiles tab first.", "error")
            return
        if not self.sources:
            self.set_status("Drop a MIDI file or click the area above to choose one.", "error")
            return
        try:
            profile = self.selected_profile()
        except Exception as exc:  # noqa: BLE001 — ошибка хранилища: окно не падает
            self.show_error(f"Conversion failed:\n\n{exc}")
            self.set_status("Conversion failed.", "error")
            return
        result = convert_batch(self.sources, profile, self.direction, self.output_dir)
        self.outputs = result.outputs
        self.results = {f.src: f for f in result.files}
        self.report_head = f"Profile: {profile.name}{' (reverse)' if self.direction == REVERSE else ''}\n\n"
        self.drop.set_files(self.sources, self.results)  # итог — в строке каждого файла
        self._show_copy()
        if result.outputs:
            self.out_card.set_files(result.outputs, ready=True, where=self._where())
        else:
            self._show_planned_outputs()
        if len(result.files) == 1:
            res = result.files[0]
            if res.ok:
                self.set_status(f"Converted: {res.dst.name}", "ok")
            else:
                self.set_status("Conversion failed.", "error")
            return
        self.set_status(batch_summary(len(result.succeeded), len(result.failed)),
                        "error" if result.failed else "ok")

    def details_dialog(self, path: Path) -> ReportDialog | None:
        """Окно Details файла path (полный отчёт или ошибка); None — результата нет."""
        res = self.results.get(path)
        if res is None:
            return None
        return ReportDialog(self, f"{path.name} — report", result_details(res, self.report_head))

    def show_details(self, path: Path) -> None:
        dlg = self.details_dialog(path)
        if dlg is not None:
            dlg.exec()

    def set_status(self, text: str, state: str = "") -> None:
        self.status.setText(text)
        _repolish(self.status, "state", state)


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("REMAP")
    load_fonts()  # до стилей: они берут имена семейств
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
