"""Стекло экрана (`ui/glass.py`): рисование, сетка, кэш `Screen`, полоса прокрутки и её связь с областью прокрутки."""
import pytest

pytest.importorskip("PySide6")
pytestmark = pytest.mark.ui

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QColor, QImage, QMouseEvent, QPainter, QRegion, QWheelEvent
from PySide6.QtWidgets import QApplication, QListWidget, QWidget

from remap.ui import theme
from remap.ui.glass import Screen, ScreenScrollBar, grid_tile, paint_glass


def render(w: float, h: float, dpr: float = 1.0, **kw) -> QImage:
    img = QImage(round(w * dpr), round(h * dpr), QImage.Format.Format_ARGB32_Premultiplied)
    img.setDevicePixelRatio(dpr)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    from PySide6.QtCore import QRectF
    paint_glass(p, QRectF(0, 0, w, h), dpr, **kw)
    p.end()
    return img


def at(img: QImage, x: float, y: float) -> tuple[int, int, int, int]:
    dpr = img.devicePixelRatio()
    c = img.pixelColor(int(x * dpr), int(y * dpr))
    return c.red(), c.green(), c.blue(), c.alpha()


def close(a, b, tol=4) -> bool:
    return all(abs(x - y) <= tol for x, y in zip(a[:3], b[:3], strict=True))


def rgb(hex_color: str) -> tuple[int, int, int]:
    c = QColor(hex_color)
    return c.red(), c.green(), c.blue()


# --- рисование ---
def test_glass_border_corner_and_gradient_follow_the_mockup(app):
    img = render(248, 616, shadow=False, grid=False)
    assert at(img, 0.5, 308)[:3] == rgb(theme.SCREEN_BORDER)  # рамка 1 px
    assert at(img, 124, 0.5)[:3] == rgb(theme.SCREEN_BORDER)
    assert at(img, 0.2, 0.2)[3] == 0  # скруглённый угол прозрачен
    assert close(at(img, 124, 1.5), rgb(theme.SCREEN_GLASS_INNER), 5)  # свет у верхней кромки
    # ниже 60 % эллипса (0.6 · 0.7 · 614 = 258 px) — #0D1C15, у нижнего края — #0A1711
    assert close(at(img, 124, 258), rgb(theme.SCREEN_GLASS_MID), 3)
    assert close(at(img, 124, 600), rgb(theme.SCREEN_GLASS_OUTER), 3)
    assert at(img, 124, 20)[1] > at(img, 124, 200)[1] > at(img, 124, 400)[1]  # свет убывает вниз


def test_glass_inner_shadow_darkens_the_edge_but_not_the_middle(app):
    plain, shaded = render(248, 616, shadow=False, grid=False), render(248, 616, grid=False)
    assert at(shaded, 124, 308) == at(plain, 124, 308)  # далеко от края (> 27 px) тени нет
    assert at(shaded, 3, 308)[1] < at(plain, 3, 308)[1] - 4  # у края темнее
    assert at(shaded, 124, 3)[1] < at(plain, 124, 3)[1] - 4  # сверху тоже (dy 0: со всех сторон)


def test_glass_grid_cross_positions_and_single_blend(app):
    """Крест — в 16 + 32k от ВНУТРЕННЕГО края (рамка 1 px), прозрачность одна на крест (в центре не двойная)."""
    img = render(248, 616, 2.0, shadow=False)
    off = render(248, 616, 2.0, shadow=False, grid=False)

    def lift(x: float, y: float) -> int:
        return at(img, x, y)[1] - at(off, x, y)[1]

    assert lift(1 + 16, 1 + 16) > 8 and lift(1 + 16 + 32, 1 + 16) > 8 and lift(1 + 16, 1 + 16 + 32) > 8
    assert abs(lift(1 + 16, 1 + 16) - lift(1 + 16, 1 + 17.9)) <= 2  # центр не ярче концов линии
    assert lift(1 + 8, 1 + 8) == 0 and lift(1 + 32, 1 + 32) == 0  # между крестами пусто
    assert lift(0.5, 0.5) == 0  # рамка сетку не получает


@pytest.mark.parametrize("dpr", [1.0, 1.25, 2.0])
def test_grid_tile_is_cached_and_whole_device_pixels(app, dpr):
    tile = grid_tile(dpr)
    assert tile is grid_tile(dpr)
    assert tile.width() == round(32 * dpr) and tile.width() / tile.devicePixelRatio() == pytest.approx(32)
    img = tile.toImage()
    centre = img.width() // 2
    arm = img.pixelColor(centre, centre - round(2 * dpr)).alpha()
    assert arm > 0 and img.pixelColor(centre, centre).alpha() <= arm * 1.6  # не двойной в центре


