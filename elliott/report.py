"""Report generation: JSON (position/invalidation/targets/alternate) and a
dependency-free labeled SVG chart. DESIGN.md §7.

Degree names are kept relative ("degree 2"/"degree 1") rather than
absolute Elliott degree names (Primary, Intermediate, ...): an engine that
auto-sized its own analysis window has no way to know it found Primary
rather than Minor (DESIGN.md §7, correcting v1's overclaim). Circled vs
parenthesized notation is used purely typographically to distinguish the
two degrees on the chart, the way a hand count would.
"""

from __future__ import annotations

import html
import math
from dataclasses import dataclass

from .anchor import TournamentResult
from .grammar import is_five_pattern
from .parser import WaveUnit
from .pivots import Pivot

IMPULSE_LABELS = ["1", "2", "3", "4", "5"]
CORRECTIVE_3_LABELS = ["A", "B", "C"]
TRIANGLE_LABELS = ["A", "B", "C", "D", "E"]
COMBO_LABELS = ["W", "X", "Y", "X", "Z"]

# Circled Unicode glyphs (Enclosed Alphanumerics, U+2460-24E9) render as
# missing-character boxes under several common renderers -- confirmed by
# rasterizing real output during testing, for both digits and letters, not
# just the combination-pattern W/X/Y/Z. Degree is distinguished purely
# typographically instead (font-size and color in the SVG, parentheses in
# text), which is verified to work everywhere.


def label_scheme(pattern_name: str) -> list[str]:
    if pattern_name in ("impulse", "diagonal_leading", "diagonal_ending"):
        return IMPULSE_LABELS
    if pattern_name == "zigzag" or pattern_name.startswith("flat"):
        return CORRECTIVE_3_LABELS
    if pattern_name.startswith("triangle"):
        return TRIANGLE_LABELS
    return COMBO_LABELS


def label_for(base: str, degree: int) -> str:
    return base if degree == 2 else f"({base})"


@dataclass
class LabeledWave:
    node: WaveUnit
    label: str
    degree: int
    path: tuple[str, ...]


def walk_labels(root: WaveUnit) -> list[LabeledWave]:
    """Flatten the tree into degree-2 and degree-1 labeled waves (raw
    monowave leaves are not individually labeled -- DESIGN.md caps
    labeling at two degrees). For a reversal reading, the tail is the
    first wave of the NEXT degree-2 pattern: it is labeled from its own
    pattern's scheme with a prime (e.g. A'), not as a spurious extra
    component of the completed pattern."""
    out = []
    scheme2 = label_scheme(root.pattern)
    tail_idx = len(root.children) - 1 if root.reversal else -1
    for idx, child in enumerate(root.children):
        if idx == tail_idx:
            # the reversal tail: first wave of the NEXT degree-2 pattern,
            # labeled from its own scheme with a prime, not as a spurious
            # extra component of the completed pattern. A bare (pattern-
            # less) tail is a reversal too young to have structure yet.
            base2 = "?'" if child.pattern is None else label_scheme(child.pattern)[0] + "'"
        else:
            base2 = scheme2[idx] if idx < len(scheme2) else str(idx + 1)
        lbl2 = label_for(base2, 2)
        out.append(LabeledWave(child, lbl2, 2, (lbl2,)))
        if child.pattern is not None and child.children:
            scheme1 = label_scheme(child.pattern)
            for j, grand in enumerate(child.children):
                base1 = scheme1[j] if j < len(scheme1) else str(j + 1)
                lbl1 = label_for(base1, 1)
                out.append(LabeledWave(grand, lbl1, 1, (lbl2, lbl1)))
    return out


def open_edge_path(root: WaveUnit) -> list[LabeledWave]:
    """The labeled waves lying on the open (right-edge, in-progress) path,
    outermost first -- what the 'position' line describes."""
    labeled = walk_labels(root)
    return [lw for lw in labeled if lw.node.open]


def _fmt_price(p: float) -> str:
    return f"{p:,.2f}" if p < 1000 else f"{p:,.0f}"


