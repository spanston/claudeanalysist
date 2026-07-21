#!/usr/bin/env python3
"""CLI entry point: `python3 -m elliott_harmonic.cli TICKER --horizon 6m`
runs the Harmonic Elliott Wave engine (engine v2) and writes a JSON report
under output/<TICKER>/. JSON-only for now (no SVG renderer in v2)."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import date

from .engine import analyze_series, run_for_horizon
from elliott.data import fetch_ohlcv


def _print_summary(report: dict) -> None:
    meta = report["meta"]
    print(f'{meta["ticker"]} [hew-v2] · daily · window {meta["window"][0]} -> {meta["window"][1]} '
          f'· {meta["monowaves"]} monowaves (k={meta["pivot_k"]})')
    hz = meta.get("horizon")
    if hz:
        print(f'horizon: {hz["input"]} ({hz["target_bars"]} bars) · window {hz["window_bars"]} bars')
    if report["no_clean_count"]:
        print()
        print("NO CLEAN COUNT")
        print(report["message"])
        return

    pref = report["preferred"]
    print()
    print(f'PREFERRED ({pref["status"]}{"" if pref["status"] == "completed" else ": " + pref["stage"]})'
          f'  harmony {pref["harmony"]}  aspects {pref["aspects"]}')
    print(f'  direction {pref["direction"]}, {pref["start"]["date"]} ({pref["start"]["price"]:,.2f})'
          f' -> {pref["end"]["date"]} ({pref["end"]["price"]:,.2f})')
    print(f'  {pref["position"]["text_en"]}')
    for w, wd in pref["waves"].items():
        print(f'  {w}: {wd}')
    for tgt in pref["targets"]:
        if "zone" in tgt:
            print(f'  Target ({tgt["label"]}): {tgt["zone"][0]:,.2f} - {tgt["zone"][1]:,.2f}  [{tgt["basis"]}]')
        else:
            print(f'  Target ({tgt["label"]}): {tgt["price"]:,.2f}  [{tgt["basis"]}]')
    for inv in pref["invalidations"]:
        marker = "<-- binding" if inv["binding"] else ""
        print(f'  Invalidation ({inv["label"]}): {inv["price"]:,.2f}  {inv["rule"]} {marker}')
    for alt in report["alternates"]:
        print(f'ALTERNATE: {alt["direction"]} {alt["status"]} '
              f'{alt["start"]["date"]} -> {alt["end"]["date"]}, harmony {alt["harmony"]}')
    for w in report.get("warnings", []):
        print(f'  ! {w}')


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Harmonic Elliott Wave engine (v2)")
    parser.add_argument("ticker", help="Yahoo Finance ticker, e.g. NFLX")
    parser.add_argument("--period", default="10y",
                          help="Yahoo range string (default: 10y; source pool for the window)")
    parser.add_argument("--horizon", default="6m", metavar="H",
                          help="target holding period, e.g. '3m', '6m', '1y' (default: 6m). "
                               "Window = 8x horizon bars, clamped to available history.")
    parser.add_argument("--json", dest="out_json", default=None,
                          help="write JSON report to this path (default: output/<TICKER>/<TICKER>_hew_<tag>.json)")
    args = parser.parse_args(argv)

    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", args.ticker)
    tag = f"h{re.sub(r'[^A-Za-z0-9]+', '', args.horizon)}" if args.horizon else args.period
    out_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "output", safe)
    os.makedirs(out_dir, exist_ok=True)
    if args.out_json is None:
        args.out_json = os.path.join(out_dir, f"{safe}_hew_{tag}.json")

    report = run_for_horizon(args.ticker, args.horizon, period=args.period,
                              run_date=date.today().isoformat())
    with open(args.out_json, "w") as f:
        json.dump(report, f, indent=2)
    print(f"report: {args.out_json}")
    _print_summary(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
