"""Soft-guideline scoring: log-likelihood ratios against a fitted null
model. DESIGN.md §5.

Every guideline ratio (retracement, extension, leg-size comparison) is
scored as a log-likelihood ratio against a null model of "no wave
structure" -- individual monowave leg sizes i.i.d. LogNormal, fit once from
the actual pivot sequence. Under the null, ln(leg_a / leg_b) for two legs
is Normal(0, 2*sigma_leg^2) (difference of two i.i.d. normals), so this
null has a closed form and needs no Monte Carlo. A guideline earns a
*positive* score only when the data fits its canonical ideal better than
chance explains it -- this is what stops guideline-rich patterns (the
impulse) from being taxed for carrying more guidelines than a permissive
pattern with none (DESIGN.md's math-audit fix for the v1 bias).

Not modeled in v1 (documented, not silently dropped): depth-of-wave-4 vs
the prior lesser-degree fourth wave, post-triangle thrust, and fifth-wave
/ diagonal throw-over. Each needs look-ahead context beyond the node being
scored (a sibling that hasn't been assembled yet, or sub-structure below
the degree floor) and is left for a later iteration.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .grammar import leg_size


# ---------------------------------------------------------------------------
# Null model
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class NullModel:
    leg_sigma: float           # sigma of ln(monowave leg size in price units)
    duration_sigma: float      # sigma of ln(monowave leg duration in bars)
    leg_log_mean: float = 0.0       # mean of ln(leg size) -- for absolute leg densities
    duration_log_mean: float = 0.0  # mean of ln(duration) -- for absolute duration densities

    @property
    def ratio_null_var(self) -> float:
        return 2.0 * self.leg_sigma ** 2

    @property
    def duration_null_var(self) -> float:
        return 2.0 * self.duration_sigma ** 2


# Floor on fitted sigma: a near-zero variance would make the null density
# collapse to a spike and any off-peak observation would score as an
# unbounded LLR. 0.15 (roughly +/-16% typical adjacent-leg variation) is a
# conservative floor well below what real price data produces.
_MIN_SIGMA = 0.15
_LLR_CLIP = 8.0  # bound any single guideline's contribution before weighting


def _fit_log_mean_sigma(values: list[float]) -> tuple[float, float]:
    logs = [math.log(v) for v in values if v > 0]
    if len(logs) < 2:
        return 0.0, 0.35  # fallback: a plausible generic spread
    mean = sum(logs) / len(logs)
    var = sum((x - mean) ** 2 for x in logs) / (len(logs) - 1)
    return mean, max(math.sqrt(var), _MIN_SIGMA)


def _clip(x: float) -> float:
    return max(-_LLR_CLIP, min(_LLR_CLIP, x))


def fit_null_model(pivots) -> NullModel:
    sizes = [abs(pivots[i + 1].price - pivots[i].price) for i in range(len(pivots) - 1)]
    durations = [max(pivots[i + 1].bar - pivots[i].bar, 1) for i in range(len(pivots) - 1)]
    leg_mean, leg_sigma = _fit_log_mean_sigma(sizes)
    dur_mean, dur_sigma = _fit_log_mean_sigma([float(d) for d in durations])
    return NullModel(
        leg_sigma=leg_sigma, duration_sigma=dur_sigma,
        leg_log_mean=leg_mean, duration_log_mean=dur_mean,
    )


def _log_gauss(u: float, mu: float, var: float) -> float:
    return -0.5 * math.log(2 * math.pi * var) - (u - mu) ** 2 / (2 * var)


def _null_ll(u: float, null_var: float) -> float:
    return _log_gauss(u, 0.0, null_var)


def _point_ll(ratio: float, ideal: float, sigma_g: float, null_var: float) -> float:
    if ratio <= 0:
        return -_LLR_CLIP
    u = math.log(ratio)
    u_star = math.log(ideal)
    return _clip(_log_gauss(u, u_star, sigma_g ** 2) - _null_ll(u, null_var))


def _two_point_ll(ratio: float, ideals: tuple[float, float], sigma_g: float,
                    null_var: float) -> float:
    """Best fit against either of two accepted ideals (e.g. W3 extends to
    1.618 OR 2.618). A true mixture-density log would be more rigorous;
    taking the max is the pragmatic v1 choice and matches how chartists
    actually score against multiple accepted Fibonacci targets."""
    return max(_point_ll(ratio, i, sigma_g, null_var) for i in ideals)


def _interval_ll(ratio: float, lo: float, hi: float, sigma_g: float,
                   null_var: float) -> float:
    if ratio <= 0:
        return -_LLR_CLIP
    u, u1, u2 = math.log(ratio), math.log(lo), math.log(hi)
    d = 0.0 if u1 <= u <= u2 else min(abs(u - u1), abs(u - u2))
    z = (u2 - u1) + sigma_g * math.sqrt(2 * math.pi)
    log_fg = -(d ** 2) / (2 * sigma_g ** 2) - math.log(z)
    return _clip(log_fg - _null_ll(u, null_var))


def _binary_ll(condition: bool, hit_prob: float = 0.8, null_prob: float = 0.5) -> float:
    """Pseudo-LLR for a yes/no guideline (e.g. alternation): reward
    `hit_prob` under a well-formed count vs `null_prob` under random
    structure."""
    p = hit_prob if condition else (1 - hit_prob)
    return math.log(p) - math.log(null_prob if condition else (1 - null_prob))


def _continuous_bonus(value_0_1: float, scale: float = 2.0) -> float:
    """Reward a [0,1]-valued fit statistic (e.g. R^2) centered at the null
    expectation of 0.5."""
    return scale * (value_0_1 - 0.5)


# ---------------------------------------------------------------------------
# Guideline registry: pattern name -> weighted LLR contributions
# ---------------------------------------------------------------------------

def _r2_of_three_points(xs: list[float], ys: list[float]) -> float:
    n = len(xs)
    if n < 3:
        return 0.5
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    syy = sum((y - my) ** 2 for y in ys)
    if sxx == 0 or syy == 0:
        return 0.5
    r = sxy / math.sqrt(sxx * syy)
    return r ** 2


def _channel_fit(components, anchor_idx=(0, 2, 4)) -> float:
    xs = [float(components[i].end_bar) for i in anchor_idx]
    ys = [components[i].end_price for i in anchor_idx]
    return _r2_of_three_points(xs, ys)


_SHARP = {"zigzag", "double_zigzag", "triple_zigzag"}
_SIDEWAYS = {"flat_regular", "flat_expanded", "flat_running",
             "triangle_contract", "triangle_expand", "double_three", "triple_three"}


def _character(c) -> str | None:
    p = getattr(c, "pattern", None)
    if p in _SHARP:
        return "sharp"
    if p in _SIDEWAYS:
        return "sideways"
    return None


def score_impulse(components, null: NullModel) -> float:
    w1, w2, w3, w4, w5 = components
    total = 0.0
    total += 3.0 * _point_ll(leg_size(w2) / leg_size(w1) if leg_size(w1) else 1.0,
                               0.55, 0.25, null.ratio_null_var)  # W2 retrace, centered in 0.5-0.618
    total += 3.0 * _two_point_ll(leg_size(w3) / leg_size(w1) if leg_size(w1) else 1.0,
                                   (1.618, 2.618), 0.30, null.ratio_null_var)
    total += 1.5 * _point_ll(leg_size(w4) / leg_size(w3) if leg_size(w3) else 1.0,
                               0.382, 0.30, null.ratio_null_var)
    total += 1.5 * _two_point_ll(leg_size(w5) / leg_size(w1) if leg_size(w1) else 1.0,
                                   (1.0, 0.618), 0.30, null.ratio_null_var)
    c2, c4 = _character(w2), _character(w4)
    if c2 and c4:
        total += 1.2 * _binary_ll(c2 != c4)
    total += 1.0 * _continuous_bonus(_channel_fit(components))
    d1 = max(w1.end_bar - w1.start_bar, 1)
    d3 = max(w3.end_bar - w3.start_bar, 1)
    d5 = max(w5.end_bar - w5.start_bar, 1)
    total += 0.4 * _interval_ll(max(d1, d3, d5) / max(min(d1, d3, d5), 1), 1.0, 10.0,
                                  0.5, null.duration_null_var)
    return total


def score_diagonal(components, null: NullModel) -> float:
    # Contraction is already a hard rule; the guideline layer only rewards
    # how *evenly* the pattern contracts (W3/W1, W4/W2, W5/W3 all similar).
    ratios = [
        leg_size(components[2]) / leg_size(components[0]) if leg_size(components[0]) else 1.0,
        leg_size(components[3]) / leg_size(components[1]) if leg_size(components[1]) else 1.0,
        leg_size(components[4]) / leg_size(components[2]) if leg_size(components[2]) else 1.0,
    ]
    return 1.5 * sum(_point_ll(r, 0.7, 0.35, null.ratio_null_var) for r in ratios) / len(ratios)


def score_zigzag(components, null: NullModel) -> float:
    a, b, c = components
    total = 0.0
    total += 2.0 * _interval_ll(leg_size(b) / leg_size(a) if leg_size(a) else 1.0,
                                  0.38, 0.79, 0.25, null.ratio_null_var)
    total += 2.0 * _two_point_ll(leg_size(c) / leg_size(a) if leg_size(a) else 1.0,
                                   (1.0, 1.618), 0.30, null.ratio_null_var)
    return total


def score_flat(components, null: NullModel, expanded: bool = False, running: bool = False) -> float:
    a, b, c = components
    total = 0.0
    b_ratio = leg_size(b) / leg_size(a) if leg_size(a) else 1.0
    if expanded:
        total += 2.0 * _interval_ll(b_ratio, 1.236, 1.382, 0.20, null.ratio_null_var)
        total += 1.5 * _point_ll(leg_size(c) / leg_size(a) if leg_size(a) else 1.0,
                                   1.618, 0.30, null.ratio_null_var)
    elif running:
        total += 1.5 * _interval_ll(b_ratio, 1.0, 1.382, 0.25, null.ratio_null_var)
    else:
        total += 1.5 * _interval_ll(b_ratio, 0.90, 1.05, 0.20, null.ratio_null_var)
        total += 1.0 * _point_ll(leg_size(c) / leg_size(a) if leg_size(a) else 1.0,
                                   1.0, 0.30, null.ratio_null_var)
    return total


def score_triangle(components, null: NullModel) -> float:
    ratios = []
    for i in range(4):
        prev, cur = leg_size(components[i]), leg_size(components[i + 1])
        if prev > 0:
            ratios.append(cur / prev)
    if not ratios:
        return 0.0
    return 1.0 * sum(_point_ll(r, 0.618, 0.35, null.ratio_null_var) for r in ratios) / len(ratios)


def score_combination(components, null: NullModel) -> float:
    total = 0.0
    named = [c for c in components if getattr(c, "pattern", None) is not None]
    xlinks = [c for c in components[1::2]]  # linking waves sit at odd indices
    corrective_ws = [c for i, c in enumerate(components) if i % 2 == 0]
    for i in range(len(corrective_ws) - 1):
        w, x = corrective_ws[i], xlinks[i] if i < len(xlinks) else None
        if x is None:
            continue
        r = leg_size(x) / leg_size(w) if leg_size(w) else 1.0
        total += 1.0 * _interval_ll(r, 0.5, 0.79, 0.30, null.ratio_null_var)
    return total


GUIDELINE_SCORERS = {
    "impulse": score_impulse,
    "diagonal_leading": score_diagonal,
    "diagonal_ending": score_diagonal,
    "zigzag": score_zigzag,
    "flat_regular": lambda c, n: score_flat(c, n),
    "flat_expanded": lambda c, n: score_flat(c, n, expanded=True),
    "flat_running": lambda c, n: score_flat(c, n, running=True),
    "triangle_contract": score_triangle,
    "triangle_expand": score_triangle,
    "double_zigzag": score_combination,
    "triple_zigzag": score_combination,
    "double_three": score_combination,
    "triple_three": score_combination,
}


def score_guidelines(pattern_name: str, components, null: NullModel) -> float:
    scorer = GUIDELINE_SCORERS.get(pattern_name)
    if scorer is None:
        return 0.0
    return scorer(components, null)