def build_position(root: WaveUnit) -> dict:
    edge = open_edge_path(root)
    path = [lw.label for lw in edge]
    if root.reversal:
        tail = root.children[-1]
        dir_sv = "nedåt" if tail.direction == "down" else "uppåt"
        tail_name = tail.pattern or "counter-move"
        tail_name_sv = "motvåg" if tail.pattern is None else tail.pattern
        young = "" if tail.pattern else " (too young to structure)"
        text_en = (f"Degree 2 {root.pattern} complete at {_fmt_price(tail.start_price)}; "
                    f"degree 1 {tail_name} ({tail.direction}) underway{young}")
        text_sv = (f"Grad 2 {root.pattern} avslutad vid {_fmt_price(tail.start_price)}; "
                    f"grad 1 {tail_name_sv} ({dir_sv}) pågår")
        return {"path": path, "text_en": text_en, "text_sv": text_sv}
    if not path:
        text_en = f"{root.pattern} complete at {_fmt_price(root.end_price)}"
        text_sv = f"{root.pattern} avslutad vid {_fmt_price(root.end_price)}"
    elif len(edge) == 1:
        text_en = f"Degree 2 {edge[0].label} in progress ({root.pattern})"
        text_sv = f"Grad 2 {edge[0].label} pågår ({root.pattern})"
    else:
        text_en = (f"Degree 2 {edge[0].label} in progress; within it, "
                    f"degree 1 {edge[1].label} unfolding ({edge[0].node.pattern})")
        text_sv = (f"Grad 2 {edge[0].label} pågår; inom den utvecklas "
                    f"grad 1 {edge[1].label} ({edge[0].node.pattern})")
    return {"path": path, "text_en": text_en, "text_sv": text_sv}


def build_invalidations(root: WaveUnit) -> list[dict]:
    """Tightest hard-rule bound on each open degree (DESIGN.md §7).

    Covered: impulse/diagonal wave 4 (must not overlap wave 1) and wave 2
    (must not fully retrace wave 1); zigzag/flat wave B (must not fully
    retrace -- or, for a flat, exceed 2.618x -- wave A). Not covered: an
    in-progress wave C of a zigzag/flat/triangle has no comparably clean
    hard-rule invalidation level in this grammar (a zigzag's C is not
    length-bounded against A), and triangle/combination interior waves
    aren't handled -- a documented v1 gap, not a silent one. When the open
    wave is one of these uncovered cases, no invalidation is reported for
    it; callers should treat that as 'not yet available', not 'none
    exists'."""
    out = []
    edge = open_edge_path(root)
    for lw in edge:
        node = lw.node
        # find this node's pattern context (its parent) to compute the bound
        container = root if lw.degree == 2 else next(
            (c for c in root.children if node in c.children), None
        )
        if container is None:
            continue
        siblings = container.children
        idx = siblings.index(node) if node in siblings else -1
        if is_five_pattern(container.pattern) and idx == 3 and len(siblings) >= 1:
            price = siblings[0].end_price
            rule = "wave 4 may not overlap wave 1's territory"
        elif is_five_pattern(container.pattern) and idx == 1 and len(siblings) >= 1:
            price = siblings[0].start_price
            rule = "wave 2 may not fully retrace wave 1"
        elif container.pattern in ("zigzag", "flat_regular", "flat_expanded", "flat_running") and idx == 1:
            a = siblings[0]
            if container.pattern == "zigzag":
                price, rule = a.start_price, "wave B may not fully retrace wave A"
            else:
                price = a.start_price + (a.start_price - a.end_price) * 1.618
                rule = "wave B beyond 2.618x wave A disqualifies this flat"
        else:
            continue
        out.append({"price": price, "degree": lw.degree, "rule": rule, "label": lw.label})
    if root.reversal and root.children[-1].pattern is None:
        # A bare-tail reversal reading's own falsifier (enforced in
        # parser._reversal_readings): a new extreme beyond the completion
        # point kills the completed reading. Emitting it also resolves the
        # no_invalidation_available warning for this case (observed on MU).
        out.append({"price": root.children[-2].end_price, "degree": 2,
                    "rule": "a new extreme beyond the completion point falsifies "
                            "the completed reading",
                    "label": "?'"})
    out.sort(key=lambda d: abs(d["price"] - root.end_price))
    for i, d in enumerate(out):
        d["binding"] = (i == 0)
    return out


