"""Regression tests for the 2026-07 review fixes:

1. Triangle degree floor: degree-1 triangle legs need >=5 monowaves
   (DESIGN.md §4), not the generic :3 floor of 3.
2. Same-anchor alternates: the report's alternate comes from the winning
   anchor's own root k-best list when a genuinely-different reading exists
   there (DESIGN.md §4/§7), and relative confidence is a softmax over that
   same-span k-best list, not across anchors.
"""

import math

from elliott.anchor import AnchorResult, TournamentResult
from elliott.guidelines import fit_null_model
from elliott.parser import WaveUnit, build_pattern_memo
from elliott.pivots import Pivot
from elliott.report import build_report
from .test_grammar_roundtrip import _textured5, _textured3


def _build_triangle_pivots(leg_builder):
    """Contracting triangle, 5 legs: A 100->140, B 140->110, C 110->130,
    D 130->115, E 115->125."""
    legs = [(100, 140, "L"), (140, 110, "H"), (110, 130, "L"),
            (130, 115, "H"), (115, 125, "L")]
    prices, kinds = [], []
    first = True
    for start, end, k0 in legs:
        p, k = leg_builder(start, end, k0)
        if first:
            prices.extend(p); kinds.extend(k); first = False
        else:
            prices.extend(p[1:]); kinds.extend(k[1:])
    return [Pivot(i, i * 2, f"d{i}", pr, kd) for i, (pr, kd) in enumerate(zip(prices, kinds))]


def test_triangle_legs_of_three_monowaves_rejected():
    """A triangle whose legs span only 3 monowaves each must NOT parse
    (the pre-fix behavior; DESIGN.md §4 requires >=5)."""
    pivots = _build_triangle_pivots(_textured3)
    null = fit_null_model(pivots)
    memo = build_pattern_memo(pivots, null, {"atr_epsilon": 0.0}, k=4)
    full = (0, len(pivots) - 1, "triangle_contract", False)
    assert full not in memo, "triangle with 3-monowave legs should fail the degree floor"


def test_triangle_legs_of_five_monowaves_accepted():
    """The same contracting triangle with 5-monowave legs parses."""
    pivots = _build_triangle_pivots(_textured5)
    null = fit_null_model(pivots)
    memo = build_pattern_memo(pivots, null, {"atr_epsilon": 0.0}, k=4)
    full = (0, len(pivots) - 1, "triangle_contract", False)
    assert full in memo, "triangle with 5-monowave legs should pass the degree floor"
    assert len(memo[full][0].children) == 5


def _node(pattern, direction, ll, i=0, j=10):
    end = 200.0 if direction == "up" else 50.0
    return WaveUnit(i=i, j=j, pattern=pattern, start_price=100.0, end_price=end,
                    hi=210.0, lo=90.0, direction=direction, n_pivots=j - i,
                    start_bar=0, end_bar=20, children=(), ll=ll, total_ll=ll)


def test_report_prefers_same_anchor_alternate_and_rootlist_confidence():
    pivots = [Pivot(i, i, f"d{i}", 100.0 + i, "H" if i % 2 else "L") for i in range(11)]
    winner_root = _node("impulse", "up", 10.0)
    same_anchor_alt = _node("zigzag", "down", 9.0)
    other_root = _node("flat_expanded", "up", 8.0)
    winner = AnchorResult(anchor=0, date="d0", score=10.0, root=winner_root,
                          roots=[winner_root, same_anchor_alt])
    other = AnchorResult(anchor=2, date="d2", score=8.0, root=other_root, roots=[other_root])
    tr = TournamentResult(candidates=[winner, other], winner=winner,
                          no_clean_count=False, margin=10.0)

    report = build_report("TEST", "2026-01-01", pivots, tr, pivot_k=1.0)

    alt = report["alternate"]
    assert alt is not None and alt["same_anchor"] is True
    assert alt["pattern"] == "zigzag" and alt["direction"] == "down"

    # confidence = softmax over the winner's root k-best [10, 9]
    expected = 1.0 / (1.0 + math.exp(9.0 - 10.0))
    assert report["preferred"]["relative_confidence"] == round(expected, 3)


def test_report_falls_back_to_other_anchor_when_no_same_anchor_diversity():
    pivots = [Pivot(i, i, f"d{i}", 100.0 + i, "H" if i % 2 else "L") for i in range(11)]
    winner_root = _node("impulse", "up", 10.0)
    other_root = _node("flat_expanded", "up", 8.0)
    winner = AnchorResult(anchor=0, date="d0", score=10.0, root=winner_root,
                          roots=[winner_root])
    other = AnchorResult(anchor=2, date="d2", score=8.0, root=other_root, roots=[other_root])
    tr = TournamentResult(candidates=[winner, other], winner=winner,
                          no_clean_count=False, margin=10.0)

    report = build_report("TEST", "2026-01-01", pivots, tr, pivot_k=1.0)
    alt = report["alternate"]
    assert alt is not None and alt["same_anchor"] is False
    assert alt["pattern"] == "flat_expanded"
    # single-root k-best list -> confidence 1.0 by construction
    assert report["preferred"]["relative_confidence"] == 1.0
