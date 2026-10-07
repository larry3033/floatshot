"""The annotation toolbar that pops up under a floating window.

Every size and colour comes from the `toolbar` section of the config; the
icons are drawn with QPainter so the app still needs no image assets, the
same choice the tray icon makes.

The toolbar is its own top-level tool window rather than a child of the
floating window: a child would be clipped to the window's rect, and the
whole point is that the bar hangs *below* the picture.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractButton,
    QColorDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .annotations import Tool
from .config import Config

# (button key, tool, tooltip). The key doubles as the icon name.
_TOOL_BUTTONS: tuple[tuple[str, Tool, str], ...] = (
    ("rect", Tool.RECT, "矩形"),
    ("ellipse", Tool.ELLIPSE, "椭圆"),
    ("arrow", Tool.ARROW, "箭头"),
    ("pen", Tool.PEN, "画笔"),
    ("text", Tool.TEXT, "文字"),
    ("mosaic", Tool.MOSAIC, "马赛克"),
    ("number", Tool.NUMBER, "序号"),
    ("highlight", Tool.HIGHLIGHT, "高亮"),
)


class _IconButton(QAbstractButton):
    """A fixed-size button that paints one vector icon by name."""

    def __init__(self, kind: str, config: dict, *, checkable: bool = False,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._kind = kind
        self._cfg = config
        self.setCheckable(checkable)
        size = max(1, int(config["button_size"]))
        self.setFixedSize(size, size)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        if checkable:
            self.toggled.connect(lambda _: self.update())

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            cfg = self._cfg
            if self.isChecked():
                background, color = cfg["active_bg"], cfg["active_color"]
            elif self.underMouse() and self.isEnabled():
                background, color = cfg["hover_bg"], cfg["icon_color"]
            else:
                background, color = None, cfg["icon_color"]
            if not self.isEnabled():
                color = cfg["disabled_color"]

            if background is not None:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(background))
                radius = float(cfg["radius"]) * 0.5
                painter.drawRoundedRect(
                    QRectF(self.rect()).adjusted(2, 2, -2, -2), radius, radius
                )

            icon = max(1, int(cfg["icon_size"]))
            painter.translate(
                (self.width() - icon) / 2.0, (self.height() - icon) / 2.0
            )
            _draw_icon(painter, self._kind, float(icon), QColor(color))
        finally:
            painter.end()

    def enterEvent(self, event) -> None:  # noqa: N802
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self.update()
        super().leaveEvent(event)


class _ColorButton(QAbstractButton):
    """Shows the current drawing colour as a filled dot; opens the palette."""

    def __init__(self, config: dict, colour: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._cfg = config
        self._colour = colour
        size = max(1, int(config["button_size"]))
        self.setFixedSize(size, size)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("颜色")

    def colour(self) -> str:
        return self._colour

    def set_colour(self, colour: str) -> None:
        self._colour = colour
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            if self.underMouse():
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(self._cfg["hover_bg"]))
                radius = float(self._cfg["radius"]) * 0.5
                painter.drawRoundedRect(
                    QRectF(self.rect()).adjusted(2, 2, -2, -2), radius, radius
                )
            diameter = max(8.0, int(self._cfg["icon_size"]) * 1.05)
            painter.setBrush(QColor(self._colour))
            painter.setPen(QPen(QColor(self._cfg["border_color"]), 1.4))
            painter.drawEllipse(QRectF(
                (self.width() - diameter) / 2.0,
                (self.height() - diameter) / 2.0,
                diameter, diameter,
            ))
        finally:
            painter.end()

    def enterEvent(self, event) -> None:  # noqa: N802
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self.update()
        super().leaveEvent(event)


class _Swatch(QAbstractButton):
    """One colour square in the palette."""

    def __init__(self, colour: str, size: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._colour = colour
        self.setFixedSize(size, size)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(colour)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.setPen(QPen(QColor("#B0B0B0"), 1))
            painter.setBrush(QColor(self._colour))
            painter.drawRoundedRect(
                QRectF(self.rect()).adjusted(1, 1, -1, -1), 3, 3
            )
        finally:
            painter.end()


class _ColorPalette(QWidget):
    """Popup grid of preset colours, plus an arbitrary-colour escape hatch."""

    picked = Signal(str)

    def __init__(self, config: Config, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        cfg = config.get("palette")
        self._cfg = cfg
        self._current = str(config.get("annotation", "stroke_color"))

        self.setWindowFlags(
            Qt.WindowType.Popup
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        grid = QGridLayout(self)
        pad = int(cfg["padding"])
        grid.setContentsMargins(pad, pad, pad, pad)
        grid.setSpacing(int(cfg["spacing"]))
        columns = max(1, int(cfg["columns"]))
        size = int(cfg["swatch_size"])

        for index, colour in enumerate(cfg["colors"]):
            swatch = _Swatch(str(colour), size, self)
            swatch.clicked.connect(lambda _=False, c=str(colour): self._choose(c))
            grid.addWidget(swatch, index // columns, index % columns)

        more = QPushButton("更多颜色…", self)
        more.setCursor(Qt.CursorShape.PointingHandCursor)
        more.clicked.connect(self._choose_custom)
        grid.addWidget(more, (len(cfg["colors"]) + columns - 1) // columns, 0,
                       1, columns)
        self.adjustSize()

    def _choose(self, colour: str) -> None:
        self.picked.emit(colour)
        self.close()

    def _choose_custom(self) -> None:
        colour = QColorDialog.getColor(QColor(self._current), self, "选择颜色")
        if colour.isValid():
            self._choose(colour.name())

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            radius = float(self._cfg["radius"])
            painter.setBrush(QColor(self._cfg["background"]))
            painter.setPen(QPen(QColor(self._cfg["border_color"]), 1))
            painter.drawRoundedRect(
                QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), radius, radius
            )
        finally:
            painter.end()


class _WidthButton(QAbstractButton):
    """Shows the current stroke thickness as a line; opens the width list."""

    def __init__(self, config: dict, width: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._cfg = config
        self._width = int(width)
        size = max(1, int(config["button_size"]))
        self.setFixedSize(size, size)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("粗细")

    def width_value(self) -> int:
        return self._width

    def set_width(self, width: int) -> None:
        self._width = int(width)
        self.setToolTip(f"粗细：{self._width}")
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            if self.underMouse():
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(self._cfg["hover_bg"]))
                radius = float(self._cfg["radius"]) * 0.5
                painter.drawRoundedRect(
                    QRectF(self.rect()).adjusted(2, 2, -2, -2), radius, radius
                )
            icon = float(self._cfg["icon_size"])
            thickness = max(1.0, min(float(self._width), icon * 0.8))
            painter.setPen(QPen(QColor(self._cfg["icon_color"]), thickness,
                                Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            middle = self.height() / 2.0
            painter.drawLine(QPointF((self.width() - icon) / 2.0, middle),
                             QPointF((self.width() + icon) / 2.0, middle))
        finally:
            painter.end()

    def enterEvent(self, event) -> None:  # noqa: N802
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self.update()
        super().leaveEvent(event)


class _WidthOption(QAbstractButton):
    """One thickness entry in the width list."""

    def __init__(self, value: int, config: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._value = int(value)
        self._cfg = config
        self.setCheckable(True)
        self.setFixedSize(int(config["preview_width"]), int(config["row_height"]))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(str(self._value))

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            if self.isChecked() or self.underMouse():
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(self._cfg["hover_bg"]))
                radius = float(self._cfg["radius"]) * 0.5
                painter.drawRoundedRect(
                    QRectF(self.rect()).adjusted(1, 1, -1, -1), radius, radius
                )
            thickness = max(1.0, min(float(self._value), self.height() - 6.0))
            painter.setPen(QPen(QColor(self._cfg["color"]), thickness,
                                Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            middle = self.height() / 2.0
            painter.drawLine(QPointF(6.0, middle),
                             QPointF(self.width() - 6.0, middle))
        finally:
            painter.end()

    def enterEvent(self, event) -> None:  # noqa: N802
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self.update()
        super().leaveEvent(event)


class _WidthPalette(QWidget):
    """Popup list of stroke thicknesses."""

    picked = Signal(int)

    def __init__(self, config: Config, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        cfg = config.get("brush")
        self._cfg = cfg
        self.setWindowFlags(
            Qt.WindowType.Popup
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        column = QVBoxLayout(self)
        pad = int(cfg["padding"])
        column.setContentsMargins(pad, pad, pad, pad)
        column.setSpacing(int(cfg["spacing"]))
        self._options: dict[int, _WidthOption] = {}
        for value in cfg["widths"]:
            option = _WidthOption(int(value), cfg, self)
            option.clicked.connect(
                lambda _=False, v=int(value): self._choose(v)
            )
            column.addWidget(option)
            self._options[int(value)] = option
        self.adjustSize()

    def set_current(self, value: int) -> None:
        for candidate, option in self._options.items():
            option.setChecked(candidate == int(value))

    def _choose(self, value: int) -> None:
        self.picked.emit(value)
        self.close()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            radius = float(self._cfg["radius"])
            painter.setBrush(QColor(self._cfg["background"]))
            painter.setPen(QPen(QColor(self._cfg["border_color"]), 1))
            painter.drawRoundedRect(
                QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), radius, radius
            )
        finally:
            painter.end()


class EditorToolbar(QWidget):
    """Bottom toolbar with the drawing tools, undo/redo, save and close."""

    tool_changed = Signal(object)   # Tool or None
    color_changed = Signal(str)
    width_changed = Signal(int)
    ai_requested = Signal()
    undo_requested = Signal()
    redo_requested = Signal()
    save_requested = Signal()
    close_requested = Signal()

    def __init__(self, config: Config, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._config = config
        self._cfg = config.get("toolbar")
        self._active: Tool | None = None
        self._tool_buttons: dict[Tool, _IconButton] = {}
        self._palette: _ColorPalette | None = None
        self._width_palette: _WidthPalette | None = None

        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowTitle("FloatShot 标注")

        layout = QHBoxLayout(self)
        pad = int(self._cfg["padding"])
        layout.setContentsMargins(pad, pad, pad, pad)
        layout.setSpacing(int(self._cfg["spacing"]))

        self._color_button = _ColorButton(
            self._cfg, str(config.get("annotation", "stroke_color")), self
        )
        self._color_button.clicked.connect(self._open_palette)
        layout.addWidget(self._color_button)

        self._width_button = _WidthButton(
            self._cfg, int(config.get("annotation", "stroke_width")), self
        )
        self._width_button.clicked.connect(self._open_width_palette)
        layout.addWidget(self._width_button)
        layout.addWidget(self._separator())

        for kind, tool, tip in _TOOL_BUTTONS:
            button = _IconButton(kind, self._cfg, checkable=True, parent=self)
            button.setToolTip(tip)
            button.clicked.connect(
                lambda checked, t=tool: self._on_tool_clicked(t, checked)
            )
            layout.addWidget(button)
            self._tool_buttons[tool] = button

        layout.addWidget(self._separator())
        self._undo = self._action_button("undo", "撤销", self.undo_requested)
        self._redo = self._action_button("redo", "重做", self.redo_requested)
        layout.addWidget(self._undo)
        layout.addWidget(self._redo)

        layout.addWidget(self._separator())
        layout.addWidget(self._action_button("ai", "AI 识别", self.ai_requested))
        layout.addWidget(self._action_button("save", "另存为", self.save_requested))
        layout.addWidget(self._action_button("close", "关闭工具栏",
                                             self.close_requested))

        self.set_history(False, False)
        self.adjustSize()

    # -- construction helpers ---------------------------------------------

    def _separator(self) -> QFrame:
        line = QFrame(self)
        line.setFixedWidth(1)
        line.setFixedHeight(int(int(self._cfg["button_size"]) * 0.6))
        line.setStyleSheet(
            f"background-color: {self._cfg['separator_color']}; border: none;"
        )
        return line

    def _action_button(self, kind: str, tip: str, signal) -> _IconButton:
        button = _IconButton(kind, self._cfg, parent=self)
        button.setToolTip(tip)
        button.clicked.connect(signal.emit)
        return button

    # -- state -------------------------------------------------------------

    def set_history(self, can_undo: bool, can_redo: bool) -> None:
        self._undo.setEnabled(can_undo)
        self._redo.setEnabled(can_redo)
        self._undo.update()
        self._redo.update()

    def set_active_tool(self, tool: Tool | None) -> None:
        self._active = tool
        for candidate, button in self._tool_buttons.items():
            button.setChecked(candidate is tool)

    def set_color(self, colour: str) -> None:
        self._color_button.set_colour(colour)

    def set_width(self, width: int) -> None:
        self._width_button.set_width(width)
        if self._width_palette is not None:
            self._width_palette.set_current(width)

    def _open_width_palette(self) -> None:
        if self._width_palette is None:
            self._width_palette = _WidthPalette(self._config, self)
            self._width_palette.picked.connect(self._on_width_picked)
        self._width_palette.set_current(self._width_button.width_value())
        self._width_palette.adjustSize()
        anchor = self._width_button.mapToGlobal(QPoint(0, 0))
        self._width_palette.move(
            anchor.x(),
            anchor.y() - self._width_palette.height() - 4,
        )
        self._width_palette.show()

    def _on_width_picked(self, width: int) -> None:
        self.set_width(width)
        self.width_changed.emit(width)

    def _open_palette(self) -> None:
        if self._palette is None:
            self._palette = _ColorPalette(self._config, self)
            self._palette.picked.connect(self._on_colour_picked)
        self._palette.adjustSize()
        # Open above the button, the way a palette hangs off a pen.
        anchor = self._color_button.mapToGlobal(QPoint(0, 0))
        self._palette.move(
            anchor.x(),
            anchor.y() - self._palette.height() - 4,
        )
        self._palette.show()

    def _on_colour_picked(self, colour: str) -> None:
        self.set_color(colour)
        self.color_changed.emit(colour)

    def _on_tool_clicked(self, tool: Tool, checked: bool) -> None:
        # Clicking the active tool turns it off, returning the window to
        # move/resize behaviour. Otherwise the clicked tool becomes the only
        # active one.
        self.set_active_tool(tool if checked else None)
        self.tool_changed.emit(self._active)

    # -- painting ----------------------------------------------------------

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            radius = float(self._cfg["radius"])
            painter.setBrush(QColor(self._cfg["background"]))
            painter.setPen(QPen(QColor(self._cfg["border_color"]), 1))
            painter.drawRoundedRect(
                QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), radius, radius
            )
        finally:
            painter.end()


# ---------------------------------------------------------------------------
# Icon drawing. Everything is expressed inside a size x size box at the
# origin; the caller has already translated the painter.
# ---------------------------------------------------------------------------

def _draw_icon(painter: QPainter, kind: str, size: float, color: QColor) -> None:
    margin = size * 0.18
    box = QRectF(margin, margin, size - 2 * margin, size - 2 * margin)
    width = max(1.4, size * 0.10)
    pen = QPen(color, width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)

    if kind == "rect":
        painter.drawRoundedRect(box, size * 0.08, size * 0.08)
    elif kind == "ellipse":
        painter.drawEllipse(box)
    elif kind == "arrow":
        _draw_line_arrow(painter, QPointF(box.left(), box.bottom()),
                         QPointF(box.right(), box.top()), size * 0.30)
    elif kind == "pen":
        painter.drawLine(QPointF(box.left(), box.bottom()),
                         QPointF(box.right(), box.top()))
        painter.drawLine(QPointF(box.left() + size * 0.02, box.bottom()),
                         QPointF(box.left() - size * 0.02, box.bottom() - size * 0.02))
    elif kind == "text":
        font = QFont()
        font.setPixelSize(max(1, int(size * 0.92)))
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(QRectF(0, 0, size, size),
                         Qt.AlignmentFlag.AlignCenter, "A")
    elif kind == "ai":
        font = QFont()
        font.setPixelSize(max(1, int(size * 0.52)))
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(QRectF(0, 0, size, size),
                         Qt.AlignmentFlag.AlignCenter, "AI")
    elif kind == "mosaic":
        _draw_mosaic(painter, box, color)
    elif kind == "number":
        painter.drawEllipse(box)
        font = QFont()
        font.setPixelSize(max(1, int(size * 0.62)))
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(QRectF(0, 0, size, size),
                         Qt.AlignmentFlag.AlignCenter, "1")
    elif kind == "highlight":
        _draw_highlight(painter, box, color, size)
    elif kind == "undo":
        _draw_tail_arrow(painter, box, mirrored=False)
    elif kind == "redo":
        _draw_tail_arrow(painter, box, mirrored=True)
    elif kind == "save":
        _draw_save(painter, box)
    elif kind == "close":
        painter.drawLine(box.topLeft(), box.bottomRight())
        painter.drawLine(box.topRight(), box.bottomLeft())


def _draw_line_arrow(painter: QPainter, tail: QPointF, tip: QPointF,
                     barb: float) -> None:
    painter.drawLine(tail, tip)
    angle = math.atan2(tip.y() - tail.y(), tip.x() - tail.x())
    sweep = math.radians(24.0)
    for delta in (sweep + math.pi, -sweep + math.pi):
        painter.drawLine(
            tip,
            QPointF(tip.x() + barb * math.cos(angle + delta),
                    tip.y() + barb * math.sin(angle + delta)),
        )


def _draw_mosaic(painter: QPainter, box: QRectF, color: QColor) -> None:
    cell = box.width() / 2.0
    painter.setPen(Qt.PenStyle.NoPen)
    for gx in range(2):
        for gy in range(2):
            painter.setBrush(color if (gx + gy) % 2 == 0
                             else Qt.BrushStyle.NoBrush)
            painter.drawRect(QRectF(box.left() + gx * cell,
                                    box.top() + gy * cell, cell, cell))


def _draw_highlight(painter: QPainter, box: QRectF, color: QColor,
                    size: float) -> None:
    marker = QColor(color)
    marker.setAlpha(100)
    pen = QPen(marker, max(2.0, size * 0.34))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    painter.drawLine(QPointF(box.left(), box.bottom()),
                     QPointF(box.right(), box.top()))
    pen = QPen(color, max(1.4, size * 0.08))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    painter.drawLine(QPointF(box.left(), box.bottom()),
                     QPointF(box.left(), box.top()))
    painter.drawLine(QPointF(box.left(), box.top()),
                     QPointF(box.right(), box.top()))


def _draw_tail_arrow(painter: QPainter, box: QRectF, *, mirrored: bool) -> None:
    """A horizontal arrow with a short hook, reading as undo / redo."""
    start = QPointF(box.right(), box.center().y())
    end = QPointF(box.left(), box.center().y())
    if mirrored:
        start, end = end, start
    painter.drawLine(start, end)
    hook = QPointF(end.x(), box.top())
    painter.drawLine(end, hook)
    angle = math.atan2(end.y() - start.y(), end.x() - start.x())
    barb = box.width() * 0.34
    for delta in (math.radians(26.0), math.radians(-26.0)):
        painter.drawLine(
            end,
            QPointF(end.x() + barb * math.cos(angle + delta),
                    end.y() + barb * math.sin(angle + delta)),
        )


def _draw_save(painter: QPainter, box: QRectF) -> None:
    middle = box.center().x()
    painter.drawLine(QPointF(middle, box.top()), QPointF(middle, box.bottom()))
    barb = box.width() * 0.34
    tip = QPointF(middle, box.bottom())
    for delta in (math.radians(150.0), math.radians(30.0)):
        painter.drawLine(
            tip,
            QPointF(tip.x() + barb * math.cos(delta),
                    tip.y() + barb * math.sin(delta)),
        )
