#!/usr/bin/env python3
"""Compare engine v1 (classical elliott/) vs engine v2 (elliott_harmonic/)
across every cached 10y daily series, at the 6m swing horizon, and score both
against the manual verdicts from the watchlist review sessions.

Usage:  py -3 tools/compare_engines.py [SYM1 SYM2 ...]
Writes: output/compare/<date>.md and prints the table.
Incremental JSONL at output/compare/<date>.jsonl (safe to interrupt/resume --
already-computed symbols are skipped).
"""

from __future__ import annotations

import functools
import json
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from elliott.data import CACHE_DIR, fetch_ohlcv
from elliott.horizon import run_for_horizon as v1_run
from elliott_harmonic.engine import run_for_horizon as v2_run

HORIZON = "6m"
cached = functools.partial(fetch_ohlcv, max_age_hours=1e6)  # use the cache as-is

# Manual verdicts from the engine+manual watchlist reviews (batches 1-3,
# data through 2026-07-20). level = manual completion extreme / key level.
MANUAL = {
    "NFLX": {"dir": "down", "level": None, "note": "topped; exp-flat C down underway"},
    "MU": {"dir": "down", "level": 1255.0, "note": "complete 1255, young decline; 1255 binding"},
    "AAPL": {"dir": "down", "level": 334.99, "note": "complete 334.99"},
    "SNDK": {"dir": "up", "level": None, "note": "up, (C) unfolding, target ~2200"},
    "AMD": {"dir": "down", "level": 584.73, "note": "complete 584.73"},
    "ORCL": {"dir": "down", "level": 250.25, "note": "complete 250.25"},
    "STX": {"dir": "down", "level": 1145.0, "note": "complete 1145"},
    "IREN": {"dir": "down", "level": 70.71, "note": "complete 70.71"},
    "BE": {"dir": "down", "level": 351.28, "note": "complete 351.28"},
    "NVDA": {"dir": "down", "level": None, "note": "exp-flat C -> 170/129, invalidation 260.7"},
    "TSLA": {"dir": "down", "level": None, "note": "correction toward ~225"},
    "MSFT": {"dir": "down", "level": None, "note": "toward ~267"},
    "META": {"dir": "down", "level": None, "note": "holding 520-526"},
    "AVGO": {"dir": "down", "level": None, "note": "290 key"},
    "MRVL": {"dir": "down", "level": None, "note": "178-200 base or 127-142"},
    "AMAT": {"dir": "down", "level": None, "note": "bounced 513 near .382 at 516"},
    "GOOG": {"dir": "down", "level": None, "note": "334/320 then 272"},
    "PLTR": {"dir": "down", "level": None, "note": "100 then 66-71"},
    "AMZN": {"dir": None, "level": None, "note": "v1 refusal correct (w3-iv overlap)"},
    "BTC-USD": {"dir": None, "level": None, "note": "honest refusal (both)"},
    "SPCX": {"dir": None, "level": None, "note": "insufficient history (25 bars)"},
}


def symbols_from_cache() -> list[str]:
    out = []
    for f in sorted(os.listdir(CACHE_DIR)):
        if f.endswith("_1d_10y.parquet"):
            out.append(f[: -len("_1d_10y.parquet")])
    return out


def v1_summary(rep: dict) -> dict:
    if rep.get("no_clean_count", True):
        return {"status": "refusal", "message": (rep.get("message") or "")[:80]}
    pref = rep["preferred"]
    inv = next((i for i in pref["invalidations"] if i["binding"]), None)
    return {
        "status": "count",
        "pattern": pref["pattern"],
        "direction": pref["direction"],
        "span": pref["span"],
        "strength": pref["structure_strength"],
        "binding_inv": inv["price"] if inv else None,
        "first_target": pref["targets"][0]["price"] if pref["targets"] else None,
        "position": pref["position"]["text_en"][:90],
    }


def v2_summary(rep: dict) -> dict:
    if rep.get("no_clean_count", True):
        return {"status": "refusal", "message": (rep.get("message") or "")[:80]}
    pref = rep["preferred"]
    inv = next((i for i in pref["invalidations"] if i["binding"]), None)
    tgt = None
    for t in pref["targets"]:
        if "price" in t:
            tgt = t["price"]
            break
        tgt = t["zone"]
        break
    return {
        "status": "count",
        "direction": pref["direction"],
        "stage": "completed" if pref["status"] == "completed" else f"in {pref['stage']}",
        "start": f"{pref['start']['date']} @{pref['start']['price']}",
        "end": f"{pref['end']['date']} @{pref['end']['price']}",
        "harmony": pref["harmony"],
        "binding_inv": inv["price"] if inv else None,
        "first_target": tgt,
    }


def dir_agrees(engine_dir: str | None, manual_dir: str | None) -> str:
    if not engine_dir or not manual_dir:
        return "-"
    # manual "down" = topped, expecting decline; engine direction is the trend
    # direction of the counted fractal. A completed UP fractal and an
    # in-progress DOWN fractal both agree with manual "down".
    return "?"  # filled by caller with fuller context


def main() -> int:
    syms = sys.argv[1:] or symbols_from_cache()
    today = date.today().isoformat()
    out_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "output", "compare")
    os.makedirs(out_dir, exist_ok=True)
    jsonl_path = os.path.join(out_dir, f"{today}.jsonl")

    done = set()
    if os.path.exists(jsonl_path):
        with open(jsonl_path) as f:
            for line in f:
                done.add(json.loads(line)["symbol"])

    with open(jsonl_path, "a") as jf:
        for sym in syms:
            if sym in done:
                continue
            row = {"symbol": sym}
            try:
                row["v1"] = v1_summary(v1_run(sym, HORIZON, fetcher=cached)["report"])
            except BaseException as e:  # SystemExit from too-few-bars guards, etc.
                row["v1"] = {"status": "error", "message": str(e)[:100]}
            try:
                row["v2"] = v2_summary(v2_run(sym, HORIZON, fetcher=cached))
            except BaseException as e:  # noqa: BLE001
                row["v2"] = {"status": "error", "message": str(e)[:100]}
            row["manual"] = MANUAL.get(sym)
            jf.write(json.dumps(row) + "\n")
            jf.flush()
            print(f"{sym}: v1={row['v1']['status']} v2={row['v2']['status']}", flush=True)

    # Render the markdown table.
    rows = []
    with open(jsonl_path) as f:
        for line in f:
            r = json.loads(line)
            if r["symbol"] in syms:
                rows.append(r)

    def cell_v1(v):
        if v["status"] != "count":
            return v["status"]
        return f'{v["direction"]} {v["pattern"]} inv {v["binding_inv"]}'

    def cell_v2(v):
        if v["status"] != "count":
            return v["status"]
        return f'{v["direction"]} {v["stage"]} h={v["harmony"]:.2f} inv {v["binding_inv"]}'

    lines = [f"# Engine comparison v1 (classical) vs v2 (HEW) -- {today}, horizon {HORIZON}",
             "",
             "| Symbol | v1 | v2 | Manual verdict |",
             "|---|---|---|---|"]
    for r in rows:
        man = r.get("manual") or {}
        lines.append(f'| {r["symbol"]} | {cell_v1(r["v1"])} | {cell_v2(r["v2"])} '
                     f'| {man.get("dir", "?")} {man.get("note", "")} |')
    md_path = os.path.join(out_dir, f"{today}.md")
    with open(md_path, "w") as f:
        f.write("\n".join(lines) + "\n")
    print(f"\nwrote {md_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
