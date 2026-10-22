"""Вид профиля «кабелями» (этап 8b2): показ и правка перетаскиванием кабелей.

Три колонки: пул (Unassigned / Keep / Delete) — отдельная QGraphicsView со своей прокруткой; подключённые ноты
и цель — вторая QGraphicsView (колонки 2 и 3 в одной сцене — одна общая прокрутка, кабели между ними внутри
сцены). Между ними QSplitter. Поверх обоих — прозрачный для мыши слой CableOverlay: на нём рисуется кабель-превью
от исходных строк к курсору через границу пула и сцены.

Порядок, группы, алиасы, высоты строк и кабели считает cable_layout (без Qt); здесь — рисование, выделение,
перетаскивание, правый клик и подсказки. Профиль — рабочая копия страницы Profiles: виджет его НЕ меняет, а
сигналами просит страницу (connect_requested / disconnect_requested / strike_requested / write_to_requested) —
правила меняет та же логика, что и в таблице.

Мышь: строки пула и колонки 2 выделяются (Ctrl/Shift — несколько) и перетаскиваются на строку цели; кабель-превью
догоняет курсор с лёгкой пружиной (таймер ~60 кадров/с), у края любой колонки — автопрокрутка, Esc — отмена.
Наведение на заголовок группы цели во время перетаскивания (~500 мс) показывает все её артикуляции.
Правый клик: кабель (или подключённая строка) — снять кабель; строка или группа пула — зачеркнуть
(правило delete) / вернуть (без правила). Бейдж «+N» строки цели — меню выбора Write to.

Пересортировка: set_profile(), resort() (кнопка ↻), режим группы цели, включение вида (set_active).
После правок — refresh(): порядок заморожен (см. cable_layout). Сворачивание в пуле и раскрытие алиасов
перестраивают только свою колонку (порядок тот же).
"""
from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPainterPathStroker, QPen
from PySide6.QtWidgets import (
    QApplication, QGraphicsItem, QGraphicsPathItem, QGraphicsScene, QGraphicsView, QMenu, QSplitter, QVBoxLayout,
    QWidget,
)

from ..core.notemap import primary_note
from ..core.pitch import pitch_name
from ..core.profile import NO_RULE, ProfileIssue, RemapProfile, validate_profile
from .cable_layout import (
    DEFAULT_COLLAPSED, DELETE, KEEP, MIXED, TARGET_PREFIX, UNASSIGNED, Cable, CableLayout, Header, OrderSnapshot,
    SourceRow, TargetRow, build_layout,
)
from .theme import TOKENS

ROW = 28            # шаг строк, px (сама строка — ROW - 2 * ROW_INSET)
ROW_INSET = 2
RADIUS = 5
PAD = 8             # поля сцены
NUM_W, PITCH_W, MARK_W = 28, 38, 24
BADGE_W = 32        # бейдж «+N» строки цели (кликабельный)
CHEVRON_W = 18      # шеврон раскрытия алиасов справа в строке
INDENT = 14         # отступ строк нот под заголовком раскрытых алиасов
PORT = 3.0          # радиус точки подключения кабеля
CABLE_W, CABLE_HOVER_W = 2.0, 3.0
CABLE_HIT = 16      # ширина зоны попадания по кабелю (по 8 px в стороны)
DIMMED = 0.3        # прозрачность прочих кабелей, пока один под курсором
STALE = 0.45        # прозрачность строки без кабеля (до пересортировки)
POOL_WIDTH = 300    # начальная ширина пула

FRAME_MS = 16                   # кадр кабеля-превью и автопрокрутки
STIFFNESS, DAMPING = 0.3, 0.6   # пружина конца кабеля-превью (лёгкое запаздывание, без раскачки)
SAG = 0.12                      # провис кабеля-превью: доля длины (не больше SAG_MAX px)
SAG_MAX = 48.0
EDGE = 32                       # зона автопрокрутки у верхнего/нижнего края, px
SCROLL_MAX = 18                 # px за кадр
SPRING_LOAD_MS = 500            # наведение на заголовок группы цели при перетаскивании — показать все
MAX_PREVIEW = 24                # кабелей-превью при перетаскивании многих строк

POOL, SOURCE, TARGET = "pool", "source", "target"  # роль строки: пул, колонка 2, цель

STATE_TIPS = {
    UNASSIGNED: "No rule yet: stays on its number unless you choose otherwise when saving",
    KEEP: "Stays on its number",
    DELETE: "Deleted from converted files",
    MIXED: "These notes have different rules",
}
STALE_TIP = "Its cable was removed. Refresh the layout to return it to the pool"
ROW_HINT = "Drag onto a target to map · Ctrl/Shift+click to select several · Right-click to delete or restore"
CONNECTED_HINT = "Drag onto another target to remap · Right-click to remove the cable"
ALIAS_HINT = "Click the arrow to show the notes one by one"
MIXED_HINT = "Notes with different rules are always shown one by one"
BADGE_HINT = "Click +{n} to choose the Write to note"
GROUP_HINT = "Right-click to delete or restore the whole group"


def _font(base: QFont, *, bold=False, weight: QFont.Weight | None = None, size_delta=0.0, strike=False,
          italic=False, caps=False) -> QFont:
    f = QFont(base)
    if size_delta:
        f.setPointSizeF(max(6.0, f.pointSizeF() + size_delta))
    if weight is not None:
        f.setWeight(weight)
    elif bold:
        f.setBold(True)
    f.setStrikeOut(strike)
    f.setItalic(italic)
    if caps:
        f.setCapitalization(QFont.Capitalization.AllUppercase)
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.8)
    return f


