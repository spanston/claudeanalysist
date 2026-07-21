"""Declarative grammar of Elliott Wave patterns: components, roles, hard
rules, and prior weights. See DESIGN.md §3.

Pure data + pure rule-checking functions; holds no parse state. Every
component fed to a hard-rule function or role check is a *node* (either a
parser.Leaf -- a degree-floor raw monowave run -- or a parser.Node -- a
completed named sub-pattern) exposing:

    .pattern        str | None   sub-pattern name, or None for a floor leaf
    .start_price    float        price at the component's first pivot
    .end_price      float        price at the component's last pivot
    .hi, .lo        float        price extremes reached within the span
    .direction       "up"|"down" sign of end_price - start_price
    .n_pivots       int          span length in monowaves

Hard rules and geometric checks (trendline convergence) use cheap proxies
(leg-size comparisons) rather than full linear regression -- regression-
quality fit belongs in guidelines.py's soft channel-fit guideline; hard
rules are on the parser's hot path and must stay O(1).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Sequence

Rule = Callable[[Sequence["object"], dict], bool]


# ---------------------------------------------------------------------------
# Roles: which named patterns (or the universal floor-leaf fallback) are
# legal in a given slot. DESIGN.md's canon fixes require this to be an
# *attribute* grammar -- a component's legality depends on the slot the
# parent places it in, not just its own shape (ending diagonals only at
# W5/C, leading only at W1/A, triangles never at W2, ...).
# ---------------------------------------------------------------------------

ROLE_FIVE_FIRST = "FIVE_FIRST"      # W1 of impulse, A of zigzag
ROLE_FIVE_MID = "FIVE_MID"          # W3 of impulse -- impulse only, ever
ROLE_FIVE_LAST = "FIVE_LAST"        # W5 of impulse, C of zigzag/flat
ROLE_FIVE_SIMPLE = "FIVE_SIMPLE"    # :5 slot inside a diagonal -- impulse only
ROLE_THREE_PLAIN = "THREE_PLAIN"    # W2 of impulse, A/B of flat: no triangle
ROLE_THREE_TRI_OK = "THREE_TRI_OK"  # W4 of impulse, B of zigzag/flat: triangle legal
ROLE_THREE_XLINK = "THREE_XLINK"    # X-wave linking a combination: simple only
ROLE_THREE_DIAGONAL = "THREE_DIAGONAL"  # :3 slot inside a diagonal: zigzag only
ROLE_TRIANGLE_LEG = "TRIANGLE_LEG"  # triangle A-D: simple corrections only
ROLE_TRIANGLE_E = "TRIANGLE_E"      # triangle E: may itself be a (contracting) triangle

_SIMPLE_THREE = ("zigzag", "flat_regular", "flat_expanded", "flat_running")
_ALL_THREE = _SIMPLE_THREE + (
    "double_zigzag", "triple_zigzag", "double_three", "triple_three",
)

ROLE_ALLOWED_PATTERNS: dict[str, tuple[str, ...]] = {
    ROLE_FIVE_FIRST: ("impulse", "diagonal_leading"),
    ROLE_FIVE_MID: ("impulse",),
    ROLE_FIVE_LAST: ("impulse", "diagonal_ending"),
    ROLE_FIVE_SIMPLE: ("impulse",),
    ROLE_THREE_PLAIN: _ALL_THREE,
    ROLE_THREE_TRI_OK: _ALL_THREE + ("triangle_contract", "triangle_expand"),
    ROLE_THREE_XLINK: _SIMPLE_THREE,
    ROLE_THREE_DIAGONAL: ("zigzag",),
    ROLE_TRIANGLE_LEG: _SIMPLE_THREE,
    ROLE_TRIANGLE_E: _SIMPLE_THREE + ("triangle_contract",),
}

# Roles whose slot type is a :5 (impulsive) span vs a :3 (corrective) span.
FIVE_ROLES = {ROLE_FIVE_FIRST, ROLE_FIVE_MID, ROLE_FIVE_LAST, ROLE_FIVE_SIMPLE}


def allowed_patterns(role: str) -> tuple[str, ...]:
    return ROLE_ALLOWED_PATTERNS[role]


def is_five_role(role: str) -> bool:
    return role in FIVE_ROLES


# ---------------------------------------------------------------------------
# Hard-rule helpers
# ---------------------------------------------------------------------------

def leg_size(c) -> float:
    return abs(c.end_price - c.start_price)


def _beyond(price: float, reference: float, direction: str) -> bool:
    """True if `price` extends further than `reference` in `direction`."""
    return price > reference if direction == "up" else price < reference


def _opposite(direction: str) -> str:
    return "down" if direction == "up" else "up"


def _retrace_frac(mover, base) -> float:
    """Fraction of `base`'s leg that `mover` retraces, mover starting at
    base's endpoint."""
    size = leg_size(base)
    if size == 0:
        return 1.0
    return abs(mover.end_price - base.end_price) / size


