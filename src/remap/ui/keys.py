"""Клавиши корпуса: вкладки, «?», квадратные клавиши со значком, «⇄», кнопки обучения и большая CONVERT.

Виджет `Key` рисует себя сам: лицо (внешняя тень, рамка, градиент, inset-линии, текстура) готовится один раз на состояние
и кэшируется pixmap'ом (`metal._Backdrop`), подпись и значок рисуются поверх вживую. Тень не выходит за виджет:
вокруг лица — поля (`key_margins()`), поэтому в раскладках расстояние между лицами — `key_row_spacing()`, а не просто
`spacing`.
"""

from dataclasses import dataclass
from math import ceil

from PySide6.QtCore import QEvent, QMargins, QPoint, QPointF, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QFontMetricsF, QLinearGradient, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QAbstractButton, QSizePolicy, QWidget

from . import theme
from .icons import ICONS, draw_icon
from .metal import _Backdrop, inner_shadow, outer_shadow, paint_metal
from .theme import qcolor

STATES = ("normal", "hover", "pressed")


@dataclass(frozen=True)
class KeySpec:
    """Вид клавиши: размер лица с рамкой (`w=None` — по тексту и полям `pad`), радиус, шрифт подписи (`font_px=None` —
    только значок), зазор значок–подпись и поле по бокам. `go` — большая клавиша с другими градиентом и тенями."""

    w: int | None
    h: int
    radius: float = theme.KEY_RADIUS
    font_px: float | None = None
    spacing: float = theme.LABEL_SPACING
    gap: int = 0
    pad: int = 0
    go: bool = False

    @property
    def shadow(self) -> dict:
        return theme.KEY_GO_SHADOW if self.go else theme.KEY_SHADOW


TAB = KeySpec(*theme.KEY_TAB_SIZE, font_px=theme.KEY_TAB_FONT, spacing=theme.KEY_TAB_SPACING, gap=theme.KEY_TAB_GAP,
              pad=theme.KEY_TAB_PAD)
HELP = KeySpec(*theme.KEY_HELP_SIZE, font_px=theme.KEY_HELP_FONT, spacing=0)
SQUARE = KeySpec(*theme.KEY_SQUARE_SIZE)  # точки, сохранение, «⇄» на Convert
SWAP = KeySpec(*theme.KEY_SWAP_SIZE)
MAP = KeySpec(*theme.KEY_MAP_SIZE)
CLOSE = KeySpec(*theme.KEY_CLOSE_SIZE)
TUT = KeySpec(None, theme.KEY_TUT_HEIGHT, font_px=theme.KEY_TUT_FONT, spacing=theme.KEY_TUT_SPACING,
              pad=theme.KEY_TUT_PAD)
GO = KeySpec(*theme.KEY_GO_SIZE, radius=theme.KEY_GO_RADIUS, font_px=theme.KEY_GO_FONT, spacing=theme.KEY_GO_SPACING,
             gap=theme.KEY_GO_GAP, go=True)
PRESETS = {"tab": TAB, "help": HELP, "square": SQUARE, "swap": SWAP, "map": MAP, "close": CLOSE, "tut": TUT, "go": GO}


def key_margins(spec: KeySpec) -> QMargins:
    """Поля вокруг лица, в которые попадает внешняя тень: вбок BLUR, сверху BLUR − DY, снизу BLUR + DY."""
    blur, dy = spec.shadow["blur"], spec.shadow["dy"]
    return QMargins(blur, blur - dy, blur, blur + dy)


def key_row_spacing(gap: int, left: KeySpec = TAB, right: KeySpec | None = None) -> int:
    """`spacing` горизонтального layout, при котором между ЛИЦАМИ соседних клавиш `left` и `right` будет `gap` px
    (поля виджетов складываются). Может быть отрицательным, если нужный зазор меньше суммы полей."""
    right = right or left
    return gap - key_margins(left).right() - key_margins(right).left()


def key_column_spacing(gap: int, top: KeySpec = TAB, bottom: KeySpec | None = None) -> int:
    """То же для вертикального layout: между лицами `top` (сверху) и `bottom` (снизу) будет `gap` px."""
    bottom = bottom or top
    return gap - key_margins(top).bottom() - key_margins(bottom).top()


def _gradient(top: str, bottom: str, rect: QRectF) -> QBrush:
    g = QLinearGradient(0, rect.top(), 0, rect.bottom())
    g.setColorAt(0, qcolor(top))
    g.setColorAt(1, qcolor(bottom))
    return QBrush(g)


