"""Binarized chart parser: degree-floor leaves -> degree-1 named patterns
-> degree-2 root. DESIGN.md §4.

Exactly two degrees are modeled, which collapses the general arbitrary
-depth chart-parser problem into a clean two-phase pipeline with no
recursion between phases:

  Phase 0 (leaves):   spans checked against a shape+size floor, O(1) each,
                       cached on demand. These ARE degree-1 waves' own
                       components -- degree-1 patterns never subdivide
                       further than raw monowaves.
  Phase 1 (patterns):  each of the 13 grammar patterns is assembled, from
                       every possible start pivot, via a forward prefix-DP
                       sweep over leaf components, keeping the top-K partial
                       derivations *at every reachable position* (the memo
                       key is effectively (start, position-so-far,
                       components-placed), matching DESIGN.md's binarized
                       -dotted-rule item). This produces PATTERN_MEMO for
                       every (i, j, pattern_name, open) reached, in one pass
                       per (pattern, start) -- the ~n^3 cost the feasibility
                       simulation measured as tractable.
  Phase 2 (root):      degree-2 root candidates are assembled the same way,
                       but components are drawn from the now-fully-populated
                       PATTERN_MEMO (role-gated) instead of leaves, and only
                       for the specific (anchor, right-edge) spans the
                       anchor tournament needs -- "one chart serves every
                       anchor" (DESIGN.md §4/§6).
"""

from __future__ import annotations

import heapq
import math
from dataclasses import dataclass, field
from typing import Optional

from . import grammar as G
from .guidelines import NullModel, score_guidelines
from .pivots import Pivot

MIN_LEAF = {"5": 5, "3": 3}

# DESIGN.md §4 degree floor: "a :5 child spans >=5 monowaves, a :3 child >=3
# (a triangle needs >=5)". Triangle legs get the stricter floor so a degree-1
# triangle cannot be assembled from minimal 3-monowave zigzag legs.
TRIANGLE_LEG_MIN = 5


@dataclass
class WaveUnit:
    """A completed span: either a degree-floor leaf (pattern=None) or a
    named pattern instance. Satisfies the component interface grammar.py's
    hard rules and guidelines.py's scorers expect."""

    i: int
    j: int
    pattern: Optional[str]
    start_price: float
    end_price: float
    hi: float
    lo: float
    direction: str
    n_pivots: int
    start_bar: int
    end_bar: int
    role: Optional[str] = None
    children: tuple = ()
    ll: float = 0.0          # this node's own contribution (prior + guidelines)
    total_ll: float = 0.0    # ll + sum(child.total_ll) -- flat sum over the subtree
    open: bool = False
    reversal: bool = False   # completed-root + reversal-tail reading (build_root_candidates)

    @property
    def label(self) -> str:
        return self.pattern or "leaf"


def _mk_leaf(pivots: list[Pivot], i: int, j: int) -> WaveUnit:
    span = pivots[i:j + 1]
    hi = max((p.price for p in span if p.kind == "H"), default=max(p.price for p in span))
    lo = min((p.price for p in span if p.kind == "L"), default=min(p.price for p in span))
    direction = "up" if pivots[j].price > pivots[i].price else "down"
    return WaveUnit(
        i=i, j=j, pattern=None,
        start_price=pivots[i].price, end_price=pivots[j].price,
        hi=hi, lo=lo, direction=direction, n_pivots=j - i,
        start_bar=pivots[i].bar, end_bar=pivots[j].bar,
        ll=0.0, total_ll=0.0,
    )


def leaf_shape_ok(pivots: list[Pivot], i: int, j: int, slot: str,
                    min_len: Optional[int] = None) -> bool:
    """Degree-floor sanity check (DESIGN.md §4): hard minimum size, odd
    parity (net directional move), the endpoint must be the span's own
    extreme in its net direction, and -- :5 slots only -- interior
    counter-swings must hold inside the leaf's own start ("interior
    pullbacks hold inside the right extremes"): a down impulse run
    containing a high above its start is not one wave, it is two waves
    the parser should split there. `min_len` overrides MIN_LEAF[slot]
    (triangle legs use TRIANGLE_LEG_MIN)."""
    L = j - i
    floor = min_len if min_len is not None else MIN_LEAF[slot]
    if L < floor or L % 2 == 0:
        return False
    direction = "up" if pivots[j].price > pivots[i].price else "down"
    want_kind = "H" if direction == "up" else "L"
    if pivots[j].kind != want_kind:
        return False
    # Compare against same-kind pivots *strictly inside* the span -- j must
    # itself be the extreme, not merely tie with itself trivially.
    others = [p.price for p in pivots[i + 1:j] if p.kind == want_kind]
    if others:
        if direction == "up" and pivots[j].price < max(others):
            return False
        if direction == "down" and pivots[j].price > min(others):
            return False
    # DESIGN.md §4 degree floor: the :5 check tests impulse shape --
    # "interior pullbacks hold inside the right extremes". A :5 run whose
    # counter-swings cross the run's own start is not one impulse wave.
    # (:3 corrective runs are exempt: deep first dips/rallies past the
    # start are legal corrective shape.)
    if slot == "5":
        counter = [p.price for p in pivots[i + 1:j] if p.kind != want_kind]
        if counter:
            if direction == "up" and min(counter) < pivots[i].price:
                return False
            if direction == "down" and max(counter) > pivots[i].price:
                return False
    return True


