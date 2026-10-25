"""Менеджер и редактор профилей ремапа (PySide6). Раскладка (8b3b1): одна строка заголовка —
[профиль ▾] [⋯] [→ N | ← M] статус … [↻] [Revert] [Save]; под ней вид «кабелями» (cable_view.py): над левым
пулом — карта источника, над сценой — счётчик правил и панель подсказок, над правым пулом — карта цели.
Всё остальное по высоте — сцене.

Направление (8b3b2): переключатель «→ N | ← M» (N, M — ноты без правила в этом направлении, missing_rules).
Профиль открывается в →; переключение — не шаг отмены. В ← вид правит профиль work.reversed(): ядро вызывается
на нём (assign_plan, assign_to_articulation, with_write_to, connect_same_numbers, apply_suggested), результат
пишется назад — карта цели обратного профиля это КОПИЯ ИСХОДНОЙ карты (туда ложится Write to), его правила —
обратные правила (_put). Подсказки, свёрнутость вида и «скрыть подсказки» — свои у каждого направления.

Логики профилей здесь нет — только вызовы midiremap.core (suggestion_targets, plan_suggestions, apply_suggested,
assign_plan, assign_to_articulation, connect_same_numbers, with_write_to) и midiremap.storage. Диалоги вынесены
в методы ask_*/confirm/show_error, чтобы тесты могли их подменить.

Подсказки (8b2d): когда пользователь задал обе карты (новый профиль или смена карты), ноты без правила, чьё имя
совпало с целевой картой, показываются пунктирными кабелями, над сценой — панель «N matches · Apply · ✕» (не
диалог). Apply — по логике назначения 8b2c (одним шагом отмены); подсказки, которым нужен выбор Write to,
пропускаются и остаются пунктиром. ✕ скрывает подсказки для этой пары карт до повторного открытия профиля.
Открытие существующего профиля панель не показывает. Нота, получившая правило, из подсказок выбывает.

Отмена/повтор (Ctrl+Z / Ctrl+Y) — один стек на оба направления: снимки рабочей копии (профили маленькие, снимок
хранит и обратные правила) вместе с подсказками обоих направлений и направлением, в котором сделан шаг: каждое
действие, изменившее профиль, кладёт снимок «до» (декоратор _undoable; вложенные вызовы — один шаг). Отмена и
повтор сначала переключают вид на направление шага (только вид, не шаг) — отменённое всегда видно. Стек
очищается при открытии другого профиля, Save его не очищает (шаг сохранения тоже отменяется).
"""
from __future__ import annotations

import copy
import functools

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QKeySequence, QPainter, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView, QButtonGroup, QComboBox, QDialog, QDialogButtonBox, QFrame, QHBoxLayout, QHeaderView, QInputDialog,
    QLabel, QLineEdit, QMenu, QMessageBox, QPushButton, QSizePolicy, QTableWidget, QTableWidgetItem, QVBoxLayout,
    QWidget,
)

from ..core.notemap import NoteMap, duplicate_map
from ..core.pitch import pitch_name
from ..core.profile import (
    FORWARD, REVERSE, RemapProfile, Rule, assign_plan, assign_to_articulation, connect_same_numbers, missing_rules,
    normalized_reverse, primary_pairs, sync_reverse, with_forward_primary, with_primary_cable, with_write_to,
)
from ..core.suggest import apply_suggested, plan_suggestions, suggestion_targets
from ..storage import Storage, sanitize_id
from ..templates import list_map_templates, load_map_template
from .cable_view import CableEditor
from .maps_page import TEMPLATE, USER, MapRef, wrapped_tooltip
from .settings import ui_settings
from .theme import TOKENS, repolish

SOURCE, TARGET = "source", "target"
REFRESH_TIP = "Refresh layout"

ID_ROLE = Qt.ItemDataRole.UserRole           # ID профиля в хранилище (None — профиль не читается)
NAME_ROLE = Qt.ItemDataRole.UserRole + 3     # имя профиля без пометки «•»
SUBTITLE_ROLE = Qt.ItemDataRole.UserRole + 4  # «карты · N rules» сохранённого состояния (подсказка пункта)

UNDO_LIMIT = 200
UNDO_KEYS, REDO_KEYS = ("Ctrl+Z",), ("Ctrl+Y", "Ctrl+Shift+Z")
UNDO_TIP = "Undo (Ctrl+Z) · Redo (Ctrl+Y)"

MORE_TIP = "New, rename, duplicate or delete a profile"
SOURCE_TIP = "Source map: the layout the MIDI file was made for (e.g. Guitar Pro 8 export)\nClick to choose a map"
TARGET_TIP = "Target map: the layout of the plugin the converted file is for\nClick to choose a map"

SUGGEST_TIP = ("Notes whose names match the target map, shown as dashed cables.\n"
               "Apply connects them: a note whose number is in the target stays on it, "
               "the others go to the Write to note.")
DISMISS_TIP = "Hide the suggestions for these maps"

DIRECTION_SIDES = {FORWARD: "source", REVERSE: "target"}  # чьи ноты считает сегмент направления
DIRECTION_TIP = "{n} {side} note{s} {have} no rule in this direction"
DIRECTION_NO_MAP_TIP = "No {side} map: nothing to count in this direction"


