"""Клавиши: размеры и поля, раскладка шапки по координатам макета, состояния, кэш, фокус, значок-точка."""
import pytest

pytest.importorskip("PySide6")
pytestmark = pytest.mark.ui

from PySide6.QtCore import QPoint, QRectF, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from remap.ui import theme
from remap.ui.keys import (
    CLOSE, GO, HELP, MAP, PRESETS, SQUARE, SWAP, TAB, TUT, Key, key_column_spacing, key_margins, key_row_spacing,
    paint_key,
)
from remap.ui.metal import MetalBody


@pytest.fixture(autouse=True)
def fonts(app):
    theme.load_fonts()


def _face_origin(key: Key, window: QWidget) -> tuple[int, int]:
    p = key.mapTo(window, key.face_rect().topLeft().toPoint())
    return p.x(), p.y()


def _header(parent: QWidget) -> tuple[Key, list[Key]]:
    """Шапка макета 900×64: «?» и три вкладки у правого края (поле 40), отступ «?» от вкладок 16, между вкладками 8."""
    row = QWidget(parent)
    row.setGeometry(0, 0, 900, 64)
    ml = key_margins(TAB)
    lay = QHBoxLayout(row)
    lay.setContentsMargins(0, ml.bottom() - ml.top(), 40 - ml.right(), 0)  # лицо по центру: поля сверху и снизу разные
    lay.setSpacing(key_row_spacing(8))
    lay.addStretch(1)
    help_key = Key("?", spec=HELP)
    lay.addWidget(help_key)
    lay.addSpacing(16 - key_margins(HELP).right() - ml.left())
    tabs = [Key(text, icon, checkable=True) for text, icon in
            (("Convert", "tab-convert"), ("Profiles", "tab-profiles"), ("Maps", "tab-maps"))]
    for tab in tabs:
        lay.addWidget(tab)
    return help_key, tabs


# --- размеры и поля ---
@pytest.mark.parametrize("spec, size", [(TAB, (118, 36)), (HELP, (36, 36)), (SQUARE, (38, 38)), (SWAP, (44, 38)),
                                        (MAP, (48, 38)), (CLOSE, (34, 34)), (GO, (268, 68))])
def test_preset_face_sizes_match_mockup(app, spec, size):
    key = Key(spec=spec)
    assert (key.face_size().width(), key.face_size().height()) == size


def test_presets_are_listed_and_tut_follows_text(app):
    assert set(PRESETS) == {"tab", "help", "square", "swap", "map", "close", "tut", "go"}
    back, nxt = Key("Back", spec=TUT), Key("Next", spec=TUT)
    assert back.face_size().height() == 36
    assert back.face_size().width() > 2 * 16 + 2 and nxt.face_size().width() > 2 * 16 + 2  # поля 16 + рамка 1+1 + текст


def test_shadow_margins_follow_blur_and_offset(app):
    assert (key_margins(TAB).left(), key_margins(TAB).top(), key_margins(TAB).right(), key_margins(TAB).bottom()) \
        == (4, 2, 4, 6)
    m = key_margins(GO)  # 0 3px 6px
    assert (m.left(), m.top(), m.right(), m.bottom()) == (6, 3, 6, 9)


def test_size_hint_is_face_plus_margins(app):
    for spec in (TAB, GO, SQUARE):
        key = Key(spec=spec)
        m = key_margins(spec)
        assert key.sizeHint().width() == key.face_size().width() + m.left() + m.right()
        assert key.sizeHint().height() == key.face_size().height() + m.top() + m.bottom()
        assert key.minimumSizeHint() == key.sizeHint()
        f = key.face_rect()
        assert (f.x(), f.y()) == (m.left(), m.top())


