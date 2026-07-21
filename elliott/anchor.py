"""Anchor tournament: compare candidate starting points on a consistent
basis. DESIGN.md §6.

Implementation note (a correction found during implementation, not in
DESIGN.md as written): the design's literal formula adds an absolute
log P0(prefix) to the tree's score S(T). Working through it, that
double-counts: S(T) is built entirely from log-likelihood *ratios*
against the null (guidelines.py), so a leaf/component that carries no
named-pattern guideline contributes 0, not its absolute null cost. Adding
an explicit, absolute log P0(prefix) on top of a 0-baseline suffix isn't
an apples-to-apples split of one coherent likelihood -- it mechanically
rewards short prefixes (fewer legs to pay the lognormal Jacobian's -ln(x)
term) almost independent of how well the tree actually fits, which was
directly observable in testing (the shortest-prefix anchor won by three
orders of magnitude regardless of fit quality).

The fix: log P0(whole window) = log P0(prefix) + log P0(suffix legs) is a
constant, independent of where the anchor falls. Since S(T) already nets
out the suffix's absolute null cost via LLR guideline terms (a named
pattern's leaves score 0 unless their *ratios* fit or fail the canon), the
prefix-vs-suffix split cancels down to comparing S(T) = root.total_ll
directly across anchors -- which is also exactly what "does the extra
data length the tree explains earn its keep" means: pivots absorbed into
a leaf with no favorable guideline fit are guideline-neutral, but pivots
that distort a pattern's ratios away from its canonical proportions are
still penalized through the existing LLR terms. No separate length
normalization or prefix bookkeeping needed.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .guidelines import NullModel
from .parser import WaveUnit, build_root_candidates
from .pivots import Pivot

NO_CLEAN_COUNT_MARGIN = 3.0  # nats of net evidence the best count must beat pure chance by


def _prominence(pivots: list[Pivot], idx: int) -> float:
    price_dist = 0.0
    if idx > 0:
        price_dist = max(price_dist, abs(pivots[idx].price - pivots[idx - 1].price))
    if idx < len(pivots) - 1:
        price_dist = max(price_dist, abs(pivots[idx].price - pivots[idx + 1].price))
    time_span = 1
    if idx > 0:
        time_span = max(time_span, pivots[idx].bar - pivots[idx - 1].bar)
    if idx < len(pivots) - 1:
        time_span = max(time_span, pivots[idx + 1].bar - pivots[idx].bar)
    return price_dist * math.sqrt(time_span)


def select_anchor_candidates(pivots: list[Pivot], n_extra: int = 3,
                               max_idx: int | None = None) -> list[int]:
    """Global min, global max, plus the `n_extra` most prominent remaining
    pivots (DESIGN.md §6). `max_idx` bounds how close to the right edge a
    candidate may sit, leaving room for a valid root span."""
    n = len(pivots)
    if max_idx is None:
        max_idx = max(0, n - 20)
    eligible = list(range(min(max_idx, n - 1)))
    if not eligible:
        return [0]
    global_min = min(eligible, key=lambda i: pivots[i].price)
    global_max = max(eligible, key=lambda i: pivots[i].price)
    chosen = {global_min, global_max}
    by_prominence = sorted(eligible, key=lambda i: -_prominence(pivots, i))
    for idx in by_prominence:
        if len(chosen) >= 2 + n_extra:
            break
        chosen.add(idx)
    return sorted(chosen)


@dataclass
class AnchorResult:
    anchor: int
    date: str
    score: float          # S(best root tree) = root.total_ll; -inf if no root found
    root: WaveUnit | None
    roots: list = field(default_factory=list)  # root k-best list at this anchor, best-first
    uplift: float = 0.0   # root.total_ll minus its best child's score (see run_tournament)


@dataclass
class TournamentResult:
    candidates: list[AnchorResult]
    winner: AnchorResult | None
    no_clean_count: bool
    margin: float          # winner.score, directly (0 = indistinguishable from random walk)


def _uplift(root: WaveUnit | None) -> float:
    """How much the assembled root adds beyond its own best component:
    root.total_ll - max(child.total_ll). Positive means the two-degree
    structure explains the data better than any single component alone.
    For a reversal reading (completed root + tail), the two-degree
    structure being validated is the COMPLETED root alone, so the tail is
    excluded from both sides."""
    if root is None or not root.children:
        return 0.0
    if root.reversal:
        core = root.children[:-1]
        core_total = root.total_ll - root.children[-1].total_ll
        return core_total - max(c.total_ll for c in core)
    return root.total_ll - max(c.total_ll for c in root.children)


def run_tournament(pivots: list[Pivot], pattern_memo: dict, null: NullModel, ctx: dict,
                     k: int = 5, n_extra_anchors: int = 3,
                     margin_threshold: float = NO_CLEAN_COUNT_MARGIN) -> TournamentResult:
    n = len(pivots)
    anchor_idxs = select_anchor_candidates(pivots, n_extra=n_extra_anchors)

    results: list[AnchorResult] = []
    for a in anchor_idxs:
        roots = build_root_candidates(pattern_memo, a, n, null, ctx, k=k, pivots=pivots)
        best_root = roots[0] if roots else None
        score = best_root.total_ll if best_root is not None else float("-inf")
        uplift = _uplift(best_root) if best_root is not None else float("-inf")
        results.append(AnchorResult(anchor=a, date=pivots[a].date, score=score,
                                      root=best_root, roots=roots, uplift=uplift))

    results.sort(key=lambda r: -r.score)
    winner = results[0] if results else None
    margin = winner.score if winner else float("-inf")
    # A count must (a) beat chance by the calibrated margin AND (b) earn its
    # keep as a two-degree structure: the assembled root must add explanatory
    # power beyond its own best component. Without (b), a single lucky
    # degree-1 span plus an open tail can masquerade as a degree-2 count
    # (observed: GBM random walk scoring +10.6 via a 2-component prefix).
    no_clean = (winner is None or winner.root is None
                or margin < margin_threshold or winner.uplift <= 0.0)

    return TournamentResult(candidates=results, winner=winner, no_clean_count=no_clean, margin=margin)
