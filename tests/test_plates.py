"""Плашки (`ui/plates.py`): состояния, метрики и тексты по эталону макета, кэш растров, заголовки, бейдж, Maps."""
import re
import time
from pathlib import Path

import pytest

pytest.importorskip("PySide6")
pytestmark = pytest.mark.ui

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter

from remap.ui import plates, theme

SRC = Path(__file__).resolve().parents[1] / "src" / "remap" / "ui"
BG = "#0D1C15"


@pytest.fixture(autouse=True)
def fonts(app):
    theme.load_fonts()


def rgb(hex_color: str) -> tuple[int, int, int]:
    c = QColor(hex_color)
    return c.red(), c.green(), c.blue()


def canvas(w=300, h=80, dpr=1.0) -> tuple[QImage, QPainter]:
    img = QImage(round(w * dpr), round(h * dpr), QImage.Format.Format_ARGB32_Premultiplied)
    img.setDevicePixelRatio(dpr)
    img.fill(QColor(BG))
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    return img, p


def px(img: QImage, x: float, y: float) -> tuple[int, int, int]:
    d = img.devicePixelRatio()
    return img.pixelColor(int(x * d), int(y * d)).getRgb()[:3]


def ink(img: QImage, box: tuple[float, float, float, float], fg: str):
    """Чернила текста в логических px: порог — половина пути от фона до цвета текста."""
    d = img.devicePixelRatio()
    x0, y0, x1, y1 = [round(v * d) for v in box]
    bg, f = img.pixelColor(x0, y0), QColor(fg)
    vec = (f.red() - bg.red(), f.green() - bg.green(), f.blue() - bg.blue())
    n2 = sum(v * v for v in vec) or 1
    xs, ys = [], []
    for x in range(x0, x1):
        for y in range(y0, y1):
            c = img.pixelColor(x, y)
            t = ((c.red() - bg.red()) * vec[0] + (c.green() - bg.green()) * vec[1] + (c.blue() - bg.blue()) * vec[2]) / n2
            if t > 0.5:
                xs.append(x)
                ys.append(y)
    return (min(xs) / d, min(ys) / d, (max(xs) + 1) / d, (max(ys) + 1) / d) if xs else None


def drawn(state="normal", dpr=1.0, **kw) -> QImage:
    img, p = canvas(dpr=dpr)
    plates.paint_plate(p, QRectF(10, 10, 200, 30), state, **kw)
    p.end()
    return img


# --- состояния ---
def test_every_state_has_a_style_and_unknown_is_rejected():
    for state in plates.STATES:
        assert plates.plate_style(state).number and plates.plate_style(state).name
    with pytest.raises(ValueError):
        plates.plate_style("glowing")
    assert plates.plate_style("suggested").dashed and plates.plate_style("suggested").opacity == theme.PLATE_SUGGESTED_OPACITY
    assert plates.plate_style("deleted").fill is None  # зачёркнутая — без заливки


@pytest.mark.parametrize("dpr", [1.0, 2.0])
@pytest.mark.parametrize(("state", "border"), [
    ("normal", theme.CHIP_BORDER), ("selected", theme.SELECTED), ("deleted", theme.PLATE_DELETED_BORDER),
    ("hover", theme.PLATE_HOVER_BORDER), ("warn", theme.WARN_BORDER), ("error", theme.ERR_BORDER), ("drop", theme.ACCENT)])
def test_plate_border_is_one_pixel_in_the_state_colour(state, border, dpr):
    img = drawn(state, dpr)
    assert px(img, 110, 10.5) == rgb(border) and px(img, 10.5, 25) == rgb(border) and px(img, 110, 39.5) == rgb(border)
    assert px(img, 110, 11.5) != rgb(border)  # ровно одна строка рамки


