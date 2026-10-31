"""Значки макета: векторные данные (пути SVG из макета), крошечный разборщик путей и рисование.

Значок — набор примитивов в системе координат `viewBox 0 0 w h`; рисуется `QPainter` цветом, поэтому цвет состояния
клавиши (`currentColor` макета) — просто цвет пера, без подстановки в строки и без QtSvg во время работы. Разборщик
знает только абсолютные команды M H V L C Z — этого хватает всем значкам макета. QtSvg нужен лишь тесту как эталон.
"""

import re
from dataclasses import dataclass
from functools import cache, lru_cache

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QPainter, QPainterPath, QPen, QPixmap

from . import theme
from .theme import RGBA, qcolor

_TOKEN = re.compile(r"[A-Za-z]|-?(?:\d+\.?\d*|\.\d+)")
_ARITY = {"M": 2, "L": 2, "H": 1, "V": 1, "C": 6, "Z": 0}

MITER_LIMIT = 4.0  # как у SVG по умолчанию


def parse_path(d: str) -> QPainterPath:
    """Путь SVG из абсолютных команд M, L, H, V, C, Z (числа через пробел и/или запятую). Другие команды — ValueError."""
    path = QPainterPath()
    tokens = _TOKEN.findall(d)
    i, x, y, start = 0, 0.0, 0.0, (0.0, 0.0)
    while i < len(tokens):
        cmd = tokens[i]
        if cmd not in _ARITY:
            raise ValueError(f"unsupported path command {cmd!r} in {d!r}")
        n = _ARITY[cmd]
        args = [float(t) for t in tokens[i + 1:i + 1 + n]]
        if len(args) != n:
            raise ValueError(f"{cmd} needs {n} numbers in {d!r}")
        i += 1 + n
        if cmd == "M":
            x, y = args
            start = (x, y)
            path.moveTo(x, y)
        elif cmd == "L":
            x, y = args
            path.lineTo(x, y)
        elif cmd == "H":
            x = args[0]
            path.lineTo(x, y)
        elif cmd == "V":
            y = args[0]
            path.lineTo(x, y)
        elif cmd == "C":
            path.cubicTo(*args)
            x, y = args[4], args[5]
        else:
            path.closeSubpath()
            x, y = start
    return path


@dataclass(frozen=True)
class Prim:
    """Примитив значка: путь (`data` — строка пути), прямоугольник (x, y, w, h) или круг (cx, cy, r). `fill` — залить,
    иначе обвести; `stroke` — своя толщина обводки."""

    kind: str
    data: str | tuple[float, ...]
    fill: bool = False
    stroke: float | None = None


@dataclass(frozen=True)
class Icon:
    """Значок: размер `viewBox`, примитивы, толщина обводки по умолчанию и собственный цвет (None — цвет задаёт
    вызывающий, как `currentColor`). Стыки — острые (miter), торцы — плоские (butt), как в макете."""

    w: float
    h: float
    prims: tuple[Prim, ...]
    stroke: float = 1.5
    fixed: str | None = None


def _path(d: str, fill: bool = False) -> Prim:
    return Prim("path", d, fill)


def _rect(x: float, y: float, w: float, h: float) -> Prim:
    return Prim("rect", (x, y, w, h), fill=True)


def _circle(cx: float, cy: float, r: float, fill: bool = False) -> Prim:
    return Prim("circle", (cx, cy, r), fill)


_SQ = theme.SCREEN_TEXT_2  # собственный цвет значков на экране (#8FC7A3)

