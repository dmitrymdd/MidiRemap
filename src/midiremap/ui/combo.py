"""Комбобокс приложения: стрелка рисуется сама.

Штатная стрелка Qt при стилизованном QComboBox стоит в отдельной рамке (::drop-down) — справа получалась двойная
граница. В таблице стилей у ::drop-down рамки нет, ::down-arrow скрыт, а стрелку (маленький треугольник, как у
меню кнопок выбора карты) рисует paintEvent — так же, как три точки DotsButton."""
from __future__ import annotations

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPolygonF
from PySide6.QtWidgets import QComboBox

from .theme import TOKENS

ARROW_W, ARROW_H = 8.0, 4.5  # треугольник стрелки, px
ARROW_RIGHT = 12.0           # центр стрелки — на столько от правого края


class ComboBox(QComboBox):
    def showPopup(self) -> None:
        # контейнер списка — отдельное окно: стиль главного окна до его полей не доходит (белые полосы сверху и
        # снизу) — цвета ему задаются явно
        container = self.view().window()
        if container is not self.window() and not container.styleSheet():
            container.setStyleSheet(f"QFrame {{ background: {TOKENS['surface']}; border: 1px solid {TOKENS['border']}; }}"
                                    " QAbstractItemView { border: none; }")
        super().showPopup()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        token = "text_faint" if not self.isEnabled() else "text" if self.underMouse() else "text_muted"
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(TOKENS[token]))
        cx, cy = self.width() - ARROW_RIGHT, self.height() / 2
        p.drawPolygon(QPolygonF([QPointF(cx - ARROW_W / 2, cy - ARROW_H / 2), QPointF(cx + ARROW_W / 2, cy - ARROW_H / 2),
                                 QPointF(cx, cy + ARROW_H / 2)]))