# ---- impulse / diagonal rules ---------------------------------------------

def w2_retrace_le_100(components, ctx) -> bool:
    return _retrace_frac(components[1], components[0]) < 1.0


def w3_not_shortest(components, ctx) -> bool:
    sizes = [leg_size(components[0]), leg_size(components[2]), leg_size(components[4])]
    return sizes[1] != min(sizes)


def w3_beyond_w1_end(components, ctx) -> bool:
    w3 = components[2]
    if w3.open:
        return True  # undecidable while W3 is underway (may yet exceed)
    return _beyond(w3.end_price, components[0].end_price, components[0].direction)


def w4_no_overlap(components, ctx) -> bool:
    """W4 must not enter W1's price territory, with an ATR-scaled tolerance
    for wicky data (DESIGN.md §3)."""
    eps = ctx.get("atr_epsilon", 0.0)
    w1, w4 = components[0], components[3]
    boundary = w1.end_price
    direction = w1.direction
    tol_boundary = boundary - eps if direction == "up" else boundary + eps
    worst = w4.lo if direction == "up" else w4.hi
    return _beyond(worst, tol_boundary, direction) or worst == tol_boundary


def w3_lt_w1(components, ctx) -> bool:
    return leg_size(components[2]) < leg_size(components[0])


def w4_lt_w2(components, ctx) -> bool:
    return leg_size(components[3]) < leg_size(components[1])


def w5_lt_w3(components, ctx) -> bool:
    return leg_size(components[4]) < leg_size(components[2])


def diagonal_converges(components, ctx) -> bool:
    """Cheap proxy for 0-2-4 / 1-3-5 trendline convergence: the final leg
    is narrower than the first (a contracting wedge narrows toward its
    apex). Full regression fit is a channel-fit guideline concern, not a
    hard-rule concern."""
    return leg_size(components[-1]) < leg_size(components[0])


# ---- zigzag / flat rules ----------------------------------------------

def b_retrace_lt_100_of_a(components, ctx) -> bool:
    return _retrace_frac(components[1], components[0]) < 1.0


def b_ge_90pct_a(components, ctx) -> bool:
    return _retrace_frac(components[1], components[0]) >= 0.90


def b_le_262pct_a(components, ctx) -> bool:
    return _retrace_frac(components[1], components[0]) <= 2.618


def b_beyond_a_start(components, ctx) -> bool:
    a, b = components[0], components[1]
    if b.open:
        return True  # undecidable while B is underway
    return _beyond(b.end_price, a.start_price, _opposite(a.direction))


def c_beyond_a_end(components, ctx) -> bool:
    a, c = components[0], components[2]
    if c.open:
        return True  # undecidable while C is underway (may yet exceed A's end)
    return _beyond(c.end_price, a.end_price, a.direction)


def c_short_of_a_end(components, ctx) -> bool:
    a, c = components[0], components[2]
    if c.open:
        # An open C violates "short of A's end" only once it has actually
        # traded beyond it (unrecoverable); delegating to c_beyond_a_end
        # here would inherit its "undecidable while open -> True" convention
        # and make a running flat unparseable while C is underway.
        return not _beyond(c.end_price, a.end_price, a.direction)
    return not c_beyond_a_end(components, ctx)


# ---- triangle rules ------------------------------------------------------

def c_within_a_end(components, ctx) -> bool:
    a, c = components[0], components[2]
    return not _beyond(c.end_price, a.end_price, a.direction)


def d_within_b_end(components, ctx) -> bool:
    b, d = components[1], components[3]
    return not _beyond(d.end_price, b.end_price, b.direction)


def e_within_c_end(components, ctx) -> bool:
    c, e = components[2], components[4]
    return not _beyond(e.end_price, c.end_price, c.direction)


def c_beyond_a_end_leg(components, ctx) -> bool:
    return c_beyond_a_end(components, ctx)


