"""Металл корпуса: текстуры, корпус с винтами, утопленные блоки. Только рисование; страницы не знают о нём.

Текстура — два слоя (шлифовка и царапины, `theme.METAL_*`) с малой непрозрачностью поверх любой металлической
поверхности. Плитки привязаны к началу ОКНА (`window_origin()`), поэтому корпус, блоки и клавиши образуют один
непрерывный лист металла: узор не «прыгает» на границах и при сдвиге виджета.
"""

import logging
from math import ceil, erfc, floor, sqrt

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, Qt
from PySide6.QtGui import (
    QBrush, QColor, QImage, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap, QRadialGradient, QTransform,
)
from PySide6.QtWidgets import QFrame, QVBoxLayout, QWidget

from . import theme
from .theme import qcolor

log = logging.getLogger(__name__)

LAYERS = (
    (theme.METAL_BRUSHED_FILE, theme.METAL_BRUSHED_TILE, theme.METAL_BRUSHED_OPACITY),
    (theme.METAL_SCRATCH_FILE, theme.METAL_SCRATCH_TILE, theme.METAL_SCRATCH_OPACITY),
)

_tiles: dict[str, QPixmap | None] = {}  # None — файла нет (предупреждение уже было)


def texture_tile(name: str, logical: int) -> QPixmap | None:
    """Плитка из assets/textures, загруженная один раз; DPR выставлен так, что её логический размер — `logical`."""
    if name not in _tiles:
        pm = QPixmap(str(theme.ASSETS / "textures" / name))
        if pm.isNull():
            log.warning("metal texture not loaded: %s", name)
            _tiles[name] = None
        else:
            pm.setDevicePixelRatio(pm.width() / logical)
            _tiles[name] = pm
    return _tiles[name]


def window_origin(w: QWidget) -> QPoint:
    """Начало окна в координатах виджета — `origin` для `paint_metal`, чтобы текстура была общей на всё окно."""
    return -w.mapTo(w.window(), QPoint(0, 0))


def _shape_path(shape: QRect | QRectF | QPainterPath, radius: float) -> QPainterPath:
    if isinstance(shape, QPainterPath):
        return shape
    path = QPainterPath()
    if radius > 0:
        path.addRoundedRect(QRectF(shape), radius, radius)
    else:
        path.addRect(QRectF(shape))
    return path


def paint_metal(painter: QPainter, shape: QRect | QRectF | QPainterPath, radius: float = 0,
                origin: QPoint | None = None) -> None:
    """Рисует оба слоя текстуры внутри фигуры (прямоугольник со скруглением или путь). Плитки раскладываются от
    `origin` (в координатах painter). Нет файла — предупреждение один раз и ровный фон (ничего не рисуется)."""
    origin = origin or QPoint(0, 0)
    path = _shape_path(shape, radius)
    bounds = path.boundingRect()
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setClipPath(path, Qt.ClipOperation.IntersectClip)
    base = painter.opacity()
    for name, size, opacity in LAYERS:
        tile = texture_tile(name, size)
        if tile is None:
            continue
        painter.setOpacity(base * opacity)
        offset = QPointF((bounds.left() - origin.x()) % size, (bounds.top() - origin.y()) % size)
        painter.drawTiledPixmap(bounds, tile, offset)
    painter.restore()


class _Backdrop:
    """Кэш готового фона виджета: пересобирается только при смене размера, DPR или положения в окне."""

    def __init__(self) -> None:
        self._key: tuple | None = None
        self._pixmap: QPixmap | None = None
        self.rebuilds = 0

    def get(self, w: QWidget, compose) -> QPixmap:
        dpr, origin = w.devicePixelRatioF(), window_origin(w)
        key = (w.width(), w.height(), dpr, origin.x(), origin.y())
        if key != self._key or self._pixmap is None:
            pm = QPixmap(ceil(w.width() * dpr), ceil(w.height() * dpr))
            pm.setDevicePixelRatio(dpr)
            pm.fill(Qt.GlobalColor.transparent)
            p = QPainter(pm)
            compose(p, QRect(0, 0, w.width(), w.height()), origin)
            p.end()
            self._key, self._pixmap = key, pm
            self.rebuilds += 1
        return self._pixmap


def _vertical(top: str, bottom: str, height: float, y0: float = 0) -> QBrush:
    g = QLinearGradient(0, y0, 0, y0 + height)
    g.setColorAt(0, qcolor(top))
    g.setColorAt(1, qcolor(bottom))
    return QBrush(g)


