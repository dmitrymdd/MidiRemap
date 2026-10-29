"""Вид профиля «кабелями»: показ и правка перетаскиванием кабелей.

Колонки (QSplitter): пул — отдельная QGraphicsView со своей прокруткой (неподключённые ноты по группам
инструментов, зачёркнутые — delete — в своей группе); сцена — вторая QGraphicsView: колонка «from» (подключённые
ноты), промежуток для кабелей и колонка «to» (карта цели) — одна общая прокрутка, кабели внутри сцены. Над пулом —
заголовок «Unassigned» (не группа, не сворачивается), над сценой — слоты from_head / to_head, выровненные по
колонкам и следующие за их границами; их заполняет страница (выбор карт, панель подсказок). Поверх всего —
прозрачный для мыши слой CableOverlay: на нём рисуется кабель-превью от исходных строк к курсору через границу пула
и сцены. Пустая колонка «from» — подсказка по центру (EMPTY_HINT).

Направление (set_direction): вид строится по profile.oriented(direction) (поле shown) одним и тем же кодом —
поток всегда слева направо: [пул] [подключённые ноты] кабели [карта цели]. В REVERSE это ноты целевой карты слева
и артикуляции исходной карты справа. Отличаются только цвет кабелей и всего, что с ними связано (TONES: → — accent,
← — reverse), и названия карт в подсказках. Свёрнутые группы, режимы групп цели, раскрытые алиасы — свои у каждого
направления.

Порядок, группы, алиасы, высоты строк и кабели считает cable_layout (без Qt); здесь — рисование, выделение,
перетаскивание, правый клик и подсказки. Профиль — рабочая копия страницы Profiles: виджет его НЕ меняет, а
сигналами просит страницу (connect_requested / group_drop_requested / disconnect_requested / strike_requested /
write_to_requested / primary_requested) — правила меняет ядро (core/profile.py) через страницу. Ноты и строки
цели в сигналах — ориентированного профиля (в REVERSE ноты — целевой карты, строки цели — артикуляции исходной);
страница разбирает их по направлению. Двойной клик по кабелю — сделать его основным (primary_requested).

Мышь: строки пула и колонки «from» выделяются (Ctrl/Shift — несколько) и перетаскиваются на строку цели (назначение
по совпадению номеров, см. assign_plan) или на заголовок группы цели (n → n для совпавших номеров); заголовок
группы пула тоже можно перетащить — со всеми его нотами. Кабель-превью
догоняет курсор с лёгкой пружиной (таймер ~60 кадров/с), у края любой колонки — автопрокрутка, Esc — отмена.
Наведение на заголовок группы цели во время перетаскивания (~500 мс) показывает все её артикуляции.
Правый клик: кабель (или подключённая строка) — снять кабель; строка или группа пула — зачеркнуть
(правило delete) / вернуть (без правила). Бейдж «+N» строки цели — меню выбора Write to.
Строка цели показывает номера, на которые идут кабели (TargetRow.lines); Write to — цветом акцента.

Подсказки (set_suggestions) — пунктирные кабели (на мышь не реагируют), у строки-подсказки — кольцо вместо точки.
Границы колонок сцены (правый край «from», края «to») тянутся мышью (зона — со стороны промежутка),
граница пула — QSplitter; ширины — в QSettings (ширина пула в px, колонки — доли ширины сцены). Имя или подпись
не помещается — полностью в подсказке.

После каждой правки — refresh(): раскладка строится заново (порядок не замораживается: снятая с кабеля нота
сразу в своей группе пула). Чтобы вид не прыгал, прокрутка каждой колонки держится за якорь — строку под курсором
или верхнюю видимую (у сцены — строки и заголовки цели). Сворачивание в пуле и раскрытие алиасов перестраивают
только свою колонку.
"""
from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field

from PySide6.QtCore import QEvent, QPoint, QPointF, QRectF, QSettings, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QFont, QFontMetrics, QPainter, QPainterPath, QPainterPathStroker, QPen
from PySide6.QtWidgets import (
    QApplication, QGraphicsItem, QGraphicsPathItem, QGraphicsScene, QGraphicsView, QHBoxLayout, QLabel, QMenu,
    QSizePolicy, QSplitter, QVBoxLayout, QWidget,
)

