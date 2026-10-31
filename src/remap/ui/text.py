"""Текст, который рисуем сами (клавиши, поля, комбо): дробные размеры без округления до целого px.

Движок шрифтов Qt округляет размер до целого px (13.5 → 14, 12.5 → 13), а браузер, по которому нарисован макет, считает
размер линейно, так что текст в Qt выходил на 3–5 % шире. Поэтому шрифт берётся один раз крупным (`BASE_PX` = 100 px,
округлять нечего), а в нужный размер текст приводится `painter.scale(px / BASE_PX)`. Ширины и обрезание «…» считаются
по тем же метрикам, пересчитанным в логические px. Текст QLabel/QSS остаётся целым — это старые страницы.
"""

from dataclasses import dataclass
from functools import cache
from math import floor

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter

from . import theme

BASE_PX = 100  # размер шрифта, на котором считаются метрики и рисуются глифы


@dataclass(frozen=True)
class TextSpec:
    """Вид текста: семейство (`"mono"` / `"label"`), размер в px (дробный допустим), насыщенность, межбуквенный
    интервал в em, ширина `wdth` (только Martian Mono; `theme.WDTH_TEXT` у span/div макета, `theme.WDTH_BUTTON` у текста
    внутри `<button>` и `<input>`)."""

    kind: str
    px: float
    weight: QFont.Weight = QFont.Weight.Normal
    spacing: float = 0.0
    wdth: float = theme.WDTH_TEXT


def mono(px: float, weight: QFont.Weight = QFont.Weight.Normal, spacing: float = 0.0,
         wdth: float = theme.WDTH_TEXT) -> TextSpec:
    return TextSpec("mono", px, weight, spacing, wdth)


def label(px: float, weight: QFont.Weight = QFont.Weight.DemiBold, spacing: float = theme.LABEL_SPACING) -> TextSpec:
    """Barlow Condensed, заглавные; `spacing` — в em."""
    return TextSpec("label", px, weight, spacing)


@cache
def _base_font(kind: str, family: str, weight: QFont.Weight, spacing: float, wdth: float) -> QFont:
    """Шрифт размером BASE_PX; `family` — часть ключа кэша: имена семейств выставляет `theme.load_fonts()`."""
    if kind == "label":
        return theme.label_font(BASE_PX, weight, spacing)
    font = theme.mono_font(BASE_PX, weight, wdth)
    font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, BASE_PX * spacing)
    return font


def base_font(spec: TextSpec) -> QFont:
    family = theme.LABEL_FAMILY if spec.kind == "label" else theme.MONO_FAMILY
    return _base_font(spec.kind, family, spec.weight, spec.spacing, spec.wdth)


def _metrics(spec: TextSpec) -> QFontMetricsF:
    return QFontMetricsF(base_font(spec))


def _scale(spec: TextSpec) -> float:
    return spec.px / BASE_PX


def text_width(text: str, spec: TextSpec) -> float:
    """Ширина текста в логических px (с межбуквенным интервалом после каждой буквы, как у CSS)."""
    if spec.kind == "label":
        text = text.upper()
    return _metrics(spec).horizontalAdvance(text) * _scale(spec)


def ascent_descent(spec: TextSpec) -> tuple[float, float]:
    """Подъём и спуск шрифта в логических px, округлённые до целых, как в браузере (Blink округляет метрики шрифта, и
    высота строки `line-height: normal` — сумма округлённых): от этого зависит положение строк в двухстрочных полях."""
    m = _metrics(spec)
    k = _scale(spec)
    return float(floor(m.ascent() * k + 0.5)), float(floor(m.descent() * k + 0.5))


def line_height(spec: TextSpec) -> float:
    a, d = ascent_descent(spec)
    return a + d


def elide(text: str, spec: TextSpec, width: float, mode: Qt.TextElideMode = Qt.TextElideMode.ElideRight) -> str:
    """Обрезает текст с «…» по метрикам крупного шрифта; ширина — в логических px."""
    if spec.kind == "label":
        text = text.upper()
    return _metrics(spec).elidedText(text, mode, width / _scale(spec))


def draw_text(p: QPainter, rect: QRectF, text: str, spec: TextSpec, color: str | QColor,
              align: Qt.AlignmentFlag = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
              elide_mode: Qt.TextElideMode | None = None) -> None:
    """Рисует одну строку в `rect`. По вертикали Center — середина строки (подъём − спуск) / 2 на середине `rect`, Top —
    верх строки у верха, Bottom — низ строки у низа. `elide_mode` — обрезать «…», если текст шире `rect`."""
    if not text:
        return
    if spec.kind == "label":
        text = text.upper()
    if elide_mode is not None:
        text = elide(text, spec, rect.width(), elide_mode)
    width = text_width(text, spec)
    ascent, descent = ascent_descent(spec)
    if align & Qt.AlignmentFlag.AlignRight:
        x = rect.right() - width
    elif align & Qt.AlignmentFlag.AlignHCenter:
        x = rect.center().x() - width / 2
    else:
        x = rect.left()
    if align & Qt.AlignmentFlag.AlignTop:
        baseline = rect.top() + ascent
    elif align & Qt.AlignmentFlag.AlignBottom:
        baseline = rect.bottom() - descent
    else:
        baseline = rect.center().y() + (ascent - descent) / 2
    p.save()
    p.setFont(base_font(spec))
    p.setPen(QColor(color))
    p.translate(QPointF(x, baseline))
    p.scale(_scale(spec), _scale(spec))
    p.drawText(QPointF(0, 0), text)
    p.restore()