def _elliptical(w: float, h: float, spec: dict, stops: list[tuple[float, theme.RGBA]]) -> QBrush:
    """Радиальный градиент CSS `ellipse rx ry at cx cy`: проценты — от ширины/высоты коробки (w×h)."""
    g = QRadialGradient(0, 0, 1)  # единичный круг, растягивается матрицей кисти до эллипса
    for at, color in stops:
        g.setColorAt(at, qcolor(color))
    brush = QBrush(g)
    brush.setTransform(QTransform(spec["rx"] * w, 0, 0, spec["ry"] * h, spec["cx"] * w, spec["cy"] * h))
    return brush


class Screw(QWidget):
    """Винт 14×14 по SVG макета: блик, обод, грань с радиальным градиентом, прямой крест и его светлая копия."""

    def __init__(self, parent: QWidget | None = None, size: int = theme.SCREW_SIZE) -> None:
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.scale(self.width() / 14, self.height() / 14)  # координаты ниже — viewBox 0 0 14 14
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(qcolor(theme.SCREW_HIGHLIGHT))
        p.drawEllipse(QPointF(7, 7.6), 6.6, 6.6)
        p.setBrush(qcolor(theme.SCREW_RIM))
        p.drawEllipse(QPointF(7, 7), 6.6, 6.6)
        face = 2 * 5.7  # градиент в долях рамки грани: центр (38 %, 32 %), радиус 75 %
        g = QRadialGradient(QPointF(1.3 + 0.38 * face, 1.3 + 0.32 * face), 0.75 * face)
        g.setColorAt(0, qcolor(theme.SCREW_LIGHT))
        g.setColorAt(0.45, qcolor(theme.SCREW_MID))
        g.setColorAt(1, qcolor(theme.SCREW_DARK))
        p.setBrush(QBrush(g))
        p.drawEllipse(QPointF(7, 7), 5.7, 5.7)
        for color, width, dx in ((qcolor(theme.SCREW_SLOT), 1.4, 0.0), (qcolor(theme.SCREW_SLOT_LIGHT), 0.6, 0.6)):
            p.setPen(QPen(color, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap))
            p.drawLine(QPointF(4.3, 7 + dx), QPointF(9.7, 7 + dx))
            p.drawLine(QPointF(7 + dx, 4.3), QPointF(7 + dx, 9.7))


class MetalBody(QWidget):
    """Корпус: градиент, виньетка, верхний свет, линии кромки и текстура металла, винты по углам. Фон кэшируется по
    размеру и DPR."""

    def __init__(self, parent: QWidget | None = None, screws: bool = True) -> None:
        super().__init__(parent)
        self._backdrop = _Backdrop()
        self.screws = [Screw(self) for _ in range(4 if screws else 0)]

    def _compose(self, p: QPainter, rect: QRect, origin: QPoint) -> None:
        w, h = rect.width(), rect.height()
        g = QLinearGradient(0, 0, 0, h)
        for at, color in ((0, theme.BODY_TOP), (theme.BODY_MID_AT, theme.BODY_MID), (1, theme.BODY_BOTTOM)):
            g.setColorAt(at, qcolor(color))
        p.fillRect(rect, QBrush(g))  # слои как в CSS макета, снизу вверх: градиент, виньетка, верхний свет
        v, t = theme.BODY_VIGNETTE, theme.BODY_TOPLIGHT
        p.fillRect(rect, _elliptical(w, h, v, [(0, (0, 0, 0, 0)), (v["from"], (0, 0, 0, 0)), (1, (0, 0, 0, v["alpha"]))]))
        white = (255, 255, 255, t["alpha"])
        p.fillRect(rect, _elliptical(w, h, t, [(0, white), (t["to"], (255, 255, 255, 0)), (1, (255, 255, 255, 0))]))
        p.fillRect(QRect(0, h - 1, w, 1), qcolor(theme.BODY_EDGE_DARK))  # inset-линии: нижняя, рамка, верхняя
        frame = qcolor(theme.BODY_EDGE_FRAME)
        for line in (QRect(0, 0, w, 1), QRect(0, h - 1, w, 1), QRect(0, 0, 1, h), QRect(w - 1, 0, 1, h)):
            p.fillRect(line, frame)
        p.fillRect(QRect(0, 0, w, 1), qcolor(theme.BODY_EDGE_LIGHT))
        paint_metal(p, rect, 0, origin)  # текстура — над всем, как ::before/::after макета

    def place_screws(self) -> None:
        if not self.screws:
            return  # `screws=False` (диалоги): zip(strict) с пустым списком упал бы
        far_x = self.width() - theme.SCREW_INSET - theme.SCREW_SIZE
        far_y = self.height() - theme.SCREW_INSET - theme.SCREW_SIZE
        for screw, (x, y) in zip(self.screws, ((theme.SCREW_INSET, theme.SCREW_INSET), (far_x, theme.SCREW_INSET),
                                               (theme.SCREW_INSET, far_y), (far_x, far_y)), strict=True):
            screw.move(x, y)
            screw.raise_()  # дочерние виджеты содержимого создаются позже и иначе перекрыли бы винты

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.place_screws()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.place_screws()

    def paintEvent(self, _event) -> None:
        QPainter(self).drawPixmap(0, 0, self._backdrop.get(self, self._compose))


