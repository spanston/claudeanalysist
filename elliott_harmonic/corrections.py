"""HEW corrective-structure classification over a pivot (monowave) sequence.

Degree mapping (as in fractals.py): at pivot granularity an impulsive leg is
3 pivot legs (a-b-c), so at this degree

    zigzag       = A(3 legs) + B(1 or 3 legs) + C(3 legs)     [5-3-5]
    flat         = A(3) + B(3) + C(3)                         [3-3-5]
    triangle     = 5 legs (a-b-c-d-e, one pivot leg each)
    double three = two zigzag/flat blocks joined by X (1 or 3 legs)

The corrections skill allows B/X of "1-3 legs"; odd counts only are reachable
because the pivot sequence strictly alternates H/L (the same (1,3,5)
convention as fractals.py), so 2-leg connectors never occur here.

Hard gates and scoring (from the corrections skill; fuzzy edges pinned to the
tolerances below):
  zigzag: B never beyond the start of A; C exceeds the A extreme. B typically
          38.2-85.4% of A (outside = tolerated, penalized); C/A scored vs
          R.C_RATIOS (most common 1.0/1.092/1.146/1.236/1.764).
  flat:   B >= 90% of A (shallower is zigzag territory); B beyond 150% of A
          invalid. Variants per the discriminator matrix:
          regular  B retests the start of A (90-110%); C ends within
                   REG_C_TOL of the A extreme ("holds near", either side);
          expanded B exceeds the A start by 14.6-38.2% of A (occasionally to
                   50%, penalized); C exceeds the A extreme ("normally just
                   beyond": fitted band 0-23.6% of A);
          running  B exceeds the A start; C fails to reach the A extreme.
  triangle: legs strictly contract; ratio bands b/a 76.4-85.4%, c/b
          66.7-76.4%, d/c 66.7-76.4%, e/d 50-66.7%. ONE irregular expansion
          <= 38.2% allowed (never for e), then the next leg must run
          85.4-105.6% of the expanded one. No leg makes a new extreme beyond
          the structure start ("in an uptrend it never makes a higher high").
          The "e not too close to the apex" rule is unmodeled -- there is no
          trendline/apex geometry at this granularity.
  double three: X never beyond the start of W (depth otherwise a wild card);
          Y = 100% x W projected from the X end, fit window 8%.

Every 3-leg block additionally obeys the fractal rules already used in
fractals.py: (b) never beyond the start of (a); (c) >= 60% of (a).

A move failing every pattern gate returns None -- honest refusal.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from elliott.pivots import Pivot

from . import ratios as R

# --- Tolerances (see module docstring) --------------------------------------
CONNECTOR_LEGS = (1, 3)             # zigzag B and double-three X leg counts
ZZ_B_TYPICAL = (0.382, 0.854)       # typical zigzag-B band
FLAT_B_MIN = 0.90                   # a flat's B is deep; shallower = zigzag
FLAT_B_REGULAR = 1.10               # regular/expanded boundary on B/A
EF_BAND = (1.146, 1.382)            # expanded-flat B overshoot band
EF_HARD_CAP = 1.50                  # "expanded beyond 50% of A" is invalid
REG_C_TOL = 0.30                    # regular flat: C holds near the A extreme
EXP_C_MAX = 0.236                   # expanded flat: C "normally just beyond"
RUN_C_MAX = 0.50                    # running flat: max credible C shortfall
TRI_BANDS = ((0.764, 0.854), (0.667, 0.764), (0.667, 0.764), (0.50, 0.667))
TRI_IRREG_MAX = 1.382               # one leg may expand beyond the prior extreme
TRI_POST_IRREG = (0.854, 1.056)     # the leg after an irregular expansion
D3_Y_TOL = 0.08                     # Y = 100% x W fit window
C_STEEP = 1.764                     # C/A above this smells impulsive, not corrective

_FIT_TOL = 0.08                     # generic ratio-fit window (as in score.py)
_EPS = 1e-9


@dataclass
class CorrectionMatch:
    """A classified corrective structure over the pivot sequence."""

    pattern: str          # "zigzag" | "flat" | "triangle" | "double_three"
    variant: str | None   # flat: regular/expanded/running; triangle: contracting/None
    direction: str        # direction of the corrective move itself: "up" | "down"
    start: int            # pivot index of the correction start (the A start)
    end: int              # pivot index of completion (C end / E end / Y end)
    score: float          # 0..1 ratio-harmony score
    legs: dict            # named leg spans/lengths with computed retr/proj ratios
    targets: list[dict]
    invalidation: dict    # {"price": float, "rule": str}
    notes: list[str] = field(default_factory=list)


@dataclass
class _Block:
    """A matched zigzag/flat block (reused as W/Y inside a double three)."""

    pattern: str          # "zigzag" | "flat"
    variant: str | None
    end: int
    net: float            # travel in the correction direction: d*(p[end]-p[start])
    score: float
    legs: dict
    targets: list[dict]
    invalidation: dict
    notes: list[str]


def _d(direction: str) -> int:
    if direction == "up":
        return 1
    if direction == "down":
        return -1
    raise ValueError(f"direction must be 'up' or 'down', got {direction!r}")


def _abc(p: list[Pivot], s: int, d: int) -> tuple[float, float, float] | None:
    """Internal a-b-c stats of the 3-leg block starting at pivot s.

    Returns (a, b, c) lengths (all positive) or None when the block is
    structurally impossible: a leg moves against its own direction, (b)
    reaches the start of (a), or (c) < 60% of (a) (the C_HARD_MIN floor).
    """
    if s + 3 > len(p) - 1:
        return None
    a = d * (p[s + 1].price - p[s].price)
    b = -d * (p[s + 2].price - p[s + 1].price)
    c = d * (p[s + 3].price - p[s + 2].price)
    if a <= 0 or b <= 0 or c <= 0:
        return None
    if b >= a - _EPS:           # (b) never beyond the start of (a)
        return None
    if c < R.C_HARD_MIN * a:    # (c) projection-table floor
        return None
    return a, b, c


def _band_fit(x: float, lo: float, hi: float, soft: float) -> float:
    """1.0 inside [lo, hi], linear decay to 0.0 at `soft` beyond the edges."""
    if lo <= x <= hi:
        return 1.0
    if x < lo:
        return max(0.0, 1.0 - (lo - x) / soft)
    return max(0.0, 1.0 - (x - hi) / soft)


def _ca_fit(abc: tuple[float, float, float]) -> float:
    """Harmony of a block's internal (c)/(a) vs the (c) projection table."""
    return R.ratio_fit(abc[2] / abc[0], R.C_RATIOS, tol=_FIT_TOL)


