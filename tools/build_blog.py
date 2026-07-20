#!/usr/bin/env python3
"""Build the Wave Log blog's data from the engine's structured outputs.

Scans output/<TICKER>/<TICKER>_<period>.{json,svg}, copies each report +
chart pair into blog/public/posts/, and writes blog/public/posts/manifest.json
with everything the UI needs for both the index and the post pages (reports
are a few KB each, so the full report is embedded in the manifest).

Usage: python tools/build_blog.py   (from the repo root)
"""

from __future__ import annotations

import json
import os
import re
import shutil

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(REPO_ROOT, "output")
POSTS_DIR = os.path.join(REPO_ROOT, "blog", "public", "posts")


def build() -> list[dict]:
    os.makedirs(POSTS_DIR, exist_ok=True)
    posts = []
    for ticker in sorted(os.listdir(OUTPUT_DIR)):
        ticker_dir = os.path.join(OUTPUT_DIR, ticker)
        if not os.path.isdir(ticker_dir):
            continue
        for fname in sorted(os.listdir(ticker_dir)):
            if not fname.endswith(".json"):
                continue
            base = fname[:-5]
            with open(os.path.join(ticker_dir, fname)) as f:
                report = json.load(f)
            post_id = re.sub(r"[^A-Za-z0-9._-]+", "_", base)
            shutil.copy2(os.path.join(ticker_dir, fname),
                         os.path.join(POSTS_DIR, f"{post_id}.json"))
            svg_src = os.path.join(ticker_dir, f"{base}.svg")
            has_svg = os.path.exists(svg_src)
            if has_svg:
                shutil.copy2(svg_src, os.path.join(POSTS_DIR, f"{post_id}.svg"))
            pref = report.get("preferred") or {}
            posts.append({
                "id": post_id,
                "ticker": report["meta"]["ticker"],
                "period": base.split("_", 1)[1] if "_" in base else "",
                "run_date": report["meta"]["run_date"],
                "window": report["meta"]["window"],
                "monowaves": report["meta"]["monowaves"],
                "last_close": report["meta"].get("last_close"),
                "data_through": report["meta"].get("data_through"),
                "no_clean_count": report["no_clean_count"],
                "pattern": pref.get("pattern"),
                "direction": pref.get("direction"),
                "structure_strength": pref.get("structure_strength"),
                "relative_confidence": pref.get("relative_confidence"),
                "position_en": (pref.get("position") or {}).get("text_en"),
                "best_score": report.get("best_score"),
                "warnings": report.get("warnings", []),
                "svg": f"posts/{post_id}.svg" if has_svg else None,
                "report": report,
            })
    # newest analysis first, then ticker
    posts.sort(key=lambda p: (p["run_date"], p["ticker"]), reverse=True)
    with open(os.path.join(POSTS_DIR, "manifest.json"), "w") as f:
        json.dump({"posts": posts}, f)
    return posts


if __name__ == "__main__":
    built = build()
    print(f"blog data: {len(built)} posts -> {os.path.relpath(POSTS_DIR, REPO_ROOT)}")
