"""Поля ввода и флажок на экране: зелёное поле-«рамка» (вставлено в металл, чёрный обод), плоское поле поиска на стекле.

`paint_bezel()` — чистое рисование лица поля; `BezelField` — виджет-контейнер (`body` — layout внутри лица), он же
статическое поле с подписью и значением (Convert: SOURCE / TARGET, Maps: MY MAP); `ComboBox` (combo.py) рисует лицо той же
функцией. Текст поля — `paint_field_text()` (общий для статического поля и комбо). Ширина шрифта (`wdth`) берётся по
тегу макета: у `<button>` и `<input>` — `WDTH_BUTTON`, у div/span — `WDTH_TEXT`.
"""

from dataclasses import dataclass

from PySide6.QtCore import QEvent, QMargins, QObject, QPoint, QPointF, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPalette, QPen
from PySide6.QtWidgets import QAbstractButton, QFrame, QHBoxLayout, QLineEdit, QSizePolicy, QVBoxLayout, QWidget

from . import text, theme
from .icons import ICONS, draw_icon
from .metal import _Backdrop, inner_shadow
from .theme import qcolor

KINDS = ("bezel", "screen")
STATES = ("normal", "hover", "focus")


def field_margins(kind: str = "bezel") -> QMargins:
    """Поля виджета вокруг лица: у «рамки» — под обод 3 px (снизу ещё 1 px светлой линии), у плоского поля нет."""
    rim = theme.FIELD_RIM_W
    return QMargins(rim, rim, rim, rim + 1) if kind == "bezel" else QMargins()


def field_height(kind: str = "bezel") -> int:
    """Полная высота виджета поля: лицо + поля под обод."""
    m = field_margins(kind)
    return (theme.FIELD_HEIGHT if kind == "bezel" else theme.FIELD_SCREEN_HEIGHT) + m.top() + m.bottom()


def paint_bezel(p: QPainter, face: QRectF, dpr: float, kind: str = "bezel", state: str = "normal") -> None:
    """Лицо поля в `face` (с рамкой 1 px). `bezel`: светлая линия и сплошной обод 3 px вокруг, градиент, тень внутри
    `inset 0 1px 3px`. `screen`: плоское, полупрозрачная заливка без обода. Состояния (в макете не заданы): hover — светлее
    рамка, focus — рамка акцентом и внутренний контур 1 px."""
    if kind not in KINDS or state not in STATES:
        raise ValueError((kind, state))

    def snap(v: float) -> float:  # границы лица и рамка — по сетке пикселей устройства (DPR 1.25, 1.5)
        return round(v * dpr) / dpr

    face = QRectF(QPointF(snap(face.left()), snap(face.top())), QPointF(snap(face.right()), snap(face.bottom())))
    r, border = theme.FIELD_RADIUS, max(1, round(dpr)) / dpr
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    if kind == "bezel":
        rim = theme.FIELD_RIM_W
        outer = face.adjusted(-rim, -rim, rim, rim)
        p.setBrush(qcolor(theme.FIELD_RIM_LIGHT))  # 0 1px 0 3px: та же форма, сдвинутая на 1 px вниз, ниже обода
        p.drawRoundedRect(outer.translated(0, 1), r + rim, r + rim)
        p.setBrush(qcolor(theme.FIELD_RIM))  # 0 0 0 3px
        p.drawRoundedRect(outer, r + rim, r + rim)
    color = {"normal": theme.FIELD_BORDER, "hover": theme.FIELD_HOVER_BORDER, "focus": theme.FIELD_FOCUS_BORDER}[state]
    inner = face.adjusted(border, border, -border, -border)
    r_in = r - border
    ring = QPainterPath()
    ring.setFillRule(Qt.FillRule.OddEvenFill)
    ring.addRoundedRect(face, r, r)
    ring.addRoundedRect(inner, r_in, r_in)
    p.setBrush(qcolor(color))
    p.drawPath(ring)  # рамка — кольцом, чтобы полупрозрачная заливка плоского поля не ложилась на неё второй раз
    if kind == "bezel":
        g = QLinearGradient(0, inner.top(), 0, inner.bottom())
        g.setColorAt(0, qcolor(theme.FIELD_TOP))
        g.setColorAt(1, qcolor(theme.FIELD_BOTTOM))
        p.setBrush(QBrush(g))
        shadow = theme.FIELD_INSET
    else:
        p.setBrush(qcolor(theme.FIELD_SCREEN_BG))
        shadow = theme.FIELD_SCREEN_INSET
    p.drawRoundedRect(inner, r_in, r_in)
    inner_shadow(p, inner, r_in, dpr, **shadow)
    if state == "focus":
        glow = QPainterPath()
        glow.setFillRule(Qt.FillRule.OddEvenFill)
        glow.addRoundedRect(inner, r_in, r_in)
        glow.addRoundedRect(inner.adjusted(border, border, -border, -border), r_in - border, r_in - border)
        p.setBrush(qcolor(theme.FIELD_FOCUS_GLOW))
        p.drawPath(glow)
    p.restore()


