# Horizon-adaptive degree selection — design

Date: 2026-07-20 · Status: approved-in-session (auto mode; user asked to brainstorm + implement)

## Problem

The engine finds the best 2-degree count over a user-supplied window
(`--period`, default 10y). On a 10y window the degree-1 waves it labels span
~1–2 years each — useless context for a swing trader holding 3–12 months.
Which two degrees are *relevant* is a function of the trading horizon, and
today nothing in the engine takes that into account.

## Goal

Given a target holding period (e.g. `--horizon 6m`), the engine picks the
analysis window such that the count it returns has **degree-1 waves whose
typical duration matches the holding period**, with degree 2 as the larger
context. "Optimal" is made measurable: minimize the gap between the
*realized* median degree-1 wave duration (from the engine's own parse) and
the requested horizon.

## Assumptions (decided in-session, auto mode)

- **The traded degree is degree 1.** The report's position/invalidation/
  targets live on the open edge; a swing trader acts on the degree-1 open
  wave and uses degree 2 as context. The horizon therefore targets degree-1
  durations.
- **Durations are measured in bars** (trading days), since the engine works
  on daily bars and pivots carry bar indices. Horizon syntax: `Nd` (days),
  `Nw` (weeks ×5), `Nm` (months ×21), `Ny` (years ×252). For 7-day markets
  (crypto) the user passes days (`90d`), which needs no calendar assumption.
- **`--period` stays as-is** (default 10y) for backward compatibility; in
  horizon mode it becomes the *source pool* the window is sliced from.
  Horizon mode is opt-in via `--horizon`.

## Approaches considered

**A. Static horizon→period mapping** (3m→"1y", 6m→"2y", 1y→"5y").
Dead simple, but blind: the pivot budget is fixed at 80–150 monowaves, so
monowave *time* size scales with the window, and the realized degree-1
duration also depends on where anchors land and how the parse partitions the
window — per instrument. A static table can never verify it hit the target.
Rejected.

**B. Closed-loop window refinement (chosen).** Fetch the long history once;
run the normal pipeline on the last W bars; measure the realized median
duration of the winning root's *closed* degree-1 components; rescale W by
horizon/measured; repeat up to 2 refinements. This is instrument-adaptive
and self-verifying: the same parse that produces the count also measures
whether the degrees came out at the right scale.

Why it converges: at a fixed monowave budget, monowave duration scales
~linearly with window length and degree-1 span-in-monowaves is roughly
scale-free (the grammar doesn't change with window size), so
`d1(W) ≈ c·W` and one or two ratio corrections land in the tolerance band.

**C. Multi-window tournament** (run 4–5 windows, keep the best horizon fit).
Thorough but ~4× the compute for marginal gain over B, since d1(W) is
monotone in W. Rejected (YAGNI).

## Design (approach B)

New module `elliott/horizon.py`:

- `parse_horizon(s) -> int` — "6m"→126 bars etc.; clear error on bad input.
- `INITIAL_WINDOW_MULT = 8` — first guess W₀ = 8×H. A degree-2 impulse has
  ~5 degree-1 components, but the root need not span the whole window and
  components average more than the minimum 5 monowaves; 8× is a sane
  starting point precisely because the loop corrects it empirically.
- `WINDOW_MIN_BARS = 250` — below ~1y of daily bars the 80–150 monowave
  budget is unreachable and the count starves.
- `closed_d1_durations(root) -> list[int]` — `end_bar - start_bar` for each
  closed degree-1 child of the root. The open right-edge child is excluded:
  it is truncated by definition and would understate durations.
- `next_window(current, measured_median, horizon, available) -> int | None`
  — ratio rescale `current × horizon/median`, clamped to
  [WINDOW_MIN_BARS, available]; `None` when measured is within
  [0.75, 1.33]×H (stop) — the band is wide because the median is over only
  2–5 components.
- `analyze_window(series, ticker, run_date, k_top)` — the pipeline core
  (calibrate → null → memo → tournament → report), extracted so `cli.run`
  and the horizon loop share one implementation.
- `run_for_horizon(ticker, horizon, period="10y", k_top, max_iters=3)` —
  fetch once, slice the source series to the last W bars per iteration, loop
  refine; keep the report of the best-fitting iteration (log-distance to H)
  as the final result.

Stop conditions: tolerance hit; iteration cap; `no_clean_count` (no root →
nothing to measure — report as-is, a legitimate "no structure at your
horizon's scale" answer); history clamp (W ≥ available → run once, warn).

### Report changes

`report["meta"]["horizon"]` (present only in horizon mode):

```json
{
  "input": "6m", "target_bars": 126, "window_bars": 1008,
  "degree1_durations_bars": [..], "degree1_median_bars": 124,
  "fit": "ok | unresolved | no_clean_count | history_limited",
  "iterations": [{"window_bars": 1008, "median_d1_bars": 62, "decision": "refine"}, ...]
}
```

A `horizon_fit_unresolved` entry goes into `warnings[]` when the band was
not reached within the iteration cap.

### CLI

`--horizon 6m` added; with it, `--period` is the source pool to slice from
(default 10y). Output filenames become `<TICKER>_h<horizon>.json/.svg` so
horizon runs don't clobber period runs. Summary prints the fit line.

## Error handling

- Bad horizon string → `SystemExit` with usage examples.
- `no_clean_count` mid-loop → stop, keep that report, fit `no_clean_count`.
- History shorter than W₀ → clamp, fit flag `history_limited` + warning.

## Testing

`elliott/tests/test_horizon.py`:

- `parse_horizon`: valid/invalid forms.
- `next_window`: rescale math, clamping, tolerance stop.
- `closed_d1_durations`: synthetic root with closed + open children (open
  excluded).
- End-to-end: `run_for_horizon` with `fetch_ohlcv` monkeypatched to a
  deterministic synthetic multi-scale series; assert ≤3 iterations,
  `meta.horizon` present and consistent, and the final window moves in the
  direction the first measurement implies.

Existing suite must stay green (backward compatibility of `--period` mode).
