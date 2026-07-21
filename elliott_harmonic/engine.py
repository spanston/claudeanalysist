"""Engine v2 orchestration: window selection, pivot calibration, candidate
enumeration, scoring, and report construction (targets / invalidations /
position) for the Harmonic Elliott Wave engine.

Reuses elliott's data, pivots and horizon helpers; the analytical core is
fractals.py + score.py. Mirrors elliott.horizon.analyze_window's role.
"""

from __future__ import annotations

from datetime import date

from elliott.data import Series, fetch_ohlcv
from elliott.horizon import parse_horizon, slice_series
from elliott.pivots import calibrate_pivots

from . import ratios as R
from .fractals import Fractal, enumerate_fractals, wave_lengths
from .score import pick_best

# Pivot budget for the marker method: a HEW fractal is 11-19 legs, so ~30-70
# monowaves over the window gives a-b-c granularity without v1's noise floor.
PIVOT_LO, PIVOT_HI = 30, 70
# First-guess window = 8x the horizon (same heuristic as v1; single pass,
# no refinement loop -- the HEW reading is far less window-sensitive because
# candidates are ratio-gated, not budget-gated).
WINDOW_MULT = 8
WINDOW_MIN_BARS = 250
# Refuse when the best candidate's harmony falls below this floor.
HARMONY_FLOOR = 0.40


def _fmt_price(x: float) -> float:
    return round(x, 2)


def _wave_report(fr: Fractal, pivots, L: dict) -> dict:
    p = pivots

    def pv(idx):
        return {"date": p[idx].date, "price": _fmt_price(p[idx].price)}

    waves = {
        "i": {"span": (pv(fr.start), pv(fr.end_i)), "len": round(L["i"], 2),
              "retr_ii": round(L["ii"] / L["i"], 3)},
        "ii": {"span": (pv(fr.end_i), pv(fr.end_ii)), "legs": fr.c2},
    }
    if "iii" in L:
        waves["iii"] = {"span": (pv(fr.end_ii), pv(fr.end_iii)),
                        "len": round(L["iii"], 2),
                        "r3": round(L["iii"] / L["i"], 3),
                        "retr_b3": round(L["b3"] / L["a3"], 3),
                        "c_over_a": round(L["c3"] / L["a3"], 3)}
    if "iv" in L:
        waves["iv"] = {"span": (pv(fr.end_iii), pv(fr.end_iv)), "legs": fr.c4,
                       "retr_iv": round(L["iv"] / L["iii"], 3)}
    if "v" in L:
        waves["v"] = {"span": (pv(fr.end_iv), pv(fr.end_v)),
                      "len": round(L["v"], 2),
                      "r5": round(L["v"] / (L["i"] + L["iii"]), 3),
                      "c_over_a": round(L["c5"] / L["a5"], 3)}
    return waves


