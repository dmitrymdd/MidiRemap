"""Металл корпуса: плитки текстур, paint_metal, MetalBody (винты), RecessedBlock (поля, тени)."""
import itertools
import logging
from math import erfc, sqrt

import pytest
from PySide6.QtCore import QPoint, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap, QRegion
from PySide6.QtWidgets import QLabel, QWidget

from remap.ui import metal, theme
from remap.ui.metal import (
    MetalBody, RecessedBlock, Screw, inner_shadow, outer_shadow, paint_metal, texture_tile, window_origin,
)

pytestmark = pytest.mark.ui

RED = QColor(255, 0, 0)


@pytest.fixture
def marker_layer(monkeypatch):
    """Подменяет текстуры плиткой-меткой: логические 4×4 (8 px при DPR 2), красный столбец слева, непрозрачность 1."""
    pm = QPixmap(8, 8)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.fillRect(0, 0, 1, 8, RED)
    p.end()
    pm.setDevicePixelRatio(2.0)
    monkeypatch.setattr(metal, "_tiles", {"marker": pm})
    monkeypatch.setattr(metal, "LAYERS", (("marker", 4, 1.0),))


def _image(w, h, dpr=1.0, fill=Qt.GlobalColor.black):
    img = QImage(round(w * dpr), round(h * dpr), QImage.Format.Format_ARGB32_Premultiplied)
    img.setDevicePixelRatio(dpr)
    img.fill(fill)
    return img


def _red_columns(img, y=2):
    return [x for x in range(img.width()) if img.pixelColor(x, y).red() > 128]


@pytest.mark.parametrize(("name", "logical"), [(theme.METAL_BRUSHED_FILE, theme.METAL_BRUSHED_TILE),
                                               (theme.METAL_SCRATCH_FILE, theme.METAL_SCRATCH_TILE)])
def test_texture_tiles_have_logical_size(app, name, logical):
    tile = texture_tile(name, logical)
    assert tile is not None and not tile.isNull()
    assert tile.width() == logical * 2 and tile.devicePixelRatio() == 2.0  # 1024² / 512 и 2048² / 1024
    assert tile.deviceIndependentSize().toSize().width() == logical
    assert texture_tile(name, logical) is tile  # загружается один раз


@pytest.mark.parametrize("dpr", [1.0, 1.25, 2.0])
def test_tiles_repeat_at_logical_period(app, marker_layer, dpr):
    img = _image(40, 8, dpr)
    p = QPainter(img)
    paint_metal(p, QRect(0, 0, 40, 8))
    p.end()
    cols = _red_columns(img)
    assert len(cols) >= 9 and {round((b - a) / dpr, 3) for a, b in itertools.pairwise(cols)} == {4.0}


def test_origin_shifts_the_tile_grid(app, marker_layer):
    img = _image(20, 4)
    p = QPainter(img)
    paint_metal(p, QRect(0, 0, 20, 4), origin=QPoint(1, 0))
    p.end()
    assert _red_columns(img, 1)[:3] == [1, 5, 9]


def test_texture_is_anchored_to_window(app, marker_layer):
    body = MetalBody(screws=False)
    child = QLabel(body)
    child.setGeometry(3, 0, 20, 4)
    body.resize(40, 20)
    assert window_origin(child) == QPoint(-3, 0)
    img = _image(20, 4)
    p = QPainter(img)
    paint_metal(p, QRect(0, 0, 20, 4), origin=window_origin(child))
    p.end()
    assert [x + 3 for x in _red_columns(img, 1)[:3]] == [4, 8, 12]  # в координатах окна — кратно периоду


def test_missing_texture_warns_once_and_does_not_crash(app, monkeypatch, tmp_path, caplog):
    monkeypatch.setattr(theme, "ASSETS", tmp_path)
    monkeypatch.setattr(metal, "_tiles", {})
    sentinel = QColor(10, 20, 30)
    img = _image(30, 30, fill=sentinel)
    with caplog.at_level(logging.WARNING, logger=metal.log.name):
        for _ in range(3):
            p = QPainter(img)
            paint_metal(p, QRect(0, 0, 30, 30), 5)
            p.end()
    warned = [r for r in caplog.records if "metal texture not loaded" in r.getMessage()]
    assert len(warned) == len(metal.LAYERS)  # по одному на файл, не на каждую отрисовку
    assert img.pixelColor(15, 15) == sentinel  # плоский фон: ничего не нарисовано


def test_paint_metal_stays_inside_rounded_shape(app, monkeypatch):
    white = QPixmap(8, 8)
    white.fill(QColor(255, 255, 255))
    white.setDevicePixelRatio(2.0)
    monkeypatch.setattr(metal, "_tiles", {"white": white})
    monkeypatch.setattr(metal, "LAYERS", (("white", 4, 1.0),))
    sentinel = QColor(0, 0, 0)
    img = _image(100, 60, fill=sentinel)
    p = QPainter(img)
    paint_metal(p, QRect(0, 0, 100, 60), 12)
    p.end()
    for corner in ((0, 0), (99, 0), (0, 59), (99, 59), (1, 1), (98, 1)):
        assert img.pixelColor(*corner) == sentinel, corner  # углы за скруглением нетронуты
    assert img.pixelColor(50, 30) == QColor(255, 255, 255) and img.pixelColor(50, 0).red() > 200


