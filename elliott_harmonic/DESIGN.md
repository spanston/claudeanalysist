# Harmonic Elliott Wave Engine (v2) — Design

Engine v2 inherits v1's infrastructure (`elliott.data`, `elliott.pivots`,
`elliott.horizon` windowing) and replaces the classical CFG parser with the
Harmonic Elliott Wave model (Ian Copsey, *Fractal Forecasting*), distilled in
`.agents/skills/harmonic-elliott-{core,corrections,process}`.

## Pipeline

1. **Window**: `--horizon H` → last `clamp(8 × H_bars, 250, available)` bars
   (single pass; v1's refinement loop is unnecessary because candidates are
   ratio-gated, not pivot-budget-gated).
2. **Pivots**: `calibrate_pivots(target 30–70 monowaves)` — a HEW fractal is
   11–19 legs, so ~40-60 pivots over ~4y gives a-b-c granularity.
3. **Enumerate** (`fractals.py`): all `(start, c2, c4)` with c2/c4 ∈ {1,3,5}
   correction leg counts. Impulse waves (i),(iii),(v) are exactly 3 legs
   (a-b-c). Candidates may be *complete* ((v) end is a pivot, tail allowed) or
   *open* (right edge truncates inside (iii)/(iv)/(v)).
4. **Hard gates** — the six HEW rules + supporting rules:
   - R1 (ii) never beyond start of (i); R2 (iii) beyond (i) extreme;
     R3 (iii) never shortest; R4 (iv) never breaches (b)-of-(iii) extreme
     (replaces the classical overlap rule); R6 (iii) ≥ 176.4%×(i), rare
     tolerance 172–176.4% (flagged, penalized). R5 ((v) exceeds (iii)) is soft.
   - R1/R4 are evaluated on the extreme over *every pivot of the correction
     span*: an interior (ii) leg beyond the start of (i), or an interior (iv)
     leg beyond the (b)-of-(iii) extreme, invalidates even when the
     correction's endpoint holds.
   - (c) of (iii) ≥ (a) of (iii); (c) ≥ 60% of (a) inside (i)/(v) (the (c)
     projection table's floor is 61.8% — a hard 76.4% floor contradicts the
     source's own table); (b) never beyond start of (a); (b) of (iii) ≤ 90%.
   - Rules 2/6/c3 fire only on a *confirmed* (iii) (a reversal leg exists).
     At the provisional right edge (iii) is unproven, not invalid.
   - **Ratchet guards**: an open count must hold its binding support — in
     (iii): the (ii) extreme; in (iv): the (b)-of-(iii) extreme (R4); in (v):
     the (iv) extreme. A right edge already past the level = count already
     invalidated by price.
   - **R6 reachability**: if the 176.4% minimum implies a negative price, no
     impulse can exist at this degree (deep crashes are corrective C-waves of
     larger degree in HEW, not impulses).
   - **Superseded guard**: a completed candidate whose tail later makes a new
     extreme beyond (v) was overrun — it was a lower-degree leg, not a
     completion. Dropped.
5. **Score** (`score.py`): harmony = weighted mean of aspect fits × penalties.
   Aspects: s3 (iii)/(i) vs clusters (w3), s5 (v)/((i)+(iii)) vs the (v)
   distribution (w2), sc mean (c)/(a) fits (w1.5), salt numeric alternation
   (ii)%+(iv)% ∈ [0.80,1.20] (w1.5). Unrealized aspects score a neutral 0.5
   (renormalizing would inflate young counts). Penalties: (v) failure ×0.8,
     rare (iii) band ×0.85, sub-equality (c) in (i)/(v) ×0.9, (iv) hugging the
     (b)-of-(iii) barrier ×0.85, structurally-complete-but-sub-172% (iii)
     at the edge ×0.7. Refusal below harmony 0.50 (backtest-calibrated:
     <0.50 calls scored 0.227 with 73% breach rate; 0.50+ scored ~0.48).
6. **Selection**: best harmony; among candidates within 0.05, prefer the
   latest realized_end (the actionable count is the recent one). Alternates
   deduped by (direction, start, end_ii, realized_end, stage).

## Reporting

- in (iii): proof level (176.4%) + next cluster targets; binding = (ii) extreme.
- in (iv): alternation-derived (iv) zone capped by the (b)-of-(iii) barrier;
  binding = (b) of (iii).
- in (v): (v)-distribution targets + 223.6%×(i); binding = (iv) extreme.
- completed: aftermath zones (span of (b) of (v); prior (iv) extreme) PLUS a
  corrective reading of the tail (zigzag/flat/... with C=A projections) when
  one scores ≥ 0.45; binding = (v) extreme. Aftermath targets the tail has
  already traded into are dropped as stale; zigzag C=A projections keep only
  levels still beyond the realized C end.
- refusal fallback: when no impulse survives the rules (or harmony < floor),
  the recent move is scanned for corrective patterns (corrections.py); a match
  ≥ 0.45 reaching the right edge is reported as a "corrective" reading --
  this covers declines too deep for a HEW impulse (rule-6 reachability). A
  match whose invalidation is already exceeded by the last close is dead on
  arrival and rejected.
- Non-positive price targets are clipped (not tradeable).

## Known limits (v2.1)

- Corrective positions (ii)/(iv) inside a fractal are typed by leg count only
  (1/3/5). Standalone corrective readings (zigzag/flat/triangle/double-three,
  corrections.py) cover the post-completion aftermath and charts where no
  impulse exists; they are not yet used to classify (ii)/(iv) internally.
- Corrective ambiguity is surfaced, not resolved: a completed zigzag can be
  the W of a forming double three, and a deep-B zigzag can describe the same
  span as a regular flat. The engine reports the best scan match; treat
  near-ties as alternates.
- No momentum/divergence confirmation (the book's confirmation layer);
  no volume model (HEW has none).
- No triple-coincidence enforcement across degrees (single-degree analysis;
  the (c)-of-(iii) ≈ (iii) target coincidence emerges in scores but is not
  gated).
- Window is fixed 8× horizon; no adaptive refinement.