def _targets_and_invalidations(fr: Fractal, pivots, L: dict) -> tuple[list, list]:
    d = 1 if fr.direction == "up" else -1
    p = pivots
    targets: list[dict] = []
    invalidations: list[dict] = []

    def beyond(price, ref):
        return d * (price - ref) > 0.01 * abs(ref)

    if not fr.complete:
        if fr.stage == "iii":
            # Proof level + next cluster projections for (iii).
            proof = p[fr.end_ii].price + d * R.W3_MIN * L["i"]
            if beyond(proof, p[fr.realized_end].price):
                targets.append({"label": "(iii) 176.4% proof level",
                                "price": _fmt_price(proof), "basis": "rule 6 minimum"})
            seen = set()
            for cl in R.W3_CLUSTERS:
                price = p[fr.end_ii].price + d * cl * L["i"]
                if price <= 0:
                    continue  # projection beyond a zero price is not tradeable
                if beyond(price, p[fr.realized_end].price) and cl not in seen:
                    targets.append({"label": f"(iii) {cl * 100:.1f}% cluster",
                                    "price": _fmt_price(price),
                                    "basis": "|(i)| x cluster from (ii) extreme"})
                    seen.add(cl)
                if len(targets) >= 4:
                    break
            invalidations.append({"label": "low of (ii)" if d > 0 else "high of (ii)",
                                  "price": _fmt_price(p[fr.end_ii].price),
                                  "rule": "rule 1 ratchet: (ii) extreme is the binding support",
                                  "binding": True})
        elif fr.stage == "iv":
            # Alternation-derived (iv) zone, capped above the (b)-of-(iii) barrier.
            r2 = L["ii"] / L["i"]
            cap = d * (p[fr.end_iii].price - p[fr.b3_end].price) / L["iii"]
            lo_r = max(0.05, R.ALT_ACCEPT[0] - r2)
            hi_r = min(R.ALT_ACCEPT[1] - r2, 0.98 * cap)
            if hi_r > lo_r:
                z0 = p[fr.end_iii].price - d * hi_r * L["iii"]
                z1 = p[fr.end_iii].price - d * lo_r * L["iii"]
                targets.append({"label": "(iv) alternation zone",
                                "zone": [_fmt_price(min(z0, z1)), _fmt_price(max(z0, z1))],
                                "basis": f"(ii)+(iv) sum in {R.ALT_ACCEPT}, capped by (b) of (iii)"})
            invalidations.append({"label": "(b) of (iii) extreme",
                                  "price": _fmt_price(p[fr.b3_end].price),
                                  "rule": "rule 4: (iv) must not breach (b) of (iii)",
                                  "binding": True})
        else:  # stage "v"
            base = L["i"] + L["iii"]
            shown = 0
            for r in R.V_RATIOS:
                price = p[fr.end_iv].price + d * r * base
                if beyond(price, p[fr.realized_end].price):
                    targets.append({"label": f"(v) {r * 100:.1f}% of (i)+(iii)",
                                    "price": _fmt_price(price),
                                    "basis": "|(i)+(iii)| x ratio from (iv) extreme"})
                    shown += 1
                if shown >= 3:
                    break
            price = p[fr.end_iv].price + d * R.V_OF_I * L["i"]
            if beyond(price, p[fr.realized_end].price):
                targets.append({"label": "(v) 223.6% of (i)",
                                "price": _fmt_price(price), "basis": "same-degree projection"})
            invalidations.append({"label": "low of (iv)" if d > 0 else "high of (iv)",
                                  "price": _fmt_price(p[fr.end_iv].price),
                                  "rule": "rule 4 ratchet: (iv) extreme is the binding support",
                                  "binding": True})
    else:
        # Completed fractal: aftermath targets per the book's reversal map.
        b5_lo = min(p[fr.end_iv + 1].price, p[fr.b5_end].price)
        b5_hi = max(p[fr.end_iv + 1].price, p[fr.b5_end].price)
        targets.append({"label": "span of (b) of (v)",
                        "zone": [_fmt_price(b5_lo), _fmt_price(b5_hi)],
                        "basis": "first reversal after (v) targets the (b)-of-(v) span"})
        targets.append({"label": "prior (iv) extreme",
                        "price": _fmt_price(p[fr.end_iv].price),
                        "basis": "first/second reversal after (v) reaches the prior (iv)"})
        invalidations.append({"label": "(v) extreme",
                              "price": _fmt_price(p[fr.end_v].price),
                              "rule": "a new extreme beyond completion falsifies the reversal reading",
                              "binding": True})
    return targets, invalidations


def _position_text(fr: Fractal, pivots) -> str:
    p = pivots
    if fr.complete:
        tail = p[fr.end_v].date
        return (f"Five-wave {fr.direction} fractal complete at {tail} "
                f"({_fmt_price(p[fr.end_v].price)}); correction/aftermath expected "
                f"toward the (b)-of-(v) span and prior (iv).")
    leg = {"iii": "wave (iii)", "iv": "wave (iv)", "v": "wave (v)"}[fr.stage]
    return (f"In {leg} of a {fr.direction} five-wave fractal "
            f"(started {p[fr.start].date} at {_fmt_price(p[fr.start].price)}).")