def test_metal_body_has_four_screws_at_corners(app):
    body = MetalBody()
    body.resize(300, 200)
    body.show()
    app.processEvents()
    assert len(body.screws) == 4 and all(isinstance(s, Screw) for s in body.screws)
    s, inset = theme.SCREW_SIZE, theme.SCREW_INSET
    assert {(sc.x(), sc.y()) for sc in body.screws} == {(inset, inset), (300 - inset - s, inset),
                                                         (inset, 200 - inset - s), (300 - inset - s, 200 - inset - s)}
    body.resize(500, 320)
    assert {(sc.x(), sc.y()) for sc in body.screws} == {(inset, inset), (500 - inset - s, inset),
                                                         (inset, 320 - inset - s), (500 - inset - s, 320 - inset - s)}
    assert all(sc.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents) for sc in body.screws)
    assert not MetalBody(screws=False).screws  # для диалогов


def test_metal_body_screws_stay_above_later_children(app):
    body = MetalBody()
    late = QLabel(body)  # создан после винтов
    body.resize(200, 100)
    body.show()
    app.processEvents()
    order = body.children()
    assert all(order.index(sc) > order.index(late) for sc in body.screws)


def test_metal_body_background_is_cached_until_resize(app):
    body = MetalBody()
    body.resize(300, 200)
    body.show()
    body.grab()
    n = body._backdrop.rebuilds
    body.repaint()
    body.repaint()
    assert body._backdrop.rebuilds == n  # перерисовка без смены размера фон не пересобирает
    body.resize(320, 200)
    body.grab()
    assert body._backdrop.rebuilds == n + 1


def test_recessed_block_lays_out_children_inside_margins(app):
    block = RecessedBlock()
    label = QLabel("x")
    block.body.addWidget(label)
    block.resize(200, 100)
    block.show()
    app.processEvents()
    pad, top, bottom = theme.RECESS_PAD, theme.RECESS_EDGE_TOP, theme.RECESS_EDGE_BOTTOM
    assert pad == 6
    inner = QRect(pad, pad + top, 200 - 2 * pad, 100 - 2 * pad - top - bottom)
    assert inner.contains(label.geometry())
    custom = RecessedBlock(margin=20)
    m = custom.body.contentsMargins()
    assert (m.left(), m.top(), m.bottom()) == (20, 20 + top, 20 + bottom)


def test_recessed_block_paints_shadow_outer_lines_and_corners(app):
    block = RecessedBlock()
    block.resize(120, 80)
    block.show()
    img = block._backdrop.get(block, block._compose).toImage()  # сам фон блока, без фона родителя
    assert img.pixelColor(0, 0).alpha() == 0 and img.pixelColor(119, 1).alpha() == 0  # углы за скруглением
    dark = img.pixelColor(60, 0)  # тёмная линия над блоком (0 -1px 0 rgba(0,0,0,.55))
    assert dark.red() == 0 and 125 <= dark.alpha() <= 155
    assert img.pixelColor(60, 1).red() < img.pixelColor(60, 20).red()  # у верхнего края тень темнее, чем глубже
    light, faint = img.pixelColor(60, 78), img.pixelColor(60, 79)  # светлая .11 и едва заметная .03 под блоком
    assert light.red() == 255 and 20 <= light.alpha() <= 40
    assert faint.red() == 255 and 4 <= faint.alpha() <= 12
    assert img.pixelColor(60, 77).alpha() == 255  # последняя строка самого блока