def paint_key(p: QPainter, face: QRectF, spec: KeySpec, state: str, dpr: float, origin: QPoint,
              badge: bool = False) -> None:
    """Лицо клавиши в прямоугольнике `face` (с рамкой): внешняя тень, рамка 1 px, градиент, inset-линии (или тень
    внутрь у нажатой), текстура металла от `origin`, точка-значок. Без подписи и значка — их рисует виджет.
    Состояния: normal, hover (светлее; в макете не задано), pressed (нажата и включена — один вид)."""
    if state not in STATES:
        raise ValueError(state)

    def snap(v: float) -> float:  # границы лица и рамка — по сетке пикселей устройства (DPR 1.25, 1.5)
        return round(v * dpr) / dpr

    face = QRectF(QPointF(snap(face.left()), snap(face.top())), QPointF(snap(face.right()), snap(face.bottom())))
    r, border = spec.radius, max(1, round(dpr)) / dpr
    pressed = state == "pressed"
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    if pressed:  # наружу — только светлая линия под клавишей
        outer_shadow(p, face, r, dpr, 1, 0, theme.KEY_PRESSED_EDGE[3], rgb=(255, 255, 255))
    else:
        outer_shadow(p, face, r, dpr, **spec.shadow)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(qcolor(theme.KEY_BORDER))
    p.drawRoundedRect(face, r, r)
    inner = face.adjusted(border, border, -border, -border)
    r_in = r - border
    top, bottom = {
        "normal": (theme.KEY_GO_TOP, theme.KEY_GO_BOTTOM) if spec.go else (theme.KEY_TOP, theme.KEY_BOTTOM),
        "hover": (theme.KEY_HOVER_TOP, theme.KEY_HOVER_BOTTOM),
        "pressed": (theme.KEY_PRESSED_TOP, theme.KEY_PRESSED_BOTTOM),
    }[state]
    p.setBrush(_gradient(top, bottom, inner))
    p.drawRoundedRect(inner, r_in, r_in)
    if pressed:
        inner_shadow(p, inner, r_in, dpr, **theme.KEY_PRESSED_SHADOW)
    else:
        light = theme.KEY_GO_INSET_LIGHT if spec.go else theme.KEY_INSET_LIGHT
        dark, dark_dy = (theme.KEY_GO_INSET_DARK, -2) if spec.go else (theme.KEY_INSET_DARK, -1)
        inner_shadow(p, inner, r_in, dpr, 1, 0, light[3], rgb=light[:3])
        inner_shadow(p, inner, r_in, dpr, dark_dy, 0, dark[3], rgb=dark[:3])
    paint_metal(p, inner, r_in, origin)  # текстура над фоном и inset-тенями, под подписью — как `.tx` в макете
    if badge:
        size = theme.KEY_BADGE_SIZE
        dot = QRectF(inner.right() - theme.KEY_BADGE_INSET - size, inner.top() + theme.KEY_BADGE_INSET, size, size)
        glow = theme.KEY_BADGE_GLOW
        outer_shadow(p, dot, size / 2, dpr, 0, theme.KEY_BADGE_GLOW_BLUR, glow[3], rgb=glow[:3])
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(qcolor(theme.KEY_BADGE))
        p.drawEllipse(dot)
    p.restore()


