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
    grip: int
    close_diameter: int
    close_hit_radius: float


def _scaled(base_px: int, scale: float) -> int:
    """Scale a base pixel value, rounding up and never dropping below 1."""
    return max(1, math.ceil(base_px * scale))


def compute_metrics(
    scale: float,
    width: int,
    height: int,
    *,
    shadow_padding: int,
    grip_px: int,
    close_diameter_px: int,
    close_hit_radius_factor: float = 1.5,
) -> Metrics:
    """Return element sizes for a window of `width` x `height` physical pixels.

    `scale` is the system UI scale (1.0 == 96 DPI).
    `close_hit_radius_factor` is how much larger the clickable radius is
    than the drawn radius; a hit area smaller than the visual button would
    make edge pixels unclickable.
    """
    short_side = max(0, min(width, height))

    grip = _scaled(grip_px, scale)
    # Layer 2: keep the four corner grips from overlapping each other.
    grip = max(1, min(grip, short_side // 3)) if short_side else grip

    close_diameter = _scaled(close_diameter_px, scale)
    # Layer 2: keep the button from swallowing a very small window.
    if short_side:
        close_diameter = max(1, min(close_diameter, int(short_side * 0.3)))

    return Metrics(
        padding=_scaled(shadow_padding, scale),
        grip=grip,
        close_diameter=close_diameter,
        close_hit_radius=(close_diameter / 2.0) * max(1.0, close_hit_radius_factor),
    )
