"""The floating screenshot window.

Frameless, translucent, always on top, with a hand-painted soft shadow and
a circular close button that fades in on hover.

The shadow is painted rather than done with QGraphicsDropShadowEffect:
that effect is unreliable on Windows for translucent frameless top-level
windows, and it applies to the whole widget tree, which would put a shadow
behind the close button too.
"""

from __future__ import annotations

import math

from PySide6.QtCore import (
    Property,
    QDateTime,
    QEasingCurve,
    QPoint,
    QPointF,
    QPropertyAnimation,
    QRect,
    QRectF,
    Qt,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QGuiApplication,
    QPainter,
    QPen,
    QPixmap,
    QPolygonF,
)
from PySide6.QtWidgets import (
    QFileDialog,
    QInputDialog,
    QMenu,
    QMessageBox,
    QWidget,
)

from .annotation_paint import AnnotationRenderer, text_box_size
from .ai_bar import AiBar
from .annotations import (
    Annotation,
    Document,
    Tool,
    angle_deg,
    corner_points,
    map_to_image,
    point_in_rotated_rect,
    rotate_point,
)
from .config import Config
from .dpi import ui_scale
from .geometry import (
    Edge,
    apply_resize,
    fit_aspect_corner,
    fit_aspect_width,
    fit_aspect_height,
    hit_test,
)
from .metrics import Metrics, compute_metrics
from .toolbar import EditorToolbar

# Cursor shape per edge combination.
_CURSORS: dict[Edge, Qt.CursorShape] = {
    Edge.LEFT: Qt.CursorShape.SizeHorCursor,
    Edge.RIGHT: Qt.CursorShape.SizeHorCursor,
    Edge.TOP: Qt.CursorShape.SizeVerCursor,
    Edge.BOTTOM: Qt.CursorShape.SizeVerCursor,
    Edge.LEFT | Edge.TOP: Qt.CursorShape.SizeFDiagCursor,
    Edge.RIGHT | Edge.BOTTOM: Qt.CursorShape.SizeFDiagCursor,
    Edge.RIGHT | Edge.TOP: Qt.CursorShape.SizeBDiagCursor,
    Edge.LEFT | Edge.BOTTOM: Qt.CursorShape.SizeBDiagCursor,
}


def _with_alpha(color: QColor, alpha: int) -> QColor:
    """`color` with its alpha replaced, leaving the RGB untouched.

    Configured colours carry no usable alpha of their own -- the painted
    alpha is computed per layer or multiplied by the fade -- so it is
    overridden rather than blended in.
    """
    out = QColor(color)
    out.setAlpha(max(0, min(255, alpha)))
    return out


