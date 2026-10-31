"""Текст, который рисуем сами (клавиши, поля, комбо): дробные размеры без округления до целого px.

Движок шрифтов Qt округляет размер до целого px (13.5 → 14, 12.5 → 13), а браузер, по которому нарисован макет, считает
размер линейно, так что текст в Qt выходил на 3–5 % шире. Поэтому шрифт берётся один раз крупным (`BASE_PX` = 100 px,
округлять нечего), а в нужный размер текст приводится `painter.scale(px / BASE_PX)`. Ширины и обрезание «…» считаются
по тем же метрикам, пересчитанным в логические px. Текст QLabel/QSS остаётся целым — это старые страницы.
"""

from dataclasses import dataclass
from functools import cache, lru_cache
from math import ceil, floor

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPixmap

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
    italic: bool = False
    strike: bool = False


def mono(px: float, weight: QFont.Weight = QFont.Weight.Normal, spacing: float = 0.0,
         wdth: float = theme.WDTH_TEXT, italic: bool = False, strike: bool = False) -> TextSpec:
    return TextSpec("mono", px, weight, spacing, wdth, italic, strike)


def label(px: float, weight: QFont.Weight = QFont.Weight.DemiBold, spacing: float = theme.LABEL_SPACING) -> TextSpec:
    """Barlow Condensed, заглавные; `spacing` — в em."""
    return TextSpec("label", px, weight, spacing)


@cache
def _base_font(kind: str, family: str, weight: QFont.Weight, spacing: float, wdth: float, italic: bool,
               strike: bool) -> QFont:
    """Шрифт размером BASE_PX; `family` — часть ключа кэша: имена семейств выставляет `theme.load_fonts()`."""
    if kind == "label":
        font = theme.label_font(BASE_PX, weight, spacing)
    else:
        font = theme.mono_font(BASE_PX, weight, wdth)
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, BASE_PX * spacing)
    font.setItalic(italic)
    font.setStrikeOut(strike)
    return font


def _key(spec: TextSpec) -> tuple:
    """Ключ кэшей: семейство берётся из темы (имена выставляет `load_fonts()`), поэтому оно — часть ключа."""
    family = theme.LABEL_FAMILY if spec.kind == "label" else theme.MONO_FAMILY
    return spec.kind, family, spec.weight, spec.spacing, spec.wdth, spec.italic, spec.strike


def base_font(spec: TextSpec) -> QFont:
    return _base_font(*_key(spec))


@cache
def _metrics_for(key: tuple) -> QFontMetricsF:
    return QFontMetricsF(_base_font(*key))


def _metrics(spec: TextSpec) -> QFontMetricsF:
    return _metrics_for(_key(spec))


def _scale(spec: TextSpec) -> float:
    return spec.px / BASE_PX


@lru_cache(maxsize=16384)
def _advance(text: str, key: tuple) -> float:
    return _metrics_for(key).horizontalAdvance(text)


def text_width(text: str, spec: TextSpec) -> float:
    """Ширина текста в логических px (с межбуквенным интервалом после каждой буквы, как у CSS)."""
    if spec.kind == "label":
        text = text.upper()
    return _advance(text, _key(spec)) * _scale(spec)


def ascent_descent(spec: TextSpec) -> tuple[float, float]:
    """Подъём и спуск шрифта в логических px, округлённые до целых, как в браузере (Blink округляет метрики шрифта, и
    высота строки `line-height: normal` — сумма округлённых): от этого зависит положение строк в двухстрочных полях."""
    m = _metrics(spec)
    k = _scale(spec)
    return float(floor(m.ascent() * k + 0.5)), float(floor(m.descent() * k + 0.5))


def line_height(spec: TextSpec) -> float:
    a, d = ascent_descent(spec)
    return a + d


@lru_cache(maxsize=16384)
def _elided(text: str, key: tuple, mode: Qt.TextElideMode, width: float) -> str:
    return _metrics_for(key).elidedText(text, mode, width)


def elide(text: str, spec: TextSpec, width: float, mode: Qt.TextElideMode = Qt.TextElideMode.ElideRight) -> str:
    """Обрезает текст с «…» по метрикам крупного шрифта; ширина — в логических px."""
    if spec.kind == "label":
        text = text.upper()
    return _elided(text, _key(spec), mode, round(width / _scale(spec), 2))


def _place(rect: QRectF, text: str, spec: TextSpec, align: Qt.AlignmentFlag,
           elide_mode: Qt.TextElideMode | None) -> tuple[str, float, float]:
    """Что рисовать (после обрезания), x начала и базовая линия. По вертикали Center — середина строки (подъём − спуск) / 2
    на середине `rect`, Top — верх строки у верха, Bottom — низ строки у низа."""
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
    return text, x, baseline


def draw_text(p: QPainter, rect: QRectF, text: str, spec: TextSpec, color: str | QColor,
              align: Qt.AlignmentFlag = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
              elide_mode: Qt.TextElideMode | None = None) -> None:
    """Рисует одну строку в `rect`. `elide_mode` — обрезать «…», если текст шире `rect`."""
    if not text:
        return
    text, x, baseline = _place(rect, text, spec, align, elide_mode)
    p.save()
    p.setFont(base_font(spec))
    p.setPen(QColor(color))
    p.translate(QPointF(x, baseline))
    p.scale(_scale(spec), _scale(spec))
    p.drawText(QPointF(0, 0), text)
    p.restore()


_PIXMAPS: dict[tuple, QPixmap] = {}
_PIXMAPS_MAX = 6000
PAD = 2  # запас растра вокруг строки: выступы глифов и сглаживание


def draw_text_cached(p: QPainter, rect: QRectF, text: str, spec: TextSpec, color: str | QColor,
                     align: Qt.AlignmentFlag = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                     elide_mode: Qt.TextElideMode | None = None) -> None:
    """То же, что `draw_text`, но строка рисуется один раз в растр (ключ: текст, шрифт, цвет, DPR) и дальше только
    копируется, в 3–4 раза быстрее при повторных перерисовках сотен плашек. Положение округляется до пикселя устройства
    (отличие от `draw_text` не больше полпикселя) — для строк на фоне плашек; поля ввода рисуют точным `draw_text`."""
    if not text:
        return
    text, x, baseline = _place(rect, text, spec, align, elide_mode)
    dpr = p.device().devicePixelRatioF()
    qc = QColor(color)
    key = (text, _key(spec), spec.px, qc.rgba(), dpr)
    pm = _PIXMAPS.get(key)
    ascent, descent = ascent_descent(spec)
    if pm is None:
        if len(_PIXMAPS) >= _PIXMAPS_MAX:
            _PIXMAPS.clear()
        width = text_width(text, spec)
        pm = QPixmap(ceil((width + 2 * PAD) * dpr), ceil((ascent + descent + 2 * PAD) * dpr))
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.GlobalColor.transparent)
        q = QPainter(pm)
        q.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        q.setFont(base_font(spec))
        q.setPen(qc)
        q.translate(QPointF(PAD, PAD + ascent))
        q.scale(_scale(spec), _scale(spec))
        q.drawText(QPointF(0, 0), text)
        q.end()
        _PIXMAPS[key] = pm
    p.drawPixmap(QPointF(round((x - PAD) * dpr) / dpr, round((baseline - ascent - PAD) * dpr) / dpr), pm)