def row_spacing(gap: int, left: QWidget, right: QWidget) -> int:
    """`spacing` горизонтального layout, при котором между ЛИЦАМИ соседних виджетов с полями под тень или обод (клавиши,
    поля, комбо: у них есть `margins()`) будет `gap` px. Может быть отрицательным."""
    return gap - left.margins().right() - right.margins().left()


class FaceSlot(QWidget):
    """Контейнер фиксированной высоты, в котором ЛИЦО вложенного виджета (`face_rect()`, а не виджет с полями под тень)
    стоит по центру: поля клавиш (сверху 2, снизу 6) и полей (3 и 4) разные, а в макете все лица в полосе центрированы.
    Растяжение по горизонтали — как у виджета."""

    def __init__(self, widget: QWidget, height: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        face = widget.face_rect()
        top = round((height - face.height()) / 2 - face.top())
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, max(top, 0), 0, 0)
        lay.setSpacing(0)
        lay.addWidget(widget, 0, Qt.AlignmentFlag.AlignTop)
        self.setFixedHeight(height)
        self.setSizePolicy(widget.sizePolicy().horizontalPolicy(), QSizePolicy.Policy.Fixed)


@dataclass(frozen=True)
class FieldSpecs:
    """Шрифты поля: подпись (`None` у однострочного) и значение."""

    caption: text.TextSpec | None
    value: text.TextSpec
    placeholder: text.TextSpec


def field_specs(two_line: bool, wdth: float, value_px: float | None = None,
                value_weight: QFont.Weight | None = None) -> FieldSpecs:
    """Подпись Martian 8.5/600/.16em и значение: 12.5/500 у двухстрочного поля, 12/400 у однострочного (числа Profiles;
    Convert отличается, поэтому `value_px` и `value_weight` можно задать)."""
    px = value_px or (theme.FIELD_VALUE2_FONT if two_line else theme.FIELD_VALUE_FONT)
    weight = value_weight or (QFont.Weight.Medium if two_line else QFont.Weight.Normal)
    caption = text.mono(theme.FIELD_CAPTION_FONT, QFont.Weight.DemiBold, theme.FIELD_CAPTION_SPACING, wdth) if two_line \
        else None
    return FieldSpecs(caption, text.mono(px, weight, 0, wdth), text.mono(px, QFont.Weight.Normal, 0, wdth))


def text_block_height(specs: FieldSpecs, has_caption: bool) -> float:
    """Высота блока текста: значение, а у двухстрочного поля ещё подпись и зазор 1 px."""
    height = text.line_height(specs.value)
    if has_caption and specs.caption:
        height += text.line_height(specs.caption) + 1
    return height


def paint_field_text(p: QPainter, content: QRectF, specs: FieldSpecs, value: str, caption: str | None = None,
                     value_color: str = theme.FIELD_TEXT, placeholder: bool = False) -> None:
    """Текст поля в `content` (область между полями рамки): значение с «…» по правому краю, над ним — подпись;
    блок по центру высоты. `placeholder` — значение рисуется приглушённым (нет выбранного значения)."""
    two = bool(caption) and specs.caption is not None
    y = content.center().y() - text_block_height(specs, two) / 2
    if two:
        height = text.line_height(specs.caption)
        text.draw_text(p, QRectF(content.left(), y, content.width(), height), caption, specs.caption, theme.FIELD_CAPTION,
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, Qt.TextElideMode.ElideRight)
        y += height + 1
    spec = specs.placeholder if placeholder else specs.value
    color = theme.FIELD_PLACEHOLDER if placeholder else value_color
    text.draw_text(p, QRectF(content.left(), y, content.width(), text.line_height(spec)), value, spec, color,
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, Qt.TextElideMode.ElideRight)


