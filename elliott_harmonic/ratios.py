"""Harmonic Elliott Wave ratio tables and fit helpers.

Distilled from Ian Copsey, "Fractal Forecasting" (see
.agents/skills/harmonic-elliott-core/SKILL.md for the full spec with line
references). All projection ratios are expressed as multipliers; retracements
as fractions of the preceding move.
"""

from __future__ import annotations

# --- Wave (iii) = |Wave (i)| x ratio, projected from the (ii) extreme -------
# Hard minimum 176.4%; 172-176.4% tolerated only on rare occasions.
W3_MIN = 1.764
W3_RARE_FLOOR = 1.72
# Cluster values: general form X23.6 / X38.2 / X61.8 - X98.7 (X += 100).
W3_CLUSTERS = [
    1.764, 1.854, 1.902, 1.987,
    2.236, 2.382, 2.618, 2.764, 2.854, 2.987,
    3.236, 3.382, 3.618, 3.764, 3.854, 3.987,
    4.236, 4.382, 4.618, 4.764, 4.854, 4.987,
]

# --- Wave (c) = |Wave (a)| x ratio, projected from the (b) extreme ----------
# Subservient to (iii) projections. Most common: 109.2 / 114.6 / 123.6, equality.
# Above 100% the table continues in the X23.6/X38.2/X61.8-X98.7 cluster form
# (Copsey: "etc."; spreadsheets show 195.4 / 223.6 / 261.8 in use).
C_RATIOS = [
    0.618, 0.667, 0.764, 0.854, 0.91, 0.944, 0.987,
    1.0, 1.021, 1.056, 1.092, 1.146, 1.236, 1.333, 1.382, 1.414,
    1.5, 1.586, 1.618, 1.667, 1.764, 1.854, 1.902, 1.954, 1.987,
    2.0, 2.236, 2.382, 2.618, 2.764, 2.854, 2.987,
]

# --- Wave (v) = |(i)+(iii)| x ratio, projected from the (iv) extreme --------
# A distribution, not a rule: average ~50%, min ~23.6%, normal max 76.4%.
V_RATIOS = [0.236, 0.30, 0.333, 0.382, 0.414, 0.50, 0.586, 0.618, 0.667, 0.764, 0.854]
V_AVG = 0.50
V_MAX_NORMAL = 0.764
# Same-degree reuse: (v) ~ 223.6% x (i) also observed.
V_OF_I = 2.236

# --- Retracement set, valid for (ii), (iv), (b), (x) -------------------------
RETRACEMENTS = [
    0.09, 0.146, 0.236, 0.333, 0.382, 0.414, 0.50, 0.586, 0.618,
    0.667, 0.764, 0.854, 0.902, 0.944, 0.954, 0.966, 0.979, 0.987, 1.0,
]

# --- Positional caps ---------------------------------------------------------
# Wave (b) of Wave (iii): max 76.4-85.4%, occasionally 90%.
B_OF_III_CAP = 0.854
B_OF_III_MAX = 0.90
# Any (b) must not breach the start of its (a) (A-B-C fractal rule).
B_MAX = 1.0
# Wave (c) of (iii) >= wave (a) of (iii); sub-equality elsewhere tolerated per
# the (c) projection table (its floor is 61.8%) but penalized in scoring.
C_OF_III_MIN = 1.0
C_HARD_MIN = 0.60   # below this the count is rejected outright

# --- Numeric alternation: (ii)% + (iv)% --------------------------------------
ALT_TREND = (0.80, 1.00)     # trending moves
ALT_CORRECTIVE = (1.00, 1.20)  # corrective structures
ALT_ACCEPT = (0.80, 1.20)    # union used for scoring
ALT_FLOOR = (0.45, 1.65)     # linear decay to 0 outside ALT_ACCEPT


def nearest(value: float, table: list[float]) -> float:
    """The table value closest to `value`."""
    return min(table, key=lambda t: abs(value - t))


def rel_dist(value: float, target: float) -> float:
    """Relative distance from `value` to `target` (0 = exact hit)."""
    if target == 0:
        return float("inf")
    return abs(value - target) / abs(target)


def ratio_fit(value: float, table: list[float], tol: float = 0.08) -> float:
    """1.0 on an exact table hit, decaying linearly to 0.0 at relative
    distance `tol` from the nearest table value."""
    d = rel_dist(value, nearest(value, table))
    return max(0.0, 1.0 - d / tol)


def alternation_fit(sum_pct: float) -> float:
    """Fit of the (ii)+(iv) retracement sum: 1.0 inside [0.80, 1.20],
    linear decay to 0.0 at [0.45, 1.65]."""
    lo, hi = ALT_ACCEPT
    flo, fhi = ALT_FLOOR
    if lo <= sum_pct <= hi:
        return 1.0
    if sum_pct < lo:
        return max(0.0, (sum_pct - flo) / (lo - flo))
    return max(0.0, (fhi - sum_pct) / (fhi - hi))
