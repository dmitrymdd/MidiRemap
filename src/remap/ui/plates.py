"""Плашки: строки пула и сцены, заголовки групп, бейдж «+N», строки нот Maps, записи списка карт.

Только рисование (`QPainter`, без виджетов): функции принимают прямоугольник и данные и ничего не кэшируют — их зовут
из `paint()` элементов QGraphicsView и делегатов таблиц, поэтому они дешёвы (ни текстур, ни теней). Метрики — из макета
(плашка: радиус 5, поля 10, зазор 10, столбец номера 28 px по правому краю), высоты строк задаёт вызывающий.
Текст — `ui/text.py`: всё здесь это span/div макета, то есть `WDTH_TEXT` (75).
"""

from dataclasses import dataclass
from functools import cache
from math import ceil

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QFont, QPainter, QPainterPath, QPen, QPixmap

from . import text, theme
from .icons import ICONS, draw_icon
from .theme import RGBA, qcolor

STATES = ("normal", "selected", "deleted", "hover", "suggested", "warn", "error", "drop")
NAME_OFFSET = theme.PLATE_PAD_X + theme.PLATE_NUM_W + theme.PLATE_GAP  # от левого края плашки до имени
LEFT_MID = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
RIGHT_MID = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
LEFT_TOP = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop


def number_spec() -> text.TextSpec:
    return text.mono(theme.PLATE_NUM_FONT)


def name_spec(italic: bool = False, strike: bool = False) -> text.TextSpec:
    return text.mono(theme.PLATE_NAME_FONT, italic=italic, strike=strike)


def name_width(name: str, italic: bool = False) -> float:
    """Ширина имени на плашке, px (для решения «обрезано ли — полное имя в подсказке»)."""
    return text.text_width(name, name_spec(italic))


@dataclass(frozen=True)
class PlateStyle:
    """Вид плашки: заливка и рамка (`None` — нет), цвета номера и имени, непрозрачность, пунктир рамки."""

    fill: RGBA | str | None
    border: RGBA | str | None
    number: str
    name: str
    opacity: float = 1.0
    dashed: bool = False


@cache
def plate_style(state: str) -> PlateStyle:
    """Вид плашки по состоянию. normal / selected / deleted — как в макете; hover, suggested, warn, error и drop (цель
    перетаскивания или кабель под курсором: рамка акцентом) в макете не заданы — это предложения."""
    normal = PlateStyle(theme.CHIP_BG, theme.CHIP_BORDER, theme.PLATE_NUM, theme.PLATE_NAME)
    styles = {
        "normal": normal,
        "selected": PlateStyle(theme.PLATE_SELECTED_BG, theme.SELECTED, theme.SELECTED, theme.SELECTED),
        "deleted": PlateStyle(None, theme.PLATE_DELETED_BORDER, theme.PLATE_DELETED_NUM, theme.PLATE_DELETED_NAME),
        "hover": PlateStyle(theme.PLATE_HOVER_BG, theme.PLATE_HOVER_BORDER, theme.PLATE_NUM, theme.PLATE_NAME),
        "suggested": PlateStyle(theme.CHIP_BG, theme.CHIP_BORDER, theme.PLATE_NUM, theme.PLATE_NAME,
                                theme.PLATE_SUGGESTED_OPACITY, True),
        "warn": PlateStyle(theme.WARN_BG, theme.WARN_BORDER, theme.WARN_TEXT, theme.WARN_TEXT),
        "error": PlateStyle(theme.ERR_BG, theme.ERR_BORDER, theme.ERR_TEXT, theme.ERR_TEXT),
        "drop": PlateStyle(theme.PLATE_HOVER_BG, theme.ACCENT, theme.PLATE_NUM, theme.PLATE_NAME),
    }
    if state not in styles:
        raise ValueError(state)
    return styles[state]


def _paint_box(p: QPainter, rect: QRectF, style: PlateStyle, radius: float = theme.PLATE_RADIUS) -> None:
    """Заливка и рамка 1 px внутри `rect` (граница по половине пикселя: линия ровно в один пиксель)."""
    box = rect.adjusted(0.5, 0.5, -0.5, -0.5)
    p.setBrush(qcolor(style.fill) if style.fill is not None else Qt.BrushStyle.NoBrush)
    if style.border is None:
        p.setPen(Qt.PenStyle.NoPen)
    else:
        pen = QPen(qcolor(style.border), 1)
        if style.dashed:
            pen.setStyle(Qt.PenStyle.CustomDashLine)
            pen.setDashPattern([3, 3])
        p.setPen(pen)
    p.drawRoundedRect(box, radius - 0.5, radius - 0.5)


_PLATES: dict[tuple, QPixmap] = {}
_PLATES_MAX = 400  # растров плашек целиком (по ~20 КБ при DPR 1): хватает на видимые строки пула и сцены