from ..core.notemap import primary_note
from ..core.pitch import pitch_name
from ..core.profile import FORWARD, NO_RULE, REVERSE, RemapProfile, validate_profile
from .cable_layout import (
    DELETE, KEEP, MIXED, POOL_PREFIX, TARGET_PREFIX, UNASSIGNED, Cable, CableLayout, Header,
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
CABLE_W = 2.0                      # подсказки (пунктир), превью от подключённых строк
CABLE_PRIMARY_W = CABLE_W          # основной кабель ноты цели (Cable.primary)
CABLE_THIN_W = CABLE_W / 2         # прочие кабели; превью от неназначенных нот (2 : 1: при 100 %
                                   # на обычном экране 2 : 1.33 у изогнутых кабелей почти не различимо)
CABLE_HOVER_EXTRA = 1.0            # кабель под курсором — толще на столько
CABLE_HIT = 16      # ширина зоны попадания по кабелю (по 8 px в стороны)
DIMMED = 0.3        # прозрачность прочих кабелей, пока один под курсором
POOL_WIDTH = 310    # начальная ширина пула
SCENE_MIN = 460     # минимальная ширина сцены, px
MIN_COL, MIN_GAP = 140.0, 40.0  # минимальные ширины колонки и промежутка для кабелей
GRIP = 6            # ширина зоны захвата границы колонок, px
SUGGESTED = 0.7     # непрозрачность пунктирного кабеля подсказки
# ключи QSettings: ширина пула (px) и доли ширины сцены колонок
POOL_KEY, COLUMNS_KEY = "cables/unassigned_width", "cables/scene_columns"
POOL_MIN = 200      # минимальная ширина пула
HEAD_H = 34         # высота строки-заголовка над колонками

# цвет кабелей направления (кабели, точки, обводка цели, превью): обычный и под курсором
TONES = {FORWARD: ("accent", "accent_hover"), REVERSE: ("reverse", "reverse_hover")}
SIDES = {FORWARD: ("source", "target"), REVERSE: ("target", "source")}  # карты сторон «from» и «to» направления

FRAME_MS = 16                   # кадр кабеля-превью и автопрокрутки
STIFFNESS, DAMPING = 0.3, 0.6   # пружина конца кабеля-превью (лёгкое запаздывание, без раскачки)
SAG = 0.12                      # провис кабеля-превью: доля длины (не больше SAG_MAX px)
SAG_MAX = 48.0
EDGE = 32                       # зона автопрокрутки у верхнего/нижнего края, px
SCROLL_MAX = 18                 # px за кадр
SPRING_LOAD_MS = 500            # наведение на заголовок группы цели при перетаскивании — показать все
MAX_PREVIEW = 24                # кабелей-превью при перетаскивании многих строк

POOL, SOURCE, TARGET = "pool", "source", "target"  # роль строки: пул, колонка «from», цель

STATE_TIPS = {
    UNASSIGNED: "No target yet: removed when saving unless you keep it",
    KEEP: "Kept on the same number",
    DELETE: "Deleted from converted files",
    MIXED: "These notes have different rules",
}
# ←: ноты цели без обратного правила при сохранении не спрашиваются (полнота — статус)
REVERSE_UNASSIGNED_TIP = "No rule in this direction: kept on the same number when converting"
PRIMARY_HINT = "Double-click to make primary"
SAME_NUMBER_HINT = "Double-click to connect to the same number"
NUMBER_DROP_HINT = "Drop on a number to connect to that note"
ROW_HINT = "Drag onto a target to map · Ctrl/Shift+click to select several · Right-click to delete or restore"
CONNECTED_HINT = "Drag onto another target to remap · Right-click to remove the cable"
ALIAS_HINT = "Click the arrow to show the notes one by one"
MIXED_HINT = "Notes with different rules are always shown one by one"
POOL_TITLE = "Unassigned"
POOL_TIP = ("{side} notes not connected in this direction, by instrument.\n"
            "Struck-through notes are deleted: right-click to restore")
EMPTY_HINT = "Drag notes from Unassigned onto the {side} map"
BADGE_HINT = "Click the badge to choose the Write to note"
WRITE_TO_HINT = "Write to: {n} — notes from other numbers are written here"
GROUP_HINT = ("Drag onto a target group to connect notes with the same numbers\n"
              "Right-click to delete or restore the whole group")
TARGET_GROUP_HINT = "Drop notes here to connect those with the same numbers"
SUGGESTED_HINT = "Apply in the bar above, or drag onto another target"
SUGGESTED_WRITE_TO_HINT = ("The target is on several notes: drag the row onto it to choose the Write to note. "
                           "Apply skips it")


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


def _setting(settings: QSettings | None, key: str, default, kind):
    """Значение из QSettings нужного типа; нет или битое — default."""
    if settings is None:
        return default
    try:
        value = settings.value(key)
        return default if value is None else kind(value)
    except (TypeError, ValueError):
        return default


def _load_columns(settings: QSettings | None) -> tuple[float, float, float] | None:
    try:
        parts = tuple(float(x) for x in _setting(settings, COLUMNS_KEY, "", str).split(","))
    except ValueError:
        return None
    if len(parts) != 3 or any(f <= 0 for f in parts) or sum(parts) > 1.001:
        return None
    return parts


def _color(token: str, alpha: float = 1.0) -> QColor:
    c = QColor(TOKENS[token])
    c.setAlphaF(alpha)
    return c


def _draw_port(p: QPainter, c: QPointF, token: str = "accent", hollow: bool = False) -> None:
    """Точка подключения кабеля; hollow — кольцо (только подсказка, правила ещё нет)."""
    if hollow:
        p.setPen(QPen(_color(token), 1.2))
        p.setBrush(_color("bg"))
    else:
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
    """Строка: фон со скруглением, номер, высота ноты, имя, бейдж «+N» и маркер справа; точка кабеля слева
    или справа. Высокая строка цели (связка многие-в-одну) — один блок, текст на уровне первой строки напротив.

    role — POOL / SOURCE / TARGET; model — SourceRow или TargetRow из раскладки. pill — текст бейджа («+N» —
    ещё N нот: алиасы источника или скрытые ноты артикуляции цели); badge — бейдж кликабелен (меню Write to).
    port — сторона точек кабеля ("left" / "right"; точка — на каждом номере из lines); tone — токены цвета
    направления (обычный, под курсором)."""

    def __init__(self, rect: QRectF, role: str, model: SourceRow | TargetRow, number: str, pitch: str, name: str,
                 *, name_color="text", strike=False, italic=False, marker="", pill="", chevron: str | None = None,
                 badge=False, port: str | None = None, dashed=False, warn=False, tooltip="",
                 lines: list[tuple[int, str, str]] | None = None, tone: tuple[str, str] = TONES[FORWARD]) -> None:
        super().__init__()
        self.rect, self.role, self.model = rect, role, model
        self.number, self.pitch, self.name = number, pitch, name
        # номера по строкам блока: (смещение, номер, высота); по умолчанию — один, на первой строке
        self.lines = lines if lines is not None else [(0, number, pitch)]
        self.name_color, self.strike, self.italic, self.marker = name_color, strike, italic, marker
        self.pill, self.chevron, self.badge = pill, chevron, badge  # chevron: collapsed / expanded / fixed
        self.port, self.dashed, self.warn, self.tone = port, dashed, warn, tone
        self.highlighted = False
        self.selected = False
        self.drop_zone: tuple | None = None  # строка цели под кабелем-превью: зона (см. zone_at)
        self._hover = False
        self.setZValue(1)
        self.setAcceptHoverEvents(True)
        if tooltip:
            self.setToolTip(tooltip)

    @property
    def notes(self) -> tuple[int, ...]:
        return self.model.notes

    def number_rect(self, off: int) -> QRectF:
        """Зона номера на строке off блока (номер и высота ноты) — цель drop «ровно на эту ноту»."""
        return QRectF(self.rect.left(), self.rect.top() + off * ROW, 6 + NUM_W + 8 + PITCH_W, ROW)

    def zone_at(self, pt: QPointF) -> tuple:
        """Зона drop строки цели под точкой сцены: ("badge",) — бейдж «+N» / «…» (меню нот артикуляции);
        ("line", смещение, нота) — номер на строке (ровно на эту ноту); ("row",) — остальное (назначение на артикуляцию, assign_plan)."""
        badge = self.badge_rect()
        if badge is not None and badge.contains(pt):
            return ("badge",)
        if self.role == TARGET:
            for off, n in self.model.numbers:
                if self.number_rect(off).contains(pt):
                    return ("line", off, n)
        return ("row",)

    def set_drop_zone(self, zone: tuple | None) -> None:
        if zone != self.drop_zone:
            self.drop_zone = zone
            self.update()

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

    def _right(self) -> float:
        """Правый край содержимого (левее шеврона)."""
        return self.rect.right() - (CHEVRON_W + 4 if self.chevron else 0)

    def _pill_right(self) -> float:
        return self._right() - (MARK_W if self.marker else 0)

    def name_room(self) -> float:
        """Ширина под имя, px (имя длиннее — обрезается, полное — в подсказке)."""
        x = self.rect.left() + 6 + NUM_W + 8 + PITCH_W
        return max(0.0, self._pill_right() - (BADGE_W if self.pill else 8) - x)

    def chevron_rect(self) -> QRectF | None:
        """Зона шеврона алиасов (в координатах сцены); None — шеврона нет или он не переключается."""
        if self.chevron not in ("collapsed", "expanded"):
            return None
        return QRectF(self.rect.right() - CHEVRON_W - 4, self.rect.top(), CHEVRON_W + 4, ROW)

    def badge_rect(self) -> QRectF | None:
        """Зона кликабельного бейджа (меню Write to строки цели)."""
        if not self.badge or not self.pill:
            return None
        return QRectF(self._pill_right() - BADGE_W - 4, self.rect.top(), BADGE_W + 4, ROW)

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
        zone = self.drop_zone[0] if self.drop_zone else None
        outline = self.highlighted or zone == "row"
        bg = ("selection" if self.selected else "warning_bg" if self.warn
              else "surface_hover" if self._hover or outline or zone else "surface")
        # подсветка (кабель под курсором, цель при перетаскивании) — тонкая обводка цветом направления
        p.setPen(QPen(_color(self.tone[0], 0.8), 1) if outline else Qt.PenStyle.NoPen)
        p.setBrush(_color(bg))
        p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), RADIUS, RADIUS)
        if zone == "line":  # drop ровно на ноту: обведён только номер этой строки (уже обводки строки)
            p.setPen(QPen(_color(self.tone[1]), 1.2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(self.number_rect(self.drop_zone[1]).adjusted(1.5, ROW_INSET + 1, -1.5, -ROW_INSET - 1),
                              RADIUS - 1, RADIUS - 1)
        line = QRectF(r.left(), r.top(), r.width(), ROW - 2 * ROW_INSET)  # первая строка блока
        x = r.left() + 6
        left_mid = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        right_mid = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        num_font, pitch_font = _font(base, weight=QFont.Weight.Medium), _font(base, size_delta=-1.5)
        for off, number, pitch in self.lines:  # у строки цели — номер на уровне своего кабеля
            top = line.top() + off * ROW
            p.setFont(num_font)
            p.setPen(_color("text"))  # номера акцентом не выделяются
            p.drawText(QRectF(x, top, NUM_W, line.height()), right_mid, number)
            p.setFont(pitch_font)
            p.setPen(_color("text_muted"))
            p.drawText(QRectF(x + NUM_W + 8, top, PITCH_W, line.height()), left_mid, pitch)
        x += NUM_W + 8 + PITCH_W
        name_w = self.name_room()
        font = _font(base, strike=self.strike, italic=self.italic)
        text = QFontMetrics(font).elidedText(self.name, Qt.TextElideMode.ElideRight, int(name_w))
        p.setFont(font)
        p.setPen(_color(self.name_color))
        p.drawText(QRectF(x, line.top(), name_w, line.height()), left_mid, text)
        if self.pill:
            pill = QRectF(self._pill_right() - BADGE_W, line.top() + 4, BADGE_W - 6, line.height() - 8)
            hot = zone == "badge"  # drop на бейдж — меню нот артикуляции
            p.setPen(QPen(_color(self.tone[1] if hot else "border"), 1.2 if hot else 1))
            p.setBrush(_color("surface_hover" if hot else "bg"))
            p.drawRoundedRect(pill, pill.height() / 2, pill.height() / 2)
            p.setFont(_font(base, size_delta=-1.5, bold=True))
            p.setPen(_color(self.tone[1] if hot else "text_muted"))
            p.drawText(pill, Qt.AlignmentFlag.AlignCenter, self.pill)
        if self.marker:
            p.setFont(_font(base, size_delta=-1.5, bold=True))
            p.setPen(_color("text_muted"))
            p.drawText(QRectF(self._right() - MARK_W, line.top(), MARK_W - 6, line.height()), right_mid,
                       self.marker)
        if self.chevron:
            _draw_chevron(p, r.right() - CHEVRON_W + 2, line.center().y(), self.chevron == "collapsed",
                          "text_faint" if self.chevron == "fixed" else "text_muted")
        if self.port:  # точка на каждом номере (у цели — куда приходят кабели), со своей стороны
            token = self.tone[1] if self.highlighted else self.tone[0]
            x = r.left() if self.port == "left" else r.right()
            for off, *_ in self.lines:
                _draw_port(p, QPointF(x, self.rect.top() + (off + 0.5) * ROW), token, self.dashed)


class _HeaderItem(QGraphicsItem):
    """Заголовок группы: шеврон, имя, число; клик — свернуть или развернуть (у цели — сменить режим)."""

    def __init__(self, rect: QRectF, header: Header, on_toggle: Callable[[str], None], tooltip: str,
                 tone: tuple[str, str] = TONES[FORWARD]) -> None:
        super().__init__()
        self.rect, self.header, self.tone = rect, header, tone
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

    def label_x(self) -> float:
        return self.rect.left() + 6 + 14

    def label_room(self) -> float:
        """Ширина под подпись, px (справа — место под число)."""
        return max(0.0, self.rect.right() - self.label_x() - 48)

    def label_font(self, base: QFont) -> QFont:
        return _font(base, bold=True, size_delta=-2.5, caps=True)

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
            p.setPen(QPen(_color(self.tone[0], 0.8), 1) if self.highlighted else Qt.PenStyle.NoPen)
            p.setBrush(_color("surface_hover"))
            p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), RADIUS, RADIUS)
        x = self.label_x()
        _draw_chevron(p, x - 14, r.center().y(), h.collapsed)
        font = self.label_font(base)
        fm = QFontMetrics(font)
        p.setFont(font)
        p.setPen(_color("text_muted"))
        avail = self.label_room()
        text = fm.elidedText(h.label, Qt.TextElideMode.ElideRight, int(avail))
        left_mid = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        p.drawText(QRectF(x, r.top(), avail, r.height()), left_mid, text)
        count = f"{h.shown} / {h.count}" if h.shown else str(h.count)  # цель: подключённые / все артикуляции
        p.setPen(_color("text_faint"))
        p.drawText(QRectF(x + fm.horizontalAdvance(text) + 8, r.top(), 48, r.height()), left_mid, count)