def test_row_spacing_puts_faces_a_given_gap_apart(app):
    assert key_row_spacing(8) == 0 and key_row_spacing(16) == 8 and key_row_spacing(8, GO) == 8 - 12
    assert key_column_spacing(8) == 8 - 2 - 6  # нижнее поле верхней клавиши 6, верхнее нижней 2
    box = QWidget()
    lay = QHBoxLayout(box)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(key_row_spacing(12, TAB, SQUARE))
    a, b = Key("a", spec=TAB), Key(spec=SQUARE)
    lay.addWidget(a)
    lay.addWidget(b)
    box.resize(box.sizeHint())
    box.show()
    gap = _face_origin(b, box)[0] - (_face_origin(a, box)[0] + a.face_size().width())
    assert gap == 12
    col = QWidget()
    vlay = QVBoxLayout(col)
    vlay.setContentsMargins(0, 0, 0, 0)
    vlay.setSpacing(key_column_spacing(10))
    top, bottom = Key(spec=TAB), Key(spec=TAB)
    vlay.addWidget(top)
    vlay.addWidget(bottom)
    col.resize(col.sizeHint())
    col.show()
    assert _face_origin(bottom, col)[1] - (_face_origin(top, col)[1] + 36) == 10


def test_header_row_lands_faces_where_the_mockup_has_them(app):
    body = MetalBody()
    body.resize(900, 800)
    help_key, tabs = _header(body)
    body.show()
    app.processEvents()
    assert [_face_origin(t, body)[0] for t in tabs] == [490, 616, 742]  # 490..608, 616..734, 742..860
    assert [_face_origin(t, body)[0] + t.face_size().width() for t in tabs] == [608, 734, 860]
    assert {_face_origin(t, body)[1] for t in tabs} == {14} and _face_origin(help_key, body) == (438, 14)
    assert 14 + 36 + 14 == 64  # лицо по центру шапки высотой 64


# --- нажатие, включение, доступность ---
def test_click_toggle_and_signals(app):
    key = Key("Maps", "tab-maps", checkable=True)
    key.show()
    clicks, toggles = [], []
    key.clicked.connect(lambda: clicks.append(1))
    key.toggled.connect(toggles.append)
    centre = key.face_rect().center().toPoint()
    QTest.mouseClick(key, Qt.MouseButton.LeftButton, pos=centre)
    assert key.isChecked() and clicks == [1] and toggles == [True]
    assert key._state() == "pressed"
    QTest.mouseClick(key, Qt.MouseButton.LeftButton, pos=centre)
    assert not key.isChecked() and toggles == [True, False]


def test_press_shows_pressed_look_only_while_held(app):
    key = Key("Save", spec=TAB)
    key.show()
    centre = key.face_rect().center().toPoint()
    QTest.mousePress(key, Qt.MouseButton.LeftButton, pos=centre)
    assert key.isDown() and key._state() == "pressed"
    QTest.mouseRelease(key, Qt.MouseButton.LeftButton, pos=centre)
    assert not key.isDown() and key._state() != "pressed"


def test_shadow_margin_is_not_clickable(app):
    key = Key("x", spec=TAB)
    key.show()
    seen = []
    key.clicked.connect(lambda: seen.append(1))
    QTest.mouseClick(key, Qt.MouseButton.LeftButton, pos=QPoint(1, 1))  # угол поля с тенью
    assert seen == [] and not key.hitButton(QPoint(1, 1))
    QTest.mouseClick(key, Qt.MouseButton.LeftButton, pos=key.face_rect().center().toPoint())
    assert seen == [1] and key.hitButton(key.face_rect().center().toPoint())


def test_disabled_key_ignores_clicks_and_dims_content(app):
    key = Key("Maps", "tab-maps", checkable=True)
    key.show()
    key.setEnabled(False)
    QTest.mouseClick(key, Qt.MouseButton.LeftButton, pos=key.face_rect().center().toPoint())
    assert not key.isChecked() and key._content_color() == theme.KEY_LABEL_DISABLED and key._state() == "normal"


def test_content_colour_by_state(app):
    key = Key("Go", checkable=True)
    assert key._content_color() == theme.KEY_LABEL
    key.lit = True
    assert key._content_color() == theme.ACCENT
    key.lit = False
    key.setChecked(True)
    assert key._content_color() == theme.ACCENT and key._state() == "pressed"


