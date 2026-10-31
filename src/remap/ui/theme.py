"""Цвета, шрифты и таблица стилей Qt. Тема одна: тёмный металлический корпус и зелёные «экраны».

Токены — константы модуля, сгруппированные по областям; цвета — строки `#RRGGBB`, полупрозрачные — кортежи
`(r, g, b, alpha)` с `qss_rgba()` / `qcolor()` для QSS и рисования. Шрифты лежат в `assets/fonts` и
регистрируются `load_fonts()`.
"""

import logging
from importlib import resources
from pathlib import Path

from PySide6.QtGui import QColor, QFont, QFontDatabase
from PySide6.QtWidgets import QApplication

log = logging.getLogger(__name__)

RGBA = tuple[int, int, int, float]

# --- Корпус ---
BODY_TOP, BODY_MID, BODY_BOTTOM = "#1E2023", "#191B1D", "#141618"  # вертикальный градиент: 0 %, BODY_MID_AT, 100 %
BODY_MID_AT = 0.45
# Виньетка: эллипс rx×ry (доли ширины/высоты) с центром (cx, cy); прозрачна до BODY_VIGNETTE_FROM, затем до alpha
BODY_VIGNETTE = {"rx": 1.30, "ry": 1.10, "cx": 0.5, "cy": 0.4, "from": 0.55, "alpha": 0.38}
# Верхний свет: эллипс 85 %×55 % с центром на верхней кромке; белый alpha → прозрачный к BODY_TOPLIGHT_TO
BODY_TOPLIGHT = {"rx": 0.85, "ry": 0.55, "cx": 0.5, "cy": 0.0, "to": 0.70, "alpha": 0.055}
# Линии по краю корпуса (inset-тени макета): верхняя светлая, рамка 1 px, нижняя тёмная
BODY_EDGE_LIGHT: RGBA = (255, 255, 255, 0.12)
BODY_EDGE_FRAME = "#0A0B0C"
BODY_EDGE_DARK: RGBA = (0, 0, 0, 0.6)
# Утопленный блок (под экраны)
RECESS_TOP, RECESS_BOTTOM, RECESS_RADIUS = "#070808", "#0D0E10", 12

# --- Клавиши: лицо — рамка 1 px, градиент, две inset-линии, внешняя тень; поверх — текстура ---
KEY_TOP, KEY_BOTTOM, KEY_BORDER, KEY_RADIUS = "#282B2F", "#1C1E21", "#08090A", 7
KEY_LABEL = "#C3C9CE"
KEY_LABEL_HOVER = "#E6EAED"  # наведение; в макете не задано
KEY_SWAP_ICON = "#F4F6F7"  # стрелки «⇄» не меняют цвет с состоянием клавиши
KEY_INSET_LIGHT: RGBA = (255, 255, 255, 0.11)  # inset 0 1px 0
KEY_INSET_DARK: RGBA = (0, 0, 0, 0.4)  # inset 0 -1px 0
KEY_SHADOW = {"dy": 2, "blur": 4, "alpha": 0.6}  # outer 0 2px 4px rgba(0,0,0,.6)
KEY_PRESSED_TOP, KEY_PRESSED_BOTTOM = "#131517", "#1A1C1F"  # нажата и включена — один вид
KEY_PRESSED_SHADOW = {"dy": 2, "blur": 4, "alpha": 0.8}  # inset 0 2px 4px rgba(0,0,0,.8)
KEY_PRESSED_EDGE: RGBA = (255, 255, 255, 0.06)  # outer 0 1px 0: светлая линия под нажатой
KEY_HOVER_TOP, KEY_HOVER_BOTTOM = "#30343A", "#22252A"  # наведение; в макете не задано
KEY_FOCUS_RING, KEY_FOCUS_GAP = "#8FC7A3", 1  # контур 1 px (как у кнопки логотипа), зазор от лица: поля клавиши малы
KEY_BADGE, KEY_BADGE_SIZE, KEY_BADGE_INSET = "#FFFFFF", 5, 5  # точка «не сохранено» у правого верхнего угла
KEY_BADGE_GLOW: RGBA = (255, 255, 255, 0.7)  # свечение 0 0 4px
KEY_BADGE_GLOW_BLUR = 4
# Большая клавиша CONVERT: другой градиент и тени
KEY_GO_TOP, KEY_GO_BOTTOM, KEY_GO_RADIUS = "#2A2D31", "#1C1E21", 10
KEY_GO_INSET_LIGHT: RGBA = (255, 255, 255, 0.13)  # inset 0 1px 0
KEY_GO_INSET_DARK: RGBA = (0, 0, 0, 0.45)  # inset 0 -2px 0
KEY_GO_SHADOW = {"dy": 3, "blur": 6, "alpha": 0.65}  # outer 0 3px 6px rgba(0,0,0,.65)
# Размеры лица клавиш (с рамкой), px; None — по тексту и полям
KEY_TAB_SIZE, KEY_HELP_SIZE, KEY_SQUARE_SIZE = (118, 36), (36, 36), (38, 38)
KEY_SWAP_SIZE, KEY_MAP_SIZE, KEY_CLOSE_SIZE, KEY_GO_SIZE = (44, 38), (48, 38), (34, 34), (268, 68)
KEY_TUT_HEIGHT, KEY_TUT_PAD = 36, 16
# Подпись клавиш: Barlow Condensed, px / межбуквенный интервал в em / зазор значок–подпись / поле по бокам
KEY_TAB_FONT, KEY_TAB_SPACING, KEY_TAB_GAP, KEY_TAB_PAD = 13.5, 0.12, 8, 13
KEY_HELP_FONT = 18
KEY_TUT_FONT, KEY_TUT_SPACING = 14, 0.14
KEY_GO_FONT, KEY_GO_SPACING, KEY_GO_GAP = 20, 0.22, 14