ICONS: dict[str, Icon] = {
    # вкладки
    "tab-convert": Icon(14, 14, (_path("M1.75 2.75 H6.25 V11.25 H1.75 Z M8 7 H12.5 M10 4.5 L12.5 7 L10 9.5"),)),
    "tab-profiles": Icon(14, 14, (_path("M1 3 H2.5 C 7 3, 7 11, 11.5 11 H13 M1 11 H2.5 C 7 11, 7 3, 11.5 3 H13"),)),
    "tab-maps": Icon(14, 14, (_path("M1.25 2.25 H12.75 V11.75 H1.25 Z M4.25 2.25 V7.75 M7 7.75 V11.75 "
                                    "M9.75 2.25 V7.75 M3.25 7.75 H5.25 M8.75 7.75 H10.75"),)),
    # клавиши
    "dots": Icon(14, 4, (_rect(0.5, 0.5, 3, 3), _rect(5.5, 0.5, 3, 3), _rect(10.5, 0.5, 3, 3))),
    "save": Icon(14, 14, (_path("M1.75 1.75 H10 L12.25 4 V12.25 H1.75 Z M4.25 1.75 V5 H9.25 V1.75 "
                                "M4 12.25 V8.5 H10 V12.25"),), stroke=1.4),
    "swap": Icon(16, 12, (_path("M1 3.5 H13 M10 1 L13 3.5 L10 6 M15 8.5 H3 M6 6 L3 8.5 L6 11"),), stroke=1.6,
                 fixed=theme.KEY_SWAP_ICON),
    "go-arrow": Icon(22, 14, (_path("M1 7 H20 M14 1.5 L20 7 L14 12.5"),), stroke=1.8),
    # карты
    "map-new": Icon(14, 14, (_path("M7 1.75 V12.25 M1.75 7 H12.25"),)),
    "map-import": Icon(14, 14, (_path("M2.75 1.25 H8.25 L11.25 4.25 V12.75 H2.75 Z M7 5 V10.5 M4.75 8.25 L7 10.5 "
                                      "L9.25 8.25"),)),
    "map-export": Icon(14, 14, (_path("M2.75 1.25 H8.25 L11.25 4.25 V12.75 H2.75 Z M7 10.5 V5 M4.75 7.25 L7 5 "
                                      "L9.25 7.25"),)),
    "map-more": Icon(14, 14, (_path("M1.5 5.5 H4.5 V8.5 H1.5 Z M5.5 5.5 H8.5 V8.5 H5.5 Z "
                                    "M9.5 5.5 H12.5 V8.5 H9.5 Z"),)),
    # экран
    "search": Icon(13, 13, (_path("M1.75 1.75 H8.25 V8.25 H1.75 Z M8.25 8.25 L12 12"),), stroke=1.4, fixed=_SQ),
    "lock": Icon(10, 12, (_path("M2.5 5.5 V3.8 C2.5 2.4 3.6 1.3 5 1.3 C6.4 1.3 7.5 2.4 7.5 3.8 V5.5 "
                                "M1.3 5.5 H8.7 V10.7 H1.3 Z"),), stroke=1.3, fixed=_SQ),
    "chevron-down": Icon(10, 6, (_path("M1 1 H9 L5 5.5 Z", fill=True),), fixed=_SQ),
    "group-caret": Icon(8, 8, (_path("M0.5 2 H7.5 L4 6.5 Z", fill=True),), fixed=_SQ),
    "file": Icon(14, 14, (_path("M2.75 1.25 H8.25 L11.25 4.25 V12.75 H2.75 Z M8.25 1.25 V4.25 H11.25"),),
                 stroke=1.3, fixed=_SQ),
    "x": Icon(10, 10, (_path("M1.5 1.5 L8.5 8.5 M8.5 1.5 L1.5 8.5"),), stroke=1.3),  # About: stroke=1.5
    "drop-target": Icon(28, 28, (_path("M14 6 V20 M7 13 H21 M2 2 H8 M2 2 V8 M26 2 H20 M26 2 V8 M2 26 H8 "
                                       "M2 26 V20 M26 26 H20 M26 26 V20"),), fixed=_SQ),
    "output-din": Icon(22, 22, (
        _circle(11, 11, 9.5), _rect(9.6, 15.2, 2.8, 2), _rect(5.2, 9.8, 2.4, 2.4), _rect(14.4, 9.8, 2.4, 2.4),
        _rect(7, 5.6, 2.4, 2.4), _rect(12.6, 5.6, 2.4, 2.4), _rect(9.8, 4.2, 2.4, 2.4)), stroke=1.3, fixed=_SQ),
    # About
    "code": Icon(14, 14, (_path("M4.5 3.5 L1 7 L4.5 10.5 M9.5 3.5 L13 7 L9.5 10.5"),), stroke=1.3, fixed=_SQ),
    "chat": Icon(14, 14, (_path("M1.75 2.75 H12.25 V9.75 H6 L3.25 12.25 V9.75 H1.75 Z"),), stroke=1.3, fixed=_SQ),
    "mail": Icon(14, 14, (_path("M1.25 2.75 H12.75 V11.25 H1.25 Z M1.25 2.75 L7 7.5 L12.75 2.75"),), stroke=1.3,
                 fixed=_SQ),
    "external-link": Icon(10, 10, (_path("M3 1.5 H8.5 V7 M8.5 1.5 L1.5 8.5"),), stroke=1.2, fixed=_SQ),
}