def test_unknown_icon_is_rejected(app):
    with pytest.raises(ValueError):
        Key("x", "no-such-icon")
    key = Key("x")
    with pytest.raises(ValueError):
        key.set_icon("no-such-icon")
    key.set_icon("save")
    assert key.icon_name == "save"


# --- лицо клавиши: пиксели ---
def _paint(spec, state, dpr=1.0):
    m = key_margins(spec)
    face = QRectF(m.left(), m.top(), spec.w, spec.h)
    img = QImage(round((spec.w + m.left() + m.right()) * dpr), round((spec.h + m.top() + m.bottom()) * dpr),
                 QImage.Format.Format_ARGB32_Premultiplied)
    img.setDevicePixelRatio(dpr)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    paint_key(p, face, spec, state, dpr, QPoint(0, 0))
    p.end()
    return img, face


def test_face_has_border_gradient_inset_lines_and_shadow(app):
    img, face = _paint(TAB, "normal")
    cx, top, bottom = int(face.center().x()), int(face.top()), int(face.bottom())
    border = img.pixelColor(cx, top)
    assert (border.red(), border.green(), border.blue()) == (8, 9, 10) and border.alpha() == 255  # #08090A, 1 px
    assert img.pixelColor(cx, top + 1).red() > img.pixelColor(cx, top + 4).red()  # светлая inset-линия сверху
    assert img.pixelColor(cx, bottom - 2).red() < img.pixelColor(cx, bottom - 5).red()  # тёмная inset-линия снизу
    assert img.pixelColor(cx, top + 8).red() > img.pixelColor(cx, bottom - 8).red()  # градиент светлее сверху
    below = img.pixelColor(cx, bottom + 2)  # внешняя тень под клавишей
    assert below.alpha() > 40 and below.red() == 0
    assert img.pixelColor(0, 0).alpha() == 0  # угол поля — тени нет
    assert img.pixelColor(cx, top - 1).alpha() < img.pixelColor(cx, bottom + 1).alpha()  # сверху тень слабее, чем снизу


def test_pressed_face_is_darker_with_inner_shadow_and_light_line_below(app):
    normal, face = _paint(TAB, "normal")
    pressed, _ = _paint(TAB, "pressed")
    cx, top, bottom = int(face.center().x()), int(face.top()), int(face.bottom())
    assert pressed.pixelColor(cx, top + 10).red() < normal.pixelColor(cx, top + 10).red()
    assert pressed.pixelColor(cx, top + 2).red() < pressed.pixelColor(cx, top + 14).red()  # тень внутрь у верхнего края
    line = pressed.pixelColor(cx, bottom)  # первая строка под лицом: 0 1px 0 rgba(255,255,255,.06) под клавишей
    assert line.red() == 255 and line.alpha() == pytest.approx(0.06 * 255, abs=3)
    assert pressed.pixelColor(cx, bottom + 2).alpha() == 0  # внешней тени нет


def test_hover_face_is_lighter(app):
    normal, face = _paint(TAB, "normal")
    hover, _ = _paint(TAB, "hover")
    y = int(face.center().y())
    assert hover.pixelColor(int(face.center().x()), y).red() > normal.pixelColor(int(face.center().x()), y).red()


def test_go_key_has_its_own_radius_and_shadow(app):
    img, face = _paint(GO, "normal")
    m = key_margins(GO)
    assert (face.x(), face.y()) == (m.left(), m.top())
    corner = img.pixelColor(int(face.left()) + 1, int(face.top()) + 1)  # радиус 10: угол лица ещё не закрашен
    assert corner.alpha() < 255 or corner.red() < 20
    assert img.pixelColor(int(face.center().x()), int(face.bottom()) + 4).alpha() > 30  # тень 0 3px 6px
    assert img.pixelColor(int(face.center().x()), int(face.bottom()) - 1).red() < 20  # inset 0 -2px 0: тёмные 2 строки


