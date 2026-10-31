"""Поля и флажок (`ui/field.py`): лицо «рамки» и плоского поля, статическое поле, поиск, флажок, помощники раскладки."""
import pytest

pytest.importorskip("PySide6")
pytestmark = pytest.mark.ui

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QRegion
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QHBoxLayout, QWidget

from remap.ui import text, theme
from remap.ui.field import (
    BezelField, FaceSlot, ScreenCheck, SearchField, field_height, field_margins, field_specs, paint_bezel, row_spacing,
)
from remap.ui.keys import SQUARE, Key


@pytest.fixture(autouse=True)
def fonts(app):
    theme.load_fonts()


def rgb(hex_color: str) -> tuple[int, int, int]:
    c = QColor(hex_color)
    return c.red(), c.green(), c.blue()


def bezel(kind="bezel", state="normal", dpr=1.0, w=200, h=45) -> QImage:
    img = QImage(round(w * dpr), round(h * dpr), QImage.Format.Format_ARGB32_Premultiplied)
    img.setDevicePixelRatio(dpr)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    m = field_margins(kind)
    face_h = theme.FIELD_HEIGHT if kind == "bezel" else theme.FIELD_SCREEN_HEIGHT
    paint_bezel(p, QRectF(m.left(), m.top(), w - m.left() - m.right(), face_h), dpr, kind, state)
    p.end()
    return img


def px(img: QImage, x: float, y: float) -> tuple[int, int, int, int]:
    d = img.devicePixelRatio()
    c = img.pixelColor(int(x * d), int(y * d))
    return c.red(), c.green(), c.blue(), c.alpha()


def near(a, b, tol=3) -> bool:
    return all(abs(x - y) <= tol for x, y in zip(a[:3], b[:3], strict=True))


def shown(widget: QWidget, app) -> QWidget:
    """Окно с виджетом, убранное от точки (0, 0), где в offscreen стоит курсор (иначе виджет «под мышью»)."""
    host = QWidget()
    widget.setParent(host)
    host.move(300, 300)
    host.resize(widget.size())
    host.show()
    app.processEvents()
    return host


def ink(img: QImage, box: QRectF, fg: str, bg_at: QPointF):
    """Чернила текста в логических px: порог — половина пути от цвета фона (в точке `bg_at`) до цвета текста."""
    d = img.devicePixelRatio()
    bg = img.pixelColor(int(bg_at.x() * d), int(bg_at.y() * d))
    f = QColor(fg)
    vec = (f.red() - bg.red(), f.green() - bg.green(), f.blue() - bg.blue())
    n2 = sum(v * v for v in vec) or 1
    xs, ys = [], []
    for x in range(int(box.left() * d), int(box.right() * d)):
        for y in range(int(box.top() * d), int(box.bottom() * d)):
            c = img.pixelColor(x, y)
            t = ((c.red() - bg.red()) * vec[0] + (c.green() - bg.green()) * vec[1] + (c.blue() - bg.blue()) * vec[2]) / n2
            if t > 0.5:
                xs.append(x)
                ys.append(y)
    return (min(xs) / d, min(ys) / d, (max(xs) + 1) / d, (max(ys) + 1) / d) if xs else None


# --- метрики ---
def test_field_margins_and_heights():
    m = field_margins("bezel")
    assert (m.left(), m.top(), m.right(), m.bottom()) == (3, 3, 3, 4)  # обод 3 px, снизу ещё светлая линия
    assert field_height("bezel") == 38 + 7 and field_height("screen") == 34
    assert not field_margins("screen").left()


# --- лицо «рамки» (числа макета: обод 3 px #07080A, светлая линия под ободом, рамка #2A4C38, градиент #11251B→#0D1C15) ---
@pytest.mark.parametrize("dpr", [1.0, 2.0])
def test_bezel_rim_border_gradient_and_light_line(dpr):
    img = bezel("bezel", dpr=dpr)
    top = 3  # верх лица
    assert px(img, 100, top - 2)[:3] == rgb(theme.FIELD_RIM)  # обод над лицом
    assert px(img, 1.5, top + 19)[:3] == rgb(theme.FIELD_RIM)  # и слева
    assert px(img, 100, top + 0.5)[:3] == rgb(theme.FIELD_BORDER)  # рамка 1 px
    light = px(img, 100, top + 38 + 3.5)  # линия под ободом: белый .09 (на прозрачном фоне — только альфа)
    assert light[3] == pytest.approx(255 * theme.FIELD_RIM_LIGHT[3], abs=4)
    assert near(px(img, 100, top + 36.5), rgb(theme.FIELD_BOTTOM), 4)  # низ градиента (inset-тени тут нет)
    assert px(img, 0.2, 0.2)[3] == 0  # снаружи обода — прозрачно