def _zigzag_block(p: list[Pivot], s: int, d: int) -> _Block | None:
    """Best zigzag A(3)-B(1|3)-C(3) starting at pivot s, or None."""
    best: _Block | None = None
    for bl in CONNECTOR_LEGS:
        e = s + 6 + bl
        if e > len(p) - 1:
            continue
        abc_a = _abc(p, s, d)
        abc_c = _abc(p, s + 3 + bl, d)
        abc_b = _abc(p, s + 3, -d) if bl == 3 else None
        if abc_a is None or abc_c is None or (bl == 3 and abc_b is None):
            continue
        A = d * (p[s + 3].price - p[s].price)
        B = -d * (p[s + 3 + bl].price - p[s + 3].price)
        C = d * (p[e].price - p[s + 3 + bl].price)
        # Hard: B stays off the start of A; C exceeds the A extreme.
        if d * (p[s].price - p[s + 3 + bl].price) >= -_EPS:
            continue
        if d * (p[e].price - p[s + 3].price) <= _EPS:
            continue

        b_ret = B / A
        ca = C / A
        b_fit = R.ratio_fit(b_ret, R.RETRACEMENTS, tol=_FIT_TOL)
        c_fit = R.ratio_fit(ca, R.C_RATIOS, tol=_FIT_TOL)
        fits = [_ca_fit(abc_a), _ca_fit(abc_c)]
        if abc_b:
            fits.append(_ca_fit(abc_b))
        internal = sum(fits) / len(fits)
        score = (1.5 * b_fit + 3.0 * c_fit + 1.5 * internal) / 6.0

        notes: list[str] = []
        if not (ZZ_B_TYPICAL[0] <= b_ret <= ZZ_B_TYPICAL[1]):
            score *= 0.9
            notes.append(f"B retrace {b_ret * 100:.0f}% is atypical for a zigzag "
                         f"(typical {ZZ_B_TYPICAL[0] * 100:.0f}-"
                         f"{ZZ_B_TYPICAL[1] * 100:.0f}%)")
        if ca > C_STEEP:
            notes.append("C disproportionately steep -- may be impulsive, not corrective")

        legs = {
            "A": {"span": (s, s + 3), "len": round(A, 4),
                  "prices": (p[s].price, p[s + 3].price),
                  "internal_ca": round(abc_a[2] / abc_a[0], 3)},
            "B": {"span": (s + 3, s + 3 + bl), "len": round(B, 4),
                  "legs": bl, "retr": round(b_ret, 3)},
            "C": {"span": (s + 3 + bl, e), "len": round(C, 4),
                  "c_over_a": round(ca, 3),
                  "internal_ca": round(abc_c[2] / abc_c[0], 3)},
        }
        targets = []
        for r in (0.618, 1.0, 1.146, 1.236, 1.764):
            proj = p[s + 3 + bl].price + d * r * A
            if proj <= 0:
                continue  # non-positive price target is not tradeable
            # Stale-level guard: the realized C already reached the projection
            # (same 1% buffer as engine.py's beyond()).
            if d * (proj - p[e].price) <= 0.01 * abs(p[e].price):
                continue
            targets.append({"label": f"C = A x {r}", "price": round(proj, 4),
                            "basis": "|A| x ratio projected from the B end"})
        inv = {"price": p[s].price,
               "rule": "B beyond the start of A kills the zigzag reading"}
        blk = _Block("zigzag", None, e, d * (p[e].price - p[s].price), score,
                     legs, targets, inv, notes)
        if best is None or blk.score > best.score:
            best = blk
    return best