# --- Винты и шелкография ---
SCREW_LIGHT, SCREW_MID, SCREW_DARK, SCREW_RIM = "#8A9096", "#3A3E43", "#16181A", "#08090A"
SCREW_HIGHLIGHT: RGBA = (255, 255, 255, 0.08)  # мягкий блик под ободом
SCREW_SLOT = "#0A0B0C"
SCREW_SLOT_LIGHT: RGBA = (255, 255, 255, 0.12)  # светлая копия шлица, сдвинутая на (+0.6, +0.6)
SILK_TEXT = "#9AA1A8"
SILK_FAINT = "#6B7278"  # приглушённая шелкография (недоступное, подсказки); в макете не задано
KEY_LABEL_DISABLED = SILK_FAINT  # недоступная клавиша; в макете не задано

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

# --- Подсказка: у Qt она квадратная, с системной тенью (скругление и тень макета в QSS недоступны) ---
TOOLTIP_BG, TOOLTIP_BORDER, TOOLTIP_TEXT = "#0B0C0E", "#3A3F44", "#D5DADF"
TOOLTIP_PX = 10
# Поля задаём в QSS половинными: Qt считает padding и рамку дважды (рамка виджета + `margin` метки QTipLabel =
# 1 + padding + рамка) и ещё 1 px своего отступа, так что от края до текста выходит 2·(padding + 1) + 2 — по вертикали
# 10, по горизонтали 12 px (в макете плашка: рамка 1 + поле 8 / 10 = 9 / 11).
TOOLTIP_PAD_Y, TOOLTIP_PAD_X = 3, 4
TOOLTIP_MAX_WIDTH = 290  # QSS не умеет ограничивать ширину подсказки: переносы — на стороне текста (`tips.tip()`)
TOOLTIP_TEXT_WIDTH = TOOLTIP_MAX_WIDTH - 2 * (2 * (TOOLTIP_PAD_X + 1) + 2)  # 266: колонка текста
TOOLTIP_LINE_HEIGHT = 150  # %

# --- Шрифты ---
MONO_FILE = "MartianMono.ttf"
LABEL_FILES = ("BarlowCondensed-Medium.ttf", "BarlowCondensed-SemiBold.ttf")
MONO_FAMILY = "Martian Mono"  # реальные имена выставляет load_fonts()
LABEL_FAMILY = "Barlow Condensed"
MONO_WIDTH = 75.0  # ось wdth Martian Mono (75–112.5)
LABEL_SPACING = 0.13  # межбуквенный интервал подписей по умолчанию, в em
APP_FONT_PX = 12  # шрифт приложения по умолчанию: Martian Mono 12 px, wdth 75
PX_TO_PT = 0.75  # 96 dpi: размер в px × 0.75 = размер в pt (дробные px, например 13.5, — только так)

