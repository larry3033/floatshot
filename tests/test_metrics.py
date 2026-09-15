import pytest

from floatshot.metrics import Metrics, compute_metrics


def _m(scale=1.0, w=400, h=300, pad=18, grip=6, close=16, hit=1.5):
    return compute_metrics(
        scale=scale, width=w, height=h,
        shadow_padding=pad, grip_px=grip,
        close_diameter_px=close, close_hit_radius_factor=hit,
    )


# ---------- 主规则：固定基准 × DPI ----------

def test_100_percent_scale_is_identity():
    m = _m(scale=1.0)
    assert m.grip == 6
    assert m.close_diameter == 16
    assert m.padding == 18


def test_125_percent_scale_rounds_up():
    # 6 * 1.25 = 7.5 -> ceil -> 8；判定区宁大勿小
    m = _m(scale=1.25)
    assert m.grip == 8
    assert m.close_diameter == 20   # 16 * 1.25 = 20 恰好整数


def test_150_percent_scale():
    m = _m(scale=1.5)
    assert m.grip == 9              # 6 * 1.5 = 9
    assert m.close_diameter == 24   # 16 * 1.5 = 24
    assert m.padding == 27          # 18 * 1.5 = 27


def test_hit_radius_exceeds_visual_radius():
    # 判定区必须大于视觉尺寸，否则边缘像素点不中
    for scale in (1.0, 1.25, 1.5, 2.0):
        m = _m(scale=scale)
        assert m.close_hit_radius > m.close_diameter / 2


def test_hit_radius_scales_with_visual_size():
    # 16px 按钮 -> 视觉半径 8，判定半径 8 * 1.5 = 12
    assert _m(scale=1.0).close_hit_radius == pytest.approx(12.0)
    # 24px 按钮 -> 视觉半径 12，判定半径 18
    assert _m(scale=1.5).close_hit_radius == pytest.approx(18.0)


# ---------- 兜底：百分比 clamp ----------

def test_grip_clamped_on_tiny_window():
    # min(400,300)/3 = 100，正常不触发；窗口缩到 60x60 时 grip 应被压到 20
    m = _m(w=60, h=60, grip=100)
    assert m.grip == 20             # 60/3


def test_grip_never_exceeds_one_third_of_short_side():
    m = _m(w=90, h=400, scale=2.0, grip=50)
    assert m.grip <= 90 // 3


def test_close_button_clamped_on_tiny_window():
    # min(60,60)*0.3 = 18
    m = _m(w=60, h=60, scale=2.0, close=100)
    assert m.close_diameter == 18


def test_clamp_does_not_trigger_on_normal_window():
    m = _m(w=400, h=300, scale=1.0)
    assert m.grip == 6
    assert m.close_diameter == 16


# ---------- 边界 ----------

def test_degenerate_window_still_returns_positive_grip():
    # 窗口尺寸为 0 或负数不应产生负判定区
    m = _m(w=0, h=0)
    assert m.grip >= 1
    assert m.close_diameter >= 1


def test_result_is_frozen():
    m = _m()
    with pytest.raises(Exception):
        m.grip = 99


def test_returns_metrics_instance():
    assert isinstance(_m(), Metrics)