class Key(QAbstractButton):
    """Клавиша корпуса. Состояния: обычная, наведение, нажатая/включённая (`checkable`), недоступная, фокус с клавиатуры.
    `lit` — подпись акцентом без включения (NEXT, CONVERT); `badge` — белая точка у угла (карта не сохранена)."""

    def __init__(self, text: str = "", icon: str | None = None, *, spec: KeySpec = TAB, checkable: bool = False,
                 icon_stroke: float | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        if icon is not None and icon not in ICONS:
            raise ValueError(f"unknown icon {icon!r}")
        self.spec = spec
        self._icon = icon
        self._icon_stroke = icon_stroke
        self._lit = False
        self._badge = False
        self._focus_visible = False
        self._faces = {(state, badge): _Backdrop() for state in STATES for badge in (False, True)}
        self.setText(text)
        self.setCheckable(checkable)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)

    # --- свойства ---
    @property
    def lit(self) -> bool:
        return self._lit

    @lit.setter
    def lit(self, value: bool) -> None:
        self._lit = value
        self.update()

    @property
    def badge(self) -> bool:
        return self._badge

    @badge.setter
    def badge(self, value: bool) -> None:
        self._badge = value
        self.update()

    def set_icon(self, name: str | None) -> None:
        if name is not None and name not in ICONS:
            raise ValueError(f"unknown icon {name!r}")
        self._icon = name
        self.updateGeometry()
        self.update()

    @property
    def icon_name(self) -> str | None:
        return self._icon

    @property
    def rebuilds(self) -> int:
        """Сколько раз пересобирались лица (для тестов кэша)."""
        return sum(b.rebuilds for b in self._faces.values())

    # --- размеры ---
    def _label_font(self) -> QFont | None:
        s = self.spec
        return theme.label_font(s.font_px, spacing=s.spacing) if s.font_px else None

    def _text_width(self) -> float:
        font = self._label_font()
        return QFontMetricsF(font).horizontalAdvance(self.text()) if font and self.text() else 0.0

    def _content_width(self) -> float:
        icon = ICONS[self._icon].w if self._icon else 0
        text = self._text_width()
        return icon + (self.spec.gap if icon and text else 0) + text

    def face_size(self) -> QSize:
        s = self.spec
        width = s.w if s.w is not None else ceil(self._text_width() + 2 * s.pad + 2)
        return QSize(width, s.h)

    def margins(self) -> QMargins:
        return key_margins(self.spec)

    def face_rect(self) -> QRectF:
        m, size = self.margins(), self.face_size()
        return QRectF(m.left(), m.top(), size.width(), size.height())

    def sizeHint(self) -> QSize:
        m, size = self.margins(), self.face_size()
        return QSize(size.width() + m.left() + m.right(), size.height() + m.top() + m.bottom())

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def hitButton(self, pos: QPoint) -> bool:
        return self.face_rect().contains(QPointF(pos))  # поля с тенью не нажимаются

    # --- вид ---
    def _state(self) -> str:
        if self.isDown() or self.isChecked():
            return "pressed"
        return "hover" if self.isEnabled() and self.underMouse() else "normal"

    def _content_color(self) -> str:
        if not self.isEnabled():
            return theme.KEY_LABEL_DISABLED
        if self.isChecked() or self._lit:
            return theme.ACCENT
        return theme.KEY_LABEL_HOVER if self._state() == "hover" else theme.KEY_LABEL

    def _face_pixmap(self) -> QPixmap:
        state, badge = self._state(), self._badge
        face = self.face_rect()

        def compose(p: QPainter, _rect: QRect, origin: QPoint) -> None:
            paint_key(p, face, self.spec, state, p.device().devicePixelRatioF(), origin, badge)

        return self._faces[(state, badge)].get(self, compose)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.drawPixmap(0, 0, self._face_pixmap())
        self._paint_content(p)
        if self._focus_visible and self.hasFocus():
            self._paint_focus(p)

    def _paint_content(self, p: QPainter) -> None:
        face = self.face_rect()
        dpr = self.devicePixelRatioF()
        color = self._content_color()
        total = self._content_width()
        x = face.center().x() - total / 2
        if self._icon:
            icon = ICONS[self._icon]
            ix = round(x * dpr) / dpr  # значок — как replaced-элемент браузера, по сетке устройства
            iy = round((face.center().y() - icon.h / 2) * dpr) / dpr
            fixed = icon.fixed is not None and self.isEnabled()
            draw_icon(p, self._icon, QRectF(ix, iy, icon.w, icon.h), None if fixed else color, self._icon_stroke)
            x += icon.w + (self.spec.gap if self.text() else 0)
        font = self._label_font()
        if font and self.text():
            p.setFont(font)
            p.setPen(QColor(color))
            fm = QFontMetricsF(font)
            baseline = face.center().y() + (fm.ascent() - fm.descent()) / 2
            p.drawText(QPointF(x, baseline), self.text())

    def _paint_focus(self, p: QPainter) -> None:
        """Контур как у кнопки логотипа в макете (1 px, `KEY_FOCUS_RING`), но вплотную к лицу: поля вокруг клавиши
        малы (сверху 2 px), а виджет за них не рисует."""
        gap = theme.KEY_FOCUS_GAP
        ring = self.face_rect().adjusted(-gap - 0.5, -gap - 0.5, gap + 0.5, gap + 0.5)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(qcolor(theme.KEY_FOCUS_RING), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        radius = self.spec.radius + gap + 0.5
        p.drawRoundedRect(ring, radius, radius)

    # --- фокус только с клавиатуры (outline: focus-visible) ---
    def focusInEvent(self, event) -> None:
        self._focus_visible = event.reason() in (Qt.FocusReason.TabFocusReason, Qt.FocusReason.BacktabFocusReason,
                                                 Qt.FocusReason.ShortcutFocusReason)
        super().focusInEvent(event)
        self.update()

    def focusOutEvent(self, event) -> None:
        self._focus_visible = False
        super().focusOutEvent(event)
        self.update()

    def event(self, e) -> bool:
        if e.type() in (QEvent.Type.HoverEnter, QEvent.Type.HoverLeave, QEvent.Type.EnabledChange):
            self.update()
        return super().event(e)