@pytest.mark.parametrize("dpr", [1.0, 1.25, 2.0])
def test_face_paints_at_fractional_dpr(app, dpr):
    img, face = _paint(TAB, "normal", dpr)
    assert img.width() == round(126 * dpr) and img.height() == round(44 * dpr)
    centre = img.pixelColor(int(face.center().x() * dpr), int(face.center().y() * dpr))
    assert centre.alpha() == 255 and 20 < centre.red() < 60
    border_row = round(face.top() * dpr)  # верх лица привязан к сетке устройства: рамка занимает ровно эту строку
    assert img.pixelColor(int(face.center().x() * dpr), border_row).red() < 12
    inner_row = border_row + max(1, round(dpr))  # рамка 1 px; при DPR 2 — две строки устройства
    assert img.pixelColor(int(face.center().x() * dpr), inner_row).red() > 20  # ниже уже не рамка


def test_unknown_state_is_rejected(app):
    img = QImage(10, 10, QImage.Format.Format_ARGB32)
    p = QPainter(img)
    with pytest.raises(ValueError):
        paint_key(p, QRectF(0, 0, 10, 10), TAB, "bogus", 1.0, QPoint(0, 0))
    p.end()


# --- виджет: кэш, фокус, значок-точка ---
def test_faces_are_cached_until_size_or_position_change(app):
    body = MetalBody(screws=False)
    body.resize(300, 100)
    key = Key("Maps", "tab-maps", parent=body)
    key.move(20, 20)
    body.show()
    key.grab()
    first = key.rebuilds
    key.grab()
    key.update()
    key.grab()
    assert key.rebuilds == first  # то же состояние: лицо не пересобиралось
    key.move(40, 30)  # текстура привязана к окну: сдвиг — новая сборка
    key.grab()
    assert key.rebuilds == first + 1


def test_widget_paints_label_icon_and_texture(app):
    body = MetalBody(screws=False)
    body.resize(300, 100)
    key = Key("Maps", "tab-maps", parent=body)
    key.move(20, 20)
    body.show()
    img = key.grab().toImage()
    face = key.face_rect()
    inked = {img.pixelColor(x, int(face.center().y())).rgb() for x in range(int(face.left()) + 10, int(face.right()) - 10)}
    assert len(inked) > 8  # значок и текст поверх градиента: в строке много разных цветов
    key.setChecked(False)
    key.lit = True
    lit = key.grab().toImage()
    accent = theme.qcolor(theme.ACCENT)
    count = sum(1 for x in range(lit.width()) for y in range(lit.height())
                if abs(lit.pixelColor(x, y).green() - accent.green()) < 25 and lit.pixelColor(x, y).red() < 140
                and lit.pixelColor(x, y).green() > 150)
    assert count > 30  # подпись и значок — акцентом


def test_focus_ring_only_for_keyboard_focus(app):
    window = QWidget()
    lay = QHBoxLayout(window)
    a, b = Key("a"), Key("b")
    lay.addWidget(a)
    lay.addWidget(b)
    window.show()
    window.activateWindow()
    QTest.qWaitForWindowActive(window)
    ring_y = 0  # кольцо — в верхнем поле клавиши
    a.setFocus(Qt.FocusReason.MouseFocusReason)
    assert a.hasFocus() and not a._focus_visible
    before = a.grab().toImage()
    a.clearFocus()
    a.setFocus(Qt.FocusReason.TabFocusReason)
    assert a._focus_visible
    after = a.grab().toImage()
    x = int(a.face_rect().center().x())
    assert before.pixelColor(x, ring_y + 0) != after.pixelColor(x, ring_y + 0)
    ring = after.pixelColor(x, 0)
    assert abs(ring.green() - 0xC7) < 40 and ring.alpha() == 255  # контур #8FC7A3 вплотную к лицу в верхнем поле
    b.setFocus(Qt.FocusReason.TabFocusReason)
    assert not a._focus_visible