def _undoable(fn):
    """Действие страницы над рабочей копией — один шаг отмены (если профиль изменился).
    Заданные обратные правила следуют за правкой прямых (sync_reverse) в том же шаге — кроме действий, которые
    сами согласовали обратные правила (_reverse_done, двойной клик). Затем обратные правила, равные выведенным,
    хранятся как None (normalized_reverse, как при чтении JSON). Правки в ← прямые правила не меняют —
    синхронизация для них ничего не делает, а отличающиеся от выведенных обратные правила становятся ручными."""
    @functools.wraps(fn)
    def wrapper(self, *args, **kwargs):
        if self.work is None or self._in_edit:
            return fn(self, *args, **kwargs)
        before = self._snapshot()
        self._in_edit = True
        self._reverse_done = False
        try:
            return fn(self, *args, **kwargs)
        finally:
            self._in_edit = False
            if self.work is not None:
                if not self._reverse_done:
                    self.work.reverse_rules = sync_reverse(before[0], self.work)
                self.work.reverse_rules = normalized_reverse(self.work)
            self._record(before)
    return wrapper


def _was(note: int, rule: Rule | None) -> str:
    """«was 60 → 62» / «was unassigned» / «was deleted» / «was kept» — прежнее правило ноты для статуса."""
    if rule is None:
        return "was unassigned"
    if rule.action == "map":
        return f"was {note} → {rule.dst}"
    return "was deleted" if rule.action == "delete" else "was kept"


def map_summary(m: NoteMap | None) -> str:
    return m.name if m is not None else "no map"


def profile_summary(p: RemapProfile, direction: str = FORWARD) -> str:
    """«<исходная карта> → <целевая карта> · N rules» (или «no maps» без обеих карт) в направлении direction:
    для REVERSE — карты наоборот и число обратных правил."""
    p = p.oriented(direction)
    n = len(p.rules)
    rules = f"{n} rule" + ("" if n == 1 else "s")
    if p.source_map is None and p.target_map is None:
        return f"no maps · {rules}"
    return f"{map_summary(p.source_map)} → {map_summary(p.target_map)} · {rules}"


def _pair_key(p: RemapProfile) -> tuple:
    """Пара карт профиля (для «скрыть подсказки для этих карт»)."""
    return tuple((m.name, tuple(sorted(m.names.items()))) for m in (p.source_map, p.target_map))


class DotsButton(QPushButton):
    """Кнопка «⋯» (меню действий с профилем): три точки рисуются сами — глиф шрифта на 100 % слишком мелкий.
    Цвет — как у текста кнопок-иконок (↻): приглушённый, при наведении — обычный."""
    DOT_R, DOT_GAP = 1.8, 6.0  # радиус точки и шаг между центрами, px

    def __init__(self, parent=None) -> None:
        super().__init__("", parent)
        self.setObjectName("iconButton")
        self.setMinimumWidth(40)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        token = "text_faint" if not self.isEnabled() else "text" if self.underMouse() or self.isDown() else "text_muted"
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(TOKENS[token]))
        c = QRectF(self.rect()).center()
        for k in (-1, 0, 1):
            p.drawEllipse(QPointF(c.x() + k * self.DOT_GAP, c.y()), self.DOT_R, self.DOT_R)


class UnassignedDialog(QDialog):
    """Диалог сохранения: ноты исходной карты без правила будут удалены. Флажок (по умолчанию снят) —
    оставить ноту на том же номере (явный keep)."""

    def __init__(self, parent, profile: RemapProfile, notes: list[int]) -> None:
        super().__init__(parent)
        self.setWindowTitle("Save profile")
        self.resize(640, 480)
        self.notes = sorted(notes)
        self.to_keep: set[int] = set()
        src, tgt = profile.source_map, profile.target_map
        n = len(self.notes)
        text = QLabel(f"{n} note{'' if n == 1 else 's'} {'has' if n == 1 else 'have'} no target "
                      "and will be removed.")
        text.setWordWrap(True)
        self.table = QTableWidget(n, 4)
        self.table.setHorizontalHeaderLabels(["", "NOTE", "SOURCE NAME", "TARGET AT THIS NUMBER"])
        self.table.verticalHeader().hide()
        self.table.setShowGrid(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.horizontalHeaderItem(0).setToolTip("Checked notes keep their numbers instead of being removed")
        for row, note in enumerate(self.notes):
            check = QTableWidgetItem()
            check.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
            check.setCheckState(Qt.CheckState.Unchecked)
            check.setToolTip("Keep on the same number")
            num = QTableWidgetItem(str(note))
            num.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            name = QTableWidgetItem(src.names.get(note, "") if src is not None else "")
            at = tgt.names.get(note) if tgt is not None else None
            target = QTableWidgetItem(at or "—")
            if at is None:
                target.setForeground(QColor(TOKENS["text_faint"]))
            for col, item in enumerate((check, num, name, target)):
                self.table.setItem(row, col, item)
        header = self.table.horizontalHeader()
        for col, width in ((0, 32), (1, 52)):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.Fixed)
            self.table.setColumnWidth(col, width)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        self.save_btn = buttons.button(QDialogButtonBox.StandardButton.Save)
        self.save_btn.setDefault(True)
        box = QVBoxLayout(self)
        box.addWidget(text)
        box.addWidget(self.table, stretch=1)
        box.addWidget(buttons)

    def checked(self) -> set[int]:
        return {n for row, n in enumerate(self.notes)
                if self.table.item(row, 0).checkState() == Qt.CheckState.Checked}

    def set_checked(self, notes: set[int]) -> None:
        for row, n in enumerate(self.notes):
            self.table.item(row, 0).setCheckState(Qt.CheckState.Checked if n in notes else Qt.CheckState.Unchecked)

    def save(self) -> None:
        self.to_keep = self.checked()
        self.accept()


