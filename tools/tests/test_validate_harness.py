"""score_call: a binding level already violated at the as-of close is an
invalid call, not a guaranteed breach_first -- it must be marked
"invalid_binding" and excluded from the means (score None)."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from elliott.data import Series
from tools.validate_harness import score_call


def _series(closes):
    n = len(closes)
    return Series(dates=[f"d{i}" for i in range(n)], opens=list(closes),
                  highs=list(closes), lows=list(closes),
                  closes=list(closes), volumes=[0.0] * n)


def test_down_call_binding_below_close_is_invalid():
    # binding 153.13 vs as-of close 173.00 for a down call: the level is
    # already broken at t, so breach_first would be guaranteed from bar 1
    series = _series([170.0] * 5 + [173.0] + [175.0] * 10)
    rec = score_call("down", binding=153.13, target=150.0, series=series, t=5, atr_t=2.0)
    assert rec["verdict"] == "invalid_binding"
    assert rec["score"] is None


def test_up_call_binding_above_close_is_invalid():
    series = _series([100.0] * 6 + [105.0] * 10)
    rec = score_call("up", binding=101.0, target=110.0, series=series, t=5, atr_t=2.0)
    assert rec["verdict"] == "invalid_binding"
    assert rec["score"] is None


def test_right_side_binding_scores_normally():
    # down call with the binding above the close: untouched in-window and
    # drifting against -> ordinary open call scoring 0.0, not invalid
    series = _series([100.0] * 6 + [105.0] * 10)
    rec = score_call("down", binding=120.0, target=None, series=series, t=5, atr_t=2.0)
    assert rec["verdict"] == "open"
    assert rec["score"] == 0.0