def d_beyond_b_end(components, ctx) -> bool:
    b, d = components[1], components[3]
    if d.open:
        return True  # undecidable while D is underway
    return _beyond(d.end_price, b.end_price, b.direction)


def e_beyond_c_end(components, ctx) -> bool:
    c, e = components[2], components[4]
    if e.open:
        return True  # undecidable while E is underway
    return _beyond(e.end_price, c.end_price, c.direction)


def triangle_not_diverging(components, ctx) -> bool:
    """Reject only clear divergence on both trailing legs -- both
    contracting and barrier triangles pass (DESIGN.md §3 finding 4)."""
    b_leg, d_leg = leg_size(components[1]), leg_size(components[3])
    c_leg, e_leg = leg_size(components[2]), leg_size(components[4])
    both_diverge = d_leg > b_leg * 1.05 and e_leg > c_leg * 1.05
    return not both_diverge


def triangle_diverging(components, ctx) -> bool:
    b_leg, d_leg = leg_size(components[1]), leg_size(components[3])
    c_leg, e_leg = leg_size(components[2]), leg_size(components[4])
    return d_leg > b_leg and e_leg > c_leg


# ---- combination rules -----------------------------------------------

def combination_composition(components, ctx) -> bool:
    """At most one zigzag, at most one flat, at most one triangle among
    the named corrective components, and a triangle only as the final
    component (DESIGN.md §3 finding 7)."""
    named = [c for c in components if getattr(c, "pattern", None) is not None]
    zigzags = sum(1 for c in named if c.pattern == "zigzag")
    flats = sum(1 for c in named if c.pattern in ("flat_regular", "flat_expanded", "flat_running"))
    triangles = [(idx, c) for idx, c in enumerate(components) if getattr(c, "pattern", None) in ("triangle_contract", "triangle_expand")]
    if zigzags > 1 or flats > 1 or len(triangles) > 1:
        return False
    if triangles and triangles[0][0] != len(components) - 1:
        return False
    return True


# ---------------------------------------------------------------------------
# Pattern specs
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Component:
    slot: str          # "5" or "3" -- span shape required
    role: str          # role constant above, governs which patterns are legal
    fixed: str | None = None  # if set, this slot MUST be exactly this pattern name


@dataclass(frozen=True)
class PatternSpec:
    name: str
    components: tuple[Component, ...]
    hard_rules: tuple[Rule, ...]
    prior: float


GRAMMAR: dict[str, PatternSpec] = {}


def _reg(name, components, hard_rules, prior):
    GRAMMAR[name] = PatternSpec(name, tuple(components), tuple(hard_rules), prior)


_reg("impulse", [
    Component("5", ROLE_FIVE_FIRST),
    Component("3", ROLE_THREE_PLAIN),
    Component("5", ROLE_FIVE_MID),
    Component("3", ROLE_THREE_TRI_OK),
    Component("5", ROLE_FIVE_LAST),
], [w2_retrace_le_100, w3_not_shortest, w3_beyond_w1_end, w4_no_overlap], 0.30)

_reg("diagonal_leading", [
    Component("5", ROLE_FIVE_SIMPLE),
    Component("3", ROLE_THREE_DIAGONAL),
    Component("5", ROLE_FIVE_SIMPLE),
    Component("3", ROLE_THREE_DIAGONAL),
    Component("5", ROLE_FIVE_SIMPLE),
], [w2_retrace_le_100, w3_lt_w1, w4_lt_w2, w5_lt_w3, w3_not_shortest, diagonal_converges], 0.02)

_reg("diagonal_ending", [
    Component("3", ROLE_THREE_DIAGONAL),
    Component("3", ROLE_THREE_DIAGONAL),
    Component("3", ROLE_THREE_DIAGONAL),
    Component("3", ROLE_THREE_DIAGONAL),
    Component("3", ROLE_THREE_DIAGONAL),
], [w2_retrace_le_100, w3_lt_w1, w4_lt_w2, w5_lt_w3, w3_not_shortest, diagonal_converges], 0.03)

_reg("zigzag", [
    Component("5", ROLE_FIVE_FIRST),
    Component("3", ROLE_THREE_TRI_OK),
    Component("5", ROLE_FIVE_LAST),
], [b_retrace_lt_100_of_a], 0.25)