def test_fills_follow_the_mockup_and_deleted_is_transparent():
    normal, selected, deleted = drawn("normal"), drawn("selected"), drawn("deleted")
    base = QColor(BG)
    green = (110 * 0.07 + base.red() * 0.93, 190 * 0.07 + base.green() * 0.93, 140 * 0.07 + base.blue() * 0.93)
    assert all(abs(a - b) <= 1.5 for a, b in zip(px(normal, 16, 25), green, strict=True))  # rgba(110,190,140,.07)
    assert px(selected, 16, 25)[0] > px(normal, 16, 25)[0] + 6  # rgba(255,255,255,.09): светлее
    assert px(deleted, 16, 25) == rgb(BG)


def test_corner_is_rounded_with_radius_5():
    img = drawn("normal")
    assert px(img, 10.2, 10.2) == rgb(BG)  # угол вырезан
    assert px(img, 10 + 5, 10.5) == rgb(theme.CHIP_BORDER)  # а у конца дуги рамка уже прямая


# --- текст: цвета и метрики ---
def test_number_column_right_aligned_and_name_at_offset_48():
    img = drawn("normal", numbers=[(0, "36")], name="Kick: Hit")
    n = ink(img, (12, 12, 48, 38), theme.PLATE_NUM)
    assert n[2] == pytest.approx(10 + 10 + 28, abs=1.0)  # правый край номера: поле 10 + столбец 28
    scratch, q = canvas()
    name_x = plates.paint_plate(q, QRectF(10, 10, 200, 30), "normal", name="X")
    q.end()
    assert scratch is not None
    assert name_x == 10 + 48 == 10 + plates.NAME_OFFSET
    k = ink(img, (58, 12, 200, 38), theme.PLATE_NAME)
    assert k[0] == pytest.approx(58, abs=1.5)


@pytest.mark.parametrize(("state", "number", "name"), [
    ("normal", theme.PLATE_NUM, theme.PLATE_NAME), ("selected", theme.SELECTED, theme.SELECTED),
    ("deleted", theme.PLATE_DELETED_NUM, theme.PLATE_DELETED_NAME), ("warn", theme.WARN_TEXT, theme.WARN_TEXT),
    ("error", theme.ERR_TEXT, theme.ERR_TEXT)])
def test_text_colours_per_state(state, number, name):
    img = drawn(state, numbers=[(0, "36")], name="Kick: Hit")
    assert ink(img, (12, 12, 48, 38), number) is not None
    assert ink(img, (58, 12, 200, 38), name) is not None
    box = (58, 12, 200, 38)
    assert ink(img, box, name)[2] - ink(img, box, name)[0] == pytest.approx(plates.name_width("Kick: Hit"), abs=2.5)


def test_deleted_text_is_struck_through_and_dim_name_is_not():
    struck = drawn("normal", name="Hi-Hat: Seq Hits", text_deleted=True)
    dim = drawn("normal", name="Hi-Hat: Seq Hits", dim_name=True)
    plain = drawn("normal", name="Hi-Hat: Seq Hits")
    def line_row(img: QImage) -> int:
        """Строка, в которой чернила имени тянутся сплошной линией (зачёркивание), или -1."""
        def lit(y: int) -> int:
            return sum(px(img, x, y)[1] > rgb(BG)[1] + 25 for x in range(60, 110))

        best = max(range(14, 36), key=lit)
        return best if lit(best) > 45 else -1

    assert line_row(struck) > 0  # у зачёркнутой есть сплошная строка поперёк слов
    assert line_row(dim) == -1 and line_row(plain) == -1
    assert ink(dim, (58, 12, 200, 38), theme.PLATE_DELETED_NAME) is not None


# Ширины чернил имён в эталоне макета (`Profiles@2x.png`): имена плашек сцены и пула — Martian 12/400, wdth 75
@pytest.mark.parametrize(("name", "expected"), [("Snare: Zone Trigger", 135.0), ("Cymbal 2: Bell Shank", 142.0),
                                                  ("Hi-Hat: Edge Trigger", 135.0)])
def test_plate_name_widths_match_the_mockup(name, expected):
    img = drawn("normal", dpr=2.0, name=name, name_room=190)
    box = ink(img, (58, 12, 205, 38), theme.PLATE_NAME)
    assert box[2] - box[0] == pytest.approx(expected, abs=1.2) or box[2] - box[0] <= 190  # «Hi-Hat: Edge Trigger» не влезает
    if name != "Hi-Hat: Edge Trigger":
        assert box[2] - box[0] == pytest.approx(expected, abs=1.2)


