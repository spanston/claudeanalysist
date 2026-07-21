#!/usr/bin/env python3
"""Pivot-layer diagnostics: is the calibrated monowave set structural, or
noise forced into the budget by calibration?

Usage (from repo root):  py -3 tools/diagnose_pivots.py NFLX --bars 1008

Checks, per ticker/window:
  A. count(k) curve + plateau width at the calibrated k (k-stability)
  B. leg-size stats at the calibrated k (are legs structural or marginal?)
  C. single-bar ATR spikes and their effect on the pivot set
     (standard vs winsorized-TR ATR)
  D. greedy zigzag vs offline-maximal (DESIGN.md's mandated algorithm)
  E. real count(k) vs a shuffled-returns null at the same ATR schedule
     (noise-floor test: if real sits inside the null band, the pivots at
     this k are indistinguishable from noise)
"""

from __future__ import annotations

import argparse
import math
import os
import random
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from elliott.data import fetch_ohlcv
from elliott.pivots import Pivot, calibrate_pivots, wilder_atr, zigzag


def slice_tail(series, bars):
    n = len(series.closes)
    b = min(bars, n)
    return (series.dates[-b:], series.highs[-b:], series.lows[-b:], series.closes[-b:])


def rolling_median(xs, win):
    out = []
    for i in range(len(xs)):
        lo = max(0, i - win + 1)
        out.append(statistics.median(xs[lo:i + 1]))
    return out


def true_ranges(highs, lows, closes):
    n = len(closes)
    tr = [highs[0] - lows[0]]
    for t in range(1, n):
        tr.append(max(highs[t] - lows[t],
                      abs(highs[t] - closes[t - 1]),
                      abs(lows[t] - closes[t - 1])))
    return tr


def wilder_smooth(tr, period=14):
    n = len(tr)
    if n == 0:
        return []
    atr = [0.0] * n
    warm = min(period, n)
    atr[warm - 1] = sum(tr[:warm]) / warm
    for t in range(warm, n):
        atr[t] = (atr[t - 1] * (period - 1) + tr[t]) / period
    for t in range(warm - 1):
        atr[t] = atr[warm - 1]
    return atr


def winsorized_atr(highs, lows, closes, period=14, cap_mult=3.0, med_win=63):
    """ATR with each bar's TR capped at cap_mult x rolling median TR:
    one-bar gaps/spikes stop inflating the reversal threshold for the whole
    smoothing tail."""
    tr = true_ranges(highs, lows, closes)
    med = rolling_median(tr, med_win)
    capped = [min(x, cap_mult * m) if m > 0 else x for x, m in zip(tr, med)]
    return wilder_smooth(capped, period)


def zigzag_with_atr(dates, highs, lows, closes, k, atr, warmup=14):
    """Same greedy threshold-reversal logic as elliott.pivots.zigzag but
    with a caller-supplied ATR series (for winsorized/null experiments)."""
    n = len(closes)
    if n <= warmup + 1:
        return []
    start = warmup
    cand_hi_bar, cand_hi = start, highs[start]
    cand_lo_bar, cand_lo = start, lows[start]
    direction = None
    t = start + 1
    while t < n and direction is None:
        if highs[t] > cand_hi:
            cand_hi_bar, cand_hi = t, highs[t]
        if lows[t] < cand_lo:
            cand_lo_bar, cand_lo = t, lows[t]
        if cand_hi - lows[t] >= k * atr[t]:
            direction = "down"
        elif highs[t] - cand_lo >= k * atr[t]:
            direction = "up"
        t += 1
    if direction is None:
        return []
    pivots = []
    if direction == "down":
        pivots.append(Pivot(0, cand_hi_bar, dates[cand_hi_bar], cand_hi, "H"))
        cand_bar, cand_price = cand_lo_bar, cand_lo
    else:
        pivots.append(Pivot(0, cand_lo_bar, dates[cand_lo_bar], cand_lo, "L"))
        cand_bar, cand_price = cand_hi_bar, cand_hi
    for t2 in range(t, n):
        if direction == "down":
            if lows[t2] < cand_price:
                cand_bar, cand_price = t2, lows[t2]
            elif highs[t2] - cand_price >= k * atr[t2]:
                pivots.append(Pivot(len(pivots), cand_bar, dates[cand_bar], cand_price, "L"))
                direction = "up"
                cand_bar, cand_price = t2, highs[t2]
        else:
            if highs[t2] > cand_price:
                cand_bar, cand_price = t2, highs[t2]
            elif cand_price - lows[t2] >= k * atr[t2]:
                pivots.append(Pivot(len(pivots), cand_bar, dates[cand_bar], cand_price, "H"))
                direction = "down"
                cand_bar, cand_price = t2, lows[t2]
    kind = "H" if direction == "up" else "L"
    pivots.append(Pivot(len(pivots), cand_bar, dates[cand_bar], cand_price, kind))
    return pivots


def offline_maximal_count(highs, lows, closes, k, atr, warmup=14):
    """Longest alternating pivot subsequence with every leg >= k*ATR at the
    leg's end bar (DESIGN.md's offline-maximal, per-leg reference = end bar).
    O(n^2) DP; ties broken toward the more extreme last leg. Confirmed
    pivots only (no provisional tail)."""
    n = len(closes)
    best_hi = [0] * n   # best count of a sequence whose last pivot is a high at bar i
    best_lo = [0] * n
    for i in range(warmup, n):
        bh, bl = 1, 1
        for j in range(warmup, i):
            if best_lo[j] and highs[i] - lows[j] >= k * atr[i]:
                bh = max(bh, best_lo[j] + 1)
            if best_hi[j] and highs[j] - lows[i] >= k * atr[i]:
                bl = max(bl, best_hi[j] + 1)
        # only register if this bar's own extreme qualifies the leg
        best_hi[i], best_lo[i] = bh, bl
    return max(max(best_hi), max(best_lo))