def _gauss_alpha(distance: float, sigma: float, alpha: float) -> float:
    """Альфа размытого гауссом края в точке на расстоянии `distance` от края (положительное — в «тень»)."""
    return alpha * 0.5 * erfc(distance / (sigma * sqrt(2)))


def _stacked_levels(p: QPainter, bounds: QRectF, dpr: float, levels: list[tuple[QPainterPath, QColor]]) -> QImage:
    """Рисует вложенные области `levels` (от большей к меньшей) в временное изображение с режимом Source: каждая меньшая
    заменяет, а не накладывается, поэтому швов антиалиасинга нет. Изображение — на `bounds` в координатах painter."""
    img = QImage(ceil(bounds.width() * dpr) + 1, ceil(bounds.height() * dpr) + 1,
                 QImage.Format.Format_ARGB32_Premultiplied)
    img.setDevicePixelRatio(dpr)
    img.fill(Qt.GlobalColor.transparent)
    q = QPainter(img)
    q.setRenderHint(QPainter.RenderHint.Antialiasing)
    q.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
    q.setPen(Qt.PenStyle.NoPen)
    q.translate(-bounds.topLeft())
    for path, color in levels:
        q.setBrush(color)
        q.drawPath(path)
    q.end()
    return img


def _hard_shadow(p: QPainter, shape: QRectF, radius: float, dy: float, color: QColor, inside: bool) -> None:
    """Тень без размытия (`0 DYpx 0 цвет`): та же фигура, сдвинутая на DY. Внутри — часть фигуры, не закрытая сдвинутой
    копией; снаружи — часть копии за пределами фигуры."""
    body, moved = _shape_path(shape, radius), _shape_path(shape.translated(0, dy), radius)
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(color)
    if inside:
        p.setClipPath(body, Qt.ClipOperation.IntersectClip)
        p.drawPath(body.subtracted(moved))
    else:
        p.drawPath(moved.subtracted(body))
    p.restore()


def inner_shadow(p: QPainter, shape: QRectF, radius: float, dpr: float, dy: float, blur: float, alpha: float,
                 rgb: tuple[int, int, int] = (0, 0, 0)) -> None:
    """Тень внутри фигуры, эквивалент `inset 0 DYpx BLURpx rgba(rgb, alpha)`: размытый гауссом край «окна», сдвинутого
    на DY (вниз при DY > 0). Альфа в точке — A·½·erfc(x / σ√2), x — расстояние внутрь от сдвинутого края (σ = BLUR/2).
    Считается вложенными областями во временном изображении. BLUR = 0 — резкая линия."""
    if blur <= 0:
        _hard_shadow(p, shape, radius, dy, qcolor((*rgb, alpha)), inside=True)
        return
    sigma, step = blur / 2, 0.5
    edge = shape.translated(0, dy)
    levels = []
    for i in reversed(range(int((blur * 2 + 4) / step))):  # от большей области к меньшей
        x = -abs(dy) - 1 + i * step
        inner = edge.adjusted(x, x, -x, -x)
        if inner.width() <= 0 or inner.height() <= 0:
            continue
        region = QPainterPath()
        region.setFillRule(Qt.FillRule.OddEvenFill)
        region.addRect(shape.adjusted(-4, -4, 4, 4))
        region.addRoundedRect(inner, max(radius - x, 0), max(radius - x, 0))
        levels.append((region, qcolor((*rgb, _gauss_alpha(x - step / 2, sigma, alpha)))))
    img = _stacked_levels(p, QRectF(0, 0, shape.right(), shape.bottom()), dpr, levels)
    p.save()
    p.setClipPath(_shape_path(shape, radius), Qt.ClipOperation.IntersectClip)
    p.drawImage(0, 0, img)
    p.restore()


