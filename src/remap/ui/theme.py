"""Цвета, шрифты и таблица стилей Qt. Тема одна: тёмный металлический корпус и зелёные «экраны».

Токены — константы модуля, сгруппированные по областям; цвета — строки `#RRGGBB`, полупрозрачные — кортежи
`(r, g, b, alpha)` с `qss_rgba()` / `qcolor()` для QSS и рисования. Шрифты лежат в `assets/fonts` и
регистрируются `load_fonts()`.
"""

import logging
from importlib import resources
from pathlib import Path

from PySide6.QtGui import QColor, QFont, QFontDatabase

log = logging.getLogger(__name__)

RGBA = tuple[int, int, int, float]

# --- Корпус ---
BODY_TOP, BODY_BOTTOM = "#1E2023", "#141618"  # вертикальный градиент
# Утопленный блок (под экраны)
RECESS_TOP, RECESS_BOTTOM, RECESS_RADIUS = "#070808", "#0D0E10", 12

# --- Клавиши ---
KEY_TOP, KEY_BOTTOM, KEY_BORDER, KEY_RADIUS = "#282B2F", "#1C1E21", "#08090A", 7
KEY_LABEL = "#C3C9CE"
KEY_PRESSED_TOP, KEY_PRESSED_BOTTOM = "#131517", "#1A1C1F"
KEY_HOVER_TOP, KEY_HOVER_BOTTOM = "#30343A", "#22252A"  # наведение; в макете не задано

# --- Винты и шелкография ---
SCREW_LIGHT, SCREW_MID, SCREW_DARK, SCREW_RIM = "#8A9096", "#3A3E43", "#16181A", "#08090A"
SILK_TEXT = "#9AA1A8"
SILK_FAINT = "#6B7278"  # приглушённая шелкография (недоступное, подсказки); в макете не задано

# --- Экран (зелёное стекло) ---
SCREEN_GLASS_INNER, SCREEN_GLASS_MID, SCREEN_GLASS_OUTER = "#132A1F", "#0D1C15", "#0A1711"  # радиальный
SCREEN_BORDER, SCREEN_RADIUS = "#21412F", 7
SCREEN_GRID: RGBA = (127, 181, 150, 0.13)  # крест сетки (#7FB596), шаг SCREEN_GRID_STEP
SCREEN_GRID_STEP = 32
CHIP_BORDER, CHIP_RADIUS = "#477A5C", 5
CHIP_BG: RGBA = (110, 190, 140, 0.07)
SCREEN_TEXT, SCREEN_TEXT_2, SCREEN_TEXT_3 = "#E6F2EA", "#8FC7A3", "#74A487"
SCREEN_DIVIDER = "#21412F"
SCREEN_BTN_BORDER, SCREEN_BTN_TEXT = "#2A4C38", "#CBE3D3"  # вторичная кнопка на экране

# --- Акцент, выбор, кабель ---
ACCENT = "#62D69A"
ACCENT_HOVER = "#86E3B3"  # наведение; в макете не задано
SELECTED = "#FFFFFF"
CABLE, CABLE_WIDTH = "#82BC98", 1.5

# --- Статусы: светодиод, текст, рамка, фон ---
OK_LED, OK_TEXT, OK_BORDER = "#62D69A", "#8FC7A3", "#477A5C"
WARN_LED, WARN_TEXT, WARN_BORDER, WARN_BG = "#E3D36B", "#E6DA8E", "#6F7748", (227, 211, 107, 0.06)
ERR_LED, ERR_TEXT, ERR_BORDER, ERR_BG = "#F0646E", "#F2939A", "#7C4248", (240, 100, 110, 0.07)

# --- Подсказка ---
TOOLTIP_BG, TOOLTIP_BORDER, TOOLTIP_RADIUS, TOOLTIP_TEXT = "#0B0C0E", "#3A3F44", 4, "#D5DADF"
TOOLTIP_PX = 10
TOOLTIP_MAX_WIDTH = 290  # QSS не умеет ограничивать ширину подсказки: переносы — на стороне текста

# --- Шрифты ---
MONO_FILE = "MartianMono.ttf"
LABEL_FILES = ("BarlowCondensed-Medium.ttf", "BarlowCondensed-SemiBold.ttf")
MONO_FAMILY = "Martian Mono"  # реальные имена выставляет load_fonts()
LABEL_FAMILY = "Barlow Condensed"
MONO_WIDTH = 75.0  # ось wdth Martian Mono (75–112.5)
LABEL_SPACING = 0.13  # межбуквенный интервал подписей, в em