def test_screw_geometry_matches_mockup(app):
    assert (theme.SCREW_SIZE, theme.SCREW_INSET) == (14, 11)
    body = MetalBody()
    body.resize(900, 800)
    body.show()
    assert {(sc.x(), sc.y()) for sc in body.screws} == {(11, 11), (875, 11), (11, 775), (875, 775)}
    img = QImage(14, 14, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    body.screws[0].render(img, QPoint(), QRegion(), QWidget.RenderFlag.DrawChildren)  # без фона окна
    assert img.pixelColor(7, 7).alpha() == 255 and img.pixelColor(0, 0).alpha() == 0  # круг в углах прозрачен


def test_body_shading_follows_mockup(app):
    body = MetalBody(screws=False)
    body.resize(900, 800)
    img = body._backdrop.get(body, body._compose).toImage()
    top_centre, mid_left, bottom_right = img.pixelColor(450, 20), img.pixelColor(100, 400), img.pixelColor(850, 780)
    assert top_centre.red() > mid_left.red() > bottom_right.red()  # верхний свет, затем виньетка к углам
    assert img.pixelColor(0, 400).red() < 14 and img.pixelColor(450, 799).red() < 14  # рамка #0A0B0C по краю
    assert img.pixelColor(450, 0).red() > 40  # светлая линия сверху (белый .12 над рамкой)


def _transparent(w, h, dpr=1.0):
    img = QImage(round(w * dpr), round(h * dpr), QImage.Format.Format_ARGB32_Premultiplied)
    img.setDevicePixelRatio(dpr)
    img.fill(Qt.GlobalColor.transparent)
    return img


def _expected(distance, blur, alpha):
    """Альфа размытого гауссом края (σ = blur/2) на расстоянии `distance` внутрь тени."""
    return alpha * 0.5 * erfc(distance / (blur / 2 * sqrt(2))) * 255


@pytest.mark.parametrize("dpr", [1.0, 2.0])
def test_outer_shadow_follows_gaussian_profile(app, dpr):
    """`0 3px 6px rgba(0,0,0,.65)` под широким прямоугольником: на оси x посередине профиль по вертикали — erfc."""
    img = _transparent(120, 80, dpr)
    p = QPainter(img)
    outer_shadow(p, QRectF(10, 10, 100, 40), 0, dpr, 3, 6, 0.65)
    p.end()
    for d in (-2, 0, 1, 3, 5):  # d — расстояние вниз от сдвинутого края (нижний край фигуры 50, сдвинутый 53)
        y = 53 + d
        got = img.pixelColor(round(60 * dpr), round(y * dpr)).alpha()
        assert got == pytest.approx(_expected(d + 0.5 / dpr, 6, 0.65), abs=4), d
    assert img.pixelColor(round(60 * dpr), round(70 * dpr)).alpha() == 0  # дальше BLUR + DY тени нет
    assert img.pixelColor(round(60 * dpr), round(30 * dpr)).alpha() == 0  # под самой фигурой тени нет (как у box-shadow)


def test_outer_shadow_margins_match_blur_and_offset(app):
    """Тень выходит за фигуру на BLUR вбок, BLUR − DY вверх и BLUR + DY вниз: из этого считаются поля клавиши."""
    img = _transparent(60, 50)
    p = QPainter(img)
    outer_shadow(p, QRectF(10, 10, 40, 20), 0, 1.0, 2, 4, 0.6)  # 0 2px 4px
    p.end()
    visible = {(x, y) for x in range(60) for y in range(50) if img.pixelColor(x, y).alpha() > 4}
    xs, ys = [x for x, _ in visible], [y for _, y in visible]
    assert min(xs) >= 10 - 4 and max(xs) <= 50 + 4  # вбок не дальше BLUR
    assert min(ys) >= 10 - 2 and max(ys) <= 30 + 6  # вверх BLUR − DY, вниз BLUR + DY
    assert min(ys) < 10 and max(ys) > 30  # и действительно выходит


def test_outer_shadow_without_blur_is_a_hard_line(app):
    img = _transparent(40, 30)
    p = QPainter(img)
    outer_shadow(p, QRectF(5, 5, 30, 15), 4, 1.0, 1, 0, 0.06, rgb=(255, 255, 255))  # 0 1px 0 rgba(255,255,255,.06)
    p.end()
    line, below, inside = img.pixelColor(20, 20), img.pixelColor(20, 22), img.pixelColor(20, 12)
    assert line.red() == 255 and line.alpha() == pytest.approx(0.06 * 255, abs=2)
    assert below.alpha() == 0 and inside.alpha() == 0


@pytest.mark.parametrize("dy", [2, -1])
def test_inner_shadow_general_offset_and_blur(app, dy):
    img = _transparent(120, 80)
    p = QPainter(img)
    p.fillRect(QRect(10, 10, 100, 60), Qt.GlobalColor.white)
    inner_shadow(p, QRectF(10, 10, 100, 60), 0, 1.0, dy, 4, 0.8)
    p.end()
    edge = 10 + dy if dy > 0 else 70 + dy  # сдвинутый край окна: у верхней стороны (dy > 0) или у нижней (dy < 0)
    inward = 1 if dy > 0 else -1
    for depth in (0, 2, 4):
        y = round(edge + inward * (depth + 0.5))
        shade = 255 - img.pixelColor(60, y).red()  # чёрная тень на белом: чем темнее, тем сильнее
        assert shade == pytest.approx(_expected(depth + 0.5, 4, 0.8), abs=9), (dy, depth)
    assert img.pixelColor(60, 40).red() == 255  # в глубине фигуры тени нет


def test_inner_shadow_without_blur_is_a_hard_line_clipped_to_shape(app):
    img = _transparent(40, 30)
    p = QPainter(img)
    p.fillRect(QRect(5, 5, 30, 20), Qt.GlobalColor.black)
    inner_shadow(p, QRectF(5, 5, 30, 20), 0, 1.0, 1, 0, 0.11, rgb=(255, 255, 255))  # inset 0 1px 0 rgba(255,255,255,.11)
    p.end()
    assert img.pixelColor(20, 5).red() == pytest.approx(0.11 * 255, abs=2)  # верхняя строка внутри фигуры
    assert img.pixelColor(20, 6).red() == 0
    assert img.pixelColor(20, 4).alpha() == 0  # снаружи не рисуется
