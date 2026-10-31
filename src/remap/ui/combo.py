"""Комбобокс приложения: поле-«рамка» (`field.paint_bezel`), одна или две строки, стеклянный список.

Лицо, текст и стрелка рисуются сами (`paintEvent`), без QSS: штатная отрисовка Qt для такого вида не годится. Одна строка —
значение (профиль); две — подпись (`caption`: SOURCE, TARGET, OUTPUT) над значением. Это `<button>` макета, поэтому текст —
`WDTH_BUTTON`. Список — окно-контейнер Qt, которому мы убираем рамку и фон и под которым рисуем стекло (`paint_glass`):
строки 28 px, при наведении плашка, текущая строка — акцентом, больше `POPUP_MAX_ROWS` строк — узкая полоса прокрутки.
Положение и размер списка ставятся по лицу поля (не по виджету с полями под обод).
"""

from shiboken6 import isValid
from PySide6.QtCore import QEvent, QModelIndex, QObject, QPoint, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QFont, QPainter, QPalette, QPen
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QListView, QSizePolicy, QStyle, QStyledItemDelegate, QStyleOptionViewItem, QWidget,
)

from . import text, theme
from .field import field_height, field_margins, field_specs, paint_bezel, paint_field_text
from .glass import ScreenScrollBar, paint_glass
from .icons import ICONS, draw_icon
from .metal import _Backdrop
from .theme import qcolor

POPUP_GAP = 5  # px от низа лица до списка: обод 3 + светлая линия 1 + 1 px воздуха


class _RowDelegate(QStyledItemDelegate):
    """Строка списка: плашка при наведении/выборе клавиатурой, текст `POPUP_TEXT`; текущее значение — акцентом,
    недоступная строка — приглушена."""

    def __init__(self, combo: "ComboBox") -> None:
        super().__init__(combo)
        self._combo = combo

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        return QSize(option.rect.width(), theme.POPUP_ROW)

    def paint(self, p: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        rect = QRectF(option.rect)
        enabled = bool(option.state & QStyle.StateFlag.State_Enabled)
        if enabled and option.state & (QStyle.StateFlag.State_MouseOver | QStyle.StateFlag.State_Selected):
            p.save()
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            r = theme.CHIP_RADIUS
            p.setPen(QPen(qcolor(theme.POPUP_HOVER_BORDER), 1))
            p.setBrush(qcolor(theme.POPUP_HOVER_BG))
            p.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), r - 0.5, r - 0.5)
            p.restore()
        color = (theme.SILK_FAINT if not enabled else theme.ACCENT if index.row() == self._combo.currentIndex()
                 else theme.POPUP_TEXT)
        pad = theme.POPUP_PAD_X
        text.draw_text(p, rect.adjusted(pad, 0, -pad, 0), str(index.data(Qt.ItemDataRole.DisplayRole) or ""),
                       self._combo.specs.value, color, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       Qt.TextElideMode.ElideRight)


class _PopupList(QListView):
    """Список комбо: прозрачный (стекло рисует контейнер), без рамки, строки по `POPUP_ROW`, полоса прокрутки экрана."""

    def __init__(self, combo: "ComboBox") -> None:
        super().__init__(combo)
        self.setFrameShape(QListView.Shape.NoFrame)
        self.setMouseTracking(True)
        self.setUniformItemSizes(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerItem)
        self.viewport().setAutoFillBackground(False)
        self.viewport().setAttribute(Qt.WidgetAttribute.WA_Hover)
        self.setItemDelegate(_RowDelegate(combo))
        self.bar = ScreenScrollBar(self, self)
        self.verticalScrollBar().rangeChanged.connect(self._fit)
        self._fit()

    def _fit(self, *_args) -> None:
        """Поля вокруг строк (рамка стекла + `POPUP_PAD`); справа при прокрутке — место под полосу."""
        pad = 1 + theme.POPUP_PAD
        gutter = theme.SCROLL_RIGHT + theme.SCROLL_WIDTH + 1 if self.verticalScrollBar().maximum() > 0 else 0
        self.setViewportMargins(pad, pad, pad + gutter, pad)
        track = self.width() - 1 - theme.SCROLL_RIGHT - theme.SCROLL_WIDTH
        self.bar.place(track, pad, self.height() - 2 * pad)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._fit()


