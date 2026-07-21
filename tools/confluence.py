#!/usr/bin/env python3
"""Confluence layer: run both engines over the cached watchlist at the 6m
horizon, bucket each symbol (cross_confirmed / duel / v1_only / v2_only /
both_refuse), compute target-confluence zones, and emit one digest with each
name's bias, kill level(s) and confluence zone.

Usage:  py -3 tools/confluence.py [SYM1 SYM2 ...] [--refresh]
Writes: output/confluence/<date>.md (+ <date>.jsonl full-report cache;
        reruns reuse the cache unless --refresh).
"""

from __future__ import annotations

import functools
import json
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from elliott.data import CACHE_DIR, fetch_ohlcv
from elliott.horizon import run_for_horizon as v1_run
from elliott_harmonic.engine import run_for_horizon as v2_run
from bias import binding_level, confluence_zone, target_prices, v1_bias, v2_bias

HORIZON = "6m"
cached = functools.partial(fetch_ohlcv, max_age_hours=1e6)

BUCKET_ORDER = ["cross_confirmed", "duel", "v2_only", "v1_only", "both_refuse"]


def symbols_from_cache() -> list[str]:
    return sorted(f[: -len("_1d_10y.parquet")]
                  for f in os.listdir(CACHE_DIR) if f.endswith("_1d_10y.parquet"))


def run_one(sym: str) -> dict:
    row = {"symbol": sym}
    try:
        row["v1"] = v1_run(sym, HORIZON, fetcher=cached)["report"]
    except (Exception, SystemExit) as e:  # not BaseException: let KeyboardInterrupt abort the run
        row["v1"] = {"no_clean_count": True, "message": str(e)[:100]}
    try:
        row["v2"] = v2_run(sym, HORIZON, fetcher=cached)
    except (Exception, SystemExit) as e:  # noqa: BLE001
        row["v2"] = {"no_clean_count": True, "message": str(e)[:100]}
    return row


def bucketize(row: dict) -> dict:
    v1_ok = not row["v1"].get("no_clean_count", True)
    v2_ok = not row["v2"].get("no_clean_count", True)
    b1, b2 = v1_bias(row["v1"]), v2_bias(row["v2"])
    if v1_ok and v2_ok:
        bucket = "cross_confirmed" if b1 == b2 else "duel"
    elif v1_ok:
        bucket = "v1_only"
    elif v2_ok:
        bucket = "v2_only"
    else:
        bucket = "both_refuse"
    return {
        "bucket": bucket,
        "bias": b2 if bucket == "v2_only" else (b1 if bucket == "v1_only"
                else (b1 if b1 == b2 else None)),
        "v1_bias": b1, "v2_bias": b2,
        "v1_kill": binding_level(row["v1"]),
        "v2_kill": binding_level(row["v2"]),
        "confluence": confluence_zone(row["v1"], row["v2"]) if (v1_ok and v2_ok) else [],
    }


def _call(rep, bias_fn, engine_tag) -> str:
    if rep.get("no_clean_count", True):
        return "-"
    p = rep["preferred"]
    if engine_tag == "v1":
        return f'{p["pattern"]} {p["direction"]} -> bias {v1_bias(rep)}'
    st = "completed" if p["status"] == "completed" else f'in {p["stage"]}'
    return f'{p["direction"]} {st} (h={p["harmony"]:.2f}) -> bias {v2_bias(rep)}'


def render(rows: list[dict], today: str) -> str:
    lines = [f"# Confluence digest -- {today} (horizon {HORIZON}, both engines)",
             "",
             "Bucket order: cross_confirmed > duel > engine-only > both_refuse.",
             ""]
    for bucket in BUCKET_ORDER:
        group = [r for r in rows if r["bucket"] == bucket]
        if not group:
            continue
        lines.append(f"## {bucket} ({len(group)})")
        lines.append("")
        lines.append("| Symbol | Bias | v1 call | v2 call | Kill level(s) | Confluence |")
        lines.append("|---|---|---|---|---|---|")
        for r in sorted(group, key=lambda x: x["symbol"]):
            kills = ", ".join(f"{e} {k:,.2f}" for e, k in
                              [("v1", r["v1_kill"]), ("v2", r["v2_kill"])] if k)
            conf = "; ".join(r["confluence"]) or "-"
            lines.append(f'| {r["symbol"]} | {r["bias"] or "-"} | {_call(r["v1"], v1_bias, "v1")} '
                         f'| {_call(r["v2"], v2_bias, "v2")} | {kills or "-"} | {conf} |')
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    args = [a for a in sys.argv[1:]]
    refresh = "--refresh" in args
    syms = [a for a in args if not a.startswith("--")] or symbols_from_cache()
    today = date.today().isoformat()
    out_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "output", "confluence")
    os.makedirs(out_dir, exist_ok=True)
    jsonl_path = os.path.join(out_dir, f"{today}.jsonl")

    have = {}
    if os.path.exists(jsonl_path) and not refresh:
        with open(jsonl_path) as f:
            for line in f:
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue  # partial last line from a hard kill mid-flush
                have[r["symbol"]] = r

    with open(jsonl_path, "a") as jf:
        for sym in syms:
            if sym in have:
                continue
            row = run_one(sym)
            have[sym] = row
            jf.write(json.dumps(row) + "\n")
            jf.flush()
            b = bucketize(row)
            print(f'{sym}: {b["bucket"]} bias={b["bias"]}', flush=True)

    rows = []
    for sym in syms:
        r = dict(have[sym])
        r.update(bucketize(r))
        rows.append(r)

    md_path = os.path.join(out_dir, f"{today}.md")
    with open(md_path, "w") as f:
        f.write(render(rows, today))
    print(f"\nwrote {md_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