# --- Металл: две текстуры поверх любой металлической поверхности (файлы в assets/textures) ---
METAL_BRUSHED_FILE, METAL_BRUSHED_TILE, METAL_BRUSHED_OPACITY = "metal009_brushed_tile.png", 512, 0.02  # шлифовка
METAL_SCRATCH_FILE, METAL_SCRATCH_TILE, METAL_SCRATCH_OPACITY = "metal031_scratch_tile.png", 1024, 0.025  # царапины
# плитка — логический размер в пикселях (картинка 1024² при 512 = DPR 2, 2048² при 1024 = DPR 2)

# --- Утопленный блок: тень внутри и светлая кромка под ним ---
RECESS_SHADOW_DY, RECESS_SHADOW_BLUR, RECESS_SHADOW_ALPHA = 2, 4, 0.95  # inset 0 2px 4px rgba(0,0,0,.95)
RECESS_EDGE_LIGHT: RGBA = (255, 255, 255, 0.11)  # 0 1px 0 rgba(255,255,255,.11)
RECESS_EDGE = 1  # px под блоком под светлую кромку
RECESS_PAD = 10  # поля содержимого блока по умолчанию

# --- Винты корпуса ---
SCREW_SIZE, SCREW_INSET = 12, 12  # 12 = левое/правое поле страниц (24) минус размер винта: контролов не касается

# --- Ресурсы ---
ASSETS = resources.files("remap") / "assets"
LOGO_PNG = Path(str(ASSETS / "logo.png"))  # 2170×725 RGBA, используется позже; может отсутствовать


# Временный слой: старые ключи → новая палитра, чтобы страницы работали до перестройки. Убирается в шагах 3–5.
# Направления цветом не различаем: обратное (←) рисуется как прямое.
LEGACY = {
    "bg": RECESS_BOTTOM,
    "surface": KEY_TOP,
    "surface_hover": KEY_HOVER_TOP,
    "border": TOOLTIP_BORDER,
    "text": SCREEN_TEXT,
    "text_muted": SILK_TEXT,
    "text_faint": SILK_FAINT,
    "accent": ACCENT,
    "accent_hover": ACCENT_HOVER,
    "on_accent": SCREEN_GLASS_OUTER,
    "success": OK_LED,
    "error": ERR_LED,
    "warning": WARN_LED,
    "warning_bg": "#1A1A16",  # WARN_BG поверх RECESS_BOTTOM (в QColor нужен непрозрачный)
    "selection": SCREEN_BORDER,
    "accent_muted": CHIP_BORDER,
    "reverse": ACCENT,
    "reverse_hover": ACCENT_HOVER,
}
TOKENS = LEGACY


def qss_rgba(c: RGBA) -> str:
    r, g, b, a = c
    return f"rgba({r}, {g}, {b}, {round(a * 100)}%)"


def qcolor(c: str | RGBA) -> QColor:
    if isinstance(c, str):
        return QColor(c)
    r, g, b, a = c
    out = QColor(r, g, b)
    out.setAlphaF(a)
    return out


def load_fonts() -> dict[str, str]:
    """Регистрирует шрифты из assets/fonts; возвращает {"mono": семейство, "label": семейство}.
    Нет файла — предупреждение в лог, остаётся запасное имя семейства (шрифт подменит система)."""
    global MONO_FAMILY, LABEL_FAMILY
    fonts = ASSETS / "fonts"
    found: dict[str, str] = {}
    for kind, files in (("mono", (MONO_FILE,)), ("label", LABEL_FILES)):
        for name in files:
            path = Path(str(fonts / name))
            fid = QFontDatabase.addApplicationFont(str(path)) if path.is_file() else -1
            families = QFontDatabase.applicationFontFamilies(fid) if fid >= 0 else []
            if not families:
                log.warning("font not loaded: %s", path)
                continue
            found[kind] = families[0]
    MONO_FAMILY = found.get("mono", MONO_FAMILY)
    LABEL_FAMILY = found.get("label", LABEL_FAMILY)
    return {"mono": MONO_FAMILY, "label": LABEL_FAMILY}


def mono_font(px: int, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
    """Martian Mono, узкая ширина (wdth 75)."""
    f = QFont(MONO_FAMILY)
    f.setPixelSize(px)
    f.setWeight(weight)
    f.setVariableAxis(QFont.Tag("wdth"), MONO_WIDTH)
    return f


def label_font(px: int, weight: QFont.Weight = QFont.Weight.DemiBold) -> QFont:
    """Barlow Condensed, заглавные, разрядка ~0.13 em."""
    f = QFont(LABEL_FAMILY)
    f.setPixelSize(px)
    f.setWeight(weight)
    f.setCapitalization(QFont.Capitalization.AllUppercase)
    f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, px * LABEL_SPACING)
    return f