def test_glass_radius_zero_is_square_and_ry_changes_the_glow(app):
    square = render(100, 100, shadow=False, grid=False, radius=0)
    assert at(square, 0.2, 0.2)[3] == 255
    tall = render(248, 616, shadow=False, grid=False, glow_ry=0.8)
    short = render(248, 616, shadow=False, grid=False)
    assert at(tall, 124, 400)[1] > at(short, 124, 400)[1]  # About: свет дальше вниз


# --- виджет Screen ---
def test_screen_margins_and_backdrop_cache(app):
    screen = Screen()
    screen.resize(260, 300)
    screen.show()
    app.processEvents()
    m = screen.body.contentsMargins()
    assert (m.left(), m.top(), m.right(), m.bottom()) == (15, 15, 15, 15)  # 14 + рамка
    img = screen.grab().toImage()
    assert at(img, 130, 0.5)[:3] == rgb(theme.SCREEN_BORDER)
    before = screen._backdrop.rebuilds
    screen.move(40, 60)  # текстуры нет: сдвиг фон не трогает
    app.processEvents()
    screen.grab()
    assert screen._backdrop.rebuilds == before
    screen.resize(280, 300)
    screen.grab()
    assert screen._backdrop.rebuilds == before + 1
    screen.close()


# --- полоса прокрутки ---
def make_view(rows: int, parent: QWidget | None = None) -> QListWidget:
    view = QListWidget(parent)
    view.addItems([f"row {i}" for i in range(rows)])
    return view


@pytest.fixture
def attached(app):
    screen = Screen()
    screen.resize(260, 628)
    view = make_view(80)
    screen.body.addWidget(view)
    bar = screen.attach(view)
    screen.show()
    app.processEvents()
    yield screen, view, bar
    screen.close()


def test_scrollbar_geometry_in_the_right_gutter(attached):
    screen, view, bar = attached
    track_left = bar.geometry().x() + theme.SCROLL_HIT
    assert track_left == screen.width() - 1 - theme.SCROLL_RIGHT - theme.SCROLL_WIDTH == 251
    assert bar.geometry().y() == 1 + 14 and bar.height() == 628 - 2 - 14 - 14
    assert view.verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff  # штатная полоса отключена
    assert bar.isVisible()


def test_scrollbar_custom_top_and_bottom(app):
    screen = Screen()
    screen.resize(564, 628)
    view = make_view(80)
    screen.body.addWidget(view)
    bar = screen.attach(view, top=86, bottom=58)  # Maps: дорожка под панелью поиска и заголовком
    screen.show()
    app.processEvents()
    assert (bar.geometry().y(), bar.height()) == (1 + 86, 628 - 2 - 86 - 58) == (87, 482)
    screen.close()


def test_scrollbar_hidden_when_nothing_scrolls(app):
    screen = Screen()
    screen.resize(260, 628)
    view = make_view(3)
    screen.body.addWidget(view)
    bar = screen.attach(view)
    screen.show()
    app.processEvents()
    assert not bar.isVisible()
    view.addItems([f"more {i}" for i in range(100)])
    app.processEvents()
    assert bar.isVisible()
    screen.close()