class LeafCache:
    def __init__(self, pivots: list[Pivot]):
        self.pivots = pivots
        self._cache: dict[tuple[int, int, str], Optional[WaveUnit]] = {}

    def get(self, i: int, j: int, slot: str,
              min_len: Optional[int] = None) -> Optional[WaveUnit]:
        key = (i, j, slot, min_len)
        if key not in self._cache:
            if leaf_shape_ok(self.pivots, i, j, slot, min_len=min_len):
                self._cache[key] = _mk_leaf(self.pivots, i, j)
            else:
                self._cache[key] = None
        return self._cache[key]


def _open_leaf(pivots: list[Pivot], i: int, j: int) -> WaveUnit:
    """An in-progress final component: no shape check, just the raw span
    (DESIGN.md §4: 'prefix-complete patterns at the right edge only')."""
    node = _mk_leaf(pivots, i, j)
    node.open = True
    return node


def _try_rule(rule, comps, ctx) -> bool:
    try:
        return rule(comps, ctx)
    except IndexError:
        return True  # not yet decidable with the components placed so far


def _passes_rules(spec: G.PatternSpec, comps: list, ctx: dict) -> bool:
    return all(_try_rule(r, comps, ctx) for r in spec.hard_rules)


def _reserve_bound(n: int, pos: int, c: int, n_comp: int, strict: bool) -> int:
    """Rightmost end a closed component at index c may have.
    strict (root phase): reserve remaining*3 for ALL remaining components --
    the root must genuinely partition the window into several degree-1
    children; one hot child covering the whole window plus crumbs is not a
    two-degree count (permissiveness leak, measured on the GBM seed sweep).
    non-strict (leaf phase): prefix-aware minimum -- a closed component at
    c >= 1 may be followed by just the open terminal (1 pivot); only the
    first component must leave room for a closed 2nd plus an open 3rd."""
    remaining_after = n_comp - c - 1
    if strict:
        reserve = remaining_after * MIN_LEAF["3"]
    elif remaining_after == 0:
        reserve = 0
    elif c >= 1:
        reserve = 1                       # next component may be the open terminal
    else:
        reserve = MIN_LEAF["3"] + 1       # closed 2nd + open 3rd minimum
    return n - 1 - reserve


def _assemble(spec: G.PatternSpec, comps: list[WaveUnit], role_universe: str,
              null: NullModel, open_flag: bool) -> WaveUnit:
    priors = G.GLOBAL_FIVE_PRIORS if role_universe == "5" else G.GLOBAL_THREE_PRIORS
    prior_p = priors.get(spec.name, 1e-6)
    guide = 0.0 if open_flag else score_guidelines(spec.name, comps, null)
    own_ll = math.log(max(prior_p, 1e-12)) + guide
    total_ll = own_ll + sum(c.total_ll for c in comps)
    i, j = comps[0].i, comps[-1].j
    return WaveUnit(
        i=i, j=j, pattern=spec.name,
        start_price=comps[0].start_price, end_price=comps[-1].end_price,
        hi=max(c.hi for c in comps), lo=min(c.lo for c in comps),
        direction="up" if comps[-1].end_price > comps[0].start_price else "down",
        n_pivots=j - i, start_bar=comps[0].start_bar, end_bar=comps[-1].end_bar,
        children=tuple(comps), ll=own_ll, total_ll=total_ll, open=open_flag,
    )


def _top_k(entries: list[tuple[float, list[WaveUnit]]], k: int):
    return heapq.nlargest(k, entries, key=lambda t: t[0])