# --- Металл: две текстуры поверх любой металлической поверхности (файлы в assets/textures) ---
METAL_BRUSHED_FILE, METAL_BRUSHED_TILE, METAL_BRUSHED_OPACITY = "metal009_brushed_tile.png", 512, 0.02  # шлифовка
METAL_SCRATCH_FILE, METAL_SCRATCH_TILE, METAL_SCRATCH_OPACITY = "metal031_scratch_tile.png", 1024, 0.025  # царапины
# плитка — логический размер в пикселях (картинка 1024² при 512 = DPR 2, 2048² при 1024 = DPR 2)

# --- Утопленный блок: тень внутри и три внешние линии ---
RECESS_SHADOW_DY, RECESS_SHADOW_BLUR, RECESS_SHADOW_ALPHA = 2, 4, 0.95  # inset 0 2px 4px rgba(0,0,0,.95)
RECESS_EDGE_DARK: RGBA = (0, 0, 0, 0.55)  # 0 -1px 0: тёмная линия над блоком
RECESS_EDGE_LIGHT: RGBA = (255, 255, 255, 0.11)  # 0 1px 0: светлая под блоком
RECESS_EDGE_FAINT: RGBA = (255, 255, 255, 0.03)  # 0 2px 0: вторая, едва заметная
RECESS_EDGE_TOP, RECESS_EDGE_BOTTOM = 1, 2  # px, которые виджет блока резервирует над и под рамкой блока
RECESS_PAD = 6  # поля содержимого блока по умолчанию

# --- Панель внутри блока («верхняя полоса»): градиент, радиус 7, светлая линия сверху ---
PANEL_TOP, PANEL_BOTTOM, PANEL_RADIUS = "#1C1E21", "#17191B", 7
PANEL_EDGE_LIGHT: RGBA = (255, 255, 255, 0.06)

# --- Винты корпуса: квадрат 14 px, левый верхний угол в 11 px от углов окна ---
SCREW_SIZE, SCREW_INSET = 14, 11

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


def _sized(font: QFont, px: float, weight: QFont.Weight) -> QFont:
    """Размер в px (допустимы дробные: 13.5, 12.5, 8.5) через pt: `setPixelSize` принимает только целые. Без хинтинга
    и со сглаживанием — ближе к тексту браузера, по которому нарисован макет."""
    font.setPointSizeF(px * PX_TO_PT)
    font.setWeight(weight)
    font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    return font


def mono_font(px: float, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
    """Martian Mono, узкая ширина (wdth 75)."""
    f = _sized(QFont(MONO_FAMILY), px, weight)
    f.setVariableAxis(QFont.Tag("wdth"), MONO_WIDTH)
    return f


def label_font(px: float, weight: QFont.Weight = QFont.Weight.DemiBold, spacing: float = LABEL_SPACING) -> QFont:
    """Barlow Condensed, заглавные, разрядка `spacing` em (по умолчанию 0.13)."""
    f = _sized(QFont(LABEL_FAMILY), px, weight)
    f.setCapitalization(QFont.Capitalization.AllUppercase)
    f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, px * spacing)
    return f


def install_app_font() -> QFont:
    """Шрифт приложения по умолчанию — Martian Mono 12 px (wdth 75), как корень макета. Вызывается после
    `load_fonts()` и до стилей; в QSS шрифт `QWidget` не задаётся, иначе он перекроет этот."""
    font = mono_font(APP_FONT_PX)
    QApplication.setFont(font)
    return font


def stylesheet(t: dict[str, str] = TOKENS) -> str:
    mono, label = f'"{MONO_FAMILY}"', f'"{LABEL_FAMILY}"'
    body = (f"qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {BODY_TOP}, stop:{BODY_MID_AT} {BODY_MID}, "
            f"stop:1 {BODY_BOTTOM})")
    key = f"qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {KEY_TOP}, stop:1 {KEY_BOTTOM})"
    key_hover = f"qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {KEY_HOVER_TOP}, stop:1 {KEY_HOVER_BOTTOM})"
    key_down = f"qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {KEY_PRESSED_TOP}, stop:1 {KEY_PRESSED_BOTTOM})"
    return f"""
    QWidget {{ background: transparent; color: {t['text']}; }}  /* шрифт — приложения (install_app_font) */
    QMainWindow {{ background: {BODY_BOTTOM}; }}  /* металл центрального виджета рисует ui/metal.py */
    QDialog {{ background: {body}; }}
    QToolTip {{ background: {TOOLTIP_BG}; color: {TOOLTIP_TEXT}; border: 1px solid {TOOLTIP_BORDER};
                padding: {TOOLTIP_PAD_Y}px {TOOLTIP_PAD_X}px; font-family: {mono}; font-size: {TOOLTIP_PX}px; }}
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