def build_targets(root: WaveUnit) -> list[dict]:
    """Fibonacci projections for the open wave's likely completion."""
    out = []
    edge = open_edge_path(root)
    for lw in edge:
        node = lw.node
        container = root if lw.degree == 2 else next(
            (c for c in root.children if node in c.children), None
        )
        if container is None:
            continue
        siblings = container.children
        idx = siblings.index(node) if node in siblings else -1
        if is_five_pattern(container.pattern) and idx == 4 and len(siblings) >= 3:
            w1, w3 = siblings[0], siblings[2]
            w1_size = abs(w1.end_price - w1.start_price)
            base = siblings[3].end_price  # wave 4 low/high
            direction = 1 if w1.direction == "up" else -1
            out.append({"price": base + direction * w1_size, "basis": "W5 = W1 from W4 extreme",
                         "degree": lw.degree, "label": lw.label,
                         "direction": "up" if direction > 0 else "down"})
        elif container.pattern in ("zigzag", "flat_regular", "flat_expanded") and idx == 2 and len(siblings) >= 1:
            a = siblings[0]
            a_size = abs(a.end_price - a.start_price)
            base = siblings[1].end_price
            direction = 1 if a.direction == "up" else -1
            out.append({"price": base + direction * a_size, "basis": "C = A from B extreme",
                         "degree": lw.degree, "label": lw.label,
                         "direction": "up" if direction > 0 else "down"})
    return out


def build_warnings(root: WaveUnit, tournament: TournamentResult, invalidations: list[dict],
                     targets: list[dict], last_close: float | None, meta: dict) -> list[str]:
    """Honesty flags for the report consumer (review v1.1): situations where
    the headline count needs an explicit caveat rather than silent omission."""
    out = []
    edge = open_edge_path(root)
    if edge and not invalidations:
        labels = "/".join(lw.label for lw in edge)
        out.append(f"no_invalidation_available: open wave {labels} has no hard-rule "
                   "invalidation in this grammar (documented gap, report.py)")
    data_through, run_date = meta.get("data_through"), meta.get("run_date")
    if data_through and run_date and data_through < run_date:
        out.append(f"stale_data: price data ends {data_through}, report run {run_date}")
    if last_close:
        for t in targets:
            # compare on the target's own side: a degree-1 target can point
            # AGAINST the root (e.g. (C) of a wave-4 zigzag inside an up
            # impulse), so keying on root.direction cries overshoot over a
            # level price never reached (observed on BTC-USD).
            overshot = (t["direction"] == "up" and last_close > t["price"]) or \
                       (t["direction"] == "down" and last_close < t["price"])
            if overshot:
                out.append(f"target_overshoot: last close {last_close:,.2f} is already beyond "
                           f"the {t['label']} projection of {t['price']:,.2f}")
    runner_up = tournament.winner.roots[1] if len(tournament.winner.roots) > 1 else None
    if runner_up is not None and (tournament.winner.score - runner_up.total_ll) < 1.0:
        out.append(f"near_tie_alternate: same-anchor {runner_up.pattern} "
                   f"({runner_up.direction}) is within 1 nat of the preferred count")
    return out


