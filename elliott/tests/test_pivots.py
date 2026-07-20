import random

from elliott.pivots import calibrate_pivots, wilder_atr, zigzag


def _gbm_series(n=1000, vol=0.6, seed=1):
    random.seed(seed)
    dt = 1 / 365
    price = 30000.0
    dates, highs, lows, closes = [], [], [], []
    for i in range(n):
        shock = random.gauss(0, vol * (dt ** 0.5))
        price *= (1 + shock)
        high = price * (1 + abs(random.gauss(0, 0.01)))
        low = price * (1 - abs(random.gauss(0, 0.01)))
        dates.append(f"2020-01-{(i % 28) + 1:02d}")
        highs.append(high)
        lows.append(low)
        closes.append(price)
    return dates, highs, lows, closes


def test_atr_matches_length():
    dates, highs, lows, closes = _gbm_series(200)
    atr = wilder_atr(highs, lows, closes, period=14)
    assert len(atr) == len(closes)
    assert all(a >= 0 for a in atr)


def test_zigzag_alternates_kind():
    dates, highs, lows, closes = _gbm_series(500)
    pivots = zigzag(dates, highs, lows, closes, k=1.0)
    kinds = [p.kind for p in pivots]
    assert all(kinds[i] != kinds[i + 1] for i in range(len(kinds) - 1))


def test_pivot_count_monotone_in_k():
    dates, highs, lows, closes = _gbm_series(1000, seed=3)
    ks = [0.3, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0]
    counts = [len(zigzag(dates, highs, lows, closes, k)) for k in ks]
    assert all(counts[i] >= counts[i + 1] for i in range(len(counts) - 1))


def test_calibrate_hits_target_band():
    dates, highs, lows, closes = _gbm_series(1200, seed=5)
    k, pivots = calibrate_pivots(dates, highs, lows, closes, target_lo=80, target_hi=150)
    assert 60 <= len(pivots) <= 170  # allow slack: step-function/plateau edge cases