class BezelField(QFrame):
    """Поле: лицо `paint_bezel`, внутри — `body` (QHBoxLayout, поля 10 px). Статическое поле с подписью и значением
    (`set_texts`) рисует текст само; контейнер с детьми (значок и строка ввода) текста не рисует. Фокус внутри
    (`watch(widget)`) и наведение мыши меняют рамку. Ширина шрифта `wdth` — у div `WDTH_TEXT`."""

    def __init__(self, kind: str = "bezel", parent: QWidget | None = None, *, wdth: float = theme.WDTH_TEXT,
                 caption: str | None = None, value: str = "", value_px: float | None = None,
                 value_weight: QFont.Weight | None = None) -> None:
        super().__init__(parent)
        if kind not in KINDS:
            raise ValueError(kind)
        self.kind = kind
        self.setFrameShape(QFrame.Shape.NoFrame)
        self._faces: dict[tuple[str, str], _Backdrop] = {}  # лицо по (вид, состояние)
        self._focus = False
        self._caption, self._value = caption, value
        self._specs = field_specs(caption is not None, wdth, value_px, value_weight)
        self.setFixedHeight(field_height(kind))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        self.body = QHBoxLayout(self)
        self.body.setContentsMargins(self.content_margins())
        self.body.setSpacing(theme.FIELD_GAP)

    def content_margins(self) -> QMargins:
        m, pad = field_margins(self.kind), theme.FIELD_PAD_X + 1
        return QMargins(m.left() + pad, m.top(), m.right() + pad, m.bottom())

    def margins(self) -> QMargins:
        return field_margins(self.kind)

    def face_rect(self) -> QRectF:
        m = field_margins(self.kind)
        return QRectF(m.left(), m.top(), self.width() - m.left() - m.right(), self.height() - m.top() - m.bottom())

    def content_rect(self) -> QRectF:
        """Область текста внутри лица: рамка 1 px и поля 10 px по бокам."""
        face, pad = self.face_rect(), theme.FIELD_PAD_X + 1
        return face.adjusted(pad, 0, -pad, 0)

    def set_texts(self, value: str, caption: str | None = None) -> None:
        self._value = value
        if caption is not None:
            self._caption = caption
        self.update()

    @property
    def value(self) -> str:
        return self._value

    @property
    def caption(self) -> str | None:
        return self._caption

    def watch(self, widget: QWidget) -> None:
        """Рамка фокуса — пока фокус у `widget` (строка ввода внутри поля)."""
        widget.installEventFilter(self)

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if event.type() in (QEvent.Type.FocusIn, QEvent.Type.FocusOut):
            self._focus = event.type() == QEvent.Type.FocusIn
            self.update()
        return super().eventFilter(obj, event)

    def _state(self) -> str:
        if self._focus:
            return "focus"
        return "hover" if self.isEnabled() and self.underMouse() else "normal"

    def event(self, e) -> bool:
        if e.type() in (QEvent.Type.HoverEnter, QEvent.Type.HoverLeave, QEvent.Type.EnabledChange):
            self.update()
        return super().event(e)

    def paintEvent(self, _event) -> None:
        state, face = self._state(), self.face_rect()

        def compose(p: QPainter, _rect: QRect, _origin: QPoint) -> None:
            paint_bezel(p, face, p.device().devicePixelRatioF(), self.kind, state)

        backdrop = self._faces.setdefault((self.kind, state), _Backdrop(textured=False))
        p = QPainter(self)
        p.drawPixmap(0, 0, backdrop.get(self, compose))
        if self._value:
            if not self.isEnabled():
                p.setOpacity(theme.FIELD_DISABLED_OPACITY)
            paint_field_text(p, self.content_rect(), self._specs, self._value, self._caption)

    @property
    def rebuilds(self) -> int:
        return sum(b.rebuilds for b in self._faces.values())


