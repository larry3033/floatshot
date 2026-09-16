import pytest

from floatshot.geometry import (
    Edge,
    apply_resize,
    fit_aspect_corner,
    fit_aspect_height,
    fit_aspect_width,
    hit_test,
)


# ---------- hit_test ----------

W, H, G = 400, 300, 6


def test_center_is_not_an_edge():
    assert hit_test(200, 150, W, H, G, G) == Edge.NONE


def test_left_edge():
    assert hit_test(2, 150, W, H, G, G) == Edge.LEFT


def test_right_edge():
    assert hit_test(W - 2, 150, W, H, G, G) == Edge.RIGHT


def test_top_edge():
    assert hit_test(200, 2, W, H, G, G) == Edge.TOP


def test_bottom_edge():
    assert hit_test(200, H - 2, W, H, G, G) == Edge.BOTTOM


def test_corners_are_combinations():
    assert hit_test(2, 2, W, H, G, G) == Edge.LEFT | Edge.TOP
    assert hit_test(W - 2, 2, W, H, G, G) == Edge.RIGHT | Edge.TOP
    assert hit_test(2, H - 2, W, H, G, G) == Edge.LEFT | Edge.BOTTOM
    assert hit_test(W - 2, H - 2, W, H, G, G) == Edge.RIGHT | Edge.BOTTOM


def test_grip_boundary_is_inclusive_at_zero():
    assert hit_test(0, 150, W, H, G, G) == Edge.LEFT


def test_grip_boundary_is_exclusive_at_grip():
    # 恰好等于 grip 时已经在内容区内，不应命中
    assert hit_test(G, 150, W, H, G, G) == Edge.NONE


def test_just_inside_grip_hits():
    assert hit_test(G - 1, 150, W, H, G, G) == Edge.LEFT


def test_oversized_grip_is_clamped_internally():
    # 防御性：调用方传了未经 clamp 的 grip，也不能让左右判定区重叠
    # 90x90 的窗口，grip=100 被内部压到 30；点 (50,50) 落在中间安全区
    assert hit_test(50, 50, 90, 90, grip_x=100, grip_y=100) == Edge.NONE


def test_clamped_grip_still_matches_its_boundary():
    # 承上：clamp 到 30 之后，29 仍应命中左边缘，30 应落回内容区
    assert hit_test(29, 50, 90, 90, grip_x=100, grip_y=100) == Edge.LEFT
    assert hit_test(30, 50, 90, 90, grip_x=100, grip_y=100) == Edge.NONE


def test_grip_axes_are_independent():
    # 判定带是按各自轴的尺寸比例算的，所以两条轴的宽度可以完全不同：
    # 这里 grip_x=130 远宽于 grip_y=1。
    assert hit_test(10, 150, W, H, 130, 1) == Edge.LEFT
    assert hit_test(200, 150, W, H, 130, 1) == Edge.NONE
    assert hit_test(200, 0, W, H, 130, 1) == Edge.TOP
    assert hit_test(200, 1, W, H, 130, 1) == Edge.NONE


def test_wide_grip_x_does_not_shrink_grip_y():
    # clamp 必须逐轴独立：一个超大的 grip_x 不该把纵向判定带也压掉
    edge = hit_test(1, 1, 300, 300, grip_x=10_000, grip_y=100)
    assert Edge.LEFT in edge
    assert Edge.TOP in edge


def test_negative_coordinates_are_outside():
    assert hit_test(-5, 150, W, H, G, G) == Edge.NONE


def test_point_beyond_window_is_outside():
    assert hit_test(W + 5, 150, W, H, G, G) == Edge.NONE


# ---------- 比例约束 ----------

def test_fit_aspect_width_keeps_ratio():
    assert fit_aspect_width(200, 100, 400) == (400, 200)


def test_fit_aspect_height_keeps_ratio():
    assert fit_aspect_height(200, 100, 300) == (600, 300)


def test_fit_aspect_rounds_to_int():
    w, h = fit_aspect_width(300, 200, 100)      # 100 * 200/300 = 66.67
    assert isinstance(w, int) and isinstance(h, int)
    assert h in (66, 67)


def test_fit_aspect_corner_picks_dominant_axis():
    # 宽变化比例更大 -> 以宽为准
    assert fit_aspect_corner(200, 100, 600, 110) == (600, 300)
    # 高变化比例更大 -> 以高为准
    assert fit_aspect_corner(200, 100, 210, 500) == (1000, 500)


def test_fit_aspect_never_returns_zero():
    w, h = fit_aspect_width(1000, 1000, 1)
    assert w >= 1 and h >= 1


# ---------- apply_resize ----------

START = (100, 100, 400, 300)   # x, y, w, h


def test_resize_right_edge_grows_width_only():
    assert apply_resize(START, Edge.RIGHT, dx=50, dy=0, min_w=80, min_h=60) == (100, 100, 450, 300)


def test_resize_bottom_edge_grows_height_only():
    assert apply_resize(START, Edge.BOTTOM, dx=0, dy=40, min_w=80, min_h=60) == (100, 100, 400, 340)


def test_resize_left_edge_moves_origin():
    # 拖左边：原点左移、宽度增加，右边界不动
    assert apply_resize(START, Edge.LEFT, dx=-50, dy=0, min_w=80, min_h=60) == (50, 100, 450, 300)


def test_resize_top_edge_moves_origin():
    assert apply_resize(START, Edge.TOP, dx=0, dy=-30, min_w=80, min_h=60) == (100, 70, 400, 330)


def test_resize_bottom_right_corner():
    assert apply_resize(START, Edge.RIGHT | Edge.BOTTOM, dx=20, dy=30, min_w=80, min_h=60) == (100, 100, 420, 330)


def test_resize_top_left_corner():
    assert apply_resize(START, Edge.LEFT | Edge.TOP, dx=-20, dy=-30, min_w=80, min_h=60) == (80, 70, 420, 330)


def test_min_width_is_enforced():
    _, _, w, _ = apply_resize(START, Edge.RIGHT, dx=-1000, dy=0, min_w=80, min_h=60)
    assert w == 80


def test_min_height_is_enforced():
    _, _, _, h = apply_resize(START, Edge.BOTTOM, dx=0, dy=-1000, min_w=80, min_h=60)
    assert h == 60


def test_min_width_keeps_right_edge_anchored_when_dragging_left():
    # 拖左边到极限：右边界必须保持不动，不能把窗口推走
    x, _, w, _ = apply_resize(START, Edge.LEFT, dx=1000, dy=0, min_w=80, min_h=60)
    assert x + w == START[0] + START[2]


def test_min_height_keeps_bottom_edge_anchored_when_dragging_top():
    _, y, _, h = apply_resize(START, Edge.TOP, dx=0, dy=1000, min_w=80, min_h=60)
    assert y + h == START[1] + START[3]


def test_edge_none_returns_start_unchanged():
    assert apply_resize(START, Edge.NONE, dx=10, dy=10, min_w=80, min_h=60) == START
