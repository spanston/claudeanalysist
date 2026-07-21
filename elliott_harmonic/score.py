"""Ratio-harmony scoring for HEW fractal candidates.

 harmony = weighted mean of aspect fits x multiplicative penalties

Aspects (weights):
  s3   (3.0)  (iii)/(i) vs the 176.4%+ projection clusters      [complete (iii)]
  s5   (2.0)  (v)/( (i)+(iii) ) vs the (v) ratio distribution   [complete (v)]
  sc   (1.5)  mean (c)/(a) fit inside the realized impulses
  salt (1.5)  numeric alternation: (ii)% + (iv)% ~ [0.80, 1.20]  [complete (iv)]

Open candidates: unrealized aspects score a neutral 0.5, so a young count is
neither inflated nor crushed for aspects the data cannot yet testify about.
Penalties: rule-5 (v) failure, rare 172-176.4% (iii) band, sub-equality (c),
(iv) approaching the (b)-of-(iii) barrier ("normally does not reach").
"""

from __future__ import annotations

from . import ratios as R
from .fractals import Fractal, wave_lengths


def score_fractal(fr: Fractal, pivots) -> dict:
    """Score a rule-valid candidate. Returns {harmony, aspects, penalties}.

    All four aspects always enter the weighted mean; an aspect that is not
    yet realized (open right edge) scores a NEUTRAL 0.5, so open candidates
    are neither inflated (renormalization would only ever remove their
    weakest aspects) nor crushed for being young."""
    L = wave_lengths(fr, pivots)
    aspects: dict[str, float] = {}
    weights = {"s3": 3.0, "s5": 2.0, "sc": 1.5, "salt": 1.5}

    if "iii" in L:
        r3 = L["iii"] / L["i"]
        aspects["s3"] = R.ratio_fit(r3, R.W3_CLUSTERS, tol=0.06)
    else:
        aspects["s3"] = 0.5
    if "v" in L:
        r5 = L["v"] / (L["i"] + L["iii"])
        aspects["s5"] = R.ratio_fit(r5, R.V_RATIOS, tol=0.12)
    else:
        aspects["s5"] = 0.5

    ca_fits = []
    for a, c in (("a1", "c1"), ("a3", "c3"), ("a5", "c5")):
        if a in L and c in L and L[a] > 0:
            ca_fits.append(R.ratio_fit(L[c] / L[a], R.C_RATIOS, tol=0.06))
    aspects["sc"] = sum(ca_fits) / len(ca_fits) if ca_fits else 0.5

    if "iv" in L:
        alt_sum = L["ii"] / L["i"] + L["iv"] / L["iii"]
        aspects["salt"] = R.alternation_fit(alt_sum)
    else:
        aspects["salt"] = 0.5

    base = sum(aspects[k] * weights[k] for k in weights) / sum(weights.values())

    penalties: dict[str, float] = {}
    # Rule 5 soft: (v) failed to exceed the (iii) extreme.
    if "v" in L:
        d = 1 if fr.direction == "up" else -1
        if d * pivots[fr.end_v].price <= d * pivots[fr.end_iii].price:
            penalties["v_failure"] = 0.80
    # Rare (iii) band 172-176.4%.
    if "iii" in L and L["iii"] < R.W3_MIN * L["i"]:
        penalties["iii_rare_band"] = 0.85
    # (iii) structurally complete at the provisional edge but ratio-deficient
    # (< 172%): a three-leg "impulse" that fails the projection requirement is
    # corrective per the book -- don't let it outrank a corrective reading.
    # (Mid-leg (iii)s are exempt: a partial r3 below the floor is normal.)
    if not fr.complete and fr.realized_end == fr.end_iii and "iii" in L:
        if L["iii"] < R.W3_RARE_FLOOR * L["i"]:
            penalties["iii_below_floor_unproven"] = 0.70
    # Sub-equality (c) inside (i)/(v) (tolerated 85.4-100%, penalized).
    for a, c, tag in (("a1", "c1", "c1_sub_a1"), ("a5", "c5", "c5_sub_a5")):
        if a in L and c in L and L[c] < L[a]:
            penalties[tag] = 0.90
    # (iv) approaching the (b)-of-(iii) barrier: gap < 5% of (iii).
    if "iv" in L and "b3" in L:
        d = 1 if fr.direction == "up" else -1
        gap = d * (pivots[fr.end_iv].price - pivots[fr.b3_end].price)  # > 0 by rule 4
        if gap < 0.05 * L["iii"]:
            penalties["iv_near_b3_barrier"] = 0.85

    harmony = base
    for pen in penalties.values():
        harmony *= pen
    return {"harmony": round(harmony, 4), "aspects": aspects, "penalties": penalties}


def pick_best(candidates: list[Fractal], pivots,
               recency_band: float = 0.05) -> tuple[Fractal | None, list[tuple[Fractal, dict]]]:
    """Score all candidates; prefer the latest realized_end among those within
    `recency_band` harmony of the best (the actionable count is the recent one).
    Returns (best, [(fractal, score), ...] sorted by realized_end desc)."""
    scored = [(fr, score_fractal(fr, pivots)) for fr in candidates]
    scored = [(fr, sc) for fr, sc in scored if sc["harmony"] > 0]
    if not scored:
        return None, []
    best_h = max(sc["harmony"] for _, sc in scored)
    pool = [(fr, sc) for fr, sc in scored if sc["harmony"] >= best_h - recency_band]
    pool.sort(key=lambda t: (t[0].realized_end, t[1]["harmony"]), reverse=True)
    best = pool[0][0]
    rest = sorted(scored, key=lambda t: (t[0].realized_end, t[1]["harmony"]), reverse=True)
    return best, rest
