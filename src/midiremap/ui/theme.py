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
    "warning": "#D9A84E",
    "warning_bg": "#3A3224",  # фон строк артикуляций с дублями без основной ноты
    "error_bg": "#40282A",
    "selection": "#4D3628",
    "accent_muted": "#6B4632",  # отмеченный, но неактивный флажок
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
    QFrame#drop[loaded="true"] {{ border-style: solid; }}
    QFrame#drop:hover {{ background: {t['surface_hover']}; }}
    QFrame#drop[active="true"] {{ border-color: {t['accent']}; }}
    QFrame#card[state="ok"] {{ border-color: {t['success']}; }}
    QFrame#card[state="ok"]:hover {{ background: {t['surface_hover']}; }}
    QFrame#card * , QFrame#drop * {{ background: transparent; border: none; }}
    QFrame#card[state="off"] QLabel {{ color: {t['text_faint']}; }}
    QLabel#icon {{ color: {t['accent']}; font-size: 16pt; }}
    QLabel#cardName {{ font-weight: 600; }}
    QPushButton {{ background: {t['surface']}; border: 1px solid {t['border']}; border-radius: 6px;
                   padding: 7px 14px; }}
    QPushButton:hover {{ background: {t['surface_hover']}; }}
    QPushButton:disabled {{ color: {t['text_faint']}; }}
    QPushButton#primary {{ background: {t['accent']}; color: {t['on_accent']}; border: none; font-weight: 600; }}
    QPushButton#primary:hover {{ background: {t['accent_hover']}; }}
    QPushButton#primary:disabled {{ background: {t['surface']}; color: {t['text_faint']};
                                    border: 1px solid {t['border']}; font-weight: 400; }}
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

    QPushButton#navTab {{ background: transparent; border: none; border-bottom: 2px solid transparent;
                          border-radius: 0; padding: 6px 12px; color: {t['text_muted']}; font-weight: 600; }}
    QPushButton#navTab:hover {{ color: {t['text']}; }}
    QPushButton#navTab:checked {{ color: {t['accent']}; border-bottom-color: {t['accent']}; }}
    QListWidget, QTableView, QTreeWidget {{ background: {t['surface']}; border: 1px solid {t['border']}; border-radius: 8px;
                               outline: none; }}
    QTableView {{ gridline-color: {t['border']}; selection-background-color: {t['selection']};
                  selection-color: {t['text']}; }}
    QHeaderView::section {{ background: {t['bg']}; color: {t['text_muted']}; border: none;
                            border-bottom: 1px solid {t['border']}; padding: 4px 6px; font-size: 8pt;
                            font-weight: 700; }}
    QTableView QLineEdit {{ border-radius: 0; padding: 0 4px; }}
    QLineEdit {{ background: {t['surface']}; border: 1px solid {t['border']}; border-radius: 6px;
                 padding: 5px 8px; selection-background-color: {t['accent']};
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
    QPushButton#segment {{ padding: 5px 12px; color: {t['text_muted']}; }}
    QPushButton#segment:checked {{ color: {t['accent']}; border-color: {t['accent']}; }}
    QGraphicsView#cables {{ background: {t['bg']}; border: 1px solid {t['border']}; border-radius: 8px; }}
    QLabel#mapTitle {{ font-size: 14pt; font-weight: 600; }}
    QLabel#chip {{ border: 1px solid {t['border']}; border-radius: 9px; padding: 1px 8px; font-size: 8pt;
                   font-weight: 700; color: {t['text_muted']}; }}
    QLabel#chip[state="ok"] {{ color: {t['success']}; border-color: {t['success']}; }}
    QLabel#chip[state="warn"] {{ color: {t['warning']}; border-color: {t['warning']}; }}
    QLabel#dirty {{ color: {t['accent']}; font-weight: 600; }}
    QLabel#issues {{ color: {t['warning']}; }}
    QLabel#issues[state="error"] {{ color: {t['error']}; }}
    """


def repolish(w, prop: str, value: str) -> None:
    """Сменить динамическое свойство виджета и применить стили, зависящие от него."""
    w.setProperty(prop, value)
    w.style().unpolish(w)
    w.style().polish(w)