def outer_shadow(p: QPainter, shape: QRectF, radius: float, dpr: float, dy: float, blur: float, alpha: float,
                 rgb: tuple[int, int, int] = (0, 0, 0)) -> None:
    """Тень снаружи фигуры, эквивалент `0 DYpx BLURpx rgba(rgb, alpha)`; под самой фигурой тени нет (как у box-shadow).
    Тот же метод, что у `inner_shadow`: альфа — A·½·erfc(d / σ√2), d — расстояние наружу от сдвинутого края. Тень
    выходит за фигуру на BLUR (вбок), BLUR − DY (вверх) и BLUR + DY (вниз): так считаются поля виджетов-клавиш."""
    if blur <= 0:
        _hard_shadow(p, shape, radius, dy, qcolor((*rgb, alpha)), inside=False)
        return
    sigma, step = blur / 2, 0.5
    edge = shape.translated(0, dy)
    reach = blur + 1
    lo = floor(-reach / step)
    levels = []
    for i in range(int(2 * reach / step), -1, -1):  # от большей области к меньшей
        d = (lo + i) * step
        grown = edge.adjusted(-d, -d, d, d)
        if grown.width() <= 0 or grown.height() <= 0:
            continue
        path = QPainterPath()
        path.addRoundedRect(grown, max(radius + d, 0), max(radius + d, 0))
        levels.append((path, qcolor((*rgb, _gauss_alpha(d - step / 2, sigma, alpha)))))
    pad = reach + abs(dy) + 1
    bounds = shape.adjusted(-pad, -pad, pad, pad)
    bounds = QRectF(floor(bounds.left() * dpr) / dpr, floor(bounds.top() * dpr) / dpr, bounds.width(), bounds.height())
    img = _stacked_levels(p, bounds, dpr, levels)
    outside = QPainterPath()
    outside.setFillRule(Qt.FillRule.OddEvenFill)
    outside.addRect(bounds)
    outside.addPath(_shape_path(shape, radius))
    p.save()
    p.setClipPath(outside, Qt.ClipOperation.IntersectClip)
    p.drawImage(bounds.topLeft(), img)
    p.restore()


class RecessedBlock(QFrame):
    """Утопленный блок: градиент, внутренняя тень, текстура и три внешние линии (тёмная над блоком, светлая и едва
    заметная под ним). Виджет резервирует под линии 1 px сверху и 2 px снизу. Контейнер: `body` — его вертикальный
    layout с полями по умолчанию; дети лежат внутри."""

    def __init__(self, parent: QWidget | None = None, margin: int = theme.RECESS_PAD) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self._backdrop = _Backdrop()
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(margin, margin + theme.RECESS_EDGE_TOP, margin, margin + theme.RECESS_EDGE_BOTTOM)
        self.body.setSpacing(8)

    def _compose(self, p: QPainter, rect: QRect, origin: QPoint) -> None:
        r, top = theme.RECESS_RADIUS, theme.RECESS_EDGE_TOP
        shape = QRectF(0, top, rect.width(), rect.height() - top - theme.RECESS_EDGE_BOTTOM)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        for dy, color in ((2, theme.RECESS_EDGE_FAINT), (1, theme.RECESS_EDGE_LIGHT), (-1, theme.RECESS_EDGE_DARK)):
            p.setBrush(qcolor(color))  # box-shadow без размытия: та же форма, сдвинутая; сам блок закроет лишнее
            p.drawRoundedRect(shape.translated(0, dy), r, r)
        p.setBrush(_vertical(theme.RECESS_TOP, theme.RECESS_BOTTOM, shape.height(), shape.top()))
        p.drawRoundedRect(shape, r, r)
        inner_shadow(p, shape, r, p.device().devicePixelRatioF(), theme.RECESS_SHADOW_DY, theme.RECESS_SHADOW_BLUR,
                     theme.RECESS_SHADOW_ALPHA)
        paint_metal(p, shape, r, origin)  # текстура поверх тени, как в макете

    def paintEvent(self, _event) -> None:
        QPainter(self).drawPixmap(0, 0, self._backdrop.get(self, self._compose))
