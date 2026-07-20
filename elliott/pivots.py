"""Pivot extraction: ATR-scaled zigzag reducing OHLC bars to alternating
swing highs/lows ("monowaves"), with monowave-budget auto-calibration.

See DESIGN.md §2. The zigzag here is the standard threshold-reversal
("greedy") algorithm: a candidate extreme is tracked and confirmed as a
pivot once price reverses by k * ATR against it. DESIGN.md's "offline
-maximal" framing is the idealization that guarantees strict monotonicity
of pivot count in k; the greedy algorithm was validated empirically to be
monotone (0 violations) on real BTC data and synthetic GBM in the
feasibility simulation, so calibration here uses a robust grid-scan +
local-refine search rather than assuming exact bisection safety.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class Pivot:
    """A confirmed swing extreme."""

    i: int          # index into the pivot sequence (0-based)
    bar: int        # index into the original OHLC bar arrays
    date: str       # ISO date string
    price: float    # extreme price (high for a peak, low for a trough)
    kind: str       # "H" (peak) or "L" (trough)


def wilder_atr(highs: Sequence[float], lows: Sequence[float],
                closes: Sequence[float], period: int = 14) -> list[float]:
    """Wilder-smoothed Average True Range. Returns a list the same length
    as the inputs; the first `period` entries are the running simple-mean
    warm-up (not None) so callers can slice past the warm-up themselves."""
    n = len(closes)
    if n == 0:
        return []
    tr = [0.0] * n
    tr[0] = highs[0] - lows[0]
    for t in range(1, n):
        tr[t] = max(
            highs[t] - lows[t],
            abs(highs[t] - closes[t - 1]),
            abs(lows[t] - closes[t - 1]),
        )
    atr = [0.0] * n
    warm = min(period, n)
    atr[warm - 1] = sum(tr[:warm]) / warm
    for t in range(warm, n):
        atr[t] = (atr[t - 1] * (period - 1) + tr[t]) / period
    # Backfill the pre-warm-up entries with the first computed value so
    # every index has a usable (if crude) ATR estimate.
    for t in range(warm - 1):
        atr[t] = atr[warm - 1]
    return atr


def zigzag(dates: Sequence[str], highs: Sequence[float], lows: Sequence[float],
            closes: Sequence[float], k: float, atr_period: int = 14,
            warmup: int | None = None) -> list[Pivot]:
    """Threshold-reversal zigzag over bar highs/lows.

    A running candidate extreme is tracked; a bar confirms and flips the
    candidate once it reverses by >= k * ATR[bar] against it. ATR is
    evaluated at the *current* bar (causal, matches the feasibility
    simulation's validated implementation).

    `warmup` bars (default = atr_period) are excluded from candidacy so
    pivots never land in the ATR warm-up region (DESIGN.md §2 edge case).
    """
    n = len(closes)
    if warmup is None:
        warmup = atr_period
    if n <= warmup + 1:
        return []

    atr = wilder_atr(highs, lows, closes, atr_period)

    # Establish the initial direction from the first decisive move after
    # warm-up: track both a candidate high and candidate low simultaneously
    # until one leg exceeds the threshold, then commit.
    start = warmup
    cand_hi_bar, cand_hi = start, highs[start]
    cand_lo_bar, cand_lo = start, lows[start]
    direction = None  # "up" (seeking a high) or "down" (seeking a low)

    t = start + 1
    while t < n and direction is None:
        if highs[t] > cand_hi:
            cand_hi_bar, cand_hi = t, highs[t]
        if lows[t] < cand_lo:
            cand_lo_bar, cand_lo = t, lows[t]
        if cand_hi - lows[t] >= k * atr[t]:
            direction = "down"  # confirmed a high, now seeking a low
        elif highs[t] - cand_lo >= k * atr[t]:
            direction = "up"  # confirmed a low, now seeking a high
        t += 1

    if direction is None:
        return []

    pivots: list[Pivot] = []
    if direction == "down":
        pivots.append(Pivot(0, cand_hi_bar, dates[cand_hi_bar], cand_hi, "H"))
        cand_bar, cand_price = cand_lo_bar, cand_lo
    else:
        pivots.append(Pivot(0, cand_lo_bar, dates[cand_lo_bar], cand_lo, "L"))
        cand_bar, cand_price = cand_hi_bar, cand_hi

    for t2 in range(t, n):
        if direction == "down":
            # seeking a low: extend the candidate low, confirm on reversal up
            if lows[t2] < cand_price:
                cand_bar, cand_price = t2, lows[t2]
            elif highs[t2] - cand_price >= k * atr[t2]:
                pivots.append(Pivot(len(pivots), cand_bar, dates[cand_bar],
                                     cand_price, "L"))
                direction = "up"
                cand_bar, cand_price = t2, highs[t2]
        else:
            if highs[t2] > cand_price:
                cand_bar, cand_price = t2, highs[t2]
            elif cand_price - lows[t2] >= k * atr[t2]:
                pivots.append(Pivot(len(pivots), cand_bar, dates[cand_bar],
                                     cand_price, "H"))
                direction = "down"
                cand_bar, cand_price = t2, lows[t2]

    # Final running candidate is always provisional (DESIGN.md §2): include
    # it as the last pivot so the parser has a right edge to work with, but
    # callers must treat it as unconfirmed (it can move every new bar).
    kind = "H" if direction == "up" else "L"
    pivots.append(Pivot(len(pivots), cand_bar, dates[cand_bar], cand_price, kind))
    return pivots


def calibrate_pivots(dates: Sequence[str], highs: Sequence[float],
                       lows: Sequence[float], closes: Sequence[float],
                       target_lo: int = 80, target_hi: int = 150,
                       atr_period: int = 14) -> tuple[float, list[Pivot]]:
    """Search k to bring the pivot count into [target_lo, target_hi],
    preferring the middle of the band. Pivot count is empirically
    non-increasing in k (validated on real + synthetic data), so a coarse
    log-spaced grid scan bracketing the target followed by local bisection
    is robust even to the rare local non-monotonicity the greedy zigzag can
    in principle introduce.
    """
    target_mid = (target_lo + target_hi) / 2

    def count_at(k: float) -> int:
        return len(zigzag(dates, highs, lows, closes, k, atr_period))

    grid = [0.05 * (1.15 ** i) for i in range(60)]  # ~0.05 .. ~500
    counts = [(k, count_at(k)) for k in grid]

    in_band = [(k, c) for k, c in counts if target_lo <= c <= target_hi]
    if in_band:
        best_k, _ = min(in_band, key=lambda kc: abs(kc[1] - target_mid))
        return best_k, zigzag(dates, highs, lows, closes, best_k, atr_period)

    # No grid point landed in-band: bracket the target and bisect between
    # the two grid points straddling it (count decreasing as k increases).
    lo_k, hi_k = grid[0], grid[-1]
    for (k1, c1), (k2, c2) in zip(counts, counts[1:]):
        if c1 >= target_mid >= c2:
            lo_k, hi_k = k1, k2
            break
    else:
        # Target unreachable within the grid: return nearest achievable.
        best_k, _ = min(counts, key=lambda kc: abs(kc[1] - target_mid))
        return best_k, zigzag(dates, highs, lows, closes, best_k, atr_period)

    for _ in range(25):
        mid_k = (lo_k + hi_k) / 2
        c = count_at(mid_k)
        if target_lo <= c <= target_hi:
            return mid_k, zigzag(dates, highs, lows, closes, mid_k, atr_period)
        if c > target_mid:
            lo_k = mid_k
        else:
            hi_k = mid_k

    final_k = (lo_k + hi_k) / 2
    return final_k, zigzag(dates, highs, lows, closes, final_k, atr_period)
