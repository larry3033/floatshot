"""Compute DPI-scaled UI element sizes for a window of a given size.

Pure functions -- no Qt import -- so the clamping behaviour at extreme
window sizes can be unit tested rather than eyeballed on screen.

Three-layer strategy (see spec section 2.2):
  1. Base pixel size x DPI scale, rounded up. Keeps the feel identical
     across 100% / 125% / 150% displays.
  2. Percentage clamp. Stops corner grips from overlapping on tiny
     windows and stops the close button from eating the whole picture.
  3. Hit areas stay larger than visual sizes.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Metrics:
    """DPI-adjusted element sizes for one window size."""

    padding: int
    grip_x: int
    grip_y: int
    close_diameter: int
    close_hit_radius: float


def _scaled(base_px: int, scale: float) -> int:
    """Scale a base pixel value, rounding up and never dropping below 1."""
    return max(1, math.ceil(base_px * scale))


def _grip(image_side: int, ratio: float) -> int:
    """How far the resize band reaches in from the picture's edge, in pixels.

    `ratio` is a fraction of the picture -- not of the window, and not of
    the shadow padding. The user grabs the *picture's* edge, so that is what
    the band has to be measured against.
    """
    if image_side <= 0:
        return 1
    return max(1, math.ceil(image_side * ratio))


def compute_metrics(
    scale: float,
    image_width: int,
    image_height: int,
    *,
    shadow_padding: int,
    grip_ratio: float,
    close_diameter_px: int,
    close_hit_radius_factor: float = 1.5,
) -> Metrics:
    """Return element sizes for a window showing an image_width x image_height picture.

    Note this takes the PICTURE size, not the window size. The window is the
    picture plus `2 * padding` on each axis, and this function derives that
    itself, because the resize bands have to be anchored to the picture's
    edges rather than the window's.

    `scale` is the system UI scale (1.0 == 96 DPI); `grip_ratio` is not
    scaled by it, since it multiplies a size that is already in physical
    pixels. `close_hit_radius_factor` is how much larger the clickable
    radius is than the drawn radius.
    """
    pad = _scaled(shadow_padding, scale)
    win_w = max(1, image_width) + 2 * pad
    win_h = max(1, image_height) + 2 * pad

    # The band spans the shadow padding AND `grip_x` pixels of picture: the
    # padding is the visual edge of the window, so it must always be
    # grabbable, and a band that stopped at the picture's edge would be
    # unreachable on a small window -- the picture's edge sits `pad` pixels
    # in from the window's, so a band narrower than `pad` misses it entirely.
    band_x = pad + _grip(image_width, grip_ratio)
    band_y = pad + _grip(image_height, grip_ratio)
    # Keep opposite bands from meeting in the middle, but never shrink one
    # below the padding itself.
    band_x = min(band_x, max(pad + 1, win_w // 3))
    band_y = min(band_y, max(pad + 1, win_h // 3))

    close_diameter = _scaled(close_diameter_px, scale)
    # Keep the button from swallowing a very small picture.
    short_side = min(win_w, win_h)
    close_diameter = max(1, min(close_diameter, int(short_side * 0.3)))

    return Metrics(
        padding=pad,
        grip_x=band_x,
        grip_y=band_y,
        close_diameter=close_diameter,
        close_hit_radius=(close_diameter / 2.0) * max(1.0, close_hit_radius_factor),
    )
