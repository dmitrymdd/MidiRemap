"""Менеджер и редактор карт нот (PySide6): список шаблонов и карт пользователя, таблица нот 0–127.

Логики карт здесь нет — только вызовы midiremap.core (duplicate_map, finalize_edit, validate_map, экспорт)
и midiremap.storage. Диалоги вынесены в методы ask_*/choose_*/show_error, чтобы тесты могли их подменить.

Write to (primary) на вкладке Maps не правится: его выбирают в профиле, в копии целевой карты.
В JSON карты primary остаётся (старые файлы читаются). Имя на нескольких нотах — бейдж «+N» рядом с именем.
"""
from __future__ import annotations

import copy
import html
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QAbstractTableModel, QEvent, QModelIndex, QRect, QSize, QSortFilterProxyModel, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPen
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QFileDialog, QGridLayout, QHBoxLayout, QHeaderView, QInputDialog,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton, QStyle, QStyledItemDelegate,
    QStyleOptionViewItem, QTableView, QVBoxLayout, QWidget,
)

from ..core.notemap import (
    NoteMap, articulations, duplicate_map, finalize_edit, group_rank, instrument_group, normalize_name, validate_map,
)
from ..core.notenames import ParseIssue, load_notenames, save_notenames
from ..core.pitch import note_tip, pitch_name
from ..storage import Storage, id_taken, sanitize_id
from ..templates import list_map_templates, load_map_template
from .theme import TOKENS, repolish

TEMPLATE, USER = "template", "user"

REF_ROLE = Qt.ItemDataRole.UserRole
SUBTITLE_ROLE = Qt.ItemDataRole.UserRole + 1
HEADER_ROLE = Qt.ItemDataRole.UserRole + 2
OTHERS_ROLE = Qt.ItemDataRole.UserRole + 4  # сколько ещё нот карты с этим именем (бейдж «+N»)

COL_NOTE, COL_NAME = range(2)
COLUMNS = ("NOTE", "NAME")  # высота ноты (C#1) для барабанов смысла не несёт — только в подсказке ячейки
COLUMN_TIPS = ("MIDI note number (the pitch name, 60 = C3, is in the cell tooltip)",
               "Articulation name. Empty = the note is not in the map. +N — the name is on N more notes")
# клик по заголовку столбца: по возрастанию → по убыванию → по группам инструментов (вид по умолчанию)
SORT_TIPS = ("Click to list notes in ascending order", "Click to list notes in ascending order",
             "Click to group notes by instrument")

EDIT_TIP = "Double-click or type to edit a name · Empty name: remove the note · Delete: clear selected names"

# служебные ключи групп (не совпадут с normalize_name настоящего инструмента)
OTHER_GROUP, UNNAMED_GROUP = "\0other", "\0unnamed"


@dataclass(frozen=True)
class MapRef:
    """Элемент списка: встроенный шаблон (только чтение) или карта пользователя из хранилища."""
    kind: str  # TEMPLATE / USER
    id: str

    @property
    def read_only(self) -> bool:
        return self.kind == TEMPLATE


@dataclass(frozen=True)
class LayoutRow:
    """Строка таблицы: заголовок группы инструмента (note is None) или нота."""
    group: str | None  # ключ группы (normalize_name инструмента или служебный); None — плоский список
    note: int | None = None
    label: str = ""    # текст заголовка

    @property
    def is_header(self) -> bool:
        return self.note is None


def group_rows(names: dict[int, str], notes: list[int], unnamed_label: str = "Not in the map",
               ) -> list[LayoutRow]:
    """Строки с заголовками групп instrument_group() (только для показа).

    Группы — в общем порядке GROUP_ORDER (group_rank, как на Profiles), одинаковый ранг — по первой (меньшей) ноте;
    ноты внутри — в порядке notes. Если ни у одного имени нет группы
    (General MIDI) — плоский список без заголовков. Именованные ноты без группы — в «Other»,
    ноты без имени — в последней группе unnamed_label.
    """
    if not any(instrument_group(names[n]) for n in notes if n in names):
        return [LayoutRow(None, n) for n in notes]
    groups: dict[str, tuple[str, list[int]]] = {}
    for n in notes:
        if n in names:
            g = instrument_group(names[n])
            key, label = (normalize_name(g), g) if g else (OTHER_GROUP, "Other")
        else:
            key, label = UNNAMED_GROUP, unnamed_label
        groups.setdefault(key, (label, []))[1].append(n)
    order = sorted(groups, key=lambda k: (k == UNNAMED_GROUP,
                                          group_rank(None if k == OTHER_GROUP else groups[k][0]), groups[k][1][0]))
    rows: list[LayoutRow] = []
    for key in order:
        label, members = groups[key]
        rows.append(LayoutRow(key, None, label))
        rows.extend(LayoutRow(key, n) for n in members)
    return rows


