"""Пробное окно PySide6: проверка сборки .exe, тёмной темы и drag-in .mid.

Запуск из исходников: python -m remap.ui.smoke
"""

import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLabel, QMainWindow, QVBoxLayout, QWidget

from remap.ui.theme import TOKENS


class DropZone(QLabel):
    """Зона, принимающая перетаскивание одного .mid-файла и показывающая его путь."""

    HINT = "Перетащите сюда .mid файл"

    def __init__(self) -> None:
        super().__init__(self.HINT)
        self.setAcceptDrops(True)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setWordWrap(True)
        self.setMinimumHeight(160)
        self._set_style(active=False)

    def _set_style(self, active: bool) -> None:
        border = TOKENS["accent"] if active else TOKENS["border"]
        self.setStyleSheet(
            f"background: {TOKENS['surface']}; color: {TOKENS['text_muted']};"
            f"border: 2px dashed {border}; border-radius: 8px; padding: 16px;"
        )

    @staticmethod
    def _mid_path(event) -> Path | None:
        urls = event.mimeData().urls()
        if len(urls) != 1 or not urls[0].isLocalFile():
            return None
        path = Path(urls[0].toLocalFile())
        return path if path.suffix.lower() in (".mid", ".midi") else None

    def dragEnterEvent(self, event) -> None:
        if self._mid_path(event):
            event.acceptProposedAction()
            self._set_style(active=True)

    def dragLeaveEvent(self, event) -> None:
        self._set_style(active=False)

    def dropEvent(self, event) -> None:
        self._set_style(active=False)
        path = self._mid_path(event)
        if path:
            self.setText(str(path))
            event.acceptProposedAction()


class SmokeWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("REMAP — PySide6 smoke test")
        self.resize(560, 320)

        title = QLabel("REMAP")
        title.setStyleSheet(f"color: {TOKENS['accent']}; font-size: 22px; font-weight: 600;")

        central = QWidget()
        central.setStyleSheet(f"background: {TOKENS['bg']}; color: {TOKENS['text']};")
        layout = QVBoxLayout(central)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.addWidget(title)
        layout.addWidget(DropZone(), stretch=1)
        self.setCentralWidget(central)


def main() -> int:
    app = QApplication(sys.argv)
    window = SmokeWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
