"""Вид профиля «кабелями» (этап 8b2a: только показ — без перетаскивания, правого клика и пунктирных подсказок).

Одна QGraphicsView: обе колонки и кабели в одной сцене, поэтому вертикальная прокрутка одна на обе колонки.
Порядок, группы, высоты строк и кабели считает cable_layout (без Qt); здесь — рисование, подсказки и
сворачивание по клику на заголовок. Профиль — рабочая копия страницы Profiles; виджет его не меняет.

Пересортировка (порядок строк заново): set_profile(), resort() (кнопка), сворачивание/разворачивание,
включение вида (set_active). После правок — refresh(): порядок заморожен (см. cable_layout).
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QGraphicsItem, QGraphicsPathItem, QGraphicsScene, QGraphicsView

from ..core.notemap import primary_note
from ..core.pitch import pitch_name
from ..core.profile import NO_RULE, ProfileIssue, RemapProfile, validate_profile
from .cable_layout import (
    DEFAULT_COLLAPSED, DELETE, KEEP, UNASSIGNED, CableLayout, Header, OrderSnapshot, SourceRow, TargetRow,
    build_layout,
)
from .theme import TOKENS

ROW = 26          # высота строки, px
PAD = 8           # поля сцены
MIN_WIDTH = 560   # уже — горизонтальной прокрутки нет, сцена просто обрезается
NUM_W, PITCH_W, MARK_W = 30, 40, 22
PORT = 3.5        # радиус точки подключения кабеля

STATE_TIPS = {
    UNASSIGNED: "No rule yet: stays on its number unless you choose otherwise when saving",
    KEEP: "Stays on its number",
    DELETE: "Deleted from converted files",
}
STALE_TIP = "Its cable was removed. Re-sort to move the row to its block"


def _font(base: QFont, *, bold=False, size_delta=0.0, strike=False, italic=False) -> QFont:
    f = QFont(base)
    if size_delta:
        f.setPointSizeF(max(6.0, f.pointSizeF() + size_delta))
    f.setBold(bold)
    f.setStrikeOut(strike)
    f.setItalic(italic)
    return f


class _Row(QGraphicsItem):
    """Строка колонки: фон, номер, высота ноты, имя, маркер справа; точка кабеля слева или справа."""

    def __init__(self, rect: QRectF, number: str, pitch: str, name: str, *, name_color="text", strike=False,
                 italic=False, marker="", port: str | None = None, bg="surface", tooltip="") -> None:
        super().__init__()
        self.rect = rect
        self.number, self.pitch, self.name = number, pitch, name
        self.name_color, self.strike, self.italic, self.marker = name_color, strike, italic, marker
        self.port, self.bg = port, bg
        self.setZValue(1)
        if tooltip:
            self.setToolTip(tooltip)

    def boundingRect(self) -> QRectF:
        return self.rect.adjusted(-PORT - 1, 0, PORT + 1, 0)

    def paint(self, p: QPainter, option, widget=None) -> None:
        base = widget.font() if widget is not None else p.font()
        r = self.rect.adjusted(0, 1, 0, -1)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(TOKENS[self.bg]))
        p.drawRoundedRect(r, 4, 4)
        x, h = r.left() + 4, r.height()
        p.setFont(base)
        p.setPen(QColor(TOKENS["text"]))
        p.drawText(QRectF(x, r.top(), NUM_W, h), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                   self.number)
        x += NUM_W + 8
        p.setFont(_font(base, size_delta=-1))
        p.setPen(QColor(TOKENS["text_muted"]))
        p.drawText(QRectF(x, r.top(), PITCH_W, h), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   self.pitch)
        x += PITCH_W
        name_w = r.right() - x - (MARK_W if self.marker else 6)
        font = _font(base, strike=self.strike, italic=self.italic)
        p.setFont(font)
        p.setPen(QColor(TOKENS[self.name_color]))
        text = QFontMetrics(font).elidedText(self.name, Qt.TextElideMode.ElideRight, max(0, int(name_w)))
        p.drawText(QRectF(x, r.top(), name_w, h), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, text)
        if self.marker:
            p.setFont(_font(base, size_delta=-1, bold=True))
            p.setPen(QColor(TOKENS["text_muted"]))
            p.drawText(QRectF(r.right() - MARK_W, r.top(), MARK_W - 4, h), Qt.AlignmentFlag.AlignCenter,
                       self.marker)
        if self.port:
            _draw_port(p, QPointF(r.right() if self.port == "right" else r.left(), r.center().y()))


class _HeaderItem(QGraphicsItem):
    """Заголовок блока или группы: стрелка, имя, число; клик — свернуть или развернуть."""

    def __init__(self, rect: QRectF, header: Header, view: CableView, *, port: str | None = None) -> None:
        super().__init__()
        self.rect, self.header, self.view, self.port = rect, header, view, port
        self._hover = False
        self.setZValue(1)
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Click to expand" if header.collapsed else "Click to collapse")

    def boundingRect(self) -> QRectF:
        return self.rect.adjusted(-PORT - 1, 0, PORT + 1, 0)

    def hoverEnterEvent(self, event) -> None:
        self._hover = True
        self.update()

    def hoverLeaveEvent(self, event) -> None:
        self._hover = False
        self.update()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            event.accept()
            # перестройка сцены удаляет этот элемент — не внутри его же обработчика
            QTimer.singleShot(0, lambda key=self.header.key: self.view.toggle(key))
        else:
            event.ignore()

    def paint(self, p: QPainter, option, widget=None) -> None:
        base = widget.font() if widget is not None else p.font()
        h = self.header
        r = self.rect.adjusted(0, 1, 0, -1)
        tall = h.height > 1
        if self._hover or tall:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(TOKENS["surface_hover" if self._hover else "surface"]))
            p.drawRoundedRect(r, 4, 4)
        indent = (10 if self.port == "left" else 4) + 14 * h.level  # не наезжать на точку кабеля
        arrow = "▸" if h.collapsed else "▾"
        label = h.label.upper() if h.level == 0 else h.label
        font = _font(base, bold=True, size_delta=-1.5 if h.level == 0 else -0.5)
        p.setFont(font)
        p.setPen(QColor(TOKENS["text_muted"]))
        fm = QFontMetrics(font)
        avail = r.width() - indent - 40
        text = fm.elidedText(f"{arrow}  {label}", Qt.TextElideMode.ElideRight, max(0, int(avail)))
        box = QRectF(r.left() + indent, r.top(), avail, r.height())
        p.drawText(box, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, text)
        p.setPen(QColor(TOKENS["text_faint"]))
        p.drawText(QRectF(r.left() + indent + fm.horizontalAdvance(text) + 8, r.top(), 40, r.height()),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, str(h.count))
        if self.port:
            _draw_port(p, QPointF(r.left() if self.port == "left" else r.right(), r.center().y()))


def _draw_port(p: QPainter, c: QPointF) -> None:
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(TOKENS["accent"]))
    p.drawEllipse(c, PORT, PORT)


class CableView(QGraphicsView):
    """Обе колонки профиля и кабели между ними в одной прокручиваемой сцене."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("cables")
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        self.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.BoundingRectViewportUpdate)
        self.profile: RemapProfile | None = None
        self.collapsed: set[str] = set(DEFAULT_COLLAPSED)
        self.order: OrderSnapshot | None = None
        self.current: CableLayout | None = None  # последняя построенная раскладка
        self.active = False                      # вид показан (скрытый не перестраивается)
        self.cable_items: list[QGraphicsPathItem] = []
        self._issues: dict[int, list[ProfileIssue]] = {}
        self._width = 0

    # --- управление ---

    def set_profile(self, p: RemapProfile | None, reset_collapsed: bool = True) -> None:
        """Другой профиль (или тот же после сохранения/отката, смены карты) — пересортировать."""
        self.profile = p
        if reset_collapsed:
            self.collapsed = set(DEFAULT_COLLAPSED)
        self.resort()

    def set_active(self, active: bool) -> None:
        """Вид показан или скрыт. Показ — пересортировка (правки, сделанные в таблице, раскладываются заново)."""
        self.active = active
        if active:
            self.resort()

    def refresh(self) -> None:
        """Правила изменились: порядок заморожен — строки без кабеля остаются на местах до пересортировки."""
        if self.active:
            self._build(self.order)

    def resort(self) -> None:
        self.order = None
        if self.active:
            self._build(None)

    def toggle(self, key: str) -> None:
        """Свернуть/развернуть блок или группу (и пересортировать)."""
        self.collapsed ^= {key}
        self.resort()

    # --- построение сцены ---

    def _build(self, snapshot: OrderSnapshot | None) -> None:
        self.current = build_layout(self.profile, self.collapsed, snapshot)
        self.order = self.current.order
        self._issues = {}
        if self.profile is not None:
            for i in validate_profile(self.profile):
                if i.code != NO_RULE:
                    self._issues.setdefault(i.note, []).append(i)
        self._draw()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self.current is not None and self.viewport().width() != self._width:
            self._draw()

    def _columns(self) -> tuple[float, float, float]:
        """x левой колонки, x правой колонки, ширина колонки."""
        width = max(self.viewport().width(), MIN_WIDTH)
        gap = max(110, int(width * 0.18))
        col = (width - 2 * PAD - gap) / 2
        return PAD, PAD + col + gap, col

    def _draw(self) -> None:
        bar = self.verticalScrollBar()
        pos = bar.value()
        self._scene.clear()
        self.cable_items = []
        self._width = self.viewport().width()
        lay = self.current
        lx, rx, col = self._columns()
        total = (lay.height if lay is not None else 0) * ROW + 2 * PAD
        self._scene.setSceneRect(0, 0, 2 * PAD + 2 * col + (rx - lx - col), total)
        if lay is None or self.profile is None:
            return

        def rect(x: float, y: int, h: int = 1) -> QRectF:
            return QRectF(x, PAD + y * ROW, col, h * ROW)

        to_headers = {c.target.key for c in lay.cables if isinstance(c.target, Header)}
        for h in lay.source_headers:
            self._scene.addItem(_HeaderItem(rect(lx, h.y), h, self))
        for h in lay.target_headers:
            self._scene.addItem(_HeaderItem(rect(rx, h.y, h.height), h, self,
                                            port="left" if h.key in to_headers else None))
        for r in lay.source_rows:
            self._scene.addItem(self._source_item(rect(lx, r.y), r))
        targets_with_cables = {c.target.slot for c in lay.cables if isinstance(c.target, TargetRow)}
        for t in lay.target_rows:
            self._scene.addItem(self._target_item(rect(rx, t.y, t.height), t, t.slot in targets_with_cables))
        x1, x2 = lx + col, rx
        for c in lay.cables:
            y1 = PAD + c.src_y * ROW + ROW / 2
            y2 = PAD + (c.target.y + c.target.height / 2) * ROW
            path = QPainterPath(QPointF(x1, y1))
            dx = (x2 - x1) / 2
            path.cubicTo(QPointF(x1 + dx, y1), QPointF(x2 - dx, y2), QPointF(x2, y2))
            item = QGraphicsPathItem(path)
            pen = QPen(QColor(TOKENS["accent"]), 1.6)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            item.setPen(pen)
            item.setToolTip(self._cable_tip(c.src, c.dst))
            self._scene.addItem(item)
            self.cable_items.append(item)
        bar.setValue(pos)

    def _source_item(self, r: QRectF, row: SourceRow) -> _Row:
        p = self.profile
        tgt = p.target_map
        if row.connected:
            tip = self._cable_tip(row.note, p.rules[row.note].dst)
        else:
            tip = STATE_TIPS.get(row.state, "")
            if row.state == KEEP and tgt is not None:
                tip += f": {tgt.names[row.note]}" if row.note in tgt.names else " (no such note in the target map)"
            if row.block is None:
                tip = f"{tip}\n{STALE_TIP}"
        issues = self._issues.get(row.note, [])
        if issues:
            tip = "\n".join([i.message for i in issues] + [tip])
        missing_name = row.name is None
        return _Row(r, str(row.note), pitch_name(row.note), row.name or "—",
                    name_color="text_faint" if row.state == DELETE or missing_name else "text",
                    strike=row.state == DELETE, marker="=" if row.state == KEEP else "",
                    port="right" if row.connected else None, bg="warning_bg" if issues else "surface", tooltip=tip)

    def _target_item(self, r: QRectF, t: TargetRow, connected: bool) -> _Row:
        tgt = self.profile.target_map
        if not t.in_map:
            tip = f"Note {t.notes[0]} is not in the target map" if tgt is not None else "No target map"
            return _Row(r, str(t.notes[0]), pitch_name(t.notes[0]), "—", name_color="text_faint", italic=True,
                        port="left" if connected else None, tooltip=tip)
        note = t.write_to if t.write_to is not None else t.notes[0]
        marker = f"+{len(t.notes) - 1}" if len(t.notes) > 1 else ""
        if len(t.notes) > 1:
            wt = f"Write to: {t.write_to}" if t.write_to is not None else "Write to: not chosen"
            tip = f"On notes {', '.join(map(str, t.notes))} · {wt}"
        else:
            tip = ""
        return _Row(r, str(note), pitch_name(note), t.label, marker=marker,
                    port="left" if connected else None, tooltip=tip)

    def _cable_tip(self, src: int, dst: int) -> str:
        p = self.profile
        src_name = p.source_map.names.get(src, "") if p.source_map is not None else ""
        tgt = p.target_map
        dst_name = tgt.names.get(dst, "") if tgt is not None else ""
        text = f"{src} {src_name}".strip() + "  →  " + f"{dst} {dst_name}".strip()
        if tgt is not None and dst in tgt.names:
            wt = primary_note(tgt, dst_name)
            if wt is not None and wt != dst:
                text += f"\nNot the Write to note ({wt})"
        return text