def _plate_direct(p: QPainter, rect: QRectF, state: str, numbers, name: str, name_room: float | None, italic: bool,
                  text_deleted: bool, dim_name: bool, line_h: float | None) -> float:
    style = plate_style(state)
    deleted = state == "deleted" or text_deleted
    number_color = theme.PLATE_DELETED_NUM if deleted else style.number
    name_color = theme.PLATE_DELETED_NAME if deleted or dim_name else style.name
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    _paint_box(p, rect, style)
    line = line_h if line_h is not None else rect.height()
    x = rect.left() + theme.PLATE_PAD_X
    for dy, number in numbers:
        text.draw_text(p, QRectF(x, rect.top() + dy, theme.PLATE_NUM_W, line), number, number_spec(), number_color, RIGHT_MID)
    name_x = rect.left() + NAME_OFFSET
    room = name_room if name_room is not None else rect.right() - theme.PLATE_PAD_X - name_x
    if name:
        text.draw_text(p, QRectF(name_x, rect.top(), max(room, 0.0), line), name, name_spec(italic, deleted), name_color,
                       LEFT_MID, Qt.TextElideMode.ElideRight)
    p.restore()
    return name_x


def paint_plate(p: QPainter, rect: QRectF, state: str = "normal", *, numbers: list[tuple[float, str]] | tuple = (),
                name: str = "", name_room: float | None = None, italic: bool = False, text_deleted: bool = False,
                dim_name: bool = False, line_h: float | None = None) -> float:
    """Плашка в `rect` (с рамкой): фон по состоянию, столбец номеров, имя с «…». `numbers` — (смещение по вертикали,
    номер): у высокой строки цели номера стоят на уровне своих кабелей; `line_h` — высота первой строки блока (по
    умолчанию вся высота). `text_deleted` — зачёркнутое имя приглушённым цветом без смены фона (зачёркнутая нота под
    курсором); `dim_name` — имя приглушено без зачёркивания (ноты без имени). Возвращает x начала имени.

    Плашка с целыми размерами рисуется один раз в растр по всем параметрам и DPR и дальше только копируется: сотни
    плашек в QGraphicsView перерисовываются при каждой прокрутке, и растр в разы дешевле, чем рисование тех же
    скруглённых рамок и строк текста заново."""
    opacity = plate_style(state).opacity
    name_x = rect.left() + NAME_OFFSET
    w, h = rect.width(), rect.height()
    if w != int(w) or h != int(h) or rect.left() != int(rect.left()) or rect.top() != int(rect.top()):
        p.save()
        p.setOpacity(p.opacity() * opacity)
        _plate_direct(p, rect, state, numbers, name, name_room, italic, text_deleted, dim_name, line_h)
        p.restore()
        return name_x
    dpr = p.device().devicePixelRatioF()
    key = (state, int(w), int(h), tuple(numbers), name, name_room, italic, text_deleted, dim_name, line_h, dpr,
           theme.MONO_FAMILY)
    pm = _PLATES.get(key)
    if pm is None:
        if len(_PLATES) >= _PLATES_MAX:
            _PLATES.clear()
        pm = QPixmap(ceil(w * dpr), ceil(h * dpr))
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.GlobalColor.transparent)
        q = QPainter(pm)
        _plate_direct(q, QRectF(0, 0, w, h), state, numbers, name, name_room, italic, text_deleted, dim_name, line_h)
        q.end()
        _PLATES[key] = pm
    if opacity != 1.0:
        p.save()
        p.setOpacity(p.opacity() * opacity)
        p.drawPixmap(rect.topLeft(), pm)
        p.restore()
    else:
        p.drawPixmap(rect.topLeft(), pm)
    return name_x


def paint_badge(p: QPainter, rect: QRectF, label: str, hot: bool = False) -> None:
    """Бейдж «+N»: рамка CHIP_BORDER радиусом 3, текст Martian 10. `hot` — цель drop (рамка и текст акцентом)."""
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    style = PlateStyle(theme.PLATE_HOVER_BG if hot else None, theme.ACCENT if hot else theme.CHIP_BORDER, "", "")
    _paint_box(p, rect, style, theme.BADGE_RADIUS)
    text.draw_text_cached(p, rect, label, text.mono(theme.BADGE_FONT), theme.ACCENT if hot else theme.SCREEN_TEXT_2,
                          Qt.AlignmentFlag.AlignCenter)
    p.restore()


def badge_width(label: str) -> float:
    """Ширина бейджа по тексту: поля 5 px и рамка."""
    return text.text_width(label, text.mono(theme.BADGE_FONT)) + 2 * theme.BADGE_PAD + 2


def header_spec() -> text.TextSpec:
    return text.mono(theme.HEADER_FONT, QFont.Weight.DemiBold, theme.HEADER_SPACING)


