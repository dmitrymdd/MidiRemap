"""Цветовые токены и таблица стилей Qt (тёмная тема; светлая — позже)."""

TOKENS = {
    "bg": "#1E1E1E",
    "surface": "#2A2A2A",
    "surface_hover": "#333333",
    "border": "#3A3A3A",
    "text": "#E6E6E6",
    "text_muted": "#9A9A9A",
    "text_faint": "#6E6E6E",
    "accent": "#E18147",
    "accent_hover": "#EA9564",
    "on_accent": "#1E1E1E",
    "success": "#6CC28A",
    "error": "#E5636B",
}


def stylesheet(t: dict[str, str] = TOKENS) -> str:
    return f"""
    QWidget {{ background: {t['bg']}; color: {t['text']}; font-family: "Segoe UI"; font-size: 10pt; }}
    QLabel#title {{ font-size: 20pt; font-weight: 600; }}
    QLabel#subtitle, QLabel#muted {{ color: {t['text_muted']}; }}
    QLabel#section {{ color: {t['text_muted']}; font-size: 8pt; font-weight: 700; letter-spacing: 1px; }}
    QLabel#hint {{ color: {t['text_faint']}; font-size: 8pt; }}
    QLabel#logo {{ background: {t['accent']}; color: {t['on_accent']}; font-size: 14pt; font-weight: 700;
                   border-radius: 6px; }}
    QFrame#card, QFrame#drop {{ background: {t['surface']}; border: 1px solid {t['border']}; border-radius: 8px; }}
    QFrame#drop {{ border: 2px dashed {t['border']}; }}
    QFrame#drop[active="true"] {{ border-color: {t['accent']}; }}
    QFrame#card[state="ok"] {{ border-color: {t['success']}; }}
    QFrame#card * , QFrame#drop * {{ background: transparent; border: none; }}
    QLabel#icon {{ color: {t['accent']}; font-size: 16pt; }}
    QLabel#cardName {{ font-weight: 600; }}
    QPushButton {{ background: {t['surface']}; border: 1px solid {t['border']}; border-radius: 6px;
                   padding: 7px 14px; }}
    QPushButton:hover {{ background: {t['surface_hover']}; }}
    QPushButton:disabled {{ color: {t['text_faint']}; }}
    QPushButton#primary {{ background: {t['accent']}; color: {t['on_accent']}; border: none; font-weight: 600; }}
    QPushButton#primary:hover {{ background: {t['accent_hover']}; }}
    QComboBox {{ background: {t['surface']}; border: 1px solid {t['border']}; border-radius: 6px;
                 padding: 5px 10px; }}
    QComboBox:hover {{ border-color: {t['accent']}; }}
    QComboBox QAbstractItemView {{ background: {t['surface']}; border: 1px solid {t['border']};
                                   selection-background-color: {t['accent']};
                                   selection-color: {t['on_accent']}; }}
    QPlainTextEdit {{ background: {t['surface']}; border: 1px solid {t['border']}; border-radius: 8px;
                      padding: 6px; font-family: Consolas, "Cascadia Mono", monospace; font-size: 9pt; }}
    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: {t['border']}; border-radius: 3px; min-height: 24px; }}
    QScrollBar::handle:vertical:hover {{ background: {t['text_faint']}; }}
    QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{
        background: none; height: 0; }}
    QLabel#status {{ color: {t['text_muted']}; }}
    QLabel#status[state="ok"] {{ color: {t['success']}; }}
    QLabel#status[state="error"] {{ color: {t['error']}; }}
    """
