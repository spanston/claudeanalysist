# Elliott Wave Engine — Design (v2)

A Python engine that fetches OHLCV data from Yahoo Finance and outputs the
best-fitting Elliott Wave count at **two adjacent degrees**, fully
automatically — no anchor, no lookback, no pattern shortlist supplied by the
user.

Status: **design v2** — revised after a three-way expert review (Elliott Wave
canon audit, mathematical audit of scoring/parsing, and an empirical
feasibility simulation). Verdict was GO-WITH-CHANGES; the changes are folded
in below and summarized in the changelog at the end.

## Settled decisions

| Fork | Decision |
|------|----------|
| Anchoring | **Full auto** — anchors compete as null-vs-structure hypotheses over the *same* full window (§6) |
| Degrees | **Single timeframe**; higher degree emerges by grouping the lower — never two reconciled zigzags |
| Pattern scope | **All families**: impulse, leading/ending diagonal, zigzag, flat (regular/expanded/running), triangle (contracting incl. barrier, expanding), double/triple zigzag, double/triple three |

## The problem, stated honestly

Elliott counting is under-determined: any series admits many legal counts.
"Most fitting" only means something if the engine separates **hard rules**
(binary, from the canon — a violation kills the count) from **soft
guidelines** (scored with tolerance). The engine is therefore a
*search + scoring* problem:

> Find the wave tree that explains the pivots better than a random-walk null
> model does, under a role-aware grammar of legal structures; return the top
> count, the best genuinely-different alternate, and the price that
> invalidates the preferred count.

A count without an invalidation level is astrology. Position, invalidation,
and targets are the primary outputs; the labeled chart exists so a human can
sanity-check them.

## Pipeline

```
yfinance ──► pivots ──► binarized chart parser over attribute grammar ──► anchor scoring ──► report
 (data.py)   (pivots.py)  (grammar.py / parser.py / guidelines.py)          (anchor.py)      (report.py)
```

### 1. Data (`data.py`)

- `yfinance` daily OHLCV, max available history; cached to parquet so engine
  iteration doesn't hammer Yahoo.
- **Price-space convention (fixed, engine-wide):** guideline ratios
  (retracements, extensions, wave-size comparisons) are computed
  **arithmetically per wave** — ratios of price differences are already
  scale-free, and arithmetic ratios are what the canon and every golden-set
  chart use. Log prices are used only where genuinely needed: channel /
  trendline fitting across large ranges, and rendering. (v1 used log prices
  everywhere, which silently moves every Fib ideal — a 0.5 log-retrace of a
  100→200 wave lands at ≈141, not 150.)

### 2. Pivot extraction (`pivots.py`)

- **Offline-maximal ATR-scaled zigzag**: the maximal alternating pivot
  subsequence in which every leg ≥ k × ATR(14), with a fixed per-leg
  reference convention. The *offline-maximal* definition matters: it makes
  pivot count provably non-increasing in k, so budget calibration by
  bisection is guaranteed to converge. (The greedy online zigzag does not
  carry this guarantee — do not substitute it.) Simulation confirmed strict
  monotonicity on both real BTC data and synthetic GBM, and bisection to a
  target budget converged in ~10 iterations.
- **Monowave-budget auto-calibration**: bisect k so the window yields
  **~80–150 monowaves, hard cap n ≤ 150** (the parser's workload is
  calibrated to this — §4). Target the middle of the band: realized counts
  jitter ±10–15% run-to-run at fixed k. Since count(k) is a step function,
  terminate on *nearest achievable* count, and on plateaus pick the midpoint
  of the achieving k-interval for stability.
- Edge conventions (each one otherwise becomes a memo-key instability):
  - The final, unconfirmed extremum is **always provisional** — never let
    calibration decide the right-edge pivot's existence (it flips span
    parity, which the grammar cares about).
  - Wide bars containing both a qualifying high and low: fixed convention
    (extreme nearer the open counts first).
  - ATR warm-up bars are excluded from the pivot span; price ties broken
    deterministically (earliest bar wins).

