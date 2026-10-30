"""Металл корпуса: текстуры, корпус с винтами, утопленные блоки. Только рисование; страницы не знают о нём.

Текстура — два слоя (шлифовка и царапины, `theme.METAL_*`) с малой непрозрачностью поверх любой металлической
поверхности. Плитки привязаны к началу ОКНА (`window_origin()`), поэтому корпус, блоки и клавиши образуют один
непрерывный лист металла: узор не «прыгает» на границах и при сдвиге виджета.
"""

import logging
from math import ceil, erfc, sqrt

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, Qt
from PySide6.QtGui import (
    QBrush, QImage, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap, QRadialGradient,
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


def _vertical(top: str, bottom: str, height: float) -> QBrush:
    g = QLinearGradient(0, 0, 0, height)
    g.setColorAt(0, qcolor(top))
    g.setColorAt(1, qcolor(bottom))
    return QBrush(g)


class Screw(QWidget):
    """Винт: радиальный градиент, обод, прямой крестовой шлиц (не повёрнут). Только рисование."""

    def __init__(self, parent: QWidget | None = None, size: int = theme.SCREW_SIZE) -> None:
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def paintEvent(self, _event) -> None:
        s = self.width()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        g = QRadialGradient(QPointF(s * 0.38, s * 0.32), s * 0.8)
        g.setColorAt(0, qcolor(theme.SCREW_LIGHT))
        g.setColorAt(0.55, qcolor(theme.SCREW_MID))
        g.setColorAt(1, qcolor(theme.SCREW_DARK))
        p.setBrush(QBrush(g))
        p.setPen(QPen(qcolor(theme.SCREW_RIM), 1))
        p.drawEllipse(QRectF(0.5, 0.5, s - 1, s - 1))
        c, arm = s / 2, s * 0.27
        slot = qcolor(theme.SCREW_RIM)
        slot.setAlphaF(0.9)
        p.setPen(QPen(slot, 1.3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap))
        p.drawLine(QPointF(c - arm, c), QPointF(c + arm, c))
        p.drawLine(QPointF(c, c - arm), QPointF(c, c + arm))


class MetalBody(QWidget):
    """Корпус: вертикальный градиент и текстура металла, винты по углам. Фон кэшируется по размеру и DPR."""

    def __init__(self, parent: QWidget | None = None, screws: bool = True) -> None:
        super().__init__(parent)
        self._backdrop = _Backdrop()
        self.screws = [Screw(self) for _ in range(4 if screws else 0)]

    def _compose(self, p: QPainter, rect: QRect, origin: QPoint) -> None:
        p.fillRect(rect, _vertical(theme.BODY_TOP, theme.BODY_BOTTOM, rect.height()))
        paint_metal(p, rect, 0, origin)

    def place_screws(self) -> None:
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


def _inner_shadow(p: QPainter, shape: QRectF, radius: float, dpr: float) -> None:
    """Тень внутри фигуры, эквивалент `inset 0 DYpx BLURpx rgba(0,0,0,A)`: размытый гауссом край «окна», сдвинутого
    вниз на DY. Альфа в точке — A·½·erfc(x / σ√2), x — расстояние внутрь от сдвинутого края (σ = BLUR/2). Считается
    вложенными областями с режимом Source (без швов антиалиасинга) во временном изображении."""
    sigma, step = theme.RECESS_SHADOW_BLUR / 2, 0.5
    edge = shape.translated(0, theme.RECESS_SHADOW_DY)
    img = QImage(ceil(shape.right() * dpr) + 1, ceil(shape.bottom() * dpr) + 1,
                 QImage.Format.Format_ARGB32_Premultiplied)
    img.setDevicePixelRatio(dpr)
    img.fill(Qt.GlobalColor.transparent)
    q = QPainter(img)
    q.setRenderHint(QPainter.RenderHint.Antialiasing)
    q.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
    q.setPen(Qt.PenStyle.NoPen)
    levels = [-theme.RECESS_SHADOW_DY - 1 + i * step for i in range(int((theme.RECESS_SHADOW_BLUR * 2 + 4) / step))]
    for x in reversed(levels):  # от большей области к меньшей: Source заменяет, а не накладывает
        inner = edge.adjusted(x, x, -x, -x)
        if inner.width() <= 0 or inner.height() <= 0:
            continue
        region = QPainterPath()
        region.setFillRule(Qt.FillRule.OddEvenFill)
        region.addRect(QRectF(-4, -4, shape.width() + 8, shape.height() + 8))
        region.addRoundedRect(inner, max(radius - x, 0), max(radius - x, 0))
        color = qcolor((0, 0, 0, theme.RECESS_SHADOW_ALPHA * 0.5 * erfc((x - step / 2) / (sigma * sqrt(2)))))
        q.setBrush(color)
        q.drawPath(region)
    q.end()
    p.save()
    p.setClipPath(_shape_path(shape, radius), Qt.ClipOperation.IntersectClip)
    p.drawImage(0, 0, img)
    p.restore()


class RecessedBlock(QFrame):
    """Утопленный блок: градиент, текстура, внутренняя тень и светлая кромка под нижним краем (1 px зарезервирован).
    Контейнер: `body` — его вертикальный layout с полями по умолчанию; дети лежат внутри."""

    def __init__(self, parent: QWidget | None = None, margin: int = theme.RECESS_PAD) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self._backdrop = _Backdrop()
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(margin, margin, margin, margin + theme.RECESS_EDGE)
        self.body.setSpacing(8)

    def _compose(self, p: QPainter, rect: QRect, origin: QPoint) -> None:
        r = theme.RECESS_RADIUS
        shape = QRectF(0, 0, rect.width(), rect.height() - theme.RECESS_EDGE)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(qcolor(theme.RECESS_EDGE_LIGHT))
        p.drawRoundedRect(shape.translated(0, theme.RECESS_EDGE), r, r)  # светлая кромка видна полоской снизу
        p.setBrush(_vertical(theme.RECESS_TOP, theme.RECESS_BOTTOM, shape.height()))
        p.drawRoundedRect(shape, r, r)
        paint_metal(p, shape, r, origin)
        _inner_shadow(p, shape, r, p.device().devicePixelRatioF())

    def paintEvent(self, _event) -> None:
        QPainter(self).drawPixmap(0, 0, self._backdrop.get(self, self._compose))