def _color(token: str, alpha: float = 1.0) -> QColor:
    c = QColor(TOKENS[token])
    c.setAlphaF(alpha)
    return c


def _draw_port(p: QPainter, c: QPointF, token: str = "accent") -> None:
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(_color(token))
    p.drawEllipse(c, PORT, PORT)


def _draw_chevron(p: QPainter, x: float, cy: float, collapsed: bool, token: str = "text_muted") -> None:
    """Шеврон: вправо — свёрнуто, вниз — развёрнуто."""
    s = 3.0
    path = QPainterPath()
    if collapsed:
        path.moveTo(x + 1, cy - s)
        path.lineTo(x + 1 + s, cy)
        path.lineTo(x + 1, cy + s)
    else:
        path.moveTo(x, cy - s / 2)
        path.lineTo(x + s, cy + s / 2)
        path.lineTo(x + 2 * s, cy - s / 2)
    pen = QPen(_color(token), 1.4)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(path)


def cable_path(a: QPointF, b: QPointF) -> QPainterPath:
    """Плавный кубический Безье: горизонтальные касательные на концах."""
    path = QPainterPath(a)
    dx = max(30.0, abs(b.x() - a.x()) / 2)
    path.cubicTo(QPointF(a.x() + dx, a.y()), QPointF(b.x() - dx, b.y()), b)
    return path


def preview_path(a: QPointF, b: QPointF) -> QPainterPath:
    """Кабель-превью: тот же Безье с лёгким провисом вниз (пропорционально длине)."""
    sag = min(SAG_MAX, math.hypot(b.x() - a.x(), b.y() - a.y()) * SAG)
    dx = max(30.0, abs(b.x() - a.x()) / 2)
    path = QPainterPath(a)
    path.cubicTo(QPointF(a.x() + dx, a.y() + sag), QPointF(b.x() - dx, b.y() + sag), b)
    return path


# --- элементы сцены ---

class _Row(QGraphicsItem):
    """Строка: фон со скруглением, номер, высота ноты, имя (и «×N» у алиасов), маркер справа; точка кабеля слева
    или справа. Высокая строка цели (связка многие-в-одну) — один блок, текст на уровне первой строки напротив.

    role — POOL / SOURCE / TARGET; model — SourceRow или TargetRow из раскладки."""

    def __init__(self, rect: QRectF, role: str, model: SourceRow | TargetRow, number: str, pitch: str, name: str,
                 *, name_color="text", strike=False, italic=False, marker="", count=1, chevron: str | None = None,
                 badge=False, port: str | None = None, warn=False, tooltip="") -> None:
        super().__init__()
        self.rect, self.role, self.model = rect, role, model
        self.number, self.pitch, self.name = number, pitch, name
        self.name_color, self.strike, self.italic, self.marker = name_color, strike, italic, marker
        self.count, self.chevron, self.badge = count, chevron, badge  # chevron: collapsed / expanded / fixed
        self.port, self.warn = port, warn
        self.highlighted = False
        self.selected = False
        self._hover = False
        self.setZValue(1)
        self.setAcceptHoverEvents(True)
        if tooltip:
            self.setToolTip(tooltip)

    @property
    def notes(self) -> tuple[int, ...]:
        return self.model.notes

    def set_highlighted(self, on: bool) -> None:
        if on != self.highlighted:
            self.highlighted = on
            self.update()

    def set_selected(self, on: bool) -> None:
        if on != self.selected:
            self.selected = on
            self.update()

    def boundingRect(self) -> QRectF:
        return self.rect.adjusted(-PORT - 1, 0, PORT + 1, 0)

    def chevron_rect(self) -> QRectF | None:
        """Зона шеврона алиасов (в координатах сцены); None — шеврона нет или он не переключается."""
        if self.chevron not in ("collapsed", "expanded"):
            return None
        return QRectF(self.rect.right() - CHEVRON_W - 4, self.rect.top(), CHEVRON_W + 4, ROW)

    def badge_rect(self) -> QRectF | None:
        if not self.badge:
            return None
        return QRectF(self.rect.right() - BADGE_W - 4, self.rect.top(), BADGE_W + 4, ROW)

    def hoverEnterEvent(self, event) -> None:
        self._hover = True
        self.update()

    def hoverMoveEvent(self, event) -> None:
        pos = event.scenePos()
        hot = any(r is not None and r.contains(pos) for r in (self.chevron_rect(), self.badge_rect()))
        self.setCursor(Qt.CursorShape.PointingHandCursor if hot else Qt.CursorShape.ArrowCursor)

    def hoverLeaveEvent(self, event) -> None:
        self._hover = False
        self.update()

    def paint(self, p: QPainter, option, widget=None) -> None:
        base = widget.font() if widget is not None else p.font()
        r = self.rect.adjusted(0, ROW_INSET, 0, -ROW_INSET)
        bg = ("selection" if self.selected else "warning_bg" if self.warn
              else "surface_hover" if self._hover or self.highlighted else "surface")
        # подсветка (кабель под курсором, цель при перетаскивании) — тонкая обводка акцентом, без заливки
        p.setPen(QPen(_color("accent", 0.8), 1) if self.highlighted else Qt.PenStyle.NoPen)
        p.setBrush(_color(bg))
        p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), RADIUS, RADIUS)
        line = QRectF(r.left(), r.top(), r.width(), ROW - 2 * ROW_INSET)  # первая строка блока
        x = r.left() + 6
        left_mid = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        right_mid = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        p.setFont(_font(base, weight=QFont.Weight.Medium))
        p.setPen(_color("text"))
        p.drawText(QRectF(x, line.top(), NUM_W, line.height()), right_mid, self.number)
        x += NUM_W + 8
        p.setFont(_font(base, size_delta=-1.5))
        p.setPen(_color("text_muted"))
        p.drawText(QRectF(x, line.top(), PITCH_W, line.height()), left_mid, self.pitch)
        x += PITCH_W
        right = r.right() - (CHEVRON_W + 4 if self.chevron else 0)
        mark_w = BADGE_W if self.badge else MARK_W if self.marker else 0
        name_w = right - x - (mark_w or 8)
        font = _font(base, strike=self.strike, italic=self.italic)
        small = _font(base, size_delta=-1.5)
        count = f"×{self.count}" if self.count > 1 else ""
        count_w = QFontMetrics(small).horizontalAdvance(count) + 6 if count else 0
        text = QFontMetrics(font).elidedText(self.name, Qt.TextElideMode.ElideRight, max(0, int(name_w - count_w)))
        p.setFont(font)
        p.setPen(_color(self.name_color))
        p.drawText(QRectF(x, line.top(), name_w, line.height()), left_mid, text)
        if count:
            p.setFont(small)
            p.setPen(_color("text_muted"))
            p.drawText(QRectF(x + QFontMetrics(font).horizontalAdvance(text) + 6, line.top(), count_w,
                              line.height()), left_mid, count)
        if self.badge:
            pill = QRectF(right - BADGE_W, line.top() + 4, BADGE_W - 6, line.height() - 8)
            p.setPen(QPen(_color("border"), 1))
            p.setBrush(_color("bg"))
            p.drawRoundedRect(pill, pill.height() / 2, pill.height() / 2)
            p.setFont(_font(base, size_delta=-1.5, bold=True))
            p.setPen(_color("text_muted"))
            p.drawText(pill, Qt.AlignmentFlag.AlignCenter, self.marker)
        elif self.marker:
            p.setFont(_font(base, size_delta=-1.5, bold=True))
            p.setPen(_color("text_muted"))
            p.drawText(QRectF(right - MARK_W, line.top(), MARK_W - 6, line.height()), right_mid, self.marker)
        if self.chevron:
            _draw_chevron(p, r.right() - CHEVRON_W + 2, line.center().y(), self.chevron == "collapsed",
                          "text_faint" if self.chevron == "fixed" else "text_muted")
        if self.port:
            port_x = r.right() if self.port == "right" else r.left()
            _draw_port(p, QPointF(port_x, r.center().y()), "accent_hover" if self.highlighted else "accent")