### 3. Grammar (`grammar.py`) — an *attribute* grammar, not a bare CFG

Elliott's structure is context-free in shape but **role-dependent in law**:
ending diagonals occur only as wave 5 or wave C; leading diagonals only as
wave 1 or wave A of a zigzag; triangles only in wave 4, wave B, or the final
X — never wave 2; a combination's triangle may only be its final component.
The parent's slot must therefore be visible inside the cell:
`parse(i, j, structure, role)`. This also lets priors condition on role,
which encodes alternation (zigzags dominate wave 2, flats/triangles wave 4)
mechanistically rather than only as a soft guideline.

The catalog, corrected against the canon (Frost & Prechter; Neely):

```python
GRAMMAR = {
  # name                 components                      hard rules                                        roles            prior*
  "impulse":           ([":5",":3",":5",":3",":5"],
                        [w2_retrace_le_100, w3_not_shortest, w3_beyond_w1_end, w4_no_overlap]),           # any :5 slot     0.30
  "diagonal_leading":  ([":5",":3",":5",":3",":5"],     # 5-3-5-3-5 is the canonical form
                        [w2_retrace_le_100, w3_lt_w1, w4_lt_w2, w5_lt_w3, w3_not_shortest,
                         w4_overlaps_w1, lines_converge]),                                                # W1, A-of-zigzag 0.02
  "diagonal_ending":   ([":3",":3",":3",":3",":3"],
                        [w2_retrace_le_100, w3_lt_w1, w4_lt_w2, w5_lt_w3, w3_not_shortest,
                         w4_overlaps_w1, lines_converge]),                                                # W5, C           0.03
  "zigzag":            ([":5",":3",":5"],  [b_retrace_lt_100_of_a]),                                      # any :3 slot     0.25
  "flat_regular":      ([":3",":3",":5"],  [b_ge_90pct_a, b_le_262pct_a]),                                # any :3 slot     0.07
  "flat_expanded":     ([":3",":3",":5"],  [b_beyond_a_start, b_le_262pct_a, c_beyond_a_end]),            # any :3 slot     0.10
  "flat_running":      ([":3",":3",":5"],  [b_beyond_a_start, b_le_262pct_a, c_short_of_a_end]),          # any :3 slot     0.02
  "triangle_contract": ([":3",":3",":3",":3",":3"],     # boundary rules, NOT leg-shrink rules
                        [c_within_a_end, d_within_b_end, e_within_c_end,
                         lines_converge_or_one_barrier]),                                                 # W4, B, final X  0.06
  "triangle_expand":   ([":3",":3",":3",":3",":3"],
                        [c_beyond_a_end, d_beyond_b_end, e_beyond_c_end, lines_diverge]),                 # W4, B, final X  0.01
  "double_zigzag":     (["zigzag","x:3","zigzag"],                     []),                               # any :3 slot     0.04
  "triple_zigzag":     (["zigzag","x:3","zigzag","x:3","zigzag"],      []),                               # any :3 slot     0.005
  "double_three":      (["W:3corr","x:3","Y:3corr"],    [combination_composition]),                       # any :3 slot     0.03
  "triple_three":      (["W:3corr","x:3","Y:3corr","x:3","Z:3corr"], [combination_composition]),          # any :3 slot     0.005
}
```

Notes pinned down by the review:

- **Family membership is explicit**: `:5` = {impulse, leading diagonal
  (role-gated), ending diagonal (role-gated)}; `:3` = {zigzag, flats,
  triangles (role-gated), combinations, and — at the degree floor only — a
  bare corrective monowave run}. `:3corr` = any *named* corrective pattern
  (not a raw run).
- **`combination_composition`** (hard): at most one zigzag, at most one
  flat, at most one triangle among W/Y/Z, and a triangle only as the final
  component. Without this, generic threes make combinations absorb
  everything.
