"""Текст, который рисуем сами (`ui/text.py`): дробные размеры без округления; ширины совпадают с эталоном макета."""
import pytest

pytest.importorskip("PySide6")
pytestmark = pytest.mark.ui

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter

from remap.ui import text, theme

W = QFont.Weight
BG, FG = "#0D1C15", "#E6F2EA"


@pytest.fixture(autouse=True)
def fonts(app):
    theme.load_fonts()


def render(txt: str, spec: text.TextSpec, dpr: float = 2.0, elide: Qt.TextElideMode | None = None,
           box: float = 380, align: Qt.AlignmentFlag = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter) -> QImage:
    img = QImage(int(420 * dpr), int(50 * dpr), QImage.Format.Format_ARGB32_Premultiplied)
    img.setDevicePixelRatio(dpr)
    img.fill(QColor(BG))
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    text.draw_text(p, QRectF(10, 0, box, 50), txt, spec, FG, align, elide)
    p.end()
    return img


def ink(img: QImage) -> tuple[float, float, float, float]:
    """Чернила текста в логических px: пиксели, где цвет прошёл больше половины пути от фона к цвету текста."""
    dpr = img.devicePixelRatio()
    bg, fg = QColor(BG), QColor(FG)
    d = (fg.red() - bg.red(), fg.green() - bg.green(), fg.blue() - bg.blue())
    n2 = sum(v * v for v in d)
    xs, ys = [], []
    for x in range(img.width()):
        for y in range(img.height()):
            c = img.pixelColor(x, y)
            t = ((c.red() - bg.red()) * d[0] + (c.green() - bg.green()) * d[1] + (c.blue() - bg.blue()) * d[2]) / n2
            if t > 0.5:
                xs.append(x)
                ys.append(y)
    assert xs, "текст не нарисован"
    return min(xs) / dpr, min(ys) / dpr, (max(xs) + 1) / dpr, (max(ys) + 1) / dpr


def ink_width(txt: str, spec: text.TextSpec) -> float:
    left, _, right, _ = ink(render(txt, spec))
    return right - left


# Ширины чернил в эталоне макета (`Profiles@2x.png`, `Maps@2x.png`, `Convert@2x.png`), логические px; измерены тем же
# способом (порог — половина пути от фона до цвета текста). Допуск ±0.5 px.
REFERENCE = [
    ("PROFILES", text.label(13.5, W.DemiBold, 0.12), 55.0),  # подпись вкладки: Barlow 13.5 / 600 / .12em
    ("EZD3 – SD3", text.mono(12, W.Normal, wdth=theme.WDTH_BUTTON), 81.5),  # значение комбо-кнопки: wdth 100
    ("SOURCE", text.mono(8.5, W.DemiBold, 0.16, theme.WDTH_BUTTON), 41.5),  # подпись внутри <button>: wdth 100
    ("Superior Drummer 3", text.mono(12.5, W.Medium, wdth=theme.WDTH_BUTTON), 155.5),
    ("MATCH BY NUMBER", text.mono(9, W.Medium, 0.04, theme.WDTH_BUTTON), 98.5),
    ("CLEAR ALL", text.mono(9, W.Medium, 0.04, theme.WDTH_BUTTON), 58.5),
    ("Search: name or note number", text.mono(12, W.Normal, wdth=theme.WDTH_BUTTON), 225.0),  # <input>: wdth 100
    ("UNASSIGNED", text.mono(11, W.DemiBold, 0.08), 73.0),  # span: wdth 75
    ("MY MAP", text.mono(8.5, W.DemiBold, 0.16), 36.5),  # подпись в div: wdth 75
    ("Superior Drummer 3 (copy)", text.mono(12.5, W.Medium), 184.0),
    ("NAMED ONLY", text.mono(10, W.DemiBold, 0.1), 68.0),
]


@pytest.mark.parametrize(("txt", "spec", "expected"), REFERENCE, ids=[r[0] for r in REFERENCE])
def test_ink_width_matches_mockup_reference(txt, spec, expected):
    assert ink_width(txt, spec) == pytest.approx(expected, abs=0.5)


def test_width_scales_linearly_with_fractional_px():
    """Qt сам округлял бы 13.5 → 14 px; через масштаб ширина строго пропорциональна размеру."""
    a, b = text.text_width("PROFILES", text.label(12, spacing=0.12)), text.text_width("PROFILES", text.label(13.5, spacing=0.12))
    assert b == pytest.approx(a * 13.5 / 12, rel=1e-9)
    m12, m125 = text.text_width("Mono", text.mono(12)), text.text_width("Mono", text.mono(12.5))
    assert m125 == pytest.approx(m12 * 12.5 / 12, rel=1e-9)


def test_wdth_button_is_wider_than_text_and_both_constants_are_named():
    assert (theme.WDTH_TEXT, theme.WDTH_BUTTON) == (75.0, 100.0)
    narrow, wide = text.text_width("EZD3 – SD3", text.mono(12)), text.text_width("EZD3 – SD3", text.mono(12, wdth=100))
    assert wide > narrow + 10  # 69.5 → 81.5 px: ось даёт не линейный рост


def test_drawn_width_equals_text_width():
    spec = text.label(13.5, spacing=0.12)
    left, _, right, _ = ink(render("PROFILES", spec))
    assert right - left == pytest.approx(text.text_width("PROFILES", spec), abs=3.0)  # advance больше чернил на интервал после последней буквы и боковые поля глифов


def test_dpr_does_not_change_layout():
    spec = text.mono(12.5, W.Medium, wdth=theme.WDTH_BUTTON)
    widths = []
    for dpr in (1.0, 1.25, 2.0):
        left, _, right, _ = ink(render("Superior Drummer 3", spec, dpr))
        widths.append(right - left)
    assert max(widths) - min(widths) < 1.0


def test_alignment_left_center_right_and_vertical():
    spec = text.mono(12)
    left, top, _, bottom = ink(render("MMMM", spec, align=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter))
    assert left == pytest.approx(10, abs=1.5)
    assert 20 < (top + bottom) / 2 < 30  # по центру высоты 50
    c0, _, c1, _ = ink(render("MMMM", spec, align=Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter))
    assert (c0 + c1) / 2 == pytest.approx(10 + 190, abs=2.5)
    _, _, r1, _ = ink(render("MMMM", spec, align=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter))
    assert r1 == pytest.approx(10 + 380, abs=2.5)
    _, t0, _, _ = ink(render("MMMM", spec, align=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop))
    assert t0 < 5


def test_elision_uses_scaled_metrics_and_never_overflows():
    spec = text.mono(12.5, W.Medium, wdth=theme.WDTH_BUTTON)
    full = "Superior Drummer 3 (copy) with a very long tail"
    cut = text.elide(full, spec, 120)
    assert cut.endswith("…") and text.text_width(cut, spec) <= 120
    assert text.text_width(cut[:-1] + "M…", spec) > 120 or len(cut) == len(full)  # букву больше уже не влезло бы
    assert text.elide("short", spec, 120) == "short"
    img = render(full, spec, elide=Qt.TextElideMode.ElideRight, box=120)
    left, _, right, _ = ink(img)
    assert right - left <= 120.5


def test_empty_text_draws_nothing_and_label_is_uppercase():
    img = render("", text.mono(12))
    assert img.pixelColor(100, 50) == QColor(BG)
    assert text.text_width("maps", text.label(13.5)) == pytest.approx(text.text_width("MAPS", text.label(13.5)))