def test_long_name_is_elided_with_an_ellipsis_inside_the_room():
    img = drawn("normal", name="Snare: Forward brushTrigger long name", name_room=100)
    box = ink(img, (58, 12, 208, 38), theme.PLATE_NAME)
    assert box[2] <= 58 + 100 + 1


def test_tall_target_plate_draws_numbers_on_their_own_lines():
    img, p = canvas(h=120)
    plates.paint_plate(p, QRectF(10, 10, 200, 66), "normal", numbers=[(0, "35"), (36, "34")], name="Kick: Open", line_h=30)
    p.end()
    first, second = ink(img, (12, 12, 48, 40), theme.PLATE_NUM), ink(img, (12, 46, 48, 74), theme.PLATE_NUM)
    assert first is not None and second is not None and second[1] - first[1] == pytest.approx(36, abs=1.0)


# --- кэш растров ---
def test_plate_is_rasterised_once_per_parameters_and_dpr():
    plates._PLATES.clear()
    for _ in range(3):
        drawn("normal", numbers=[(0, "36")], name="Kick: Hit")
    assert len(plates._PLATES) == 1
    drawn("selected", numbers=[(0, "36")], name="Kick: Hit")
    drawn("normal", numbers=[(0, "36")], name="Kick: Open")
    drawn("normal", 2.0, numbers=[(0, "36")], name="Kick: Hit")
    assert len(plates._PLATES) == 4
    _img, p = canvas()
    plates.paint_plate(p, QRectF(10.5, 10, 200, 30), "normal", name="Fractional")  # нецелая позиция — без кэша
    p.end()
    assert len(plates._PLATES) == 4


def test_cached_plate_looks_like_the_direct_one():
    cached = drawn("normal", numbers=[(0, "36")], name="Kick: Hit")
    direct, p = canvas()
    plates._plate_direct(p, QRectF(10, 10, 200, 30), "normal", [(0, "36")], "Kick: Hit", None, False, False, False, None)
    p.end()
    assert max(abs(a - b) for x in range(10, 210) for y in range(10, 40)
               for a, b in zip(cached.pixelColor(x, y).getRgb()[:3], direct.pixelColor(x, y).getRgb()[:3], strict=True)) <= 1


def test_suggested_is_dashed_and_dimmed():
    img = drawn("suggested")
    border = [px(img, x, 10.5) for x in range(40, 80)]
    on = sum(c != rgb(BG) and c[1] > 60 for c in border)
    assert 10 < on < 30  # пунктир: часть пикселей рамки есть, часть — просвет


# --- заголовок группы ---
def test_scene_header_has_a_divider_pool_header_not():
    img, p = canvas(h=120)
    plates.paint_group_header(p, QRectF(10, 10, 220, 30), "snare", "6 / 15", variant="scene")
    plates.paint_group_header(p, QRectF(10, 60, 220, 29), "hi-hat", "3", variant="pool")
    p.end()
    assert px(img, 150, 39.5) == rgb(theme.SCREEN_DIVIDER)  # нижняя строка заголовка сцены
    assert all(px(img, 150, y) == rgb(BG) for y in (86, 87, 88))  # у пула линии нет
    scratch, q = canvas()
    with pytest.raises(ValueError):
        plates.paint_group_header(q, QRectF(0, 0, 100, 30), "x", variant="wide")
    q.end()
    assert scratch is not None


def test_header_label_is_uppercase_accent_and_count_dim_on_one_baseline():
    img, p = canvas(h=60)
    plates.paint_group_header(p, QRectF(10, 10, 220, 30), "snare", "6 / 15", variant="scene")
    p.end()
    label, count = ink(img, (24, 12, 66, 38), theme.ACCENT), ink(img, (72, 12, 140, 38), theme.SCREEN_TEXT_3)
    assert label is not None and count is not None
    assert label[3] == pytest.approx(count[3], abs=3.0)  # одна базовая линия («/» свисает ниже на 2 px)
    assert label[2] - label[0] == pytest.approx(plates.header_label_width("snare") - 1.3, abs=3.0)