def _flat_block(p: list[Pivot], s: int, d: int) -> _Block | None:
    """Flat A(3)-B(3)-C(3) starting at pivot s, variant per the matrix, or None."""
    e = s + 9
    if e > len(p) - 1:
        return None
    abc_a = _abc(p, s, d)
    abc_b = _abc(p, s + 3, -d)
    abc_c = _abc(p, s + 6, d)
    if abc_a is None or abc_b is None or abc_c is None:
        return None
    A = d * (p[s + 3].price - p[s].price)
    B = -d * (p[s + 6].price - p[s + 3].price)
    C = d * (p[e].price - p[s + 6].price)
    b_ret = B / A
    if b_ret < FLAT_B_MIN or b_ret > EF_HARD_CAP:
        return None
    # C terminal vs the A extreme, in units of A (> 0 = beyond the extreme).
    c_term = d * (p[e].price - p[s + 3].price) / A

    if b_ret <= FLAT_B_REGULAR:
        variant = "regular"
        if abs(c_term) > REG_C_TOL:
            return None
        b_fit = max(0.0, 1.0 - abs(b_ret - 1.0) / (FLAT_B_REGULAR - 1.0))
        c_fit = max(0.0, 1.0 - abs(c_term) / REG_C_TOL)
    elif c_term > 0:
        variant = "expanded"
        b_fit = _band_fit(b_ret, *EF_BAND, soft=0.10)
        c_fit = _band_fit(c_term, 0.0, EXP_C_MAX, soft=0.15)
    else:
        variant = "running"
        b_fit = _band_fit(b_ret, *EF_BAND, soft=0.10)
        c_fit = max(0.0, 1.0 - abs(c_term) / RUN_C_MAX)
    if b_fit == 0.0 or c_fit == 0.0:
        return None

    internal = (_ca_fit(abc_a) + _ca_fit(abc_b) + _ca_fit(abc_c)) / 3.0
    score = (2.0 * b_fit + 2.0 * c_fit + 1.5 * internal) / 5.5

    notes: list[str] = []
    if variant == "expanded":
        notes.append("trend resumption confirmed only on a break of the 38.2-50% "
                     "expansion zone beyond the A start")
        if b_ret > EF_BAND[1]:
            score *= 0.9
            notes.append("B overshoot beyond 38.2% of A -- occasional, tolerated up to 50%")

    legs = {
        "A": {"span": (s, s + 3), "len": round(A, 4),
              "prices": (p[s].price, p[s + 3].price),
              "internal_ca": round(abc_a[2] / abc_a[0], 3)},
        "B": {"span": (s + 3, s + 6), "len": round(B, 4),
              "retr": round(b_ret, 3),
              "beyond_start": round(b_ret - 1.0, 3)},
        "C": {"span": (s + 6, e), "len": round(C, 4),
              "terminal_vs_a": round(c_term, 3),
              "internal_ca": round(abc_c[2] / abc_c[0], 3)},
    }
    targets = [{
        "label": "C terminal zone (A extreme)",
        "zone": sorted([round(p[s + 3].price, 4),
                        round(p[s + 3].price + d * 0.146 * A, 4)]),
        "basis": ("regular/expanded: C normally just beyond A's end; "
                  "running: C fails toward it"),
    }]
    if variant == "regular":
        inv = {"price": p[s].price,
               "rule": "B beyond the start of A ends the regular-flat reading "
                       "(re-read as expanded/running)"}
    else:
        inv = {"price": round(p[s + 3].price - d * EF_HARD_CAP * A, 4),
               "rule": "B beyond 150% of A invalidates the expanded/running-flat reading"}
    return _Block("flat", variant, e, d * (p[e].price - p[s].price), score,
                  legs, targets, inv, notes)