def test_bezel_inner_shadow_is_strongest_at_the_top_edge():
    img = bezel("bezel")
    rows = [px(img, 100, 3 + 1 + i)[1] for i in range(5)]  # зелёный канал сразу под рамкой вниз
    assert rows[0] < rows[1] < rows[2] < rows[3] and rows[0] < rows[3] - 6  # тень сверху вниз затухает


def test_bezel_states_change_only_the_border_and_focus_glow():
    normal, hover, focus = bezel("bezel", "normal"), bezel("bezel", "hover"), bezel("bezel", "focus")
    assert px(hover, 100, 3.5)[:3] == rgb(theme.FIELD_HOVER_BORDER)
    assert px(focus, 100, 3.5)[:3] == rgb(theme.FIELD_FOCUS_BORDER)
    assert px(focus, 100, 4.5)[1] > px(normal, 100, 4.5)[1] + 4  # внутренний контур 1 px под рамкой
    assert px(normal, 100, 1.5) == px(hover, 100, 1.5) == px(focus, 100, 1.5)  # обод во всех состояниях один
    with pytest.raises(ValueError):
        bezel("bezel", "pressed")
    with pytest.raises(ValueError):
        bezel("tall")


def test_screen_kind_is_flat_and_translucent():
    img = bezel("screen", h=34)
    assert px(img, 100, 0.5)[:3] == rgb(theme.FIELD_BORDER)
    fill = px(img, 100, 24)
    assert fill[:3] == (0, 0, 0) and fill[3] == pytest.approx(255 * theme.FIELD_SCREEN_BG[3], abs=4)  # rgba(0,0,0,.28)
    assert px(img, 100, 2)[3] > fill[3]  # тень внутри сверху темнее заливки
    assert px(img, 0.2, 0.2)[3] == 0  # обода и светлой линии нет, угол скруглён


def test_bezel_snaps_to_the_device_grid_at_dpr_125():
    """Рамка ровно в одну устройственную строку, обод над ней — чистого цвета (без размытия на соседние строки)."""
    img = bezel("bezel", dpr=1.25)
    rows = [img.pixelColor(125, r).getRgb()[:3] for r in range(12)]
    border_rows = [r for r, c in enumerate(rows) if c == rgb(theme.FIELD_BORDER)]
    assert len(border_rows) == 1
    assert rows[border_rows[0] - 1] == rgb(theme.FIELD_RIM)


# --- шрифты поля ---
def test_field_specs_follow_the_mockup_and_wdth():
    one, two = field_specs(False, theme.WDTH_BUTTON), field_specs(True, theme.WDTH_BUTTON)
    assert one.caption is None and (one.value.px, one.value.weight) == (12, QFont.Weight.Normal)
    assert (two.value.px, two.value.weight) == (12.5, QFont.Weight.Medium)
    assert (two.caption.px, two.caption.weight, two.caption.spacing) == (8.5, QFont.Weight.DemiBold, 0.16)
    assert two.value.wdth == two.caption.wdth == 100
    custom = field_specs(True, theme.WDTH_TEXT, 13, QFont.Weight.Medium)
    assert (custom.value.px, custom.value.wdth) == (13, 75)


# --- статическое поле ---
def test_static_field_paints_caption_and_value_as_in_the_mockup(app):
    """Div макета: wdth 75. Положение чернил — по эталону Maps@2x (подпись y 84–91, лицо поля с y 77)."""
    field = BezelField(caption="MY MAP", value="Superior Drummer 3 (copy)")
    field.setFixedWidth(476 + 6)
    assert (field.height(), field.margins().top(), field.margins().bottom()) == (45, 3, 4)
    host = shown(field, app)
    img = field.grab().toImage()
    face_top = field.face_rect().top()
    face = field.face_rect().adjusted(4, 3, -4, -3)  # только внутри лица: снаружи у grab() фон окна
    caption = ink(img, QRectF(face.left(), face_top + 3, face.width(), 14), theme.FIELD_CAPTION, QPointF(300, face_top + 5))
    value = ink(img, QRectF(face.left(), face_top + 18, face.width(), 16), theme.FIELD_TEXT, QPointF(300, face_top + 20))
    assert caption is not None and value is not None
    assert caption[1] - face_top == pytest.approx(84 - 77, abs=0.6) and caption[3] - face_top == pytest.approx(91 - 77, abs=0.6)
    assert caption[2] - caption[0] == pytest.approx(36.5, abs=0.6)  # «MY MAP», wdth 75
    assert value[2] - value[0] == pytest.approx(184, abs=0.6)  # «Superior Drummer 3 (copy)» 12.5/500, wdth 75
    host.close()


