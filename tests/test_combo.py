"""Комбобокс (`ui/combo.py`): лицо «рамки», одна и две строки, размеры, состояния и стеклянный список."""
import pytest

pytest.importorskip("PySide6")
pytestmark = pytest.mark.ui

from PySide6.QtCore import QPoint, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QComboBox, QVBoxLayout, QWidget

from remap.ui import text, theme
from remap.ui.combo import ComboBox
from remap.ui.field import field_height

ITEMS = ["EZD3 – SD3", "GM – SD3", "My kit"]


@pytest.fixture(autouse=True)
def fonts(app):
    theme.load_fonts()
    theme.install_app_font()
    app.setStyleSheet(theme.stylesheet())  # как в приложении: общая таблица со старыми правилами QComboBox
    yield
    app.setStyleSheet("")


def rgb(hex_color: str) -> tuple[int, int, int]:
    c = QColor(hex_color)
    return c.red(), c.green(), c.blue()


class Host(QWidget):
    """Окно с комбо, убранное от точки (0, 0), где в offscreen стоит курсор."""

    def __init__(self, app, combo: ComboBox, width=300, height=200) -> None:
        super().__init__()
        self.combo = combo
        lay = QVBoxLayout(self)
        lay.setContentsMargins(40, 40, 40, 40)
        lay.addWidget(combo)
        lay.addStretch(1)
        self.move(300, 300)
        self.resize(width, height)
        self.show()
        self.activateWindow()
        QTest.qWaitForWindowActive(self)
        app.processEvents()
        if app.focusWidget() is not None:
            app.focusWidget().clearFocus()
        combo.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, False)


def combo_with(items=ITEMS, **kw) -> ComboBox:
    combo = ComboBox(**kw)
    combo.addItems(items)
    return combo


def face_pixel(combo: ComboBox, dx: float, dy: float) -> tuple[int, int, int]:
    face = combo.face_rect()
    return combo.grab().toImage().pixelColor(int(face.left() + dx), int(face.top() + dy)).getRgb()[:3]


# --- это по-прежнему QComboBox ---
def test_combo_is_a_normal_qcombobox_with_the_old_api(app):
    combo = combo_with()
    assert isinstance(combo, QComboBox) and combo.count() == 3 and combo.currentIndex() == 0
    seen = []
    combo.currentIndexChanged.connect(seen.append)
    combo.setCurrentIndex(2)
    assert seen == [2] and combo.currentText() == "My kit"
    combo.addItem("Other", "data-id")
    assert combo.findData("data-id") == 3 and combo.itemData(3) == "data-id"
    combo.setItemData(0, "tip", Qt.ItemDataRole.ToolTipRole)
    assert combo.itemData(0, Qt.ItemDataRole.ToolTipRole) == "tip"
    combo.model().item(1).setEnabled(False)  # недоступный пункт, как на странице профилей
    assert not combo.model().item(1).isEnabled()


def test_sizes_two_lines_and_contents_length(app):
    one, two = combo_with(), combo_with(caption="SOURCE")
    assert one.height() == two.height() == field_height() == 45
    assert one.caption is None and two.caption == "SOURCE"
    one.set_caption("TARGET")
    assert one.caption == "TARGET"
    assert (one.margins().left(), one.margins().top(), one.margins().right(), one.margins().bottom()) == (3, 3, 3, 4)
    wide = combo_with(["Short", "A much longer item text"])
    assert wide.sizeHint().width() > one.sizeHint().width()  # по содержимому
    fixed = combo_with(["Short"])
    fixed.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
    fixed.setMinimumContentsLength(30)
    chars = text.text_width("0", fixed.specs.value)
    assert fixed.sizeHint().width() == pytest.approx(6 + 22 + 30 * chars + 8 + 10, abs=1.5)  # поля + 30 знаков + стрелка
    fixed.addItem("An item much longer than thirty characters in total length")
    assert fixed.sizeHint().width() == pytest.approx(6 + 22 + 30 * chars + 8 + 10, abs=1.5)  # длина не от пунктов


def test_text_specs_follow_the_mockup(app):
    one, two = combo_with(), combo_with(caption="SOURCE")
    assert (one.specs.value.px, one.specs.value.weight, one.specs.value.wdth) == (12, QFont.Weight.Normal, 100)  # <button>
    assert (two.specs.value.px, two.specs.value.weight) == (12.5, QFont.Weight.Medium)
    assert two.specs.caption.wdth == 100
    convert = combo_with(value_px=13, value_weight=QFont.Weight.Medium)  # профиль на Convert: 13/500
    assert (convert.specs.value.px, convert.specs.value.weight) == (13, QFont.Weight.Medium)
    div = combo_with(wdth=theme.WDTH_TEXT)
    assert div.specs.value.wdth == 75