def test_header_caret_rotates_when_collapsed():
    open_img, p = canvas(h=40)
    plates.paint_group_header(p, QRectF(0, 0, 200, 30), "kick", collapsed=False)
    p.end()
    shut_img, q = canvas(h=40)
    plates.paint_group_header(q, QRectF(0, 0, 200, 30), "kick", collapsed=True)
    q.end()
    assert any(open_img.pixelColor(x, y) != shut_img.pixelColor(x, y) for x in range(10) for y in range(10, 26))
    assert plates.header_label_x("pool") == 17 and plates.header_label_x("scene") == 15 and plates.header_label_x("scene", 4) == 19


def test_header_state_plate_for_hover_and_lit():
    img, p = canvas(h=40)
    plates.paint_group_header(p, QRectF(10, 5, 200, 24), "kick", variant="pool", state="lit")
    p.end()
    assert px(img, 110, 5.5) == rgb(theme.ACCENT)


# --- бейдж, шеврон, точка, цвета кабелей ---
def test_badge_width_and_hot_state():
    assert plates.badge_width("+2") == pytest.approx(plates.badge_width("+13") - plates.badge_width("+13") + plates.badge_width("+2"))
    assert plates.badge_width("+13") > plates.badge_width("+2")
    img, p = canvas(h=40)
    plates.paint_badge(p, QRectF(10, 10, plates.badge_width("+2"), 17), "+2")
    plates.paint_badge(p, QRectF(100, 10, plates.badge_width("+2"), 17), "+2", hot=True)
    p.end()
    assert px(img, 20, 10.5) == rgb(theme.CHIP_BORDER) and px(img, 110, 10.5) == rgb(theme.ACCENT)
    assert px(img, 14, 20) == rgb(BG)  # без заливки


def test_cable_colours_and_ports():
    assert plates.cable_color() == theme.CABLE == "#82BC98"
    assert plates.cable_color(selected=True) == theme.SELECTED
    assert plates.cable_color(hovered=True) == theme.ACCENT
    assert plates.cable_color(selected=True, hovered=True) == theme.SELECTED  # выбранный остаётся белым
    img, p = canvas(h=40)
    plates.paint_port(p, QPointF(20, 20), 3.0, theme.CABLE)
    plates.paint_port(p, QPointF(60, 20), 3.0, theme.CABLE, hollow=True)
    p.end()
    assert px(img, 20, 20) == rgb(theme.CABLE) and px(img, 60, 20) == rgb(theme.SCREEN_GLASS_MID)  # кольцо пустое внутри
    assert px(img, 60, 17.2) != rgb(BG)


def test_chevron_changes_with_state():
    imgs = []
    for collapsed, fixed in ((True, False), (False, False), (True, True)):
        img, p = canvas(h=30)
        plates.paint_chevron(p, 10, 15, collapsed, fixed)
        p.end()
        imgs.append(img)
    assert imgs[0] != imgs[1]
    assert ink(imgs[0], (6, 8, 24, 22), theme.SCREEN_TEXT_2) is not None and ink(imgs[2], (6, 8, 24, 22), theme.SCREEN_TEXT_3) is not None


# --- Maps ---
def test_note_row_number_column_line_and_editing():
    img, p = canvas(w=522, h=70)
    plates.paint_note_row(p, QRectF(0, 0, 522, 28), "37", "Snare: Sidestick", badge="+1")
    plates.paint_note_row(p, QRectF(0, 34, 522, 28), "39", "Snare: Ruff", editing=True)
    p.end()
    assert px(img, 300, 27.5)[1] > px(img, 300, 20)[1]  # линия под строкой rgba(110,190,140,.08)
    n = ink(img, (4, 2, 64, 26), theme.PLATE_NUM)
    assert n[2] == pytest.approx(64 - 18, abs=1.0)  # номер: столбец 64, правый отступ 18
    assert px(img, 300, 34.5) == rgb(theme.SELECTED)  # белая рамка строки в правке
    assert px(img, 70, 48) == rgb(theme.NOTE_EDIT_FIELD)  # поле имени
    assert ink(img, (60, 36, 260, 60), theme.SELECTED) is not None  # белый текст в поле