def test_static_field_face_cache_and_states(app):
    field = BezelField(caption="TARGET", value="Superior Drummer 3")
    field.resize(206, 45)
    host = shown(field, app)
    field.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, False)
    field.grab()
    base = field.rebuilds
    field.grab()
    assert field.rebuilds == base  # без изменений лицо не пересобирается
    field.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, True)
    field.grab()
    assert field.rebuilds == base + 1  # наведение — другое лицо
    field.grab()
    assert field.rebuilds == base + 1
    field.set_texts("EZdrummer 3")
    field.grab()
    assert field.rebuilds == base + 1  # смена текста лицо не трогает
    host.close()


def test_disabled_static_field_dims_its_text(app):
    field = BezelField(caption="TARGET", value="Superior Drummer 3")
    field.resize(206, 45)
    host = shown(field, app)
    field.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, False)
    face_top = field.face_rect().top()
    on = ink(field.grab().toImage(), QRectF(0, face_top + 18, 206, 18), theme.FIELD_TEXT, QPointF(190, face_top + 20))
    assert on is not None
    y = int(on[1] + 6)
    bright = max(field.grab().toImage().pixelColor(x, y).green() for x in range(10, 150))
    field.setEnabled(False)
    app.processEvents()
    dim = max(field.grab().toImage().pixelColor(x, y).green() for x in range(10, 150))
    assert bright > 200 and dim < 140  # 45 % непрозрачности
    host.close()


# --- поиск ---
def test_search_field_flat_kind_icon_and_input_font(app):
    search = SearchField("Search: name or note number")
    assert search.kind == "screen" and search.height() == 34 and not search.margins().left()
    assert search.edit.placeholderText() == "Search: name or note number"
    assert search.edit.font().pointSizeF() == pytest.approx(12 * 0.75)
    # это <input> макета: текст шире, чем в span (wdth 100, а не 75)
    ratio = text.text_width("Search", text.mono(12, wdth=theme.WDTH_BUTTON)) / text.text_width("Search", text.mono(12))
    assert ratio > 1.1
    seen = []
    search.textChanged.connect(seen.append)
    search.setText("snare")
    assert seen == ["snare"] and search.text() == "snare"


def test_search_field_focus_ring_follows_the_edit(app):
    search = SearchField("Search")
    host = QWidget()
    host.move(300, 300)
    lay = QHBoxLayout(host)
    lay.addWidget(search)
    host.resize(300, 60)
    host.show()
    host.activateWindow()
    QTest.qWaitForWindowActive(host)
    search.edit.clearFocus()  # окно при показе отдаёт фокус первому виджету
    app.processEvents()
    assert search._state() == "normal"
    search.edit.setFocus()
    app.processEvents()
    assert search._state() == "focus"
    search.edit.clearFocus()
    app.processEvents()
    assert search._state() == "normal"
    host.close()


# --- флажок ---
def test_check_box_toggles_by_click_on_square_and_label(app):
    check = ScreenCheck("NAMED ONLY")
    assert check.sizeHint().height() % 2 == 0
    assert check.sizeHint().width() == pytest.approx(theme.CHECK_PAD + 15 + 8 + text.text_width("NAMED ONLY", check._spec), abs=1)
    check.resize(check.sizeHint())
    host = shown(check, app)
    y = check.height() // 2
    QTest.mouseClick(check, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(int(check.box_rect().center().x()), y))
    assert check.isChecked()
    QTest.mouseClick(check, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(check.width() - 3, y))
    assert not check.isChecked()  # и по подписи
    host.close()