def header_label_width(label: str) -> float:
    """Ширина метки заголовка группы (заглавными), px."""
    return text.text_width(label.upper(), header_spec())


def header_label_x(variant: str = "scene", inset: float | None = None) -> float:
    """Отступ метки заголовка от левого края: поле (у пула 2 px) + значок 8 px + зазор 7."""
    return (2 if inset is None and variant == "pool" else inset or 0) + 8 + 7


def paint_group_header(p: QPainter, rect: QRectF, label: str, count: str = "", collapsed: bool = False, *,
                       variant: str = "scene", state: str = "normal", caret: bool = True, icon: str | None = None,
                       align: str = "bottom", inset: float | None = None, label_room: float | None = None) -> float:
    """Заголовок группы: значок (треугольник, свёрнут — повёрнут вправо; или `icon`, например замок Maps), метка акцентом,
    число приглушённо на одной базовой линии. `variant`: `scene` — с линией SCREEN_DIVIDER на нижней строке `rect` и полем
    под ней 6 px; `pool` — без линии, поле снизу 3 px. `align`: `bottom` — строка прижата к низу содержимого (Profiles),
    `center` — по центру (список карт Maps). `state`: normal / hover / lit (кабель или цель drop: плашка наведения
    с рамкой акцентом). Возвращает x конца метки."""
    if variant not in ("scene", "pool") or align not in ("bottom", "center"):
        raise ValueError((variant, align))
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    if state in ("hover", "lit"):
        _paint_box(p, rect, plate_style("drop" if state == "lit" else "hover"))
    if variant == "scene":
        p.fillRect(QRectF(rect.left(), rect.bottom() - 1, rect.width(), 1), qcolor(theme.SCREEN_DIVIDER))
    pad = 6 if variant == "scene" else 3
    spec = header_spec()
    line = text.line_height(spec)
    bottom = rect.bottom() - pad
    top = bottom - line if align == "bottom" else (rect.top() + bottom) / 2 - line / 2
    left = rect.left() + (2 if inset is None and variant == "pool" else inset or 0)
    x = left
    if icon is not None or caret:
        name = icon or "group-caret"
        ic = ICONS[name]
        box = QRectF(left, top + line / 2 - ic.h / 2, ic.w, ic.h)
        if icon is None and align == "bottom":
            box.moveTop(bottom - 6 - ic.h / 2)  # треугольник: центр на 6 px выше низа строки (в макете margin-bottom 2)
        p.save()
        if collapsed and icon is None:
            p.translate(box.center())
            p.rotate(-90)
            p.translate(-box.center())
        draw_icon(p, name, box)
        p.restore()
        x = left + ic.w + 7
    room = label_room if label_room is not None else rect.right() - x - 48
    shown = text.elide(label.upper(), spec, max(room, 0.0))
    text.draw_text(p, QRectF(x, top, max(room, 0.0), line), shown, spec, theme.ACCENT, LEFT_TOP)
    end = x + text.text_width(shown, spec)
    if count:
        small = text.mono(theme.HEADER_COUNT_FONT)
        ascent, _ = text.ascent_descent(small)
        baseline = top + text.ascent_descent(spec)[0]
        text.draw_text(p, QRectF(end + 7, baseline - ascent, 56, text.line_height(small)), count, small,
                       theme.SCREEN_TEXT_3, LEFT_TOP)
    p.restore()
    return end


def paint_chevron(p: QPainter, x: float, cy: float, collapsed: bool, fixed: bool = False) -> None:
    """Шеврон раскрытия алиасов: вправо — свёрнуто, вниз — развёрнуто; `fixed` — раскрыть нельзя (приглушён)."""
    s = 3.0
    path = QPainterPath()
    if collapsed:
        path.moveTo(x + 1, cy - s)
        path.lineTo(x + 1 + s, cy)
        path.lineTo(x + 1, cy + s)
    else:
        path.moveTo(x, cy - s / 2)
        path.lineTo(x + s, cy + s / 2)
        path.lineTo(x + 2 * s, cy - s / 2)
    pen = QPen(qcolor(theme.SCREEN_TEXT_3 if fixed else theme.SCREEN_TEXT_2), 1.4)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(path)
    p.restore()


def cable_color(selected: bool = False, hovered: bool = False) -> str:
    """Цвет кабеля, точки и превью: обычный CABLE, под курсором — акцент, у выбранной строки — белый. Направление цветом не
    различается."""
    return theme.SELECTED if selected else theme.ACCENT if hovered else theme.CABLE


def paint_port(p: QPainter, c: QPointF, radius: float, color: str, hollow: bool = False) -> None:
    """Точка подключения кабеля; `hollow` — кольцо (подсказка, правила ещё нет)."""
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    if hollow:
        p.setPen(QPen(qcolor(color), 1.2))
        p.setBrush(qcolor(theme.SCREEN_GLASS_MID))
    else:
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(qcolor(color))
    p.drawEllipse(c, radius, radius)
    p.restore()