_reg("flat_regular", [
    Component("3", ROLE_THREE_PLAIN),
    Component("3", ROLE_THREE_TRI_OK),
    Component("5", ROLE_FIVE_LAST),
], [b_ge_90pct_a, b_le_262pct_a], 0.07)

_reg("flat_expanded", [
    Component("3", ROLE_THREE_PLAIN),
    Component("3", ROLE_THREE_TRI_OK),
    Component("5", ROLE_FIVE_LAST),
], [b_beyond_a_start, b_le_262pct_a, c_beyond_a_end], 0.10)

_reg("flat_running", [
    Component("3", ROLE_THREE_PLAIN),
    Component("3", ROLE_THREE_TRI_OK),
    Component("5", ROLE_FIVE_LAST),
], [b_beyond_a_start, b_le_262pct_a, c_short_of_a_end], 0.02)

_reg("triangle_contract", [
    Component("3", ROLE_TRIANGLE_LEG),
    Component("3", ROLE_TRIANGLE_LEG),
    Component("3", ROLE_TRIANGLE_LEG),
    Component("3", ROLE_TRIANGLE_LEG),
    Component("3", ROLE_TRIANGLE_E),
], [c_within_a_end, d_within_b_end, e_within_c_end, triangle_not_diverging], 0.06)

_reg("triangle_expand", [
    Component("3", ROLE_TRIANGLE_LEG),
    Component("3", ROLE_TRIANGLE_LEG),
    Component("3", ROLE_TRIANGLE_LEG),
    Component("3", ROLE_TRIANGLE_LEG),
    Component("3", ROLE_TRIANGLE_LEG),
], [c_beyond_a_end_leg, d_beyond_b_end, e_beyond_c_end, triangle_diverging], 0.01)

_reg("double_zigzag", [
    Component("3", ROLE_THREE_PLAIN, fixed="zigzag"),
    Component("3", ROLE_THREE_XLINK),
    Component("3", ROLE_THREE_PLAIN, fixed="zigzag"),
], [], 0.04)

_reg("triple_zigzag", [
    Component("3", ROLE_THREE_PLAIN, fixed="zigzag"),
    Component("3", ROLE_THREE_XLINK),
    Component("3", ROLE_THREE_PLAIN, fixed="zigzag"),
    Component("3", ROLE_THREE_XLINK),
    Component("3", ROLE_THREE_PLAIN, fixed="zigzag"),
], [], 0.005)

_reg("double_three", [
    Component("3", ROLE_THREE_PLAIN),
    Component("3", ROLE_THREE_XLINK),
    Component("3", ROLE_THREE_TRI_OK),
], [combination_composition], 0.03)

_reg("triple_three", [
    Component("3", ROLE_THREE_PLAIN),
    Component("3", ROLE_THREE_XLINK),
    Component("3", ROLE_THREE_PLAIN),
    Component("3", ROLE_THREE_XLINK),
    Component("3", ROLE_THREE_TRI_OK),
], [combination_composition], 0.005)


def patterns_for_role(role: str) -> list[PatternSpec]:
    return [GRAMMAR[name] for name in allowed_patterns(role) if name in GRAMMAR]


def normalized_priors(role: str) -> dict[str, float]:
    """Priors normalized within the conditioning class named by `role`
    (DESIGN.md §5: pi(pattern | family, role) must sum to 1 within class)."""
    specs = patterns_for_role(role)
    total = sum(s.prior for s in specs)
    if total <= 0:
        return {s.name: 0.0 for s in specs}
    return {s.name: s.prior / total for s in specs}


# A pattern's own identity (not the slot it happens to fill) determines
# which prior universe it draws from: is *this pattern* an impulsive :5
# shape or a corrective :3 shape. Used to normalize priors independent of
# which role/slot ultimately consumes the parse (DESIGN.md §5's per-class
# normalization, simplified to two universes -- see parser.py docstring
# for why memo cells are role-agnostic).
FIVE_PATTERNS = ("impulse", "diagonal_leading", "diagonal_ending")

ROLE_FIVE_ANY = "FIVE_ANY"
ROLE_ALLOWED_PATTERNS[ROLE_FIVE_ANY] = FIVE_PATTERNS

GLOBAL_FIVE_PRIORS = normalized_priors(ROLE_FIVE_ANY)
GLOBAL_THREE_PRIORS = normalized_priors(ROLE_THREE_TRI_OK)


def is_five_pattern(name: str) -> bool:
    return name in FIVE_PATTERNS
