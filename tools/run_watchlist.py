#!/usr/bin/env python3
"""Watchlist runner: keep a set of symbols' candle caches current and run
the horizon-adaptive Elliott workflow over them.

Per symbol: update_ohlcv() probes the last few days and downloads new
candles only when the cache is behind (full refetch on gaps or
split/adjustment basis changes); then the standard horizon analysis runs
and writes output/<SYM>/<SYM>_h<horizon>.{json,svg}. Finally an aggregate
markdown digest is written to output/watchlist/<today>.md.

Usage (from repo root):
    py -3 tools/run_watchlist.py                      # default watchlist
    py -3 tools/run_watchlist.py MU NVDA --horizon 3m
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from elliott.cli import run
from elliott.data import update_ohlcv

DEFAULT_WATCHLIST = ["MU", "NVDA", "AAPL", "SNDK", "TSLA",
                     "AMD", "MSFT", "INTC", "AMZN", "META"]

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _fmt(p: float) -> str:
    return f"{p:,.2f}" if p < 1000 else f"{p:,.0f}"


def _report_lines(report: dict) -> list[str]:
    meta = report["meta"]
    hz = meta.get("horizon") or {}
    lines = [f'- window {meta["window"][0]} → {meta["window"][1]} · {meta["monowaves"]} monowaves'
             + (f' · horizon {hz.get("input")} fit **{hz.get("fit")}**'
                f' (window {hz.get("window_bars")} bars'
                + (f', degree-1 median {hz.get("degree1_median_bars")} bars'
                   if hz.get("degree1_median_bars") is not None else "")
                + ')'
                if hz else "")]
    if report["no_clean_count"]:
        best = report.get("best_score")
        lines.append(f'- **NO CLEAN COUNT**' + (f' (best {best})' if best is not None else ""))
        return lines
    pref = report["preferred"]
    lines.append(f'- **{pref["pattern"]} ({pref["direction"]})** · strength {pref["structure_strength"]}'
                 f' · confidence {pref["relative_confidence"]}'
                 + (' · **completed**' if pref.get("completed") else ""))
    lines.append(f'- {pref["position"]["text_en"]}')
    for inv in pref["invalidations"]:
        lines.append(f'- Invalidation {inv["label"]} (degree {inv["degree"]}): '
                     f'**{_fmt(inv["price"])}**'
                     + (' ← binding' if inv.get("binding") else ""))
    for tgt in pref["targets"]:
        lines.append(f'- Target {tgt["label"]}: {_fmt(tgt["price"])} [{tgt["basis"]}]')
    if report["alternate"]:
        alt = report["alternate"]
        lines.append(f'- Alternate: {alt["pattern"]} ({alt["direction"]}), score {alt["score"]}')
    for w in report.get("warnings", []):
        lines.append(f'- ⚠ {w}')
    return lines


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("symbols", nargs="*", default=DEFAULT_WATCHLIST,
                    help=f"tickers (default: {' '.join(DEFAULT_WATCHLIST)})")
    ap.add_argument("--horizon", default="6m", help="trading horizon (default: 6m)")
    ap.add_argument("--period", default="10y", help="source pool to slice from (default: 10y)")
    args = ap.parse_args(argv)

    today = date.today().isoformat()
    sections, rows = [], []
    for sym in args.symbols:
        sym = sym.upper()
        print(f"[{sym}] updating cache...", flush=True)
        try:
            series, status = update_ohlcv(sym, period=args.period)
        except (Exception, SystemExit) as e:  # network/data failure: note and continue
            rows.append((sym, "data error", str(e)))
            sections.append(f'## {sym}\n\n- ⚠ data update failed: {e}')
            continue
        print(f"[{sym}] {status['refreshed']} (+{status['added']} candles, through {status['through']}); "
              f"analyzing...", flush=True)

        safe = re.sub(r"[^A-Za-z0-9._-]+", "_", sym)
        tag = f"h{re.sub(r'[^A-Za-z0-9]+', '', args.horizon)}"
        out_dir = os.path.join(REPO_ROOT, "output", safe)
        os.makedirs(out_dir, exist_ok=True)
        try:
            report = run(sym, period=args.period, horizon=args.horizon,
                          out_json=os.path.join(out_dir, f"{safe}_{tag}.json"),
                          out_svg=os.path.join(out_dir, f"{safe}_{tag}.svg"))
        except (Exception, SystemExit) as e:  # SystemExit = engine refusal-by-abort (e.g. too few bars)
            rows.append((sym, "analysis error", str(e)))
            sections.append(f'## {sym}\n\n- ⚠ analysis failed: {e}')
            continue

        if report["no_clean_count"]:
            verdict = "NO CLEAN COUNT"
        else:
            pref = report["preferred"]
            verdict = f'{pref["pattern"]} ({pref["direction"]}): {pref["position"]["text_en"]}'
        fit = (report["meta"].get("horizon") or {}).get("fit", "?")
        rows.append((sym, fit, verdict))
        sections.append(f'## {sym}\n\n' + "\n".join(_report_lines(report)))

    out_md_dir = os.path.join(REPO_ROOT, "output", "watchlist")
    os.makedirs(out_md_dir, exist_ok=True)
    out_md = os.path.join(out_md_dir, f"{today}.md")
    header = (f"# Elliott watchlist — {today}\n\n"
              f"Horizon-adaptive 2-degree counts (`--horizon {args.horizon}`). "
              "Levels are computed from Yahoo daily candles; verify against your chart before trading.\n")
    with open(out_md, "w", encoding="utf-8") as f:
        f.write(header + "\n" + "\n\n".join(sections) + "\n")

    print()
    for sym, fit, verdict in rows:
        print(f"{sym:6s} [{fit:15s}] {verdict}")
    print(f"\ndigest: {out_md}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