def analyze_series(series: Series, ticker: str, run_date: str,
                    horizon: str | None = None,
                    pivot_band: tuple[int, int] = (PIVOT_LO, PIVOT_HI),
                    harmony_floor: float = HARMONY_FLOOR) -> dict:
    """Run the HEW pipeline on a daily series. Returns the report dict."""
    window_bars = len(series.closes)
    hz_meta = None
    if horizon is not None:
        target = parse_horizon(horizon)
        window_bars = min(max(WINDOW_MIN_BARS, WINDOW_MULT * target), len(series.closes))
        series = slice_series(series, window_bars)
        hz_meta = {"input": horizon, "target_bars": target,
                   "window_bars": window_bars, "fit": "fixed-8x"}

    pivot_k, pivots = calibrate_pivots(series.dates, series.highs, series.lows,
                                        series.closes,
                                        target_lo=pivot_band[0], target_hi=pivot_band[1])

    report: dict = {
        "meta": {
            "ticker": ticker,
            "engine": "hew-v2",
            "window": [series.dates[0], series.dates[-1]],
            "monowaves": len(pivots),
            "pivot_k": round(pivot_k, 4),
            "run_date": run_date,
            "last_close": _fmt_price(series.closes[-1]),
        },
        "no_clean_count": True,
        "message": "",
        "preferred": None,
        "alternates": [],
        "warnings": [],
    }
    if hz_meta:
        report["meta"]["horizon"] = hz_meta
    if pivots and pivots[-1].bar == len(series.closes) - 1:
        report["warnings"].append("right-edge pivot is provisional (can move with new bars)")

    if len(pivots) < 12:
        report["message"] = (f"Only {len(pivots)} monowaves in this window -- too few "
                             f"for a HEW five-wave fractal (needs >= 11 legs).")
        return report

    candidates = enumerate_fractals(pivots)
    best, ranked = pick_best(candidates, pivots)

    def _entry(fr: Fractal, sc: dict) -> dict:
        L = wave_lengths(fr, pivots)
        targets, invalidations = _targets_and_invalidations(fr, pivots, L)
        return {
            "direction": fr.direction,
            "status": "completed" if fr.complete else "in_progress",
            "stage": None if fr.complete else fr.stage,
            "harmony": sc["harmony"],
            "aspects": sc["aspects"],
            "penalties": sc["penalties"],
            "start": {"date": pivots[fr.start].date,
                      "price": _fmt_price(pivots[fr.start].price)},
            "end": {"date": pivots[fr.realized_end].date,
                    "price": _fmt_price(pivots[fr.realized_end].price)},
            "waves": _wave_report(fr, pivots, L),
            "position": {"text_en": _position_text(fr, pivots)},
            "targets": targets,
            "invalidations": invalidations,
        }

    if best is None:
        report["message"] = ("No HEW five-wave fractal survives the six hard rules "
                             f"({len(candidates)} structural candidates tried). "
                             "Honest refusal.")
        return report

    best_sc = next(sc for fr, sc in ranked if fr is best)
    if best_sc["harmony"] < harmony_floor:
        report["message"] = (f"Best HEW candidate scores {best_sc['harmony']:.2f} "
                             f"< {harmony_floor} harmony floor -- structure present "
                             "but ratios do not confirm. Honest refusal.")
        report["best_candidate"] = _entry(best, best_sc)
        return report

    report["no_clean_count"] = False
    report["preferred"] = _entry(best, best_sc)
    seen = {(best.direction, best.start, best.end_ii, best.realized_end, best.stage)}
    for fr, sc in ranked:
        if fr is best:
            continue
        if sc["harmony"] < harmony_floor:
            continue
        # Candidates differing only in the hypothetical (iv) leg count (or in
        # nothing at all) are the same market story -- report each once.
        key = (fr.direction, fr.start, fr.end_ii, fr.realized_end, fr.stage)
        if key in seen:
            continue
        seen.add(key)
        report["alternates"].append(_entry(fr, sc))
        if len(report["alternates"]) >= 3:
            break
    return report


def run_for_horizon(ticker: str, horizon: str, period: str = "10y",
                     run_date: str | None = None, fetcher=fetch_ohlcv) -> dict:
    """CLI/batch entry point: fetch (cached) daily data, slice the horizon
    window, analyze. `fetcher` injectable for tests/batch cache control."""
    run_date = run_date or date.today().isoformat()
    series = fetcher(ticker, period=period)
    return analyze_series(series, ticker, run_date, horizon=horizon)