@cache
def _shape(prim: Prim) -> QPainterPath:
    if prim.kind == "path":
        return parse_path(str(prim.data))
    path = QPainterPath()
    if prim.kind == "rect":
        path.addRect(QRectF(*prim.data))
    elif prim.kind == "circle":
        cx, cy, r = prim.data
        path.addEllipse(QPointF(cx, cy), r, r)
    else:
        raise ValueError(f"unknown primitive {prim.kind!r}")
    return path


def draw_icon(p: QPainter, name: str, rect: QRectF, color: str | RGBA | None = None,
              stroke: float | None = None) -> None:
    """Рисует значок `name` по центру `rect` (масштаб — по меньшей стороне; при совпадении размеров 1:1). `color` — цвет
    пера и заливки (`currentColor` макета); None — собственный цвет значка. `stroke` — другая толщина обводки.
    Как у встроенного `<svg>`, всё за пределами viewBox обрезается."""
    icon = ICONS[name]
    paint = color if color is not None else icon.fixed
    if paint is None:
        raise ValueError(f"icon {name!r} has no colour of its own: pass `color`")
    col = qcolor(paint)
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    scale = min(rect.width() / icon.w, rect.height() / icon.h)
    p.translate(rect.center().x() - icon.w * scale / 2, rect.center().y() - icon.h * scale / 2)
    p.scale(scale, scale)
    p.setClipRect(QRectF(0, 0, icon.w, icon.h))
    for prim in icon.prims:
        if prim.fill:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(col)
        else:
            pen = QPen(col, stroke or prim.stroke or icon.stroke, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap,
                       Qt.PenJoinStyle.MiterJoin)
            pen.setMiterLimit(MITER_LIMIT)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(_shape(prim))
    p.restore()


@lru_cache(maxsize=256)
def icon_pixmap(name: str, color: str | RGBA | None = None, dpr: float = 1.0, stroke: float | None = None) -> QPixmap:
    """Значок готовым pixmap (для мест, где нужен QPixmap/QIcon, а не рисование); размер — как у значка, DPR — `dpr`."""
    icon = ICONS[name]
    pm = QPixmap(round(icon.w * dpr), round(icon.h * dpr))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    draw_icon(p, name, QRectF(0, 0, icon.w, icon.h), color, stroke)
    p.end()
    return pm


def icon_svg(name: str, color: str = "#FFFFFF", stroke: float | None = None) -> str:
    """Тот же значок строкой SVG — только для сверки разборщика с QtSvg в тестах."""
    icon = ICONS[name]
    parts = [(f'<svg xmlns="http://www.w3.org/2000/svg" width="{icon.w}" height="{icon.h}" '
              f'viewBox="0 0 {icon.w} {icon.h}">')]
    for prim in icon.prims:
        width = stroke or prim.stroke or icon.stroke
        look = (f'fill="{color}"' if prim.fill
                else f'fill="none" stroke="{color}" stroke-width="{width}" stroke-linejoin="miter" stroke-linecap="butt"')
        if prim.kind == "path":
            parts.append(f'<path d="{prim.data}" {look}/>')
        elif prim.kind == "rect":
            x, y, w, h = prim.data
            parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" {look}/>')
        else:
            cx, cy, r = prim.data
            parts.append(f'<circle cx="{cx}" cy="{cy}" r="{r}" {look}/>')
    parts.append("</svg>")
    return "".join(parts)
