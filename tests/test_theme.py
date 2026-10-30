"""Тема: токены — валидные цвета, старой палитры (оранжевый / бирюзовый) нет, шрифты регистрируются."""
import re
from pathlib import Path

import pytest
from PySide6.QtGui import QColor, QFont

from remap.ui import theme

UI_DIR = Path(theme.__file__).parent
OLD_PALETTE = ["#E18147", "#EA9564", "#6B4632", "#4D3628", "#3A3224", "#4FB0C6", "#74C4D6"]
LEGACY_KEYS = ["bg", "surface", "surface_hover", "border", "text", "text_muted", "text_faint", "accent",
               "accent_hover", "on_accent", "success", "error", "warning", "warning_bg", "selection",
               "accent_muted", "reverse", "reverse_hover"]


def _constants():
    return {k: v for k, v in vars(theme).items() if k.isupper() and not k.startswith("_")}


def test_hex_constants_are_valid_colors():
    hexes = {k: v for k, v in _constants().items() if isinstance(v, str) and v.startswith("#")}
    assert len(hexes) > 40
    assert all(QColor(v).isValid() and re.fullmatch(r"#[0-9A-Fa-f]{6}", v) for v in hexes.values())


def test_rgba_constants_are_valid():
    rgba = {k: v for k, v in _constants().items() if isinstance(v, tuple) and len(v) == 4}
    assert {"SCREEN_GRID", "CHIP_BG", "WARN_BG", "ERR_BG"} <= set(rgba)
    for v in rgba.values():
        assert all(0 <= x <= 255 for x in v[:3]) and 0 < v[3] <= 1
        assert theme.qcolor(v).isValid() and re.fullmatch(r"rgba\(\d+, \d+, \d+, \d+%\)", theme.qss_rgba(v))
    assert theme.qss_rgba(theme.CHIP_BG) == "rgba(110, 190, 140, 7%)"


def test_legacy_layer_maps_every_old_key():
    assert theme.TOKENS is theme.LEGACY
    assert list(theme.LEGACY) == LEGACY_KEYS
    assert all(QColor(v).isValid() for v in theme.LEGACY.values())
    assert theme.LEGACY["reverse"] == theme.LEGACY["accent"]  # направления цветом не различаем


def test_no_old_palette_left_in_ui():
    for path in UI_DIR.glob("*.py"):
        text = path.read_text(encoding="utf-8").upper()
        assert not [h for h in OLD_PALETTE if h.upper() in text], path.name


def test_stylesheet_builds():
    css = theme.stylesheet()
    assert "QToolTip" in css and theme.TOOLTIP_BG in css and theme.BODY_TOP in css
    assert "{t[" not in css and "{{" not in css and "None" not in css


def test_logo_path_constant_does_not_require_file():
    assert theme.LOGO_SVG.name == "logo.svg" and theme.LOGO_SVG.parent.name == "textures"


def test_font_files_are_packaged():
    fonts = Path(str(theme.ASSETS / "fonts"))
    for name in (theme.MONO_FILE, *theme.LABEL_FILES, "OFL-MartianMono.txt", "OFL-BarlowCondensed.txt"):
        assert (fonts / name).is_file(), name


@pytest.mark.ui
def test_load_fonts_registers_both_families(app):
    fam = theme.load_fonts()
    assert fam == {"mono": "Martian Mono", "label": "Barlow Condensed"}
    from PySide6.QtGui import QFontDatabase
    assert {"Martian Mono", "Barlow Condensed"} <= set(QFontDatabase.families())


@pytest.mark.ui
def test_font_helpers(app):
    theme.load_fonts()
    from PySide6.QtGui import QFontMetrics
    wide = QFont("Martian Mono")
    wide.setPixelSize(20)
    narrow = theme.mono_font(20)
    assert narrow.family() == "Martian Mono" and narrow.pixelSize() == 20
    assert QFontMetrics(narrow).horizontalAdvance("MMMM") < QFontMetrics(wide).horizontalAdvance("MMMM")  # wdth 75
    lab = theme.label_font(12)
    assert lab.family() == "Barlow Condensed" and lab.weight() == QFont.Weight.DemiBold
    assert lab.capitalization() == QFont.Capitalization.AllUppercase and lab.letterSpacing() == pytest.approx(12 * 0.13, abs=0.05)


def test_missing_font_file_only_warns(monkeypatch, caplog):
    monkeypatch.setattr(theme, "ASSETS", Path("no-such-assets-dir"))
    monkeypatch.setattr(theme, "MONO_FAMILY", "Martian Mono")
    with caplog.at_level("WARNING"):
        fam = theme.load_fonts()
    assert fam["mono"] == "Martian Mono" and "font not loaded" in caplog.text
