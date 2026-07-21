"""Open-component handling of "must exceed" hard rules (grammar.py): an
assertion like "C must exceed A's end" is undecidable while C is underway
-- killing the parse there refuses legitimate still-forming patterns (the
NVDA expanded-flat case). "Within/short" rules are unaffected: a violation
by an open component is unrecoverable and still fails."""

from elliott import grammar as G
from elliott.guidelines import fit_null_model
from elliott.parser import WaveUnit, build_pattern_memo
from elliott.pivots import Pivot


def _unit(start, end, open_=False):
    return WaveUnit(i=0, j=1, pattern=None, start_price=start, end_price=end,
                    hi=max(start, end), lo=min(start, end),
                    direction="up" if end > start else "down", n_pivots=1,
                    start_bar=0, end_bar=1, open=open_)


def test_beyond_rules_undecidable_when_open():
    a = _unit(100, 70)          # down leg
    b_open = _unit(70, 95, open_=True)   # not yet beyond A's start (100)
    assert G.b_beyond_a_start([a, b_open], {}) is True
    b_closed = _unit(70, 95)
    assert G.b_beyond_a_start([a, b_closed], {}) is False  # closed: rule bites

    c_open = _unit(95, 80, open_=True)   # not yet beyond A's end (70)
    assert G.c_beyond_a_end([a, b_closed, c_open], {}) is True
    c_closed = _unit(95, 80)
    assert G.c_beyond_a_end([a, b_closed, c_closed], {}) is False


def test_within_rules_still_fail_when_unrecoverable():
    a = _unit(100, 70)
    c_open_beyond = _unit(95, 60, open_=True)  # already beyond A's end: can't come back
    assert G.c_short_of_a_end([a, _unit(70, 95), c_open_beyond], {}) is False
    assert G.c_within_a_end([a, _unit(70, 95), c_open_beyond], {}) is False


def _pivots(pts):
    return [Pivot(i, i, f"d{i}", pr, kd) for i, (pr, kd) in enumerate(pts)]


def test_open_expanded_flat_parses_before_c_exceeds_a_end():
    # A down (3 monowaves), B up beyond A's start, C underway NOT yet beyond
    # A's end -- the still-forming expanded flat must now be representable.
    pts = [(100, "H"), (82, "L"), (87.4, "H"), (70, "L"),          # A
           (91.6, "H"), (85.12, "L"), (106, "H"),                  # B (beyond 100)
           (90, "L"), (96, "H"), (80, "L")]                        # C open, above 70
    pivots = _pivots(pts)
    null = fit_null_model(pivots)
    memo = build_pattern_memo(pivots, null, {"atr_epsilon": 0.0}, k=4)
    key = (0, len(pivots) - 1, "flat_expanded", True)
    assert key in memo, "open expanded flat with C not yet beyond A's end was refused"
    assert memo[key][0].children[-1].open


def test_closed_expanded_flat_rule_still_bites():
    # same shape but C COMPLETES above A's end: not an expanded flat
    pts = [(100, "H"), (82, "L"), (87.4, "H"), (70, "L"),
           (91.6, "H"), (85.12, "L"), (106, "H"),
           (90, "L"), (96, "H"), (85, "L"), (88, "H"), (80, "L")]  # C closed at 80 > 70
    pivots = _pivots(pts)
    null = fit_null_model(pivots)
    memo = build_pattern_memo(pivots, null, {"atr_epsilon": 0.0}, k=4)
    key = (0, len(pivots) - 1, "flat_expanded", False)
    assert key not in memo, "closed flat with C short of A's end must stay illegal"
