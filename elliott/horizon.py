"""Horizon-adaptive degree selection: pick the analysis window so the two
degrees the engine finds are the ones relevant to a given trading horizon.

Design doc: docs/superpowers/specs/2026-07-20-horizon-adaptive-degrees-design.md

The problem: on a 10y window the degree-1 waves the parser labels span
~1-2 years each -- the wrong two degrees for a swing trader holding 3-12
months. The pivot budget is fixed at 80-150 monowaves, so the *time* size
of a degree-1 wave scales with the window length; which window yields
horizon-sized degree-1 waves is therefore a search problem, solved here in
closed loop:

  1. run the normal pipeline on the last W bars,
  2. measure the realized median duration of the winning root's *closed*
     degree-1 components (the open right-edge child is truncated by
     definition and excluded),
  3. rescale W by horizon/measured and repeat, up to MAX_ITERS runs.

Convergence is fast because d1(W) is ~linear in W at a fixed monowave
budget. The traded degree is degree 1 by design: the report's position/
invalidation/targets live on the open edge, so a swing trader acts on the
degree-1 open wave with degree 2 as context.
"""

from __future__ import annotations

import math
import re
import statistics
from datetime import date

from .anchor import run_tournament
from .data import Series, fetch_ohlcv
from .guidelines import fit_null_model
from .parser import WaveUnit, build_pattern_memo
from .pivots import calibrate_pivots, wilder_atr
from .report import build_report

# First-guess window = 8x the horizon. A degree-2 impulse has ~5 degree-1
# components, but the root need not span the whole window and components
# average more than the 5-monowave floor -- 8x is a starting point the loop
# then corrects empirically.
INITIAL_WINDOW_MULT = 8
# Below ~1y of daily bars the 80-150 monowave budget is unreachable and the
# count starves.
WINDOW_MIN_BARS = 250
MAX_ITERS = 3
# Accept the window when the realized median degree-1 duration lies within
# [0.75, 1.33]x the horizon (the median is over only 2-5 components, so the
# band must be wide).
TOL_LO, TOL_HI = 0.75, 1.33

_HORIZON_RE = re.compile(r"^(\d+)\s*([dwmy])$", re.IGNORECASE)
_UNIT_BARS = {"d": 1, "w": 5, "m": 21, "y": 252}  # bars = trading days


def parse_horizon(s: str) -> int:
    """Parse a horizon string to bars (trading days): "90d", "26w", "6m",
    "1y" -> 90 / 130 / 126 / 252. For 7-day markets (crypto) pass days.
    Raises ValueError on anything else."""
    m = _HORIZON_RE.match(s.strip())
    if not m:
        raise ValueError(
            f"invalid horizon {s!r}: use a number plus d/w/m/y, "
            f"e.g. '90d', '26w', '6m', '1y' (d=1, w=5, m=21, y=252 bars)"
        )
    n, unit = int(m.group(1)), m.group(2).lower()
    if n <= 0:
        raise ValueError(f"invalid horizon {s!r}: must be positive")
    return n * _UNIT_BARS[unit]


def closed_d1_durations(root: WaveUnit) -> list[int]:
    """Bar durations (end_bar - start_bar) of the root's *closed* degree-1
    children. The open right-edge child is excluded: it is truncated by
    definition and would understate the typical wave duration."""
    return [c.end_bar - c.start_bar for c in root.children if not c.open]


def next_window(current_bars: int, measured_median: float, target_bars: int,
                available_bars: int) -> int | None:
    """Next window to try, or None when the measured median is already
    within tolerance of the target. Ratio rescale (d1 is ~linear in window
    at a fixed monowave budget), clamped to [WINDOW_MIN_BARS, available]."""
    if measured_median <= 0:
        return None
    if TOL_LO * target_bars <= measured_median <= TOL_HI * target_bars:
        return None
    w = round(current_bars * target_bars / measured_median)
    return max(WINDOW_MIN_BARS, min(available_bars, w))


def slice_series(series: Series, bars: int) -> Series:
    """The last `bars` bars of a fetched series (bar 0 of the slice = a new
    window start; all downstream bar indices are slice-relative)."""
    return Series(
        dates=series.dates[-bars:],
        opens=series.opens[-bars:],
        highs=series.highs[-bars:],
        lows=series.lows[-bars:],
        closes=series.closes[-bars:],
        volumes=series.volumes[-bars:],
    )


