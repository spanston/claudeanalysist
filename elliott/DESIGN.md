# Elliott Wave Engine — Design

A Python engine that fetches OHLCV data from Yahoo Finance and outputs the
best-fitting Elliott Wave count at **two adjacent degrees**, fully
automatically — no anchor, no lookback, no pattern shortlist supplied by the
user.

Status: design settled, pre-implementation.

## Settled decisions

| Fork | Decision |
|------|----------|
| Anchoring | **Full auto** — the engine picks its own origin via an anchor tournament |
| Degrees | **Single timeframe**; higher degree emerges by grouping the lower — never two reconciled zigzags |
| Pattern scope | **All families**: impulse, leading/ending diagonal, zigzag, flat (regular/expanded/running), triangle (contracting/expanding), double/triple zigzag, double/triple three |

## The problem, stated honestly

Elliott counting is under-determined: any series admits many legal counts.
"Most fitting" only means something if the engine separates **hard rules**
(binary, from the canon — a violation kills the count) from **soft
guidelines** (scored with tolerance). The engine is therefore a
*search + scoring* problem:

> Generate all rule-legal wave trees over the swing pivots, score each
> against guidelines and pattern priors, return the top count plus the best
> genuinely-different alternate and the price that invalidates the preferred
> count.

A count without an invalidation level is astrology. Position, invalidation,
and targets are the primary outputs; the labeled chart exists so a human can
sanity-check them.

## Pipeline

```
yfinance ──► pivots ──► chart parser over grammar ──► anchor tournament ──► report
 (data.py)   (pivots.py)  (grammar.py / parser.py /      (anchor.py)        (report.py)
                           guidelines.py)
```

### 1. Data (`data.py`)

- `yfinance` daily OHLCV, max available history; cached to parquet so
  engine iteration doesn't hammer Yahoo.
- **Log prices internally** so Fibonacci ratio checks behave identically at
  $200 and $120k.

### 2. Pivot extraction (`pivots.py`)

- **ATR-scaled zigzag**: reversal threshold = k × ATR, so volatility regimes
  don't change wave granularity. One fine-grained pivot set only — these are
  the *monowaves*; all higher structure is composition. (Running two zigzags
  at two thresholds and reconciling them is explicitly rejected: the coarse
  pivots don't land on fine pivots and the degrees stop nesting.)
- **Monowave-budget auto-calibration**: tune k so the analysis window yields
  **~80–150 monowaves**. That budget is what makes exactly two degrees fit
  naturally — too few and degree 1 has nothing to subdivide into, too many
  and the data implicitly demands a third degree. This replaces "pick a
  lookback period" with a self-calibrating knob.

### 3. Grammar (`grammar.py`)

Elliott structure is a context-free grammar over monowaves. The whole
catalog is one declarative table — components, hard rules, prior:

```python
GRAMMAR = {
  # name                  components                     hard rules                                   prior
  "impulse":            ([":5",":3",":5",":3",":5"],   [w2_full_retrace, w3_shortest, w4_overlap],  0.30),
  "diagonal_leading":   ([":3"]*5,                     [converging_lines, overlap_ok, pos_first],   0.02),
  "diagonal_ending":    ([":3"]*5,                     [converging_lines, overlap_ok, pos_last],    0.03),
  "zigzag":             ([":5",":3",":5"],             [b_below_a_start],                           0.25),
  "flat_regular":       ([":3",":3",":5"],             [b_ge_90pct_a],                              0.10),
  "flat_expanded":      ([":3",":3",":5"],             [b_beyond_a_start, c_beyond_a_end],          0.08),
  "flat_running":       ([":3",":3",":5"],             [b_beyond_a_start, c_short_of_a_end],        0.02),
  "triangle_contract":  ([":3"]*5,                     [alternating_shrink, trendlines_converge],   0.06),
  "triangle_expand":    ([":3"]*5,                     [alternating_grow],                          0.01),
  "double_zigzag":      (["zigzag","x:3","zigzag"],    [x_retrace_bounds],                          0.04),
  "double_three":       ([":3corr","x:3",":3corr"],    [x_retrace_bounds],                          0.02),
  "triple_three":       ([":3corr","x:3",":3corr","x:3",":3corr"], [x_retrace_bounds],              0.005),
}
```

**Priors are what make "support everything" survivable.** Running flats,
expanding triangles, and triple threes are permissive enough to absorb
almost any price action; unpenalized they win every contest. Priors enter
the score as log-penalties, so a triple-three only wins when every simpler
reading fails its hard rules or scores terribly. Occam's razor encoded as
data — and the engine's main tuning surface.

Hard rules (pruned inline during split enumeration):

- Wave 2 never retraces >100% of wave 1.
- Wave 3 is never the shortest of 1/3/5.
- Wave 4 never enters wave 1's price territory (diagonals exempt).
- Corrective structures must match their template exactly (zigzag 5-3-5,
  flat 3-3-5, triangle 3-3-3-3-3, combinations per the table).
- Flat/triangle/X-wave price bounds per the table above.

### 4. Parser (`parser.py`)

CYK-style **chart parser with memoization** — the right machine for "best
parse under a scored grammar" (beam search was the earlier design; it does
not survive combinations and triangles):

- `parse(i, j, structure)` → top-k scored interpretations of pivot span
  `i..j` as `structure` (`:5`-family or `:3`-family), memoized per cell.
