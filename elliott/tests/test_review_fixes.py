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
from .test_grammar_roundtrip import _build_impulse_pivots, _textured5, _textured3


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


# ---------------------------------------------------------------------------
# v1.1: open-edge coherence + report price context
# ---------------------------------------------------------------------------

def test_prefix_complete_impulse_wave3_underway():
    """Prefix-complete parse (DESIGN.md §4, review finding B): an impulse
    with waves 1-2 complete and wave 3 underway must be representable --
    not only 'final component in progress' readings."""
    p1, k1 = _textured5(100, 200, "L")   # wave 1 complete
    p2, k2 = _textured3(200, 150, "H")   # wave 2 complete
    p3, k3 = [150, 220, 190, 260], ["L", "H", "L", "H"]  # wave 3 underway
    prices = p1 + p2[1:] + p3[1:]
    kinds = k1 + k2[1:] + k3[1:]
    pivots = [Pivot(i, i * 2, f"d{i}", pr, kd) for i, (pr, kd) in enumerate(zip(prices, kinds))]

    null = fit_null_model(pivots)
    memo = build_pattern_memo(pivots, null, {"atr_epsilon": 0.0}, k=4)
    full = (0, len(pivots) - 1, "impulse", True)
    assert full in memo, "no open impulse spanning the partial wave 3"
    prefixes = [nd for nd in memo[full] if len(nd.children) == 3]
    assert prefixes, "expected a prefix parse with children (1, 2, open 3)"
    node = prefixes[0]
    assert [c.open for c in node.children] == [False, False, True]
    assert node.children[2].direction == "up"


def test_open_components_always_alternate_direction():
    """An open right-edge component must move AGAINST its predecessor --
    otherwise the predecessor is still unfolding (review finding A: NVO/BTC
    'up wave 5' readings whose open leaf was in fact collapsing)."""
    base = _build_impulse_pivots()
    # collapse tail: price falls hard from the 450 top -- the incoherent
    # "open up wave 5" configuration from the review
    tail = [
        Pivot(len(base), base[-1].bar + 2, "t1", 380.0, "L"),
        Pivot(len(base) + 1, base[-1].bar + 4, "t2", 400.0, "H"),
        Pivot(len(base) + 2, base[-1].bar + 6, "t3", 300.0, "L"),
    ]
    pivots = base + tail
    null = fit_null_model(pivots)
    memo = build_pattern_memo(pivots, null, {"atr_epsilon": 0.0}, k=4)

    checked = 0
    for (i, j, name, is_open), nodes in memo.items():
        if not is_open:
            continue
        for nd in nodes:
            ch = nd.children
            assert ch and ch[-1].open, f"open {name} without open last child"
            if len(ch) >= 2:
                assert ch[-1].direction != ch[-2].direction, (
                    f"open {name} [{i},{j}]: last two components both {ch[-1].direction}")
                checked += 1
    assert checked > 0, "no multi-component open parses found to check"


def _open_c_zigzag_root():
    """Up zigzag with wave C open (the documented no-invalidation case)."""
    a = WaveUnit(i=0, j=4, pattern=None, start_price=100.0, end_price=200.0,
                 hi=200.0, lo=100.0, direction="up", n_pivots=4, start_bar=0, end_bar=8)
    b = WaveUnit(i=4, j=7, pattern=None, start_price=200.0, end_price=150.0,
                 hi=200.0, lo=150.0, direction="down", n_pivots=3, start_bar=8, end_bar=14)
    c = WaveUnit(i=7, j=10, pattern=None, start_price=150.0, end_price=180.0,
                 hi=185.0, lo=150.0, direction="up", n_pivots=3, start_bar=14, end_bar=20,
                 open=True)
    return WaveUnit(i=0, j=10, pattern="zigzag", start_price=100.0, end_price=180.0,
                    hi=200.0, lo=100.0, direction="up", n_pivots=10, start_bar=0, end_bar=20,
                    children=(a, b, c), ll=5.0, total_ll=10.0, open=True)