def analyze_window(series: Series, ticker: str, run_date: str, k_top: int = 4) -> dict:
    """The pipeline core shared by cli.run (single fixed window) and
    run_for_horizon (refining loop): calibrate pivots, fit the null, build
    the pattern memo, run the anchor tournament, build the report."""
    pivot_k, pivots = calibrate_pivots(series.dates, series.highs, series.lows, series.closes)
    if len(pivots) < 21:
        raise SystemExit(
            f"Only {len(pivots)} monowaves in this window -- too few for a 2-degree "
            f"count (minimum pattern needs ~11-21). Try a longer window/period."
        )

    null = fit_null_model(pivots)

    atr = wilder_atr(series.highs, series.lows, series.closes)
    atr_epsilon = 0.25 * statistics.median(atr[-len(pivots) * 3:]) if atr else 0.0
    ctx = {"atr_epsilon": atr_epsilon}

    memo = build_pattern_memo(pivots, null, ctx, k=k_top)
    tournament = run_tournament(pivots, memo, null, ctx, k=k_top)

    report = build_report(ticker, run_date, pivots, tournament, pivot_k,
                          last_close=series.closes[-1] if series.closes else None,
                          data_through=series.dates[-1] if series.dates else None)
    root = tournament.winner.root if (tournament.winner and not report["no_clean_count"]) else None
    return {"report": report, "tournament": tournament, "pivots": pivots,
            "pivot_k": pivot_k, "root": root}


def run_for_horizon(ticker: str, horizon: str, period: str = "10y", k_top: int = 4,
                    run_date: str | None = None, max_iters: int = MAX_ITERS,
                    fetcher=fetch_ohlcv) -> dict:
    """Horizon mode entry point. Fetches the `period` source pool once, then
    refines the analysis window until the winning count's median closed
    degree-1 duration lands within tolerance of the parsed horizon (or a
    stop condition fires). Returns the best-fitting iteration's
    {report, pivots, root}, with a meta.horizon diagnostics block attached
    to the report. `fetcher` is injectable for tests."""
    target = parse_horizon(horizon)
    run_date = run_date or date.today().isoformat()
    series = fetcher(ticker, period=period)
    available = len(series.closes)
    if available < 21 + 14:  # ATR warm-up + parser minimum, same scale as analyze_window's check
        raise SystemExit(f"Only {available} bars of history for {ticker} -- "
                         f"too few for a 2-degree count at any horizon.")

    history_limited = INITIAL_WINDOW_MULT * target > available
    w = min(max(WINDOW_MIN_BARS, INITIAL_WINDOW_MULT * target), available)

    iterations: list[dict] = []
    best = None  # (log-distance to target, result, window, durations, median)
    fit = "unresolved"

    for _ in range(max_iters):
        try:
            res = analyze_window(slice_series(series, w), ticker, run_date, k_top=k_top)
        except SystemExit:
            # A refined (smaller) window can drop below the 21-monowave
            # parser minimum on flat data -- treat like an unmeasurable
            # result: stop, keep the best earlier iteration if any.
            iterations.append({"window_bars": w, "median_d1_bars": None,
                               "decision": "stop_too_few_pivots"})
            if best is None:
                raise
            break
        root = res["root"]
        if root is None:
            # Nothing to measure. At the first iteration this *is* the
            # answer ("no structure at your horizon's scale"); on a later
            # refinement keep the earlier, measurable result instead.
            iterations.append({"window_bars": w, "median_d1_bars": None,
                               "decision": "stop_no_clean_count"})
            if best is None:
                best = (float("inf"), res, w, [], None)
                fit = "no_clean_count"
            break

        durs = closed_d1_durations(root)
        if len(durs) < 2:
            iterations.append({"window_bars": w, "median_d1_bars": None,
                               "d1_bars": durs, "decision": "stop_unmeasurable"})
            if best is None:
                best = (float("inf"), res, w, durs, None)
            break

        med = statistics.median(durs)
        nxt = next_window(w, med, target, available)
        decision = "accept" if nxt is None else ("refine" if nxt != w else "stop_clamped")
        iterations.append({"window_bars": w, "median_d1_bars": med,
                           "d1_bars": durs, "decision": decision})

        logdist = abs(math.log(med / target))
        if best is None or logdist < best[0]:
            best = (logdist, res, w, durs, med)

        if nxt is None:
            # Accepted: within tolerance. This run is the answer, even if an
            # earlier out-of-band run happened to land marginally closer in
            # log-space -- reporting a different window than the accepted one
            # would be confusing.
            best = (logdist, res, w, durs, med)
            fit = "ok"
            break
        if nxt == w:  # clamped: wants a window beyond the available history
            fit = "history_limited"
            break
        w = nxt
    else:
        # Iteration cap hit without acceptance: keep the best-fitting run.
        if history_limited:
            fit = "history_limited"

    _, res, best_w, durs, med = best
    report = res["report"]
    report["meta"]["horizon"] = {
        "input": horizon,
        "target_bars": target,
        "window_bars": best_w,
        "degree1_durations_bars": durs,
        "degree1_median_bars": med,
        "fit": fit,
        "iterations": iterations,
    }
    if fit in ("unresolved", "history_limited"):
        msg = (f"horizon_fit_{fit}: realized median degree-1 duration "
               f"{med if med is not None else 'n/a'} bars did not settle within "
               f"[{TOL_LO}, {TOL_HI}]x the {target}-bar horizon")
        if fit == "history_limited":
            msg += f" (history limited to {available} bars)"
        report.setdefault("warnings", []).append(msg)

    return {"report": report, "pivots": res["pivots"], "root": res["root"]}