def parse_pattern_from_start(
    spec: G.PatternSpec, i: int, n: int, *,
    component_kind: str,  # "leaf" | "pattern"
    leaf_cache: Optional[LeafCache] = None,
    pattern_memo: Optional[dict] = None,
    pivots: Optional[list[Pivot]] = None,
    null: NullModel, ctx: dict, k: int, allow_open: bool,
) -> dict[int, list[WaveUnit]]:
    """Forward prefix-DP sweep from a fixed start `i`. Returns, for every
    ending position j reached, the top-k completed parses of `spec`
    spanning exactly [i, j]. This is the workhorse both for degree-1
    pattern assembly (component_kind="leaf") and degree-2 root assembly
    restricted to specific spans (component_kind="pattern")."""
    n_comp = len(spec.components)
    role_universe = "5" if G.is_five_pattern(spec.name) else "3"
    # Degree floor: triangle legs need >=5 monowaves, not the generic 3
    # (DESIGN.md §4). Applies only when components are raw leaves.
    leaf_min_len = TRIANGLE_LEG_MIN if (
        component_kind == "leaf" and spec.name.startswith("triangle")) else None
    # states[pos] = top-k (score, comps) after placing all components so far
    states: dict[int, list[tuple[float, list[WaveUnit]]]] = {i: [(0.0, [])]}
    # Prefix-complete derivations (DESIGN.md §4: an impulse with waves 1-2
    # done and wave 3 UNDERWAY is a legal terminal parse): any component
    # from the 2nd onward may be the open right-edge one, ending the
    # derivation there. Without this, every count is forced to claim its
    # final component is underway -- the engine could never say "wave 3 of
    # 5 in progress" (review finding B).
    prefix: dict[int, list[tuple[float, list[WaveUnit]]]] = {}

    for c, comp in enumerate(spec.components):
        new_states: dict[int, list[tuple[float, list[WaveUnit]]]] = {}
        for pos, entries in states.items():
            max_e = min(n - 1, _reserve_bound(n, pos, c, n_comp,
                                              strict=component_kind == "pattern"))
            if max_e <= pos:
                continue
            for score, comps in entries:
                for e in range(pos + 1, max_e + 1):
                    open_ok = allow_open and e == n - 1 and c >= 1
                    units = _candidate_units(
                        comp, pos, e, component_kind=component_kind,
                        leaf_cache=leaf_cache, pattern_memo=pattern_memo,
                        pivots=pivots, open_ok=open_ok, leaf_min_len=leaf_min_len,
                    )
                    for unit in units:
                        # Open-edge coherence: every Elliott component alternates
                        # net direction against its predecessor. An open component
                        # moving the SAME way as the previous one means the previous
                        # component is still unfolding, not that a new wave has begun
                        # (kills "up wave 5 in progress" readings where price is in
                        # fact collapsing below wave 4's start -- review finding A).
                        if unit.open and comps and unit.direction == comps[-1].direction:
                            continue
                        comps2 = comps + [unit]
                        if not _passes_rules(spec, comps2, ctx):
                            continue
                        if unit.open:
                            prefix.setdefault(e, []).append((score + unit.total_ll, comps2))
                            continue  # nothing may follow an open component
                        new_states.setdefault(e, []).append((score + unit.total_ll, comps2))
                # Prefix-complete terminal at the right edge for NON-final
                # components ("wave 3 of 5 underway"): the reserve bound
                # above correctly excludes e == n-1 from the closed loop
                # (it saves room for siblings that will never exist in a
                # prefix), so the open terminal is considered separately.
                # c >= 2: at least TWO closed components must precede the
                # open one -- a single closed wave plus "something is moving"
                # is not a count, and letting one lucky child carry a whole
                # root breaks the permissiveness margin.
                if allow_open and c >= 2 and c < n_comp - 1:
                    e = n - 1
                    for unit in _candidate_units(
                            comp, pos, e, component_kind=component_kind,
                            leaf_cache=leaf_cache, pattern_memo=pattern_memo,
                            pivots=pivots, open_ok=True, leaf_min_len=leaf_min_len):
                        if not unit.open:
                            continue
                        if comps and unit.direction == comps[-1].direction:
                            continue
                        comps2 = comps + [unit]
                        if not _passes_rules(spec, comps2, ctx):
                            continue
                        prefix.setdefault(e, []).append((score + unit.total_ll, comps2))
        for pos2 in new_states:
            new_states[pos2] = _top_k(new_states[pos2], k)
        states = new_states

    results: dict[int, list[WaveUnit]] = {}
    for j, entries in states.items():
        nodes = []
        for score, comps in entries:
            if not _passes_rules(spec, comps, ctx):
                continue
            open_flag = any(c.open for c in comps)
            nodes.append(_assemble(spec, comps, role_universe, null, open_flag=open_flag))
        if nodes:
            results[j] = sorted(nodes, key=lambda nd: -nd.total_ll)[:k]

    # assemble prefix-complete (open) derivations and merge into results
    for j, entries in prefix.items():
        nodes = list(results.get(j, []))
        for score, comps in entries:
            if not _passes_rules(spec, comps, ctx):
                continue
            nodes.append(_assemble(spec, comps, role_universe, null, open_flag=True))
        if nodes:
            results[j] = sorted(nodes, key=lambda nd: -nd.total_ll)[:k]

    return results


