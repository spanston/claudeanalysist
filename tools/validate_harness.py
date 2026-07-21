#!/usr/bin/env python3
"""Validation harness: backtest both engines by replaying history.

For each cached symbol, truncate the cached daily series at several historical
as-of points, run v1 (elliott) and v2 (elliott_harmonic) on data available up
to that point (identical 8x-horizon windows for both), record their calls, then
score the outcome over the following H bars with the full series:

  target_first : any in-bias target touched before the binding level breaks (1.0)
  breach_first : binding invalidation broken before any target            (0.0)
  invalid_binding : binding already violated at the as-of close -- marked,
                 excluded from the means (score None)
  open         : neither within H bars -- directional drift at H scores
                 0.5 (agrees) / 0.25 (flat, |drift| < 1 ATR) / 0.0 (against)
  refusal      : no call; max favorable excursion over H recorded in ATRs
                 (>= 6 ATR = notable missed move, opportunity cost)

Usage:  py -3 tools/validate_harness.py [SYM1 SYM2 ...]
Writes: output/validation/<date>.md and <date>.jsonl (resume-safe).
"""

from __future__ import annotations

import functools
import json
import os
import statistics
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from elliott.data import CACHE_DIR, Series, fetch_ohlcv
from elliott.horizon import analyze_window as v1_analyze
from elliott.pivots import wilder_atr
from elliott_harmonic.engine import analyze_series as v2_analyze
from bias import binding_level, target_prices, v1_bias, v2_bias

HORIZON_BARS = 126          # 6m
WINDOW_BARS = 8 * HORIZON_BARS
OUTCOME_H = 63              # ~3m forward outcome window
AS_OF_OFFSETS = (127, 190, 253, 316)  # bars back from the data end
FLAT_ATR = 1.0              # |drift| < 1 ATR at H counts as flat
MISS_ATR = 6.0              # refusal with >= 6 ATR favorable excursion = notable miss

cached = functools.partial(fetch_ohlcv, max_age_hours=1e6)


def symbols_from_cache() -> list[str]:
    return sorted(f[: -len("_1d_10y.parquet")]
                  for f in os.listdir(CACHE_DIR) if f.endswith("_1d_10y.parquet"))


def slice_to(series: Series, end: int, window: int) -> Series:
    lo = max(0, end - window)
    return Series(dates=series.dates[lo:end], opens=series.opens[lo:end],
                  highs=series.highs[lo:end], lows=series.lows[lo:end],
                  closes=series.closes[lo:end], volumes=series.volumes[lo:end])


def run_engines(series: Series, ticker: str, as_of: str) -> dict:
    out = {}
    try:
        out["v1"] = v1_analyze(series, ticker, as_of)["report"]
    except (Exception, SystemExit) as e:  # not BaseException: let KeyboardInterrupt abort the run
        out["v1"] = {"no_clean_count": True, "message": str(e)[:100]}
    try:
        out["v2"] = v2_analyze(series, ticker, as_of, horizon=None)
    except (Exception, SystemExit) as e:  # noqa: BLE001
        out["v2"] = {"no_clean_count": True, "message": str(e)[:100]}
    return out


def pick_target(targets: list[tuple], bias: str, ref: float) -> float | None:
    """First plain-price target in the bias direction from `ref`."""
    prices = [p for p, _ in targets if isinstance(p, (int, float))]
    if bias == "up":
        prices = [p for p in prices if p > ref]
        return min(prices) if prices else None
    prices = [p for p in prices if p < ref]
    return max(prices) if prices else None


def score_call(bias: str | None, binding: float | None, target: float | None,
                series: Series, t: int, atr_t: float) -> dict:
    """Outcome of one engine call over bars t+1..t+OUTCOME_H."""
    n = len(series.closes)
    end = min(n, t + 1 + OUTCOME_H)
    ref = series.closes[t]
    if bias is None:
        # Refusal: measure the biggest excursion either way, in ATRs.
        hi = max(series.highs[t + 1:end], default=ref)
        lo = min(series.lows[t + 1:end], default=ref)
        mfe = max(hi - ref, ref - lo) / atr_t if atr_t else 0.0
        return {"verdict": "refusal", "score": None, "mfe_atr": round(mfe, 2),
                "missed": mfe >= MISS_ATR}

    if binding is not None and ((bias == "up" and binding >= ref) or
                                (bias == "down" and binding <= ref)):
        # The binding level is already violated at the as-of close, so a
        # breach is guaranteed from bar 1: scoring it would book a free
        # loss and skew the call means / harmony-floor calibration. Mark
        # the call invalid and exclude it (score None) instead.
        return {"verdict": "invalid_binding", "score": None}

    tgt_bar = breach_bar = None
    for b in range(t + 1, end):
        if tgt_bar is None and target is not None:
            if (bias == "up" and series.highs[b] >= target) or \
               (bias == "down" and series.lows[b] <= target):
                tgt_bar = b
        if breach_bar is None and binding is not None:
            if (bias == "up" and series.lows[b] < binding) or \
               (bias == "down" and series.highs[b] > binding):
                breach_bar = b
        if tgt_bar and breach_bar:
            break

    if tgt_bar and (not breach_bar or tgt_bar < breach_bar):
        return {"verdict": "target_first", "score": 1.0, "bars": tgt_bar - t}
    if breach_bar and (not tgt_bar or breach_bar < tgt_bar):
        return {"verdict": "breach_first", "score": 0.0, "bars": breach_bar - t}

    drift = series.closes[end - 1] - ref
    agrees = (bias == "up" and drift > 0) or (bias == "down" and drift < 0)
    flat = abs(drift) < FLAT_ATR * atr_t
    score = 0.25 if flat else (0.5 if agrees else 0.0)
    return {"verdict": "open", "score": score, "drift_atr": round(drift / atr_t, 2) if atr_t else None}