def shuffled_null_counts(closes, atr, k, m=24, seed=7):
    """Pivot counts of synthetic paths built from the same returns in
    shuffled order, driven against the REAL ATR schedule. If the real
    pivot count sits inside this band, the zigzag at this k is measuring
    noise, not structure."""
    rets = [math.log(closes[t] / closes[t - 1]) for t in range(1, len(closes))]
    counts = []
    rng = random.Random(seed)
    for _ in range(m):
        sh = rets[:]
        rng.shuffle(sh)
        path = [closes[0]]
        for r in sh:
            path.append(path[-1] * math.exp(r))
        dates = [str(i) for i in range(len(path))]
        piv = zigzag_with_atr(dates, path, path, path, k, atr)
        counts.append(len(piv))
    return counts


def plateau_width(curve, idx):
    """Width (in grid steps) of the constant-count run containing idx."""
    n_target = curve[idx][1]
    lo = idx
    while lo > 0 and curve[lo - 1][1] == n_target:
        lo -= 1
    hi = idx
    while hi < len(curve) - 1 and curve[hi + 1][1] == n_target:
        hi += 1
    k_lo, k_hi = curve[lo][0], curve[hi][0]
    return k_lo, k_hi, hi - lo + 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tickers", nargs="+")
    ap.add_argument("--bars", type=int, default=1008)
    ap.add_argument("--period", default="10y")
    args = ap.parse_args()

    for ticker in args.tickers:
        series = fetch_ohlcv(ticker, period=args.period)
        dates, highs, lows, closes = slice_tail(series, args.bars)
        n = len(closes)
        print(f"\n=== {ticker} · last {n} bars ({dates[0]} -> {dates[-1]}) ===")

        k_cal, pivots = calibrate_pivots(dates, highs, lows, closes)
        atr = wilder_atr(highs, lows, closes)

        # A. count(k) curve + plateau at calibrated k
        ks = [0.2 * (1.08 ** i) for i in range(90)]
        curve = [(k, len(zigzag(dates, highs, lows, closes, k))) for k in ks]
        idx = min(range(len(curve)), key=lambda i: abs(curve[i][0] - k_cal))
        k_lo, k_hi, width = plateau_width(curve, idx)
        print(f"A. calibrated k={k_cal:.3f} -> {len(pivots)} pivots; "
              f"plateau k in [{k_lo:.3f}, {k_hi:.3f}] ({width} grid steps, "
              f"+{(k_hi/k_cal-1)*100:.0f}%/-{(1-k_lo/k_cal)*100:.0f}% in k)")
        near = [(k, c) for k, c in curve if 0.5 * k_cal <= k <= 2.0 * k_cal]
        print("   count(k) around calibrated k: " +
              " ".join(f"{k:.2f}:{c}" for k, c in near[::2]))

        # B. leg stats
        legs = []
        for a, b in zip(pivots, pivots[1:]):
            size = abs(b.price - a.price)
            mult = size / atr[b.bar] if atr[b.bar] > 0 else float("inf")
            legs.append((b.bar - a.bar, mult))
        durs = [d for d, _ in legs]
        mults = [m for _, m in legs]
        marginal = sum(1 for m in mults if m < k_cal + 0.5) / max(len(mults), 1)
        print(f"B. legs: n={len(legs)}, median duration {statistics.median(durs):.0f} bars, "
              f"median size {statistics.median(mults):.1f}x ATR, "
              f"{marginal:.0%} of legs within 0.5 ATR of the threshold (noise-sensitive)")

        # C. ATR spikes
        tr = true_ranges(highs, lows, closes)
        med_tr = statistics.median(tr)
        spikes = sum(1 for x in tr if x > 3 * med_tr)
        atr_w = winsorized_atr(highs, lows, closes)
        piv_w = zigzag_with_atr(dates, highs, lows, closes, k_cal, atr_w)
        bars_std = {p.bar for p in pivots}
        bars_win = {p.bar for p in piv_w}
        print(f"C. TR spikes (>3x median): {spikes} bars ({spikes/n:.1%}); "
              f"winsorized ATR at same k -> {len(piv_w)} pivots "
              f"(shared {len(bars_std & bars_win)}, only-std {len(bars_std - bars_win)}, "
              f"only-winsor {len(bars_win - bars_std)})")

        # D. greedy vs offline-maximal at calibrated k
        off = offline_maximal_count(highs, lows, closes, k_cal, atr)
        print(f"D. offline-maximal count at same k: {off} "
              f"(greedy confirmed-only: {len(pivots) - 1})")

        # E. shuffled-returns null band at calibrated k
        null_counts = shuffled_null_counts(closes, atr, k_cal)
        lo_n, med_n, hi_n = min(null_counts), statistics.median(null_counts), max(null_counts)
        verdict = ("STRUCTURAL (above null band)" if len(pivots) > hi_n
                   else "NOISE-SCALE (inside null band)")
        print(f"E. shuffled-null pivot counts at k={k_cal:.3f}: "
              f"[{lo_n}, {med_n:.0f}, {hi_n}] vs real {len(pivots)} -> {verdict}")


if __name__ == "__main__":
    sys.exit(main())
