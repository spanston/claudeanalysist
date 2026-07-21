"""Degree-floor shape checks (DESIGN.md §4): endpoint extremes AND interior
containment -- a run whose counter-swings cross the run's own start is not
one wave and must be rejected as a leaf."""

from elliott.parser import leaf_shape_ok
from elliott.pivots import Pivot


def _pivots(prices_kinds):
    return [Pivot(i, i, f"d{i}", pr, kd) for i, (pr, kd) in enumerate(prices_kinds)]


def test_down_leaf_rejects_interior_high_above_start():
    # down run 100 -> 80 with an interior rally to 110: not one wave
    pivots = _pivots([(100, "H"), (90, "L"), (110, "H"), (85, "L"), (95, "H"), (80, "L")])
    assert not leaf_shape_ok(pivots, 0, 5, "5")


def test_down_leaf_accepts_interior_pullbacks_inside_extremes():
    # down run 100 -> 80, interior rally only to 95: legal
    pivots = _pivots([(100, "H"), (90, "L"), (95, "H"), (85, "L"), (92, "H"), (80, "L")])
    assert leaf_shape_ok(pivots, 0, 5, "5")


def test_up_leaf_rejects_interior_low_below_start():
    # up run 80 -> 100 with an interior dip to 70: not one wave
    pivots = _pivots([(80, "L"), (90, "H"), (70, "L"), (95, "H"), (85, "L"), (100, "H")])
    assert not leaf_shape_ok(pivots, 0, 5, "5")


def test_up_leaf_accepts_interior_pullbacks_inside_extremes():
    pivots = _pivots([(80, "L"), (90, "H"), (85, "L"), (95, "H"), (88, "L"), (100, "H")])
    assert leaf_shape_ok(pivots, 0, 5, "5")