class _Bundle(QGraphicsItem):
    """Тонкая рамка вокруг строк колонки «from» напротив одной высокой строки цели: связка читается как один блок."""

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
    """Кабель: наведение — толще и ярче, его строки подсвечены, остальные кабели приглушены.
    Подсказка (cable.suggested) — пунктир, на мышь не реагирует (действия — у строки и в панели подсказок)."""

    def __init__(self, path: QPainterPath, cable: Cable, editor: CableEditor, src: _Row, dst: _Row,
                 tooltip: str, tone: tuple[str, str] = TONES[FORWARD]) -> None:
        super().__init__(path)
        self.cable, self.editor, self.src, self.dst, self.tone = cable, editor, src, dst, tone
        self.setZValue(0.5)
        self.setAcceptHoverEvents(not cable.suggested)
        if not cable.suggested:
            self.setToolTip(tooltip)
        self.set_style(False)

    @property
    def ends(self) -> tuple[int, int]:
        """(нота строки, нота цели) ориентированного профиля: у строки алиасов — её показываемый номер."""
        return self.src.model.shown, self.cable.dst

    def set_style(self, hovered: bool) -> None:
        normal, hover = self.tone
        if self.cable.suggested:
            pen = QPen(_color(normal, SUGGESTED), CABLE_W, Qt.PenStyle.CustomDashLine)
            pen.setDashPattern([3, 3])
            self.setPen(pen)
            self.setZValue(0.4)
            return
        width = CABLE_PRIMARY_W if self.cable.primary else CABLE_THIN_W
        pen = QPen(_color(hover if hovered else normal), width + CABLE_HOVER_EXTRA if hovered else width)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        self.setPen(pen)
        self.setZValue(0.6 if hovered else 0.5)

    def shape(self) -> QPainterPath:
        if self.cable.suggested:
            return QPainterPath()  # не перехватывает мышь
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
        self.guide_x: float | None = None  # граница колонок под курсором или перетаскиваемая — тонкая линия
        self.hint: tuple[float, float, str] | None = None  # подсказка пустой колонки: x, ширина, текст

    def set_guide(self, x: float | None) -> None:
        if x != self.guide_x:
            self.guide_x = x
            self.viewport().update()

    def set_hint(self, hint: tuple[float, float, str] | None) -> None:
        if hint != self.hint:
            self.hint = hint
            self.viewport().update()

    def drawForeground(self, p: QPainter, rect: QRectF) -> None:
        if self.guide_x is not None:
            p.setPen(QPen(_color("accent", 0.6), 1))
            p.drawLine(QPointF(self.guide_x, rect.top()), QPointF(self.guide_x, rect.bottom()))
        if self.hint is not None:  # по центру видимой части колонки (не зависит от высоты сцены)
            x, width, text = self.hint
            visible = self.mapToScene(self.viewport().rect()).boundingRect()
            p.setFont(self.font())
            p.setPen(_color("text_faint"))
            p.drawText(QRectF(x, visible.top(), width, visible.height()),
                       Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, text)

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
        self.width = CABLE_W
        self.tone = TONES[FORWARD]

    def show_preview(self, starts: list[QPointF], end: QPointF, valid: bool = False, width: float = CABLE_W,
                     tone: tuple[str, str] = TONES[FORWARD]) -> None:
        self.preview = [preview_path(a, end) for a in starts]
        self.end, self.valid, self.width, self.tone = end, valid, width, tone
        self.update()

    def clear_preview(self) -> None:
        self.preview = self.end = None
        self.update()

    def paintEvent(self, event) -> None:
        if self.preview is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        token = self.tone[1] if self.valid else self.tone[0]
        pen = QPen(_color(token), self.width)
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
    header: str | None = None    # нажали на заголовок пула: клик — свернуть, перетаскивание — все его ноты