def build_report(ticker: str, run_date: str, pivots: list[Pivot], tournament: TournamentResult,
                   pivot_k: float, last_close: float | None = None,
                   data_through: str | None = None,
                   volumes: list[float] | None = None,
                   atr_last: float | None = None) -> dict:
    """`volumes` (bar-aligned) and `atr_last` enrich the report without
    touching scores: relative volume at the completion point of a reversal
    reading (volume confirmation is the standard TA cross-check) and
    ATR-banded zones around levels (levels are zones, not lines)."""
    winner = tournament.winner
    meta = {
        "ticker": ticker, "run_date": run_date,
        "window": [pivots[0].date, pivots[-1].date] if pivots else [],
        "monowaves": len(pivots), "pivot_k": round(pivot_k, 4),
        "last_close": last_close,
        "data_through": data_through or (pivots[-1].date if pivots else None),
        # the zigzag's final candidate pivot is always provisional
        # (pivots.py): the right edge can re-pivot with each new bar, and
        # with it every open-wave reading in this report
        "right_edge_provisional": True,
    }
    if tournament.no_clean_count or winner is None or winner.root is None:
        return {
            "meta": meta,
            "no_clean_count": True,
            "best_score": round(tournament.margin, 3) if tournament.margin != float("-inf") else None,
            "message": ("Price action does not resolve into a coherent Elliott structure "
                         "at this degree; no count is reported."),
            "anchors_considered": [
                {"date": r.date, "score": (round(r.score, 3) if r.score != float("-inf") else None)}
                for r in tournament.candidates
            ],
        }

    root = winner.root

    def _alt_dict(anchor_date: str, node: WaveUnit, score: float, same_anchor: bool) -> dict:
        return {
            "anchor_date": anchor_date, "pattern": node.pattern,
            "score": round(score, 3), "direction": node.direction,
            "span": [pivots[node.i].date, pivots[node.j].date],
            "same_anchor": same_anchor,
        }

    # Alternate selection, diversity by market implication (DESIGN.md §7).
    # Prefer a genuinely-different reading at the SAME anchor from the
    # winner's own root k-best list -- this is where the classic "pattern
    # just completed vs larger-degree reversal just began" ambiguity lives
    # (DESIGN.md §4) -- and only then fall back to other anchors' winners.
    alt = None
    same_anchor_roots = [r for r in winner.roots if r is not root]
    diff_dir = [r for r in same_anchor_roots if r.direction != root.direction]
    diff_pat = [r for r in same_anchor_roots if r.pattern != root.pattern]
    pick = diff_dir[0] if diff_dir else (diff_pat[0] if diff_pat else None)
    if pick is not None:
        alt = _alt_dict(winner.date, pick, pick.total_ll, True)
    else:
        alternates = [r for r in tournament.candidates if r is not winner and r.root is not None]
        if alternates:
            opp_direction = [r for r in alternates if r.root.direction != root.direction]
            r0 = opp_direction[0] if opp_direction else alternates[0]
            alt = _alt_dict(r0.date, r0.root, r0.score, False)

    # Relative confidence: softmax over the winning anchor's root k-best
    # list (DESIGN.md §7) -- the preferred count vs its same-span
    # competitors, not across different anchors.
    root_scores = [r.total_ll for r in winner.roots] or [winner.score]
    top = max(root_scores)
    denom = sum(math.exp(s - top) for s in root_scores)
    relative_confidence = math.exp(winner.score - top) / denom if denom > 0 else 1.0

    invalidations = build_invalidations(root)
    targets = build_targets(root)
    if last_close:
        for d in invalidations + targets:
            d["pct_from_last"] = round((d["price"] / last_close - 1.0) * 100.0, 1)
    if atr_last:
        for d in invalidations + targets:
            d["zone"] = [round(d["price"] - 0.5 * atr_last, 2),
                         round(d["price"] + 0.5 * atr_last, 2)]

    def _relvol(bar: int) -> float | None:
        if not volumes or bar <= 0:
            return None
        base = [v for v in volumes[max(0, bar - 50):bar] if v > 0]
        if not base or not volumes[bar]:
            return None
        return round(volumes[bar] / (sum(base) / len(base)), 2)

    warnings = build_warnings(root, tournament, invalidations, targets, last_close, meta)
    if volumes:
        rv = _relvol(pivots[-1].bar)
        if rv is not None:
            meta["relvol_50"] = rv

    reversal_tail = None
    if root.reversal:
        tail = root.children[-1]
        reversal_tail = {
            "pattern": tail.pattern, "direction": tail.direction,
            "structured": tail.pattern is not None,
            "span": [pivots[tail.i].date, pivots[tail.j].date],
            "completed_at": {"date": pivots[tail.i].date, "price": pivots[tail.i].price},
        }
        rv_c = _relvol(pivots[tail.i].bar)
        if rv_c is not None:
            reversal_tail["relvol_at_completion"] = rv_c
            if rv_c < 0.85:
                warnings.append(f"low_volume_at_completion: {rv_c}x 50-bar mean at "
                                f"{pivots[tail.i].date} -- the top is not volume-confirmed")

    return {
        "meta": meta,
        "no_clean_count": False,
        "anchor": {"date": winner.date, "index": winner.anchor},
        "preferred": {
            "pattern": root.pattern,
            "structure_strength": round(root.total_ll, 3),
            "relative_confidence": round(relative_confidence, 3),
            "direction": root.direction,
            "span": [pivots[root.i].date, pivots[root.j].date],
            "completed": root.reversal,
            "reversal_tail": reversal_tail,
            "position": build_position(root),
            "invalidations": invalidations,
            "targets": targets,
        },
        "alternate": alt,
        "warnings": warnings,
        "anchors_considered": [
            {"date": r.date, "score": (round(r.score, 3) if r.score != float("-inf") else None)}
            for r in tournament.candidates
        ],
    }


