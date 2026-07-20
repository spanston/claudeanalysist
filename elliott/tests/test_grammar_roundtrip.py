"""Grammar round-trip: build a deliberately clean, textured impulse and
confirm the parser recovers it as the top-scoring degree-1 pattern
(DESIGN.md's testing strategy §testing item 1)."""

from elliott.guidelines import fit_null_model
from elliott.parser import build_pattern_memo
from elliott.pivots import Pivot


def _textured5(start, end, kind0):
    total = end - start
    p1 = start + 0.5 * total
    p2 = p1 - 0.3 * (p1 - start)
    p3 = p1 + 0.6 * (end - p1)
    p4 = p3 - 0.3 * (p3 - p2)
    kinds = [kind0, _flip(kind0), kind0, _flip(kind0), kind0, _flip(kind0)]
    return [start, p1, p2, p3, p4, end], kinds


def _textured3(start, end, kind0):
    total = end - start
    p1 = start + 0.6 * total
    p2 = p1 - 0.3 * (p1 - start)
    kinds = [kind0, _flip(kind0), kind0, _flip(kind0)]
    return [start, p1, p2, end], kinds


def _flip(k):
    return "L" if k == "H" else "H"


def _build_impulse_pivots():
    segs = [
        (100, 200, "L", "5"), (200, 150, "H", "3"), (150, 380, "L", "5"),
        (380, 320, "H", "3"), (320, 450, "L", "5"),
    ]
    prices, kinds = [], []
    first = True
    for start, end, k0, slot in segs:
        p, k = _textured5(start, end, k0) if slot == "5" else _textured3(start, end, k0)
        if first:
            prices.extend(p)
            kinds.extend(k)
            first = False
        else:
            prices.extend(p[1:])
            kinds.extend(k[1:])
    return [Pivot(i, i * 2, f"d{i}", pr, kd) for i, (pr, kd) in enumerate(zip(prices, kinds))]


def test_clean_impulse_is_recovered():
    pivots = _build_impulse_pivots()
    null = fit_null_model(pivots)
    ctx = {"atr_epsilon": 0.0}
    memo = build_pattern_memo(pivots, null, ctx, k=4)

    impulse_entries = [key for key in memo if key[2] == "impulse" and not key[3]]
    assert impulse_entries, "no closed impulse parse found at all"

    full_span = (0, len(pivots) - 1, "impulse", False)
    assert full_span in memo, "impulse spanning the whole textured series was not recovered"
    best = memo[full_span][0]
    assert best.total_ll > 0, "a clean, well-proportioned impulse should score better than the null"
    assert len(best.children) == 5


def test_bad_impulse_scores_worse_than_clean_one():
    """A wave 3 shortened to violate 'W3 is never the shortest' should
    either be pruned entirely (hard rule) or, if some other partition
    still reads as 'impulse' at the full span, score worse than the clean
    case above."""
    pivots = _build_impulse_pivots()
    # shrink wave 3 (segment index 2, pivot span roughly [8,13]) toward wave 1's size
    bad_prices = [p.price for p in pivots]
    bad_prices[11] = bad_prices[8] + (bad_prices[5] - bad_prices[0]) * 0.3
    bad_prices[13] = bad_prices[8] + (bad_prices[5] - bad_prices[0]) * 0.5
    bad_pivots = [Pivot(p.i, p.bar, p.date, bad_prices[p.i], p.kind) for p in pivots]

    null = fit_null_model(bad_pivots)
    ctx = {"atr_epsilon": 0.0}
    memo = build_pattern_memo(bad_pivots, null, ctx, k=4)
    full_span = (0, len(bad_pivots) - 1, "impulse", False)
    assert full_span not in memo, "an impulse with a too-short wave 3 should fail the hard rule"
