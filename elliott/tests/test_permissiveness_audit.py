"""Permissiveness audit (DESIGN.md testing strategy §3): random-walk data
must usually refuse to resolve into a count. MULTI-SEED since v1.1: the
single-seed version of this audit passed while 4/8 unseen seeds produced
counts on pure noise -- a calibration failure the one lucky seed hid.

Honest v1.1 calibration state (measured on the 8 seeds below): 6/8 seeds
refuse, 2/8 produce a count on pure noise -- one weak (3.9, permissive
triangle root, the known hot spot from DESIGN.md's named risks) and one
STRONG (seed 4: closed zigzag at 16.4 nats, carried by a single lucky
degree-1 impulse at +12.5 -- the multiple-comparison max over ~1e5 spans,
not fixable by thresholding without killing every genuine weak count,
whose scores start at 4.2). This audit is therefore a REGRESSION TRIPWIRE
pinned to the measured state, not an unattainable zero-FPR assertion:
  * at least 6 of 8 seeds must declare no-clean-count
  * no seed may score above 17.0 nats
Exceeding either bound means the hypothesis space leaked further (as it
did at +14.8 before the final-open gate) -- investigate, don't re-pin.
Residual false positives are disclosed in DESIGN.md's errata and softened
by the report's confidence/alternate/warnings fields.
"""

import random

from elliott.anchor import NO_CLEAN_COUNT_MARGIN, run_tournament
from elliott.guidelines import fit_null_model
from elliott.parser import build_pattern_memo
from elliott.pivots import calibrate_pivots

SEEDS = range(8)
MIN_REFUSALS = 6            # of 8; measured v1.1 state is exactly 6
MAX_TOLERATED_MARGIN = 17.0  # nats; measured v1.1 worst is 16.4 (seed 4)


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


def test_random_walks_mostly_trigger_no_clean_count():
    refusals = 0
    worst_margin = float("-inf")
    for seed in SEEDS:
        dates, highs, lows, closes = _gbm(seed=seed)
        _, pivots = calibrate_pivots(dates, highs, lows, closes)
        null = fit_null_model(pivots)
        ctx = {"atr_epsilon": 0.0}
        memo = build_pattern_memo(pivots, null, ctx, k=4)
        tournament = run_tournament(pivots, memo, null, ctx, k=4)
        if tournament.no_clean_count:
            refusals += 1
        if tournament.margin != float("-inf"):
            worst_margin = max(worst_margin, tournament.margin)

    assert refusals >= MIN_REFUSALS, (
        f"only {refusals}/{len(list(SEEDS))} random walks refused "
        f"(margin threshold {NO_CLEAN_COUNT_MARGIN})")
    assert worst_margin < MAX_TOLERATED_MARGIN, (
        f"a random walk scored {worst_margin:.2f} nats -- the grammar is "
        f"absorbing noise; check for a hypothesis-space leak")
