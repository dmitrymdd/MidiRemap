"""Менеджер и редактор карт нот (PySide6): список шаблонов и карт пользователя, таблица нот 0–127.

Логики карт здесь нет — только вызовы midiremap.core (duplicate_map, finalize_edit, validate_map, экспорт)
и midiremap.storage. Диалоги вынесены в методы ask_*/choose_*/show_error, чтобы тесты могли их подменить.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QAbstractTableModel, QEvent, QModelIndex, QRect, QSize, QSortFilterProxyModel, Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QFileDialog, QGridLayout, QHBoxLayout, QHeaderView, QInputDialog, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QMenu, QMessageBox, QPushButton, QStyle, QStyledItemDelegate,
    QTableView, QVBoxLayout, QWidget,
)

from ..core.notemap import (
    NoteMap, articulations, duplicate_map, finalize_edit, normalize_name, validate_map,
)
from ..core.notenames import ParseIssue, load_notenames, primary_only_notes, save_notenames
from ..core.pitch import pitch_name
from ..storage import Storage, sanitize_id
from ..templates import list_map_templates, load_map_template
from .theme import TOKENS, repolish

TEMPLATE, USER = "template", "user"

REF_ROLE = Qt.ItemDataRole.UserRole
SUBTITLE_ROLE = Qt.ItemDataRole.UserRole + 1
HEADER_ROLE = Qt.ItemDataRole.UserRole + 2

COL_NOTE, COL_PITCH, COL_NAME, COL_PRIMARY, COL_SHARED = range(5)
COLUMNS = ("NOTE", "PITCH", "NAME", "PRIMARY", "SHARED")
COLUMN_TIPS = ("MIDI note number", "Pitch name (60 = C3, Toontrack convention)",
               "Articulation name. Empty = the note is not in the map",
               "Primary note of the articulation (used when converting TO this layout). "
               "Available only when the name is on several notes",
               "How many notes share this name")


@dataclass(frozen=True)
class MapRef:
    """Элемент списка: встроенный шаблон (только чтение) или карта пользователя из хранилища."""
    kind: str  # TEMPLATE / USER
    id: str

    @property
    def read_only(self) -> bool:
        return self.kind == TEMPLATE


def edited_status(base: NoteMap, work: NoteMap) -> str:
    """Статус, с которым карта будет сохранена (правило из finalize_edit)."""
    return "unverified" if work.names != base.names else base.meta.status


# --- таблица нот ---

class NoteTableModel(QAbstractTableModel):
    """128 строк (ноты 0–127) над рабочей копией карты; правит её на месте."""

    edited = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.map: NoteMap | None = None
        self.read_only = True
        self._groups: dict[str, list[int]] = {}

    def set_map(self, m: NoteMap | None, read_only: bool) -> None:
        self.beginResetModel()
        self.map, self.read_only = m, read_only
        self._regroup()
        self.endResetModel()

    def refresh(self) -> None:
        """Карта изменилась снаружи (например, после сохранения) — перерисовать всё."""
        self._regroup()
        if self.map is not None:
            self.dataChanged.emit(self.index(0, 0), self.index(127, len(COLUMNS) - 1))

    def _regroup(self) -> None:
        self._groups = articulations(self.map) if self.map is not None else {}

    def group(self, note: int) -> list[int]:
        """Ноты с тем же (нормализованным) именем; [] — нота не в карте."""
        name = self.map.names.get(note) if self.map is not None else None
        return self._groups.get(normalize_name(name), []) if name is not None else []

    def group_state(self, note: int) -> str:
        """"" — норма; "warning" — имя на нескольких нотах без основной; "error" — основных больше одной."""
        notes = self.group(note)
        if len(notes) < 2:
            return ""
        flagged = sum(1 for n in notes if n in self.map.primary)
        return "warning" if flagged == 0 else "error" if flagged > 1 else ""

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() or self.map is None else 128

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(COLUMNS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal:
            if role == Qt.ItemDataRole.DisplayRole:
                return COLUMNS[section]
            if role == Qt.ItemDataRole.ToolTipRole:
                return COLUMN_TIPS[section]
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or self.map is None:
            return None
        n, col = index.row(), index.column()
        name = self.map.names.get(n)
        notes = self.group(n)
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            if col == COL_NOTE:
                return str(n)
            if col == COL_PITCH:
                return pitch_name(n)
            if col == COL_NAME:
                return name or ""
            if col == COL_SHARED:
                return str(len(notes)) if notes else ""
            return None
        # флажок — только у имён на нескольких нотах (или если флаг уже стоит, например в старом файле)
        if role == Qt.ItemDataRole.CheckStateRole and col == COL_PRIMARY and (len(notes) > 1 or n in self.map.primary):
            return Qt.CheckState.Checked if n in self.map.primary else Qt.CheckState.Unchecked
        if role == Qt.ItemDataRole.BackgroundRole:
            state = self.group_state(n)
            return QColor(TOKENS[f"{state}_bg"]) if state else None
        if role == Qt.ItemDataRole.ForegroundRole:
            if name is None or (col == COL_SHARED and len(notes) == 1):
                return QColor(TOKENS["text_faint"])
            return None
        if role == Qt.ItemDataRole.TextAlignmentRole and col != COL_NAME:
            return int(Qt.AlignmentFlag.AlignCenter)
        if role == Qt.ItemDataRole.ToolTipRole:
            state = self.group_state(n)
            if state == "warning":
                return f'"{name}" is on {len(notes)} notes and none is marked primary'
            if state == "error":
                return f'"{name}" has several primary notes — keep only one'
        return None

    def flags(self, index):
        if not index.isValid() or self.map is None:
            return Qt.ItemFlag.NoItemFlags
        f = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        col, n = index.column(), index.row()
        if col == COL_NAME and not self.read_only:
            f |= Qt.ItemFlag.ItemIsEditable
        if col == COL_PRIMARY and n in self.map.names:
            if self.read_only or len(self.group(n)) < 2:
                f &= ~Qt.ItemFlag.ItemIsEnabled  # шаблон или имя на одной ноте — флажок неактивен
            else:
                f |= Qt.ItemFlag.ItemIsUserCheckable
        return f

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole) -> bool:
        if not index.isValid() or self.map is None or self.read_only:
            return False
        n, col = index.row(), index.column()
        if col == COL_NAME and role == Qt.ItemDataRole.EditRole:
            return self.set_name(n, str(value or ""))
        if col == COL_PRIMARY and role == Qt.ItemDataRole.CheckStateRole:
            checked = value in (Qt.CheckState.Checked, Qt.CheckState.Checked.value)
            return self.set_primary(n, checked)
        return False

    def set_name(self, n: int, label: str) -> bool:
        """Пустое имя — нота удаляется из карты. Смена артикуляции снимает флаг primary с ноты."""
        label = label.strip()
        old = self.map.names.get(n)
        if label == (old or ""):
            return False
        if label:
            self.map.names[n] = label
        else:
            del self.map.names[n]
        if n in self.map.primary and (not label or normalize_name(label) != normalize_name(old)):
            self.map.primary.discard(n)
        self._changed()
        return True

    def set_primary(self, n: int, checked: bool) -> bool:
        """Основная нота — не больше одной на артикуляцию: отметка снимает флаг с остальных нот имени."""
        notes = self.group(n)
        if len(notes) < 2:
            return False
        if checked:
            self.map.primary.difference_update(notes)
            self.map.primary.add(n)
        else:
            self.map.primary.discard(n)
        self._changed()
        return True

    def _changed(self) -> None:
        self.refresh()  # меняются счётчики и подсветка всех нот затронутых артикуляций
        self.edited.emit()


class NoteFilter(QSortFilterProxyModel):
    """«Только ноты с именем» + поиск по имени, номеру ноты или названию высоты.

    Фильтр не пересчитывается при правке (dynamicSortFilter выключен): строка, у которой стёрли имя,
    не исчезает из-под курсора. Пересчёт — при смене фильтра или карты.
    """

    def __init__(self) -> None:
        super().__init__()
        self.named_only = True
        self.query = ""
        self.setDynamicSortFilter(False)

    def set_filter(self, named_only: bool, query: str) -> None:
        self.beginFilterChange()
        self.named_only, self.query = named_only, query
        self.endFilterChange()

    def filterAcceptsRow(self, row, parent) -> bool:
        m = self.sourceModel().map
        if m is None:
            return False
        name = m.names.get(row)
        if self.named_only and name is None:
            return False
        q = normalize_name(self.query)
        if not q:
            return True
        if q.isdigit():
            return int(q) == row
        return q == pitch_name(row).casefold() or (name is not None and q in normalize_name(name))


# --- список карт ---

class MapListDelegate(QStyledItemDelegate):
    """Две строки: имя карты и (приглушённо) статус/источник; заголовки групп — мелкими капителями."""

    def sizeHint(self, option, index) -> QSize:
        return QSize(200, 30 if index.data(HEADER_ROLE) else 46)

    def paint(self, p, option, index) -> None:
        p.save()
        r: QRect = option.rect
        font = QFont(option.font)
        if index.data(HEADER_ROLE):
            font.setPointSizeF(8)
            font.setBold(True)
            p.setFont(font)
            p.setPen(QColor(TOKENS["text_muted"]))
            p.drawText(r.adjusted(10, 0, -10, -4), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom,
                       index.data())
            p.restore()
            return
        enabled = bool(index.flags() & Qt.ItemFlag.ItemIsEnabled)
        if option.state & QStyle.StateFlag.State_Selected:
            p.fillRect(r, QColor(TOKENS["selection"]))
            p.fillRect(QRect(r.left(), r.top(), 3, r.height()), QColor(TOKENS["accent"]))
        elif option.state & QStyle.StateFlag.State_MouseOver and enabled:
            p.fillRect(r, QColor(TOKENS["surface_hover"]))
        text = r.adjusted(12, 4, -8, -4)
        half = text.height() // 2
        font.setBold(enabled)
        p.setFont(font)
        p.setPen(QColor(TOKENS["text"] if enabled else TOKENS["text_faint"]))
        title = p.fontMetrics().elidedText(index.data() or "", Qt.TextElideMode.ElideRight, text.width())
        p.drawText(QRect(text.left(), text.top(), text.width(), half),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, title)
        font.setBold(False)
        font.setPointSizeF(max(font.pointSizeF() - 1, 7))
        p.setFont(font)
        p.setPen(QColor(TOKENS["text_muted"]))
        sub = p.fontMetrics().elidedText(index.data(SUBTITLE_ROLE) or "", Qt.TextElideMode.ElideRight, text.width())
        p.drawText(QRect(text.left(), text.top() + half, text.width(), text.height() - half),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, sub)
        p.restore()


def _subtitle(m: NoteMap, legacy: bool = False) -> str:
    parts = ["legacy .txt"] if legacy else []
    parts.append(m.meta.status)
    parts.append(m.meta.source or "source not recorded")
    return " · ".join(parts)


def _tooltip(m: NoteMap, extra: str = "") -> str:
    lines = [m.name, f"Status: {m.meta.status}", f"Source: {m.meta.source or 'not recorded'}"]
    if m.meta.notes:
        lines.append(f"Notes: {m.meta.notes}")
    if extra:
        lines.append(extra)
    return "\n".join(lines)


def format_parse_issues(issues: list[ParseIssue], limit: int = 30) -> str:
    lines = [(f"line {i.line}: " if i.line else "") + i.message for i in issues[:limit]]
    if len(issues) > limit:
        lines.append(f"… and {len(issues) - limit} more")
    return "\n".join(lines)


# --- страница ---

class MapsPage(QWidget):
    """Менеджер карт (слева) и редактор выбранной карты (справа)."""

    dirty_changed = Signal(bool)

    def __init__(self, storage: Storage) -> None:
        super().__init__()
        self.storage = storage
        self.current: MapRef | None = None
        self.base: NoteMap | None = None  # последнее сохранённое состояние
        self.work: NoteMap | None = None  # рабочая копия, её правит таблица
        self.load_issues: list[ParseIssue] = []
        self.legacy = False  # открыта старая карта .txt (при сохранении станет .json)
        self._templates: dict[str, NoteMap] = {}
        self._user_ids: list[str] = []
        self._dirty = False
        self._build_ui()
        self.reload_list()
        self._update_state()

    # --- построение UI ---

    def _build_ui(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 10, 0, 0)
        root.setSpacing(16)

        left = QVBoxLayout()
        left.setSpacing(8)
        self.list = QListWidget()
        self.list.setItemDelegate(MapListDelegate(self.list))
        self.list.setMouseTracking(True)
        self.list.currentItemChanged.connect(self._on_current_changed)
        left.addWidget(self.list, stretch=1)

        self.new_btn = QPushButton("New")
        self.import_btn = QPushButton("Import .txt…")
        self.duplicate_btn = QPushButton("Duplicate")
        self.rename_btn = QPushButton("Rename")
        self.delete_btn = QPushButton("Delete")
        self.export_btn = QPushButton("Export .txt")
        export_menu = QMenu(self.export_btn)
        export_menu.addAction("Full map…", lambda: self.export(primary_only=False))
        export_menu.addAction("Primary notes only…", lambda: self.export(primary_only=True))
        self.export_btn.setMenu(export_menu)
        self.new_btn.setToolTip("Create an empty map")
        self.import_btn.setToolTip("Import a REAPER MIDI note name map (.txt)")
        self.duplicate_btn.setToolTip("Copy the selected map. This is the only way to edit a built-in template")
        self.export_btn.setToolTip("Export the map as it is shown in the editor to a REAPER .txt file")
        self.new_btn.clicked.connect(self.new_map)
        self.import_btn.clicked.connect(self.import_txt)
        self.duplicate_btn.clicked.connect(self.duplicate)
        self.rename_btn.clicked.connect(self.rename)
        self.delete_btn.clicked.connect(self.delete)
        grid = QGridLayout()
        grid.setSpacing(6)
        for i, b in enumerate((self.new_btn, self.import_btn, self.duplicate_btn, self.rename_btn,
                               self.delete_btn, self.export_btn)):
            grid.addWidget(b, i // 2, i % 2)
        left.addLayout(grid)
        left_box = QWidget()
        left_box.setLayout(left)
        left_box.setFixedWidth(290)
        root.addWidget(left_box)

        right = QVBoxLayout()
        right.setSpacing(6)
        self.title = QLabel("No map selected")
        self.title.setObjectName("mapTitle")
        self.status_chip = QLabel()
        self.status_chip.setObjectName("chip")
        self.kind_chip = QLabel()
        self.kind_chip.setObjectName("chip")
        self.dirty_label = QLabel("● Unsaved changes")
        self.dirty_label.setObjectName("dirty")
        head = QHBoxLayout()
        head.addWidget(self.title, stretch=1)
        head.addWidget(self.dirty_label)
        head.addWidget(self.kind_chip)
        head.addWidget(self.status_chip)
        right.addLayout(head)
        self.source_label = QLabel()
        self.source_label.setObjectName("muted")
        self.source_label.setWordWrap(True)
        self.source_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        right.addWidget(self.source_label)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search: name, note number or pitch (e.g. C1)")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._apply_filter)
        self.named_only = QCheckBox("Show only named notes")
        self.named_only.setChecked(True)
        self.named_only.toggled.connect(self._apply_filter)
        tools = QHBoxLayout()
        tools.addWidget(self.search, stretch=1)
        tools.addSpacing(8)
        tools.addWidget(self.named_only)
        right.addLayout(tools)

        self.model = NoteTableModel()
        self.model.edited.connect(self._update_state)
        self.proxy = NoteFilter()
        self.proxy.setSourceModel(self.model)
        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(26)
        self.table.setShowGrid(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked
                                   | QAbstractItemView.EditTrigger.EditKeyPressed
                                   | QAbstractItemView.EditTrigger.AnyKeyPressed)
        header = self.table.horizontalHeader()
        header.setHighlightSections(False)
        for col, width in ((COL_NOTE, 64), (COL_PITCH, 64), (COL_PRIMARY, 76), (COL_SHARED, 70)):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.Fixed)
            self.table.setColumnWidth(col, width)
        header.setSectionResizeMode(COL_NAME, QHeaderView.ResizeMode.Stretch)
        self.table.installEventFilter(self)
        right.addWidget(self.table, stretch=1)

        self.issues_label = QLabel()
        self.issues_label.setObjectName("issues")
        self.issues_label.setWordWrap(True)
        right.addWidget(self.issues_label)

        self.revert_btn = QPushButton("Revert")
        self.revert_btn.clicked.connect(self.revert)
        self.save_btn = QPushButton("Save")
        self.save_btn.setObjectName("primary")
        self.save_btn.clicked.connect(self.save)
        self.status = QLabel()
        self.status.setObjectName("status")
        self.status.setWordWrap(True)
        bottom = QHBoxLayout()
        bottom.addWidget(self.status, stretch=1)
        self.read_only_hint = QLabel("Built-in template — Duplicate to edit")
        self.read_only_hint.setObjectName("muted")
        bottom.addWidget(self.read_only_hint)
        bottom.addWidget(self.revert_btn)
        bottom.addWidget(self.save_btn)
        right.addLayout(bottom)
        self.edit_hint = QLabel("Double-click or type to edit a name    Empty name: remove the note    "
                                "Delete: clear selected names")
        self.edit_hint.setObjectName("hint")
        right.addWidget(self.edit_hint)
        root.addLayout(right, stretch=1)

    def eventFilter(self, obj, event) -> bool:
        # Delete в таблице (не в режиме правки ячейки) стирает имена выделенных нот
        if (obj is self.table and event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Delete
                and self.table.state() != QAbstractItemView.State.EditingState and not self.model.read_only):
            rows = sorted({self.proxy.mapToSource(i).row() for i in self.table.selectionModel().selectedRows()})
            for n in rows:
                self.model.set_name(n, "")
            return True
        return super().eventFilter(obj, event)

    # --- диалоги (тесты подменяют эти методы) ---

    def ask_text(self, title: str, label: str, default: str) -> str | None:
        text, ok = QInputDialog.getText(self, title, label, QLineEdit.EchoMode.Normal, default)
        return text if ok else None

    def confirm(self, title: str, text: str, details: str = "") -> bool:
        box = QMessageBox(QMessageBox.Icon.Question, title, text,
                          QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel, self)
        if details:
            box.setInformativeText(details)
        box.setDefaultButton(QMessageBox.StandardButton.Cancel)
        return box.exec() == QMessageBox.StandardButton.Yes

    def ask_save_changes(self) -> str:
        """"save" / "discard" / "cancel"."""
        answer = QMessageBox.question(
            self, "Unsaved changes", f'Save changes to "{self.work.name}"?',
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save)
        return {QMessageBox.StandardButton.Save: "save",
                QMessageBox.StandardButton.Discard: "discard"}.get(answer, "cancel")

    def choose_open_file(self) -> str | None:
        path, _ = QFileDialog.getOpenFileName(self, "Import REAPER note names", "",
                                              "REAPER note names (*.txt);;All files (*.*)")
        return path or None

    def choose_save_file(self, default_name: str) -> str | None:
        path, _ = QFileDialog.getSaveFileName(self, "Export REAPER note names", default_name,
                                              "REAPER note names (*.txt)")
        return path or None

    def show_error(self, text: str) -> None:
        QMessageBox.warning(self, "MidiRemap", text)

    # --- список ---

    def reload_list(self, select: MapRef | None = None) -> None:
        """Перестроить список; выделение — select или текущая карта (сигналы при этом не идут)."""
        select = select or self.current
        self.list.blockSignals(True)
        self.list.clear()
        self._templates = {}
        self._header("BUILT-IN TEMPLATES")
        for tid, m in list_map_templates():
            self._templates[tid] = m
            self._item(f"🔒  {m.name}", _subtitle(m), MapRef(TEMPLATE, tid),
                       _tooltip(m, "Built-in template: read-only. Duplicate it to make your own map."))
        self._header("MY MAPS")
        try:
            entries, issues = self.storage.list_maps()
        except OSError as e:
            entries, issues = [], []
            self.set_status(f"Cannot read the maps folder: {e}", "error")
        self._user_ids = [e.id for e in entries]
        for e in entries:
            try:
                m, _ = self.storage.load_map(e.id)
            except (OSError, ValueError) as err:
                self._item(e.name, f"cannot read: {err}", None, str(e.path))
                continue
            extra = f"Legacy REAPER .txt map ({e.path.name}). Saving converts it to JSON." if e.legacy else ""
            self._item(e.name, _subtitle(m, e.legacy), MapRef(USER, e.id), _tooltip(m, extra))
        if not entries:
            self._item("No maps yet", "Create, import or duplicate one", None)
        if issues:
            self.set_status(f"Skipped unreadable maps ({len(issues)}): "
                            + ", ".join(i.path.name for i in issues), "error")
        for i in range(self.list.count()):
            if select is not None and self.list.item(i).data(REF_ROLE) == select:
                self.list.setCurrentRow(i)
                break
        self.list.blockSignals(False)

    def _header(self, text: str) -> None:
        item = QListWidgetItem(text)
        item.setData(HEADER_ROLE, True)
        item.setFlags(Qt.ItemFlag.NoItemFlags)
        self.list.addItem(item)

    def _item(self, title: str, subtitle: str, ref: MapRef | None, tooltip: str = "") -> None:
        item = QListWidgetItem(title)
        item.setData(SUBTITLE_ROLE, subtitle)
        item.setData(REF_ROLE, ref)
        item.setToolTip(tooltip)
        if ref is None:
            item.setFlags(Qt.ItemFlag.NoItemFlags)
        self.list.addItem(item)

    def _on_current_changed(self, cur: QListWidgetItem | None, prev: QListWidgetItem | None) -> None:
        ref = cur.data(REF_ROLE) if cur is not None else None
        if ref is None or ref == self.current:
            return
        if not self.maybe_leave():
            self.list.blockSignals(True)
            self.list.setCurrentItem(prev)
            self.list.blockSignals(False)
            return
        self.open(ref)

    def select(self, ref: MapRef) -> None:
        """Выделить и открыть карту (с вопросом о несохранённых правках)."""
        for i in range(self.list.count()):
            if self.list.item(i).data(REF_ROLE) == ref:
                self.list.setCurrentRow(i)
                return

    # --- редактор ---

    @property
    def dirty(self) -> bool:
        return self._dirty

    def open(self, ref: MapRef) -> bool:
        try:
            if ref.read_only:
                m, issues = load_map_template(ref.id), []
            else:
                m, issues = self.storage.load_map(ref.id)
        except (OSError, ValueError, KeyError) as e:
            self.show_error(f"Cannot open the map:\n\n{e}")
            return False
        self.current, self.base, self.load_issues = ref, m, issues
        self.legacy = not ref.read_only and not (self.storage.maps_dir / f"{ref.id}.json").is_file()
        self.work = copy.deepcopy(m)
        self.model.set_map(self.work, ref.read_only)
        self._apply_filter()
        self._update_state()
        self.set_status("")
        return True

    def close_map(self) -> None:
        self.current = self.base = self.work = None
        self.load_issues = []
        self.legacy = False
        self.model.set_map(None, True)
        self._update_state()

    def _apply_filter(self) -> None:
        self.proxy.set_filter(self.named_only.isChecked(), self.search.text())

    def maybe_leave(self) -> bool:
        """Перед уходом с карты: несохранённые правки — спросить. False — остаться."""
        if not self.dirty:
            return True
        answer = self.ask_save_changes()
        if answer == "save":
            return self.save()
        if answer == "discard":
            self.revert()
            return True
        return False

    def save(self) -> bool:
        if self.current is None or self.current.read_only or self.work is None:
            return False
        errors = [i.message for i in validate_map(self.work) if i.severity == "error"]
        if errors:
            self.show_error("The map has errors and was not saved:\n\n" + "\n".join(errors))
            return False
        out = finalize_edit(self.base, self.work)
        try:
            self.storage.save_map(out, map_id=self.current.id, overwrite=True)
        except (OSError, ValueError) as e:
            self.show_error(f"Cannot save the map:\n\n{e}")
            return False
        # рабочую копию не пересоздаём, чтобы таблица не теряла прокрутку и выделение
        self.base = out
        self.work.meta = copy.deepcopy(out.meta)
        self.work.order = copy.deepcopy(out.order)
        self.work.primary = set(out.primary)
        self.load_issues = []
        self.legacy = False
        self.model.refresh()
        self.reload_list()
        self._update_state()
        self.set_status(f'Saved "{out.name}".', "ok")
        return True

    def revert(self) -> None:
        if self.base is None:
            return
        self.work = copy.deepcopy(self.base)
        self.model.set_map(self.work, self.current.read_only)
        self._apply_filter()
        self._update_state()

    def _update_state(self) -> None:
        has_map = self.work is not None
        ref = self.current
        dirty = has_map and (self.work.names != self.base.names or self.work.primary != self.base.primary)
        if dirty != self._dirty:
            self._dirty = dirty
            self.dirty_changed.emit(dirty)
        self.dirty_label.setVisible(dirty)
        read_only = has_map and ref.read_only
        self.save_btn.setEnabled(dirty)
        self.revert_btn.setEnabled(dirty)
        # у шаблона сохранять нечего: вместо Save/Revert — подсказка
        self.save_btn.setHidden(read_only)
        self.revert_btn.setHidden(read_only)
        self.read_only_hint.setVisible(read_only)
        self.edit_hint.setHidden(read_only)
        self.duplicate_btn.setEnabled(has_map)
        self.export_btn.setEnabled(has_map)
        self.rename_btn.setEnabled(has_map and not ref.read_only)
        self.delete_btn.setEnabled(has_map and not ref.read_only)
        self.search.setEnabled(has_map)
        self.named_only.setEnabled(has_map)
        self.status_chip.setVisible(has_map)
        self.kind_chip.setVisible(has_map and (ref.read_only or self.legacy))
        if not has_map:
            self.title.setText("No map selected")
            self.source_label.setText("Select a map on the left, or create one.")
            self.issues_label.setText("")
            return
        self.title.setText(self.work.name)
        status = edited_status(self.base, self.work)
        self.status_chip.setText(status.upper())
        repolish(self.status_chip, "state", "ok" if status == "verified" else "warn")
        self.status_chip.setToolTip(
            "Note names were edited: the map will be saved as unverified."
            if status != self.base.meta.status else
            "Verified against the program or plugin itself." if status == "verified" else
            "Not verified against the program or plugin.")
        self.kind_chip.setText("🔒 TEMPLATE · READ-ONLY" if ref.read_only else "LEGACY .TXT")
        self.kind_chip.setToolTip("Duplicate the template to edit a copy." if ref.read_only else
                                  "Old REAPER .txt map. Saving converts it to JSON.")
        lines = [f"Source: {self.work.meta.source or 'not recorded'}"]
        if self.work.meta.notes:
            lines.append(f"Notes: {self.work.meta.notes}")
        lines.append(f"{len(self.work.names)} named notes")
        self.source_label.setText("\n".join(lines))
        self._update_issues()

    def _update_issues(self) -> None:
        issues = validate_map(self.work)
        errors = [i.message for i in issues if i.severity == "error"]
        warnings = [i for i in issues if i.severity == "warning"]
        parts = []
        if errors:
            parts.append("Errors: " + "; ".join(errors))
        if warnings:
            parts.append(f"{len(warnings)} articulation(s) on several notes without a primary note "
                         "(highlighted) — they are skipped in “primary notes only” export.")
        if self.load_issues:
            parts.append(f"{len(self.load_issues)} issue(s) when reading the .txt file "
                         "(see the tooltip).")
        self.issues_label.setText("\n".join(parts))
        self.issues_label.setToolTip(format_parse_issues(self.load_issues) if self.load_issues else "")
        repolish(self.issues_label, "state", "error" if errors else "")

    # --- действия ---

    def ask_unique_name(self, title: str, default: str, exclude_id: str | None = None) -> str | None:
        """Имя новой карты; ID (имя файла) не должен совпадать с существующей картой. None — отмена."""
        taken = {i.casefold() for i in self._user_ids} - {(exclude_id or "").casefold()}
        while True:
            text = self.ask_text(title, "Map name:", default)
            if text is None:
                return None
            text = text.strip()
            if not text:
                self.show_error("The name cannot be empty.")
                continue
            if sanitize_id(text).casefold() in taken:
                self.show_error(f'A map named "{text}" already exists. Choose another name.')
                default = text
                continue
            return text

    def _add_and_open(self, m: NoteMap) -> MapRef | None:
        try:
            map_id = self.storage.save_map(m)
        except (OSError, ValueError) as e:
            self.show_error(f"Cannot save the map:\n\n{e}")
            return None
        ref = MapRef(USER, map_id)
        self.reload_list(select=ref)
        self.open(ref)
        return ref

    def new_map(self) -> None:
        if not self.maybe_leave():
            return
        name = self.ask_unique_name("New map", "New map")
        if name is None:
            return
        if self._add_and_open(NoteMap(name=name)):
            self.named_only.setChecked(False)  # в пустой карте иначе нечего показать
            self.set_status(f'Created "{name}". Type names next to the notes and click Save.', "ok")

    def import_txt(self) -> None:
        if not self.maybe_leave():
            return
        path = self.choose_open_file()
        if not path:
            return
        try:
            m, issues = load_notenames(path)
        except (OSError, ValueError) as e:
            self.show_error(f"Cannot read the file:\n\n{e}")
            return
        if issues and not self.confirm(
                "Import REAPER note names",
                f"{Path(path).name}: {len(m.names)} notes read, {len(issues)} issue(s). Import anyway?",
                format_parse_issues(issues)):
            return
        name = self.ask_unique_name("Import map", m.name)
        if name is None:
            return
        m.name = name
        m.meta.notes = f"Imported from {Path(path).name}"
        if self._add_and_open(m):
            self.set_status(f'Imported "{name}": {len(m.names)} notes.', "ok")

    def duplicate(self) -> None:
        if self.base is None or not self.maybe_leave():
            return
        src, from_template = self.base, self.current.read_only
        name = self.ask_unique_name("Duplicate map", f"{src.name} (copy)")
        if name is None:
            return
        if self._add_and_open(duplicate_map(src, name, from_template=from_template)):
            self.set_status(f'Created "{name}" from "{src.name}".', "ok")

    def rename(self) -> None:
        if self.current is None or self.current.read_only or not self.maybe_leave():
            return
        old_ref, old_name = self.current, self.base.name
        name = self.ask_unique_name("Rename map", old_name, exclude_id=old_ref.id)
        if name is None or name == old_name:
            return
        m = copy.deepcopy(self.base)
        m.name = name
        new_id = sanitize_id(name)
        try:
            if new_id.casefold() == old_ref.id.casefold():  # тот же файл (Windows не различает регистр)
                self.storage.save_map(m, map_id=old_ref.id, overwrite=True)
                new_id = old_ref.id
            else:
                self.storage.save_map(m, map_id=new_id)
                self.storage.delete_map(old_ref.id)
        except (OSError, ValueError) as e:
            self.show_error(f"Cannot rename the map:\n\n{e}")
            return
        ref = MapRef(USER, new_id)
        self.current = None
        self.reload_list(select=ref)
        self.open(ref)
        self.set_status(f'Renamed "{old_name}" to "{name}".', "ok")

    def delete(self) -> None:
        if self.current is None or self.current.read_only:
            return
        name = self.base.name
        if not self.confirm("Delete map", f'Delete the map "{name}"? This cannot be undone.'):
            return
        try:
            self.storage.delete_map(self.current.id)
        except OSError as e:
            self.show_error(f"Cannot delete the map:\n\n{e}")
            return
        self.close_map()
        self.reload_list()
        self.set_status(f'Deleted "{name}".', "ok")

    def export(self, primary_only: bool) -> None:
        """Экспорт карты в том виде, как она в редакторе (включая несохранённые правки)."""
        if self.work is None:
            return
        m = finalize_edit(self.base, self.work)
        skipped: list[str] = []
        if primary_only:
            keep, skipped = primary_only_notes(m)
            if not keep:
                self.show_error("Nothing to export: no articulation has a single or primary note.")
                return
            if skipped and not self.confirm(
                    "Export primary notes only",
                    f"{len(skipped)} articulation(s) are on several notes without a primary note "
                    "and will be skipped. Export anyway?",
                    "\n".join(skipped)):
                return
        suffix = " (primary)" if primary_only else ""
        path = self.choose_save_file(sanitize_id(m.name + suffix) + ".txt")
        if not path:
            return
        try:
            save_notenames(m, path, primary_only)
        except OSError as e:
            self.show_error(f"Cannot export the map:\n\n{e}")
            return
        text = f"Exported to {path}."
        if skipped:
            text += f" Skipped ({len(skipped)}): " + ", ".join(skipped)
        self.set_status(text, "ok")

    def set_status(self, text: str, state: str = "") -> None:
        self.status.setText(text)
        repolish(self.status, "state", state)