class _HeaderItem(QGraphicsItem):
    """Заголовок блока или группы: шеврон, имя, число; клик — свернуть или развернуть (у цели — сменить режим)."""

    def __init__(self, rect: QRectF, header: Header, on_toggle: Callable[[str], None], tooltip: str) -> None:
        super().__init__()
        self.rect, self.header = rect, header
        self._on_toggle = on_toggle
        self._hover = False
        self.highlighted = False
        self.setZValue(1)
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(tooltip)

    def set_highlighted(self, on: bool) -> None:
        if on != self.highlighted:
            self.highlighted = on
            self.update()

    def boundingRect(self) -> QRectF:
        return QRectF(self.rect)

    def hoverEnterEvent(self, event) -> None:
        self._hover = True
        self.update()

    def hoverLeaveEvent(self, event) -> None:
        self._hover = False
        self.update()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            event.accept()
            # перестройка сцены удаляет этот элемент — не внутри его же обработчика
            QTimer.singleShot(0, lambda key=self.header.key: self._on_toggle(key))
        else:
            event.ignore()

    def paint(self, p: QPainter, option, widget=None) -> None:
        base = widget.font() if widget is not None else p.font()
        h = self.header
        r = self.rect.adjusted(0, ROW_INSET, 0, -ROW_INSET)
        if self.highlighted or self._hover:
            p.setPen(QPen(_color("accent", 0.8), 1) if self.highlighted else Qt.PenStyle.NoPen)
            p.setBrush(_color("surface_hover"))
            p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), RADIUS, RADIUS)
        x = r.left() + 6 + 14 * h.level
        _draw_chevron(p, x, r.center().y(), h.collapsed)
        x += 14
        font = (_font(base, bold=True, size_delta=-2.5, caps=True) if h.level == 0
                else _font(base, weight=QFont.Weight.DemiBold, size_delta=-1))
        fm = QFontMetrics(font)
        p.setFont(font)
        p.setPen(_color("text_muted"))
        avail = r.right() - x - 48
        text = fm.elidedText(h.label, Qt.TextElideMode.ElideRight, max(0, int(avail)))
        left_mid = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        p.drawText(QRectF(x, r.top(), avail, r.height()), left_mid, text)
        count = f"{h.shown} / {h.count}" if h.shown else str(h.count)  # цель: подключённые / все артикуляции
        p.setPen(_color("text_faint"))
        p.drawText(QRectF(x + fm.horizontalAdvance(text) + 8, r.top(), 48, r.height()), left_mid, count)


