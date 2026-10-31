"""Экран («зелёное стекло»): фон, рамка, тень внутри, сетка и узкая полоса прокрутки. Страницы кладут содержимое в
`Screen.body`, а список или сцену подключают к полосе через `Screen.attach()`.

`paint_glass()` — чистая функция рисования (в тестах и в списке комбо), `Screen` — виджет, который кэширует готовый
фон и пересобирает его только при смене размера или DPR (текстуры у стекла нет, сдвиг виджета фон не трогает).
"""

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, Qt
from PySide6.QtGui import QBrush, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QAbstractScrollArea, QFrame, QScrollBar, QVBoxLayout, QWidget

from . import theme
from .metal import _Backdrop, _elliptical, inner_shadow
from .theme import qcolor

_grid_tiles: dict[float, QPixmap] = {}


def grid_tile(dpr: float) -> QPixmap:
    """Плитка сетки 32×32: крест из линий 1 px длиной 5 px по центру (`M16 13.5 V18.5 M13.5 16 H18.5`, #7FB596 при 13 %).
    Готовится под DPR один раз; размер в устройственных пикселях округляется, чтобы плитки стыковались без шва.
    Крест рисуется сплошным цветом, а прозрачность накладывается потом: иначе пересечение линий в центре
    смешивалось бы дважды (в SVG макета прозрачность одна на весь path)."""
    step = theme.SCREEN_GRID_STEP
    if dpr not in _grid_tiles:
        size = round(step * dpr)
        ratio = size / step
        cross = QPixmap(size, size)
        cross.setDevicePixelRatio(ratio)
        cross.fill(Qt.GlobalColor.transparent)
        p = QPainter(cross)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = qcolor(theme.SCREEN_GRID[:3] + (1.0,))
        p.setPen(QPen(color, 1, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap))
        c = step / 2
        p.drawLine(QPointF(c, c - 2.5), QPointF(c, c + 2.5))
        p.drawLine(QPointF(c - 2.5, c), QPointF(c + 2.5, c))
        p.end()
        tile = QPixmap(size, size)
        tile.setDevicePixelRatio(ratio)
        tile.fill(Qt.GlobalColor.transparent)
        p = QPainter(tile)
        p.setOpacity(theme.SCREEN_GRID[3])
        p.drawPixmap(0, 0, cross)
        p.end()
        _grid_tiles[dpr] = tile
    return _grid_tiles[dpr]


def paint_glass(p: QPainter, rect: QRectF, dpr: float, glow_ry: float = theme.SCREEN_GLOW["ry"], grid: bool = True,
                shadow: bool = True, radius: float = theme.SCREEN_RADIUS) -> None:
    """Стекло в `rect` (с рамкой 1 px): радиальный градиент (эллипс `SCREEN_GLOW`, от верхнего края), рамка, тень внутри
    `SCREEN_SHADOW`, сетка 32 px от внутреннего края (поверх тени, под содержимым). `glow_ry` — вертикальный радиус
    эллипса в долях высоты (у окна About 0.80); `radius` — скругление (0 — квадратное)."""
    r = radius
    inner = rect.adjusted(1, 1, -1, -1)
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(qcolor(theme.SCREEN_BORDER))
    p.drawRoundedRect(rect, r, r)
    glow = {**theme.SCREEN_GLOW, "ry": glow_ry}
    stops = [(0, theme.SCREEN_GLASS_INNER), (theme.SCREEN_GLOW_MID_AT, theme.SCREEN_GLASS_MID),
             (1, theme.SCREEN_GLASS_OUTER)]
    p.save()
    p.translate(inner.topLeft())  # градиент считается от padding-box: его размеры — без рамки
    brush = _elliptical(inner.width(), inner.height(), glow, [(at, (*qcolor(c).getRgb()[:3], 1.0)) for at, c in stops])
    p.setBrush(brush)
    p.drawRoundedRect(QRectF(0, 0, inner.width(), inner.height()), max(r - 1, 0), max(r - 1, 0))
    p.restore()
    if shadow:
        inner_shadow(p, inner, max(r - 1, 0), dpr, **theme.SCREEN_SHADOW)
    if grid:
        clip = QPainterPath()
        clip.addRoundedRect(inner, max(r - 1, 0), max(r - 1, 0))
        p.setClipPath(clip, Qt.ClipOperation.IntersectClip)
        p.drawTiledPixmap(inner, grid_tile(dpr), QPointF(0, 0))
    p.restore()