def stylesheet(t: dict[str, str] = TOKENS) -> str:
    mono, label = f'"{MONO_FAMILY}"', f'"{LABEL_FAMILY}"'
    body = f"qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {BODY_TOP}, stop:1 {BODY_BOTTOM})"
    key = f"qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {KEY_TOP}, stop:1 {KEY_BOTTOM})"
    key_hover = f"qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {KEY_HOVER_TOP}, stop:1 {KEY_HOVER_BOTTOM})"
    key_down = f"qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {KEY_PRESSED_TOP}, stop:1 {KEY_PRESSED_BOTTOM})"
    return f"""
    QWidget {{ background: transparent; color: {t['text']}; font-family: "Segoe UI"; font-size: 10pt; }}
    QMainWindow {{ background: {BODY_BOTTOM}; }}  /* металл центрального виджета рисует ui/metal.py */
    QDialog {{ background: {body}; }}
    QToolTip {{ background: {TOOLTIP_BG}; color: {TOOLTIP_TEXT}; border: 1px solid {TOOLTIP_BORDER};
                border-radius: {TOOLTIP_RADIUS}px; padding: 4px 6px; font-family: {mono};
                font-size: {TOOLTIP_PX}px; }}
    QLabel#title {{ font-size: 20pt; font-weight: 600; }}
    QLabel#subtitle, QLabel#muted {{ color: {t['text_muted']}; }}
    QLabel#section {{ color: {t['text_muted']}; font-family: {label}; font-size: 10pt; font-weight: 600; }}
    QLabel#columnTitle {{ color: {t['text_muted']}; font-family: {label}; font-weight: 600; padding-left: 4px; }}
    QLabel#hint {{ color: {t['text_faint']}; font-size: 8pt; }}
    QLabel#logo {{ background: {t['accent']}; color: {t['on_accent']}; font-size: 14pt; font-weight: 700;
                   border-radius: 6px; }}
    QFrame#card, QFrame#drop {{ background: {t['surface']}; border: 1px solid {t['border']}; border-radius: 8px; }}
    QFrame#drop {{ border: 2px dashed {t['border']}; }}
    QFrame#drop[loaded="true"] {{ border-style: solid; }}
    QFrame#drop:hover {{ background: {t['surface_hover']}; }}
    QFrame#drop[active="true"] {{ border-color: {t['accent']}; }}
    QFrame#card[state="ok"] {{ border-color: {t['success']}; }}
    QFrame#card[state="ok"]:hover {{ background: {t['surface_hover']}; }}
    QFrame#card * , QFrame#drop * {{ background: transparent; border: none; }}
    QFrame#card[state="off"] QLabel {{ color: {t['text_faint']}; }}
    QLabel#icon {{ color: {t['accent']}; font-size: 16pt; }}
    QLabel#cardName {{ font-weight: 600; }}
    QPushButton {{ background: {key}; color: {KEY_LABEL}; border: 1px solid {KEY_BORDER};
                   border-radius: {KEY_RADIUS}px; padding: 7px 14px; }}
    QPushButton:hover {{ background: {key_hover}; }}
    QPushButton:pressed {{ background: {key_down}; }}
    QPushButton:disabled {{ color: {t['text_faint']}; }}
    QPushButton#primary {{ background: {t['accent']}; color: {t['on_accent']}; border: none; font-weight: 600; }}
    QPushButton#primary:hover {{ background: {t['accent_hover']}; }}
    QPushButton#primary:disabled {{ background: {key}; color: {t['text_faint']};
                                    border: 1px solid {KEY_BORDER}; font-weight: 400; }}
    QComboBox {{ background: {t['surface']}; border: 1px solid {t['border']}; border-radius: 6px;
                 padding: 5px 24px 5px 10px; font-family: {mono}; font-size: 12px; }}
    QComboBox:hover {{ border-color: {t['accent']}; }}
    /* стрелку рисует ui/combo.py (ComboBox): у ::drop-down своей рамки нет — иначе справа двойная граница */
    QComboBox::drop-down {{ subcontrol-origin: padding; subcontrol-position: center right; width: 20px;
                            border: none; background: transparent; }}
    QComboBox::down-arrow {{ image: none; width: 0; height: 0; }}
    QComboBox QAbstractItemView {{ background: {t['surface']}; border: 1px solid {t['border']};
                                   selection-background-color: {t['accent']};
                                   selection-color: {t['on_accent']}; }}
    QPlainTextEdit {{ background: {t['bg']}; border: 1px solid {t['border']}; border-radius: 8px;
                      padding: 6px; font-family: {mono}; font-size: 12px; }}
    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: {t['border']}; border-radius: 3px; min-height: 24px; }}
    QScrollBar::handle:vertical:hover {{ background: {t['text_faint']}; }}
    QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{
        background: none; height: 0; }}
    QLabel#status {{ color: {t['text_muted']}; }}
    QLabel#status[state="ok"] {{ color: {OK_TEXT}; }}
    QLabel#status[state="error"] {{ color: {ERR_TEXT}; }}

    QPushButton#navTab {{ background: transparent; border: none; border-bottom: 2px solid transparent;
                          border-radius: 0; padding: 6px 12px; color: {t['text_muted']}; font-family: {label};
                          font-size: 11pt; font-weight: 600; }}
    QPushButton#navTab:hover {{ color: {t['text']}; }}
    QPushButton#navTab:checked {{ color: {t['accent']}; border-bottom-color: {t['accent']}; }}
    QListWidget, QTableView, QTreeWidget {{ background: {t['bg']}; border: 1px solid {t['border']}; border-radius: 8px;
                               outline: none; font-family: {mono}; font-size: 12px; }}
    QTableView {{ gridline-color: {t['border']}; selection-background-color: {t['selection']};
                  selection-color: {t['text']}; }}
    QHeaderView::section {{ background: {t['bg']}; color: {t['text_muted']}; border: none;
                            border-bottom: 1px solid {t['border']}; padding: 4px 6px; font-family: {label};
                            font-size: 10pt; font-weight: 600; }}
    QTableView QLineEdit {{ border-radius: 0; padding: 0 4px; }}
    QLineEdit {{ background: {t['bg']}; border: 1px solid {t['border']}; border-radius: 6px;
                 padding: 5px 8px; font-family: {mono}; font-size: 12px; selection-background-color: {t['accent']};
                 selection-color: {t['on_accent']}; }}
    QLineEdit:focus {{ border-color: {t['accent']}; }}
    QMenu {{ background: {t['surface']}; border: 1px solid {t['border']}; padding: 4px; }}
    QMenu::item {{ padding: 6px 18px; border-radius: 4px; }}
    QMenu::item:selected {{ background: {t['accent']}; color: {t['on_accent']}; }}
    QCheckBox::indicator, QTableView::indicator {{ width: 14px; height: 14px; border: 1px solid {t['text_faint']};
                                                   border-radius: 3px; background: {t['bg']}; }}
    QCheckBox::indicator:checked, QTableView::indicator:checked {{ background: {t['accent']};
                                                                   border-color: {t['accent']}; }}
    QCheckBox::indicator:hover, QTableView::indicator:hover {{ border-color: {t['accent']}; }}
    QCheckBox::indicator:disabled, QTableView::indicator:disabled {{ border-color: {t['border']};
                                                                     background: {t['surface']}; }}
    QCheckBox::indicator:checked:disabled, QTableView::indicator:checked:disabled {{
        background: {t['accent_muted']}; border-color: {t['accent_muted']}; }}
    QPushButton#direction {{ color: {t['accent']}; font-size: 13pt; padding: 0 6px; }}
    QPushButton#direction[dir="reverse"] {{ color: {t['reverse']}; }}
    QPushButton#direction:disabled {{ color: {t['text_faint']}; }}
    QPushButton#iconButton {{ font-size: 14pt; padding: 1px 12px; color: {t['text_muted']}; }}
    QPushButton#iconButton:hover {{ color: {t['text']}; }}
    QPushButton#iconButton::menu-indicator {{ image: none; width: 0; }}
    QFrame#suggestBar {{ background: {t['surface']}; border: 1px dashed {t['accent_muted']}; border-radius: 6px; }}
    QFrame#suggestBar QLabel {{ background: transparent; color: {t['text_muted']}; }}
    QPushButton#link {{ background: transparent; border: none; padding: 3px 6px; color: {t['accent']};
                        font-weight: 600; }}
    QPushButton#link:hover {{ color: {t['accent_hover']}; }}
    QPushButton#link:disabled {{ color: {t['text_faint']}; }}
    QPushButton#remove {{ background: transparent; border: none; padding: 0; color: {t['text_faint']}; }}
    QPushButton#remove:hover {{ color: {t['accent']}; }}
    QGraphicsView#cables {{ background: {t['bg']}; border: 1px solid {t['border']}; border-radius: 8px; }}
    QLabel#mapTitle {{ font-size: 14pt; font-weight: 600; }}
    QLabel#chip {{ border: 1px solid {CHIP_BORDER}; border-radius: 9px; padding: 1px 8px; font-size: 8pt;
                   font-weight: 700; color: {t['text_muted']}; }}
    QLabel#chip[state="ok"] {{ color: {OK_TEXT}; border-color: {OK_BORDER}; }}
    QLabel#chip[state="warn"] {{ color: {WARN_TEXT}; border-color: {WARN_BORDER}; }}
    QLabel#dirty {{ color: {t['accent']}; font-weight: 600; }}
    QLabel#issues {{ color: {WARN_TEXT}; }}
    QLabel#issues[state="error"] {{ color: {ERR_TEXT}; }}
    """


def repolish(w, prop: str, value: str) -> None:
    """Сменить динамическое свойство виджета и применить стили, зависящие от него."""
    w.setProperty(prop, value)
    w.style().unpolish(w)
    w.style().polish(w)