def _candidate_units(comp: G.Component, pos: int, e: int, *, component_kind: str,
                       leaf_cache: Optional[LeafCache], pattern_memo: Optional[dict],
                       pivots: Optional[list[Pivot]], open_ok: bool,
                       leaf_min_len: Optional[int] = None) -> list[WaveUnit]:
    if component_kind == "leaf":
        out = []
        unit = leaf_cache.get(pos, e, comp.slot, min_len=leaf_min_len)
        if unit is not None:
            out.append(unit)
        if open_ok and pivots is not None:
            out.append(_open_leaf(pivots, pos, e))
        return out
    names = (comp.fixed,) if comp.fixed else G.allowed_patterns(comp.role)
    out = []
    for name in names:
        out.extend(pattern_memo.get((pos, e, name, False), []))
        if open_ok:
            # Only FINAL-component-open patterns may serve as a root's open
            # child. A mid-prefix open pattern (e.g. impulse with waves 1-2
            # done and 3 underway) carries almost no scoring cost for its
            # long open tail, which lets noise winners park all their
            # evidence in one hot closed sibling and claim the rest of the
            # window for ~0 nats (measured: GBM seed 5 at +14.8). Root
            # mid-prefixes themselves stay legal -- their open child is one
            # of these final-open patterns.
            for u in pattern_memo.get((pos, e, name, True), []):
                if len(u.children) == len(G.GRAMMAR[name].components):
                    out.append(u)
    return out


def build_pattern_memo(pivots: list[Pivot], null: NullModel, ctx: dict, k: int = 5,
                         allow_open: bool = True) -> dict:
    """Phase 1: assemble every one of the 13 grammar patterns from every
    start pivot. Returns PATTERN_MEMO[(i, j, pattern_name, open)] -> list
    of top-k WaveUnit, sorted best-first."""
    n = len(pivots)
    leaf_cache = LeafCache(pivots)
    memo: dict[tuple[int, int, str, bool], list[WaveUnit]] = {}
    for name, spec in G.GRAMMAR.items():
        for i in range(n - 1):
            results = parse_pattern_from_start(
                spec, i, n, component_kind="leaf", leaf_cache=leaf_cache,
                pivots=pivots, null=null, ctx=ctx, k=k, allow_open=allow_open,
            )
            for j, nodes in results.items():
                closed = [nd for nd in nodes if not nd.open]
                opened = [nd for nd in nodes if nd.open]
                if closed:
                    memo[(i, j, name, False)] = sorted(closed, key=lambda nd: -nd.total_ll)[:k]
                if opened:
                    memo.setdefault((i, j, name, True), [])
                    memo[(i, j, name, True)] = sorted(
                        memo[(i, j, name, True)] + opened, key=lambda nd: -nd.total_ll
                    )[:k]
    return memo


# A structured reversal tail needs >=2 closed :3 leaves plus an open one;
# below this span no structured tail is possible at all.
STRUCTURED_TAIL_MIN = 2 * MIN_LEAF["3"] + 1


