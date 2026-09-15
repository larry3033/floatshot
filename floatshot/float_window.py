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
    QEasingCurve,
    QPoint,
    QPointF,
    QPropertyAnimation,
    QRect,
    QRectF,
    Qt,
    Signal,
)
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QWidget

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

        self.setWindowTitle("FloatShot")

    # -- geometry helpers ------------------------------------------------

    def _metrics_for(self, img_w: int, img_h: int) -> Metrics:
        """Element sizes for a window whose picture area is img_w x img_h."""
        cb = self._config.get("close_button")
        r = self._config.get("resize")
        return compute_metrics(
            self._scale,
            img_w + 2 * self._pad,
            img_h + 2 * self._pad,
            shadow_padding=self._shadow_cfg["padding"],
            grip_px=r["grip_px"],
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
                        self._metrics.grip)

    def enterEvent(self, event) -> None:  # noqa: N802
        self._animate_close_button(float(self._config.get("close_button", "hover_opacity")))
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._animate_close_button(0.0)
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            return
        pos = event.position().toPoint()

        if self._hits_close_button(event.position()):
            self.close()   # closeEvent is the single place that emits `closed`
            return

        self._press_pos = event.globalPosition().toPoint()
        self._active_edge = self._edge_at(pos)
        self._press_geom = (self.x(), self.y(), self.width(), self.height())

    def _hits_close_button(self, pos: QPointF) -> bool:
        centre = self.close_button_center()
        r = self._metrics.close_hit_radius
        return (pos.x() - centre.x()) ** 2 + (pos.y() - centre.y()) ** 2 <= r * r

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        pos = event.position().toPoint()

        if self._press_pos is None:
            # Not dragging: just reflect what the cursor is over.
            edge = self._edge_at(pos)
            if self._hits_close_button(event.position()):
                self.setCursor(Qt.CursorShape.PointingHandCursor)
            else:
                self.setCursor(_CURSORS.get(edge, Qt.CursorShape.ArrowCursor))
            return

        delta = event.globalPosition().toPoint() - self._press_pos
        if self._active_edge == Edge.NONE:
            self._drag_by(delta)
        else:
            self._resize_by(delta, event.modifiers())

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
        self._press_pos = None
        self._press_geom = None
        self._active_edge = Edge.NONE

    def resizeEvent(self, event) -> None:  # noqa: N802
        self._metrics = self._metrics_for(
            max(1, self.width() - 2 * self._pad),
            max(1, self.height() - 2 * self._pad),
        )
        super().resizeEvent(event)

    def closeEvent(self, event) -> None:  # noqa: N802
        """The single point that announces closure, however it was triggered."""
        self._close_anim.stop()
        self.closed.emit(self)
        super().closeEvent(event)
        self.deleteLater()

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            self.close()   # closeEvent is the single place that emits `closed`
            return
        super().keyPressEvent(event)