def main() -> int:
    syms = sys.argv[1:] or symbols_from_cache()
    today = date.today().isoformat()
    out_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "output", "validation")
    os.makedirs(out_dir, exist_ok=True)
    jsonl_path = os.path.join(out_dir, f"{today}.jsonl")

    done = set()
    records = []
    if os.path.exists(jsonl_path):
        with open(jsonl_path) as f:
            for line in f:
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue  # partial last line from a hard kill mid-flush
                done.add((r["symbol"], r["as_of"]))
                records.append(r)

    with open(jsonl_path, "a") as jf:
        for sym in syms:
            series = cached(sym, period="10y")
            n = len(series.closes)
            atr = wilder_atr(series.highs, series.lows, series.closes)
            for off in AS_OF_OFFSETS:
                t = n - off
                if t < 300:
                    continue  # need window + warm-up behind the as-of point
                as_of = series.dates[t]
                if (sym, as_of) in done:
                    continue
                windowed = slice_to(series, t + 1, WINDOW_BARS)
                reps = run_engines(windowed, sym, as_of)
                for eng, rep in reps.items():
                    bias = v1_bias(rep) if eng == "v1" else v2_bias(rep)
                    binding = binding_level(rep)
                    ref = windowed.closes[-1]
                    target = pick_target(target_prices(rep), bias, ref) if bias else None
                    strength = None
                    if not rep.get("no_clean_count", True) and rep.get("preferred"):
                        p = rep["preferred"]
                        strength = p.get("harmony") if eng == "v2" else p.get("structure_strength")
                    rec = {"symbol": sym, "as_of": as_of, "engine": eng,
                           "status": "count" if bias else "refusal", "bias": bias,
                           "binding": binding, "target": target, "strength": strength}
                    rec.update(score_call(bias, binding, target, series, t, atr[t]))
                    records.append(rec)
                    jf.write(json.dumps(rec) + "\n")
                jf.flush()
                print(f"{sym} {as_of} done", flush=True)

    md = render(records, syms, today)
    md_path = os.path.join(out_dir, f"{today}.md")
    with open(md_path, "w") as f:
        f.write(md)
    print(f"\nwrote {md_path}")
    return 0


def render(records: list[dict], syms: list[str], today: str) -> str:
    lines = [f"# Validation harness -- {today}",
             "",
             f"Backtest: {len(syms)} symbols x {len(AS_OF_OFFSETS)} as-of points "
             f"(offsets {AS_OF_OFFSETS} bars), outcome over {OUTCOME_H} bars. "
             "Score: target_first 1.0 / breach_first 0.0 / open 0.5|0.25|0.0.",
             ""]
    for eng in ("v1", "v2"):
        recs = [r for r in records if r["engine"] == eng]
        calls = [r for r in recs if r["status"] == "count"]
        refs = [r for r in recs if r["status"] == "refusal"]
        scored = [r for r in calls if r["score"] is not None]
        hits = [r for r in calls if r["verdict"] == "target_first"]
        brch = [r for r in calls if r["verdict"] == "breach_first"]
        inv = [r for r in calls if r["verdict"] == "invalid_binding"]
        misses = [r for r in refs if r.get("missed")]
        avg = statistics.mean(r["score"] for r in scored) if scored else None
        lines += [f"## {eng}",
                  f"- calls: {len(calls)}, refusals: {len(refs)} "
                  f"(missed moves >= {MISS_ATR} ATR: {len(misses)}), "
                  f"invalid_binding (excluded): {len(inv)}",
                  f"- target_first: {len(hits)} ({len(hits) / max(1, len(calls)):.0%}), "
                  f"breach_first: {len(brch)} ({len(brch) / max(1, len(calls)):.0%})",
                  f"- mean call score: {avg:.3f}" if avg is not None else "- mean call score: n/a",
                  ""]
        if eng == "v2":
            lines.append("### v2 by harmony bucket (informs the refusal floor)")
            lines.append("")
            lines.append("| bucket | calls | target_first | breach_first | mean score |")
            lines.append("|---|---|---|---|---|")
            for lo, hi in ((0.0, 0.5), (0.5, 0.65), (0.65, 1.01)):
                b = [r for r in calls if r["strength"] is not None and lo <= r["strength"] < hi]
                if not b:
                    continue
                bh = sum(1 for r in b if r["verdict"] == "target_first")
                bb = sum(1 for r in b if r["verdict"] == "breach_first")
                b_scores = [r["score"] for r in b if r["score"] is not None]
                bm = f"{statistics.mean(b_scores):.3f}" if b_scores else "n/a"
                lines.append(f"| {lo:.2f}-{hi:.2f} | {len(b)} | {bh} | {bb} | {bm} |")
            lines.append("")

    lines.append("## Per-call log (counts only)")
    lines.append("")
    lines.append("| Symbol | As-of | Engine | Bias | Binding | Target | Verdict | Score | Strength |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for r in records:
        if r["status"] != "count":
            continue
        fmt = lambda x: f"{x:,.2f}" if isinstance(x, (int, float)) else "-"
        lines.append(f'| {r["symbol"]} | {r["as_of"]} | {r["engine"]} | {r["bias"]} '
                     f'| {fmt(r["binding"])} | {fmt(r["target"])} | {r["verdict"]} '
                     f'| {r["score"]} | {r["strength"] and round(r["strength"], 2)} |')
    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    sys.exit(main())
