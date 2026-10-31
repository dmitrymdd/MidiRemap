"""Подсказки: `tip()` готовит текст для `setToolTip` так, чтобы длинная подсказка переносилась на ширине макета.

QSS не умеет ограничивать ширину подсказки, а у Qt она по умолчанию растягивается чуть ли не на пол-экрана. Поэтому
длинный текст оборачивается в таблицу фиксированной ширины `theme.TOOLTIP_TEXT_WIDTH`; короткий остаётся без неё и
подсказка не раздувается до полной ширины. Внешний вид (фон, рамка, поля, шрифт) — `QToolTip` в `theme.stylesheet()`.
"""

from html import escape

from PySide6.QtGui import QFontMetricsF

from . import theme


def tip(text: str, title: str | None = None) -> str:
    """HTML подсказки: экранирует `<`, `&`, переводы строк — в `<br>`, заголовок `title` — жирной первой строкой.
    Нужен QGuiApplication (измеряется шрифт подсказки)."""
    metrics = QFontMetricsF(theme.mono_font(theme.TOOLTIP_PX))
    lines = ([title] if title else []) + text.split("\n")
    widest = max(metrics.horizontalAdvance(line) for line in lines)
    body = "<br>".join(escape(line) for line in text.split("\n"))
    if title:
        body = f"<b>{escape(title)}</b><br>{body}"
    if widest > theme.TOOLTIP_TEXT_WIDTH:
        return (f'<table width="{theme.TOOLTIP_TEXT_WIDTH}" cellspacing="0" cellpadding="0"><tr><td>'
                f'<p style="margin:0; line-height:{theme.TOOLTIP_LINE_HEIGHT}%">{body}</p></td></tr></table>')
    # короткий текст: без переноса, иначе Qt сам сломает даже одну короткую строку на несколько
    return f'<p style="margin:0; white-space:nowrap; line-height:{theme.TOOLTIP_LINE_HEIGHT}%">{body}</p>'
