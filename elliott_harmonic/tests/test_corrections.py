"""Unit tests for corrective-structure classification: zigzag, flat family,
contracting triangle, double three, and honest refusal on non-corrections."""

from __future__ import annotations

from elliott.pivots import Pivot

from elliott_harmonic.corrections import match_correction, scan_corrections


def mk_pivots(prices: list[float]) -> list[Pivot]:
    """Alternating-kind pivot list from a price path (first pivot = trough)."""
    out = []
    for i, price in enumerate(prices):
        kind = "L" if i % 2 == 0 else "H"
        out.append(Pivot(i=i, bar=i * 5, date=f"2026-01-{i + 1:02d}", price=price, kind=kind))
    return out


# Up-zigzag: A = 100->110 (internal c/a ~ 1.146), B = 61.8% retrace (1 leg),
# C = 103.8->114.7 = 1.09x A (internal c/a ~ 1.586).
ZIGZAG_UP = [100, 106, 103, 110, 103.8, 108.8, 106.8, 114.7]

# Same skeleton but B = 55% (mid-gap between table values) and C = 1.17x A
# (between 1.146 and 1.236): structurally valid, harmonically sloppy.
ZIGZAG_SLOPPY = [100, 106, 103, 110, 104.5, 109.5, 107.5, 116.2]

# Down expanded flat (lead-in L): A = 100->90, B overshoots the A start by
# 27% of A (inside the 14.6-38.2% band), C exceeds the A end by 15% of A.
FLAT_EXPANDED_DOWN = [90, 100, 95, 97, 90, 97, 94, 102.7, 96, 99, 88.5]

# Up running flat: A = 100->110, B overshoots the A start by 24% of A,
# C fails to reach the A end (110) by 20% of A.
FLAT_RUNNING_UP = [100, 106, 103, 110, 104, 107, 97.6, 103, 100.6, 108]

# Up regular flat: B retests the A start (98%), C ends exactly on the A end.
FLAT_REGULAR_UP = [100, 106, 103, 110, 104, 109, 100.2, 105.7, 103.2, 110]

# Down contracting triangle (lead-in L): legs 8 / 6.4 / 4.6 / 3.3 / 1.9,
# ratios 0.80 / 0.72 / 0.72 / 0.58 -- all inside their bands.
TRIANGLE_DOWN = [88, 100, 92, 98.4, 93.8, 97.1, 95.2]

# Down double three (lead-in L): W = zigzag 100->88.5 (net 11.5, B 55% so the
# lone-zigzag reading is sloppy), X = 1 leg to 93, Y = zigzag 93->81.6
# (net 11.4 = 99.1% of W).
DOUBLE_THREE_DOWN = [85, 100, 95, 97.5, 92, 96.4, 93, 95, 88.5, 93,
                     88.5, 90.5, 85.5, 89.25, 86, 88, 81.6]


def test_clean_zigzag():
    m = match_correction(mk_pivots(ZIGZAG_UP), 0, "up")
    assert m is not None
    assert m.pattern == "zigzag"
    assert m.variant is None
    assert m.direction == "up"
    assert (m.start, m.end) == (0, 7)
    assert m.score > 0.85, f"clean zigzag should score high: {m.score}"
    assert abs(m.legs["B"]["retr"] - 0.62) < 0.01
    assert abs(m.legs["C"]["c_over_a"] - 1.09) < 0.01
    # C=A projections: only levels still beyond the realized C end (114.7)
    # survive -- the rest are stale (already traded through).
    prices = {t["label"]: t["price"] for t in m.targets}
    assert "C = A x 1.0" not in prices      # 113.8 < 114.7: already reached
    assert "C = A x 0.618" not in prices
    assert abs(prices["C = A x 1.236"] - 116.16) < 1e-6
    assert abs(prices["C = A x 1.764"] - 121.44) < 1e-6
    assert m.invalidation["price"] == 100
    # End is the last pivot -> provisional edge flagged.
    assert any("provisional" in n for n in m.notes)


def test_zigzag_targets_stale_levels_dropped():
    # Realized C/A = 1.5: every projection up to 1.236 is already exceeded;
    # only the 1.764 extension remains a live target.
    steep = [100, 106, 103, 110, 103.8, 112, 109, 118.8]
    m = match_correction(mk_pivots(steep), 0, "up")
    assert m is not None and m.pattern == "zigzag"
    assert abs(m.legs["C"]["c_over_a"] - 1.5) < 0.01
    assert [t["label"] for t in m.targets] == ["C = A x 1.764"]


def test_clean_zigzag_beats_sloppy():
    clean = match_correction(mk_pivots(ZIGZAG_UP), 0, "up")
    sloppy = match_correction(mk_pivots(ZIGZAG_SLOPPY), 0, "up")
    assert clean is not None and sloppy is not None
    assert sloppy.pattern == "zigzag"
    assert clean.score > sloppy.score


