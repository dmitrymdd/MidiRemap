"""Подсказки: `tip()` экранирует и переносит; в живой подсказке Qt длинный текст держится в 290 px, короткий — в строку."""
import pytest

pytest.importorskip("PySide6")
pytestmark = pytest.mark.ui

from PySide6.QtCore import QCoreApplication, QEvent, QPoint
from PySide6.QtWidgets import QToolTip, QWidget

from remap.ui import theme
from remap.ui.tips import tip

LONG = ("Connects every free note to the target note with the same number. "
        "A quick start when both maps share a layout.\nCtrl+S saves.")


@pytest.fixture
def styled(app):
    theme.load_fonts()
    theme.install_app_font()
    app.setStyleSheet(theme.stylesheet())
    host = QWidget()
    host.resize(400, 200)
    host.show()
    yield host
    host.close()
    app.setStyleSheet("")


def _show(app, host, html):
    """Показывает подсказку и возвращает её метку (QTipLabel), прибрав предыдущую."""
    QToolTip.hideText()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    QToolTip.showText(host.mapToGlobal(QPoint(20, 20)), html, host)
    app.processEvents()
    labels = [w for w in app.topLevelWidgets() if w.metaObject().className() == "QTipLabel"]
    assert labels, "подсказка не показалась"
    return labels[0]


def test_tip_escapes_html_and_converts_line_breaks(app):
    theme.load_fonts()
    html = tip("a < b & c\nsecond line")
    assert "&lt;" in html and "&amp;" in html and "a < b" not in html
    assert html.count("<br>") == 1


def test_tip_title_is_a_bold_first_line(app):
    theme.load_fonts()
    html = tip("body", title="MATCH <BY> NUMBER")
    assert html.index("<b>MATCH &lt;BY&gt; NUMBER</b>") < html.index("body")


def test_short_tip_has_no_table_long_tip_has_fixed_width_table(app):
    theme.load_fonts()
    short, long = tip("Save profile (Ctrl+S)"), tip(LONG)
    assert "<table" not in short and "nowrap" in short
    assert f'<table width="{theme.TOOLTIP_TEXT_WIDTH}"' in long and "nowrap" not in long
    assert f'<table width="{theme.TOOLTIP_TEXT_WIDTH}"' in tip("x" * 120)  # одна длинная строка тоже переносится


def test_live_short_tip_stays_one_narrow_line(app, styled):
    label = _show(app, styled, tip("Save profile (Ctrl+S)"))
    assert label.height() < 45 and label.width() < theme.TOOLTIP_MAX_WIDTH


def test_live_long_tip_wraps_within_max_width(app, styled):
    label = _show(app, styled, tip(LONG, title="MATCH BY NUMBER"))
    assert label.width() == theme.TOOLTIP_MAX_WIDTH  # 266 колонка + поля и рамка = 290
    assert label.height() > 4 * 15  # заголовок, три строки абзаца и вторая строка
    plain = _show(app, styled, LONG)  # без tip() Qt растягивает подсказку сильно шире
    assert plain.width() > theme.TOOLTIP_MAX_WIDTH


def test_tooltip_uses_theme_font_colours_and_square_corners(app, styled):
    label = _show(app, styled, tip("Hello"))
    assert label.font().family() == theme.MONO_FAMILY
    img = label.grab().toImage()
    assert img.pixelColor(0, 0).name().upper() == theme.TOOLTIP_BORDER and img.pixelColor(0, 0).alpha() == 255  # без скругления
    inner = img.pixelColor(img.width() // 2, 4)
    assert inner.name().upper() == theme.TOOLTIP_BG
    assert "border-radius" not in theme.stylesheet().split("QToolTip")[1].split("}")[0]