def test_check_box_square_sits_on_row_10_of_a_34_px_row_like_the_mockup(app):
    """В макете квадрат 15 px в строке 34 — со строки 10 (центр 9.5 браузер округляет вверх), а не с 9."""
    host = QWidget()
    host.move(300, 300)
    host.resize(200, 34)
    lay = QHBoxLayout(host)
    lay.setContentsMargins(0, 0, 0, 0)
    check = ScreenCheck("NAMED ONLY")
    lay.addWidget(check, 0, Qt.AlignmentFlag.AlignLeft)
    host.show()
    app.processEvents()
    check.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, False)
    assert check.geometry().y() + int(check.box_rect().top()) == 10
    img = host.grab().toImage()
    border = rgb(theme.CHECK_BORDER)
    col = [img.pixelColor(theme.CHECK_PAD + 7, y).getRgb()[:3] for y in range(34)]  # в строке 34 слева, с x = 0
    assert [y for y, c in enumerate(col) if c == border] == [10, 24]  # верхняя и нижняя рамка 15 px
    host.close()


def test_check_box_states_checked_hover_disabled(app):
    check = ScreenCheck("X")
    check.resize(check.sizeHint())
    host = shown(check, app)
    check.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, False)
    box = check.box_rect()
    edge = (int(box.left()), int(box.center().y()))

    def edge_color() -> tuple[int, int, int]:
        return check.grab().toImage().pixelColor(*edge).getRgb()[:3]

    assert edge_color() == rgb(theme.CHECK_BORDER)
    check.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, True)
    assert edge_color() == rgb(theme.CHECK_HOVER_BORDER)
    check.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, False)
    check.setChecked(True)
    assert edge_color() == rgb(theme.ACCENT)  # рамка акцентом
    img = check.grab().toImage()
    mark = [img.pixelColor(x, y).getRgb()[:3] for x in range(int(box.left()) + 3, int(box.right()) - 2)
            for y in range(int(box.top()) + 3, int(box.bottom()) - 2)]
    assert any(abs(c[1] - 214) < 30 and c[0] < 140 for c in mark)  # галочка акцентом
    check.setEnabled(False)
    flat = QImage(check.size(), QImage.Format.Format_ARGB32_Premultiplied)
    flat.fill(Qt.GlobalColor.transparent)
    check.render(flat, QPoint(), QRegion(), QWidget.RenderFlag.DrawChildren)
    assert 255 * 0.4 < flat.pixelColor(*edge).alpha() < 255 * 0.6  # приглушён: рамка на 45 % плюс заливка под ней
    host.close()


def test_check_box_focus_ring_only_from_keyboard_and_inside_the_widget(app):
    host = QWidget()
    host.move(300, 300)
    host.resize(160, 40)
    check = ScreenCheck("OK", host)
    check.move(0, 10)
    host.show()
    host.activateWindow()
    QTest.qWaitForWindowActive(host)
    check.setFocus(Qt.FocusReason.MouseFocusReason)
    app.processEvents()
    assert not check._focus_visible
    check.clearFocus()
    check.setFocus(Qt.FocusReason.TabFocusReason)
    app.processEvents()
    assert check._focus_visible
    img = check.grab().toImage()
    ring = rgb(theme.KEY_FOCUS_RING)
    left_col = [img.pixelColor(0, y).getRgb()[:3] for y in range(check.height())]
    assert any(sum(abs(a - b) for a, b in zip(c, ring, strict=True)) < 60 for c in left_col)  # кольцо не обрезано краем
    host.close()


# --- раскладка: поля под тень и обод ---
def test_row_spacing_gives_face_to_face_gaps(app):
    a, b = BezelField(), Key(icon="save", spec=SQUARE)
    assert row_spacing(8, a, b) == 8 - 3 - 4  # 1 px: поле (справа 3) и клавиша (слева 4)
    assert row_spacing(8, b, b) == 0  # клавиши: 4 + 4
    assert row_spacing(54, b, a) == 54 - 4 - 3


@pytest.mark.parametrize("make", [lambda: BezelField(), lambda: Key(icon="save", spec=SQUARE)], ids=["field", "key"])
def test_face_slot_centres_the_face_not_the_widget(app, make):
    widget = make()
    if isinstance(widget, BezelField):
        widget.setFixedWidth(120)
    host = QWidget()
    host.move(300, 300)
    lay = QHBoxLayout(host)
    lay.setContentsMargins(0, 0, 0, 0)
    slot = FaceSlot(widget, 52)
    lay.addWidget(slot)
    host.resize(200, 52)
    host.show()
    app.processEvents()
    face = widget.face_rect()
    top = widget.mapTo(host, QPoint(0, 0)).y() + face.top()
    assert top == (52 - face.height()) / 2 == 7  # у обеих лицо 38 px: верх лица на 7, как в макете
    assert slot.height() == 52
    host.close()
