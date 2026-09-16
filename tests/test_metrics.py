import pytest

from floatshot.metrics import Metrics, compute_metrics


def _m(scale=1.0, w=436, h=336, pad=18, ratio=0.10, close=16, hit=1.5):
    """Metrics for a 436x336 window: a 400x300 picture plus 18px of padding."""
    return compute_metrics(
        scale=scale, width=w, height=h,
        shadow_padding=pad, grip_ratio=ratio,
        close_diameter_px=close, close_hit_radius_factor=hit,
    )


# ---------- Layer 1: fixed sizes that do scale with DPI ----------

def test_padding_scales_with_dpi():
    assert _m(scale=1.0).padding == 18
    assert _m(scale=1.25).padding == 23    # 22.5, rounded up
    assert _m(scale=1.5).padding == 27


def test_close_diameter_scales_with_dpi():
    assert _m(scale=1.0).close_diameter == 16
    assert _m(scale=1.25).close_diameter == 20
    assert _m(scale=1.5).close_diameter == 24


# ---------- The resize bands: a fraction of each axis ----------

def test_grip_is_a_fraction_of_each_axis():
    # 436 * 0.10 = 43.6 -> 44;  336 * 0.10 = 33.6 -> 34
    m = _m(ratio=0.10)
    assert m.grip_x == 44
    assert m.grip_y == 34


def test_grip_axes_use_their_own_dimension():
    # A wide, short window gets wide side bands and narrow top/bottom ones.
    m = _m(w=1000, h=200, ratio=0.10)
    assert m.grip_x == 100
    assert m.grip_y == 20
    assert m.grip_x > m.grip_y


def test_grip_does_not_scale_with_dpi():
    # The ratio multiplies a window size that is ALREADY in physical pixels,
    # so applying the DPI scale again would double the bands on a 150%
    # display. This is the property that makes a ratio better than a pixel
    # count here.
    base = _m(scale=1.0)
    hidpi = _m(scale=1.5)
    assert hidpi.grip_x == base.grip_x
    assert hidpi.grip_y == base.grip_y


def test_grip_rounds_up():
    # 337 * 0.10 = 33.7 -> 34, not 33: a band is better slightly too wide.
    assert _m(w=337, h=337, ratio=0.10).grip_x == 34


def test_grip_grows_with_the_window():
    # The point of this change: a bigger picture is easier to grab.
    small = _m(w=200, h=200, ratio=0.10)
    large = _m(w=1200, h=800, ratio=0.10)
    assert large.grip_x > small.grip_x
    assert large.grip_y > small.grip_y


# ---------- Layer 2: percentage clamps ----------

def test_grip_clamped_on_small_window():
    # 60 // 3 = 20; a 0.5 ratio would give 30 and is pulled back to 20.
    m = _m(w=60, h=60, ratio=0.5)
    assert m.grip_x == 20
    assert m.grip_y == 20


def test_grip_clamp_is_per_axis():
    # 90 // 3 = 30 and 400 // 3 = 133: each axis is clamped on its own, so a
    # wide-window clamp cannot shrink the other axis's bands.
    m = _m(w=90, h=400, ratio=0.5)
    assert m.grip_x == 30
    assert m.grip_y == 133


def test_grip_leaves_room_to_drag():
    # Both bands together must never eat the window, or there would be
    # nowhere left to press to move it.
    for side in (60, 200, 1000):
        m = _m(w=side, h=side, ratio=1.0)
        assert m.grip_x * 2 < side


def test_close_button_clamped_on_tiny_window():
    m = _m(w=60, h=60, ratio=0.1, close=100)
    assert m.close_diameter == 18          # int(60 * 0.3)


def test_close_button_not_clamped_on_normal_window():
    assert _m(scale=1.0).close_diameter == 16


# ---------- Layer 3: hit areas larger than the drawn element ----------

def test_hit_radius_exceeds_visual_radius():
    for scale in (1.0, 1.25, 1.5, 2.0):
        m = _m(scale=scale)
        assert m.close_hit_radius > m.close_diameter / 2


def test_hit_radius_scales_with_visual_size():
    assert _m(scale=1.0).close_hit_radius == pytest.approx(12.0)
    assert _m(scale=1.5).close_hit_radius == pytest.approx(18.0)


# ---------- Degenerate input ----------

def test_degenerate_window_still_returns_positive_sizes():
    m = _m(w=0, h=0)
    assert m.grip_x >= 1
    assert m.grip_y >= 1
    assert m.close_diameter >= 1


def test_result_is_frozen():
    m = _m()
    with pytest.raises(Exception):
        m.grip_x = 99


def test_returns_metrics_instance():
    assert isinstance(_m(), Metrics)
