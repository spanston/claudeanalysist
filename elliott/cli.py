#!/usr/bin/env python3
"""CLI entry point: `python3 -m elliott.cli TICKER` runs the full pipeline
fully automatically -- fetch, calibrate pivots, parse, run the anchor
tournament, and write a JSON report + labeled SVG chart. See DESIGN.md."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import date

from .data import fetch_ohlcv
from .horizon import analyze_window, run_for_horizon
from .report import render_svg_labeled


def run(ticker: str, period: str = "10y", k_top: int = 4,
         out_json: str | None = None, out_svg: str | None = None,
         horizon: str | None = None) -> dict:
    run_date = date.today().isoformat()
    if horizon is not None:
        # Horizon mode: --period is only the source pool; the window is
        # refined until the count's degree-1 waves match the horizon.
        result = run_for_horizon(ticker, horizon, period=period, k_top=k_top,
                                  run_date=run_date)
    else:
        series = fetch_ohlcv(ticker, period=period)
        result = analyze_window(series, ticker, run_date, k_top=k_top)
    report, pivots, root = result["report"], result["pivots"], result["root"]

    if out_json:
        with open(out_json, "w") as f:
            json.dump(report, f, indent=2)

    svg = render_svg_labeled(pivots, root, report)
    if out_svg:
        with open(out_svg, "w") as f:
            f.write(svg)

    return report


def _print_summary(report: dict) -> None:
    meta = report["meta"]
    print(f'{meta["ticker"]} · daily · window {meta["window"][0]} -> {meta["window"][1]} '
          f'· {meta["monowaves"]} monowaves')
    hz = meta.get("horizon")
    if hz:
        print(f'horizon: {hz["input"]} ({hz["target_bars"]} bars) · window {hz["window_bars"]} bars · '
              f'degree-1 median {hz["degree1_median_bars"]} bars · fit {hz["fit"]} '
              f'({len(hz["iterations"])} iteration(s))')
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
    for w in report.get("warnings", []):
        print(f'  ! {w}')


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Elliott Wave engine (2-degree, fully automatic)")
    parser.add_argument("ticker", help="Yahoo Finance ticker, e.g. BTC-USD")
    parser.add_argument("--period", default="10y",
                          help="Yahoo range string (default: 10y; avoid 'max', see data.py). "
                               "With --horizon this is only the source pool the window is sliced from.")
    parser.add_argument("--horizon", default=None, metavar="H",
                          help="target holding period, e.g. '3m', '6m', '1y', '90d' (d/w/m/y). "
                               "The analysis window is refined until the count's degree-1 waves "
                               "match the holding period (see horizon.py).")
    parser.add_argument("--k", type=int, default=4, help="top-k retained per parse cell (default: 4)")
    parser.add_argument("--json", dest="out_json", default=None,
                          help="write JSON report to this path (default: output/<TICKER>/<TICKER>_<period>.json)")
    parser.add_argument("--svg", dest="out_svg", default=None,
                          help="write labeled SVG chart to this path (default: output/<TICKER>/<TICKER>_<period>.svg)")
    args = parser.parse_args(argv)

    # Repo-structured outputs (output/<TICKER>/ per ticker, per period) so
    # every run's report and chart are kept, not just printed.
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", args.ticker)
    tag = f"h{re.sub(r'[^A-Za-z0-9]+', '', args.horizon)}" if args.horizon else args.period
    out_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "output", safe)
    os.makedirs(out_dir, exist_ok=True)
    if args.out_json is None:
        args.out_json = os.path.join(out_dir, f"{safe}_{tag}.json")
    if args.out_svg is None:
        args.out_svg = os.path.join(out_dir, f"{safe}_{tag}.svg")

    report = run(args.ticker, period=args.period, k_top=args.k,
                  out_json=args.out_json, out_svg=args.out_svg, horizon=args.horizon)
    print(f"report: {args.out_json}")
    print(f"chart:  {args.out_svg}")
    _print_summary(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