# ---------------------------------------------------------------------------
# SVG chart -- dependency-free, matches tools/plot_zones.py's approach.
# ---------------------------------------------------------------------------

W, H = 1000, 560
ML, MR, MT, MB = 64, 40, 40, 36
COL = {
    "grid": "#e2e8f0", "axis": "#475569", "text": "#1a202c", "muted": "#718096",
    "zig_up": "#2f855a", "zig_dn": "#c53030", "deg2": "#1a202c", "deg1": "#718096",
    "inval": "#b91c1c", "target": "#2563eb", "open": "#d97706",
}


def _esc(s) -> str:
    return html.escape(str(s))


def render_svg(pivots: list[Pivot], report: dict) -> str:
    prices = [p.price for p in pivots]
    if report.get("preferred"):
        for inv in report["preferred"].get("invalidations", []):
            prices.append(inv["price"])
        for tgt in report["preferred"].get("targets", []):
            prices.append(tgt["price"])
    pmin, pmax = min(prices), max(prices)
    pad = (pmax - pmin) * 0.06 or 1
    pmin, pmax = pmin - pad, pmax + pad

    plot_l, plot_r = ML, W - MR
    plot_t, plot_b = MT, H - MB
    n = len(pivots)

    def xf(i: int) -> float:
        return plot_l + (plot_r - plot_l) * (i / max(n - 1, 1))

    def yf(price: float) -> float:
        return plot_b - (plot_b - plot_t) * ((price - pmin) / (pmax - pmin))

    parts = []
    parts.append(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" '
                  f'font-family="system-ui,-apple-system,sans-serif">')
    parts.append(f'<rect width="{W}" height="{H}" fill="white"/>')

    # gridlines + price axis labels
    for frac in (0, 0.25, 0.5, 0.75, 1.0):
        price = pmin + (pmax - pmin) * frac
        y = yf(price)
        parts.append(f'<line x1="{plot_l}" y1="{y:.1f}" x2="{plot_r}" y2="{y:.1f}" '
                      f'stroke="{COL["grid"]}" stroke-width="1"/>')
        parts.append(f'<text x="{plot_r + 6}" y="{y+4:.1f}" font-size="11" fill="{COL["muted"]}">'
                      f'{_fmt_price(price)}</text>')

    # zigzag polyline, colored by leg direction
    for i in range(n - 1):
        x1, y1 = xf(i), yf(pivots[i].price)
        x2, y2 = xf(i + 1), yf(pivots[i + 1].price)
        color = COL["zig_up"] if pivots[i + 1].price > pivots[i].price else COL["zig_dn"]
        parts.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
                      f'stroke="{color}" stroke-width="1.6"/>')

    pref = report.get("preferred")

    for i, p in enumerate(pivots):
        x, y = xf(i), yf(p.price)
        r = 2.2
        parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r}" fill="{COL["axis"]}"/>')

    if pref:
        for inv in pref.get("invalidations", []):
            y = yf(inv["price"])
            parts.append(f'<line x1="{plot_l}" y1="{y:.1f}" x2="{plot_r}" y2="{y:.1f}" '
                          f'stroke="{COL["inval"]}" stroke-width="1.4" stroke-dasharray="6,4"/>')
            parts.append(f'<text x="{plot_l+4}" y="{y-4:.1f}" font-size="10" fill="{COL["inval"]}">'
                          f'invalidation {_fmt_price(inv["price"])}</text>')
        for tgt in pref.get("targets", []):
            y = yf(tgt["price"])
            parts.append(f'<line x1="{plot_l}" y1="{y:.1f}" x2="{plot_r}" y2="{y:.1f}" '
                          f'stroke="{COL["target"]}" stroke-width="1.2" stroke-dasharray="3,4"/>')
            parts.append(f'<text x="{plot_l+4}" y="{y-4:.1f}" font-size="10" fill="{COL["target"]}">'
                          f'target {_fmt_price(tgt["price"])} ({_esc(tgt["basis"])})</text>')

    title = f'{report["meta"]["ticker"]} — Elliott Wave count'
    if pref:
        title += f' — {pref["pattern"]} ({pref["direction"]})'
    parts.append(f'<text x="{plot_l}" y="24" font-size="16" font-weight="600" fill="{COL["text"]}">'
                  f'{_esc(title)}</text>')
    if pref:
        parts.append(f'<text x="{plot_l}" y="{H-10}" font-size="11" fill="{COL["muted"]}">'
                      f'{_esc(pref["position"]["text_en"])}</text>')

    parts.append('</svg>')
    return "\n".join(parts)


