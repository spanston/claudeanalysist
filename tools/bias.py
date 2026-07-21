"""Shared report -> forward-bias mapping for the two engines, used by
tools/confluence.py and tools/validate_harness.py.

Bias is the engine's actionable call at the right edge:
  v1: "X underway" in the position text -> that direction; a bare "complete"
      -> opposite of the counted structure's direction (correction expected).
  v2: in_progress -> the fractal's direction; completed -> opposite (aftermath).
"""

from __future__ import annotations

import re


def v1_bias(report: dict) -> str | None:
    """'up' | 'down' | None (refusal) for a v1 (elliott) report.

    v1 position phrasings: "X underway" / "Y in progress" / "(C) unfolding"
    all mean the counted structure is still active -> bias = its direction.
    A bare "complete" -> opposite (correction expected). Fallback: direction.
    """
    if report.get("no_clean_count", True) or not report.get("preferred"):
        return None
    pref = report["preferred"]
    text = pref.get("position", {}).get("text_en", "")
    d = pref.get("direction")
    m = re.search(r"\((down|up)\)\s+underway", text)
    if m:
        return m.group(1)
    if "underway" in text or "in progress" in text or "unfolding" in text:
        return d
    if "complete" in text:
        return {"up": "down", "down": "up"}.get(d)
    return d


def v2_bias(report: dict) -> str | None:
    """'up' | 'down' | None for a v2 (elliott_harmonic) report."""
    if report.get("no_clean_count", True) or not report.get("preferred"):
        return None
    pref = report["preferred"]
    d = pref.get("direction")
    if pref.get("status") == "completed":
        return {"up": "down", "down": "up"}.get(d)
    # in_progress fractal: trend direction. Corrective reading: the corrective
    # move itself is the active one.
    return d


def binding_level(report: dict) -> float | None:
    """The binding invalidation price, either engine's report shape."""
    if report.get("no_clean_count", True) or not report.get("preferred"):
        return None
    for inv in report["preferred"].get("invalidations", []):
        if inv.get("binding"):
            return inv.get("price")
    return None


def target_prices(report: dict) -> list[tuple[float | tuple, str]]:
    """Flat list of (price_or_zone, label) from either engine's targets."""
    if report.get("no_clean_count", True) or not report.get("preferred"):
        return []
    out = []
    for t in report["preferred"].get("targets", []):
        if "price" in t:
            out.append((t["price"], t["label"]))
        elif "zone" in t:
            out.append((tuple(t["zone"]), t["label"]))
    return out


def confluence_zone(v1_rep: dict, v2_rep: dict,
                     tol: float = 0.025) -> list[str]:
    """Human-readable overlaps between v1 and v2 target sets: v1 price within
    `tol` of a v2 price, or inside a v2 zone."""
    hits = []
    v1_t = [p for p, _ in target_prices(v1_rep) if isinstance(p, (int, float))]
    for price, label in target_prices(v2_rep):
        if isinstance(price, tuple):
            lo, hi = price
            for p1 in v1_t:
                if lo <= p1 <= hi:
                    hits.append(f"{p1:,.2f} inside v2 zone {lo:,.2f}-{hi:,.2f} ({label})")
        else:
            for p1 in v1_t:
                if abs(p1 - price) / price <= tol:
                    hits.append(f"{price:,.2f} ~= v1 {p1:,.2f} ({label})")
    return hits
