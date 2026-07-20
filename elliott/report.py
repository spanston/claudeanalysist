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
    labeling at two degrees)."""
    out = []
    scheme2 = label_scheme(root.pattern)
    for idx, child in enumerate(root.children):
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
                         "degree": lw.degree, "label": lw.label})
        elif container.pattern in ("zigzag", "flat_regular", "flat_expanded") and idx == 2 and len(siblings) >= 1:
            a = siblings[0]
            a_size = abs(a.end_price - a.start_price)
            base = siblings[1].end_price
            direction = 1 if a.direction == "up" else -1
            out.append({"price": base + direction * a_size, "basis": "C = A from B extreme",
                         "degree": lw.degree, "label": lw.label})
    return out


def build_report(ticker: str, run_date: str, pivots: list[Pivot], tournament: TournamentResult,
                   pivot_k: float) -> dict:
    winner = tournament.winner
    meta = {
        "ticker": ticker, "run_date": run_date,
        "window": [pivots[0].date, pivots[-1].date] if pivots else [],
        "monowaves": len(pivots), "pivot_k": round(pivot_k, 4),
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
            "position": build_position(root),
            "invalidations": build_invalidations(root),
            "targets": build_targets(root),
        },
        "alternate": alt,
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