def render_svg_labeled(pivots: list[Pivot], root: WaveUnit | None, report: dict) -> str:
    """Full chart with every degree-1/degree-2 wave labeled at its
    terminal pivot, not just the open edge."""
    svg = render_svg(pivots, report)
    if root is None:
        return svg
    prices = [p.price for p in pivots]
    pmin, pmax = min(prices), max(prices)
    pad = (pmax - pmin) * 0.06 or 1
    pmin, pmax = pmin - pad, pmax + pad
    plot_l, plot_r, plot_t, plot_b = ML, W - MR, MT, H - MB
    n = len(pivots)

    def xf(i: int) -> float:
        return plot_l + (plot_r - plot_l) * (i / max(n - 1, 1))

    def yf(price: float) -> float:
        return plot_b - (plot_b - plot_t) * ((price - pmin) / (pmax - pmin))

    labels_svg = []
    for lw in walk_labels(root):
        x, y = xf(lw.node.j), yf(lw.node.end_price)
        size = 13 if lw.degree == 2 else 10
        color = COL["deg2"] if lw.degree == 2 else COL["deg1"]
        is_peak = pivots[lw.node.j].kind == "H"
        # A pattern's last child always shares its own endpoint, so degree-2
        # and degree-1 labels commonly land on the same pixel -- push
        # degree-2 further out so the pair stacks legibly instead of
        # overlapping.
        offset = 20 if lw.degree == 2 else 8
        dy = -offset if is_peak else offset + size
        style = "italic" if lw.node.open else "normal"
        labels_svg.append(
            f'<text x="{x:.1f}" y="{y+dy:.1f}" font-size="{size}" font-style="{style}" '
            f'fill="{color}" text-anchor="middle">{_esc(lw.label)}</text>'
        )
    return svg.replace("</svg>", "\n".join(labels_svg) + "\n</svg>")