def update_spans(table: QTableView, columns: int) -> None:
    """Заголовки групп — на всю ширину таблицы (span пересчитывается после фильтрации и перестройки).
    Модель таблицы — модель с row_at() или прокси над ней."""
    table.clearSpans()
    view = table.model()
    proxy = view if isinstance(view, QSortFilterProxyModel) else None
    model = proxy.sourceModel() if proxy is not None else view
    for r in range(view.rowCount()):
        src = proxy.mapToSource(proxy.index(r, 0)).row() if proxy is not None else r
        if model.row_at(src).is_header:
            table.setSpan(r, 0, 1, columns)


def header_data(row: LayoutRow, col: int, role):
    """Данные строки-заголовка группы в таблице нот."""
    if role == Qt.ItemDataRole.DisplayRole and col == 0:
        return row.label.upper()
    if role == Qt.ItemDataRole.FontRole:
        f = QFont()
        f.setBold(True)
        f.setPointSizeF(8)
        return f
    if role == Qt.ItemDataRole.ForegroundRole:
        return QColor(TOKENS["text_muted"])
    if role == Qt.ItemDataRole.BackgroundRole:
        return QColor(TOKENS["bg"])
    return None


# --- таблица нот ---

class NoteTableModel(QAbstractTableModel):
    """Ноты 0–127 (с заголовками групп инструментов) над рабочей копией карты; правит её на месте.

    Раскладка строк пересчитывается при смене карты, фильтра и после сохранения, но не при правке имени:
    строка не уезжает из-под курсора.
    """

    edited = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.map: NoteMap | None = None
        self.read_only = True
        self._groups: dict[str, list[int]] = {}
        self.rows: list[LayoutRow] = []
        self.sort: tuple[int, bool] | None = None  # (колонка, по убыванию); None — по группам инструментов
        self._note_rows: dict[int, int] = {}
        self._members: dict[str | None, list[int]] = {}

    def set_map(self, m: NoteMap | None, read_only: bool) -> None:
        self.beginResetModel()
        self.map, self.read_only = m, read_only
        self._regroup()
        self._layout()
        self.endResetModel()

    def relayout(self) -> None:
        self.beginResetModel()
        self._regroup()
        self._layout()
        self.endResetModel()

    def set_sort(self, sort: tuple[int, bool] | None) -> None:
        """Сортировка (колонка, по убыванию) — все ноты без заголовков групп; None — по группам инструментов."""
        if sort != self.sort:
            self.sort = sort
            self.relayout()

    def _sorted_notes(self) -> list[int]:
        """Ноты 0–127 по колонке сортировки. NOTE — по номеру; NAME —
        по имени (без учёта регистра), равные — по номеру; ноты без имени — всегда в конце."""
        col, desc = self.sort
        notes = list(range(128))
        if col != COL_NAME:
            return notes[::-1] if desc else notes
        names = self.map.names
        named = sorted((n for n in notes if n in names), key=lambda n: (normalize_name(names[n]), n), reverse=desc)
        return named + [n for n in notes if n not in names]

    def _layout(self) -> None:
        if self.map is None:
            self.rows = []
        elif self.sort is not None:
            self.rows = [LayoutRow(None, n) for n in self._sorted_notes()]
        else:
            self.rows = group_rows(self.map.names, list(range(128)))
        self._note_rows = {r.note: i for i, r in enumerate(self.rows) if not r.is_header}
        self._members = {}
        for i, r in enumerate(self.rows):
            if not r.is_header:
                self._members.setdefault(r.group, []).append(i)

    def row_at(self, row: int) -> LayoutRow:
        return self.rows[row]

    def members(self, group: str | None) -> list[int]:
        """Строки нот группы."""
        return self._members.get(group, [])

    def note_index(self, note: int, col: int) -> QModelIndex:
        return self.index(self._note_rows[note], col)

    def note_at(self, row: int) -> int | None:
        return self.rows[row].note if 0 <= row < len(self.rows) else None

    @property
    def grouped(self) -> bool:
        return any(r.is_header for r in self.rows)

    def refresh(self) -> None:
        """Карта изменилась снаружи (например, после сохранения) — перерисовать всё."""
        self._regroup()
        if self.rows:
            self.dataChanged.emit(self.index(0, 0), self.index(len(self.rows) - 1, len(COLUMNS) - 1))

    def _regroup(self) -> None:
        self._groups = articulations(self.map) if self.map is not None else {}

    def group(self, note: int) -> list[int]:
        """Ноты с тем же (нормализованным) именем; [] — нота не в карте."""
        name = self.map.names.get(note) if self.map is not None else None
        return self._groups.get(normalize_name(name), []) if name is not None else []

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(COLUMNS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal:
            if role == Qt.ItemDataRole.DisplayRole:
                return COLUMNS[section]
            if role == Qt.ItemDataRole.ToolTipRole:
                tip = COLUMN_TIPS[section] + "\n" + SORT_TIPS[section]
                if section == COL_NAME and not self.read_only:
                    return tip + "\n" + EDIT_TIP
                return tip
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or self.map is None:
            return None
        row = self.rows[index.row()]
        if row.is_header:
            return header_data(row, index.column(), role)
        n, col = row.note, index.column()
        name = self.map.names.get(n)
        notes = self.group(n)
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            if col == COL_NOTE:
                return str(n)
            if col == COL_NAME:
                return name or ""
            return None
        if role == OTHERS_ROLE and col == COL_NAME:
            return max(0, len(notes) - 1)
        if role == Qt.ItemDataRole.ForegroundRole and name is None:
            return QColor(TOKENS["text_faint"])
        if role == Qt.ItemDataRole.TextAlignmentRole and col != COL_NAME:
            return int(Qt.AlignmentFlag.AlignCenter)
        if role == Qt.ItemDataRole.ToolTipRole:
            tip = note_tip([n])
            if col == COL_NAME and len(notes) > 1:
                tip = f"{name}\n{tip}\nOn notes {', '.join(map(str, notes))}"
            return tip
        return None

    def flags(self, index):
        if not index.isValid() or self.map is None:
            return Qt.ItemFlag.NoItemFlags
        row = self.rows[index.row()]
        if row.is_header:
            return Qt.ItemFlag.ItemIsEnabled
        f = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if index.column() == COL_NAME and not self.read_only:
            f |= Qt.ItemFlag.ItemIsEditable
        return f

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole) -> bool:
        if not index.isValid() or self.map is None or self.read_only:
            return False
        n, col = self.rows[index.row()].note, index.column()
        if n is None:
            return False
        if col == COL_NAME and role == Qt.ItemDataRole.EditRole:
            return self.set_name(n, str(value or ""))
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

    def _changed(self) -> None:
        self.refresh()  # меняются счётчики и подсветка всех нот затронутых артикуляций
        self.edited.emit()