def test_zigzag_tail_allowed():
    # A tail after the C end (no new extreme) does not disturb the reading.
    m = match_correction(mk_pivots(ZIGZAG_UP + [111, 113]), 0, "up")
    assert m is not None and m.pattern == "zigzag"
    assert m.end == 7
    assert not any("provisional" in n for n in m.notes)


def test_expanded_flat():
    m = match_correction(mk_pivots(FLAT_EXPANDED_DOWN), 1, "down")
    assert m is not None
    assert m.pattern == "flat"
    assert m.variant == "expanded"
    assert m.score > 0.85, f"clean expanded flat should score high: {m.score}"
    assert abs(m.legs["B"]["retr"] - 1.27) < 0.01
    assert m.legs["C"]["terminal_vs_a"] > 0  # C exceeded the A extreme


def test_running_flat():
    m = match_correction(mk_pivots(FLAT_RUNNING_UP), 0, "up")
    assert m is not None
    assert m.pattern == "flat"
    assert m.variant == "running"
    assert m.legs["B"]["retr"] > 1.0          # B made a new extreme
    assert m.legs["C"]["terminal_vs_a"] < 0   # C failed to reach the A extreme


def test_regular_flat():
    # Structurally also a valid deep-B zigzag; the exact B retest + C landing
    # on the A end should tip the reading to regular flat.
    m = match_correction(mk_pivots(FLAT_REGULAR_UP), 0, "up")
    assert m is not None
    assert m.pattern == "flat"
    assert m.variant == "regular"


def test_contracting_triangle():
    m = match_correction(mk_pivots(TRIANGLE_DOWN), 1, "down")
    assert m is not None
    assert m.pattern == "triangle"
    assert m.variant == "contracting"
    assert m.score > 0.9, f"band-perfect triangle should score high: {m.score}"
    assert abs(m.legs["b"]["ratio_to_prev"] - 0.80) < 0.01
    assert abs(m.legs["e"]["ratio_to_prev"] - 0.58) < 0.01
    assert any("wave-e" in n for n in m.notes)
    # Post-thrust projection: leg a (8 points) UP from the e end -- price
    # enters and leaves a triangle in the same direction (trend resumption);
    # the a-leg is counter-trend, so the thrust runs opposite it.
    assert abs(m.targets[0]["price"] - 103.2) < 1e-6


def test_double_three():
    m = match_correction(mk_pivots(DOUBLE_THREE_DOWN), 1, "down")
    assert m is not None
    assert m.pattern == "double_three"
    assert m.variant is None
    assert m.end == 16
    assert m.score > 0.7, f"double three should beat its sloppy W zigzag: {m.score}"
    assert abs(m.legs["y_over_w"] - 0.991) < 0.01
    # Y = 100% x W projected from the X end: 93 - 11.5.
    assert abs(m.targets[0]["price"] - 81.5) < 1e-6
    assert m.invalidation["price"] == 100


def test_negative_b_beyond_start_of_a():
    # B reaches 160% of A: kills the zigzag (B beyond start of A) and the flat
    # (expanded beyond 50% of A); C then runs far beyond -- not corrective.
    bad = [100, 106, 103, 110, 104, 108, 94, 102, 99, 112]
    assert match_correction(mk_pivots(bad), 0, "up") is None


def test_negative_non_contracting_triangle():
    # 5 legs but expansions everywhere: b > a, d > c beyond the 38.2%
    # irregular allowance, and the post-expansion leg misses 85.4-105.6%.
    bad = [95, 100, 94, 99, 92, 98]
    assert match_correction(mk_pivots(bad), 0, "up") is None


def test_negative_directionless_chop():
    chop = [100 + (1 if i % 2 else 0) for i in range(12)]
    pivots = mk_pivots(chop)
    assert match_correction(pivots, 0, "up") is None
    assert scan_corrections(pivots) == []


def test_direction_must_agree_with_start_kind():
    pivots = mk_pivots(ZIGZAG_UP)  # pivot 0 is a trough
    assert match_correction(pivots, 0, "down") is None


def test_scan_corrections_sorted_and_deduped():
    pivots = mk_pivots(DOUBLE_THREE_DOWN)
    out = scan_corrections(pivots)
    assert out, "expected matches on the double-three sequence"
    scores = [m.score for m in out]
    assert scores == sorted(scores, reverse=True)
    keys = [(m.pattern, m.variant, m.start, m.end) for m in out]
    assert len(keys) == len(set(keys))
    # The double three outranks the lone (sloppy-B) W zigzag at the same start;
    # the clean Y zigzag outranking both is correct -- Y IS a zigzag.
    d3 = next(m for m in out if m.pattern == "double_three")
    w_zz = next(m for m in out if m.pattern == "zigzag" and m.start == 1)
    assert d3.start == 1
    assert d3.score > w_zz.score
    # Direction filter: no up-corrections in this down structure.
    assert all(m.direction == "up" for m in scan_corrections(pivots, "up"))