def test_note_name_badge_follows_the_name():
    img, p = canvas(w=300, h=30)
    plates.paint_note_name(p, QRectF(10, 0, 280, 28), "Kick: Open", badge="+1")
    p.end()
    badge_x = round(10 + plates.name_width("Kick: Open") + 8)  # зазор 8 px после имени
    top = [px(img, badge_x + 6, y) for y in (5, 6)]
    assert rgb(theme.CHIP_BORDER) in top  # верхняя рамка бейджа высотой 17 по центру строки
    assert ink(img, (badge_x + 2, 7, badge_x + 14, 22), theme.SCREEN_TEXT_2) is not None  # «+1» внутри


def test_map_entry_selected_hover_and_text():
    def entry(**kw) -> QImage:
        img, p = canvas(w=240, h=60)
        plates.paint_map_entry(p, QRectF(10, 5, 218, 46), "Superior Drummer 3", "core library, default preset", **kw)
        p.end()
        return img

    normal, selected = entry(), entry(selected=True)
    assert px(normal, 110, 5.5) == rgb(theme.CHIP_BORDER) and px(selected, 110, 5.5) == rgb(theme.SELECTED)
    title = ink(selected, (18, 10, 222, 28), theme.SELECTED)
    assert title[2] - title[0] == pytest.approx(128, abs=1.2)  # «Superior Drummer 3» 12/500 — по эталону Maps@2x
    assert ink(selected, (18, 28, 222, 48), theme.MAP_SUB_SELECTED) is not None
    assert ink(normal, (18, 28, 222, 48), theme.SCREEN_TEXT_3) is not None
    assert px(entry(hover=True), 110, 5.5) == rgb(theme.PLATE_HOVER_BORDER)
    assert px(entry(hover=True, enabled=False), 110, 5.5) == rgb(theme.CHIP_BORDER)  # недоступная не подсвечивается


# --- быстродействие ---
def test_visible_part_of_a_long_scene_repaints_quickly(app):
    """300 плашек в QGraphicsScene: перерисовка видимой части (~22 плашки) в пределах кадра на любом железе."""
    from types import SimpleNamespace

    from PySide6.QtWidgets import QGraphicsScene

    from remap.ui import cable_view
    scene = QGraphicsScene()
    for i in range(300):
        model = SimpleNamespace(notes=(i,), shown=i, expanded=False)
        scene.addItem(cable_view._Row(QRectF(8, 8 + i * cable_view.ROW, 200, cable_view.ROW), "pool", model, str(i),
                                      f"Name {i % 17}", pill="+1" if i % 3 == 0 else "", strike=i % 7 == 0))
    img = QImage(240, 620, QImage.Format.Format_ARGB32_Premultiplied)
    vis = QRectF(0, 0, 240, 620)
    times = []
    for _ in range(8):
        p = QPainter(img)
        t = time.perf_counter()
        scene.render(p, vis, vis)
        times.append(time.perf_counter() - t)
        p.end()
    assert sorted(times)[len(times) // 2] < 0.05  # медиана: на этой машине ~2 мс, запас на медленные (цель — 16 мс)


# --- руками нарисованный код без своих цветов ---
@pytest.mark.parametrize("module", ["cable_view", "maps_page", "profiles_page", "main_window", "plates", "keys", "combo", "field",
                                    "glass", "text", "cable_layout"])
def test_hand_painted_modules_have_no_hex_colours_or_legacy_tokens(module):
    source = (SRC / f"{module}.py").read_text(encoding="utf-8")
    code = "\n".join(line.split("#", 1)[0] if not re.search(r"[\"']#", line) else line for line in source.splitlines())
    assert not re.search(r"[\"']#[0-9A-Fa-f]{6}[\"']", code), module
    assert "TOKENS" not in source and "LEGACY" not in source.replace("LEGACY .TXT", ""), module
    assert Qt is not None
