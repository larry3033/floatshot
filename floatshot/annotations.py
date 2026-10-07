"""Annotation model and drawing geometry for the floating-window editor.

Pure Python -- no Qt import -- so undo/redo and the geometric parts (arrow
heads, brush sampling, widget-to-image mapping) are unit testable without a
display. The actual painting lives in annotation_paint.py.

An annotation is stored in *image* coordinates, never window coordinates:
the window can be moved, resized and DPI-scaled after a stroke is drawn, and
a stroke has to stay pinned to the pixels it was drawn on.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum


class Tool(str, Enum):
    """The annotation tools offered by the toolbar."""

    RECT = "rect"
    ELLIPSE = "ellipse"
    ARROW = "arrow"
    PEN = "pen"
    TEXT = "text"
    MOSAIC = "mosaic"
    NUMBER = "number"
    HIGHLIGHT = "highlight"


@dataclass
class Annotation:
    """One committed drawing step.

    `points` is the gesture's path in image coordinates: two points for the
    two-corner tools (rect/ellipse/arrow), a polyline for the freehand tools
    (pen/mosaic/highlight), one point for the placed tools (text/number).
    """

    tool: Tool
    points: list[tuple[float, float]] = field(default_factory=list)
    color: str = "#FF3B30"
    width: float = 2.0
    text: str = ""
    number: int = 0
    font_px: int = 16
    rotation: float = 0.0

    def bounds(self) -> tuple[float, float, float, float]:
        """(left, top, right, bottom) of the raw points; empty is all zeros."""
        xs = [p[0] for p in self.points]
        ys = [p[1] for p in self.points]
        if not xs:
            return (0.0, 0.0, 0.0, 0.0)
        return (min(xs), min(ys), max(xs), max(ys))


class Document:
    """The annotation list with an undo/redo cursor.

    Linear history: committing a new item drops the redo branch, which is
    what a user expects from a pencil-and-undo UI.
    """

    def __init__(self) -> None:
        self._items: list[Annotation] = []
        self._redo: list[Annotation] = []

    @property
    def items(self) -> list[Annotation]:
        """A copy of the committed items, in paint order."""
        return list(self._items)

    @property
    def can_undo(self) -> bool:
        return bool(self._items)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    def add(self, item: Annotation) -> None:
        self._items.append(item)
        self._redo.clear()

    def undo(self) -> None:
        if self._items:
            self._redo.append(self._items.pop())

    def redo(self) -> None:
        if self._redo:
            self._items.append(self._redo.pop())

    def next_number(self) -> int:
        """The badge number a new marker should get.

        Derived from what is currently visible rather than from a counter,
        so undoing a marker frees its number for reuse instead of leaving a
        permanent gap.
        """
        used = [a.number for a in self._items if a.tool is Tool.NUMBER]
        return 1 + max(used, default=0)


def normalize_rect(
    a: tuple[float, float], b: tuple[float, float]
) -> tuple[float, float, float, float]:
    """(x, y, w, h) of the rectangle spanned by two corner points.

    Handles drags in any direction; the result is never negative.
    """
    x1, y1 = a
    x2, y2 = b
    return (min(x1, x2), min(y1, y2), abs(x2 - x1), abs(y2 - y1))


def map_to_image(
    px: float,
    py: float,
    rect: tuple[float, float, float, float],
    image_w: int,
    image_h: int,
) -> tuple[float, float, bool]:
    """Map a widget point to image coordinates.

    `rect` is the picture's rect inside the widget (x, y, w, h). The third
    return value says whether the point actually landed on the picture:
    outside it, the clamped coordinates are still returned so a drag that
    leaves the picture keeps drawing to the edge.
    """
    rx, ry, rw, rh = rect
    if rw <= 0 or rh <= 0 or image_w <= 0 or image_h <= 0:
        return (0.0, 0.0, False)
    ix = (px - rx) * image_w / rw
    iy = (py - ry) * image_h / rh
    inside = 0.0 <= ix <= image_w and 0.0 <= iy <= image_h
    ix = min(max(ix, 0.0), float(image_w))
    iy = min(max(iy, 0.0), float(image_h))
    return (ix, iy, inside)


def arrow_head(
    tail: tuple[float, float],
    tip: tuple[float, float],
    size: float,
    half_angle_deg: float = 26.0,
) -> list[tuple[float, float]]:
    """The two barb points of an arrow head whose point is at `tip`."""
    tx, ty = tail
    hx, hy = tip
    angle = math.atan2(hy - ty, hx - tx)
    back = angle + math.pi
    spread = math.radians(half_angle_deg)
    return [
        (hx + size * math.cos(back - spread), hy + size * math.sin(back - spread)),
        (hx + size * math.cos(back + spread), hy + size * math.sin(back + spread)),
    ]


def rotate_point(
    px: float, py: float, cx: float, cy: float, degrees: float
) -> tuple[float, float]:
    """Rotate a point about (cx, cy) by `degrees` (positive is clockwise)."""
    radians = math.radians(degrees)
    cos_a = math.cos(radians)
    sin_a = math.sin(radians)
    dx = px - cx
    dy = py - cy
    return (cx + dx * cos_a - dy * sin_a, cy + dx * sin_a + dy * cos_a)


def corner_points(
    cx: float, cy: float, width: float, height: float
) -> list[tuple[float, float]]:
    """The four corners of an upright box centred on (cx, cy)."""
    half_w = width / 2.0
    half_h = height / 2.0
    return [
        (cx - half_w, cy - half_h),
        (cx + half_w, cy - half_h),
        (cx + half_w, cy + half_h),
        (cx - half_w, cy + half_h),
    ]


def point_in_rotated_rect(
    px: float, py: float, cx: float, cy: float,
    width: float, height: float, degrees: float,
) -> bool:
    """Whether a point is inside a box rotated about its centre.

    Works by rotating the point back into the box's own frame, which turns
    the test into a plain axis-aligned one.
    """
    local_x, local_y = rotate_point(px, py, cx, cy, -degrees)
    return abs(local_x - cx) <= width / 2.0 and abs(local_y - cy) <= height / 2.0


def angle_deg(
    cx: float, cy: float, px: float, py: float
) -> float:
    """Angle of the ray from (cx, cy) to (px, py), in degrees."""
    return math.degrees(math.atan2(py - cy, px - cx))