class ScreenScrollBar(QWidget):
    """Узкая полоса прокрутки (3 px) на экране: рисует дорожку и ручку, а значение берёт у штатной полосы области
    прокрутки и пишет в неё (двусторонне). Штатная полоса отключена (`ScrollBarAlwaysOff`) — прокрутка колесом и клавишами
    работает как раньше. Невидима, пока прокручивать нечего. Ширина виджета больше видимой полосы — так за неё можно взяться."""

    def __init__(self, view: QAbstractScrollArea, parent: QWidget) -> None:
        super().__init__(parent)
        self._view = view
        self._source: QScrollBar | None = None
        view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._drag: float | None = None  # смещение точки захвата от верха ручки
        self._hover = False
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        self.setFixedWidth(theme.SCROLL_WIDTH + 2 * theme.SCROLL_HIT)
        self._sync()

    @property
    def _bar(self) -> QScrollBar:
        """Штатная вертикальная полоса области. Контейнер списка комбо Qt подменяет её при показе, поэтому берём каждый
        раз у области и подписываемся заново, если объект другой."""
        bar = self._view.verticalScrollBar()
        if bar is not self._source:
            self._source = bar
            bar.valueChanged.connect(self.update)
            bar.rangeChanged.connect(self._sync)
        return bar

    def place(self, track_left: int, top: int, height: int) -> None:
        """Ставит дорожку: левый край видимой полосы, верх и высота — в координатах родителя."""
        self.setGeometry(track_left - theme.SCROLL_HIT, top, self.width(), max(height, 0))
        self._sync()

    def _sync(self, *_args) -> None:
        bar = self._bar
        self.setVisible(bar.maximum() > bar.minimum() and self.height() > 0)
        self.update()

    def handle_rect(self) -> QRectF:
        """Ручка в координатах виджета: длина пропорциональна видимой доле, но не короче `SCROLL_MIN_HANDLE`."""
        bar, length = self._bar, float(self.height())
        span = bar.maximum() - bar.minimum()
        total = span + bar.pageStep()
        size = min(length, max(float(theme.SCROLL_MIN_HANDLE), length * bar.pageStep() / total)) if total > 0 else length
        free = length - size
        top = free * (bar.value() - bar.minimum()) / span if span > 0 else 0.0
        return QRectF(theme.SCROLL_HIT, top, theme.SCROLL_WIDTH, size)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        r = theme.SCROLL_RADIUS
        p.setBrush(qcolor(theme.SCROLL_TRACK))
        p.drawRoundedRect(QRectF(theme.SCROLL_HIT, 0, theme.SCROLL_WIDTH, self.height()), r, r)
        hot = self._hover or self._drag is not None
        p.setBrush(QBrush(qcolor(theme.SCROLL_HANDLE_HOVER if hot else theme.SCROLL_HANDLE)))
        p.drawRoundedRect(self.handle_rect(), r, r)

    # --- мышь ---
    def _set_from_handle_top(self, top: float) -> None:
        bar, handle = self._bar, self.handle_rect()
        free = self.height() - handle.height()
        if free > 0:
            frac = min(max(top / free, 0.0), 1.0)
            bar.setValue(round(bar.minimum() + frac * (bar.maximum() - bar.minimum())))

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        y, handle = event.position().y(), self.handle_rect()
        if handle.top() <= y <= handle.bottom():
            self._drag = y - handle.top()
        else:  # по дорожке — на страницу к точке нажатия
            step = self._bar.pageStep()
            self._bar.setValue(self._bar.value() + (step if y > handle.bottom() else -step))
        self.update()

    def mouseMoveEvent(self, event) -> None:
        if self._drag is not None:
            self._set_from_handle_top(event.position().y() - self._drag)

    def mouseReleaseEvent(self, _event) -> None:
        self._drag = None
        self.update()

    def wheelEvent(self, event) -> None:
        notches = event.angleDelta().y() / 120
        self._bar.setValue(self._bar.value() - round(notches * 3 * self._bar.singleStep()))
        event.accept()

    def event(self, e) -> bool:
        if e.type() == e.Type.HoverEnter:
            self._hover = True
            self.update()
        elif e.type() == e.Type.HoverLeave:
            self._hover = False
            self.update()
        return super().event(e)


class Screen(QFrame):
    """Экран: стеклянный фон с рамкой 1 px, содержимое — в `body` (поля 14 + рамка). Полоса прокрутки лежит в правом
    поле (5 px от внутреннего края) и подключается `attach()`."""

    def __init__(self, parent: QWidget | None = None, glow_ry: float = theme.SCREEN_GLOW["ry"], grid: bool = True,
                 pad: int = theme.SCREEN_PAD) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self._backdrop = _Backdrop(textured=False)
        self._glow_ry, self._grid = glow_ry, grid
        self._bars: list[tuple[ScreenScrollBar, int, int]] = []
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(pad + 1, pad + 1, pad + 1, pad + 1)
        self.body.setSpacing(0)

    def _compose(self, p: QPainter, rect: QRect, _origin: QPoint) -> None:
        paint_glass(p, QRectF(rect), p.device().devicePixelRatioF(), self._glow_ry, self._grid)

    def attach(self, view: QAbstractScrollArea, top: int = theme.SCREEN_PAD, bottom: int = theme.SCREEN_PAD) -> ScreenScrollBar:
        """Подключает полосу к области прокрутки; `top`/`bottom` — отступы дорожки от внутренних краёв экрана
        (по умолчанию как поля содержимого; на Maps дорожка начинается под панелью поиска и заголовком)."""
        bar = ScreenScrollBar(view, self)
        self._bars.append((bar, top, bottom))
        self._place(bar, top, bottom)
        bar.raise_()
        return bar

    def _place(self, bar: ScreenScrollBar, top: int, bottom: int) -> None:
        left = self.width() - 1 - theme.SCROLL_RIGHT - theme.SCROLL_WIDTH
        bar.place(left, 1 + top, self.height() - 2 - top - bottom)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        for bar, top, bottom in self._bars:
            self._place(bar, top, bottom)

    def paintEvent(self, _event) -> None:
        QPainter(self).drawPixmap(0, 0, self._backdrop.get(self, self._compose))
