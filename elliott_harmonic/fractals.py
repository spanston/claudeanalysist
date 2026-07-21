"""HEW five-wave fractal enumeration over a pivot (monowave) sequence.

A Harmonic Elliott Wave five-wave fractal at pivot granularity is

    (i)   = 3 legs (a-b-c), trend direction
    (ii)  = correction of c2 legs (1, 3 or 5)
    (iii) = 3 legs (a-b-c), trend direction
    (iv)  = correction of c4 legs (1, 3 or 5)
    (v)   = 3 legs (a-b-c), trend direction

c2/c4 odd keeps the H/L alternation consistent. Candidates may be complete
(the (v) end is a pivot, possibly with a tail after it) or open (the right
edge of the data truncates the fractal inside (iii), (iv) or (v); the last
zigzag pivot is provisional, which the report must flag).

Hard gates (the six HEW rules + supporting rules, see harmonic-elliott-core):
  1. (ii) never beyond start of (i)
  2. (iii) exceeds the (i) extreme            (checked once (iii) is complete)
  3. (iii) never the shortest of (i),(iii),(v)
  4. (iv) never breaches the (b)-of-(iii) extreme
  5. (v) normally exceeds (iii)               (soft -- penalty, not a gate)
  6. (iii) >= 176.4% x (i)  (172-176.4% rare-tolerance band, flagged)
plus: (c) of (iii) >= (a) of (iii); (c) >= 76.4% of (a) inside (i)/(v);
(b) never beyond start of (a); (b) of (iii) capped ~90% of (a).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from elliott.pivots import Pivot

from . import ratios as R

CORRECTION_LEGS = (1, 3, 5)

# Structural leg offsets within a candidate (from start pivot s):
#   (i):   s .. s+3            end_i   = s+3
#   (ii):  s+3 .. s+3+c2       end_ii  = s+3+c2
#   (iii): end_ii .. end_ii+3  b3_end  = end_ii+2, end_iii = end_ii+3
#   (iv):  end_iii .. +c4      end_iv  = end_iii+c4
#   (v):   end_iv .. end_iv+3  b5_end  = end_iv+2, end_v = end_iv+3


@dataclass
class Fractal:
    """A candidate HEW five-wave fractal over the pivot sequence."""

    direction: str          # "up" | "down"
    start: int              # pivot index of the fractal origin
    c2: int                 # (ii) leg count
    c4: int                 # (iv) leg count
    realized_end: int       # last pivot index the reading uses (< end_v when open)
    complete: bool          # True when realized_end == end_v
    stage: str              # "iii" | "iv" | "v" (open) or "done" (complete)
    violations: list[str] = field(default_factory=list)

    # --- structural pivot indices (derived in __post_init__) ---
    end_i: int = 0
    end_ii: int = 0
    a3_end: int = 0
    b3_end: int = 0
    end_iii: int = 0
    end_iv: int = 0
    b5_end: int = 0
    end_v: int = 0

    def __post_init__(self) -> None:
        self.end_i = self.start + 3
        self.end_ii = self.end_i + self.c2
        self.a3_end = self.end_ii + 1
        self.b3_end = self.end_ii + 2
        self.end_iii = self.end_ii + 3
        self.end_iv = self.end_iii + self.c4
        self.b5_end = self.end_iv + 2
        self.end_v = self.end_iv + 3


def _move(pivots: list[Pivot], j0: int, j1: int, d: int) -> float:
    """Signed length of the move pivot j0 -> j1, positive in trend direction."""
    return d * (pivots[j1].price - pivots[j0].price)


def wave_lengths(fr: Fractal, pivots: list[Pivot]) -> dict:
    """Trend-direction-positive lengths of the realized structure."""
    d = 1 if fr.direction == "up" else -1
    p = pivots
    out = {
        "i": _move(p, fr.start, fr.end_i, d),
        "ii": -_move(p, fr.end_i, fr.end_ii, d),  # positive = depth of retrace
        "a1": _move(p, fr.start, fr.start + 1, d),
        "b1": -_move(p, fr.start + 1, fr.start + 2, d),
        "c1": _move(p, fr.start + 2, fr.end_i, d),
    }
    if fr.realized_end >= fr.a3_end:
        out["a3"] = _move(p, fr.end_ii, fr.a3_end, d)
    if fr.realized_end >= fr.b3_end:
        out["b3"] = -_move(p, fr.a3_end, fr.b3_end, d)
    if fr.realized_end >= fr.end_iii:
        out["c3"] = _move(p, fr.b3_end, fr.end_iii, d)
        out["iii"] = _move(p, fr.end_ii, fr.end_iii, d)
    else:  # (iii) still unfolding: measure to the realized edge
        out["iii_partial"] = _move(p, fr.end_ii, fr.realized_end, d)
    if fr.realized_end >= fr.end_iv:
        out["iv"] = -_move(p, fr.end_iii, fr.end_iv, d)
    elif fr.realized_end > fr.end_iii:
        out["iv_partial"] = -_move(p, fr.end_iii, fr.realized_end, d)
    if fr.realized_end >= fr.end_v:
        out["a5"] = _move(p, fr.end_iv, fr.end_iv + 1, d)
        out["b5"] = -_move(p, fr.end_iv + 1, fr.b5_end, d)
        out["c5"] = _move(p, fr.b5_end, fr.end_v, d)
        out["v"] = _move(p, fr.end_iv, fr.end_v, d)
    elif fr.realized_end > fr.end_iv:
        out["v_partial"] = _move(p, fr.end_iv, fr.realized_end, d)
    return out


def check_hard_rules(fr: Fractal, pivots: list[Pivot]) -> list[str]:
    """Return the list of violated hard rules (empty = candidate is valid)."""
    d = 1 if fr.direction == "up" else -1
    p = pivots
    L = wave_lengths(fr, p)
    v: list[str] = []

    # Rule 1: (ii) never beyond start of (i).
    if L["ii"] >= L["i"] - 1e-9:
        v.append("r1_ii_beyond_start_of_i")

    # (b) never beyond start of (a), inside every realized a-b-c.
    if L["b1"] >= L["a1"] - 1e-9:
        v.append("b1_beyond_start_of_a1")
    if "b3" in L and L["b3"] >= L["a3"] - 1e-9:
        v.append("b3_beyond_start_of_a3")
    if "b5" in L and L["b5"] >= L["a5"] - 1e-9:
        v.append("b5_beyond_start_of_a5")

    # (c)/(a) floors: hard 76.4% everywhere. (c) of (iii) >= (a) of (iii) is
    # gated on a CONFIRMED (iii) (a reversal leg exists after it); at the
    # provisional right edge the (c) leg may still be extending.
    confirmed_iii = fr.complete or fr.realized_end > fr.end_iii
    if L["c1"] < R.C_HARD_MIN * L["a1"]:
        v.append("c1_below_76pct_of_a1")
    if confirmed_iii and "c3" in L and L["c3"] < R.C_OF_III_MIN * L["a3"] * 0.99:
        v.append("c3_below_a3")
    if "c5" in L and L["c5"] < R.C_HARD_MIN * L["a5"]:
        v.append("c5_below_76pct_of_a5")

    # (b) of (iii) positional cap (~90% hard edge of the 76.4-85.4% band).
    if "b3" in L and L["b3"] > R.B_OF_III_MAX * L["a3"]:
        v.append("b3_exceeds_90pct_of_a3")

    if confirmed_iii:
        # Rule 2: (iii) exceeds the (i) extreme.
        if d * p[fr.end_iii].price <= d * p[fr.end_i].price:
            v.append("r2_iii_not_beyond_i")
        # Rule 6: (iii) >= 172% (rare floor) x (i).
        if L["iii"] < R.W3_RARE_FLOOR * L["i"]:
            v.append("r6_iii_below_172pct_of_i")

    # Rule 4: (iv) never breaches the (b)-of-(iii) extreme -- checked both for
    # completed (iv) and for the realized edge while (iv) is unfolding.
    if fr.realized_end > fr.end_iii and "b3" in L:
        deepest_iv = fr.end_iv if fr.realized_end >= fr.end_iv else fr.realized_end
        if d * p[deepest_iv].price <= d * p[fr.b3_end].price:
            v.append("r4_iv_breaches_b_of_iii")

    # Rule 3 (the part not implied by rule 6): (iii) not shorter than (v).
    if "v" in L and L["v"] >= L["iii"]:
        v.append("r3_v_not_shorter_than_iii")
    if "v_partial" in L and L["v_partial"] >= L.get("iii", float("inf")):
        v.append("r3_v_partial_already_exceeds_iii")

    # Right-edge ratchet guards: an open count must hold its binding support.
    # Stage (iv) is already covered by the rule-4 check above (it uses the
    # realized edge); stages (iii) and (v) need the explicit edge check.
    if not fr.complete:
        if fr.realized_end <= fr.end_iii:  # in (iii): hold above the (ii) extreme
            if d * p[fr.realized_end].price <= d * p[fr.end_ii].price:
                v.append("edge_broke_ii_extreme")
        elif fr.realized_end > fr.end_iv:  # in (v): hold above the (iv) extreme
            if d * p[fr.realized_end].price <= d * p[fr.end_iv].price:
                v.append("edge_broke_iv_extreme")

    # Rule 6 reachability: if the minimum (iii) projection implies a negative
    # price (deep down moves), no HEW impulse can ever complete -- the move is
    # not an impulse of this degree (likely a corrective C of larger degree).
    if not confirmed_iii and fr.realized_end <= fr.end_iii:
        proof = p[fr.end_ii].price + d * R.W3_MIN * L["i"]
        if proof <= 0:
            v.append("r6_unreachable_negative_price")

    return v


def enumerate_fractals(pivots: list[Pivot],
                        min_span_frac: float = 0.15) -> list[Fractal]:
    """Enumerate all rule-valid candidates (complete and open) over `pivots`.

    `min_span_frac` is an anti-noise floor: the fractal's price span must be
    at least this fraction of the whole pivot sequence's span.
    """
    n = len(pivots)
    out: list[Fractal] = []
    if n < 6:
        return out
    hi = max(p.price for p in pivots)
    lo = min(p.price for p in pivots)
    min_span = min_span_frac * (hi - lo)

    for s in range(0, n - 6):
        direction = "up" if pivots[s].kind == "L" else "down"
        d = 1 if direction == "up" else -1
        for c2 in CORRECTION_LEGS:
            end_ii = s + 3 + c2
            if end_ii + 1 > n - 1:
                continue  # (iii) cannot even start
            for c4 in CORRECTION_LEGS:
                end_v = end_ii + 3 + c4 + 3
                realized_end = min(end_v, n - 1)
                if realized_end < end_ii + 1:
                    continue  # too young: (iii) leg (a) not done
                complete = realized_end == end_v
                edge = realized_end == n - 1  # last zigzag pivot: provisional
                if complete:
                    stage = "done"
                elif realized_end < end_ii + 3 or (realized_end == end_ii + 3 and edge):
                    # (iii) still unfolding, or its 3rd leg ends exactly at the
                    # provisional right edge (it may extend -- unproven, not gated).
                    stage = "iii"
                elif realized_end < end_ii + 3 + c4 or (realized_end == end_ii + 3 + c4 and edge):
                    stage = "iv"
                else:
                    stage = "v"
                fr = Fractal(direction, s, c2, c4, realized_end, complete, stage)

                # Anti-noise span floor.
                seg = pivots[s:realized_end + 1]
                span = max(q.price for q in seg) - min(q.price for q in seg)
                if span < min_span:
                    continue

                fr.violations = check_hard_rules(fr, pivots)
                if fr.violations:
                    continue

                # Completed candidates whose tail makes a new extreme beyond
                # the (v) end were overrun: the "completion" was at best a
                # lower-degree leg. Superseded readings are dropped -- the
                # larger structure is the actionable one.
                if complete and realized_end < n - 1:
                    v_extreme = pivots[end_v].price
                    if any(d * q.price > d * v_extreme for q in pivots[end_v + 1:]):
                        continue

                out.append(fr)
    return out