class IconLabel(QWidget):
    """Значок на экране: рисуется `draw_icon` в собственном цвете или заданном (у поиска — собственный)."""

    def __init__(self, name: str, color: str | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        icon = ICONS[name]
        self._name, self._color = name, color
        self.setFixedSize(icon.w, icon.h)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        draw_icon(p, self._name, QRectF(self.rect()), self._color)


class SearchField(BezelField):
    """Поле поиска (Maps): плоское на экране, значок лупы и строка ввода (`edit`). Это `<input>` макета — текст набирается
    с `WDTH_BUTTON`; текст-подсказка приглушён."""

    textChanged = Signal(str)

    def __init__(self, placeholder: str = "", parent: QWidget | None = None) -> None:
        super().__init__("screen", parent, wdth=theme.WDTH_BUTTON)
        self.edit = QLineEdit(self)
        self.edit.setFont(theme.mono_font(theme.FIELD_VALUE_FONT, wdth=theme.WDTH_BUTTON))
        self.edit.setFrame(False)
        self.edit.setPlaceholderText(placeholder)
        accent = theme.qss_rgba((98, 214, 154, 0.35))
        # локальная таблица перекрывает общую (QLineEdit со старых страниц): без фона, рамки и полей
        self.edit.setStyleSheet(
            f"QLineEdit {{ background: transparent; border: none; padding: 0; margin: 0; color: {theme.FIELD_TEXT};"
            f" selection-background-color: {accent}; selection-color: #FFFFFF;"
            f" placeholder-text-color: {theme.FIELD_PLACEHOLDER}; }}")
        pal = self.edit.palette()
        pal.setColor(QPalette.ColorRole.PlaceholderText, QColor(theme.FIELD_PLACEHOLDER))
        self.edit.setPalette(pal)
        self.body.addWidget(IconLabel("search", parent=self))
        self.body.addWidget(self.edit, 1)
        self.watch(self.edit)
        self.edit.textChanged.connect(self.textChanged)

    def text(self) -> str:
        return self.edit.text()

    def setText(self, value: str) -> None:
        self.edit.setText(value)


class ScreenCheck(QAbstractButton):
    """Флажок на экране: квадрат 15 px (рамка, затемнённая заливка) и подпись Martian 10/600/.1em — это `label > span`
    макета (`WDTH_TEXT`). Включённый — акцентная галочка и рамка (в макете показан только выключенный)."""

    def __init__(self, label: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setText(label)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        self._spec = text.mono(theme.CHECK_FONT, QFont.Weight.DemiBold, theme.CHECK_SPACING)
        self._focus_visible = False

    def sizeHint(self) -> QSize:
        """Квадрат и подпись; слева (а без подписи и справа) запас `CHECK_PAD` под кольцо фокуса, сверху и снизу он тоже
        есть. Высота чётная, чтобы квадрат вставал по центру строки без полпикселя: Qt делит остаток пополам с
        отбрасыванием, браузер — с округлением вверх."""
        pad = theme.CHECK_PAD
        width = pad + theme.CHECK_SIZE + (theme.CHECK_GAP + text.text_width(self.text(), self._spec) if self.text() else pad)
        height = max(theme.CHECK_SIZE + 2 * pad - 1, int(text.line_height(self._spec) + 0.999))
        return QSize(int(width + 0.999), height + height % 2)

    def box_rect(self) -> QRectF:
        """Квадрат флажка: слева с запасом `CHECK_PAD`, по центру высоты (половина пикселя — вверх, как у браузера: 15 px
        в строке 34 стоят со строки 10, а не с 9)."""
        return QRectF(theme.CHECK_PAD, (self.height() - theme.CHECK_SIZE + 1) // 2, theme.CHECK_SIZE, theme.CHECK_SIZE)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        dpr = self.devicePixelRatioF()
        box, border = self.box_rect(), max(1, round(dpr)) / dpr
        hot = self.underMouse() and self.isEnabled()
        color = theme.FIELD_FOCUS_BORDER if self.isChecked() else theme.CHECK_HOVER_BORDER if hot else theme.CHECK_BORDER
        r = theme.CHECK_RADIUS
        ring = QPainterPath()
        ring.setFillRule(Qt.FillRule.OddEvenFill)
        ring.addRoundedRect(box, r, r)
        ring.addRoundedRect(box.adjusted(border, border, -border, -border), r - border, r - border)
        if not self.isEnabled():
            p.setOpacity(theme.FIELD_DISABLED_OPACITY)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(qcolor(theme.FIELD_SCREEN_BG))
        p.drawRoundedRect(box, r, r)
        p.setBrush(qcolor(color))
        p.drawPath(ring)
        if self.isChecked():
            p.setPen(QPen(qcolor(theme.ACCENT), 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap, Qt.PenJoinStyle.MiterJoin))
            p.setBrush(Qt.BrushStyle.NoBrush)
            x, y = box.left(), box.top()
            p.drawPolyline([QPointF(x + 3.5, y + 7.8), QPointF(x + 6.3, y + 10.6), QPointF(x + 11.6, y + 4.6)])
        if self._focus_visible and self.hasFocus():
            p.setPen(QPen(qcolor(theme.KEY_FOCUS_RING), 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(box.adjusted(-1.5, -1.5, 1.5, 1.5), r + 1.5, r + 1.5)
        if self.text():
            text.draw_text(p, QRectF(box.right() + theme.CHECK_GAP, 0, self.width(), self.height()), self.text(),
                           self._spec, theme.CHECK_TEXT)

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