def test_report_price_context_and_warnings():
    pivots = [Pivot(i, i * 2, f"2026-07-{7 + i:02d}", 100.0 + i, "H" if i % 2 else "L")
              for i in range(11)]
    root = _open_c_zigzag_root()
    winner = AnchorResult(anchor=0, date=pivots[0].date, score=10.0, root=root, roots=[root])
    tr = TournamentResult(candidates=[winner], winner=winner,
                          no_clean_count=False, margin=10.0)

    report = build_report("TEST", "2026-07-20", pivots, tr, pivot_k=1.0,
                          last_close=180.0, data_through="2026-07-17")

    assert report["meta"]["last_close"] == 180.0
    assert report["meta"]["data_through"] == "2026-07-17"
    # the zigzag's last pivot is always provisional (pivots.py): the report
    # must say so for downstream consumers
    assert report["meta"]["right_edge_provisional"] is True

    targets = report["preferred"]["targets"]
    assert len(targets) == 1 and targets[0]["price"] == 250.0  # C = A from B
    assert targets[0]["pct_from_last"] == 38.9

    warnings = report["warnings"]
    assert any(w.startswith("no_invalidation_available") for w in warnings)
    assert any(w.startswith("stale_data") for w in warnings)
    assert not any(w.startswith("target_overshoot") for w in warnings)


# ---------------------------------------------------------------------------
# v1.2: target_overshoot keys on the target's own direction
# ---------------------------------------------------------------------------

def _impulse_with_open_w4_zigzag_root():
    """Up impulse whose wave 4 is an unfolding zigzag: the degree-1 (C)
    target points DOWN, against the root's up direction (the BTC-USD case:
    up impulse, '(C) unfolding (zigzag)', downside target never reached)."""
    w1 = WaveUnit(i=0, j=3, pattern=None, start_price=100.0, end_price=200.0,
                  hi=200.0, lo=100.0, direction="up", n_pivots=3, start_bar=0, end_bar=6)
    w2 = WaveUnit(i=3, j=5, pattern=None, start_price=200.0, end_price=150.0,
                  hi=200.0, lo=150.0, direction="down", n_pivots=2, start_bar=6, end_bar=10)
    w3 = WaveUnit(i=5, j=9, pattern=None, start_price=150.0, end_price=400.0,
                  hi=400.0, lo=150.0, direction="up", n_pivots=4, start_bar=10, end_bar=18)
    a = WaveUnit(i=9, j=11, pattern=None, start_price=400.0, end_price=350.0,
                 hi=400.0, lo=350.0, direction="down", n_pivots=2, start_bar=18, end_bar=22)
    b = WaveUnit(i=11, j=13, pattern=None, start_price=350.0, end_price=380.0,
                 hi=380.0, lo=350.0, direction="up", n_pivots=2, start_bar=22, end_bar=26)
    c = WaveUnit(i=13, j=15, pattern=None, start_price=380.0, end_price=360.0,
                 hi=380.0, lo=355.0, direction="down", n_pivots=2, start_bar=26, end_bar=30,
                 open=True)
    w4 = WaveUnit(i=9, j=15, pattern="zigzag", start_price=400.0, end_price=360.0,
                  hi=400.0, lo=350.0, direction="down", n_pivots=6, start_bar=18, end_bar=30,
                  children=(a, b, c), ll=5.0, total_ll=8.0, open=True)
    return WaveUnit(i=0, j=15, pattern="impulse", start_price=100.0, end_price=360.0,
                    hi=400.0, lo=100.0, direction="up", n_pivots=15, start_bar=0, end_bar=30,
                    children=(w1, w2, w3, w4), ll=10.0, total_ll=15.0, open=True)


def test_target_overshoot_compares_on_the_targets_own_side():
    pivots = [Pivot(i, i * 2, f"2026-07-{1 + i:02d}", 100.0 + i, "H" if i % 2 else "L")
              for i in range(16)]
    root = _impulse_with_open_w4_zigzag_root()
    winner = AnchorResult(anchor=0, date=pivots[0].date, score=15.0, root=root, roots=[root])
    tr = TournamentResult(candidates=[winner], winner=winner,
                          no_clean_count=False, margin=15.0)

    report = build_report("TEST", "2026-07-21", pivots, tr, pivot_k=1.0, last_close=360.0)
    targets = report["preferred"]["targets"]
    assert len(targets) == 1 and targets[0]["price"] == 330.0  # C = A from B
    assert targets[0]["direction"] == "down"
    # 360 is NOT beyond a downside target of 330: the pre-fix check keyed on
    # the root's up direction and fired spuriously here
    assert not any(w.startswith("target_overshoot") for w in report["warnings"])

    # a close on the target's own far side (below 330) still warns
    report = build_report("TEST", "2026-07-21", pivots, tr, pivot_k=1.0, last_close=320.0)
    assert any(w.startswith("target_overshoot") for w in report["warnings"])
