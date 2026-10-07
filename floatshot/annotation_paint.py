"""Paint annotation items with QPainter, in image coordinates.

The painter is expected to already be transformed into image space, so this
module never scales anything itself. The same code therefore serves both the
on-screen preview (painter scaled to the window) and the full-resolution
composite written by "save as" / "copy" (painter scale 1).
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetricsF,
    QImage,
    QPainter,
    QPainterPath,
    QPainterPathStroker,
    QPen,
    QPixmap,
    QPolygonF,
)

from .annotations import Annotation, Tool, arrow_head, normalize_rect


def text_box_size(item: Annotation) -> tuple[float, float]:
    """The on-picture size of a text annotation, in image pixels.

    Shared by the painter and by the window's handle hit-testing so the
    selection frame can never drift from what is actually drawn.
    """
    font = QFont()
    font.setPixelSize(max(1, int(item.font_px)))
    bounds = QFontMetricsF(font).boundingRect(item.text or " ")
    pad = max(2.0, float(item.font_px) * 0.18)
    return (bounds.width() + 2 * pad, bounds.height() + 2 * pad)



class AnnotationRenderer:
    """Draws a Document's items and can flatten them into an image.

    Holds the untouched base picture so the mosaic tool can sample it: the
    pixelated version is built once per window rather than per stroke.
    """

    def __init__(self, base: QPixmap, config: dict) -> None:
        self._base = base
        self._cfg = config
        self._mosaic: QPixmap | None = None

    # -- public -----------------------------------------------------------

    def paint(
        self,
        painter: QPainter,
        items: list[Annotation],
        pending: Annotation | None = None,
    ) -> None:
        for item in items:
            self._paint_item(painter, item)
        if pending is not None:
            self._paint_item(painter, pending)

    def flatten(self, items: list[Annotation]) -> QImage:
        """Return the base picture with every item composited at full size."""
        image = self._base.toImage()
        painter = QPainter(image)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            self.paint(painter, items)
        finally:
            painter.end()
        return image

    # -- dispatch ---------------------------------------------------------

    def _paint_item(self, painter: QPainter, item: Annotation) -> None:
        if item.tool is Tool.RECT:
            self._paint_rect(painter, item)
        elif item.tool is Tool.ELLIPSE:
            self._paint_ellipse(painter, item)
        elif item.tool is Tool.ARROW:
            self._paint_arrow(painter, item)
        elif item.tool in (Tool.PEN, Tool.HIGHLIGHT):
            self._paint_stroke(painter, item)
        elif item.tool is Tool.MOSAIC:
            self._paint_mosaic(painter, item)
        elif item.tool is Tool.TEXT:
            self._paint_text(painter, item)
        elif item.tool is Tool.NUMBER:
            self._paint_number(painter, item)

    # -- shape tools ------------------------------------------------------

    def _paint_rect(self, painter: QPainter, item: Annotation) -> None:
        x, y, w, h = normalize_rect(item.points[0], item.points[-1])
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(_stroke_pen(item))
        painter.drawRect(QRectF(x, y, w, h))

    def _paint_ellipse(self, painter: QPainter, item: Annotation) -> None:
        x, y, w, h = normalize_rect(item.points[0], item.points[-1])
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(_stroke_pen(item))
        painter.drawEllipse(QRectF(x, y, w, h))

    def _paint_arrow(self, painter: QPainter, item: Annotation) -> None:
        tail = item.points[0]
        tip = item.points[-1]
        length = math.hypot(tip[0] - tail[0], tip[1] - tail[1])
        # A head that is proportional to the shaft reads well at any size,
        # but must never grow past the shaft or it becomes the whole arrow.
        size = min(max(item.width * 3.5, length * 0.22), length * 0.6 or 1.0)

        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(_stroke_pen(item))
        painter.drawLine(QPointF(*tail), QPointF(*tip))

        barbs = arrow_head(tail, tip, size)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(item.color))
        painter.drawPolygon(
            QPolygonF([QPointF(*tip), QPointF(*barbs[0]), QPointF(*barbs[1])])
        )

    def _paint_stroke(self, painter: QPainter, item: Annotation) -> None:
        if len(item.points) < 2:
            return
        color = QColor(item.color)
        if item.tool is Tool.HIGHLIGHT:
            # The highlighter is a fat translucent mark: solid, it would
            # hide the very text it is meant to point at.
            color.setAlpha(max(0, min(255, int(self._cfg["highlight_alpha"]))))
        pen = QPen(color, max(1.0, item.width))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        polyline = [QPointF(x, y) for x, y in item.points]
        painter.drawPolyline(QPolygonF(polyline))

    def _paint_mosaic(self, painter: QPainter, item: Annotation) -> None:
        if len(item.points) < 2:
            return
        brush = max(1.0, float(item.width or self._cfg["mosaic_brush"]))
        path = QPainterPath(QPointF(*item.points[0]))
        for x, y in item.points[1:]:
            path.lineTo(QPointF(x, y))
        stroker = QPainterPathStroker()
        stroker.setWidth(brush)
        stroker.setCapStyle(Qt.PenCapStyle.RoundCap)
        stroker.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        region = stroker.createStroke(path)

        painter.save()
        painter.setClipPath(region)
        # Blocky, not smooth: the pixelation has to survive the draw.
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        painter.drawPixmap(QPointF(0.0, 0.0), self._mosaic_pixmap())
        painter.restore()

    def _paint_text(self, painter: QPainter, item: Annotation) -> None:
        # Text is positioned by its centre and may be rotated, so the box is
        # built in a local frame and the painter moved into it.
        font = QFont()
        font.setPixelSize(max(1, int(item.font_px)))
        width, height = text_box_size(item)

        painter.save()
        painter.translate(item.points[0][0], item.points[0][1])
        painter.rotate(item.rotation)
        painter.setFont(font)
        painter.setPen(QColor(item.color))
        painter.drawText(
            QRectF(-width / 2.0, -height / 2.0, width, height),
            Qt.AlignmentFlag.AlignCenter,
            item.text,
        )
        painter.restore()

    def _paint_number(self, painter: QPainter, item: Annotation) -> None:
        radius = max(1.0, float(self._cfg["number_diameter_px"]) / 2.0)
        centre = QPointF(*item.points[0])
        painter.setPen(Qt.PenStyle.NoPen)
        # The badge colour is per-item so the palette can restyle one.
        painter.setBrush(QColor(item.color or self._cfg["number_color"]))
        painter.drawEllipse(centre, radius, radius)

        font = QFont()
        font.setPixelSize(max(1, int(self._cfg["number_font_px"])))
        painter.setFont(font)
        painter.setPen(QColor(self._cfg["number_text_color"]))
        box = QRectF(
            centre.x() - radius, centre.y() - radius, radius * 2.0, radius * 2.0
        )
        painter.drawText(box, Qt.AlignmentFlag.AlignCenter, str(item.number))

    # -- mosaic source ----------------------------------------------------

    def _mosaic_pixmap(self) -> QPixmap:
        """The whole picture pixelated, built once and reused."""
        if self._mosaic is None:
            block = max(2, int(self._cfg["mosaic_block"]))
            width = max(1, self._base.width() // block)
            height = max(1, self._base.height() // block)
            small = self._base.toImage().scaled(
                width,
                height,
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self._mosaic = QPixmap.fromImage(
                small.scaled(
                    self._base.width(),
                    self._base.height(),
                    Qt.AspectRatioMode.IgnoreAspectRatio,
                    Qt.TransformationMode.FastTransformation,
                )
            )
        return self._mosaic


def _stroke_pen(item: Annotation) -> QPen:
    pen = QPen(QColor(item.color), max(1.0, item.width))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return pen