def test_handle_is_proportional_with_minimum_and_follows_the_view(attached):
    _, view, bar = attached
    sb = view.verticalScrollBar()
    handle = bar.handle_rect()
    assert handle.width() == theme.SCROLL_WIDTH and handle.top() == 0
    expected = bar.height() * sb.pageStep() / (sb.maximum() - sb.minimum() + sb.pageStep())
    assert handle.height() == pytest.approx(max(theme.SCROLL_MIN_HANDLE, expected))
    sb.setValue(sb.maximum())
    end = bar.handle_rect()
    assert end.bottom() == pytest.approx(bar.height()) and end.top() > handle.top()
    sb.setValue((sb.minimum() + sb.maximum()) // 2)
    mid = bar.handle_rect()
    frac = (sb.value() - sb.minimum()) / (sb.maximum() - sb.minimum())
    assert mid.top() == pytest.approx((bar.height() - mid.height()) * frac)
    view.addItems([f"x{i}" for i in range(5000)])  # огромный список: ручка не короче минимума
    QApplication.processEvents()
    assert bar.handle_rect().height() == pytest.approx(theme.SCROLL_MIN_HANDLE)


def flat(widget: QWidget) -> QImage:
    """Снимок виджета на прозрачном фоне (grab() подложил бы фон окна)."""
    img = QImage(widget.size(), QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    widget.render(img, QPoint(), QRegion(), QWidget.RenderFlag.DrawChildren)
    return img


def send(widget, kind, pos: QPointF, button=Qt.MouseButton.LeftButton, buttons=Qt.MouseButton.LeftButton):
    QApplication.sendEvent(widget, QMouseEvent(kind, pos, QPointF(widget.mapToGlobal(pos.toPoint())), button, buttons,
                                               Qt.KeyboardModifier.NoModifier))


def test_dragging_the_handle_scrolls_the_view_both_ways(attached):
    _, view, bar = attached
    sb = view.verticalScrollBar()
    grab_at = QPointF(theme.SCROLL_HIT + 1, bar.handle_rect().center().y())
    send(bar, QEvent.Type.MouseButtonPress, grab_at)
    send(bar, QEvent.Type.MouseMove, QPointF(grab_at.x(), grab_at.y() + 100))
    moved = sb.value()
    assert moved > sb.minimum()
    handle = bar.handle_rect()
    free = bar.height() - handle.height()
    assert handle.top() == pytest.approx(free * (moved - sb.minimum()) / (sb.maximum() - sb.minimum()), abs=1.5)
    send(bar, QEvent.Type.MouseMove, QPointF(grab_at.x(), grab_at.y() + 5000), buttons=Qt.MouseButton.LeftButton)
    assert sb.value() == sb.maximum()  # за пределами дорожки — упирается в конец
    send(bar, QEvent.Type.MouseButtonRelease, grab_at, buttons=Qt.MouseButton.NoButton)
    sb.setValue(sb.minimum())  # обратно: колесо у области двигает и ручку
    assert bar.handle_rect().top() == 0


def test_click_on_track_pages_and_wheel_scrolls(attached):
    _, view, bar = attached
    sb = view.verticalScrollBar()
    below = QPointF(theme.SCROLL_HIT + 1, bar.height() - 5)
    send(bar, QEvent.Type.MouseButtonPress, below)
    send(bar, QEvent.Type.MouseButtonRelease, below, buttons=Qt.MouseButton.NoButton)
    assert sb.value() == min(sb.pageStep(), sb.maximum())  # на страницу вниз (у списка по строкам — не дальше конца)
    sb.setValue(sb.minimum())
    before = sb.value()
    wheel = QWheelEvent(QPointF(4, 50), QPointF(bar.mapToGlobal(QPoint(4, 50))), QPoint(0, 0), QPoint(0, -120),
                        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
    QApplication.sendEvent(bar, wheel)
    assert sb.value() > before


def test_scrollbar_paints_track_and_handle_colours(attached):
    _, _, bar = attached
    img = flat(bar)
    x = theme.SCROLL_HIT + 1
    handle, below = bar.handle_rect(), bar.height() - 10
    track = at(img, x, below)
    assert (track[0], track[1], track[2]) != (0, 0, 0) and track[3] == pytest.approx(255 * theme.SCROLL_TRACK[3], abs=3)
    assert at(img, x, handle.center().y())[:3] == rgb(theme.SCROLL_HANDLE) and at(img, x, handle.center().y())[3] == 255
    assert at(img, 0.5, handle.center().y())[3] == 0  # вне полосы (зона захвата) ничего не нарисовано
    bar._hover = True
    bar.update()
    assert at(flat(bar), x, handle.center().y())[:3] == rgb(theme.SCROLL_HANDLE_HOVER)


def test_scrollbar_survives_a_replaced_view_scrollbar(app):
    """Контейнер списка комбо подменяет полосу области; наша берёт актуальную и подписывается заново."""
    from PySide6.QtWidgets import QScrollBar
    view = make_view(80)
    host = QWidget()
    host.resize(200, 300)
    bar = ScreenScrollBar(view, host)
    view.setParent(host)
    view.setVerticalScrollBar(QScrollBar())
    bar.place(100, 0, 200)
    host.show()
    view.show()
    app.processEvents()
    assert bar.handle_rect().height() > 0
    view.verticalScrollBar().setValue(view.verticalScrollBar().maximum())
    assert bar.handle_rect().bottom() == pytest.approx(200)
    host.close()