def _match_triangle(p: list[Pivot], s: int, d: int) -> CorrectionMatch | None:
    """Contracting (or once-irregular) 5-leg triangle starting at pivot s."""
    e = s + 5
    if e > len(p) - 1:
        return None
    L = [abs(p[s + j + 1].price - p[s + j].price) for j in range(5)]
    if min(L) <= 0:
        return None
    # No leg makes a new extreme beyond the structure start.
    for j in range(s + 1, e + 1):
        if d * (p[s].price - p[j].price) >= -_EPS:
            return None

    names = "abcde"
    ratios = [L[k + 1] / L[k] for k in range(4)]
    fits: list[float] = []
    notes: list[str] = ["wave-e fakeout risk: e may fake a breakdown or truncate"]
    irregular = False
    k = 0
    while k < 4:
        r = ratios[k]
        if r < 1.0 - _EPS:  # contracting leg
            fits.append(_band_fit(r, *TRI_BANDS[k], soft=0.10))
            k += 1
            continue
        # Expanding leg: allowed once, <= 38.2% beyond the prior leg, never e.
        if irregular or r > TRI_IRREG_MAX + _EPS or k == 3:
            return None
        irregular = True
        fits.append(max(0.0, 1.0 - 0.5 * (r - 1.0) / (TRI_IRREG_MAX - 1.0)))
        r2 = ratios[k + 1]
        post = _band_fit(r2, *TRI_POST_IRREG, soft=0.08)
        if post == 0.0:
            return None
        fits.append(post)
        notes.append(f"irregular expansion in leg {names[k]} (x{r:.2f}); "
                     f"leg {names[k + 1]} runs {r2 * 100:.0f}% of it")
        k += 2

    score = sum(fits) / 4.0
    legs: dict = {}
    for j in range(5):
        entry: dict = {"span": (s + j, s + j + 1), "len": round(L[j], 4),
                       "prices": (p[s + j].price, p[s + j + 1].price)}
        if j:
            entry["ratio_to_prev"] = round(ratios[j - 1], 3)
        legs[names[j]] = entry
    targets = [{"label": "post-triangle thrust ~= leg a",
                "price": round(p[e].price - d * L[0], 4),
                "basis": "price leaves a triangle with a spiky move ~= its widest "
                         "leg, projected from the e end OPPOSITE the a-leg "
                         "(the a-leg is counter-trend; the trend resumes)"}]
    inv = {"price": p[s].price,
           "rule": "a new extreme beyond the structure start kills the triangle reading"}
    return CorrectionMatch("triangle", None if irregular else "contracting",
                           "up" if d > 0 else "down", s, e, round(score, 4),
                           legs, targets, inv, notes)