def _reversal_readings(pattern_memo: dict, closed_by_end: dict[int, list[WaveUnit]],
                       n: int, pivots: list[Pivot] | None = None) -> list[WaveUnit]:
    """DESIGN.md §4's missing reading: "pattern just completed, larger-degree
    reversal just began". A CLOSED degree-2 root ending at m < n-1, plus an
    open degree-1 tail spanning [m, n-1] -- the first wave of the NEXT
    degree-2 pattern. Without this, every root must partition the entire
    window into its own components, which forces a completed trend plus a
    young counter-move into a bogus containing pattern (observed on NFLX:
    2022-2025 advance + 12-month decline could only parse as a triple
    zigzag with negative uplift, or as nothing at 4/5 anchors).

    Guards, each mirroring an existing right-edge gate (permissiveness is
    the binding constraint here):
    - the tail must be a FINAL-component-open pattern with >=2 closed
      components (a single closed wave plus "something moved" is not a
      reversal, same reasoning as the root prefix guard);
    - it must move AGAINST the completed root's last component -- same
      direction means the old wave is still unfolding, not that a new one
      began (v1.1's open-edge coherence rule);
    - the tournament's uplift gate applies to the completed root alone
      (anchor._uplift), so the root must earn its keep without the tail.

    Bare-tail fallback: when the counter-move is too young for ANY
    structured tail (span < STRUCTURED_TAIL_MIN pivots), a raw open
    monowave run may serve as the tail instead. This only relaxes the
    gates exactly where structure is impossible by construction -- the
    reading then says "root complete, reversal underway but not yet
    structured" (observed on MU: impulse complete at the high, decline
    containing a single monowave -- invisible to the structured gates).
    """
    best: dict[tuple[str, int], WaveUnit] = {}
    for m, roots in closed_by_end.items():
        tails = []
        for name, spec in G.GRAMMAR.items():
            for t in pattern_memo.get((m, n - 1, name, True), []):
                if not t.open or len(t.children) != len(spec.components):
                    continue
                if sum(1 for c in t.children if not c.open) < 2:
                    continue
                tails.append(t)
        if not tails and pivots is not None and (n - 1 - m) < STRUCTURED_TAIL_MIN:
            tails.append(_open_leaf(pivots, m, n - 1))
        if not tails:
            continue
        for r in roots:
            if not r.children:
                continue
            for t in tails:
                if t.direction == r.children[-1].direction:
                    continue
                if t.pattern is None:
                    # Bare tails carry no internal shape checks, so check
                    # the one thing that falsifies the reversal itself: no
                    # new extreme beyond the completion point. (Structured
                    # tails need no such guard -- a legitimately verified
                    # expanded flat's B MAY exceed it, cf. NFLX.)
                    if r.children[-1].direction == "up" and t.hi > r.end_price:
                        continue
                    if r.children[-1].direction == "down" and t.lo < r.end_price:
                        continue
                wrapper = WaveUnit(
                    i=r.i, j=n - 1, pattern=r.pattern,
                    start_price=r.start_price, end_price=t.end_price,
                    hi=max(r.hi, t.hi), lo=min(r.lo, t.lo),
                    # the live move is the tail's; the completed pattern's
                    # direction is history
                    direction=t.direction,
                    n_pivots=(n - 1) - r.i,
                    start_bar=r.start_bar, end_bar=t.end_bar,
                    children=r.children + (t,),
                    ll=r.ll, total_ll=r.total_ll + t.total_ll,
                    open=True, reversal=True,
                )
                # One reading per (pattern, completion point): the
                # roots x tails cross-product otherwise floods the root
                # k-best with near-identical variants, which deflates
                # relative_confidence's softmax, crowds out genuinely
                # diverse alternates, and fires near-tie warnings between
                # variants of the SAME reading (observed on NFLX).
                key = (r.pattern, m)
                if key not in best or wrapper.total_ll > best[key].total_ll:
                    best[key] = wrapper
    return list(best.values())


def build_root_candidates(pattern_memo: dict, anchor_i: int, n: int, null: NullModel,
                            ctx: dict, k: int = 5, allow_open: bool = True,
                            pivots: list[Pivot] | None = None) -> list[WaveUnit]:
    """Phase 2: assemble degree-2 root candidates spanning [anchor_i, n-1]
    only -- the one span the anchor tournament actually needs (DESIGN.md
    §4/§6: 'one chart serves everything'). Also admits completed-root +
    reversal-tail readings (closed root ending at m < n-1, open degree-1
    tail over [m, n-1]) via _reversal_readings. `pivots` enables the
    bare-tail fallback for too-young reversals; without it only
    structured tails are considered."""
    out: list[WaveUnit] = []
    closed_by_end: dict[int, list[WaveUnit]] = {}
    for name, spec in G.GRAMMAR.items():
        results = parse_pattern_from_start(
            spec, anchor_i, n, component_kind="pattern", pattern_memo=pattern_memo,
            null=null, ctx=ctx, k=k, allow_open=allow_open,
        )
        for j, nodes in results.items():
            if j == n - 1:
                out.extend(nodes)
            elif allow_open:
                closed_by_end.setdefault(j, []).extend(nd for nd in nodes if not nd.open)
    if allow_open:
        out.extend(_reversal_readings(pattern_memo, closed_by_end, n, pivots=pivots))
    return sorted(out, key=lambda nd: -nd.total_ll)[:max(k, 5)]