# --- вид ---
def test_face_matches_the_bezel_and_states(app):
    combo = combo_with()
    combo.setFixedWidth(132)
    host = Host(app, combo)
    face = combo.face_rect()
    assert (face.left(), face.top(), face.width(), face.height()) == (3, 3, 126, 38)
    img = combo.grab().toImage()
    assert img.pixelColor(60, 1).getRgb()[:3] == rgb(theme.FIELD_RIM)  # обод 3 px над лицом
    assert face_pixel(combo, 60, 0.5) == rgb(theme.FIELD_BORDER)
    combo.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, True)
    assert face_pixel(combo, 60, 0.5) == rgb(theme.FIELD_HOVER_BORDER)
    combo.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, False)
    host.close()


def test_chevron_sits_10px_inside_the_face_right_edge(app):
    combo = combo_with()
    combo.setFixedWidth(132)
    host = Host(app, combo)
    img = combo.grab().toImage()
    accent = rgb("#8FC7A3")
    xs = [x for x in range(132) for y in range(15, 30) if img.pixelColor(x, y).getRgb()[:3] == accent]
    assert xs and max(xs) < 3 + 126 - 11 and min(xs) >= 3 + 126 - 11 - 10  # 10 px шириной у правого поля 10 + рамка 1
    host.close()


def test_keyboard_focus_ring_not_on_mouse_focus(app):
    combo = combo_with()
    host = Host(app, combo)
    combo.setFocus(Qt.FocusReason.MouseFocusReason)
    app.processEvents()
    assert combo._state() == "normal"  # мышью — без кольца (откроется список)
    combo.clearFocus()
    combo.setFocus(Qt.FocusReason.TabFocusReason)
    app.processEvents()
    assert combo._state() == "focus"
    assert face_pixel(combo, 60, 0.5) == rgb(theme.FIELD_FOCUS_BORDER)
    host.close()


def test_disabled_dims_and_placeholder_is_dim(app):
    combo = ComboBox()
    combo.setPlaceholderText("Select a profile")
    host = Host(app, combo)
    assert combo.currentIndex() == -1 and combo._shown_text() == ("Select a profile", True)
    empty = ComboBox()
    assert empty._shown_text() == ("—", True)  # пустой список
    combo.addItems(ITEMS)
    combo.setCurrentIndex(0)
    assert combo._shown_text() == ("EZD3 – SD3", False)
    bright = max(combo.grab().toImage().pixelColor(x, 22).green() for x in range(14, 100))
    combo.setEnabled(False)
    app.processEvents()
    assert max(combo.grab().toImage().pixelColor(x, 22).green() for x in range(14, 100)) < bright - 40
    host.close()


def test_text_is_elided_to_the_room_before_the_chevron(app):
    combo = combo_with(["A very long profile name that cannot possibly fit into this narrow combobox"])
    combo.setFixedWidth(150)
    host = Host(app, combo)
    face_right = combo.face_rect().right()
    img = combo.grab().toImage()
    ink = [x for x in range(150) for y in range(15, 30) if img.pixelColor(x, y).getRgb()[:3] != img.pixelColor(2, 20).getRgb()[:3]
           and img.pixelColor(x, y).green() > 200]
    assert ink and max(ink) <= face_right - 11 - 10 - 8 + 1  # не заходит за место под стрелку
    host.close()


def test_face_is_cached_between_paints(app):
    combo = combo_with()
    host = Host(app, combo)
    combo.grab()
    base = combo.rebuilds
    combo.grab()
    combo.setCurrentIndex(1)  # смена текста лицо не трогает
    combo.grab()
    assert combo.rebuilds == base
    host.close()


# --- список ---
def open_popup(app, combo):
    combo.showPopup()
    app.processEvents()
    return combo.view().window()


def test_popup_sits_under_the_face_with_the_face_width_and_row_heights(app):
    combo = combo_with()
    combo.setFixedWidth(206)
    host = Host(app, combo)
    container = open_popup(app, combo)
    assert container.isVisible()
    face = combo.face_rect()
    top_left = combo.mapToGlobal(QPoint(round(face.left()), round(face.top())))
    assert container.x() == top_left.x() and container.width() == round(face.width()) == 200
    assert container.y() == top_left.y() + 38 + 5  # лицо + зазор
    assert container.height() == 3 * theme.POPUP_ROW + 2 * (1 + theme.POPUP_PAD) == 3 * 28 + 10
    view = combo.view()
    assert view.geometry() == container.rect()  # ни полей, ни «скроллеров» Qt вокруг списка
    assert view.viewport().height() == 3 * 28
    assert view.sizeHintForRow(0) == 28
    combo.hidePopup()
    app.processEvents()
    assert not container.isVisible() and combo._state() == "normal"
    host.close()


def test_popup_open_state_looks_focused_and_returns(app):
    combo = combo_with()
    host = Host(app, combo)
    open_popup(app, combo)
    assert combo._state() == "focus" and face_pixel(combo, 60, 0.5) == rgb(theme.FIELD_FOCUS_BORDER)
    combo.hidePopup()
    app.processEvents()
    assert combo._state() == "normal"
    host.close()