def _match_double_three(p: list[Pivot], s: int, d: int) -> CorrectionMatch | None:
    """Two zigzag/flat blocks (W, Y) joined by an X connector, or None."""
    n = len(p)
    best: CorrectionMatch | None = None
    ws = [b for b in (_zigzag_block(p, s, d), _flat_block(p, s, d)) if b]
    for w in ws:
        for xl in CONNECTOR_LEGS:
            xe = w.end + xl
            if xe > n - 1:
                continue
            # Hard: X must not exceed the start of W (depth otherwise wild).
            if d * (p[s].price - p[xe].price) >= -_EPS:
                continue
            if -d * (p[xe].price - p[w.end].price) <= 0:
                continue
            if xl == 3 and _abc(p, w.end, -d) is None:
                continue
            ys = [b for b in (_zigzag_block(p, xe, d), _flat_block(p, xe, d)) if b]
            for y in ys:
                yw = y.net / w.net
                yw_fit = max(0.0, 1.0 - abs(yw - 1.0) / D3_Y_TOL)
                if yw_fit == 0.0:
                    continue
                score = (2.0 * yw_fit + 1.5 * w.score + 1.5 * y.score) / 5.0
                notes = [f"W: {w.pattern}" + (f" ({w.variant})" if w.variant else ""),
                         f"Y: {y.pattern}" + (f" ({y.variant})" if y.variant else "")]
                notes += w.notes + y.notes
                legs = {"W": w.legs, "Y": y.legs,
                        "X": {"span": (w.end, xe), "legs": xl,
                              "depth": round(-d * (p[xe].price - p[w.end].price), 4)},
                        "y_over_w": round(yw, 3)}
                targets = [{"label": "Y = 100% x W",
                            "price": round(p[xe].price + d * w.net, 4),
                            "basis": "Y = 100% x W projected from the X end"}]
                inv = {"price": p[s].price,
                       "rule": "X beyond the start of W kills the double-three reading"}
                m = CorrectionMatch("double_three", None, "up" if d > 0 else "down",
                                    s, y.end, round(score, 4), legs, targets,
                                    inv, notes)
                if best is None or m.score > best.score:
                    best = m
    return best


def _wrap(blk: _Block, direction: str, s: int) -> CorrectionMatch:
    return CorrectionMatch(blk.pattern, blk.variant, direction, s, blk.end,
                           round(blk.score, 4), blk.legs, blk.targets,
                           blk.invalidation, blk.notes)


def _all_matches(p: list[Pivot], s: int, direction: str) -> list[CorrectionMatch]:
    """Every pattern passing its hard gates at pivot s (unsorted)."""
    d = _d(direction)
    out = [_wrap(b, direction, s)
           for b in (_zigzag_block(p, s, d), _flat_block(p, s, d)) if b]
    for m in (_match_triangle(p, s, d), _match_double_three(p, s, d)):
        if m:
            out.append(m)
    for m in out:
        if m.end == len(p) - 1:
            m.notes.append("end is the provisional right-edge pivot (can move with new bars)")
    return out


def match_correction(pivots: list[Pivot], start: int,
                     direction: str) -> CorrectionMatch | None:
    """Best corrective match beginning at pivot `start` (kind must agree with
    direction: up-correction starts at an L pivot and vice versa). Tries all
    patterns; returns the highest-scoring complete match, or None."""
    _d(direction)  # validates the direction string
    if not 0 <= start < len(pivots):
        return None
    if pivots[start].kind != ("L" if direction == "up" else "H"):
        return None
    cands = _all_matches(pivots, start, direction)
    return max(cands, key=lambda m: m.score) if cands else None


def scan_corrections(pivots: list[Pivot], direction: str | None = None,
                     min_span_frac: float = 0.15) -> list[CorrectionMatch]:
    """All reasonable matches across start positions (deduped by
    pattern+variant+start+end), sorted by score desc.

    `min_span_frac` is the same anti-noise floor as in fractals.py: a match's
    price span must be at least this fraction of the whole sequence's span.
    """
    n = len(pivots)
    if n < 6:
        return []
    hi = max(q.price for q in pivots)
    lo = min(q.price for q in pivots)
    min_span = min_span_frac * (hi - lo)
    if direction is None:
        directions = ("up", "down")
    else:
        _d(direction)  # validates the direction string
        directions = (direction,)
    seen: set[tuple] = set()
    out: list[CorrectionMatch] = []
    for s in range(0, n - 5):
        for dr in directions:
            if pivots[s].kind != ("L" if dr == "up" else "H"):
                continue
            for m in _all_matches(pivots, s, dr):
                key = (m.pattern, m.variant, m.start, m.end)
                if key in seen:
                    continue
                seg = pivots[m.start:m.end + 1]
                if max(q.price for q in seg) - min(q.price for q in seg) < min_span:
                    continue
                seen.add(key)
                out.append(m)
    out.sort(key=lambda m: m.score, reverse=True)
    return out