class FloatWindow(QWidget):
    """A frameless always-on-top window showing one screenshot."""

    closed = Signal(object)

    def __init__(self, pixmap: QPixmap, config: Config,
                 scale: float | None = None) -> None:
        super().__init__(None)
        self._pixmap = pixmap
        self._config = config
        self._scale = ui_scale() if scale is None else scale

        # Shadow padding depends only on DPI, never on window size, so it is
        # resolved once here. Everything else derives from it.
        self._shadow_cfg = config.get("shadow")
        self._pad = max(1, math.ceil(self._shadow_cfg["padding"] * self._scale))

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMouseTracking(True)
        # Needed for the Esc shortcut to reach keyPressEvent.
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self._active_edge = Edge.NONE
        self._press_pos: QPoint | None = None
        self._press_geom: tuple[int, int, int, int] | None = None

        self._metrics = self._metrics_for(pixmap.width(), pixmap.height())
        self.setGeometry(0, 0,
                         pixmap.width() + 2 * self._pad,
                         pixmap.height() + 2 * self._pad)

        self._close_opacity = 0.0
        self._close_anim = QPropertyAnimation(self, b"closeOpacity", self)
        self._close_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        # Annotation state. The renderer keeps the untouched picture so the
        # mosaic tool can always sample the original pixels, and so undo can
        # simply stop painting an item instead of un-painting one.
        self._ann_cfg = config.get("annotation")
        self._doc = Document()
        self._renderer = AnnotationRenderer(pixmap, self._ann_cfg)
        self._tool: Tool | None = None
        self._pending: Annotation | None = None
        self._toolbar: EditorToolbar | None = None
        self._ai_bar: AiBar | None = None
        # None means "use the per-tool default from config"; a string is a
        # colour the user picked, applied to new marks and to the selection.
        self._color: str | None = None
        self._width: float | None = None
        self._dragged = False

        # Text selection / transform state.
        self._selected: Annotation | None = None
        self._text_mode: str | None = None
        self._text_center: tuple[float, float] = (0.0, 0.0)
        self._text_font = 0
        self._text_rotation = 0.0
        self._text_press_at: tuple[float, float] = (0.0, 0.0)
        self._text_distance = 1.0
        self._text_angle = 0.0

        self.setWindowTitle("FloatShot")

    # -- geometry helpers ------------------------------------------------

    def _metrics_for(self, img_w: int, img_h: int) -> Metrics:
        """Element sizes for a window whose picture area is img_w x img_h.

        Takes the PICTURE size: compute_metrics derives the window size from
        it, because the resize bands are anchored to the picture's edges.
        """
        cb = self._config.get("close_button")
        r = self._config.get("resize")
        return compute_metrics(
            self._scale,
            img_w,
            img_h,
            shadow_padding=self._shadow_cfg["padding"],
            grip_ratio=r["grip_ratio"],
            close_diameter_px=cb["diameter_px"],
            close_hit_radius_factor=cb["hit_radius_factor"],
        )

    def image_rect(self) -> QRect:
        """Where the picture sits inside the window, excluding shadow padding."""
        p = self._pad
        return QRect(p, p,
                     max(1, self.width() - 2 * p),
                     max(1, self.height() - 2 * p))

    def close_button_center(self) -> QPointF:
        """Centre of the close button: the picture's top-right corner."""
        r = self.image_rect()
        return QPointF(r.x() + r.width(), r.y())

    # -- close button opacity animation ----------------------------------

    def _get_close_opacity(self) -> float:
        return self._close_opacity

    def _set_close_opacity(self, value: float) -> None:
        self._close_opacity = value
        self.update()

    closeOpacity = Property(float, _get_close_opacity, _set_close_opacity)

    def _animate_close_button(self, target: float) -> None:
        cb = self._config.get("close_button")
        self._close_anim.stop()
        self._close_anim.setDuration(int(cb["fade_ms"]))
        self._close_anim.setStartValue(self._close_opacity)
        self._close_anim.setEndValue(target)
        self._close_anim.start()

    # -- painting --------------------------------------------------------

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt override)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        try:
            self._paint_shadow(painter)
            self._paint_image(painter)
            self._paint_annotations(painter)
            self._paint_outline(painter)
            self._paint_corner_dots(painter)
            self._paint_selection(painter)
            # Painted last so it covers the top-right corner dot while hovered.
            self._paint_close_button(painter)
        finally:
            painter.end()

    def _paint_shadow(self, painter: QPainter) -> None:
        """Concentric rounded rects with falling alpha, darkest at the edge."""
        s = self._shadow_cfg
        layers = max(1, int(s["layers"]))
        max_alpha = max(0, int(s["max_alpha"]))
        offset_y = float(s["offset_y"])
        radius = float(s["radius"])
        falloff = float(s["falloff"])
        color = QColor(s["color"])
        pad = self._pad

        if max_alpha <= 0 or pad <= 0:
            return

        base = QRectF(self.image_rect())
        painter.setPen(Qt.PenStyle.NoPen)

        for i in range(layers):
            t = i / max(1, layers - 1)
            expand = pad * (1.0 - t)
            alpha = int(max_alpha * (t ** falloff))
            if alpha <= 0:
                continue
            rect = base.adjusted(-expand, -expand, expand, expand)
            rect.translate(0, offset_y * (1.0 - t))
            painter.setBrush(_with_alpha(color, alpha))
            painter.drawRoundedRect(rect, radius, radius)

    def _paint_image(self, painter: QPainter) -> None:
        target = self.image_rect()
        painter.drawPixmap(target, self._pixmap)

    def _paint_annotations(self, painter: QPainter) -> None:
        """Draw the items scaled into the picture's on-screen rect.

        Items live in image coordinates, so the painter is scaled to the
        picture's current display size rather than the items being.
        """
        items = self._doc.items
        if not items and self._pending is None:
            return
        target = self.image_rect()
        painter.save()
        painter.translate(target.x(), target.y())
        painter.scale(
            target.width() / max(1, self._pixmap.width()),
            target.height() / max(1, self._pixmap.height()),
        )
        self._renderer.paint(painter, items, self._pending)
        painter.restore()

    def _paint_selection(self, painter: QPainter) -> None:
        """Dashed frame, corner handles and rotation handle for the selection."""
        selected = self._selected
        if selected is None or not self._drawing_tool_active():
            return

        target = self.image_rect()
        scale_x = target.width() / max(1, self._pixmap.width())
        scale_y = target.height() / max(1, self._pixmap.height())

        def to_widget(point: tuple[float, float]) -> QPointF:
            return QPointF(target.x() + point[0] * scale_x,
                           target.y() + point[1] * scale_y)

        centre = selected.points[0]
        width, height = text_box_size(selected)
        corners = [
            rotate_point(x, y, centre[0], centre[1], selected.rotation)
            for x, y in corner_points(centre[0], centre[1], width, height)
        ]

        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor("#4A9EFF"), 1, Qt.PenStyle.DashLine))
        painter.drawPolygon(QPolygonF([to_widget(c) for c in corners]))

        top_mid = rotate_point(centre[0], centre[1] - height / 2.0,
                               centre[0], centre[1], selected.rotation)
        rotation_handle = self._rotation_handle_point(selected)

        painter.setPen(QPen(QColor("#4A9EFF"), 1))
        painter.drawLine(to_widget(top_mid), to_widget(rotation_handle))

        painter.setBrush(QColor("#FFFFFF"))
        for point in corners:
            painter.drawEllipse(to_widget(point), 4.0, 4.0)
        painter.setBrush(QColor("#4A9EFF"))
        painter.drawEllipse(to_widget(rotation_handle), 4.0, 4.0)

    def _paint_outline(self, painter: QPainter) -> None:
        """Coloured frame just outside the picture.

        Without it a freshly pasted screenshot blends into whatever is
        behind it; the frame is what makes it read as "a window appeared
        here" rather than as part of the desktop.
        """
        o = self._config.get("outline")
        if not o["enabled"]:
            return

        width = max(1, math.ceil(int(o["width_px"]) * self._scale))
        offset = math.ceil(int(o["offset_px"]) * self._scale)
        # A stroked path straddles the path line, so push the rect out by
        # half the stroke width: the frame then sits entirely outside the
        # picture and never covers a pixel of the screenshot itself.
        half = width / 2.0
        rect = QRectF(self.image_rect()).adjusted(
            -half - offset, -half - offset, half + offset, half + offset
        )

        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(o["color"]), width))
        painter.drawRect(rect)

    def _paint_corner_dots(self, painter: QPainter) -> None:
        """A dot on each of the four corners, marking the resize handles."""
        c = self._config.get("corner_dots")
        if not c["enabled"]:
            return

        radius = max(1, math.ceil(int(c["diameter_px"]) * self._scale)) / 2.0
        img = QRectF(self.image_rect())

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(c["color"]))
        # QRectF's right()/bottom() are the far edges (x + width), which is
        # where a corner dot belongs -- unlike QRect's, which is one less.
        for cx in (img.left(), img.right()):
            for cy in (img.top(), img.bottom()):
                painter.drawEllipse(QPointF(cx, cy), radius, radius)

    def _paint_close_button(self, painter: QPainter) -> None:
        if self._close_opacity <= 0.01:
            return

        cb = self._config.get("close_button")
        centre = self.close_button_center()
        radius = self._metrics.close_diameter / 2.0
        alpha = max(0.0, min(1.0, self._close_opacity))
        disc_alpha = int(int(cb["disc_alpha"]) * alpha)
        cross_alpha = int(int(cb["cross_alpha"]) * alpha)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(_with_alpha(QColor(cb["disc_color"]), disc_alpha))
        painter.drawEllipse(centre, radius, radius)

        # The cross, drawn as two short strokes.
        arm = radius * float(cb["cross_arm_ratio"])
        painter.setPen(QPen(
            _with_alpha(QColor(cb["cross_color"]), cross_alpha),
            max(1.0, radius * float(cb["cross_stroke_ratio"])),
        ))
        painter.drawLine(
            QPointF(centre.x() - arm, centre.y() - arm),
            QPointF(centre.x() + arm, centre.y() + arm),
        )
        painter.drawLine(
            QPointF(centre.x() + arm, centre.y() - arm),
            QPointF(centre.x() - arm, centre.y() + arm),
        )

    # -- mouse interaction -----------------------------------------------

    def _edge_at(self, pos: QPoint) -> Edge:
        return hit_test(pos.x(), pos.y(), self.width(), self.height(),
                        self._metrics.grip_x, self._metrics.grip_y)

    def enterEvent(self, event) -> None:  # noqa: N802
        self._animate_close_button(float(self._config.get("close_button", "hover_opacity")))
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._animate_close_button(0.0)
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.RightButton:
            self._show_context_menu(event.globalPosition().toPoint())
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        pos = event.position().toPoint()

        if self._hits_close_button(event.position()):
            self.close()   # closeEvent is the single place that emits `closed`
            return

        if self._drawing_tool_active() and self._image_point(event.position())[2]:
            if self._tool is Tool.TEXT:
                self._text_press(event.position())
            else:
                self._begin_annotation(event.position())
            return

        self._dragged = False
        self._press_pos = event.globalPosition().toPoint()
        self._active_edge = self._edge_at(pos)
        self._press_geom = (self.x(), self.y(), self.width(), self.height())

    def _drawing_tool_active(self) -> bool:
        return self._tool is not None and self._toolbar is not None \
            and self._toolbar.isVisible()

    def _image_point(self, pos: QPointF) -> tuple[float, float, bool]:
        """Map a widget-space point onto the picture's own pixel grid."""
        r = self.image_rect()
        return map_to_image(
            pos.x(), pos.y(),
            (r.x(), r.y(), r.width(), r.height()),
            self._pixmap.width(), self._pixmap.height(),
        )

    def _begin_annotation(self, pos: QPointF) -> None:
        """Start the stroke under the pointer for the drag-style tools."""
        ix, iy, _ = self._image_point(pos)
        tool = self._tool
        assert tool is not None

        if tool is Tool.NUMBER:
            self._doc.add(Annotation(
                tool=Tool.NUMBER,
                points=[(ix, iy)],
                color=self._color or self._ann_cfg["number_color"],
                number=self._doc.next_number(),
                font_px=int(self._ann_cfg["number_font_px"]),
            ))
            self._after_change()
            return

        color, width = self._tool_style(tool)
        self._pending = Annotation(
            tool=tool, points=[(ix, iy)], color=color, width=width
        )
        self.update()

    # -- text: place / select / move / scale / rotate ---------------------

    def _text_press(self, pos: QPointF) -> None:
        ix, iy, _ = self._image_point(pos)

        if self._selected is not None:
            handle = self._handle_at(ix, iy)
            if handle is not None:
                self._start_text_drag("rotate" if handle == "rotate" else "scale",
                                      ix, iy)
                return
            if self._inside_selection(ix, iy):
                self._start_text_drag("move", ix, iy)
                return

        hit = self._text_at(ix, iy)
        if hit is not None:
            self._selected = hit
            self._start_text_drag("move", ix, iy)
            self.update()
            return

        self._new_text(ix, iy)

    def _new_text(self, ix: float, iy: float) -> None:
        self._selected = None
        text, ok = QInputDialog.getText(self, "文字", "输入文字：")
        if not ok or not text:
            self.update()
            return
        annotation = Annotation(
            tool=Tool.TEXT,
            points=[(ix, iy)],
            color=self._color or self._ann_cfg["text_color"],
            text=text,
            font_px=int(self._ann_cfg["text_font_px"]),
        )
        self._doc.add(annotation)
        # Select it straight away so it can be dragged/scaled/rotated without
        # a second click.
        self._selected = annotation
        self._after_change()

    def _start_text_drag(self, mode: str, ix: float, iy: float) -> None:
        selected = self._selected
        assert selected is not None
        self._text_mode = mode
        self._text_center = selected.points[0]
        self._text_font = int(selected.font_px)
        self._text_rotation = selected.rotation
        self._text_press_at = (ix, iy)
        self._text_distance = max(
            1.0,
            math.hypot(ix - self._text_center[0], iy - self._text_center[1]),
        )
        self._text_angle = angle_deg(
            self._text_center[0], self._text_center[1], ix, iy
        )

    def _text_box(self, annotation: Annotation) -> tuple[float, float, float, float]:
        """(centre_x, centre_y, width, height) in image coordinates."""
        width, height = text_box_size(annotation)
        return (annotation.points[0][0], annotation.points[0][1], width, height)

    def _handle_image_radius(self) -> float:
        target = self.image_rect()
        return 7.0 * max(1, self._pixmap.width()) / max(1, target.width())

    def _rotation_handle_point(self, annotation: Annotation) -> tuple[float, float]:
        cx, cy, _, height = self._text_box(annotation)
        gap = 26.0 * max(1, self._pixmap.width()) / max(1, self.image_rect().width())
        return rotate_point(cx, cy - height / 2.0 - gap, cx, cy, annotation.rotation)

    def _handle_at(self, ix: float, iy: float) -> str | None:
        selected = self._selected
        if selected is None:
            return None
        cx, cy, width, height = self._text_box(selected)
        radius = self._handle_image_radius()

        hx, hy = self._rotation_handle_point(selected)
        if math.hypot(ix - hx, iy - hy) <= radius * 1.4:
            return "rotate"

        for index, (x, y) in enumerate(corner_points(cx, cy, width, height)):
            rx, ry = rotate_point(x, y, cx, cy, selected.rotation)
            if math.hypot(ix - rx, iy - ry) <= radius:
                return f"corner{index}"
        return None

    def _inside_selection(self, ix: float, iy: float) -> bool:
        selected = self._selected
        if selected is None:
            return False
        cx, cy, width, height = self._text_box(selected)
        return point_in_rotated_rect(
            ix, iy, cx, cy, width, height, selected.rotation
        )

    def _text_at(self, ix: float, iy: float) -> Annotation | None:
        for item in reversed(self._doc.items):
            if item.tool is not Tool.TEXT:
                continue
            cx, cy, width, height = self._text_box(item)
            if point_in_rotated_rect(ix, iy, cx, cy, width, height, item.rotation):
                return item
        return None

    def _drag_text(self, ix: float, iy: float) -> None:
        selected = self._selected
        if selected is None or self._text_mode is None:
            return
        if self._text_mode == "move":
            dx = ix - self._text_press_at[0]
            dy = iy - self._text_press_at[1]
            selected.points = [
                (self._text_center[0] + dx, self._text_center[1] + dy)
            ]
        elif self._text_mode == "scale":
            distance = math.hypot(
                ix - self._text_center[0], iy - self._text_center[1]
            )
            factor = distance / self._text_distance
            selected.font_px = max(6, int(round(self._text_font * factor)))
        elif self._text_mode == "rotate":
            current = angle_deg(
                self._text_center[0], self._text_center[1], ix, iy
            )
            selected.rotation = self._text_rotation + (current - self._text_angle)
        self.update()

    def _tool_style(self, tool: Tool) -> tuple[str, float]:
        if tool is Tool.HIGHLIGHT:
            return self._color or self._ann_cfg["highlight_color"], float(
                self._width or self._ann_cfg["highlight_width"])
        if tool is Tool.MOSAIC:
            # The mosaic never paints its own colour; it samples the picture.
            return self._ann_cfg["stroke_color"], float(
                self._width or self._ann_cfg["mosaic_brush"])
        return self._color or self._ann_cfg["stroke_color"], float(
            self._width or self._ann_cfg["stroke_width"])

    def _hits_close_button(self, pos: QPointF) -> bool:
        centre = self.close_button_center()
        r = self._metrics.close_hit_radius
        return (pos.x() - centre.x()) ** 2 + (pos.y() - centre.y()) ** 2 <= r * r

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        pos = event.position().toPoint()

        if self._text_mode is not None:
            ix, iy, _ = self._image_point(event.position())
            self._drag_text(ix, iy)
            return

        if self._pending is not None:
            ix, iy, _ = self._image_point(event.position())
            self._pending.points.append((ix, iy))
            self.update()
            return

        if self._press_pos is None:
            # Not dragging: just reflect what the cursor is over.
            if self._drawing_tool_active() and self._image_point(
                    event.position())[2]:
                self.setCursor(self._annotation_cursor(event.position()))
                return
            edge = self._edge_at(pos)
            if self._hits_close_button(event.position()):
                self.setCursor(Qt.CursorShape.PointingHandCursor)
            else:
                self.setCursor(_CURSORS.get(edge, Qt.CursorShape.ArrowCursor))
            return

        if (event.globalPosition().toPoint() - self._press_pos).manhattanLength() > 3:
            self._dragged = True
        delta = event.globalPosition().toPoint() - self._press_pos
        if self._active_edge == Edge.NONE:
            self._drag_by(delta)
        else:
            self._resize_by(delta, event.modifiers())

    def _annotation_cursor(self, pos: QPointF) -> Qt.CursorShape:
        if self._tool is not Tool.TEXT:
            return Qt.CursorShape.CrossCursor
        ix, iy, _ = self._image_point(pos)
        handle = self._handle_at(ix, iy)
        if handle == "rotate":
            return Qt.CursorShape.CrossCursor
        if handle is not None:
            return Qt.CursorShape.SizeFDiagCursor
        if self._inside_selection(ix, iy) or self._text_at(ix, iy) is not None:
            return Qt.CursorShape.SizeAllCursor
        return Qt.CursorShape.CrossCursor


    def _drag_by(self, delta: QPoint) -> None:
        assert self._press_geom is not None
        x, y, _, _ = self._press_geom
        self.move(x + delta.x(), y + delta.y())

    def _resize_by(self, delta: QPoint, modifiers: Qt.KeyboardModifier) -> None:
        assert self._press_geom is not None
        r = self._config.get("resize")
        min_w = max(1, int(r["min_width"]))
        min_h = max(1, int(r["min_height"]))
        lock_aspect = bool(modifiers & Qt.KeyboardModifier.ShiftModifier)

        x, y, w, h = apply_resize(
            self._press_geom, self._active_edge, delta.x(), delta.y(),
            min_w=min_w,
            min_h=min_h,
        )

        if lock_aspect:
            # Constrain the picture area to the source aspect, then add the
            # shadow padding back on: padding is fixed, so the ratio applies
            # to the image region only.
            pad = self._pad
            img_w = max(1, w - 2 * pad)
            img_h = max(1, h - 2 * pad)
            src_w, src_h = self._pixmap.width(), self._pixmap.height()
            # Only one edge is dragged at a time, so a pure left/right or
            # top/bottom edge is a single flag -- corners fall through.
            if self._active_edge in (Edge.LEFT, Edge.RIGHT):
                img_w, img_h = fit_aspect_width(src_w, src_h, img_w)
            elif self._active_edge in (Edge.TOP, Edge.BOTTOM):
                img_w, img_h = fit_aspect_height(src_w, src_h, img_h)
            else:
                img_w, img_h = fit_aspect_corner(src_w, src_h, img_w, img_h)

            # apply_resize clamped the *window*, but re-deriving the size
            # from aspect-fitted image dimensions can undo that: a very
            # lopsided source shrinks the short side below the minimum. The
            # clamp below happens in picture space so the ratio survives --
            # both sides are grown by the same factor, whichever of the two
            # minimums binds harder.
            min_img_w = max(1, min_w - 2 * pad)
            min_img_h = max(1, min_h - 2 * pad)
            grow = max(min_img_w / img_w, min_img_h / img_h, 1.0)
            if grow > 1.0:
                img_w = max(min_img_w, math.ceil(img_w * grow))
                img_h = max(min_img_h, math.ceil(img_h * grow))

            new_w = img_w + 2 * pad
            new_h = img_h + 2 * pad
            # Keep the edges that are not being dragged anchored.
            if Edge.LEFT in self._active_edge:
                x = self._press_geom[0] + self._press_geom[2] - new_w
            if Edge.TOP in self._active_edge:
                y = self._press_geom[1] + self._press_geom[3] - new_h
            w, h = new_w, new_h

        self.setGeometry(x, y, w, h)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._text_mode is not None:
            self._text_mode = None
            self.update()
            return

        if self._pending is not None:
            # A plain click with a shape tool makes a zero-size mark, which
            # is noise; only a real gesture is committed.
            pending, self._pending = self._pending, None
            if len(pending.points) >= 2:
                self._doc.add(pending)
                self._after_change()
            else:
                self.update()
            return

        was_press = self._press_pos is not None
        dragged = self._dragged
        self._press_pos = None
        self._press_geom = None
        self._active_edge = Edge.NONE

        # A click that never turned into a drag toggles the toolbar, which is
        # how the editor is opened from an idle floating window.
        if was_press and not dragged:
            self._toggle_toolbar()

    # -- context menu -----------------------------------------------------

    def _show_context_menu(self, global_pos: QPoint) -> None:
        menu = QMenu(self)
        act_copy = menu.addAction("复制到剪切板")
        act_save = menu.addAction("另存为…")
        menu.addSeparator()
        act_close = menu.addAction("关闭")

        act_copy.triggered.connect(self._copy_to_clipboard)
        act_save.triggered.connect(self._save_as)
        act_close.triggered.connect(self.close)

        menu.exec(global_pos)

    def _copy_to_clipboard(self) -> None:
        QGuiApplication.clipboard().setPixmap(self._composite())

    def _save_as(self) -> None:
        """Ask for a destination, then write the composite picture there.

        The default name is timestamped so repeated saves do not overwrite
        each other, and PNG is the default format because it is lossless --
        a screenshot is exactly the kind of image where JPEG artefacts show.
        """
        default = QDateTime.currentDateTime().toString("yyyyMMdd-HHmmss") + ".png"
        path, _ = QFileDialog.getSaveFileName(
            self,
            "另存为",
            default,
            "PNG 图片 (*.png);;JPEG 图片 (*.jpg *.jpeg);;BMP 图片 (*.bmp)",
        )
        if not path:
            return
        if not self._composite().save(path):
            QMessageBox.warning(self, "FloatShot", f"保存失败：{path}")

    def _composite(self) -> QPixmap:
        """The picture with every annotation burned in, at full size."""
        return QPixmap.fromImage(self._renderer.flatten(self._doc.items))

    def _toggle_ai_bar(self) -> None:
        """Show/hide the single-line AI bar under this window."""
        if self._ai_bar is None:
            self._ai_bar = AiBar(self._config, self._composite())
            self._ai_bar.resized.connect(self._position_ai_bar)
        else:
            self._ai_bar.set_image(self._composite())
        if self._ai_bar.isVisible():
            self._ai_bar.hide()
            return
        self._position_ai_bar()
        self._ai_bar.show()
        self._ai_bar.raise_()

    def _position_ai_bar(self) -> None:
        """Hang the AI bar under the window, or under the toolbar if shown."""
        bar = self._ai_bar
        if bar is None:
            return
        gap = int(self._config.get("toolbar", "gap"))
        anchor_bottom = self.y() + self.height()
        if self._toolbar is not None and self._toolbar.isVisible():
            anchor_bottom = self._toolbar.y() + self._toolbar.height()
        size = bar.size()
        x = self.x() + (self.width() - size.width()) // 2
        y = anchor_bottom + gap

        screen = self.screen()
        if screen is not None:
            area = screen.availableGeometry()
            x = max(area.left(), min(x, area.right() - size.width() + 1))
            y = max(area.top(), min(y, area.bottom() - size.height() + 1))
        bar.move(x, y)

    # -- annotation / toolbar ---------------------------------------------

    def _after_change(self) -> None:
        self._sync_toolbar()
        self.update()

    def _sync_toolbar(self) -> None:
        if self._toolbar is not None:
            self._toolbar.set_history(self._doc.can_undo, self._doc.can_redo)

    def _toggle_toolbar(self) -> None:
        if self._toolbar is not None and self._toolbar.isVisible():
            self._hide_toolbar()
        else:
            self._show_toolbar()

    def _show_toolbar(self) -> None:
        if self._toolbar is None:
            self._toolbar = EditorToolbar(self._config, self)
            self._toolbar.tool_changed.connect(self._on_tool_changed)
            self._toolbar.color_changed.connect(self._on_color_changed)
            self._toolbar.width_changed.connect(self._on_width_changed)
            self._toolbar.ai_requested.connect(self._toggle_ai_bar)
            self._toolbar.undo_requested.connect(self._undo)
            self._toolbar.redo_requested.connect(self._redo)
            self._toolbar.save_requested.connect(self._save_as)
            self._toolbar.close_requested.connect(self._hide_toolbar)
            self._toolbar.set_color(
                self._color or str(self._ann_cfg["stroke_color"])
            )
            self._toolbar.set_width(
                int(self._width or self._ann_cfg["stroke_width"])
            )
        self._sync_toolbar()
        self._toolbar.adjustSize()
        self._position_toolbar()
        self._toolbar.show()
        self._toolbar.raise_()
        self._position_ai_bar()

    def _hide_toolbar(self) -> None:
        if self._toolbar is not None:
            self._toolbar.hide()
            self._toolbar.set_active_tool(None)
        self._tool = None
        self._selected = None
        self._text_mode = None
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self._position_ai_bar()

    def _position_toolbar(self) -> None:
        """Hang the bar just under the picture, kept on screen."""
        if self._toolbar is None:
            return
        gap = int(self._config.get("toolbar", "gap"))
        size = self._toolbar.size()
        x = self.x() + (self.width() - size.width()) // 2
        y = self.y() + self.height() + gap

        screen = self.screen()
        if screen is not None:
            area = screen.availableGeometry()
            x = max(area.left(), min(x, area.right() - size.width() + 1))
            if y + size.height() > area.bottom():
                # No room below: flip above, then clamp.
                y = self.y() - gap - size.height()
            y = max(area.top(), min(y, area.bottom() - size.height() + 1))
        self._toolbar.move(x, y)

    def _on_tool_changed(self, tool: Tool | None) -> None:
        self._tool = tool
        if tool is not Tool.TEXT:
            self._selected = None
            self._text_mode = None
        if tool is None:
            self.setCursor(Qt.CursorShape.ArrowCursor)
        else:
            self.setCursor(Qt.CursorShape.CrossCursor)

    def _on_color_changed(self, colour: str) -> None:
        """Adopt a picked colour, and re-colour the selected mark right away.

        Re-colouring the selection is what makes the palette feel like it is
        editing "the thing I just added" rather than only setting the next
        stroke.
        """
        self._color = colour
        if self._selected is not None:
            self._selected.color = colour
        self.update()

    def _on_width_changed(self, width: int) -> None:
        self._width = float(width)

    def _undo(self) -> None:
        self._doc.undo()
        self._after_change()

    def _redo(self) -> None:
        self._doc.redo()
        self._after_change()

    def resizeEvent(self, event) -> None:  # noqa: N802
        self._metrics = self._metrics_for(
            max(1, self.width() - 2 * self._pad),
            max(1, self.height() - 2 * self._pad),
        )
        self._position_toolbar()
        self._position_ai_bar()
        super().resizeEvent(event)

    def moveEvent(self, event) -> None:  # noqa: N802
        self._position_toolbar()
        self._position_ai_bar()
        super().moveEvent(event)

    def closeEvent(self, event) -> None:  # noqa: N802
        """The single point that announces closure, however it was triggered."""
        self._close_anim.stop()
        if self._toolbar is not None:
            self._toolbar.hide()
        if self._ai_bar is not None:
            self._ai_bar.close()
        self.closed.emit(self)
        super().closeEvent(event)
        self.deleteLater()

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            # Esc first backs out of annotation; only an idle window closes,
            # so a stray Esc cannot destroy a screenshot mid-edit.
            if self._drawing_tool_active():
                self._hide_toolbar()
                return
            self.close()   # closeEvent is the single place that emits `closed`
            return
        super().keyPressEvent(event)