- A pattern spec splits its span into components and recurses; hard rules
  prune split candidates *before* recursion.
- **Degree 2 = the root parse; degree 1 = the root's children.** Children
  must terminate exactly on the parent's boundary pivots — nesting is by
  construction, not reconciliation. The parser is naturally arbitrary-depth;
  we label two levels of it (a third degree later is just labeling deeper).

Combinatorics are controlled by three levers, all present from v1:

1. **Top-k per chart cell** (k ≈ 3–5).
2. **Proportionality pruning of splits**: no component under ~3% or over
   ~90% of its pattern's span (also canonically justified — waves of one
   degree are comparable in scale). This is the perf hotspot; it cannot be
   bolted on later.
3. The monowave budget from stage 2.

**Degree floor**: children of degree-1 waves are raw monowave runs. Each
child gets a cheap structural sanity check — a `:5` child should be an odd
run ≥5 monowaves with impulse shape, a `:3` an odd run ≥3 with corrective
shape — which kills many wrong parses without paying for a third degree.

**Right edge is always open.** Live data means the final pattern is almost
never complete, so the parser accepts **prefix-complete patterns at the
right edge only** (impulse with 1–4 done and 5 underway is a legal terminal
parse). The open path down the tree yields position, invalidation, and
targets directly.

### 5. Scoring (`guidelines.py`)

Log-space: `total = Σ guideline log-scores + Σ pattern log-priors`. Each
guideline is a tolerance curve (Gaussian bump around the ideal ratio, not a
hard band):

| Guideline | Ideal | Weight |
|---|---|---|
| W2 retracement of W1 | 0.5–0.618 | high |
| W3 extension vs W1 | 1.618 (or 2.618) | high |
| W4 retracement of W3 | 0.382 | med |
| Alternation (W2 vs W4 sharp/flat) | different character | med |
| Channel fit (0-2-4 line, 1-3 parallel) | high R² | med |
| Time proportionality | no wave 10× its sibling | low |
| W5 vs W1 equality (when W3 extends) | ≈1.0 | low |

Parent total = own score + λ · mean(child scores): a beautiful high-degree
count with unbuildable internals loses to a decent count that nests cleanly.
Per-guideline scores are preserved into the report so a human can see *why*
a count won.

### 6. Anchor tournament (`anchor.py`)

- Candidate anchors: window's global min, global max, plus the 2–3 most
  prominent remaining pivot extremes (prominence = price distance × time
  separation).
- Parse each candidate to the right edge; winner = best
  **length-normalized** score (average log-score per labeled wave). Without
  normalization shorter parses always look cleaner and the engine
  degenerates into counting only the last swing.
- Losing anchors' best parses are kept in the report as context — honest
  about how anchor-sensitive the count is.

### 7. Report (`report.py`)

JSON + labeled chart (matplotlib/SVG, both degrees labeled on the pivots):

```json
{
  "preferred": {
    "position": "Primary ③ in progress; within it, Intermediate (4) unfolding as a flat",
    "score": 0.74,
    "invalidation": 96500.0,
    "invalidation_basis": "degree-1 W4 overlap limit (nearer than degree-2 W2 bound)",
    "targets": [{"basis": "W5 = W1 from W4 low", "price": 138200}],
    "guideline_breakdown": {}
  },
  "alternate": {"position": "Primary Ⓑ of expanded flat", "score": 0.68},
  "anchors_considered": [],
  "pivots": [],
  "labels": []
}
```

- **Invalidation** = the tightest hard-rule bound across *both* open
  degrees; report the nearer one and both.
- **Alternate** requires a diversity rule: second-best parse that differs at
  **degree-2 labeling**, not an internal re-split of the same top-level
  story — preferred vs. alternate must be genuinely different theses.
- A random-walk-like series should produce low scores across the board: the
  engine must be able to say "no clean count here" rather than hallucinate.

## Package shape

```
elliott/
  data.py       # yfinance → parquet cache, log-price transform
  pivots.py     # ATR zigzag + monowave-budget auto-calibration
  grammar.py    # pattern table: components, hard rules, priors
  guidelines.py # soft-score curves (Fib ratios, alternation, channels, time)
  parser.py     # memoized chart parser, top-k cells, right-edge open patterns
  anchor.py     # candidate anchors, tournament, length normalization
  report.py     # JSON (position/invalidation/targets/alternate) + labeled chart
  cli.py        # elliott BTC-USD  → full auto, zero required args
```

## Testing strategy

The domain invites self-deception, so three legs from the start:

1. **Grammar round-trip**: synthetic waves generated *from the grammar
   itself* with known labels — the parser must recover them.
2. **Golden set**: a small set of historical charts with widely-agreed
   counts (e.g. BTC 2018–2021) as regression fixtures.
3. **Permissiveness audit**: feed random walks; assert scores come out low
   and pattern priors dominate — the engine says "no clean count" instead of
   inventing one.

## Named risks

- **Prior tuning is empirical, not design** — expect iteration; the
  permissiveness audit is the guardrail.
- **Split enumeration is the perf hotspot** — proportionality pruning ships
  in v1, not later.
- **Anchor sensitivity** — surfaced in the report rather than hidden.

## Digest integration (later, out of scope for v1)

The engine is ticker-agnostic; the BTC daily digest can later call it as an
extra section (count position vs. regime state machine). Nothing in v1
depends on the digest.