class _PopupFilter(QObject):
    """Фильтр контейнера списка: рисует под содержимым стекло и сообщает комбо о закрытии."""

    def __init__(self, combo: "ComboBox") -> None:
        super().__init__(combo)
        self._combo = combo
        self._glass = _Backdrop(textured=False)

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.Paint and isinstance(obj, QWidget):
            def compose(p: QPainter, rect: QRect, _origin: QPoint) -> None:
                paint_glass(p, QRectF(rect), p.device().devicePixelRatioF(),
                            radius=theme.SCREEN_RADIUS if theme.POPUP_ROUNDED else 0)

            QPainter(obj).drawPixmap(0, 0, self._glass.get(obj, compose))
        elif event.type() == QEvent.Type.Hide and isValid(self._combo):  # при выходе комбо может быть уже удалён
            self._combo._popup_closed()
        return False


class ComboBox(QComboBox):
    """Комбобокс-«рамка». `caption` — подпись над значением (двухстрочный вид); `value_px` / `value_weight` — шрифт значения
    (по умолчанию 12/400 у однострочного, 12.5/500 у двухстрочного). Остальное — штатный QComboBox: элементы, данные,
    сигналы, `setPlaceholderText`, `setMinimumContentsLength`."""

    def __init__(self, parent: QWidget | None = None, *, caption: str | None = None, value_px: float | None = None,
                 value_weight: QFont.Weight | None = None, wdth: float = theme.WDTH_BUTTON) -> None:
        super().__init__(parent)
        self._caption = caption
        self.specs = field_specs(caption is not None, wdth, value_px, value_weight)
        self._open = False
        self._focus_visible = False  # кольцо фокуса — только с клавиатуры (как outline: focus-visible) и при открытом списке
        self._faces: dict[str, _Backdrop] = {}
        self._filter = _PopupFilter(self)
        self._container_ready = False
        self.setView(_PopupList(self))
        self.setMaxVisibleItems(theme.POPUP_MAX_ROWS)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(field_height())
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    # --- размеры ---
    @property
    def caption(self) -> str | None:
        return self._caption

    def set_caption(self, caption: str | None) -> None:
        self._caption = caption
        self.update()

    def margins(self):
        return field_margins()

    def face_rect(self) -> QRectF:
        m = field_margins()
        return QRectF(m.left(), m.top(), self.width() - m.left() - m.right(), self.height() - m.top() - m.bottom())

    def content_rect(self) -> QRectF:
        pad = theme.FIELD_PAD_X + 1
        return self.face_rect().adjusted(pad, 0, -pad, 0)

    def text_room(self) -> float:
        """Ширина под текст: между полями лица, без стрелки и зазора до неё."""
        return self.content_rect().width() - ICONS["chevron-down"].w - theme.FIELD_GAP

    def sizeHint(self) -> QSize:
        policy = self.sizeAdjustPolicy()
        if policy == QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon:
            room = self.minimumContentsLength() * text.text_width("0", self.specs.value)
        else:
            room = max((text.text_width(self.itemText(i), self.specs.value) for i in range(min(self.count(), 200))),
                       default=0.0)
        if self._caption and self.specs.caption:
            room = max(room, text.text_width(self._caption, self.specs.caption))
        m = field_margins()
        width = (m.left() + m.right() + 2 * (theme.FIELD_PAD_X + 1) + room + theme.FIELD_GAP + ICONS["chevron-down"].w)
        return QSize(int(width + 0.999), field_height())

    def minimumSizeHint(self) -> QSize:
        return QSize(60, field_height())

    # --- вид ---
    def _state(self) -> str:
        if self._open or (self._focus_visible and self.hasFocus()):
            return "focus"
        return "hover" if self.isEnabled() and self.underMouse() else "normal"

    def _shown_text(self) -> tuple[str, bool]:
        """Что показать и приглушённое ли это (нет выбранного значения: подсказка поля или «—» у пустого списка)."""
        if self.currentIndex() >= 0:
            return self.currentText(), False
        return self.placeholderText() or ("—" if self.count() == 0 else ""), True

    def paintEvent(self, _event) -> None:
        state, face = self._state(), self.face_rect()

        def compose(p: QPainter, _rect: QRect, _origin: QPoint) -> None:
            paint_bezel(p, face, p.device().devicePixelRatioF(), "bezel", state)

        p = QPainter(self)
        p.drawPixmap(0, 0, self._faces.setdefault(state, _Backdrop(textured=False)).get(self, compose))
        if not self.isEnabled():
            p.setOpacity(theme.FIELD_DISABLED_OPACITY)
        content = self.content_rect()
        chevron = ICONS["chevron-down"]
        dpr = self.devicePixelRatioF()
        cx = round((content.right() - chevron.w) * dpr) / dpr  # значок — по сетке устройства, как у клавиш
        cy = round((face.center().y() - chevron.h / 2) * dpr) / dpr
        draw_icon(p, "chevron-down", QRectF(cx, cy, chevron.w, chevron.h))
        value, dim = self._shown_text()
        if value:
            room = QRectF(content.left(), content.top(), self.text_room(), content.height())
            paint_field_text(p, room, self.specs, value, self._caption, placeholder=dim)

    def focusInEvent(self, event) -> None:
        self._focus_visible = event.reason() in (Qt.FocusReason.TabFocusReason, Qt.FocusReason.BacktabFocusReason,
                                                 Qt.FocusReason.ShortcutFocusReason)
        super().focusInEvent(event)
        self.update()

    def focusOutEvent(self, event) -> None:
        self._focus_visible = False
        super().focusOutEvent(event)
        self.update()

    def event(self, e) -> bool:
        if e.type() in (QEvent.Type.HoverEnter, QEvent.Type.HoverLeave, QEvent.Type.EnabledChange):
            self.update()
        return super().event(e)

    @property
    def rebuilds(self) -> int:
        return sum(b.rebuilds for b in self._faces.values())

    # --- список ---
    def popup_height(self) -> int:
        rows = min(self.count(), self.maxVisibleItems())
        return rows * theme.POPUP_ROW + 2 * (1 + theme.POPUP_PAD)

    def showPopup(self) -> None:
        container = self.view().window()
        if container is not self.window() and not self._container_ready:
            # контейнер — отдельное окно Qt: убираем рамку и фон (стиль приложения до него не доходит, остались бы белые
            # поля), стекло рисует фильтр; прозрачность нужна для скруглённых углов
            container.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
            container.setWindowFlag(Qt.WindowType.NoDropShadowWindowHint, True)
            container.setStyleSheet("QFrame { background: transparent; border: none; }"
                                    " QAbstractItemView { background: transparent; border: none; }")
            if theme.POPUP_ROUNDED:
                container.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
            else:  # запасной вариант: квадратный список на сплошном фоне (стекло ляжет сверху фильтром)
                container.setAutoFillBackground(True)
                pal = container.palette()
                pal.setColor(QPalette.ColorRole.Window, qcolor(theme.SCREEN_GLASS_OUTER))
                container.setPalette(pal)
            for child in container.findChildren(QWidget):  # стрелки-«скроллеры» Qt (5 px) съели бы место у списка
                if child.metaObject().className() == "QComboBoxPrivateScroller":
                    child.setFixedHeight(0)
            container.installEventFilter(self._filter)
            self._container_ready = True
        self._open = True
        self.update()
        super().showPopup()
        if container.isVisible():
            layout = container.layout()
            if layout is not None:  # в стиле с «всплывающими» комбо (Fusion) Qt оставляет по 5 px распорками сверху и снизу
                layout.setContentsMargins(0, 0, 0, 0)
                layout.setSpacing(0)
                for index in (0, layout.count() - 1):
                    spacer = layout.itemAt(index).spacerItem()
                    if spacer is not None:
                        spacer.changeSize(0, 0)
            container.setGeometry(self._popup_rect(container))
            if layout is not None:
                layout.activate()

    def _popup_rect(self, container: QWidget) -> QRect:
        """Список вплотную под лицом поля (над ним, если снизу нет места), шириной с лицо."""
        face = self.face_rect()
        top_left = self.mapToGlobal(QPoint(round(face.left()), round(face.top())))
        width, height = round(face.width()), self.popup_height()
        y = top_left.y() + round(face.height()) + POPUP_GAP
        screen = self.screen()
        if screen is not None and y + height > screen.availableGeometry().bottom():
            y = top_left.y() - POPUP_GAP - height
        return QRect(top_left.x(), y, width, height)

    def _popup_closed(self) -> None:
        self._open = False
        self.update()