@dataclass
class _Drag:
    """Перетаскивание кабеля: ноты, курсор и конец превью (догоняет курсор пружиной) в координатах CableEditor."""
    notes: tuple[int, ...]
    cursor: QPointF
    pos: QPointF
    vel: QPointF
    hover: _Row | _HeaderItem | None = None
    header: str | None = None    # тащат заголовок пула: кабель-превью — от него
    zone: tuple | None = None    # зона строки цели под курсором (_Row.zone_at)

    def step(self) -> None:
        """Шаг пружины с затуханием: конец кабеля догоняет курсор с лёгким запаздыванием."""
        self.vel = self.vel * DAMPING + (self.cursor - self.pos) * STIFFNESS
        self.pos = self.pos + self.vel


@dataclass
class _ViewState:
    """Свёрнутость вида — своя у каждого направления (ключи групп двух карт могут совпасть)."""
    collapsed: set[str] = field(default_factory=set)  # свёрнутые группы пула
    show_all: set[str] = field(default_factory=set)   # группы цели в режиме «все»
    expanded: set[str] = field(default_factory=set)   # раскрытые алиасы («<место>|<имя>»)


def _row_box(widget: QWidget) -> QHBoxLayout:
    box = QHBoxLayout(widget)
    box.setContentsMargins(0, 0, 0, 0)
    box.setSpacing(6)
    return box


def _column(head: QWidget, view: QGraphicsView) -> QWidget:
    """Колонка сплиттера: строка-заголовок и view под ней."""
    col = QWidget()
    box = QVBoxLayout(col)
    box.setContentsMargins(0, 0, 0, 0)
    box.setSpacing(6)
    head.setFixedHeight(HEAD_H)
    box.addWidget(head)
    box.addWidget(view, stretch=1)
    return col


