"""Window edge hit-testing and resize math.

Pure functions -- no Qt import -- so the fiddly boundary behaviour can be
unit tested instead of hunted down with a mouse.
"""

from __future__ import annotations

from enum import IntFlag


class Edge(IntFlag):
    """Which window edges a point is touching. Corners are combinations."""

    NONE = 0
    LEFT = 1
    RIGHT = 2
    TOP = 4
    BOTTOM = 8


def hit_test(
    x: float, y: float, width: int, height: int, grip_x: int, grip_y: int
) -> Edge:
    """Return the edges touched by the client-area point (x, y).

    `grip_x` is the thickness of the left/right resize bands and `grip_y`
    that of the top/bottom bands -- two values rather than one because the
    bands are a fraction of each axis, so a wide window gets wide side
    bands and a tall window gets tall ones.

    Both are clamped internally so an oversized value can never make
    opposite bands meet and swallow the whole window. The clamp is per
    axis: a huge `grip_x` must not shrink the vertical bands.
    """
    if width <= 0 or height <= 0:
        return Edge.NONE

    grip_x = max(1, min(grip_x, max(1, width // 3)))
    grip_y = max(1, min(grip_y, max(1, height // 3)))

    if not (0 <= x < width and 0 <= y < height):
        return Edge.NONE

    edge = Edge.NONE
    if x < grip_x:
        edge |= Edge.LEFT
    elif x >= width - grip_x:
        edge |= Edge.RIGHT
    if y < grip_y:
        edge |= Edge.TOP
    elif y >= height - grip_y:
        edge |= Edge.BOTTOM
    return edge


def fit_aspect_width(orig_w: int, orig_h: int, target_w: int) -> tuple[int, int]:
    """Size the image to `target_w` wide, keeping its aspect ratio."""
    if orig_w <= 0 or orig_h <= 0:
        return max(1, target_w), max(1, target_w)
    w = max(1, int(target_w))
    h = max(1, round(w * orig_h / orig_w))
    return w, h


def fit_aspect_height(orig_w: int, orig_h: int, target_h: int) -> tuple[int, int]:
    """Size the image to `target_h` tall, keeping its aspect ratio."""
    if orig_w <= 0 or orig_h <= 0:
        return max(1, target_h), max(1, target_h)
    h = max(1, int(target_h))
    w = max(1, round(h * orig_w / orig_h))
    return w, h


def fit_aspect_corner(
    orig_w: int, orig_h: int, cand_w: int, cand_h: int
) -> tuple[int, int]:
    """Lock a corner drag to the image aspect ratio.

    Whichever axis changed proportionally more wins, so dragging a corner
    does not jitter between the two constraints.
    """
    if orig_w <= 0 or orig_h <= 0:
        return max(1, cand_w), max(1, cand_h)
    ratio_w = max(1, cand_w) / orig_w
    ratio_h = max(1, cand_h) / orig_h
    if ratio_w >= ratio_h:
        return fit_aspect_width(orig_w, orig_h, cand_w)
    return fit_aspect_height(orig_w, orig_h, cand_h)


def apply_resize(
    start: tuple[int, int, int, int],
    edge: Edge,
    dx: int,
    dy: int,
    *,
    min_w: int,
    min_h: int,
) -> tuple[int, int, int, int]:
    """Apply a resize drag to `start` = (x, y, w, h).

    Edges not present in `edge` are immovable: dragging the left edge
    changes x and w but leaves the right edge exactly where it was, which
    is what stops the window from sliding when it hits the minimum size.
    """
    x, y, w, h = start
    if edge == Edge.NONE:
        return start

    if Edge.LEFT in edge:
        new_w = max(min_w, w - dx)
        x = x + (w - new_w)
        w = new_w
    elif Edge.RIGHT in edge:
        w = max(min_w, w + dx)

    if Edge.TOP in edge:
        new_h = max(min_h, h - dy)
        y = y + (h - new_h)
        h = new_h
    elif Edge.BOTTOM in edge:
        h = max(min_h, h + dy)

    return x, y, w, h
