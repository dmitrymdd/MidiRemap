"""Менеджер и редактор профилей ремапа (PySide6): список профилей слева, справа — карты профиля
и таблица правил «исходная нота → цель».

Логики профилей здесь нет — только вызовы midiremap.core (suggest_rules, apply_suggestions, validate_profile,
unassigned_keep_warnings, with_explicit_keeps) и midiremap.storage. Диалоги вынесены в методы ask_*/pick_*/confirm/show_error,
чтобы тесты могли их подменить. Таблица — основной вид этапа 8b1; визуальный редактор «кабелями» (8b2)
будет работать над той же моделью.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass

from PySide6.QtCore import (
    QAbstractTableModel, QEvent, QItemSelection, QItemSelectionModel, QModelIndex, Qt, Signal,
)
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QDialogButtonBox, QGridLayout, QTableWidget, QTableWidgetItem, QHBoxLayout, QHeaderView, QInputDialog, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QMenu, QMessageBox, QPushButton, QTableView, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget,
)

from ..core.notemap import NoteMap, articulations, duplicate_map, instrument_group, normalize_name
from ..core.pitch import pitch_name
from ..core.profile import (
    DIFFERENT_INSTRUMENT, NO_RULE, SAME_INSTRUMENT, KeepWarning, ProfileIssue, RemapProfile, Rule,
    unassigned_keep_warnings, validate_profile, with_explicit_keeps,
)
from ..core.suggest import Suggestion, apply_suggestions, suggest_rules
from ..storage import Storage, sanitize_id
from ..templates import list_map_templates, load_map_template
from .maps_page import (
    HEADER_ROLE, REF_ROLE, SUBTITLE_ROLE, TEMPLATE, USER, LayoutRow, MapListDelegate, MapRef, group_rows,
    header_data, update_spans, wrapped_tooltip,
)
from .theme import TOKENS, repolish

SOURCE, TARGET = "source", "target"

NAME_ROLE = Qt.ItemDataRole.UserRole + 3  # имя профиля без пометки «•»

MARKER_TIPS = {
    DIFFERENT_INSTRUMENT: "Different instrument at this number in the target map, or no such note there",
    SAME_INSTRUMENT: "Same instrument, different name — probably the same sound, but check",
}

COL_NOTE, COL_PITCH, COL_SOURCE, COL_TARGET, COL_STATUS = range(5)
COLUMNS = ("NOTE", "PITCH", "SOURCE NAME", "TARGET", "STATUS")
COLUMN_TIPS = ("Source MIDI note number", "Pitch name (60 = C3, Toontrack convention)",
               "Name of the note in the source map",
               "Where the note goes. Double-click or press Enter to choose; Ctrl/Shift+click to choose "
               "for several notes at once; right-click to delete a note or clear its rule",
               "Suggestion or rule state")

DELETED_GROUP = "\0deleted"

ACCEPT_TIP = ("Map notes whose names match the target map exactly or after ignoring case and spaces. "
              "Existing rules are never changed")

STATUS_TEXT = {
    "exact": "Suggested: exact", "probable": "Suggested: probable",
    "ambiguous": "Needs a Write to choice", "none": "No match",
}


def map_summary(m: NoteMap | None) -> str:
    return m.name if m is not None else "no map"


def profile_summary(p: RemapProfile) -> str:
    """«<исходная карта> → <целевая карта> · N rules» (или «no maps» без обеих карт)."""
    n = len(p.rules)
    rules = f"{n} rule" + ("" if n == 1 else "s")
    if p.source_map is None and p.target_map is None:
        return f"no maps · {rules}"
    return f"{map_summary(p.source_map)} → {map_summary(p.target_map)} · {rules}"


@dataclass(frozen=True)
class Pick:
    """Выбор в окне цели: артикуляция целевой карты (по нормализованному имени) или конкретная нота."""
    articulation: str | None = None
    note: int | None = None


# --- таблица правил ---

class RulesModel(QAbstractTableModel):
    """Строки таблицы правил над рабочей копией профиля (правит её на месте).

    С исходной картой — по строке на каждую её ноту, по группам instrument_group(); правила для нот вне
    исходной карты — в группе «Not in the source map». Без исходной карты — по строке на правило, без групп.
    Удалённые ноты — в сворачиваемой секции «Deleted» внизу.
    """

    edited = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.profile: RemapProfile | None = None
        self.suggestions: dict[int, Suggestion] = {}
        self.issues: dict[int, list[ProfileIssue]] = {}
        self.deleted_collapsed = True
        self.rows: list[LayoutRow] = []
        self._note_rows: dict[int, int] = {}

    def set_profile(self, p: RemapProfile | None) -> None:
        self.profile = p
        self.recompute()
        self.relayout()

    def recompute(self) -> None:
        """Подсказки и замечания (после смены карт или правил)."""
        p = self.profile
        self.suggestions = ({s.src: s for s in suggest_rules(p.source_map, p.target_map)}
                            if p is not None and p.source_map is not None and p.target_map is not None else {})
        self.issues = {}
        if p is not None:
            for i in validate_profile(p):
                if i.code != NO_RULE:
                    self.issues.setdefault(i.note, []).append(i)

    def relayout(self) -> None:
        """Перестроить строки (после удаления/возврата нот и смены карт): строки переходят между секциями."""
        self.beginResetModel()
        self.rows = self._layout()
        self._note_rows = {r.note: i for i, r in enumerate(self.rows) if not r.is_header}
        self.endResetModel()

    def _layout(self) -> list[LayoutRow]:
        p = self.profile
        if p is None:
            return []
        src = p.source_map
        notes = sorted(src.names) + sorted(n for n in p.rules if n not in src.names) if src else sorted(p.rules)
        deleted = [n for n in notes if self.rule(n) == Rule.delete()]
        active = [n for n in notes if self.rule(n) != Rule.delete()]
        rows = group_rows(src.names, active, "Not in the source map") if src else [LayoutRow(None, n) for n in active]
        if deleted:
            arrow = "▸" if self.deleted_collapsed else "▾"
            rows.append(LayoutRow(DELETED_GROUP, None, f"{arrow} Deleted ({len(deleted)})"))
            if not self.deleted_collapsed:
                rows.extend(LayoutRow(DELETED_GROUP, n) for n in deleted)
        return rows

    def toggle_deleted(self) -> None:
        self.deleted_collapsed = not self.deleted_collapsed
        self.relayout()

    def refresh(self) -> None:
        """Правила изменились без переходов между секциями — пересчитать и перерисовать."""
        self.recompute()
        if self.rows:
            self.dataChanged.emit(self.index(0, 0), self.index(len(self.rows) - 1, len(COLUMNS) - 1))

    # --- доступ ---

    def rule(self, n: int) -> Rule | None:
        return self.profile.rules.get(n) if self.profile is not None else None

    def row_at(self, row: int) -> LayoutRow:
        return self.rows[row]

    def note_at(self, row: int) -> int | None:
        return self.rows[row].note if 0 <= row < len(self.rows) else None

    def note_index(self, note: int, col: int) -> QModelIndex:
        return self.index(self._note_rows[note], col)

    def has_row(self, note: int) -> bool:
        return note in self._note_rows

    def source_name(self, n: int) -> str | None:
        src = self.profile.source_map
        return src.names.get(n) if src is not None else None

    def target_text(self, n: int) -> str:
        rule, tgt = self.rule(n), self.profile.target_map
        if rule is None:
            return "kept as is"
        if rule.action == "delete":
            return "deleted"
        if rule.action == "keep":
            name = tgt.names.get(n) if tgt is not None else None
            return f"same number · {name}" if name else "same number"
        if tgt is None:
            return f"→ {rule.dst}"
        name = tgt.names.get(rule.dst)
        return f"{name} · {rule.dst}" if name else f"{rule.dst} — not in the target map"

    def status_text(self, n: int) -> str:
        rule, s = self.rule(n), self.suggestions.get(n)
        if rule is None:
            text = STATUS_TEXT[s.kind] if s is not None else "Unassigned"
        elif rule.action == "delete":
            text = "Deleted"
        elif rule.action == "keep":
            text = "Kept"
        elif s is not None and s.dst == rule.dst and s.kind in ("exact", "probable"):
            text = f"Mapped · {s.kind}"
        else:
            text = "Mapped"
        return f"⚠ {text}" if n in self.issues else text

    # --- Qt ---

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.rows)

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
        if not index.isValid() or self.profile is None:
            return None
        row = self.rows[index.row()]
        if row.is_header:
            if role == Qt.ItemDataRole.ToolTipRole and row.group == DELETED_GROUP:
                return "Click to show or hide deleted notes"
            return header_data(row, index.column(), role)
        n, col = row.note, index.column()
        rule = self.rule(n)
        if role == Qt.ItemDataRole.DisplayRole:
            if col == COL_NOTE:
                return str(n)
            if col == COL_PITCH:
                return pitch_name(n)
            if col == COL_SOURCE:
                return self.source_name(n) or ("—" if self.profile.source_map is None else "")
            if col == COL_TARGET:
                return self.target_text(n)
            return self.status_text(n)
        if role == Qt.ItemDataRole.ForegroundRole:
            if rule == Rule.delete():
                return QColor(TOKENS["text_faint"])
            if col == COL_TARGET and rule is None:
                return QColor(TOKENS["text_faint"])
            if col == COL_STATUS and rule is None:
                s = self.suggestions.get(n)
                return QColor(TOKENS["warning"] if s is not None and s.kind == "ambiguous" else TOKENS["text_muted"])
            return None
        if role == Qt.ItemDataRole.BackgroundRole and n in self.issues:
            return QColor(TOKENS["warning_bg"])
        if role == Qt.ItemDataRole.FontRole and col == COL_TARGET and rule is None:
            f = QFont()
            f.setItalic(True)
            return f
        if role == Qt.ItemDataRole.TextAlignmentRole and col in (COL_NOTE, COL_PITCH):
            return int(Qt.AlignmentFlag.AlignCenter)
        if role == Qt.ItemDataRole.ToolTipRole:
            lines = [i.message for i in self.issues.get(n, [])]
            s = self.suggestions.get(n)
            if rule is None and s is not None and s.kind == "ambiguous":
                lines.append(f'"{s.target_name}" is on several notes in the target map: choose it in Target '
                             "and pick the note to write to")
            return "\n".join(lines) or None
        return None

    def flags(self, index):
        if not index.isValid() or self.profile is None:
            return Qt.ItemFlag.NoItemFlags
        if self.rows[index.row()].is_header:
            return Qt.ItemFlag.ItemIsEnabled
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable


# --- выбор цели ---

class TargetPicker(QDialog):
    """Окно выбора цели: поиск по целевой карте, группы инструментов, по строке на артикуляцию
    (с номерами её нот). У артикуляции на нескольких нотах можно раскрыть ноты и выбрать конкретную."""

    def __init__(self, parent, target: NoteMap, count: int) -> None:
        super().__init__(parent)
        self.setWindowTitle("Choose target")
        self.resize(460, 560)
        self.result_pick: Pick | None = None
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search the target map: name or note number")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.itemActivated.connect(lambda *_: self._accept())
        self.tree.setToolTip(f"{count} source note(s) will be mapped. Expand an articulation on several notes "
                             "to pick a specific note instead of its Write to note (*)")
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        box = QVBoxLayout(self)
        box.addWidget(self.search)
        box.addWidget(self.tree, stretch=1)
        box.addWidget(buttons)
        self._fill(target)
        self.search.setFocus()

    def _fill(self, target: NoteMap) -> None:
        groups: dict[str, QTreeWidgetItem] = {}
        for key, notes in sorted(articulations(target).items(), key=lambda kv: kv[1][0]):
            label = target.names[notes[0]]
            g = instrument_group(label)
            parent = self.tree.invisibleRootItem()
            if g:
                gkey = normalize_name(g)
                if gkey not in groups:
                    groups[gkey] = QTreeWidgetItem(self.tree, [g.upper()])
                    groups[gkey].setFlags(Qt.ItemFlag.ItemIsEnabled)
                    groups[gkey].setExpanded(True)
                parent = groups[gkey]
            wt = [n for n in notes if n in target.primary]
            marks = ", ".join(f"{n}*" if n in wt else str(n) for n in notes)
            item = QTreeWidgetItem(parent, [f"{label}    {marks}"])
            item.setData(0, Qt.ItemDataRole.UserRole, Pick(articulation=key))
            item.setData(0, Qt.ItemDataRole.UserRole + 1, f"{normalize_name(label)} {' '.join(map(str, notes))}")
            if len(notes) > 1:
                item.setToolTip(0, "Several notes. * = Write to note. Expand to pick a specific note")
                for n in notes:
                    child = QTreeWidgetItem(item, [f"{n} ({pitch_name(n)})" + ("  · Write to" if n in wt else "")])
                    child.setData(0, Qt.ItemDataRole.UserRole, Pick(note=n))

    def _filter(self, text: str) -> None:
        q = normalize_name(text)
        root = self.tree.invisibleRootItem()
        for i in range(root.childCount()):
            top = root.child(i)
            if top.data(0, Qt.ItemDataRole.UserRole) is not None:  # плоский список (нет групп)
                top.setHidden(not self._match(top, q))
                continue
            any_visible = False
            for j in range(top.childCount()):
                item = top.child(j)
                visible = self._match(item, q)
                item.setHidden(not visible)
                any_visible |= visible
            top.setHidden(not any_visible)

    @staticmethod
    def _match(item: QTreeWidgetItem, q: str) -> bool:
        if not q:
            return True
        hay = item.data(0, Qt.ItemDataRole.UserRole + 1) or ""
        return q in hay.split() if q.isdigit() else q in hay

    def _accept(self) -> None:
        item = self.tree.currentItem()
        pick = item.data(0, Qt.ItemDataRole.UserRole) if item is not None else None
        if pick is None:
            return
        self.result_pick = pick
        self.accept()


class UnassignedDialog(QDialog):
    """Диалог сохранения: неназначенные ноты, которые при keep попадут на другой звук или на отсутствующую ноту.
    Флажки (по умолчанию сняты) — какие из них удалить; остальные неназначенные ноты останутся на своих номерах."""

    def __init__(self, parent, total: int, warnings: list[KeepWarning], target: str) -> None:
        super().__init__(parent)
        self.setWindowTitle("Save profile")
        self.resize(640, 480)
        self.to_delete: set[int] = set()
        self.warnings = warnings
        text = QLabel(f"{total} note(s) will stay on their numbers. {len(warnings)} of them land on a "
                      f"different sound or a missing note in {target}.")
        text.setWordWrap(True)
        self.table = QTableWidget(len(warnings), 4)
        self.table.setHorizontalHeaderLabels(["", "", "NOTE", "SOURCE NAME → TARGET AT THIS NUMBER"])
        self.table.verticalHeader().hide()
        self.table.setShowGrid(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.horizontalHeaderItem(0).setToolTip("Checked notes are deleted from converted files")
        for row, w in enumerate(warnings):
            check = QTableWidgetItem()
            check.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
            check.setCheckState(Qt.CheckState.Unchecked)
            check.setToolTip("Delete this note")
            marker = QTableWidgetItem(w.marker)
            marker.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            marker.setToolTip(MARKER_TIPS[w.marker])
            marker.setForeground(QColor(TOKENS["error" if w.marker == DIFFERENT_INSTRUMENT else "warning"]))
            note = QTableWidgetItem(str(w.note))
            note.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            names = QTableWidgetItem(f"{w.source_name}  →  {w.target_name or 'no note'}")
            for col, item in enumerate((check, marker, note, names)):
                self.table.setItem(row, col, item)
        header = self.table.horizontalHeader()
        for col, width in ((0, 32), (1, 28), (2, 52)):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.Fixed)
            self.table.setColumnWidth(col, width)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table.itemChanged.connect(self._update_buttons)

        buttons = QDialogButtonBox()
        self.delete_btn = buttons.addButton("Delete checked and save", QDialogButtonBox.ButtonRole.DestructiveRole)
        self.keep_btn = buttons.addButton("Keep all and save", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        self.delete_btn.clicked.connect(self.delete_checked)
        self.keep_btn.clicked.connect(self.keep_all)
        buttons.rejected.connect(self.reject)
        self.keep_btn.setDefault(True)
        box = QVBoxLayout(self)
        box.addWidget(text)
        box.addWidget(self.table, stretch=1)
        box.addWidget(buttons)
        self.table.setVisible(bool(warnings))
        self.delete_btn.setVisible(bool(warnings))
        self._update_buttons()

    def checked(self) -> set[int]:
        return {w.note for row, w in enumerate(self.warnings)
                if self.table.item(row, 0).checkState() == Qt.CheckState.Checked}

    def set_checked(self, notes: set[int]) -> None:
        for row, w in enumerate(self.warnings):
            self.table.item(row, 0).setCheckState(
                Qt.CheckState.Checked if w.note in notes else Qt.CheckState.Unchecked)

    def _update_buttons(self, *_) -> None:
        self.delete_btn.setEnabled(bool(self.checked()))

    def delete_checked(self) -> None:
        self.to_delete = self.checked()
        self.accept()

    def keep_all(self) -> None:
        self.to_delete = set()
        self.accept()


# --- страница ---

class ProfilesPage(QWidget):
    """Список профилей (слева) и редактор выбранного профиля (справа)."""

    dirty_changed = Signal(bool)
    profiles_changed = Signal()  # профиль сохранён, создан, переименован или удалён

    def __init__(self, storage: Storage) -> None:
        super().__init__()
        self.storage = storage
        self.current: str | None = None        # ID профиля в хранилище
        self.base: RemapProfile | None = None  # последнее сохранённое состояние
        self.work: RemapProfile | None = None  # рабочая копия, её правит таблица
        self._ids: list[str] = []
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
        self.duplicate_btn = QPushButton("Duplicate")
        self.rename_btn = QPushButton("Rename")
        self.delete_btn = QPushButton("Delete")
        self.new_btn.clicked.connect(self.new_profile)
        self.duplicate_btn.clicked.connect(self.duplicate)
        self.rename_btn.clicked.connect(self.rename)
        self.delete_btn.clicked.connect(self.delete)
        grid = QGridLayout()
        grid.setSpacing(6)
        for i, b in enumerate((self.new_btn, self.duplicate_btn, self.rename_btn, self.delete_btn)):
            grid.addWidget(b, i // 2, i % 2)
        left.addLayout(grid)
        left_box = QWidget()
        left_box.setLayout(left)
        left_box.setFixedWidth(290)
        root.addWidget(left_box)

        right = QVBoxLayout()
        right.setSpacing(6)
        self.title = QLabel("No profile selected")
        self.title.setObjectName("mapTitle")
        self.dirty_label = QLabel("● Unsaved changes")
        self.dirty_label.setObjectName("dirty")
        head = QHBoxLayout()
        head.addWidget(self.title, stretch=1)
        head.addWidget(self.dirty_label)
        right.addLayout(head)

        self.source_btn = QPushButton()
        self.target_btn = QPushButton()
        maps_row = QHBoxLayout()
        for side, btn, caption in ((SOURCE, self.source_btn, "SOURCE MAP"), (TARGET, self.target_btn, "TARGET MAP")):
            menu = QMenu(btn)
            menu.aboutToShow.connect(lambda m=menu, s=side: self._fill_map_menu(m, s))
            btn.setMenu(menu)
            col = QVBoxLayout()
            col.setSpacing(2)
            label = QLabel(caption)
            label.setObjectName("section")
            col.addWidget(label)
            col.addWidget(btn)
            maps_row.addLayout(col, stretch=1)
            if side == SOURCE:
                arrow = QLabel("→")
                arrow.setObjectName("icon")
                maps_row.addWidget(arrow, alignment=Qt.AlignmentFlag.AlignBottom)
        self.source_btn.setToolTip("The layout the MIDI file was made for (e.g. Guitar Pro 8 export)")
        self.target_btn.setToolTip("The layout of the plugin the converted file is for")
        right.addLayout(maps_row)

        self.accept_btn = QPushButton("Accept suggestions")
        self.accept_btn.clicked.connect(self.accept_suggestions)
        self.assign_btn = QPushButton("Assign target…")
        self.assign_btn.setToolTip("Choose a target for all selected rows (many-to-one)")
        self.assign_btn.clicked.connect(self.assign_selected)
        self.summary = QLabel()
        self.summary.setObjectName("muted")
        tools = QHBoxLayout()
        tools.addWidget(self.summary, stretch=1)
        tools.addWidget(self.assign_btn)
        tools.addWidget(self.accept_btn)
        right.addLayout(tools)

        self.model = RulesModel()
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(26)
        self.table.setShowGrid(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._context_menu)
        self.table.doubleClicked.connect(lambda idx: self._on_activated(idx))
        self.table.clicked.connect(self._on_clicked)
        self.table.installEventFilter(self)
        header = self.table.horizontalHeader()
        header.setHighlightSections(False)
        for col, width in ((COL_NOTE, 56), (COL_PITCH, 56), (COL_STATUS, 170)):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.Fixed)
            self.table.setColumnWidth(col, width)
        header.setSectionResizeMode(COL_SOURCE, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(COL_TARGET, QHeaderView.ResizeMode.Stretch)
        self.model.modelReset.connect(lambda: update_spans(self.table, len(COLUMNS)))
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
        if obj is self.table and event.type() == QEvent.Type.KeyPress and self.work is not None:
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self.assign_selected()
                return True
            if event.key() == Qt.Key.Key_Delete:
                self.delete_notes(self.selected_notes())
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
            self, "Unsaved changes", f'Save changes to the profile "{self.work.name}"?',
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save)
        return {QMessageBox.StandardButton.Save: "save",
                QMessageBox.StandardButton.Discard: "discard"}.get(answer, "cancel")

    def pick_target(self, notes: list[int]) -> Pick | None:
        dlg = TargetPicker(self, self.work.target_map, len(notes))
        return dlg.result_pick if dlg.exec() == QDialog.DialogCode.Accepted else None

    def ask_note_number(self, notes: list[int]) -> int | None:
        """Цель без целевой карты — просто номер ноты 0–127."""
        rule = self.work.rules.get(notes[0])
        default = rule.dst if rule is not None and rule.action == "map" else notes[0]
        value, ok = QInputDialog.getInt(self, "Target note", f"Map {len(notes)} note(s) to note number (0–127):",
                                        default, 0, 127)
        return value if ok else None

    def ask_write_to(self, name: str, notes: list[int]) -> int | None:
        """Артикуляция на нескольких нотах без Write to: на какую ноту писать (ответ запомнится в профиле)."""
        items = [f"{n} · {pitch_name(n)}" for n in notes]
        dlg = QInputDialog(self)
        dlg.setWindowTitle("Write to")
        dlg.setLabelText(f'"{name}" is on several notes. Write converted notes to:')
        dlg.setComboBoxItems(items)
        dlg.setComboBoxEditable(False)
        dlg.setToolTip("The choice is saved in this profile's copy of the target map, not in the map itself")
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return None
        return notes[items.index(dlg.textValue())]

    def ask_unassigned(self, total: int, warnings: list[KeepWarning]) -> set[int] | None:
        """Перед сохранением: какие из проблемных нот удалить. None — отмена; пустое множество — оставить всё."""
        dlg = UnassignedDialog(self, total, warnings, map_summary(self.work.target_map))
        return dlg.to_delete if dlg.exec() == QDialog.DialogCode.Accepted else None

    def show_error(self, text: str) -> None:
        QMessageBox.warning(self, "MidiRemap", text)

    # --- список ---

    def reload_list(self, select: str | None = None) -> None:
        """Перестроить список; выделение — select или текущий профиль (сигналы при этом не идут)."""
        select = select or self.current
        self.list.blockSignals(True)
        self.list.clear()
        try:
            entries, issues = self.storage.list_profiles()
        except OSError as e:
            entries, issues = [], []
            self.set_status(f"Cannot read the profiles folder: {e}", "error")
        self._ids = [e.id for e in entries]
        for e in entries:
            try:
                p = self.storage.load_profile(e.id)
            except (OSError, ValueError) as err:
                self._item(e.name, f"cannot read: {err}", None)
                continue
            self._item(p.name, profile_summary(p), e.id)
        if not entries:
            self._item("No profiles yet", "Click New to create one", None)
        if issues:
            self.set_status(f"Skipped unreadable profiles ({len(issues)}): "
                            + ", ".join(i.path.name for i in issues), "error")
        for i in range(self.list.count()):
            if select is not None and self.list.item(i).data(REF_ROLE) == select:
                self.list.setCurrentRow(i)
                break
        self.list.blockSignals(False)
        self._mark_dirty_item()

    def _item(self, title: str, subtitle: str, profile_id: str | None) -> None:
        item = QListWidgetItem(title)
        item.setData(NAME_ROLE, title)
        item.setData(SUBTITLE_ROLE, subtitle)
        item.setData(REF_ROLE, profile_id)
        item.setData(HEADER_ROLE, False)
        item.setToolTip(wrapped_tooltip(f"{title}\n{subtitle}"))
        if profile_id is None:
            item.setFlags(Qt.ItemFlag.NoItemFlags)
        self.list.addItem(item)

    def _mark_dirty_item(self) -> None:
        """«•» перед именем профиля с несохранёнными правками; подзаголовок — сохранённое состояние."""
        for i in range(self.list.count()):
            item = self.list.item(i)
            name = item.data(NAME_ROLE)
            if name is None:
                continue
            text = f"• {name}" if self._dirty and item.data(REF_ROLE) == self.current else name
            if item.text() != text:
                item.setText(text)

    def _on_current_changed(self, cur: QListWidgetItem | None, prev: QListWidgetItem | None) -> None:
        profile_id = cur.data(REF_ROLE) if cur is not None else None
        if profile_id is None or profile_id == self.current:
            return
        if not self.maybe_leave():
            self.list.blockSignals(True)
            self.list.setCurrentItem(prev)
            self.list.blockSignals(False)
            return
        self.open(profile_id)

    def select(self, profile_id: str) -> None:
        """Выделить и открыть профиль (с вопросом о несохранённых правках)."""
        for i in range(self.list.count()):
            if self.list.item(i).data(REF_ROLE) == profile_id:
                self.list.setCurrentRow(i)
                return

    # --- редактор ---

    @property
    def dirty(self) -> bool:
        return self._dirty

    def open(self, profile_id: str) -> bool:
        try:
            p = self.storage.load_profile(profile_id)
        except (OSError, ValueError) as e:
            self.show_error(f"Cannot open the profile:\n\n{e}")
            return False
        self.current, self.base = profile_id, p
        self.work = copy.deepcopy(p)
        self.model.deleted_collapsed = True
        self.model.set_profile(self.work)
        self._update_state()
        self.set_status("")
        return True

    def close_profile(self) -> None:
        self.current = self.base = self.work = None
        self.model.set_profile(None)
        self._update_state()

    def maybe_leave(self) -> bool:
        """Перед уходом с профиля: несохранённые правки — спросить. False — остаться."""
        if not self.dirty:
            return True
        answer = self.ask_save_changes()
        if answer == "save":
            return self.save()
        if answer == "discard":
            self.revert()
            return True
        return False

    def revert(self) -> None:
        if self.base is None:
            return
        self.work = copy.deepcopy(self.base)
        self.model.set_profile(self.work)
        self._update_state()

    def unassigned(self) -> list[int]:
        """Ноты исходной карты без правила."""
        src = self.work.source_map if self.work is not None else None
        return [] if src is None else [n for n in sorted(src.names) if n not in self.work.rules]

    def save(self) -> bool:
        """Сохранить. Ноты исходной карты без правила: диалог, затем явные keep (with_explicit_keeps) —
        при конвертации спрашивать придётся только о нотах, которых нет в исходной карте."""
        if self.work is None or self.current is None:
            return False
        work = self.work
        unassigned = self.unassigned()
        if unassigned:
            to_delete = self.ask_unassigned(len(unassigned), unassigned_keep_warnings(work))
            if to_delete is None:
                return False
            for n in to_delete:  # только отмеченные; остальные неназначенные станут явным keep
                work.rules[n] = Rule.delete()
        out = with_explicit_keeps(work)
        try:
            self.storage.save_profile(out, profile_id=self.current, overwrite=True)
        except (OSError, ValueError) as e:
            self.show_error(f"Cannot save the profile:\n\n{e}")
            return False
        self.base = out
        self.work = copy.deepcopy(out)
        self.model.profile = self.work
        self.model.recompute()
        self.model.relayout()
        self.reload_list()
        self._update_state()
        self.profiles_changed.emit()
        self.set_status(f'Saved "{out.name}".', "ok")
        return True

    def _changed(self, relayout: bool = False) -> None:
        if relayout:
            self.model.recompute()
            self.model.relayout()
        else:
            self.model.refresh()
        self._update_state()

    def _update_state(self) -> None:
        has = self.work is not None
        dirty = has and self.work.to_dict() != self.base.to_dict()
        if dirty != self._dirty:
            self._dirty = dirty
            self.dirty_changed.emit(dirty)
        self._mark_dirty_item()
        self.dirty_label.setVisible(dirty)
        self.save_btn.setEnabled(dirty)
        self.revert_btn.setEnabled(dirty)
        self.duplicate_btn.setEnabled(has)
        self.rename_btn.setEnabled(has)
        self.delete_btn.setEnabled(has)
        for btn in (self.source_btn, self.target_btn, self.assign_btn):
            btn.setEnabled(has)
        both = has and self.work.source_map is not None and self.work.target_map is not None
        self.accept_btn.setEnabled(both)
        self.accept_btn.setToolTip(ACCEPT_TIP if both else "Needs both a source and a target map")
        if not has:
            self.title.setText("No profile selected")
            self.source_btn.setText("—")
            self.target_btn.setText("—")
            self.summary.setText("")
            self.issues_label.setText("")
            return
        self.title.setText(self.work.name)
        self.source_btn.setText(map_summary(self.work.source_map))
        self.target_btn.setText(map_summary(self.work.target_map))
        n_rules = len(self.work.rules)
        parts = [f"{n_rules} rule" + ("" if n_rules == 1 else "s")]
        if self.work.source_map is not None:
            parts.append(f"{len(self.unassigned())} unassigned")
        self.summary.setText(" · ".join(parts))
        self.summary.setToolTip("" if self.work.source_map is not None else
                                "No source map: the table shows one row per rule")
        issues = [i for lst in self.model.issues.values() for i in lst]
        if issues:
            shown = [f"{i.message}" for i in issues[:6]]
            more = f"\n… and {len(issues) - 6} more" if len(issues) > 6 else ""
            self.issues_label.setText(f"{len(issues)} issue(s):\n" + "\n".join(shown) + more)
            self.issues_label.setToolTip("\n".join(i.message for i in issues))
        else:
            self.issues_label.setText("")
            self.issues_label.setToolTip("")
        repolish(self.issues_label, "state", "")

    # --- карты профиля ---

    def _fill_map_menu(self, menu: QMenu, side: str) -> None:
        menu.clear()
        menu.addAction("No map", lambda: self.choose_map(side, None))
        menu.addSection("Built-in templates")
        for tid, m in list_map_templates():
            menu.addAction(f"🔒  {m.name}", lambda t=tid: self.choose_map(side, MapRef(TEMPLATE, t)))
        menu.addSection("My maps")
        try:
            entries, _ = self.storage.list_maps()
        except OSError:
            entries = []
        for e in entries:
            menu.addAction(e.name, lambda i=e.id: self.choose_map(side, MapRef(USER, i)))
        if not entries:
            menu.addAction("No maps yet").setEnabled(False)

    def choose_map(self, side: str, ref: MapRef | None) -> bool:
        """Встроить в профиль копию карты (или убрать карту). Правила сохраняются; если они есть — спросить."""
        if self.work is None:
            return False
        m: NoteMap | None = None
        if ref is not None:
            try:
                m = load_map_template(ref.id) if ref.read_only else self.storage.load_map(ref.id)[0]
            except (OSError, ValueError, KeyError) as e:
                self.show_error(f"Cannot open the map:\n\n{e}")
                return False
            m = duplicate_map(m, m.name, from_template=ref.read_only)  # meta копируется, source сохраняется
        what = "source" if side == SOURCE else "target"
        if self.work.rules and not self.confirm(
                f"Change {what} map", f"The profile has {len(self.work.rules)} rule(s). Change the {what} map?",
                "The rules are kept. Problems with them will be shown under the table."):
            return False
        if side == SOURCE:
            self.work.source_map = m
        else:
            self.work.target_map = m
        self._changed(relayout=True)
        self.set_status(f"{what.capitalize()} map: {map_summary(m)}.")
        return True

    # --- правила ---

    def selected_notes(self) -> list[int]:
        rows = {i.row() for i in self.table.selectionModel().selectedRows()}
        return sorted(n for n in map(self.model.note_at, rows) if n is not None)

    def select_notes(self, notes: list[int]) -> None:
        """Выделить строки нот (для тестов и после перестройки таблицы)."""
        sel = self.table.selectionModel()
        sel.clearSelection()
        selection = QItemSelection()
        for n in notes:
            if self.model.has_row(n):
                idx = self.model.note_index(n, 0)
                selection.select(idx, self.model.note_index(n, len(COLUMNS) - 1))
        sel.select(selection, QItemSelectionModel.SelectionFlag.Select)

    def _on_clicked(self, idx: QModelIndex) -> None:
        row = self.model.row_at(idx.row()) if idx.isValid() else None
        if row is not None and row.is_header and row.group == DELETED_GROUP:
            self.model.toggle_deleted()

    def _on_activated(self, idx: QModelIndex) -> None:
        if idx.isValid() and not self.model.row_at(idx.row()).is_header:
            self.assign_selected()

    def _context_menu(self, pos) -> None:
        notes = self.selected_notes()
        if not notes:
            return
        menu = QMenu(self.table)
        menu.addAction("Assign target…", self.assign_selected)
        menu.addSeparator()
        menu.addAction("Delete note" if len(notes) == 1 else f"Delete {len(notes)} notes",
                       lambda: self.delete_notes(notes))
        menu.addAction("Clear rule" if len(notes) == 1 else f"Clear {len(notes)} rules",
                       lambda: self.clear_rules(notes))
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def assign_selected(self) -> bool:
        notes = self.selected_notes()
        if self.work is None or not notes:
            return False
        if self.work.target_map is None:
            dst = self.ask_note_number(notes)
            return dst is not None and self.assign_note(notes, dst)
        pick = self.pick_target(notes)
        if pick is None:
            return False
        if pick.note is not None:
            return self.assign_note(notes, pick.note)
        return self.assign_articulation(notes, pick.articulation)

    def assign_articulation(self, notes: list[int], articulation: str) -> bool:
        """Цель — артикуляция целевой карты. Одна нота — на неё; несколько с Write to — на Write to;
        несколько без Write to — спросить один раз и запомнить как primary в КОПИИ целевой карты профиля
        (карта пользователя в хранилище не меняется)."""
        tgt = self.work.target_map
        candidates = articulations(tgt).get(normalize_name(articulation), [])
        if not candidates:
            return False
        flagged = [n for n in candidates if n in tgt.primary]
        if len(candidates) == 1:
            dst = candidates[0]
        elif len(flagged) == 1:
            dst = flagged[0]
        else:
            dst = self.ask_write_to(tgt.names[candidates[0]], candidates)
            if dst is None:
                return False
            tgt.primary.difference_update(candidates)
            tgt.primary.add(dst)
        return self.assign_note(notes, dst)

    def assign_note(self, notes: list[int], dst: int) -> bool:
        was_deleted = any(self.work.rules.get(n) == Rule.delete() for n in notes)
        for n in notes:
            self.work.rules[n] = Rule.map_to(dst)
        self._changed(relayout=was_deleted)
        if was_deleted:
            self.select_notes(notes)
        self.set_status(f"{len(notes)} note(s) → {dst}.")
        return True

    def delete_notes(self, notes: list[int]) -> None:
        if self.work is None or not notes:
            return
        for n in notes:
            self.work.rules[n] = Rule.delete()
        self._changed(relayout=True)
        self.set_status(f"Deleted {len(notes)} note(s).")

    def clear_rules(self, notes: list[int]) -> None:
        if self.work is None or not notes:
            return
        was_deleted = any(self.work.rules.get(n) == Rule.delete() for n in notes)
        for n in notes:
            self.work.rules.pop(n, None)
        # без исходной карты строка существует только пока есть правило
        self._changed(relayout=was_deleted or self.work.source_map is None)
        self.set_status(f"Cleared {len(notes)} rule(s).")

    def accept_suggestions(self) -> tuple[int, int, int] | None:
        """Правила из точных и вероятных подсказок (существующие не меняются).
        Возвращает (добавлено, нужен выбор Write to, без совпадения) — среди нот без правила."""
        w = self.work
        if w is None or w.source_map is None or w.target_map is None:
            return None
        suggestions = suggest_rules(w.source_map, w.target_map)
        new = apply_suggestions(w, suggestions)
        added = len(new.rules) - len(w.rules)
        rest = [s for s in suggestions if s.src not in new.rules]
        ambiguous = sum(1 for s in rest if s.kind == "ambiguous")
        none = sum(1 for s in rest if s.kind == "none")
        w.rules = new.rules
        self._changed()
        self.set_status(f"{added} mapped, {ambiguous} need a Write to choice, {none} without a match.", "ok")
        return added, ambiguous, none

    # --- действия со списком ---

    def ask_unique_name(self, title: str, default: str, exclude_id: str | None = None) -> str | None:
        """Имя профиля; ID (имя файла) не должен совпадать с существующим профилем. None — отмена."""
        taken = {i.casefold() for i in self._ids} - {(exclude_id or "").casefold()}
        while True:
            text = self.ask_text(title, "Profile name:", default)
            if text is None:
                return None
            text = text.strip()
            if not text:
                self.show_error("The name cannot be empty.")
                continue
            if sanitize_id(text).casefold() in taken:
                self.show_error(f'A profile named "{text}" already exists. Choose another name.')
                default = text
                continue
            return text

    def _add_and_open(self, p: RemapProfile) -> str | None:
        try:
            profile_id = self.storage.save_profile(p)
        except (OSError, ValueError) as e:
            self.show_error(f"Cannot save the profile:\n\n{e}")
            return None
        self.reload_list(select=profile_id)
        self.open(profile_id)
        self.profiles_changed.emit()
        return profile_id

    def new_profile(self) -> None:
        if not self.maybe_leave():
            return
        name = self.ask_unique_name("New profile", "New profile")
        if name is None:
            return
        if self._add_and_open(RemapProfile(name=name)):
            self.set_status(f'Created "{name}".', "ok")

    def duplicate(self) -> None:
        if self.base is None or not self.maybe_leave():
            return
        src = self.base
        name = self.ask_unique_name("Duplicate profile", f"{src.name} (copy)")
        if name is None:
            return
        p = copy.deepcopy(src)
        p.name = name
        if self._add_and_open(p):
            self.set_status(f'Created "{name}" from "{src.name}".', "ok")

    def rename(self) -> None:
        if self.current is None or not self.maybe_leave():
            return
        old_id, old_name = self.current, self.base.name
        name = self.ask_unique_name("Rename profile", old_name, exclude_id=old_id)
        if name is None or name == old_name:
            return
        p = copy.deepcopy(self.base)
        p.name = name
        new_id = sanitize_id(name)
        try:
            if new_id.casefold() == old_id.casefold():  # тот же файл (Windows не различает регистр)
                self.storage.save_profile(p, profile_id=old_id, overwrite=True)
                new_id = old_id
            else:
                self.storage.save_profile(p, profile_id=new_id)
                self.storage.delete_profile(old_id)
        except (OSError, ValueError) as e:
            self.show_error(f"Cannot rename the profile:\n\n{e}")
            return
        self.current = None
        self.reload_list(select=new_id)
        self.open(new_id)
        self.profiles_changed.emit()
        self.set_status(f'Renamed "{old_name}" to "{name}".', "ok")

    def delete(self) -> None:
        if self.current is None:
            return
        name = self.base.name
        if not self.confirm("Delete profile", f'Delete the profile "{name}"? This cannot be undone.'):
            return
        try:
            self.storage.delete_profile(self.current)
        except OSError as e:
            self.show_error(f"Cannot delete the profile:\n\n{e}")
            return
        self.close_profile()
        self.reload_list()
        self.profiles_changed.emit()
        self.set_status(f'Deleted "{name}".', "ok")

    def set_status(self, text: str, state: str = "") -> None:
        self.status.setText(text)
        repolish(self.status, "state", state)