# --- Maps ---
def paint_note_number(p: QPainter, rect: QRectF, label: str, editing: bool = False) -> None:
    """Номер в столбце ноты: по правому краю с отступом 18 px."""
    text.draw_text(p, rect.adjusted(0, 0, -theme.NOTE_NUM_PAD, 0), label, number_spec(),
                   theme.SELECTED if editing else theme.PLATE_NUM, RIGHT_MID)


def paint_note_name(p: QPainter, rect: QRectF, name: str, *, dim: bool = False, badge: str = "") -> None:
    """Имя ноты с «…» и бейджем «+N» за ним (зазор 8 px); `dim` — ноты без имени."""
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    room = rect.width()
    pill = badge_width(badge) if badge else 0.0
    if badge:
        room -= pill + 8
    shown = text.elide(name, name_spec(), max(room, 0.0))
    color = theme.PLATE_DELETED_NAME if dim else theme.PLATE_NAME
    text.draw_text(p, QRectF(rect.left(), rect.top(), max(room, 0.0), rect.height()), shown, name_spec(), color, LEFT_MID)
    if badge:
        x = round(rect.left() + text.text_width(shown, name_spec()) + 8)  # по целым пикселям: рамка в 1 px без размытия
        h = theme.BADGE_HEIGHT
        paint_badge(p, QRectF(x, round(rect.center().y() - h / 2), round(pill), h), badge)
    p.restore()


def paint_note_row(p: QPainter, rect: QRectF, number: str, name: str, *, editing: bool = False, dim: bool = False,
                   badge: str = "") -> None:
    """Строка ноты Maps целиком: столбец номера 64 px, имя, линия под строкой. `editing` — как в макете: заливка и белая
    рамка 1 px, поле имени `NOTE_EDIT_FIELD` с кареткой (в приложении правит настоящий QLineEdit; это для образца)."""
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    if editing:
        _paint_box(p, rect, PlateStyle(theme.NOTE_EDIT_BG, theme.SELECTED, "", ""), 4)
    else:
        p.fillRect(QRectF(rect.left(), rect.bottom() - 1, rect.width(), 1), qcolor(theme.NOTE_ROW_LINE))
    paint_note_number(p, QRectF(rect.left(), rect.top(), theme.NOTE_NUM_COL, rect.height()), number, editing)
    cell = QRectF(rect.left() + theme.NOTE_NUM_COL, rect.top(), rect.width() - theme.NOTE_NUM_COL, rect.height())
    if editing:
        field = QRectF(cell.left() - 9, rect.center().y() - 11, max(180.0, text.text_width(name, name_spec()) + 17), 22)
        _paint_box(p, field, PlateStyle(theme.NOTE_EDIT_FIELD, theme.CHIP_BORDER, "", ""), theme.NOTE_EDIT_RADIUS)
        text.draw_text(p, field.adjusted(9, 0, -9, 0), name, name_spec(), theme.SELECTED, LEFT_MID)
        caret_x = field.left() + 9 + text.text_width(name, name_spec()) + 1
        p.fillRect(QRectF(caret_x, rect.center().y() - 7, 1, 14), qcolor(theme.SELECTED))
    else:
        paint_note_name(p, cell, name, dim=dim, badge=badge)
    p.restore()


def paint_map_entry(p: QPainter, rect: QRectF, name: str, sub: str, *, selected: bool = False, hover: bool = False,
                    enabled: bool = True) -> None:
    """Запись списка карт: плашка (выбранная — белая), имя 12/500 и строка источника 9.5, блок по центру высоты."""
    state = "selected" if selected else "hover" if hover and enabled else "normal"
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    _paint_box(p, rect, plate_style(state))
    title = text.mono(theme.MAP_NAME_FONT, QFont.Weight.Medium)
    small = text.mono(theme.MAP_SUB_FONT)
    th, sh = text.line_height(title), text.line_height(small)
    y = rect.center().y() - (th + theme.MAP_ENTRY_GAP + sh) / 2
    room = max(rect.width() - 2 * theme.PLATE_PAD_X - 2, 0.0)
    color = theme.SELECTED if selected else theme.PLATE_NAME if enabled else theme.PLATE_DELETED_NAME
    x = rect.left() + theme.PLATE_PAD_X + 1  # поле 10 и рамка 1 px
    text.draw_text(p, QRectF(x, y, room, th), name, title, color, LEFT_TOP, Qt.TextElideMode.ElideRight)
    text.draw_text(p, QRectF(x, y + th + theme.MAP_ENTRY_GAP, room, sh), sub, small,
                   theme.MAP_SUB_SELECTED if selected else theme.SCREEN_TEXT_3, LEFT_TOP, Qt.TextElideMode.ElideRight)
    p.restore()

