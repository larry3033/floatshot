import pytest

from floatshot.metrics import Metrics, compute_metrics


def _m(scale=1.0, w=400, h=300, pad=18, ratio=0.10, close=16, hit=1.5):
    """Metrics for a `w` x `h` PICTURE (not window) with `pad` shadow padding."""
    return compute_metrics(
        scale=scale, image_width=w, image_height=h,
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


# ---------- The resize bands ----------
#
# A band is measured in from the WINDOW's edge and covers the shadow padding
# plus `ratio` of the picture. Measured from the picture's edge instead, it
# would leave the picture's own edge -- the pixels the user actually grabs --
# outside the band on any small window.

def test_band_is_padding_plus_a_fraction_of_the_picture():
    m = _m(ratio=0.10)
    assert m.grip_x == 18 + 40      # padding + 400 * 0.10
    assert m.grip_y == 18 + 30      # padding + 300 * 0.10


def test_band_axes_use_their_own_dimension():
    # A wide, short picture gets wide side bands and narrow top/bottom ones.
    m = _m(w=1000, h=200, ratio=0.10)
    assert m.grip_x == 18 + 100
    assert m.grip_y == 18 + 20
    assert m.grip_x > m.grip_y


def test_picture_portion_does_not_scale_with_dpi():
    # The padding does scale, so the band as a whole does too -- but the part
    # derived from the ratio must not, or the band would double on a 150%
    # display. This is the property a fixed pixel count cannot have.
    base = _m(scale=1.0)
    hidpi = _m(scale=1.5)
    assert (base.grip_x - base.padding) == (hidpi.grip_x - hidpi.padding)
    assert (base.grip_y - base.padding) == (hidpi.grip_y - hidpi.padding)


def test_band_rounds_up():
    # 337 * 0.10 = 33.7 -> 34, not 33: a band is better slightly too wide.
    assert _m(w=337, h=337, ratio=0.10).grip_x == 18 + 34


def test_band_grows_with_the_picture():
    # A bigger picture is easier to grab.
    small = _m(w=200, h=200, ratio=0.10)
    large = _m(w=1200, h=800, ratio=0.10)
    assert large.grip_x > small.grip_x
    assert large.grip_y > small.grip_y


# ---------- Regression: the picture's edge must stay grabbable ----------
#
# Before this was anchored to the window's edge, any picture narrower than
# about 144px had its own edge fall outside the band: dragging the edge the
# user can see was treated as a plain window move, so the window could not
# be resized up again.

@pytest.mark.parametrize("w,h", [(400, 300), (200, 150), (144, 108), (100, 80), (44, 24)])
def test_picture_edge_is_inside_the_band(w, h):
    m = _m(w=w, h=h, ratio=0.10)
    assert m.padding < m.grip_x, (
        f"picture left edge at x={m.padding} falls outside the band [0,{m.grip_x})"
    )
    assert m.padding < m.grip_y, (
        f"picture top edge at y={m.padding} falls outside the band [0,{m.grip_y})"
    )


def test_picture_edge_grabbable_at_the_minimum_window():
    # The smallest window the app allows is 80x60, i.e. a 44x24 picture at
    # the default 18px padding -- the worst case for this bug.
    m = _m(w=44, h=24, pad=18, ratio=0.10)
    assert m.padding < m.grip_x
    assert m.padding < m.grip_y


# ---------- Layer 2: percentage clamps ----------

def test_band_clamped_on_small_window():
    # A 60x60 picture gives a 96x96 window; 96 // 3 = 32 pulls the band back.
    m = _m(w=60, h=60, ratio=0.5)
    assert m.grip_x == 32
    assert m.grip_y == 32


def test_band_clamp_is_per_axis():
    m = _m(w=90, h=400, ratio=0.5)
    assert m.grip_x == 42       # 126 // 3
    assert m.grip_y == 145      # 436 // 3


def test_band_leaves_room_to_drag():
    # Both bands together must never eat the window, or there would be
    # nowhere left to press to move it.
    for side in (60, 200, 1000):
        m = _m(w=side, h=side, ratio=1.0)
        assert m.grip_x * 2 < side + 2 * m.padding


def test_close_button_clamped_on_a_small_window():
    m = _m(w=60, h=60, ratio=0.1, close=100)
    assert m.close_diameter == 28     # int(96 * 0.3)


def test_close_button_not_clamped_on_a_normal_window():
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

def test_degenerate_picture_still_returns_positive_sizes():
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