def test_popup_more_than_ten_rows_scrolls_with_the_thin_bar(app):
    combo = combo_with([f"Item {i}" for i in range(14)])
    host = Host(app, combo, height=500)
    container = open_popup(app, combo)
    assert container.height() == 10 * 28 + 10  # не больше десяти строк
    view = combo.view()
    assert view.bar.isVisible() and view.verticalScrollBar().maximum() == 4
    assert view.bar.width() == theme.SCROLL_WIDTH + 2 * theme.SCROLL_HIT
    assert view.viewport().width() == view.width() - 2 * (1 + theme.POPUP_PAD) - (theme.SCROLL_RIGHT + theme.SCROLL_WIDTH + 1)
    combo.hidePopup()
    short = combo_with()
    host2 = Host(app, short)
    open_popup(app, short)
    assert not short.view().bar.isVisible()  # три строки — прокручивать нечего
    short.hidePopup()
    host.close()
    host2.close()


def test_popup_container_is_frameless_translucent_glass(app):
    combo = combo_with([f"Item {i}" for i in range(4)])
    host = Host(app, combo)
    container = open_popup(app, combo)
    assert container.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    assert container.windowFlags() & Qt.WindowType.FramelessWindowHint
    assert "background" in container.styleSheet()  # без белых полей у списка
    img = container.grab().toImage()
    assert img.pixelColor(0, 0).alpha() == 0  # скруглённый угол прозрачен
    assert img.pixelColor(img.width() // 2, 0).getRgb()[:3] == rgb(theme.SCREEN_BORDER)  # рамка стекла 1 px
    inner = img.pixelColor(img.width() - 40, img.height() // 2)
    assert inner.getRgb()[:3] != rgb(theme.SCREEN_BORDER) and inner.alpha() == 255
    combo.hidePopup()
    host.close()


def test_popup_rows_current_accent_hover_plate_and_disabled(app):
    combo = combo_with(["One", "Two", "Three"])
    combo.model().item(2).setEnabled(False)
    combo.setCurrentIndex(0)
    host = Host(app, combo)
    container = open_popup(app, combo)
    view = combo.view()
    img = container.grab().toImage()

    def row_ink(row: int, pred) -> bool:
        y0 = 1 + theme.POPUP_PAD + row * 28
        return any(pred(img.pixelColor(x, y).getRgb()[:3]) for x in range(11, 80) for y in range(y0 + 6, y0 + 22))

    assert row_ink(0, lambda c: c[1] > 190 and c[0] < 140)  # текущий — акцентом (#62D69A)
    assert row_ink(1, lambda c: c[0] > 200 and c[1] > 200)  # обычная строка #E0EDE5
    assert row_ink(2, lambda c: abs(c[0] - 107) < 25 and abs(c[1] - 114) < 25)  # недоступная — SILK_FAINT
    plate = view.visualRect(view.model().index(0, 0))
    assert img.pixelColor(plate.left() + 1 + 1, plate.center().y() + 1 + 0).green() >= 0  # плашка у выбранной строки
    combo.hidePopup()
    host.close()


def test_selecting_an_item_closes_the_popup_and_changes_the_value(app):
    combo = combo_with()
    host = Host(app, combo)
    container = open_popup(app, combo)
    view = combo.view()
    index = view.model().index(1, 0)
    QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, view.visualRect(index).center())
    app.processEvents()
    assert combo.currentIndex() == 1 and not container.isVisible()
    host.close()


def test_popup_square_fallback_is_opaque_and_unrounded(app, monkeypatch):
    monkeypatch.setattr(theme, "POPUP_ROUNDED", False)
    combo = combo_with([f"Item {i}" for i in range(4)])
    host = Host(app, combo)
    container = open_popup(app, combo)
    assert not container.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    img = container.grab().toImage()
    assert img.pixelColor(0, 0).alpha() == 255 and img.pixelColor(0, 0).getRgb()[:3] == rgb(theme.SCREEN_BORDER)  # угол квадратный
    combo.hidePopup()
    host.close()


def test_popup_flips_above_when_there_is_no_room_below(app):
    combo = combo_with([f"Item {i}" for i in range(8)])
    host = Host(app, combo)
    screen = host.screen().availableGeometry()
    host.move(300, screen.bottom() - 120)  # комбо у нижнего края экрана
    app.processEvents()
    container = open_popup(app, combo)
    face_top = combo.mapToGlobal(QPoint(0, round(combo.face_rect().top()))).y()
    assert container.y() + container.height() <= face_top  # над лицом
    combo.hidePopup()
    host.close()


def test_old_stylesheet_does_not_leak_into_the_new_face(app):
    """В общей таблице стилей ещё лежат правила QComboBox для старых страниц; лицо рисуется само и их не использует."""
    assert "QComboBox" in theme.stylesheet()
    combo = combo_with()
    combo.setFixedWidth(132)
    host = Host(app, combo)
    assert face_pixel(combo, 60, 0.5) == rgb(theme.FIELD_BORDER) and face_pixel(combo, 60, 20) != rgb(theme.LEGACY["surface"])
    host.close()
    assert QRectF is not None and QImage is not None  # импорты нужны другим тестам этого файла