class NameDelegate(QStyledItemDelegate):
    """Имя и бейдж «+N» (имя ещё на N нотах карты) — как в виде «кабелями». Правка имени — как обычно."""

    BADGE_PAD = 12

    def paint(self, p, option, index) -> None:
        others = index.data(OTHERS_ROLE)
        if not others:
            super().paint(p, option, index)
            return
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        style = opt.widget.style() if opt.widget is not None else QApplication.style()
        rect = style.subElementRect(QStyle.SubElement.SE_ItemViewItemText, opt, opt.widget)
        margin = style.pixelMetric(QStyle.PixelMetric.PM_FocusFrameHMargin, opt, opt.widget) + 1
        badge = f"+{others}"
        small = QFont(opt.font)
        small.setPointSizeF(max(6.0, small.pointSizeF() - 1.5))
        small.setBold(True)
        p.save()
        p.setFont(small)
        bw = p.fontMetrics().horizontalAdvance(badge) + self.BADGE_PAD
        # имя рисует сам стиль (тот же отступ, что у строк без бейджа); место под бейдж — заранее
        opt.text = opt.fontMetrics.elidedText(opt.text, Qt.TextElideMode.ElideRight,
                                              max(0, rect.width() - 2 * margin - bw - 8))
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, p, opt.widget)
        x = rect.left() + margin + opt.fontMetrics.horizontalAdvance(opt.text) + 8
        h = min(rect.height() - 8, 16)
        pill = QRect(x, rect.center().y() - h // 2 + 1, bw, h)
        p.setPen(QPen(QColor(TOKENS["border"]), 1))
        p.setBrush(QColor(TOKENS["bg"]))
        p.drawRoundedRect(pill, h / 2, h / 2)
        p.setFont(small)
        p.setPen(QColor(TOKENS["text_muted"]))
        p.drawText(pill, Qt.AlignmentFlag.AlignCenter, badge)
        p.restore()


class NoteFilter(QSortFilterProxyModel):
    """«Только ноты с именем» + поиск по имени, номеру ноты или названию высоты.
    Заголовок группы виден, если видна хотя бы одна нота группы.

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

    def note_rows(self) -> list[int]:
        """Видимые ноты (без заголовков), сверху вниз."""
        model = self.sourceModel()
        notes = [model.note_at(self.mapToSource(self.index(r, 0)).row()) for r in range(self.rowCount())]
        return [n for n in notes if n is not None]

    def filterAcceptsRow(self, row, parent) -> bool:
        model = self.sourceModel()
        if model.map is None:
            return False
        r = model.row_at(row)
        if r.is_header:
            return any(self._accept_note(model.rows[i].note) for i in model.members(r.group))
        return self._accept_note(r.note)

    def _accept_note(self, n: int) -> bool:
        name = self.sourceModel().map.names.get(n)
        if self.named_only and name is None:
            return False
        q = normalize_name(self.query)
        if not q:
            return True
        if q.isdigit():
            return int(q) == n
        return q == pitch_name(n).casefold() or (name is not None and q in normalize_name(name))


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
    parts.append(m.meta.source or "source not recorded")
    return " · ".join(parts)


def _tooltip(m: NoteMap, extra: str = "") -> str:
    lines = [m.name, f"Source: {m.meta.source or 'not recorded'}"]
    if m.meta.notes:
        lines.append(f"Notes: {m.meta.notes}")
    if extra:
        lines.append(extra)
    return "\n".join(lines)


def wrapped_tooltip(text: str) -> str:
    """Подсказка с переносом строк: длинный обычный текст Qt показывает одной строкой и обрезает краем экрана."""
    return "<qt>" + html.escape(text).replace("\n", "<br>") + "</qt>" if text else ""


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
        self.new_btn.setToolTip("Create an empty map")
        self.import_btn.setToolTip("Import a REAPER MIDI note name map (.txt)")
        self.duplicate_btn.setToolTip("Copy the selected map. This is the only way to edit a built-in template")
        self.export_btn.setToolTip("Export the map as it is shown in the editor to a REAPER .txt file")
        self.new_btn.clicked.connect(self.new_map)
        self.import_btn.clicked.connect(self.import_txt)
        self.duplicate_btn.clicked.connect(self.duplicate)
        self.rename_btn.clicked.connect(self.rename)
        self.delete_btn.clicked.connect(self.delete)
        self.export_btn.clicked.connect(self.export)
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
        self.kind_chip = QLabel()
        self.kind_chip.setObjectName("chip")
        self.dirty_label = QLabel("● Unsaved changes")
        self.dirty_label.setObjectName("dirty")
        self.edit_copy_btn = QPushButton("Duplicate to edit")
        self.edit_copy_btn.setObjectName("primary")
        self.edit_copy_btn.setToolTip("Built-in templates are read-only. Make your own copy to edit it")
        self.edit_copy_btn.clicked.connect(self.duplicate)
        head = QHBoxLayout()
        head.addWidget(self.title, stretch=1)
        head.addWidget(self.edit_copy_btn)
        head.addWidget(self.dirty_label)
        head.addWidget(self.kind_chip)
        right.addLayout(head)
        self.source_label = QLabel()
        self.source_label.setObjectName("muted")
        self.source_label.setWordWrap(True)
        self.source_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        right.addWidget(self.source_label)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search: name or note number")
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
        header.setSectionsClickable(True)
        header.setSortIndicatorShown(False)  # по умолчанию — группы, без стрелки
        header.sectionClicked.connect(self.sort_by)
        header.setSectionResizeMode(COL_NOTE, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(COL_NOTE, 64)
        header.setSectionResizeMode(COL_NAME, QHeaderView.ResizeMode.Stretch)
        self.table.setItemDelegateForColumn(COL_NAME, NameDelegate(self.table))
        self.table.installEventFilter(self)
        for sig in (self.proxy.modelReset, self.proxy.layoutChanged, self.proxy.rowsInserted,
                    self.proxy.rowsRemoved):
            sig.connect(lambda *_: update_spans(self.table, len(COLUMNS)))
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
        bottom.addWidget(self.revert_btn)
        bottom.addWidget(self.save_btn)
        right.addLayout(bottom)
        root.addLayout(right, stretch=1)

    def eventFilter(self, obj, event) -> bool:
        # Delete в таблице (не в режиме правки ячейки) стирает имена выделенных нот
        if (obj is self.table and event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Delete
                and self.table.state() != QAbstractItemView.State.EditingState and not self.model.read_only):
            rows = {self.proxy.mapToSource(i).row() for i in self.table.selectionModel().selectedRows()}
            for n in sorted(n for n in map(self.model.note_at, rows) if n is not None):
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
        # подзаголовок в списке обрезается по ширине — в подсказке текст целиком
        item.setToolTip(wrapped_tooltip(tooltip or f"{title}\n{subtitle}"))
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

    def sort_by(self, column: int) -> None:
        """Клик по заголовку колонки: по возрастанию → по убыванию → снова по группам инструментов (вид по
        умолчанию); клик по другой колонке — сразу по возрастанию. Стрелка заголовка показывает состояние."""
        sort = self.model.sort
        if sort is None or sort[0] != column:
            sort = (column, False)
        elif not sort[1]:
            sort = (column, True)
        else:
            sort = None
        header = self.table.horizontalHeader()
        header.setSortIndicatorShown(sort is not None)
        if sort is not None:
            header.setSortIndicator(sort[0], Qt.SortOrder.DescendingOrder if sort[1] else Qt.SortOrder.AscendingOrder)
        note = self._current_note()
        self.model.set_sort(sort)
        self.proxy.set_filter(self.named_only.isChecked(), self.search.text())
        if note is not None:
            self._reveal_note(note)

    def _current_note(self) -> int | None:
        index = self.table.currentIndex()
        if not index.isValid():
            return None
        return self.model.note_at(self.proxy.mapToSource(index).row())

    def _reveal_note(self, note: int) -> None:
        index = self.proxy.mapFromSource(self.model.note_index(note, COL_NAME))
        if index.isValid():
            self.table.setCurrentIndex(index)
            self.table.scrollTo(index, QAbstractItemView.ScrollHint.PositionAtCenter)

    def _apply_filter(self) -> None:
        self.model.relayout()  # переименованные ноты встают в свои группы
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
        if self.model.rows != group_rows(self.work.names, list(range(128))):
            self._apply_filter()  # группы изменились; иначе не сбрасываем прокрутку и выделение
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
        # у шаблона сохранять нечего: вместо Save/Revert — кнопка «Duplicate to edit»
        self.save_btn.setHidden(read_only)
        self.revert_btn.setHidden(read_only)
        self.edit_copy_btn.setVisible(read_only)
        self.duplicate_btn.setEnabled(has_map)
        self.export_btn.setEnabled(has_map)
        self.rename_btn.setEnabled(has_map and not ref.read_only)
        self.delete_btn.setEnabled(has_map and not ref.read_only)
        self.search.setEnabled(has_map)
        self.named_only.setEnabled(has_map)
        self.kind_chip.setVisible(has_map and (ref.read_only or self.legacy))
        if not has_map:
            self.title.setText("No map selected")
            self.source_label.setText("Select a map on the left, or create one.")
            self.issues_label.setText("")
            return
        self.title.setText(self.work.name)
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
        errors = [i.message for i in validate_map(self.work) if i.severity == "error"]
        parts = []
        if errors:
            parts.append("Errors: " + "; ".join(errors))
        if self.load_issues:
            parts.append(f"{len(self.load_issues)} issue(s) when reading the .txt file "
                         "(see the tooltip).")
        self.issues_label.setText("\n".join(parts))
        self.issues_label.setToolTip(format_parse_issues(self.load_issues) if self.load_issues else "")
        repolish(self.issues_label, "state", "error" if errors else "")

    # --- действия ---

    def ask_unique_name(self, title: str, default: str, exclude_id: str | None = None) -> str | None:
        """Имя новой карты; ID (имя файла) не должен совпадать с существующей картой. None — отмена."""
        while True:
            text = self.ask_text(title, "Map name:", default)
            if text is None:
                return None
            text = text.strip()
            if not text:
                self.show_error("The name cannot be empty.")
                continue
            if id_taken(text, self._user_ids, exclude_id):
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
        try:
            new_id = self.storage.rename_map(old_ref.id, m)
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

    def export(self) -> None:
        """Экспорт всей карты в том виде, как она в редакторе (включая несохранённые правки)."""
        if self.work is None:
            return
        m = finalize_edit(self.base, self.work)
        path = self.choose_save_file(sanitize_id(m.name) + ".txt")
        if not path:
            return
        try:
            save_notenames(m, path)
        except OSError as e:
            self.show_error(f"Cannot export the map:\n\n{e}")
            return
        self.set_status(f"Exported to {path}.", "ok")

    def set_status(self, text: str, state: str = "") -> None:
        self.status.setText(text)
        repolish(self.status, "state", state)
