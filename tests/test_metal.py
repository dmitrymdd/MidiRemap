"""Металл корпуса: плитки текстур, paint_metal, MetalBody (винты), RecessedBlock (поля, тени)."""
import itertools
import logging

import pytest
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QLabel

from remap.ui import metal, theme
from remap.ui.metal import MetalBody, RecessedBlock, Screw, paint_metal, texture_tile, window_origin

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
    pad, edge = theme.RECESS_PAD, theme.RECESS_EDGE
    inner = QRect(pad, pad, 200 - 2 * pad, 100 - 2 * pad - edge)
    assert inner.contains(label.geometry()) and label.geometry().bottom() < 100 - edge
    custom = RecessedBlock(margin=20)
    assert custom.body.contentsMargins().left() == 20 and custom.body.contentsMargins().bottom() == 20 + edge


def test_recessed_block_paints_shadow_edge_and_corners(app):
    block = RecessedBlock()
    block.resize(120, 80)
    block.show()
    img = block._backdrop.get(block, block._compose).toImage()  # сам фон блока, без фона родителя
    assert img.pixelColor(0, 0).alpha() == 0 and img.pixelColor(119, 0).alpha() == 0  # углы за скруглением
    assert img.pixelColor(60, 0).red() < img.pixelColor(60, 20).red()  # у верхнего края тень темнее, чем глубже
    edge = img.pixelColor(60, 79)  # последняя строка — светлая кромка (белый, альфа ≈ 0.11)
    assert edge.red() == 255 and 20 <= edge.alpha() <= 40 and img.pixelColor(60, 78).alpha() == 255