- **Triangle rules are boundary rules** (C never beyond the end of A, D
  never beyond B's end, E never beyond C's end) — a "each leg shorter"
  rule is non-canonical: it forbids the legal running triangle (B beyond A's
  start is fine) and permits shapes that break prior extremes. The
  **barrier** triangle (one trendline horizontal) is covered by
  `lines_converge_or_one_barrier`; only *diverging both lines* is illegal
  for the contracting family. E may itself be a triangle or zigzag — the
  recursion must not forbid it.
- **Flat B is capped**: B ≤ 2.618×A is a hard disqualifier (Neely); the
  1.05–1.38×A zone is the expanded flat's guideline sweet spot, scored not
  gated.
- **X-wave retrace bounds are a guideline, not a hard rule** (running
  combinations legally exceed them); typical X ≈ 50–79% of W.
- **Hard-rule price basis is pivot extremes** (the zigzag's atoms), stated
  explicitly. For crypto's wicky data, wave-4 overlap uses an ε×ATR
  tolerance band: overlap within ε is scored against, only overlap beyond ε
  kills. Truncated fifths (W5 failing to exceed W3's end) are legal and the
  right-edge logic must allow "completed below W3," typically after an
  extended third.
- **Priors (\*)**: expanded > regular flat (practitioner consensus; v1 had
  them inverted). Raw numbers are relative weights only — the engine
  normalizes them **within each conditioning class**
  `π(pattern | family, role, open/complete)`, per §5. Role-conditioning is
  also where alternation lives. Double threes vs double zigzags (0.03/0.04)
  may flip under tuning; both are tuning surface, not settled facts.

### 4. Parser (`parser.py`) — binarized, exact, measured

**Naive 5-way split enumeration does not survive contact with n=150.**
Measured (stub parser, real combinatorics, analytic count cross-checked):
~772M split evaluations, ~2 hours with a realistic scoring cost — per
anchor. The 3%-floor proportionality prune is decorative at this arity
(~2× constant against an ~n⁶ term). The fix is structural:

- **Binarize the grammar** (dotted-rule / prefix-DP form): `impulse → I₁ :3`,
  `I₁ → I₂ :5`, … Intermediate items are keyed by (start, end, dot
  position) plus a small threaded state carrying exactly the data the
  non-adjacent hard rules need (W1's length and endpoint for the overlap
  test; running-shortest for W3-not-shortest). Joint rules that need all
  breakpoints are applied at final assembly of the last component. Measured
  effect: n=150 drops from ~2 h to **~90 s** with 20×-slower real scoring,
  scaling ~n³. For spans under ~40 pivots, naive enumeration is cheap
  (~2M splits) and may be used where a joint rule resists threading.
- **Cell key carries everything context can see**:
  `(i, j, pattern-family, role, direction, complete|open-right)`.
  This single change does double duty: it implements the attribute grammar
  (§3), and it restores optimal substructure — with the refined key,
  **Viterbi is exact and top-k is no longer a soundness heuristic**, just
  the mechanism for alternates. (With the v1 key `(i,j,:3/:5)`, open and
  complete parses and sharp vs flat corrections competed for the same k
  slots and could evict the globally best tree.)
- **k-best**: lazy k-best à la Huang & Chiang (2005) over the binarized
  hypergraph — exact alternates at ~O(k log k) extra per cell. **k = 4–5,
  floor 3**: simulation showed k=1 silently loses the true count ~25% of
  the time, while root top-1 accuracy is identical across k — k's entire
  value is keeping the true count alive as the alternate.
- **One chart serves everything**: anchors only change which root cell is
  read out (§6), so the anchor tournament costs ~nothing beyond the single
  chart.
- **Right edge is always open.** The parser accepts **prefix-complete
  patterns on right-edge spans only** (impulse with 1–4 done and 5 underway
  is a legal terminal parse). Open-ness is in the cell key. The root k-best
  must also admit the readings "pattern just completed, nothing underway"
  and "larger-degree reversal just began" — the classic top-call ambiguity
  that the alternate slot usually carries.

**Degree floor (load-bearing — simulation's round-trip failures were almost
all violations of it).** Children of degree-1 waves are raw monowave runs,
checked two ways:

1. **Hard minimum sizes**: a `:5` child spans ≥5 monowaves, a `:3` child
   ≥3 (a triangle needs ≥5). A single monowave can never be an entire
   degree-1 wave — this was the dominant failure mode in round-trip tests.
2. **Shape, not parity**: "odd run" is vacuous (any low-to-high pivot span
   has odd legs by parity). The `:5` floor check tests impulse shape on
   pivot prices — interior pullbacks hold inside the right extremes,
   middle-third not shortest; the `:3` check tests corrective shape.

Degree-1 corrective *internals* remain unverified below the floor — a fair
trade for tractability, but the report says so (§7).

### 5. Scoring (`guidelines.py`) — one objective, no λ, LLR against a null

v1 defined the objective twice, incompatibly (flat Σ vs `parent = own +
λ·mean(children)`); the two disagree and each is biased (the Σ of negative
penalties favors 3-wave readings; the mean dilutes a flaw buried in an
impulse by λ²/25 vs λ²/9 in a zigzag — the very failure it was meant to
prevent). Both are replaced by a single proper log-likelihood, flat over
nodes:

**S(T) = Σ over nodes v of [ log π(p(v) | family(v), role(v), open(v)) + Σ over guidelines g of w_g · ( log f_g(x_g(v)) − log f₀,g(x_g(v)) ) ]**

- **π** is normalized within each conditioning class (Σ = 1 separately per
  family × role × open/complete). Raw table priors are weights, not
  probabilities.
- **Every guideline is a log-likelihood *ratio* against a null model** P₀
  (alternating pivot legs, sizes i.i.d. from a fitted log-normal; f₀,g
  estimated once by Monte Carlo). Under the null a guideline's expected
  contribution is ≤ 0; under a genuinely well-formed pattern it's positive.
  This is the fix for "each guideline adds a negative log term": guidelines
  reward fit instead of taxing ambition, the impulse stops being punished
  for being the most falsifiable pattern, and permissive patterns (flat
  f_g ≈ f₀) gain nothing — much of the Occam work v1 assigned to priors
  happens automatically.
- **Kernels in log-ratio space**: deviation d = ln(r/r*), score ∝
  exp(−d²/2σ²) — multiplicative errors symmetric, no mass at r<0. Interval
  ideals like 0.5–0.618 get a flat-top kernel (d = distance to the nearest
  edge in log space) with proper normalization. Ratios themselves are
  arithmetic per §1.
- **Weights are tempering exponents** w_g ∈ (0,1] — no separate weighting
  scheme.
- A bad child now subtracts from the root at full weight: "nests cleanly
  beats beautiful-but-unbuildable" is automatic, no λ needed.

Guideline table (expanded per the canon audit):

| Guideline | Ideal | w |
|---|---|---|
| W2 retracement of W1 | 0.5–0.618 | high |
| W3 extension vs W1 | 1.618 (alt 2.618) | high |
| C vs A in zigzags/flats | ≈1.0 (alt 1.618) | high |
| W4 retracement of W3 | ≈0.382 | med |
| Depth of W4: into prior 4th-wave span of one lesser degree | inside span | med |
| W5 vs W1 equality when W3 extends | ≈1.0 (alt 0.618) | med |
| Alternation (W2 vs W4 sharp/flat) | different character | med |
| Channel fit (0-2-4 line, 1-3 parallel; log price) | high R² | med |
| Zigzag B retrace of A | 0.38–0.79 | med |
| Expanded-flat sweet spots | B ≈ 1.236–1.382×A, C ≈ 1.618×A | med |
| Post-triangle thrust | ≈ triangle's widest width | med |
| Triangle leg vs prior leg | ≈0.618 | low |
| X-wave retrace of W | 0.50–0.79 | low |
| Time proportionality | no wave ≫10× siblings | low |
| Fifth-wave / diagonal throw-over | present at completion | low |

### 6. Anchoring (`anchor.py`) — null-prefix scoring, not length normalization

v1's "average log-score per labeled wave" was gameable (denominator is a
property of the parse, not the data — the NMT length-normalization
pathology) and still degenerated toward recent swings. Replaced by scoring
**every anchor on the identical full window**:

**Score(a) = log P₀(pivots [0, a)) + S(T over [a, e])**

The prefix before the anchor is explained by the null model, the suffix by
the wave tree. Raw sums are directly comparable; an anchor extends leftward
exactly when the wave model beats randomness on the extra pivots — which is
the honest answer to "how far back does structure reach." Candidate anchors
(window extremes + prominent pivots) are just root read-outs of the one
shared chart. **"No clean count"** is now precise: declared when
max over (a,T) of Score minus log P₀(whole window) falls below a calibrated
margin — the permissiveness audit asserts on exactly this quantity.

### 7. Report (`report.py`)

JSON + labeled SVG chart (same dependency-free approach as
`tools/plot_zones.py`; renders inline on GitHub/mobile).

- **Degrees are relative** — "degree 2 / degree 1" with notation styles
  (circled / parenthesized) used purely typographically. An engine that
  auto-sized its own window cannot know it found *Primary* rather than
  *Minor*; absolute degree names, if shown, come from a duration heuristic
  with an explicit caveat. (v1's report overclaimed here.)
- **Position**: path down the open edge of the tree, machine-readable
  (`["③","(4)"]`) plus display strings (Swedish + English — the BTC digest
  consumes the Swedish verbatim).
- **Invalidation**: tightest hard-rule bound across both open degrees;
  report the binding one and both, each tagged with its rule.
- **Targets**: Fib projections per degree, including post-triangle thrust
  and truncation-aware fifth-wave logic.
- **Scores with defined scales** (v1's bare "0.74" had none):
  - **structure strength** = per-pivot LLR vs the null (0 ≈ random walk) —
    the headline number;
  - **relative confidence** = softmax over the root k-best list
    (preferred vs alternate);
  - raw S(T) for debugging, plus the per-guideline breakdown.
- **Alternate diversity is by market implication**, not merely different
  labels: materially different direction, invalidation, or target
  (practitioners' "top alternate"). Two counts that both say "up, same
  invalidation" are not a useful pair. The just-completed /
  larger-degree-reversal readings (§4) are first-class alternate candidates.
- The report flags that degree-1 corrective internals below the degree
  floor are unverified (§4).
- Chart: candles + faint monowave zigzag, both degree labelings, red
  invalidation line, dashed targets with their basis, shaded projection cone
  for the open wave, grey inset strip showing the alternate's degree-2
  labels.

## Performance budget (measured, stub parser ×20 scoring-cost factor)

| Configuration | n=150 workload | est. real time |
|---|---|---|
| v1 naive 5-way splits, 3–90% prune | 772M splits | ~2 h per anchor |
| Binarized prefix-DP (adopted) | 37M combines | **~90 s, all anchors** |
| Fallback if binarization slips: ≥15% floor | 8.9M splits | ~80 s, per anchor, forbids some legal counts |

Pivot budget n ≤ 150 is a hard design constraint, not a preference.

## Package shape

```
elliott/
  data.py       # yfinance → parquet cache; arithmetic-ratio convention
  pivots.py     # offline-maximal ATR zigzag + bisection budget calibration
  grammar.py    # attribute grammar: components, hard rules, roles, prior weights
  guidelines.py # LLR guideline kernels vs fitted null, tempering weights
  parser.py     # binarized chart parser, refined cell keys, H&C k-best
  anchor.py     # null-prefix anchor scoring, no-clean-count margin
  report.py     # JSON (position/invalidation/targets/alternate) + labeled SVG
  cli.py        # elliott BTC-USD  → full auto, zero required args
```

## Testing strategy

1. **Grammar round-trip**: synthetic 2-degree waves generated from the
   grammar with known labels; parser must recover them. Simulation baseline
   to beat: top-1 ≈ 0.72/0.68 and top-5 ≈ 0.97/0.90 at noise σ = 0.10/0.25 —
   *without* the degree floor; with it, the dominant failure mode
   (single-monowave degree-1 waves) is eliminated by construction.
2. **Golden set**: historical charts with widely-agreed counts (e.g. BTC
   2018–2021) as regression fixtures — also validates the arithmetic-ratio
   convention against how those counts were drawn.
3. **Permissiveness audit**: random walks must trigger the no-clean-count
   margin (§6) — now a precise assertion, not a vibe. Watch the flat family
   and diagonals/triangles specifically: simulation showed flats are the
   confusable family and absorption by diagonal/triangle is real.

## Named risks

- **Prior/σ tuning is empirical, not design** — the permissiveness audit
  and round-trip suite are the guardrails; flat-vs-flat and
  diagonal-absorption confusions are the known hot spots.
- **Threading non-local hard rules through binarized items** is the trickiest
  implementation detail; the <40-pivot naive fallback bounds the damage if a
  rule resists threading.
- **ε×ATR overlap tolerance** for wicky crypto data needs calibration
  against the golden set.
- **Anchor sensitivity** is surfaced in the report, not hidden.

## Digest integration (later, out of scope for v1)

The engine is ticker-agnostic; the BTC daily digest can later call it as an
extra section (count position vs. regime state machine, Swedish position
string consumed verbatim). Nothing in v1 depends on the digest.

---

## Changelog v1 → v2 (from the three-way review)

**Elliott Wave canon audit** — leading diagonal corrected to 5-3-5-3-5;
diagonal contraction rules added (W3<W1, W4<W2, W5<W3, W2≤100%, overlap
required); triangle rules replaced with canonical boundary rules + barrier
support; triple zigzag added; combination composition rule added; flat B
capped at 2.618×A; flat priors un-inverted (expanded > regular); X-retrace
demoted to guideline; grammar upgraded to attribute grammar (role-gated
diagonals/triangles); guideline table roughly doubled; degree names made
relative; alternate diversity redefined by market implication; degree-floor
check made shape-based; extreme-vs-close price basis pinned with ε×ATR
overlap tolerance; truncated fifths handled.

**Math audit** — dual objective (Σ vs λ·mean) replaced by single flat
PCFG-style sum; priors normalized per conditioning class; guidelines turned
into LLRs against a fitted null (fixes systematic anti-impulse bias);
kernels moved to log-ratio space with flat-top interval ideals; guideline
ratios computed arithmetically (log-price ideals were silently shifted);
anchor tournament replaced by null-prefix full-window scoring; cell key
refined to (i,j,family,role,direction,open) making Viterbi exact and top-k
purely the alternates mechanism; Huang–Chiang k-best adopted; offline-maximal
zigzag mandated for monotone calibration; report scores given defined scales.

**Feasibility simulation** (GO-WITH-CHANGES) — naive 5-way splits measured
at ~772M evaluations ≈ 2 h at n=150: binarization mandatory (measured ~90 s
incl. 20× scoring factor); 3% proportionality floor shown decorative;
cell top-k ≥ 3 (k=4–5) — k=1 loses the true count ~25% of the time;
degree-floor minimum sizes promoted to hard rules (dominant round-trip
failure was single-monowave degree-1 waves); n ≤ 150 hard cap; bisection
calibration empirically validated (monotone on real BTC + GBM); flat-family
confusability confirmed as the top tuning risk.
