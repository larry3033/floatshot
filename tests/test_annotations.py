import math

import pytest

from floatshot.annotations import (
    Annotation,
    Document,
    Tool,
    angle_deg,
    arrow_head,
    corner_points,
    map_to_image,
    normalize_rect,
    point_in_rotated_rect,
    rotate_point,
)


# ---------- Document: undo / redo ----------

def _item(tool=Tool.RECT, **kw):
    return Annotation(tool=tool, points=[(0, 0), (10, 10)], **kw)


def test_new_document_has_nothing_to_undo_or_redo():
    doc = Document()
    assert doc.items == []
    assert not doc.can_undo
    assert not doc.can_redo


def test_add_then_undo_then_redo_round_trips():
    doc = Document()
    a = _item()
    doc.add(a)

    assert doc.items == [a]
    assert doc.can_undo and not doc.can_redo

    doc.undo()
    assert doc.items == []
    assert not doc.can_undo and doc.can_redo

    doc.redo()
    assert doc.items == [a]
    assert doc.can_undo and not doc.can_redo


def test_undo_redo_are_noops_at_the_ends():
    doc = Document()
    doc.undo()          # nothing to undo
    doc.redo()          # nothing to redo
    assert doc.items == []


def test_adding_after_undo_drops_the_redo_branch():
    doc = Document()
    first, second = _item(), _item()
    doc.add(first)
    doc.add(second)
    doc.undo()
    doc.add(_item())

    assert not doc.can_redo
    assert len(doc.items) == 2


def test_items_property_is_a_copy():
    doc = Document()
    doc.add(_item())
    doc.items.clear()
    assert len(doc.items) == 1


# ---------- numbering ----------

def test_numbering_starts_at_one():
    assert Document().next_number() == 1


def test_numbering_follows_the_largest_visible_marker():
    doc = Document()
    doc.add(_item(Tool.NUMBER, number=1))
    doc.add(_item(Tool.NUMBER, number=2))
    assert doc.next_number() == 3


def test_undoing_a_marker_frees_its_number():
    doc = Document()
    doc.add(_item(Tool.NUMBER, number=1))
    doc.add(_item(Tool.NUMBER, number=2))
    doc.undo()
    assert doc.next_number() == 2


def test_shapes_do_not_consume_numbers():
    doc = Document()
    doc.add(_item(Tool.RECT))
    assert doc.next_number() == 1


# ---------- normalize_rect ----------

@pytest.mark.parametrize("a,b,expected", [
    ((0, 0), (10, 5), (0, 0, 10, 5)),
    ((10, 5), (0, 0), (0, 0, 10, 5)),      # dragged up-left
    ((5, 0), (0, 10), (0, 0, 5, 10)),      # dragged left only
    ((3, 3), (3, 3), (3, 3, 0, 0)),        # a click
])
def test_normalize_rect(a, b, expected):
    assert normalize_rect(a, b) == expected


# ---------- map_to_image ----------

def test_map_is_identity_when_rect_matches_the_image():
    x, y, inside = map_to_image(50, 30, (0, 0, 400, 300), 400, 300)
    assert (x, y) == (50, 30)
    assert inside


def test_map_scales_from_a_shrunk_display_rect():
    # A 400x300 picture shown inside a 200x150 rect: half scale.
    x, y, inside = map_to_image(100, 75, (10, 10, 200, 150), 400, 300)
    assert x == pytest.approx(180.0)   # (100-10) * 400/200
    assert y == pytest.approx(130.0)   # (75-10) * 300/150
    assert inside


def test_map_clamps_points_outside_the_picture():
    x, y, inside = map_to_image(1_000, -50, (0, 0, 100, 100), 200, 200)
    assert (x, y) == (200.0, 0.0)
    assert not inside


def test_map_reports_the_edge_as_inside():
    x, y, inside = map_to_image(100, 100, (0, 0, 100, 100), 200, 200)
    assert (x, y) == (200.0, 200.0)
    assert inside


def test_map_degenerate_rect_is_safe():
    assert map_to_image(5, 5, (0, 0, 0, 0), 100, 100) == (0.0, 0.0, False)


# ---------- arrow head ----------

def test_arrow_head_is_symmetric_about_the_shaft():
    tail, tip, size = (0.0, 0.0), (100.0, 0.0), 20.0
    left, right = arrow_head(tail, tip, size)
    assert left[1] == pytest.approx(-right[1])
    assert left[0] == pytest.approx(right[0])


def test_arrow_head_barbs_are_the_requested_distance_from_the_tip():
    for barb in arrow_head((0.0, 0.0), (100.0, 0.0), 20.0):
        assert math.hypot(barb[0] - 100.0, barb[1]) == pytest.approx(20.0)


def test_arrow_head_points_back_towards_the_tail():
    left, right = arrow_head((0.0, 0.0), (100.0, 0.0), 20.0)
    assert left[0] < 100.0 and right[0] < 100.0


# ---------- bounds ----------

def test_bounds_of_an_empty_annotation_are_zero():
    assert Annotation(tool=Tool.PEN).bounds() == (0.0, 0.0, 0.0, 0.0)


def test_bounds_cover_every_point():
    ann = Annotation(tool=Tool.PEN, points=[(5, 9), (-2, 3), (10, -1)])
    assert ann.bounds() == (-2.0, -1.0, 10.0, 9.0)


# ---------- rotation helpers ----------

def test_rotate_point_by_zero_is_identity():
    assert rotate_point(3.0, 4.0, 1.0, 1.0, 0.0) == pytest.approx((3.0, 4.0))


def test_rotate_point_quarter_turn_is_clockwise():
    # Positive degrees turn clockwise in screen coordinates (y grows down).
    x, y = rotate_point(2.0, 0.0, 0.0, 0.0, 90.0)
    assert (x, y) == pytest.approx((0.0, 2.0))


def test_rotate_point_preserves_distance_to_the_centre():
    x, y = rotate_point(7.0, 1.0, 3.0, 4.0, 123.0)
    assert math.hypot(x - 3.0, y - 4.0) == pytest.approx(
        math.hypot(7.0 - 3.0, 1.0 - 4.0)
    )


def test_corner_points_are_symmetric_about_the_centre():
    corners = corner_points(10.0, 20.0, 4.0, 8.0)
    assert corners == [(8.0, 16.0), (12.0, 16.0), (12.0, 24.0), (8.0, 24.0)]


def test_point_in_rotated_rect_is_a_plain_contains_when_upright():
    assert point_in_rotated_rect(10.0, 20.0, 10.0, 20.0, 8.0, 8.0, 0.0)
    assert not point_in_rotated_rect(20.0, 20.0, 10.0, 20.0, 8.0, 8.0, 0.0)


def test_point_in_rotated_rect_follows_the_rotation():
    # A 10x2 box turned 90 degrees becomes tall, so a point above the centre
    # is inside it only after the turn.
    assert not point_in_rotated_rect(0.0, -4.0, 0.0, 0.0, 10.0, 2.0, 0.0)
    assert point_in_rotated_rect(0.0, -4.0, 0.0, 0.0, 10.0, 2.0, 90.0)


def test_angle_deg_points_where_expected():
    assert angle_deg(0.0, 0.0, 1.0, 0.0) == pytest.approx(0.0)
    assert angle_deg(0.0, 0.0, 0.0, 1.0) == pytest.approx(90.0)
    assert angle_deg(0.0, 0.0, -1.0, 0.0) == pytest.approx(180.0)
