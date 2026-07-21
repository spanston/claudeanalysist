# Engine review — 2026-07-21 (three independent subagent analyses)

Scope: v1 (`elliott/`) + v2 (`elliott_harmonic/`) code correctness; v2 methodology
fidelity vs the HEW skills/sources; backtest data analysis (200 harness records).

## A. Bugs (code review, evidence-backed)

| # | Sev | Where | Finding |
|---|---|---|---|
| A1 | HIGH | fractals.py:126,162-165 | Rules 1 & 4 check only the correction's END pivot: an interior leg that breaches start-of-(i) / (b)-of-(iii) and recovers passes the hard gates. Reproduced. Fix: extreme-scan over the correction's pivot range. |
| A2 | HIGH | corrections.py:335-338 | Triangle post-thrust target points the wrong way (sign of a-leg, should be entry direction). Test enshrines the error (test_corrections.py:122). |
| A3 | HIGH | cli.py:40,69 | KeyError crash printing flat corrective readings (zone targets indexed as ["price"]). |
| A4 | MED | report.py:227-232 (v1) | target_overshoot warning keys on root direction; misfires for counter-trend degree-1 targets (BTC, NIO, NVO reports). |
| A5 | MED | engine.py:183-196 + corrections.py:196-202 | v2 aftermath/corrective targets never filtered against realized price — stale targets (the v1 disease re-introduced). |
| A6 | MED | data.py:128-167 | update_ohlcv writes empty frames → poisons cache, never self-heals. |
| A7 | MED | tools/*.py | except BaseException swallows KeyboardInterrupt, records it as engine error in resume jsonl. |
| A8 | MED | engine.py:248 (v2) + report.py (v1) | Provisional right-edge flag almost never emitted though every report has one. |
| A9 | LOW | grammar.py:183-184 (v1) | Open running-flat C can never parse (undecidable treated as fail). |
| A10 | LOW | fractals.py:210 | Off-by-one: `range(0, n-6)` drops the youngest possible open candidate; makes the n<6 guard dead. |

## B. Methodology fidelity (v2 vs skills vs sources)

Engine is largely faithful; invented constants mostly reasonable. Top gaps by reading impact:
1. **No momentum/divergence layer** — the methodology's veto at targets ("if indicators say trend intact, the count is wrong"). Biggest single gap.
2. **No triple coincidence / clustering** — live example: NFLX targets 61.88 (66.7% of (i)+(iii)) and 62.63 (223.6%×(i)) are the same cluster; engine lists them separately, doesn't detect it.
3. **Alternation compensation mechanisms absent** (deep (b) of (iii) >66.7% sanctions sum <80%; sum <75% → expect deep (b) of (v)) — mis-ranks valid counts, common in US equities.
4. **(iii) targets unfiltered by the implied-(iv) barrier test** — can advertise targets inconsistent with the count's own geometry (the cap exists for stage-(iv), not stage-(iii)).
5. **Corrective coverage**: no double zigzag/triple three; hard C>A zigzag gate rejects truncating Cs (table bottoms at 61.8%).
Plus: classical (i)/(iv) non-overlap is *retained* by the book alongside the (b)-of-(iii) barrier (skill said "replaced"); rare case where engine accepts a count the book rejects.

## C. Backtest data analysis (200 records, verified)

- My headline numbers reproduce exactly. Two data caveats: sample is 25 symbols (SNDK/SPCX too short); BTC's as-of dates are calendar-shifted.
- **Floor circularity**: post-floor mean 0.481 but bootstrap CI [0.35, 0.61]; the toxic band is specifically [0.45,0.50) (n=7, 6/7 breach, mean 0.143); no evidence for 0.55 over 0.50. **Freeze 0.50, no more tuning on this dataset.**
- **Regime killer**: v2 down-calls in high-beta names: n=11, mean 0.091, 82% breach, harmony up to 0.93 useless. Steady-name down-calls fine (0.464). The mania run-up (Apr/Jul as-ofs) was systematically deadly for ALL down-calls (77% breach).
- **Harness fairness**: v1's 0.284 deficit is mostly measurement artifact — v1 calls with an in-bias target scored 0.500 (above v2's 0.426); paired slots (n=11): v1 won 6. The real v1 deficit is coverage, not per-call quality. Also: 11/16 v2 target_first hits were ≤2 ATR away (2 were ≤0.1 ATR — inflated).
- **Two v2 calls had bindings already violated at entry** (NVDA/STX corrective-fallback zigzags: binding is pattern-invalidation, not directional). Guaranteed zeros; excluding them v2 = 0.444, top bucket = 0.538.
- H=63 undercredits both engines ~0.05 vs H=126.

## D. Ranked actions (from the three reports)

Bugs first (A1-A3 immediate), then:
1. Wrong-side binding fix (harness + corrective fallback directional invalidation).
2. Counter-trend gating in high-beta names (suppress or raise floor for momentum-name counter-trend calls).
3. Harness: de-inflate target_first (<1 ATR targets), score at H=126, fix v1 flipped-call target asymmetry.
4. v2: triple-coincidence clustering (single-degree first), alternation compensation, (iii)-target barrier filter.
5. Momentum/divergence confirmation layer (biggest methodology gap, larger build).