# --- страница ---

class ProfilesPage(QWidget):
    """Строка заголовка (выбор профиля, действия, Save) и редактор выбранного профиля под ней."""

    dirty_changed = Signal(bool)
    profiles_changed = Signal()  # профиль сохранён, создан, переименован или удалён

    def __init__(self, storage: Storage) -> None:
        super().__init__()
        self.storage = storage
        self.settings = ui_settings(storage)
        self.current: str | None = None        # ID профиля в хранилище
        self.base: RemapProfile | None = None  # последнее сохранённое состояние
        self.work: RemapProfile | None = None  # рабочая копия, её правит вид «кабелями» (через страницу)
        self._ids: list[str] = []
        self._dirty = False
        # снимки «до» действия: профиль, подсказки обоих направлений, направление, в котором сделан шаг
        self._undo: list[tuple[RemapProfile, dict[str, dict[int, str]], str]] = []
        self._redo: list[tuple[RemapProfile, dict[str, dict[int, str]], str]] = []
        self._in_edit = False
        self._reverse_done = False  # действие само согласовало обратные правила (sync_reverse не нужен)
        self.direction = FORWARD
        # подсказки по направлениям: нота исходной стороны без правила -> артикуляция стороны цели
        self._suggest: dict[str, dict[int, str]] = {FORWARD: {}, REVERSE: {}}
        self._dismissed: set[tuple] = set()  # (пара карт, направление): подсказки скрыты (до открытия профиля)
        self._build_ui()
        self.reload_list()
        self._update_state()

    # --- построение UI ---

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 10, 0, 0)
        root.setSpacing(8)

        # строка заголовка: [профиль ▾] [⋯] [направление — 8b3b2] статус … [↻] [Revert] [Save]
        self.combo = QComboBox()
        self.combo.setMinimumWidth(240)
        self.combo.setMaximumWidth(420)
        self.combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.combo.currentIndexChanged.connect(self._on_combo_changed)
        self.more_btn = DotsButton()
        self.more_btn.setToolTip(MORE_TIP)
        more = QMenu(self.more_btn)
        self.new_action = more.addAction("New", self.new_profile)
        self.rename_action = more.addAction("Rename", self.rename)
        self.duplicate_action = more.addAction("Duplicate", self.duplicate)
        more.addSeparator()
        self.delete_action = more.addAction("Delete", self.delete)
        self.more_btn.setMenu(more)
        # переключатель направления: «→ N | ← M», N и M — ноты без правила в этом направлении
        self.direction_slot = QHBoxLayout()
        self.direction_slot.setContentsMargins(0, 0, 0, 0)
        self.direction_slot.setSpacing(0)
        self.direction_group = QButtonGroup(self)
        self.direction_group.setExclusive(True)
        self.direction_btns: dict[str, QPushButton] = {}
        for d, pos in ((FORWARD, "first"), (REVERSE, "last")):
            btn = QPushButton()
            btn.setObjectName("segment")
            btn.setCheckable(True)
            btn.setProperty("pos", pos)
            btn.setProperty("dir", d)
            btn.clicked.connect(lambda _=False, d=d: self.set_direction(d))
            self.direction_group.addButton(btn)
            self.direction_slot.addWidget(btn)
            self.direction_btns[d] = btn
        self.direction_btns[FORWARD].setChecked(True)
        self.status = QLabel()
        self.status.setObjectName("status")
        self.status.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)  # длинный — обрезается
        self.refresh_btn = QPushButton("↻")
        self.refresh_btn.setToolTip(REFRESH_TIP)
        self.refresh_btn.setObjectName("iconButton")
        self.refresh_btn.clicked.connect(lambda: self.cables.resort())
        self.revert_btn = QPushButton("Revert")
        self.revert_btn.setToolTip(f"Discard unsaved changes\n{UNDO_TIP}")
        self.revert_btn.clicked.connect(self.revert)
        self.save_btn = QPushButton("Save")
        self.save_btn.setObjectName("primary")
        self.save_btn.clicked.connect(self.save)
        head = QHBoxLayout()
        head.setSpacing(6)
        head.addWidget(self.combo, stretch=1)
        head.addWidget(self.more_btn)
        head.addLayout(self.direction_slot)
        head.addSpacing(10)
        head.addWidget(self.status, stretch=2)
        head.addWidget(self.refresh_btn)
        head.addWidget(self.revert_btn)
        head.addWidget(self.save_btn)
        root.addLayout(head)
        self.header_controls = (self.combo, self.more_btn, *self.direction_btns.values(), self.refresh_btn,
                                self.revert_btn, self.save_btn)

        self.cables = CableEditor(self.settings)
        self.cables.connect_requested.connect(self.connect_to)
        self.cables.group_drop_requested.connect(self.group_drop)
        self.cables.disconnect_requested.connect(self.clear_rules)
        self.cables.strike_requested.connect(self.toggle_strike)
        self.cables.write_to_requested.connect(self.set_write_to)
        self.cables.primary_requested.connect(self.make_primary)
        root.addWidget(self.cables, stretch=1)

        # над внешними колонками — карты: источник над левым пулом, цель над правым
        self.source_btn = QPushButton()
        self.target_btn = QPushButton()
        for side_name, btn, tip, head_box in ((SOURCE, self.source_btn, SOURCE_TIP, self.cables.left_head),
                                              (TARGET, self.target_btn, TARGET_TIP, self.cables.right_head)):
            menu = QMenu(btn)
            menu.aboutToShow.connect(lambda m=menu, s=side_name: self._fill_map_menu(m, s))
            btn.setMenu(menu)
            btn.setToolTip(tip)
            btn.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            head_box.addWidget(btn)

        # над сценой — счётчик правил и панель подсказок «N matches · Apply · ✕» (не диалог, ничего не блокирует)
        self.summary = QLabel()
        self.summary.setObjectName("muted")
        self.summary.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.suggest_bar = QFrame()
        self.suggest_bar.setObjectName("suggestBar")
        self.suggest_label = QLabel()
        self.apply_btn = QPushButton("Apply")
        self.apply_btn.setObjectName("link")
        self.apply_btn.clicked.connect(self.apply_suggestions)
        self.dismiss_btn = QPushButton("✕")
        self.dismiss_btn.setObjectName("link")
        self.dismiss_btn.setToolTip(DISMISS_TIP)
        self.dismiss_btn.clicked.connect(self.dismiss_suggestions)
        bar = QHBoxLayout(self.suggest_bar)
        bar.setContentsMargins(10, 0, 4, 0)
        bar.setSpacing(4)
        dot = QLabel("·")
        dot.setObjectName("muted")
        bar.addWidget(self.suggest_label)
        bar.addWidget(dot)
        bar.addWidget(self.apply_btn)
        bar.addWidget(self.dismiss_btn)
        mid = self.cables.mid_head
        mid.addSpacing(4)
        mid.addWidget(self.summary, stretch=1)
        mid.addWidget(self.suggest_bar)

        context = Qt.ShortcutContext.WidgetWithChildrenShortcut
        for keys, slot in ((UNDO_KEYS, self.undo), (REDO_KEYS, self.redo)):
            for k in keys:
                QShortcut(QKeySequence(k), self, activated=slot, context=context)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._fit_header()

    def _fit_header(self) -> None:
        """Контролы строки заголовка — одной высоты (по самому высокому), «⋯» — размером с ↻. Считается при
        показе: размеры зависят от стиля окна, а при создании страницы он ещё не применён."""
        for w in self.header_controls:
            w.setMinimumHeight(0)
            w.setMaximumHeight(16777215)
            w.ensurePolished()
        height = max(w.sizeHint().height() for w in self.header_controls)
        for w in self.header_controls:
            w.setFixedHeight(height)
        self.more_btn.setFixedWidth(self.refresh_btn.sizeHint().width())

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

    def ask_write_to(self, name: str, notes: list[int], preselect: int | None = None) -> int | None:
        """Артикуляция на нескольких нотах без Write to: на какую ноту писать (ответ запомнится в профиле).
        preselect — нота, выбранная в списке заранее (первая совпавшая по номеру)."""
        dlg, items = self.write_to_dialog(name, notes, preselect)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return None
        return notes[items.index(dlg.textValue())]

    def write_to_dialog(self, name: str, notes: list[int], preselect: int | None = None
                        ) -> tuple[QInputDialog, list[str]]:
        """Диалог вопроса о Write to (без показа) и его пункты. В ← цель — исходная карта: выбор ляжет в её копию."""
        items = [f"{n} · {pitch_name(n)}" for n in notes]
        dlg = QInputDialog(self)
        dlg.setWindowTitle("Write to")
        dlg.setLabelText(f'"{name}" is on several notes. Write converted notes to:')
        dlg.setComboBoxItems(items)
        dlg.setComboBoxEditable(False)
        if preselect in notes:
            dlg.setTextValue(items[notes.index(preselect)])
        side = "source" if self.direction == REVERSE else "target"
        dlg.setToolTip(f"The choice is saved in this profile's copy of the {side} map, not in the map itself")
        return dlg, items

    def ask_unassigned(self, notes: list[int]) -> set[int] | None:
        """Перед сохранением: ноты без правила будут удалены — какие оставить на своих номерах.
        None — отмена; пустое множество — удалить все."""
        dlg = UnassignedDialog(self, self.work, notes)
        return dlg.to_keep if dlg.exec() == QDialog.DialogCode.Accepted else None

    def show_error(self, text: str) -> None:
        QMessageBox.warning(self, "MidiRemap", text)

    # --- список (комбобокс профилей) ---

    def reload_list(self, select: str | None = None) -> None:
        """Перестроить список; выбран — select или текущий профиль (сигналы при этом не идут)."""
        select = select or self.current
        self.combo.blockSignals(True)
        self.combo.clear()
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
        self.combo.setPlaceholderText("Select a profile" if entries else "No profiles yet")
        self.combo.setToolTip("" if entries else "Create one: ⋯ → New")
        if issues:
            self.set_status(f"Skipped unreadable profiles ({len(issues)}): "
                            + ", ".join(i.path.name for i in issues), "error")
        self.combo.setCurrentIndex(self._index_of(select))
        self.combo.blockSignals(False)
        self._mark_dirty_item()

    def _item(self, title: str, subtitle: str, profile_id: str | None) -> None:
        self.combo.addItem(title)
        i = self.combo.count() - 1
        self.combo.setItemData(i, profile_id, ID_ROLE)
        self.combo.setItemData(i, title, NAME_ROLE)
        self.combo.setItemData(i, subtitle, SUBTITLE_ROLE)
        self.combo.setItemData(i, wrapped_tooltip(subtitle), Qt.ItemDataRole.ToolTipRole)
        if profile_id is None:  # профиль не читается — пункт виден, но не выбирается
            self.combo.model().item(i).setEnabled(False)

    def _index_of(self, profile_id: str | None) -> int:
        if profile_id is None:
            return -1
        return next((i for i in range(self.combo.count()) if self.combo.itemData(i, ID_ROLE) == profile_id), -1)

    def _show_current(self) -> None:
        """Комбобокс показывает открытый профиль (без сигналов)."""
        index = self._index_of(self.current)
        if self.combo.currentIndex() != index:
            self.combo.blockSignals(True)
            self.combo.setCurrentIndex(index)
            self.combo.blockSignals(False)

    def _mark_dirty_item(self) -> None:
        """«•» перед именем профиля с несохранёнными правками; подсказка — сохранённое состояние."""
        for i in range(self.combo.count()):
            name = self.combo.itemData(i, NAME_ROLE)
            if name is None:
                continue
            text = f"• {name}" if self._dirty and self.combo.itemData(i, ID_ROLE) == self.current else name
            if self.combo.itemText(i) != text:
                self.combo.setItemText(i, text)

    def _on_combo_changed(self, index: int) -> None:
        profile_id = self.combo.itemData(index, ID_ROLE) if index >= 0 else None
        if profile_id is None or profile_id == self.current:
            return
        if not self.maybe_leave():
            self._show_current()
            return
        self.open(profile_id)

    def select(self, profile_id: str) -> None:
        """Выбрать и открыть профиль (с вопросом о несохранённых правках)."""
        index = self._index_of(profile_id)
        if index >= 0:
            self.combo.setCurrentIndex(index)

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
        self._show_current()
        self._undo.clear()
        self._redo.clear()
        self._suggest = {FORWARD: {}, REVERSE: {}}  # открытие профиля подсказок не показывает
        self._dismissed.clear()
        self._show_direction(FORWARD)  # профиль открывается в →
        self._sync_suggestions()
        self.cables.set_profile(self.work, direction=FORWARD)
        self._update_state()
        self.set_status("")
        return True

    def close_profile(self) -> None:
        self.current = self.base = self.work = None
        self._undo.clear()
        self._redo.clear()
        self._suggest = {FORWARD: {}, REVERSE: {}}
        self._show_direction(FORWARD)
        self._sync_suggestions()
        self.cables.set_profile(None, direction=FORWARD)
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

    @_undoable
    def revert(self) -> None:
        if self.base is None:
            return
        self.work = copy.deepcopy(self.base)
        self._sync_suggestions()
        self.cables.set_profile(self.work, reset_collapsed=False)
        self._update_state()

    # --- отмена / повтор ---

    def _record(self, before: tuple[RemapProfile, dict[str, dict[int, str]], str]) -> None:
        """После действия: профиль изменился — снимок «до» в стек отмены, повтор сбрасывается."""
        if self.work is None or before[0].to_dict() == self.work.to_dict():
            return
        self._undo.append(before)
        del self._undo[:-UNDO_LIMIT]
        self._redo.clear()

    def _snapshot(self, direction: str | None = None) -> tuple[RemapProfile, dict[str, dict[int, str]], str]:
        """Рабочая копия, подсказки обоих направлений и направление шага (по умолчанию — текущее)."""
        return (copy.deepcopy(self.work), {d: dict(v) for d, v in self._suggest.items()},
                direction or self.direction)

    def _restore(self, snap: tuple[RemapProfile, dict[str, dict[int, str]], str]) -> None:
        """Вернуть рабочую копию к снимку (на месте: «кабели» держат тот же объект) и подсказки."""
        profile, suggest, _ = snap
        self._suggest = {d: dict(v) for d, v in suggest.items()}
        w = self.work
        maps_changed = (w.source_map, w.target_map) != (profile.source_map, profile.target_map)
        w.name, w.source_map, w.target_map, w.rules = profile.name, profile.source_map, profile.target_map, \
            profile.rules
        w.reverse_rules = profile.reverse_rules
        self._changed()
        if maps_changed:
            self.cables.resort()

    def undo(self) -> bool:
        """Отменить шаг: сначала вид — на направление, в котором он сделан (не шаг), затем снимок «до»."""
        if self.work is None or not self._undo:
            return False
        snap = self._undo.pop()
        self._redo.append(self._snapshot(snap[2]))
        self.set_direction(snap[2])
        self._restore(snap)
        return True

    def redo(self) -> bool:
        if self.work is None or not self._redo:
            return False
        snap = self._redo.pop()
        self._undo.append(self._snapshot(snap[2]))
        self.set_direction(snap[2])
        self._restore(snap)
        return True

    # --- направление ---

    def set_direction(self, direction: str) -> None:
        """Переключить вид на направление (→ / ←). Это не шаг отмены: профиль не меняется."""
        if direction == self.direction:
            self._show_direction(direction)
            return
        self._show_direction(direction)
        self._sync_suggestions()
        self.cables.set_direction(direction)
        self._update_state()

    def _show_direction(self, direction: str) -> None:
        self.direction = direction
        btn = self.direction_btns[direction]
        if not btn.isChecked():
            btn.setChecked(True)

    def _oriented(self) -> RemapProfile:
        """Профиль, который правит вид: сам work (→) или work.reversed() (←)."""
        return self.work.oriented(self.direction)

    def _put(self, new: RemapProfile) -> None:
        """Результат правки ориентированного профиля — в рабочую копию. В → это карта цели и прямые правила;
        в ← — карта цели обратного профиля = копия ИСХОДНОЙ карты (Write to ложится в неё) и обратные правила."""
        if self.direction == FORWARD:
            self.work.target_map, self.work.rules = new.target_map, new.rules
        else:
            self.work.source_map, self.work.reverse_rules = new.target_map, dict(new.rules)

    def _update_direction(self) -> None:
        """Числа сегментов: ноты карты исходной стороны направления без правила (missing_rules)."""
        for d, btn in self.direction_btns.items():
            arrow = "→" if d == FORWARD else "←"
            btn.setEnabled(self.work is not None)
            side = DIRECTION_SIDES[d]
            side_map = None
            if self.work is not None:
                side_map = self.work.source_map if d == FORWARD else self.work.target_map
            if side_map is None:
                btn.setText(arrow)
                btn.setToolTip(DIRECTION_NO_MAP_TIP.format(side=side) if self.work is not None else "")
                continue
            n = len(missing_rules(self.work, d))
            btn.setText(f"{arrow} {n}")
            btn.setToolTip(DIRECTION_TIP.format(n=n, side=side, s="" if n == 1 else "s",
                                                have="has" if n == 1 else "have"))

    def unassigned(self) -> list[int]:
        """Ноты исходной карты без правила."""
        src = self.work.source_map if self.work is not None else None
        return [] if src is None else [n for n in sorted(src.names) if n not in self.work.rules]

    @_undoable
    def save(self) -> bool:
        """Сохранить. Ноты исходной карты без правила: диалог — по умолчанию удаляются (delete), отмеченные
        остаются на своих номерах (явный keep). Конвертация спрашивает только о нотах вне исходной карты."""
        if self.work is None or self.current is None:
            return False
        out = copy.deepcopy(self.work)
        unassigned = self.unassigned()
        if unassigned:
            to_keep = self.ask_unassigned(unassigned)
            if to_keep is None:
                return False
            for n in unassigned:
                out.rules[n] = Rule.keep() if n in to_keep else Rule.delete()
        try:
            self.storage.save_profile(out, profile_id=self.current, overwrite=True)
        except (OSError, ValueError) as e:
            self.show_error(f"Cannot save the profile:\n\n{e}")
            return False
        self.base = out
        self.work = copy.deepcopy(out)
        self._sync_suggestions()
        self.cables.set_profile(self.work, reset_collapsed=False)
        self.reload_list()
        self._update_state()
        self.profiles_changed.emit()
        self.set_status(f'Saved "{out.name}".', "ok")
        return True

    def _changed(self) -> None:
        self._sync_suggestions()
        self.cables.refresh()
        self._update_state()

    def _update_state(self) -> None:
        has = self.work is not None
        dirty = has and self.work.to_dict() != self.base.to_dict()
        if dirty != self._dirty:
            self._dirty = dirty
            self.dirty_changed.emit(dirty)
        self._mark_dirty_item()
        self.save_btn.setEnabled(dirty)
        self.revert_btn.setEnabled(dirty)
        for action in (self.duplicate_action, self.rename_action, self.delete_action):
            action.setEnabled(has)
        for btn in (self.source_btn, self.target_btn, self.refresh_btn):
            btn.setEnabled(has)
        self._update_suggest_bar()
        self._update_direction()
        if not has:
            self.source_btn.setText("—")
            self.target_btn.setText("—")
            self.summary.setText("")
            return
        self.source_btn.setText(map_summary(self.work.source_map))
        self.target_btn.setText(map_summary(self.work.target_map))
        q = self._oriented()  # счётчик — по направлению вида
        n_rules = len(q.rules)
        parts = [f"{n_rules} rule" + ("" if n_rules == 1 else "s")]
        if q.source_map is not None:
            parts.append(f"{len(missing_rules(self.work, self.direction))} unassigned")
        self.summary.setText(" · ".join(parts))
        side = DIRECTION_SIDES[self.direction]
        self.summary.setToolTip(UNDO_TIP if q.source_map is not None else
                                f"No {side} map: one row per rule\n{UNDO_TIP}")

    # --- подсказки ---

    def _sync_suggestions(self) -> None:
        """Нота, получившая правило (в своём направлении), из подсказок выбывает навсегда (для этой пары карт);
        подсказки текущего направления — в «кабели»."""
        if self.work is None:
            self._suggest = {FORWARD: {}, REVERSE: {}}
        else:
            rules = {FORWARD: self.work.rules, REVERSE: self.work.effective_reverse()}
            self._suggest = {d: {n: a for n, a in v.items() if n not in rules[d]} for d, v in self._suggest.items()}
        self.cables.set_suggestions(self._suggest[self.direction])

    def _compute_suggestions(self) -> None:
        """Обе карты заданы пользователем: подсказки для нот без правила в каждом направлении (в ← —
        ноты цели без обратного правила, имена ищутся в исходной карте); направление, скрытое ✕ для этой пары
        карт, — без подсказок."""
        w = self.work
        for d in (FORWARD, REVERSE):
            q = w.oriented(d)
            if q.source_map is None or q.target_map is None or (_pair_key(w), d) in self._dismissed:
                self._suggest[d] = {}
            else:
                self._suggest[d] = {n: a for n, a in suggestion_targets(q.source_map, q.target_map).items()
                                    if n not in q.rules}

    def suggestion_counts(self) -> tuple[int, int]:
        """(подсказок показано, из них применится по Apply) — в текущем направлении."""
        suggest = self._suggest[self.direction]
        if self.work is None or not suggest:
            return 0, 0
        planned = plan_suggestions(self._oriented(), suggest)
        return len(planned), sum(dst is not None for dst in planned.values())

    def _update_suggest_bar(self) -> None:
        total, ready = self.suggestion_counts()
        self.suggest_bar.setVisible(total > 0)
        if not total:
            return
        self.suggest_label.setText(f"{total} match" + ("" if total == 1 else "es"))
        need = total - ready
        tip = SUGGEST_TIP
        if need:
            tip += (f"\n{need} need{'s' if need == 1 else ''} a Write to choice and stay dashed: "
                    "drag them onto the target.")
        self.suggest_bar.setToolTip(tip)
        self.apply_btn.setEnabled(ready > 0)
        self.apply_btn.setToolTip(f"Connect {ready} note{'' if ready == 1 else 's'} (one undo step)")

    @_undoable
    def apply_suggestions(self) -> int:
        """Применить подсказки по логике назначения 8b2c (core apply_suggested); нужен выбор Write to —
        пропускаются и остаются пунктиром. Возвращает число подключённых нот."""
        if self.work is None or not self._suggest[self.direction]:
            return 0
        new, done = apply_suggested(self._oriented(), self._suggest[self.direction])
        self._put(new)
        self._changed()
        n = len(done)
        self.set_status(f"{n} note{'' if n == 1 else 's'} connected.", "ok")
        return n

    def dismiss_suggestions(self) -> None:
        """✕: скрыть подсказки для этой пары карт в текущем направлении до повторного открытия профиля."""
        if self.work is None:
            return
        self._dismissed.add((_pair_key(self.work), self.direction))
        self._suggest[self.direction] = {}
        self._sync_suggestions()
        self.cables.resort()
        self._update_state()

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

    @_undoable
    def choose_map(self, side: str, ref: MapRef | None) -> bool:
        """Встроить в профиль копию карты (или убрать карту). Правила сохраняются; если они есть — спросить.
        Обе карты заданы — подсказки пересчитываются (пунктир и панель)."""
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
                "The rules are kept. Problems with them are highlighted in the editor."):
            return False
        if side == SOURCE:
            self.work.source_map = m
        else:
            self.work.target_map = m
        self.work.reverse_rules = None  # обратные правила по нотам прежней карты не переживают смену — снова выводятся
        self._compute_suggestions()
        self._sync_suggestions()
        self.cables.resort()  # смена карты — пересортировка
        self._update_state()
        self.set_status(f"{what.capitalize()} map: {map_summary(m)}.")
        return True

    # --- правила ---

    @_undoable
    def assign_articulation(self, notes: list[int], articulation: str) -> bool:
        """Цель — артикуляция целевой карты (логика — core assign_plan / assign_to_articulation): нота, чей номер
        есть среди нот артикуляции, остаётся на нём; остальные — на Write to. Нужен выбор Write to — спросить
        один раз; он запоминается как primary в КОПИИ целевой карты профиля (карта в хранилище не меняется)."""
        if self.work is None or not notes:
            return False
        q = self._oriented()  # в ← — обратный профиль: цель — исходная карта, Write to ляжет в её копию
        if q.target_map is None:
            return False
        try:
            plan = assign_plan(q, notes, articulation)
        except ValueError:
            return False
        write_to = None
        if plan.ask:
            write_to = self.ask_write_to(plan.name, list(plan.targets), plan.preselect)
            if write_to is None:
                return False
        self._put(assign_to_articulation(q, notes, articulation, write_to))
        self._changed()
        self.set_status(f"{len(plan.same) + len(plan.others)} note(s) → {plan.name}.")
        return True

    @_undoable
    def group_drop(self, notes: list[int], targets: list[int]) -> int:
        """Кабель отпустили на заголовке группы цели: n → n для нот, чей номер есть в группе (core
        connect_same_numbers; ноты без совпадения и уже подключённые не трогаются, вопросов нет)."""
        if self.work is None or not notes:
            return 0
        new, done = connect_same_numbers(self._oriented(), notes, targets)
        if done:
            self._put(new)
            self._changed()
        self.set_status(f"{len(done)} of {len(set(notes))} connected")
        return len(done)

    @_undoable
    def assign_note(self, notes: list[int], dst: int) -> bool:
        """Номер вне карты стороны цели (или карты нет): правило map на него."""
        q = self._oriented()
        for n in notes:
            q.rules[n] = Rule.map_to(dst)
        self._put(q)
        self._changed()
        self.set_status(f"{len(notes)} note(s) → {dst}.")
        return True

    @_undoable
    def delete_notes(self, notes: list[int]) -> None:
        if self.work is None or not notes:
            return
        q = self._oriented()
        for n in notes:
            q.rules[n] = Rule.delete()
        self._put(q)
        self._changed()
        self.set_status(f"Deleted {len(notes)} note(s).")

    @_undoable
    def clear_rules(self, notes: list[int]) -> None:
        if self.work is None or not notes:
            return
        q = self._oriented()
        for n in notes:
            q.rules.pop(n, None)
        self._put(q)
        self._changed()
        self.set_status(f"Cleared {len(notes)} rule(s).")

    @_undoable
    def connect_to(self, notes: list[int], slot: str) -> bool:
        """Кабель отпустили на строке цели. slot — «a:<артикуляция>» (Write to спросят один раз, если нужно)
        или «n:<номер>» (нота вне целевой карты)."""
        if self.work is None or not notes:
            return False
        if slot.startswith("a:"):
            return self.assign_articulation(notes, slot[2:])
        return self.assign_note(notes, int(slot[2:]))

    @_undoable
    def toggle_strike(self, notes: list[int]) -> None:
        """Правый клик в пуле: зачеркнуть (delete); если все ноты уже зачёркнуты — вернуть (без правила)."""
        if self.work is None or not notes:
            return
        if all(self._oriented().rules.get(n) == Rule.delete() for n in notes):
            self.clear_rules(notes)
        else:
            self.delete_notes(notes)

    @_undoable
    def set_write_to(self, note: int) -> bool:
        """Write to артикуляции стороны цели = note (в → — в копии целевой карты профиля, в ← — исходной); на
        note переводятся правила map, которые шли на прежний Write to (кроме n → n) — core with_write_to."""
        if self.work is None:
            return False
        q = self._oriented()
        if q.target_map is None or note not in q.target_map.names:
            return False
        new = with_write_to(q, note)
        moved = sum(1 for n, r in new.rules.items() if r != q.rules.get(n))
        self._put(new)
        self._changed()
        self.set_status(f"Write to: {note} ({pitch_name(note)}) · {moved} rule(s) moved.")
        return True

    @_undoable
    def make_primary(self, src: int, dst: int) -> bool:
        """Двойной клик по кабелю (src -> dst ориентированного профиля) — сделать его основным.
        → (a -> b): обратное правило b -> a (with_primary_cable; алиасы-«дублёры» b — туда же).
        ← (b -> a): прямое правило a -> b вместо прежнего a -> b' (with_forward_primary; выведенные для b'
        обратные правила следуют за прямыми). Уже основной — ничего. Один шаг отмены."""
        if self.work is None:
            return False
        a, b = (src, dst) if self.direction == FORWARD else (dst, src)
        if (a, b) in primary_pairs(self.work):
            return False
        try:
            if self.direction == FORWARD:
                old = self.work.effective_reverse().get(b)
                new = with_primary_cable(self.work, a, b)
                status = f"Reverse: {b} → {a} ({_was(b, old)})"
            else:
                old = self.work.rules.get(a)
                new = with_forward_primary(self.work, a, b)
                status = f"Forward: {a} → {b} ({_was(a, old)})"
        except ValueError:
            return False
        self.work.rules, self.work.reverse_rules = new.rules, new.reverse_rules
        self._reverse_done = True  # обратные правила уже согласованы ядром (постусловие — основной кабель)
        self._changed()
        self.set_status(status)
        return True

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
