#!/usr/bin/env python3
"""CLI entry point: `python3 -m elliott.cli TICKER` runs the full pipeline
fully automatically -- fetch, calibrate pivots, parse, run the anchor
tournament, and write a JSON report + labeled SVG chart. See DESIGN.md."""

from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys
from datetime import date

from .anchor import run_tournament
from .data import fetch_ohlcv
from .guidelines import fit_null_model
from .parser import build_pattern_memo
from .pivots import calibrate_pivots, wilder_atr
from .report import build_report, render_svg_labeled


def run(ticker: str, period: str = "10y", k_top: int = 4,
         out_json: str | None = None, out_svg: str | None = None) -> dict:
    series = fetch_ohlcv(ticker, period=period)
    pivot_k, pivots = calibrate_pivots(series.dates, series.highs, series.lows, series.closes)
    if len(pivots) < 21:
        raise SystemExit(
            f"Only {len(pivots)} monowaves in this window -- too few for a 2-degree "
            f"count (minimum pattern needs ~11-21). Try a longer `period`."
        )

    null = fit_null_model(pivots)

    atr = wilder_atr(series.highs, series.lows, series.closes)
    atr_epsilon = 0.25 * statistics.median(atr[-len(pivots) * 3:]) if atr else 0.0
    ctx = {"atr_epsilon": atr_epsilon}

    memo = build_pattern_memo(pivots, null, ctx, k=k_top)
    tournament = run_tournament(pivots, memo, null, ctx, k=k_top)

    run_date = date.today().isoformat()
    report = build_report(ticker, run_date, pivots, tournament, pivot_k)

    if out_json:
        with open(out_json, "w") as f:
            json.dump(report, f, indent=2)

    root = tournament.winner.root if (tournament.winner and not report["no_clean_count"]) else None
    svg = render_svg_labeled(pivots, root, report)
    if out_svg:
        with open(out_svg, "w") as f:
            f.write(svg)

    return report


def _print_summary(report: dict) -> None:
    meta = report["meta"]
    print(f'{meta["ticker"]} · daily · window {meta["window"][0]} -> {meta["window"][1]} '
          f'· {meta["monowaves"]} monowaves')
    if report["no_clean_count"]:
        print()
        print("NO CLEAN COUNT" + (f' (best {report["best_score"]})' if report.get("best_score") is not None else ""))
        print(report["message"])
        return

    pref = report["preferred"]
    print(f'anchor: {report["anchor"]["date"]}')
    print()
    print(f'PREFERRED COUNT                      structure strength {pref["structure_strength"]}'
          f'  (relative confidence {pref["relative_confidence"]})')
    print(f'  {pref["pattern"]} ({pref["direction"]}), span {pref["span"][0]} -> {pref["span"][1]}')
    print(f'  Position: {pref["position"]["text_en"]}')
    for inv in pref["invalidations"]:
        marker = "<-- binding" if inv["binding"] else ""
        print(f'  Invalidation ({inv["label"]}, degree {inv["degree"]}): {inv["price"]:,.2f}  '
              f'{inv["rule"]} {marker}')
    for tgt in pref["targets"]:
        print(f'  Target ({tgt["label"]}): {tgt["price"]:,.2f}  [{tgt["basis"]}]')

    if report["alternate"]:
        alt = report["alternate"]
        print()
        print(f'ALTERNATE: {alt["pattern"]} ({alt["direction"]}) from anchor {alt["anchor_date"]}, '
              f'score {alt["score"]}')


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Elliott Wave engine (2-degree, fully automatic)")
    parser.add_argument("ticker", help="Yahoo Finance ticker, e.g. BTC-USD")
    parser.add_argument("--period", default="10y",
                          help="Yahoo range string (default: 10y; avoid 'max', see data.py)")
    parser.add_argument("--k", type=int, default=4, help="top-k retained per parse cell (default: 4)")
    parser.add_argument("--json", dest="out_json", default=None,
                          help="write JSON report to this path (default: output/<TICKER>/<TICKER>_<period>.json)")
    parser.add_argument("--svg", dest="out_svg", default=None,
                          help="write labeled SVG chart to this path (default: output/<TICKER>/<TICKER>_<period>.svg)")
    args = parser.parse_args(argv)

    # Repo-structured outputs (output/<TICKER>/ per ticker, per period) so
    # every run's report and chart are kept, not just printed.
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", args.ticker)
    out_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "output", safe)
    os.makedirs(out_dir, exist_ok=True)
    if args.out_json is None:
        args.out_json = os.path.join(out_dir, f"{safe}_{args.period}.json")
    if args.out_svg is None:
        args.out_svg = os.path.join(out_dir, f"{safe}_{args.period}.svg")

    report = run(args.ticker, period=args.period, k_top=args.k,
                  out_json=args.out_json, out_svg=args.out_svg)
    print(f"report: {args.out_json}")
    print(f"chart:  {args.out_svg}")
    _print_summary(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
