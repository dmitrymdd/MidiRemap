"""Пробное окно PySide6: проверка сборки .exe, тёмной темы и drag-in .mid.

Запуск из исходников: python -m remap.ui.smoke
"""

import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLabel, QMainWindow, QVBoxLayout, QWidget

from remap.ui import theme


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
        border = theme.ACCENT if active else theme.SCREEN_BORDER
        self.setStyleSheet(
            f"background: {theme.SCREEN_GLASS_MID}; color: {theme.SCREEN_TEXT_2};"
            f"border: 2px dashed {border}; border-radius: {theme.SCREEN_RADIUS}px; padding: 16px;"
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
        title.setStyleSheet(f"color: {theme.ACCENT}; font-size: 22px; font-weight: 600;")

        central = QWidget()
        central.setStyleSheet(f"background: {theme.RECESS_BOTTOM}; color: {theme.SCREEN_TEXT};")
        layout = QVBoxLayout(central)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.addWidget(title)
        layout.addWidget(DropZone(), stretch=1)
        self.setCentralWidget(central)


def main() -> int:
    app = QApplication(sys.argv)
    theme.load_fonts()  # проверка сборки: шрифты из assets/fonts должны найтись и в .exe
    theme.install_app_font()
    window = SmokeWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