class CableEditor(QWidget):
    """Пул | сцена: подключённые и цель (QSplitter) + слой для кабелей-превью поверх всего."""

    connect_requested = Signal(list, str)   # ноты, строка цели (slot): map — решает страница (Write to и т.п.)
    group_drop_requested = Signal(list, list)  # ноты, ноты группы цели: n → n для совпавших номеров
    disconnect_requested = Signal(list)     # ноты: снять кабель (правило убрать)
    strike_requested = Signal(list)         # ноты: зачеркнуть (delete) или, если все зачёркнуты, вернуть
    write_to_requested = Signal(int)        # нота цели: сделать Write to и перенаправить правила
    primary_requested = Signal(int, int)    # двойной клик: кабель (нота строки, нота цели) — сделать основным
    same_number_requested = Signal(list)    # двойной клик по строке Unassigned: ноты — на те же номера
    note_drop_requested = Signal(list, int)  # drop на номер строки цели (или выбор в меню бейджа): ровно на ноту

    def __init__(self, settings: QSettings | None = None, parent=None) -> None:
        super().__init__(parent)
        self.settings = settings  # ширины колонок между запусками
        self.pool = _ColumnView(self._draw_pool)
        self.view = _ColumnView(self._draw_scene)
        self.pool.handler = self.view.handler = self
        # над пулом — заголовок колонки; над сценой — слоты, выровненные по колонкам «from» и «to» (_place_heads)
        pool_head = QWidget()
        pool_head.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)  # ширину пула задаёт не заголовок
        self.pool_title = QLabel(POOL_TITLE)
        self.pool_title.setObjectName("columnTitle")
        self.pool_head = _row_box(pool_head)  # страница добавляет кнопки справа от заголовка
        self.pool_head.addWidget(self.pool_title)
        self.pool_head.addStretch(1)
        self.scene_head = QWidget()
        self.from_slot, self.gap_slot, self.to_slot = (QWidget(self.scene_head) for _ in range(3))
        self.from_head, self.gap_head, self.to_head = (_row_box(w) for w in (self.from_slot, self.gap_slot,
                                                                             self.to_slot))
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(8)
        self.splitter.addWidget(_column(pool_head, self.pool))
        self.splitter.addWidget(_column(self.scene_head, self.view))
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        # ширина пула в px; точно — при первом показе (до него QSplitter масштабирует её пропорционально)
        self._pool_width: int | None = _setting(settings, POOL_KEY, POOL_WIDTH, int)
        self.splitter.setSizes([self._pool_width, 800])
        self.splitter.splitterMoved.connect(self._save_pool_width)
        self.pool.setMinimumWidth(POOL_MIN)
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.addWidget(self.splitter)
        self.overlay = CableOverlay(self)

        self.profile: RemapProfile | None = None  # рабочая копия страницы (настоящий профиль)
        self.direction = FORWARD
        self.shown: RemapProfile | None = None    # profile.oriented(direction) — по нему строится вид
        self._state = {FORWARD: _ViewState(), REVERSE: _ViewState()}  # свёрнутость — своя у направления
        self.selection: set[int] = set()                   # выделенные ноты (строки пула и колонки «from»)
        self.suggested: dict[int, str] = {}                # подсказки: нота без правила -> артикуляция цели
        self.current: CableLayout | None = None  # последняя построенная раскладка
        # доли ширины сцены: колонка «from», промежуток для кабелей, колонка «to» (None — по умолчанию от ширины)
        self.columns: tuple[float, float, float] | None = _load_columns(settings)
        # тащат границу колонок: индекс, ширины (px) и x мыши в начале
        self._resize: tuple[int, tuple[float, float, float], float] | None = None
        self.cable_items: list[_CableItem] = []
        self.suggestion_items: list[_CableItem] = []             # пунктирные кабели подсказок
        self.pool_items: dict[int, _Row] = {}                    # нота -> строка пула (у алиасов — общая)
        self.source_items: dict[int, _Row] = {}                  # нота -> строка колонки «from»
        self.pool_rows: list[_Row] = []
        self.pool_headers: dict[str, _HeaderItem] = {}           # заголовки пула по ключу
        self.scene_rows: list[_Row] = []
        self.target_items: dict[str, _Row] = {}                  # строки цели по slot
        self.scene_headers: dict[str, _HeaderItem] = {}          # заголовки групп цели по ключу
        self.hovered: _CableItem | None = None
        self._issues: dict[int, list[str]] = {}  # нота -> тексты замечаний (подсказка строки)
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
        self._apply_pool_width()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._apply_pool_width()

    def _apply_pool_width(self) -> None:
        """Сохранённая ширина пула — один раз, когда вид впервые показан с настоящей шириной."""
        if self._pool_width is None or not self.isVisible():
            return
        width, self._pool_width = self._pool_width, None
        total = sum(self.splitter.sizes())
        self.splitter.setSizes([width, max(SCENE_MIN, total - width)])

    # --- направление ---

    @property
    def collapsed(self) -> set[str]:
        return self._state[self.direction].collapsed

    @collapsed.setter
    def collapsed(self, value: set[str]) -> None:
        self._state[self.direction].collapsed = set(value)

    @property
    def show_all(self) -> set[str]:
        return self._state[self.direction].show_all

    @show_all.setter
    def show_all(self, value: set[str]) -> None:
        self._state[self.direction].show_all = set(value)

    @property
    def expanded(self) -> set[str]:
        return self._state[self.direction].expanded

    @expanded.setter
    def expanded(self, value: set[str]) -> None:
        self._state[self.direction].expanded = set(value)

    @property
    def tone(self) -> tuple[str, str]:
        return TONES[self.direction]

    @property
    def sides(self) -> tuple[str, str]:
        """Карты сторон «from» и «to» направления: "source" / "target"."""
        return SIDES[self.direction]

    def set_direction(self, direction: str) -> None:
        """Сменить направление. Вид остаётся на той же группе инструментов: группа вверху
        видимой части сцены (по normalize_name подписи) — после перестройки снова вверху; нет такой — к началу."""
        if direction == self.direction:
            return
        group = self._top_group()
        self.cancel_drag()
        self.selection.clear()
        self.direction = direction
        self._build(anchor=False)
        self._scroll_to_group(group)

    def _top_group(self) -> str | None:
        """Ключ группы цели, которой принадлежит верх видимой части сцены (None — групп нет)."""
        if self.current is None or not self.current.scene.target_headers:
            return None
        top = (self.view.mapToScene(QPoint(0, 0)).y() - PAD) / ROW
        heads = sorted(self.current.scene.target_headers, key=lambda h: h.y)
        above = [h for h in heads if h.y <= top + 0.5]
        return (above[-1] if above else heads[0]).key

    def _scroll_to_group(self, key: str | None) -> None:
        h = self.current.header(key) if self.current is not None and key is not None else None
        self.view.verticalScrollBar().setValue(0 if h is None else h.y * ROW)  # над заголовком — поле PAD

    # --- управление ---

    def set_profile(self, p: RemapProfile | None, reset_collapsed: bool = True, direction: str | None = None) -> None:
        """Другой профиль (или тот же после сохранения/отката, смены карты). reset_collapsed — свёрнутость по умолчанию в обоих направлениях (открытие профиля);
        direction — сразу в этом направлении (None — в текущем)."""
        self.cancel_drag()
        self.profile = p
        if direction is not None:
            self.direction = direction
        self.selection.clear()
        if reset_collapsed:
            self._state = {FORWARD: _ViewState(), REVERSE: _ViewState()}
        self._build(anchor=reset_collapsed is False)

    def reveal(self, note: int) -> None:
        """Строка ноты в сцене и номер её цели должны быть видны: минимальная прокрутка (уже видны — без
        движения, к началу не прыгает)."""
        item = self.source_items.get(note)
        if item is None:
            return
        rect = QRectF(item.rect)
        cable = next((c for c in self.cable_items if c.src is item), None)
        if cable is not None:
            dst = cable.dst.rect
            rect = rect.united(QRectF(dst.left(), PAD + cable.cable.dst_y * ROW, dst.width(), ROW))
        self.view.ensureVisible(rect, 0, ROW // 2)

    def set_suggestions(self, suggested: dict[int, str]) -> None:
        """Подсказки для показа пунктиром (перестройка — refresh())."""
        self.suggested = dict(suggested)

    def refresh(self) -> None:
        """Правила (или подсказки) изменились: раскладка заново, прокрутка — за якорь."""
        self._build()

    def toggle_pool(self, key: str) -> None:
        """Свернуть/развернуть группу пула: перестраивается только пул."""
        self.collapsed ^= {key}
        self._build(scene=False)

    def toggle_target(self, key: str) -> None:
        """Группа цели: «только подключённые» ↔ «все»."""
        self.show_all ^= {key}
        self._build()

    def toggle_alias(self, key: str, in_pool: bool) -> None:
        """Раскрыть/свернуть алиасы: перестраивается только своя колонка."""
        self.expanded ^= {key}
        self._build(pool=in_pool, scene=not in_pool)

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

    def _anchor_of(self, view: _ColumnView, item: _Row | _HeaderItem) -> QPointF:
        """Правый край первой строки элемента (сторона кабеля); за краем видимой области — прижать к краю."""
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
            if isinstance(item, _CableItem) and item.cable.suggested:
                continue
            if isinstance(item, (_Row, _HeaderItem, _CableItem)):
                return item
        return None

    def view_press(self, view: _ColumnView, event) -> bool:
        """Нажатие в одной из view. True — обработано здесь (элементам сцены не передавать).
        Двойной клик по кабелю — сделать его основным; первое нажатие двойного клика по кабелю ничего не делает
        (не перетаскивание и не смена выделения)."""
        pos = event.position()
        if event.button() == Qt.MouseButton.LeftButton and self._drag is None:
            edge = self._boundary_at(view, pos.x())
            if edge is not None:
                self._resize = (edge, self._column_px(view.width_px(SCENE_MIN)), pos.x())
                return True
        item = self._item_at(view, pos.toPoint())
        if event.button() == Qt.MouseButton.RightButton:
            self.right_click(item)
            return True
        if event.button() != Qt.MouseButton.LeftButton or self._drag is not None:
            return self._drag is not None
        if isinstance(item, _CableItem):
            if event.type() == QEvent.Type.MouseButtonDblClick and not item.cable.primary:
                QTimer.singleShot(0, lambda ends=item.ends: self.primary_requested.emit(*ends))
            return True
        scene_pt = view.mapToScene(pos.toPoint())
        if isinstance(item, _Row) and item.role == TARGET:
            badge = item.badge_rect()
            if badge is not None and badge.contains(scene_pt):
                at = view.viewport().mapToGlobal(pos.toPoint())
                QTimer.singleShot(0, lambda t=item.model: self._write_to_menu(t, at))
            return True
        if isinstance(item, _HeaderItem) and view is self.pool:
            # клик — свернуть (при отпускании), перетаскивание — все ноты заголовка
            self._press = _Press(view, frozenset(item.header.notes), pos, False, item.header.key)
            return True
        if isinstance(item, _Row):
            chevron = item.chevron_rect()
            if chevron is not None and chevron.contains(scene_pt):
                QTimer.singleShot(0, lambda k=item.model.alias, pool=view is self.pool: self.toggle_alias(k, pool))
                return True
            if (event.type() == QEvent.Type.MouseButtonDblClick and item.role == POOL
                    and item.model.state != DELETE):
                # первое нажатие двойного клика лишь выделило строку (перетаскивания без сдвига нет)
                self._press = None
                QTimer.singleShot(0, lambda notes=list(item.notes): self.same_number_requested.emit(notes))
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
        if self._resize is not None:
            self._resize_to(pos.x())
            return True
        if self._drag is None and self._press is None and view is self.view:
            edge = self._boundary_at(view, pos.x())
            view.set_guide(None if edge is None else self._boundaries(view.width_px(SCENE_MIN))[edge])
            if edge is not None:
                view.viewport().setCursor(Qt.CursorShape.SplitHCursor)
            else:
                view.viewport().unsetCursor()
        if self._drag is not None:
            self.drag_to(QPointF(view.viewport().mapTo(self, pos.toPoint())))
            return True
        press = self._press
        if press is not None and event.buttons() & Qt.MouseButton.LeftButton:
            if (pos - press.pos).manhattanLength() >= QApplication.startDragDistance():
                at = QPointF(view.viewport().mapTo(self, pos.toPoint()))
                if press.header is not None:
                    self.begin_drag(set(press.notes), at, header=press.header)
                else:
                    notes = self.selection if press.notes <= self.selection else set(press.notes)
                    self.begin_drag(notes, at)
            return True
        return False

    def view_release(self, view: _ColumnView, event) -> bool:
        if event.button() != Qt.MouseButton.LeftButton:
            return self._drag is not None
        if self._resize is not None:
            self._resize = None
            self.view.set_guide(None)
            self._save_columns()
            return True
        if self._drag is not None:
            self.end_drag(drop=True)
            return True
        press, self._press = self._press, None
        if press is not None:
            if press.header is not None:
                # перестройка пула удаляет заголовок — после обработки события
                QTimer.singleShot(0, lambda key=press.header: self.toggle_pool(key))
                return True
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
        p = self.shown
        if isinstance(item, _CableItem):
            self.disconnect_requested.emit(list(item.cable.notes))
        elif isinstance(item, _Row) and item.role in (POOL, SOURCE):
            row = item.model
            if item.role == SOURCE and row.connected:
                mapped = [n for n in row.notes if p.rules.get(n) is not None and p.rules[n].action == "map"]
                self.disconnect_requested.emit(mapped)
            else:
                self.strike_requested.emit(list(row.notes))
        elif isinstance(item, _HeaderItem) and item.header.key.startswith(POOL_PREFIX) and item.header.notes:
            self.strike_requested.emit(list(item.header.notes))

    # --- перетаскивание ---

    def begin_drag(self, notes: set[int], at: QPointF, header: str | None = None) -> None:
        """Начать перетаскивание кабеля от строк с этими нотами (at — курсор в координатах CableEditor).
        header — тащат заголовок пула (кабель-превью — от него)."""
        if not notes:
            return
        self._press = None
        self.hover_cable(None)
        self._drag = _Drag(tuple(sorted(notes)), QPointF(at), QPointF(at), QPointF(0, 0), header=header)
        for v in (self.pool, self.view):
            v.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
        self._frame.start()
        self._tick()

    def _preview_width(self, d: _Drag) -> float:
        """Тянут только неназначенные ноты (без правила map) — тонкий кабель-превью, иначе обычный."""
        rules = self.shown.rules if self.shown is not None else {}
        mapped = any(rules.get(n) is not None and rules[n].action == "map" for n in d.notes)
        return CABLE_W if mapped else CABLE_THIN_W

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
        if isinstance(d.hover, _Row):
            d.hover.set_drop_zone(None)
        elif d.hover is not None:
            d.hover.set_highlighted(False)
        for v in (self.pool, self.view):
            v.viewport().unsetCursor()
        if drop and isinstance(d.hover, _Row):
            notes, slot, zone = list(d.notes), d.hover.model.slot, d.zone or ("row",)
            self.set_selection(set())
            if zone[0] == "line":  # ровно на эту ноту: без логики Write to и вопросов
                QTimer.singleShot(0, lambda: self.note_drop_requested.emit(notes, zone[2]))
            elif zone[0] == "badge":  # меню всех нот артикуляции — куда пойдёт кабель (Write to не меняется)
                t, at = d.hover.model, self._global(d.cursor)
                QTimer.singleShot(0, lambda: self._destination_menu(notes, t, at))
            else:
                # вопрос о Write to (модальный) — после того, как превью исчезло
                QTimer.singleShot(0, lambda: self.connect_requested.emit(notes, slot))
        elif drop and self._droppable(d.hover):
            notes, targets = list(d.notes), list(d.hover.header.notes)
            self.set_selection(set())
            QTimer.singleShot(0, lambda: self.group_drop_requested.emit(notes, targets))

    def cancel_drag(self) -> None:
        self._press = None
        self.end_drag(drop=False)

    @staticmethod
    def _droppable(item) -> bool:
        """Сюда можно отпустить кабель: строка цели или заголовок группы цели с нотами."""
        return isinstance(item, _Row) or (isinstance(item, _HeaderItem) and bool(item.header.notes))

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
            if isinstance(d.hover, _Row):
                d.hover.set_drop_zone(None)
            elif d.hover is not None:
                d.hover.set_highlighted(False)
            d.hover = target
            if isinstance(target, _HeaderItem):
                target.set_highlighted(True)
        # строка цели: зона под курсором — номер строки, бейдж или вся строка
        d.zone = target.zone_at(self._scene_point(d.cursor)) if isinstance(target, _Row) else None
        if isinstance(target, _Row):
            target.set_drop_zone(d.zone)
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
        self._build(pool=False)  # пул не трогаем: строки, которые тащат, не двигаются
        self._update_hover()

    def _tick(self) -> None:
        """Кадр перетаскивания: пружина, автопрокрутка, цель под курсором, превью."""
        d = self._drag
        if d is None:
            return
        d.step()
        self._autoscroll(d.cursor)
        self._update_hover()
        self.overlay.show_preview(self._drag_anchors(d), d.pos, self._droppable(d.hover), self._preview_width(d),
                                  self.tone)

    def _drag_anchors(self, d: _Drag) -> list[QPointF]:
        if d.header is not None:
            item = self.pool_headers.get(d.header)
            return [self._anchor_of(self.pool, item)] if item is not None else []
        wanted = set(d.notes)
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

    def _scene_point(self, at: QPointF) -> QPointF:
        """Точка CableEditor -> координаты сцены."""
        return self.view.mapToScene(self.view.viewport().mapFrom(self, at.toPoint()))

    def _global(self, at: QPointF) -> QPoint:
        return self.mapToGlobal(at.toPoint())

    def pick_destination(self, t: TargetRow, at: QPoint) -> int | None:
        """Меню ВСЕХ нот артикуляции (номер, высота; текущий Write to отмечен, как в меню Write to): куда пойдёт
        кабель. Write to не меняется. None — Esc или клик мимо."""
        return self._notes_menu("Connect to", t, at)

    def _destination_menu(self, notes: list[int], t: TargetRow, at: QPoint) -> None:
        n = self.pick_destination(t, at)
        if n is not None:
            self.note_drop_requested.emit(notes, n)

    def pick_write_to(self, t: TargetRow, at: QPoint) -> int | None:
        """Меню нот артикуляции (номер, высота), текущий Write to отмечен. None — ничего не выбрали."""
        return self._notes_menu("Write to", t, at)

    def notes_menu(self, title: str, t: TargetRow) -> QMenu:
        """Меню нот артикуляции t (номер, высота) под заголовком title; текущий Write to отмечен галочкой.
        Общее для «Write to» (клик по бейджу) и «Connect to» (drop на бейдж)."""
        menu = QMenu(self)
        menu.addSection(title)
        for n in t.notes:
            action = menu.addAction(f"{n}   {pitch_name(n)}")
            action.setCheckable(True)
            action.setChecked(n == t.write_to)
            action.setData(n)
        return menu

    def _notes_menu(self, title: str, t: TargetRow, at: QPoint) -> int | None:
        chosen = self.notes_menu(title, t).exec(at)
        return chosen.data() if chosen is not None and chosen.data() is not None else None

    def _write_to_menu(self, t: TargetRow, at: QPoint) -> None:
        n = self.pick_write_to(t, at)
        if n is not None and n != t.write_to:
            self.write_to_requested.emit(n)

    # --- построение ---

    def _build(self, *, pool: bool = True, scene: bool = True, anchor: bool = True) -> None:
        """Раскладка заново; pool / scene — какие колонки перерисовать; anchor — удержать прокрутку за якорь."""
        p = self.profile
        self.shown = p.oriented(self.direction) if p is not None else None
        lay = build_layout(self.shown, self.collapsed, show_all=self.show_all, expanded=self.expanded,
                           suggested=self.suggested)
        if self.current is not None:  # нетронутая колонка остаётся как есть
            if not pool:
                lay.pool = self.current.pool
            if not scene:
                lay.scene = self.current.scene
        anchors = {v: self._anchors(v) if anchor else [] for v in (self.pool, self.view)}
        self.current = lay
        self._issues = {}
        if p is not None:
            for i in validate_profile(p, self.direction):
                if i.code != NO_RULE:
                    self._issues.setdefault(i.note, []).append(i.message[:1].upper() + i.message[1:])
        if self._drag is not None and self._drag.hover is not None:
            self._drag.hover = None  # элементы сейчас пересоздадутся
        if pool:
            self._draw_pool()
            self._restore_anchor(self.pool, anchors[self.pool])
        if scene:
            self._draw_scene()
            self._restore_anchor(self.view, anchors[self.view])
        visible = {n for item in self.pool_rows + self.scene_rows for n in item.notes}
        self.set_selection(self.selection & visible)

    # --- якорь прокрутки ---

    def _anchor_items(self, view: _ColumnView) -> list[tuple[tuple, QRectF]]:
        """Элементы, за которые держится прокрутка view (ключ, прямоугольник): в пуле — строки и заголовки групп,
        в сцене — строки и заголовки цели (подключённые строки при правках переезжают, цели — нет)."""
        if view is self.pool:
            rows = [(("a", i.model.alias) if i.model.expanded else ("n", i.notes[0]), i.rect) for i in self.pool_rows]
            return rows + [(("h", k), i.rect) for k, i in self.pool_headers.items()]
        return ([(("t", k), i.rect) for k, i in self.target_items.items()]
                + [(("h", k), i.rect) for k, i in self.scene_headers.items()])

    def _anchors(self, view: _ColumnView) -> list[tuple[tuple, float]]:
        """Якоря: элемент под курсором (или верхний видимый) и следующие за ним — ключ и смещение от верха
        видимой части. После перестройки берётся первый уцелевший (строка могла уйти из пула)."""
        items = sorted(self._anchor_items(view), key=lambda kr: kr[1].top())
        if not items:
            return []
        top = view.verticalScrollBar().value()
        vp = view.viewport()
        cursor = vp.mapFromGlobal(QCursor.pos())
        y = view.mapToScene(cursor).y() if vp.rect().contains(cursor) else top
        start = next((i for i, (_, r) in enumerate(items) if r.bottom() > y), len(items))
        return [(k, r.top() - top) for k, r in items[start:]]

    def _restore_anchor(self, view: _ColumnView, anchors: list[tuple[tuple, float]]) -> None:
        if not anchors:
            return
        now = dict(self._anchor_items(view))
        for key, offset in anchors:
            if key in now:
                view.verticalScrollBar().setValue(round(now[key].top() - offset))
                return

    def _draw_pool(self) -> None:
        lay = self.current
        self.pool_items, self.pool_rows, self.pool_headers = {}, [], {}
        side = self.sides[0]
        self.pool_title.setToolTip(POOL_TIP.format(side=side.capitalize()))
        if lay is None:
            self.pool.scene().clear()
            return
        view = self.pool
        width = view.begin(lay.pool.height, POOL_MIN)
        col = width - 2 * PAD
        scene = view.scene()
        for h in lay.pool.headers:
            tip = ("Click to expand" if h.collapsed else "Click to collapse") + f"\n{GROUP_HINT}"
            item = _HeaderItem(QRectF(PAD, PAD + h.y * ROW, col, ROW), h, self.toggle_pool, tip, self.tone)
            self._full_label(item, view)
            self.pool_headers[h.key] = item
            scene.addItem(item)
        for r in lay.pool.rows:
            indent = INDENT if r.child else 0
            item = self._source_item(QRectF(PAD + indent, PAD + r.y * ROW, col - indent, ROW), r, POOL)
            self._full_name(item, view)
            self._register(item, self.pool_items, self.pool_rows)
            scene.addItem(item)
        view.end()

    @staticmethod
    def _register(item: _Row, by_note: dict[int, _Row], rows: list[_Row]) -> None:
        rows.append(item)
        if item.model.expanded:  # заголовок алиасов: ноты закреплены за их собственными строками ниже
            for n in item.notes:
                by_note.setdefault(n, item)
        else:
            for n in item.notes:
                by_note[n] = item

    # --- ширины колонок сцены ---

    def _column_px(self, width: float) -> tuple[float, float, float]:
        """Ширины колонки «from», промежутка и колонки «to» в px при ширине сцены width."""
        avail = width - 2 * PAD
        if self.columns is None:  # по умолчанию: промежуток ~12 %, колонки поровну
            gap = min(150.0, max(70.0, width * 0.12))
            return (avail - gap) / 2, gap, (avail - gap) / 2
        c2, gap, c3 = (f * avail for f in self.columns)
        gap = max(MIN_GAP, gap)
        c2 = max(MIN_COL, min(c2, avail - gap - MIN_COL))
        c3 = max(MIN_COL, min(c3, avail - c2 - gap))
        return c2, gap, c3

    def _boundaries(self, width: float) -> tuple[float, float, float]:
        """x границ: правый край колонки «from», левый и правый края колонки «to»."""
        c2, gap, c3 = self._column_px(width)
        return PAD + c2, PAD + c2 + gap, PAD + c2 + gap + c3

    def _boundary_at(self, view: _ColumnView, x: float) -> int | None:
        """Индекс границы колонок сцены под x (координаты viewport = сцены: горизонтальной прокрутки нет).
        Зона — со стороны промежутка, чтобы не мешать точкам кабелей."""
        if view is not self.view or self.current is None:
            return None
        b2, b3, b_end = self._boundaries(view.width_px(SCENE_MIN))
        zones = ((b2 + PORT + 1, b2 + PORT + 1 + GRIP), (b3 - PORT - 1 - GRIP, b3 - PORT - 1),
                 (b_end + 1, b_end + 1 + GRIP))
        return next((i for i, (a, b) in enumerate(zones) if a <= x <= b), None)

    def _resize_to(self, x: float) -> None:
        """Тянут границу колонок: меняются две соседние части (колонка / промежуток / свободное место справа)."""
        edge, (c2, gap, c3), start = self._resize
        dx = x - start  # граница сдвигается на смещение мыши (не прыгает к курсору)
        width = self.view.width_px(SCENE_MIN)
        avail = width - 2 * PAD
        if edge == 0:
            new = max(MIN_COL, min(c2 + dx, c2 + gap - MIN_GAP))
            c2, gap = new, c2 + gap - new
        elif edge == 1:
            new = max(MIN_GAP, min(gap + dx, gap + c3 - MIN_COL))
            gap, c3 = new, gap + c3 - new
        else:
            c3 = max(MIN_COL, min(c3 + dx, avail - c2 - gap))
        self.columns = (c2 / avail, gap / avail, c3 / avail)
        self._draw_scene()
        self.view.set_guide(self._boundaries(width)[edge])

    def _save_columns(self) -> None:
        if self.settings is not None and self.columns is not None:
            self.settings.setValue(COLUMNS_KEY, ",".join(f"{f:.4f}" for f in self.columns))

    def _save_pool_width(self, *_) -> None:
        if self.settings is not None:
            self.settings.setValue(POOL_KEY, self.splitter.sizes()[0])

    def _scene_columns(self, width: float) -> tuple[float, float, float, float]:
        """x колонки «from», x колонки «to», ширины колонок «from» и «to»."""
        c2, gap, c3 = self._column_px(width)
        return PAD, PAD + c2 + gap, c2, c3

    def _place_heads(self) -> None:
        """Слоты над сценой — ровно над колонками «from» и «to» и по центру промежутка между ними (за границами
        колонок при перетаскивании). Слот промежутка не уже своего содержимого."""
        lx, rx, col2, col3 = self._scene_columns(self.view.width_px(SCENE_MIN))
        off = self.scene_head.mapFromGlobal(self.view.viewport().mapToGlobal(QPoint(0, 0))).x()
        height = self.scene_head.height()
        self.from_slot.setGeometry(round(off + lx), 0, round(col2), height)
        self.to_slot.setGeometry(round(off + rx), 0, round(col3), height)
        gap = max(rx - lx - col2, self.gap_slot.sizeHint().width())
        self.gap_slot.setGeometry(round(off + (lx + col2 + rx) / 2 - gap / 2), 0, round(gap), height)

    # --- полные имена в подсказках ---

    @staticmethod
    def _full_name(item: _Row, view: _ColumnView) -> None:
        """Имя не помещается в строку — полное имя первой строкой подсказки."""
        font = _font(view.font(), strike=item.strike, italic=item.italic)
        if item.name and QFontMetrics(font).horizontalAdvance(item.name) > item.name_room():
            item.setToolTip(f"{item.name}\n{item.toolTip()}".strip())

    @staticmethod
    def _full_label(item: _HeaderItem, view: _ColumnView) -> None:
        if QFontMetrics(item.label_font(view.font())).horizontalAdvance(item.header.label) > item.label_room():
            item.setToolTip(f"{item.header.label}\n{item.toolTip()}")

    def _draw_scene(self) -> None:
        """Колонка «from» (подключённые строки, точка справа) и колонка «to» (строки цели, точка слева)."""
        lay = self.current
        self.cable_items, self.source_items, self.scene_rows, self.target_items = [], {}, [], {}
        self.suggestion_items, self.scene_headers = [], {}
        self.hovered = None
        self._place_heads()
        if lay is None:
            self.view.scene().clear()
            self.view.set_hint(None)
            return
        sc = lay.scene
        width = self.view.begin(sc.height, SCENE_MIN)
        lx, rx, col2, col3 = self._scene_columns(width)
        scene = self.view.scene()
        # колонка «from» пуста (новый профиль) — что делать; пул пуст — подсказывать нечего
        empty = not sc.source_rows and bool(lay.pool.rows or lay.pool.headers)
        self.view.set_hint((lx, col2, EMPTY_HINT.format(side=self.sides[1])) if empty else None)

        def rect(x: float, y: int, h: int = 1) -> QRectF:
            return QRectF(x, PAD + y * ROW, col2 if x == lx else col3, h * ROW)

        for h in sc.target_headers:
            if not lay.placement.slots:  # кабелей нет — все группы раскрыты (клик ничего не скрывает)
                tip = "All articulations shown until something is connected"
            elif h.key in self.show_all:
                tip = "All articulations shown. Click to show connected only"
            else:
                tip = "Connected only. Click to show all articulations"
            if h.shown:
                tip = f"{h.shown} of {h.count} connected\n{tip}"
            if h.notes:
                tip += f"\n{TARGET_GROUP_HINT}"
            item = _HeaderItem(rect(rx, h.y), h, self.toggle_target, tip, self.tone)
            self._full_label(item, self.view)
            self.scene_headers[h.key] = item
            scene.addItem(item)
        solid = {c.target.slot for c in sc.cables if not c.suggested}
        dashed = {c.target.slot for c in sc.cables if c.suggested} - solid
        for t in sc.target_rows:
            item = self._target_item(rect(rx, t.y, t.height), t, t.slot in solid | dashed, t.slot in dashed)
            self._full_name(item, self.view)
            self.target_items[t.slot] = item
            scene.addItem(item)
            if t.height > 1:
                scene.addItem(_Bundle(rect(lx, t.y, t.height).adjusted(-3, 0, 3, 0)))
        for r in sc.source_rows:
            indent = INDENT if r.child else 0
            item = self._source_item(rect(lx, r.y).adjusted(indent, 0, 0, 0), r, SOURCE)
            self._full_name(item, self.view)
            self._register(item, self.source_items, self.scene_rows)
            scene.addItem(item)
        rows_by_y = {item.model.y: item for item in self.scene_rows}
        for c in sc.cables:
            src = rows_by_y[c.src_y]
            a = QPointF(src.rect.right(), PAD + c.src_y * ROW + ROW / 2)
            b = QPointF(rx, PAD + (c.dst_y + 0.5) * ROW)  # на свой номер в строке цели
            tip = self._cable_tip(c.notes, c.dst) if c.dst is not None else ""
            if tip and not c.primary:
                tip += f"\n{PRIMARY_HINT}"
            item = _CableItem(cable_path(a, b), c, self, src, self.target_items[c.target.slot], tip, self.tone)
            scene.addItem(item)
            (self.suggestion_items if c.suggested else self.cable_items).append(item)
        self.view.end()

    def _source_item(self, r: QRectF, row: SourceRow, role: str) -> _Row:
        p = self.shown
        tgt = p.target_map
        if row.connected and not row.expanded:
            tip = f"{self._cable_tip(row.notes, p.rules[row.note].dst)}\n{CONNECTED_HINT}"
        elif row.suggested and not row.expanded:
            cable = next(c for c in self.current.scene.cables if c.src_y == row.y)
            name = cable.target.label
            tip = (f"Suggested: {name} · {cable.dst}\n{SUGGESTED_HINT}" if cable.dst is not None
                   else f"Suggested: {name}\n{SUGGESTED_WRITE_TO_HINT}")
        else:
            tip = (REVERSE_UNASSIGNED_TIP if self.direction == REVERSE and row.state == UNASSIGNED
                   else STATE_TIPS.get(row.state, ""))
            if row.state == KEEP and tgt is not None:
                tip += (f": {tgt.names[row.note]}" if row.note in tgt.names
                        else f" (no such note in the {self.sides[1]} map)")
            tip += f"\n{ROW_HINT}"
            if row.block == UNASSIGNED and row.state != DELETE:
                tip += f"\n{SAME_NUMBER_HINT}"
        if len(row.notes) > 1:
            tip = f"Notes {', '.join(map(str, row.notes))}\n{tip}\n{MIXED_HINT if row.mixed else ALIAS_HINT}"
        issues = [i for n in row.notes for i in self._issues.get(n, [])]
        if issues:
            tip = "\n".join(issues + [tip])
        chevron = None
        if row.alias is not None:
            chevron = "fixed" if row.mixed else "expanded" if row.expanded else "collapsed"
        n = row.shown
        cabled = (row.connected or row.suggested) and not row.expanded
        return _Row(r, role, row, str(n), pitch_name(n), row.name or "—",
                    name_color="text_faint" if row.state == DELETE or row.name is None else "text",
                    strike=row.state == DELETE, marker="=" if row.state == KEEP else "",
                    pill=f"+{len(row.notes) - 1}" if len(row.notes) > 1 and not row.expanded else "",
                    chevron=chevron, port="right" if cabled else None,
                    dashed=row.suggested, warn=bool(issues), tooltip=tip, tone=self.tone)

    def _target_item(self, r: QRectF, t: TargetRow, connected: bool, dashed: bool = False) -> _Row:
        tgt = self.shown.target_map
        port = "left" if connected else None
        if not t.in_map:
            side = f"{self.sides[1]} map"
            tip = f"Note {t.notes[0]} is not in the {side}" if tgt is not None else f"No {side}"
            return _Row(r, TARGET, t, str(t.notes[0]), pitch_name(t.notes[0]), "—", name_color="text_faint",
                        italic=True, port=port, dashed=dashed, tooltip=tip, tone=self.tone)
        many = len(t.notes) > 1
        lines = [(off, str(n), pitch_name(n)) for off, n in t.numbers]
        tip = ""
        if many:
            wt = WRITE_TO_HINT.format(n=t.write_to) if t.write_to is not None else "Write to: not chosen"
            tip = f"On notes {', '.join(map(str, t.notes))}\n{wt}\n{BADGE_HINT}"
        tip = f"{tip}\n{NUMBER_DROP_HINT}".lstrip("\n")
        _, number, pitch = lines[0]
        return _Row(r, TARGET, t, number, pitch, t.label, pill=(f"+{t.hidden}" if t.hidden else "…") if many else "",
                    badge=many, port=port, dashed=dashed, tooltip=tip, lines=lines, tone=self.tone)

    def _cable_tip(self, notes: tuple[int, ...], dst: int) -> str:
        """«ноты имя → нота имя» по ориентированному профилю (как на картинке — слева направо)."""
        p = self.shown
        src_name = p.source_map.names.get(notes[0], "") if p.source_map is not None else ""
        tgt = p.target_map
        dst_name = tgt.names.get(dst, "") if tgt is not None else ""
        left = f"{', '.join(map(str, notes))} {src_name}".strip()
        right = f"{dst} {dst_name}".strip()
        text = f"{left}  →  {right}"
        if tgt is not None and dst in tgt.names:
            wt = primary_note(tgt, dst_name)
            if wt is not None and wt != dst:
                text += f"\nNot the Write to note ({wt})"
        return text
