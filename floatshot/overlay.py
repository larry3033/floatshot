"""Full-desktop selection overlay.

Shown after the screen has already been captured, so the darkened backdrop
and selection border can never appear in the resulting screenshot.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from .config import Config
from .dpi import ui_scale

_HINT_SIZE = 12


class SelectionOverlay(QWidget):
    """Drag to select a region of the desktop.

    Emits `selected` with a rect in *desktop* coordinates (which may be
    negative on multi-monitor setups), or `cancelled` on Esc / right-click.
    """

    selected = Signal(QRect)
    cancelled = Signal()

    def __init__(self, origin: QRect, config: Config,
                 scale: float | None = None) -> None:
        super().__init__(None)
        self._origin = origin
        self._config = config
        self._scale = ui_scale() if scale is None else scale

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setGeometry(origin)

        self._anchor: QPoint | None = None
        self._current: QPoint | None = None

    # -- selection maths --------------------------------------------------

    def _selection_local(self) -> QRect:
        if self._anchor is None or self._current is None:
            return QRect()
        # Both drag directions must describe the same region, and the corner
        # must sit exactly under the mouse. QRect's two-point constructor
        # followed by normalized() loses one pixel on *every* side of a
        # reversed rect (QRect(QPoint(200,150), QPoint(600,450)) is
        # 401x301, while the same two points the other way round normalise
        # to 399x299), so build the corners explicitly instead.
        a, b = self._anchor, self._current
        top_left = QPoint(min(a.x(), b.x()), min(a.y(), b.y()))
        bottom_right = QPoint(max(a.x(), b.x()), max(a.y(), b.y()))
        return QRect(top_left, bottom_right)

    def _selection_desktop(self) -> QRect:
        return self._selection_local().translated(self._origin.topLeft())

    # -- painting ---------------------------------------------------------

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        try:
            self._paint_dim(painter)
            sel = self._selection_local()
            if not sel.isEmpty():
                self._paint_border(painter, sel)
                self._paint_hint(painter, sel)
        finally:
            painter.end()

    def _paint_dim(self, painter: QPainter) -> None:
        """Darken everything except the selection."""
        cfg = self._config.get("overlay")
        alpha = max(0, min(255, int(cfg["dim_alpha"])))

        path = QPainterPath()
        path.addRect(self.rect())
        sel = self._selection_local()
        if not sel.isEmpty():
            hole = QPainterPath()
            hole.addRect(sel)
            path = path.subtracted(hole)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.fillPath(path, QColor(0, 0, 0, alpha))

    def _paint_border(self, painter: QPainter, sel: QRect) -> None:
        cfg = self._config.get("overlay")
        width = max(1, int(cfg["border_width"] * self._scale))
        pen = QPen(QColor(cfg["border_color"]))
        pen.setWidth(width)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        # QRect's edges are inclusive, so the -1 keeps the outline on the
        # selection's outermost pixel ring instead of one pixel outside it.
        painter.drawRect(sel.adjusted(0, 0, -1, -1))

    def _paint_hint(self, painter: QPainter, sel: QRect) -> None:
        if not self._config.get("overlay", "show_size_hint"):
            return

        text = f"{sel.width()} x {sel.height()}"
        font = QFont()
        font.setPointSize(int(_HINT_SIZE * self._scale))
        painter.setFont(font)

        metrics = painter.fontMetrics()
        pad = int(4 * self._scale)
        box = metrics.boundingRect(text).adjusted(-pad, -pad, pad, pad)

        # Prefer just above the selection; flip inside if it would go off-screen.
        y = sel.top() - box.height() - 2
        if y < 0:
            y = sel.top() + 2
        box.moveTo(sel.left(), y)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 170))
        painter.drawRoundedRect(box, 3, 3)

        painter.setPen(QColor(255, 255, 255))
        painter.drawText(box, Qt.AlignmentFlag.AlignCenter, text)

    # -- input -------------------------------------------------------------

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.RightButton:
            self.cancelled.emit()
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self._anchor = event.position().toPoint()
        self._current = self._anchor
        self.update()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._anchor is None:
            return
        self._current = event.position().toPoint()
        self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton or self._anchor is None:
            return
        sel = self._selection_desktop()
        self._anchor = None
        self._current = None
        if sel.width() < 2 or sel.height() < 2:
            self.cancelled.emit()
        else:
            self.selected.emit(sel)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            self.cancelled.emit()
            return
        super().keyPressEvent(event)