class _Bundle(QGraphicsItem):
    """Тонкая рамка вокруг строк колонки 2 напротив одной высокой строки цели: связка читается как один блок."""

    def __init__(self, rect: QRectF) -> None:
        super().__init__()
        self.rect = rect
        self.setZValue(0)

    def boundingRect(self) -> QRectF:
        return self.rect.adjusted(-1, -1, 1, 1)

    def paint(self, p: QPainter, option, widget=None) -> None:
        p.setPen(QPen(_color("border"), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(self.rect, RADIUS + 2, RADIUS + 2)


class _CableItem(QGraphicsPathItem):
    """Кабель: наведение — толще и ярче, его строки подсвечены, остальные кабели приглушены."""

    def __init__(self, path: QPainterPath, cable: Cable, editor: CableEditor, src: _Row, dst: _Row,
                 tooltip: str) -> None:
        super().__init__(path)
        self.cable, self.editor, self.src, self.dst = cable, editor, src, dst
        self.setZValue(0.5)
        self.setAcceptHoverEvents(True)
        self.setToolTip(tooltip)
        self.set_style(False)

    def set_style(self, hovered: bool) -> None:
        pen = QPen(_color("accent_hover" if hovered else "accent"), CABLE_HOVER_W if hovered else CABLE_W)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        self.setPen(pen)
        self.setZValue(0.6 if hovered else 0.5)

    def shape(self) -> QPainterPath:
        stroker = QPainterPathStroker()
        stroker.setWidth(CABLE_HIT)  # попасть курсором в 2-пиксельную линию
        return stroker.createStroke(self.path())

    def hoverEnterEvent(self, event) -> None:
        self.editor.hover_cable(self)

    def hoverLeaveEvent(self, event) -> None:
        self.editor.hover_cable(None)


# --- представления ---

class _ColumnView(QGraphicsView):
    """Общая настройка обеих view: своя сцена, без горизонтальной прокрутки, перерисовка при смене ширины.
    Мышь и Esc сначала отдаются редактору (handler): выделение, перетаскивание, правый клик."""

    def __init__(self, on_width_changed: Callable[[], None], parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("cables")
        self.setScene(QGraphicsScene(self))
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        self.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setMouseTracking(True)
        self.handler: CableEditor | None = None
        self._on_width_changed = on_width_changed
        self._width = 0

    def width_px(self, minimum: int) -> int:
        return max(self.viewport().width(), minimum)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self.viewport().width() != self._width:
            self._width = self.viewport().width()
            self._on_width_changed()

    def mousePressEvent(self, event) -> None:
        if self.handler is None or not self.handler.view_press(self, event):
            super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        # второй клик двойного — как обычный (шеврон, выделение), а не событие элементов
        if self.handler is None or not self.handler.view_press(self, event):
            super().mouseDoubleClickEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self.handler is None or not self.handler.view_move(self, event):
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self.handler is None or not self.handler.view_release(self, event):
            super().mouseReleaseEvent(event)

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape and self.handler is not None and self.handler.dragging:
            self.handler.cancel_drag()
            return
        super().keyPressEvent(event)

    def begin(self, height_rows: int, minimum: int) -> float:
        """Очистить сцену (позиция прокрутки сохраняется в end()); вернуть ширину сцены."""
        self._scroll = self.verticalScrollBar().value()
        self.scene().clear()
        width = self.width_px(minimum)
        self.scene().setSceneRect(0, 0, width, height_rows * ROW + 2 * PAD)
        return width

    def end(self) -> None:
        self.verticalScrollBar().setValue(self._scroll)


class CableOverlay(QWidget):
    """Прозрачный для мыши слой поверх пула и сцены: кабели-превью от строк к курсору (через границу колонок)."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setStyleSheet("background: transparent;")
        self.preview: list[QPainterPath] | None = None
        self.end: QPointF | None = None
        self.valid = False  # под курсором — строка цели (кабель ярче)

    def show_preview(self, starts: list[QPointF], end: QPointF, valid: bool = False) -> None:
        self.preview = [preview_path(a, end) for a in starts]
        self.end, self.valid = end, valid
        self.update()

    def clear_preview(self) -> None:
        self.preview = self.end = None
        self.update()

    def paintEvent(self, event) -> None:
        if self.preview is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        token = "accent_hover" if self.valid else "accent"
        pen = QPen(_color(token), CABLE_W)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        for path in self.preview:
            p.drawPath(path)
        _draw_port(p, self.end, token)


@dataclass
class _Press:
    """Нажатие на строку слева: может стать перетаскиванием или кликом."""
    view: _ColumnView
    notes: frozenset[int]
    pos: QPointF                 # в координатах viewport
    select_on_release: bool      # клик по уже выделенной строке без модификаторов: выделить только её при отпускании


@dataclass
class _Drag:
    """Перетаскивание кабеля: ноты, курсор и конец превью (догоняет курсор пружиной) в координатах CableEditor."""
    notes: tuple[int, ...]
    cursor: QPointF
    pos: QPointF
    vel: QPointF
    hover: _Row | _HeaderItem | None = None

    def step(self) -> None:
        """Шаг пружины с затуханием: конец кабеля догоняет курсор с лёгким запаздыванием."""
        self.vel = self.vel * DAMPING + (self.cursor - self.pos) * STIFFNESS
        self.pos = self.pos + self.vel


class CableEditor(QWidget):
    """Пул | подключённые и цель (QSplitter) + слой для кабелей-превью поверх обоих."""

    connect_requested = Signal(list, str)   # ноты, строка цели (slot): map — решает страница (Write to и т.п.)
    disconnect_requested = Signal(list)     # ноты: снять кабель (правило убрать)
    strike_requested = Signal(list)         # ноты: зачеркнуть (delete) или, если все зачёркнуты, вернуть
    write_to_requested = Signal(int)        # нота цели: сделать Write to и перенаправить правила

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.pool = _ColumnView(self._draw_pool)
        self.view = _ColumnView(self._draw_scene)
        self.pool.handler = self.view.handler = self
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(8)
        self.splitter.addWidget(self.pool)
        self.splitter.addWidget(self.view)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([POOL_WIDTH, 800])
        self.pool.setMinimumWidth(200)
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.addWidget(self.splitter)
        self.overlay = CableOverlay(self)

        self.profile: RemapProfile | None = None
        self.collapsed: set[str] = set(DEFAULT_COLLAPSED)  # свёрнутые блоки и группы пула
        self.show_all: set[str] = set()                    # группы цели в режиме «все»
        self.expanded: set[str] = set()                    # раскрытые алиасы («<место>|<имя>»)
        self.selection: set[int] = set()                   # выделенные ноты (строки пула и колонки 2)
        self.order: OrderSnapshot | None = None
        self.current: CableLayout | None = None  # последняя построенная раскладка
        self.active = False                      # вид показан (скрытый не перестраивается)
        self.cable_items: list[_CableItem] = []
        self.pool_items: dict[int, _Row] = {}                    # нота -> строка пула (у алиасов — общая)
        self.source_items: dict[int, _Row] = {}                  # нота -> строка колонки 2
        self.pool_rows: list[_Row] = []
        self.scene_rows: list[_Row] = []
        self.target_items: dict[str, _Row] = {}                  # строки цели по slot
        self.hovered: _CableItem | None = None
        self._issues: dict[int, list[ProfileIssue]] = {}
        self._press: _Press | None = None
        self._anchor: tuple[_ColumnView, frozenset[int]] | None = None  # начало диапазона Shift+клика
        self._drag: _Drag | None = None
        self._frame = QTimer(self)
        self._frame.setInterval(FRAME_MS)
        self._frame.timeout.connect(self._tick)
        self._spring = QTimer(self)
        self._spring.setSingleShot(True)
        self._spring.setInterval(SPRING_LOAD_MS)
        self._spring.timeout.connect(self._spring_open)
        self._spring_key: str | None = None

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.overlay.setGeometry(self.rect())
        self.overlay.raise_()

    # --- управление ---

    def set_profile(self, p: RemapProfile | None, reset_collapsed: bool = True) -> None:
        """Другой профиль (или тот же после сохранения/отката, смены карты) — пересортировать."""
        self.cancel_drag()
        self.profile = p
        self.selection.clear()
        if reset_collapsed:
            self.collapsed = set(DEFAULT_COLLAPSED)
            self.show_all.clear()
            self.expanded.clear()
        self.resort()

    def set_active(self, active: bool) -> None:
        """Вид показан или скрыт. Показ — пересортировка (правки, сделанные в таблице, раскладываются заново)."""
        self.active = active
        if not active:
            self.cancel_drag()
        if active:
            self.resort()

    def refresh(self) -> None:
        """Правила изменились: порядок заморожен — строки без кабеля остаются на местах до пересортировки."""
        if self.active:
            self._build(self.order)

    def resort(self) -> None:
        self.order = None
        if self.active:
            self._build(None)

    def toggle_pool(self, key: str) -> None:
        """Свернуть/развернуть блок или группу пула: перестраивается только пул (порядок тот же)."""
        self.collapsed ^= {key}
        if self.active:
            self._build(self.order, scene=False)

    def toggle_target(self, key: str) -> None:
        """Группа цели: «только подключённые» ↔ «все» (с пересортировкой)."""
        self.show_all ^= {key}
        self.resort()

    def toggle_alias(self, key: str, in_pool: bool) -> None:
        """Раскрыть/свернуть алиасы: перестраивается только своя колонка (порядок тот же)."""
        self.expanded ^= {key}
        if self.active:
            self._build(self.order, pool=in_pool, scene=not in_pool)

    def selected_notes(self) -> list[int]:
        return sorted(self.selection)

    def set_selection(self, notes: set[int]) -> None:
        self.selection = set(notes)
        for item in self.pool_rows + self.scene_rows:
            item.set_selected(bool(self.selection) and set(item.notes) <= self.selection)

    def source_anchor(self, note: int) -> QPointF | None:
        """Точка строки ноты (правый край) в координатах CableEditor — начало кабеля-превью.
        None — строки не видно (свёрнута) или вид не построен."""
        for view, items in ((self.view, self.source_items), (self.pool, self.pool_items)):
            item = items.get(note)
            if item is not None:
                return self._anchor_of(view, item)
        return None

    def _anchor_of(self, view: _ColumnView, item: _Row) -> QPointF:
        """Правый край первой строки элемента; за краем видимой области — прижать к краю."""
        r = item.rect
        pt = view.mapFromScene(QPointF(r.right(), r.top() + ROW / 2))
        vp = view.viewport()
        y = min(max(pt.y(), 0), vp.height())
        return QPointF(vp.mapTo(self, QPoint(pt.x(), y)))

    # --- наведение ---

    def hover_cable(self, item: _CableItem | None) -> None:
        """Кабель под курсором: он толще и ярче, его строки подсвечены, прочие кабели приглушены."""
        if self._drag is not None:
            item = None
        self.hovered = item
        for c in self.cable_items:
            c.set_style(c is item)
            c.setOpacity(1.0 if item is None or c is item else DIMMED)
        for row in self.scene_rows:
            row.set_highlighted(item is not None and row is item.src)
        for row in self.target_items.values():
            row.set_highlighted(item is not None and row is item.dst)

    # --- мышь ---

    @property
    def dragging(self) -> bool:
        return self._drag is not None

    def _item_at(self, view: _ColumnView, pos: QPoint):
        for item in view.items(pos):
            if isinstance(item, (_Row, _HeaderItem, _CableItem)):
                return item
        return None

    def view_press(self, view: _ColumnView, event) -> bool:
        """Нажатие в одной из view. True — обработано здесь (элементам сцены не передавать)."""
        pos = event.position()
        item = self._item_at(view, pos.toPoint())
        if event.button() == Qt.MouseButton.RightButton:
            self.right_click(item)
            return True
        if event.button() != Qt.MouseButton.LeftButton or self._drag is not None:
            return self._drag is not None
        scene_pt = view.mapToScene(pos.toPoint())
        if isinstance(item, _Row) and item.role == TARGET:
            badge = item.badge_rect()
            if badge is not None and badge.contains(scene_pt):
                at = view.viewport().mapToGlobal(pos.toPoint())
                QTimer.singleShot(0, lambda t=item.model: self._write_to_menu(t, at))
            return True
        if isinstance(item, _Row):
            chevron = item.chevron_rect()
            if chevron is not None and chevron.contains(scene_pt):
                QTimer.singleShot(0, lambda k=item.model.alias, pool=view is self.pool: self.toggle_alias(k, pool))
                return True
            view.setFocus()
            self._press_row(view, item, event.modifiers(), pos)
            return True
        if item is None and not event.modifiers() & (Qt.KeyboardModifier.ControlModifier
                                                     | Qt.KeyboardModifier.ShiftModifier):
            self.set_selection(set())
        return False

    def _press_row(self, view: _ColumnView, item: _Row, mods, pos: QPointF) -> None:
        notes = frozenset(item.notes)
        later = False
        if mods & Qt.KeyboardModifier.ControlModifier:
            self.set_selection(self.selection - notes if notes <= self.selection else self.selection | notes)
            self._anchor = (view, notes)
        elif mods & Qt.KeyboardModifier.ShiftModifier and self._anchor is not None and self._anchor[0] is view:
            self.set_selection(self.selection | self._range(view, self._anchor[1], notes))
        elif notes <= self.selection:
            later = True  # возможно, перетаскивание всего выделения
        else:
            self.set_selection(set(notes))
            self._anchor = (view, notes)
        self._press = _Press(view, notes, pos, later)

    def _range(self, view: _ColumnView, a: frozenset[int], b: frozenset[int]) -> set[int]:
        """Ноты строк view между строками a и b (по порядку показа)."""
        rows = sorted(self.pool_rows if view is self.pool else self.scene_rows, key=lambda i: i.rect.top())
        idx = [i for i, row in enumerate(rows) if frozenset(row.notes) in (a, b)]
        if not idx:
            return set(b)
        return {n for row in rows[min(idx):max(idx) + 1] for n in row.notes}

    def view_move(self, view: _ColumnView, event) -> bool:
        pos = event.position()
        if self._drag is not None:
            self.drag_to(QPointF(view.viewport().mapTo(self, pos.toPoint())))
            return True
        press = self._press
        if press is not None and event.buttons() & Qt.MouseButton.LeftButton:
            if (pos - press.pos).manhattanLength() >= QApplication.startDragDistance():
                notes = self.selection if press.notes <= self.selection else set(press.notes)
                self.begin_drag(notes, QPointF(view.viewport().mapTo(self, pos.toPoint())))
            return True
        return False

    def view_release(self, view: _ColumnView, event) -> bool:
        if event.button() != Qt.MouseButton.LeftButton:
            return self._drag is not None
        if self._drag is not None:
            self.end_drag(drop=True)
            return True
        press, self._press = self._press, None
        if press is not None:
            if press.select_on_release:
                self.set_selection(set(press.notes))
                self._anchor = (press.view, press.notes)
            return True
        return False

    def right_click(self, item) -> None:
        """Кабель или подключённая строка — снять кабель; строка или группа пула, строка без кабеля — зачеркнуть
        или вернуть. Сразу, без контекстного меню."""
        if self._drag is not None:
            return
        p = self.profile
        if isinstance(item, _CableItem):
            self.disconnect_requested.emit(list(item.cable.notes))
        elif isinstance(item, _Row) and item.role in (POOL, SOURCE):
            row = item.model
            if item.role == SOURCE and row.connected:
                mapped = [n for n in row.notes if p.rules.get(n) is not None and p.rules[n].action == "map"]
                self.disconnect_requested.emit(mapped)
            else:
                self.strike_requested.emit(list(row.notes))
        elif isinstance(item, _HeaderItem) and item.header.level == 1 and item.header.notes:
            self.strike_requested.emit(list(item.header.notes))

    # --- перетаскивание ---

    def begin_drag(self, notes: set[int], at: QPointF) -> None:
        """Начать перетаскивание кабеля от строк с этими нотами (at — курсор в координатах CableEditor)."""
        if not notes:
            return
        self._press = None
        self.hover_cable(None)
        self._drag = _Drag(tuple(sorted(notes)), QPointF(at), QPointF(at), QPointF(0, 0))
        for v in (self.pool, self.view):
            v.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
        self._frame.start()
        self._tick()

    def drag_to(self, at: QPointF) -> None:
        if self._drag is not None:
            self._drag.cursor = QPointF(at)
            self._update_hover()

    def end_drag(self, drop: bool = True) -> None:
        """Отпустить: над строкой цели — map (через страницу, после перерисовки); иначе — ничего."""
        d = self._drag
        if d is None:
            return
        self._drag = None
        self._frame.stop()
        self._spring.stop()
        self._spring_key = None
        self.overlay.clear_preview()
        if d.hover is not None:
            d.hover.set_highlighted(False)
        for v in (self.pool, self.view):
            v.viewport().unsetCursor()
        if drop and isinstance(d.hover, _Row):
            notes, slot = list(d.notes), d.hover.model.slot
            self.set_selection(set())
            # вопрос о Write to (модальный) — после того, как превью исчезло
            QTimer.singleShot(0, lambda: self.connect_requested.emit(notes, slot))

    def cancel_drag(self) -> None:
        self._press = None
        self.end_drag(drop=False)

    def _drop_target_at(self, at: QPointF) -> _Row | _HeaderItem | None:
        """Строка цели или заголовок группы цели под точкой (координаты CableEditor)."""
        vp = self.view.viewport()
        local = vp.mapFrom(self, at.toPoint())
        if not vp.rect().contains(local):
            return None
        for item in self.view.items(local):
            if isinstance(item, _Row) and item.role == TARGET:
                return item
            if isinstance(item, _HeaderItem) and item.header.key.startswith(TARGET_PREFIX):
                return item
        return None

    def _update_hover(self) -> None:
        d = self._drag
        target = self._drop_target_at(d.cursor)
        if target is not d.hover:
            if d.hover is not None:
                d.hover.set_highlighted(False)
            d.hover = target
            if target is not None:
                target.set_highlighted(True)
        # заголовок группы со скрытыми артикуляциями: подержать курсор — показать все
        key = target.header.key if isinstance(target, _HeaderItem) and target.header.collapsed else None
        if key != self._spring_key:
            self._spring_key = key
            if key is None:
                self._spring.stop()
            else:
                self._spring.start()

    def _spring_open(self) -> None:
        key = self._spring_key
        if self._drag is None or key is None:
            return
        self._spring_key = None
        self.show_all.add(key)
        self._build(self.order, pool=False)  # порядок тот же: строки, которые тащат, не двигаются
        self._update_hover()

    def _tick(self) -> None:
        """Кадр перетаскивания: пружина, автопрокрутка, цель под курсором, превью."""
        d = self._drag
        if d is None:
            return
        d.step()
        self._autoscroll(d.cursor)
        self._update_hover()
        self.overlay.show_preview(self._drag_anchors(d.notes), d.pos, isinstance(d.hover, _Row))

    def _drag_anchors(self, notes: tuple[int, ...]) -> list[QPointF]:
        wanted = set(notes)
        out: list[QPointF] = []
        for view, rows in ((self.pool, self.pool_rows), (self.view, self.scene_rows)):
            for item in rows:
                if not item.model.expanded and set(item.notes) <= wanted:
                    out.append(self._anchor_of(view, item))
        return out[:MAX_PREVIEW]

    def _autoscroll(self, at: QPointF) -> None:
        """Курсор у верхнего/нижнего края колонки (или за ним) — прокрутить её; быстрее, чем ближе к краю."""
        for view in (self.pool, self.view):
            vp = view.viewport()
            top_left = vp.mapTo(self, QPoint(0, 0))
            if not top_left.x() <= at.x() <= top_left.x() + vp.width():
                continue
            top, bottom = top_left.y(), top_left.y() + vp.height()
            if at.y() < top + EDGE:
                depth = top + EDGE - at.y()
                step = -1
            elif at.y() > bottom - EDGE:
                depth = at.y() - (bottom - EDGE)
                step = 1
            else:
                continue
            bar = view.verticalScrollBar()
            bar.setValue(bar.value() + step * max(1, min(SCROLL_MAX, round(depth / EDGE * SCROLL_MAX))))

    # --- Write to ---

    def pick_write_to(self, t: TargetRow, at: QPoint) -> int | None:
        """Меню нот артикуляции (номер, высота), текущий Write to отмечен. None — ничего не выбрали."""
        menu = QMenu(self)
        menu.addSection("Write to")
        for n in t.notes:
            action = menu.addAction(f"{n}   {pitch_name(n)}")
            action.setCheckable(True)
            action.setChecked(n == t.write_to)
            action.setData(n)
        chosen = menu.exec(at)
        return chosen.data() if chosen is not None and chosen.data() is not None else None

    def _write_to_menu(self, t: TargetRow, at: QPoint) -> None:
        n = self.pick_write_to(t, at)
        if n is not None and n != t.write_to:
            self.write_to_requested.emit(n)

    # --- построение ---

    def _build(self, snapshot: OrderSnapshot | None, *, pool: bool = True, scene: bool = True) -> None:
        lay = build_layout(self.profile, self.collapsed, snapshot, self.show_all, self.expanded)
        if self.current is not None:  # порядок тот же — нетронутая колонка остаётся как есть
            if not pool:
                lay.pool = self.current.pool
            if not scene:
                lay.scene = self.current.scene
        self.current = lay
        self.order = lay.order
        self._issues = {}
        if self.profile is not None:
            for i in validate_profile(self.profile):
                if i.code != NO_RULE:
                    self._issues.setdefault(i.note, []).append(i)
        if self._drag is not None and self._drag.hover is not None:
            self._drag.hover = None  # элементы сейчас пересоздадутся
        if pool:
            self._draw_pool()
        if scene:
            self._draw_scene()
        visible = {n for item in self.pool_rows + self.scene_rows for n in item.notes}
        self.set_selection(self.selection & visible)

    def _draw_pool(self) -> None:
        lay = self.current
        self.pool_items, self.pool_rows = {}, []
        if lay is None:
            return
        width = self.pool.begin(lay.pool.height, 200)
        col = width - 2 * PAD
        scene = self.pool.scene()
        for h in lay.pool.headers:
            tip = "Click to expand" if h.collapsed else "Click to collapse"
            if h.level == 1:
                tip += f"\n{GROUP_HINT}"
            scene.addItem(_HeaderItem(QRectF(PAD, PAD + h.y * ROW, col, ROW), h, self.toggle_pool, tip))
        for r in lay.pool.rows:
            indent = INDENT if r.child else 0
            item = self._source_item(QRectF(PAD + indent, PAD + r.y * ROW, col - indent, ROW), r, POOL)
            self._register(item, self.pool_items, self.pool_rows)
            scene.addItem(item)
        self.pool.end()

    @staticmethod
    def _register(item: _Row, by_note: dict[int, _Row], rows: list[_Row]) -> None:
        rows.append(item)
        if item.model.expanded:  # заголовок алиасов: ноты закреплены за их собственными строками ниже
            for n in item.notes:
                by_note.setdefault(n, item)
        else:
            for n in item.notes:
                by_note[n] = item

    def _scene_columns(self, width: float) -> tuple[float, float, float]:
        """x колонки 2, x колонки 3, ширина колонки."""
        gap = min(220.0, max(90.0, width * 0.22))
        col = (width - 2 * PAD - gap) / 2
        return PAD, PAD + col + gap, col

    def _draw_scene(self) -> None:
        lay = self.current
        self.cable_items, self.source_items, self.scene_rows, self.target_items = [], {}, [], {}
        self.hovered = None
        if lay is None:
            return
        sc = lay.scene
        width = self.view.begin(sc.height, 460)
        lx, rx, col = self._scene_columns(width)
        scene = self.view.scene()

        def rect(x: float, y: int, h: int = 1) -> QRectF:
            return QRectF(x, PAD + y * ROW, col, h * ROW)

        for h in sc.target_headers:
            if h.key in self.show_all:
                tip = "All articulations shown. Click to show connected only"
            else:
                tip = "Connected only. Click to show all articulations"
            if h.shown:
                tip = f"{h.shown} of {h.count} connected\n{tip}"
            scene.addItem(_HeaderItem(rect(rx, h.y), h, self.toggle_target, tip))
        connected_slots = {c.target.slot for c in sc.cables}
        for t in sc.target_rows:
            item = self._target_item(rect(rx, t.y, t.height), t, t.slot in connected_slots)
            self.target_items[t.slot] = item
            scene.addItem(item)
            if t.height > 1:
                scene.addItem(_Bundle(rect(lx, t.y, t.height).adjusted(-3, 0, 3, 0)))
        for r in sc.source_rows:
            indent = INDENT if r.child else 0
            item = self._source_item(rect(lx, r.y).adjusted(indent, 0, 0, 0), r, SOURCE)
            if r.stale:
                item.setOpacity(STALE)
            self._register(item, self.source_items, self.scene_rows)
            scene.addItem(item)
        rows_by_y = {item.model.y: item for item in self.scene_rows}
        x1, x2 = lx + col, rx
        for c in sc.cables:
            a = QPointF(x1, PAD + c.src_y * ROW + ROW / 2)
            b = QPointF(x2, PAD + (c.target.y + c.target.height / 2) * ROW)
            item = _CableItem(cable_path(a, b), c, self, rows_by_y[c.src_y], self.target_items[c.target.slot],
                              self._cable_tip(c.notes, c.dst))
            scene.addItem(item)
            self.cable_items.append(item)
        self.view.end()

    def _source_item(self, r: QRectF, row: SourceRow, role: str) -> _Row:
        p = self.profile
        tgt = p.target_map
        if row.connected and not row.expanded:
            tip = f"{self._cable_tip(row.notes, p.rules[row.note].dst)}\n{CONNECTED_HINT}"
        else:
            tip = STATE_TIPS.get(row.state, "")
            if row.state == KEEP and tgt is not None:
                tip += f": {tgt.names[row.note]}" if row.note in tgt.names else " (no such note in the target map)"
            tip += f"\n{STALE_TIP}" if row.stale else f"\n{ROW_HINT}"
        if len(row.notes) > 1:
            tip = f"Notes {', '.join(map(str, row.notes))}\n{tip}\n{MIXED_HINT if row.mixed else ALIAS_HINT}"
        issues = [i for n in row.notes for i in self._issues.get(n, [])]
        if issues:
            tip = "\n".join([i.message for i in issues] + [tip])
        chevron = None
        if row.alias is not None:
            chevron = "fixed" if row.mixed else "expanded" if row.expanded else "collapsed"
        return _Row(r, role, row, str(row.note), pitch_name(row.note), row.name or "—",
                    name_color="text_faint" if row.state == DELETE or row.name is None else "text",
                    strike=row.state == DELETE, marker="=" if row.state == KEEP else "", count=len(row.notes),
                    chevron=chevron, port="right" if row.connected and not row.expanded else None,
                    warn=bool(issues), tooltip=tip)

    def _target_item(self, r: QRectF, t: TargetRow, connected: bool) -> _Row:
        tgt = self.profile.target_map
        port = "left" if connected else None
        if not t.in_map:
            tip = f"Note {t.notes[0]} is not in the target map" if tgt is not None else "No target map"
            return _Row(r, TARGET, t, str(t.notes[0]), pitch_name(t.notes[0]), "—", name_color="text_faint",
                        italic=True, port=port, tooltip=tip)
        note = t.write_to if t.write_to is not None else t.notes[0]
        tip = ""
        if len(t.notes) > 1:
            wt = f"Write to: {t.write_to}" if t.write_to is not None else "Write to: not chosen"
            tip = f"On notes {', '.join(map(str, t.notes))} · {wt}\n{BADGE_HINT.format(n=len(t.notes) - 1)}"
        many = len(t.notes) > 1
        return _Row(r, TARGET, t, str(note), pitch_name(note), t.label, marker=f"+{len(t.notes) - 1}" if many else "",
                    badge=many, port=port, tooltip=tip)

    def _cable_tip(self, notes: tuple[int, ...], dst: int) -> str:
        p = self.profile
        src_name = p.source_map.names.get(notes[0], "") if p.source_map is not None else ""
        tgt = p.target_map
        dst_name = tgt.names.get(dst, "") if tgt is not None else ""
        text = f"{', '.join(map(str, notes))} {src_name}".strip() + "  →  " + f"{dst} {dst_name}".strip()
        if tgt is not None and dst in tgt.names:
            wt = primary_note(tgt, dst_name)
            if wt is not None and wt != dst:
                text += f"\nNot the Write to note ({wt})"
        return text
