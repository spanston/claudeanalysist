"""Permissiveness audit (DESIGN.md testing strategy §3): random-walk data
must not resolve into a confidently-labeled count. The engine should say
'no clean count' rather than hallucinate structure, and even the winning
candidate's LLR-based score should not be strongly positive."""

import random

from elliott.anchor import NO_CLEAN_COUNT_MARGIN, run_tournament
from elliott.guidelines import fit_null_model
from elliott.parser import build_pattern_memo
from elliott.pivots import calibrate_pivots


def _gbm(n=600, vol=0.6, seed=42):
    random.seed(seed)
    dt = 1 / 365
    price = 30000.0
    dates, highs, lows, closes = [], [], [], []
    for i in range(n):
        shock = random.gauss(0, vol * (dt ** 0.5))
        price *= (1 + shock)
        highs.append(price * (1 + abs(random.gauss(0, 0.01))))
        lows.append(price * (1 - abs(random.gauss(0, 0.01))))
        closes.append(price)
        dates.append(f"d{i}")
    return dates, highs, lows, closes


def test_random_walk_triggers_no_clean_count():
    dates, highs, lows, closes = _gbm()
    _, pivots = calibrate_pivots(dates, highs, lows, closes)
    null = fit_null_model(pivots)
    ctx = {"atr_epsilon": 0.0}
    memo = build_pattern_memo(pivots, null, ctx, k=4)
    tournament = run_tournament(pivots, memo, null, ctx, k=4)

    assert tournament.no_clean_count
    assert tournament.margin < NO_CLEAN_COUNT_MARGIN
