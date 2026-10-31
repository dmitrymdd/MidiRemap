"""Значки: разборщик путей, границы в viewBox, сверка отрисовки с QtSvg (эталон только в тестах)."""
import pytest

pytest.importorskip("PySide6")
pytestmark = pytest.mark.ui

from PySide6.QtCore import QByteArray, QPointF, QRectF
from PySide6.QtGui import QImage, QPainter

from remap.ui import icons, theme
from remap.ui.icons import ICONS, draw_icon, icon_pixmap, icon_svg, parse_path


def _render(draw, w: float, h: float, scale: float) -> QImage:
    img = QImage(round(w * scale), round(h * scale), QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(0)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.scale(scale, scale)
    draw(p)
    p.end()
    return img


def _alpha(img: QImage) -> list[int]:
    return [img.pixelColor(x, y).alpha() for y in range(img.height()) for x in range(img.width())]


def test_parser_handles_all_commands(app):
    path = parse_path("M1 1 H5 V4 L2 4 C 3 6, 4 6, 5 5 Z")
    box = path.boundingRect()
    assert (box.left(), box.top(), box.right()) == (1, 1, 5)
    assert path.elementCount() == 8  # M, H, V, L, три точки кривой C, замыкающая линия
    assert path.contains(QPointF(2, 2))  # замкнутый контур: Z вернул перо в начало


def test_parser_accepts_commas_negatives_and_implicit_spaces(app):
    a = parse_path("M1,2 L-3 .5")
    assert a.currentPosition() == QPointF(-3, 0.5)
    assert parse_path("M0 0 H4 H-1").currentPosition() == QPointF(-1, 0)


def test_parser_rejects_unsupported_commands(app):
    with pytest.raises(ValueError):
        parse_path("m1 1 l2 2")  # относительные команды в значках макета не встречаются
    with pytest.raises(ValueError):
        parse_path("M1")  # не хватает числа


def test_icon_set_is_complete(app):
    expected = {"tab-convert", "tab-profiles", "tab-maps", "dots", "save", "swap", "go-arrow", "map-new", "map-import",
                "map-export", "map-more", "search", "lock", "chevron-down", "group-caret", "file", "x", "drop-target",
                "output-din", "code", "chat", "mail", "external-link"}
    assert set(ICONS) == expected and len(ICONS) >= 22


@pytest.mark.parametrize("name", sorted(ICONS))
def test_icon_geometry_stays_inside_viewbox(app, name):
    icon = ICONS[name]
    for prim in icon.prims:
        box = icons._shape(prim).boundingRect()
        assert box.left() >= 0 and box.top() >= 0 and box.right() <= icon.w and box.bottom() <= icon.h, name


@pytest.mark.parametrize("name", sorted(ICONS))
@pytest.mark.parametrize("scale", [1, 4])
def test_rendering_matches_qtsvg(app, name, scale):
    """Те же данные, нарисованные нашим кодом и QSvgRenderer: расхождение — только сглаживание краёв."""
    from PySide6.QtSvg import QSvgRenderer

    icon = ICONS[name]
    ours = _render(lambda p: draw_icon(p, name, QRectF(0, 0, icon.w, icon.h), "#FFFFFF"), icon.w, icon.h, scale)
    renderer = QSvgRenderer(QByteArray(icon_svg(name).encode()))
    ref = _render(lambda p: renderer.render(p, QRectF(0, 0, icon.w, icon.h)), icon.w, icon.h, scale)
    diffs = [abs(a - b) for a, b in zip(_alpha(ours), _alpha(ref), strict=True)]
    assert sum(diffs) / len(diffs) < 1.5 and max(diffs) <= 64, name  # из 255


def test_stroke_override_matches_qtsvg(app):
    icon = ICONS["x"]
    from PySide6.QtSvg import QSvgRenderer

    ours = _render(lambda p: draw_icon(p, "x", QRectF(0, 0, 10, 10), "#FFFFFF", stroke=1.5), 10, 10, 4)
    renderer = QSvgRenderer(QByteArray(icon_svg("x", stroke=1.5).encode()))
    ref = _render(lambda p: renderer.render(p, QRectF(0, 0, 10, 10)), icon.w, icon.h, 4)
    assert max(abs(a - b) for a, b in zip(_alpha(ours), _alpha(ref), strict=True)) <= 64


def test_colour_comes_from_caller_or_from_the_icon(app):
    img = _render(lambda p: draw_icon(p, "dots", QRectF(0, 0, 14, 4), "#62D69A"), 14, 4, 4)
    assert img.pixelColor(8, 8).name().upper() == "#62D69A"  # внутри первого квадрата 3×3
    own = _render(lambda p: draw_icon(p, "chevron-down", QRectF(0, 0, 10, 6)), 10, 6, 4)
    assert own.pixelColor(20, 8).name().upper() == theme.SCREEN_TEXT_2
    canvas = QImage(4, 4, QImage.Format.Format_ARGB32)
    painter = QPainter(canvas)
    with pytest.raises(ValueError):
        draw_icon(painter, "dots", QRectF(0, 0, 14, 4))  # у «dots» нет собственного цвета
    painter.end()


def test_drawing_is_clipped_to_the_viewbox_and_centred(app):
    # 14×4 значок в большом прямоугольнике — по центру без масштаба при совпадении пропорций
    img = _render(lambda p: draw_icon(p, "dots", QRectF(0, 0, 14, 4), "#FFFFFF"), 20, 20, 1)
    assert img.pixelColor(1, 1).alpha() > 0 and img.pixelColor(15, 1).alpha() == 0
    big = _render(lambda p: draw_icon(p, "dots", QRectF(0, 0, 28, 8), "#FFFFFF"), 28, 8, 1)  # масштаб ×2
    assert big.pixelColor(3, 3).alpha() == 255 and big.pixelColor(9, 3).alpha() == 0  # зазор между квадратами


def test_icon_pixmap_has_icon_size_and_dpr(app):
    pm = icon_pixmap("save", "#C3C9CE", 2.0)
    assert (pm.width(), pm.height(), pm.devicePixelRatio()) == (28, 28, 2.0)
    assert icon_pixmap("save", "#C3C9CE", 2.0) is pm  # кэш
    assert icon_pixmap("go-arrow", "#62D69A", 1.0).width() == 22


def test_icon_svg_is_valid_xml(app):
    import xml.etree.ElementTree as ET

    for name in ICONS:
        assert ET.fromstring(icon_svg(name)).tag.endswith("svg")
