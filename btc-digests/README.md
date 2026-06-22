# BTC Investtech Daily Digest

Daily Bitcoin (BTCUSDT) technical-analysis digests built from Investtech's
short-, medium-, long-term and total analysis. One file per day,
`YYYY-MM-DD.md`.

## Strategy model

This digest serves **aggressive mid-to-long-term accumulation & distribution**.
The trader is a **fader**: accumulate into weakness, distribute into strength,
and accept being early as the price of not missing the move. Short-term
confirmation is a *timing nudge*, never an entry gate.

### Regime state machine

Driven mainly by **medium + long-term score level and slope** (short-term is
demoted to fill timing):

| Regime | Trigger | Action |
|--------|---------|--------|
| **ACCUMULATE** | long/med score deep-negative, slope flattening or up | buy ladder armed across the support band |
| **DISTRIBUTE** | long/med score high-positive, slope flattening or down | sell ladder armed across the resistance band |
| **HOLD** | mid-range, or slope still accelerating against us | no adds; map the band and wait |
| **INVALIDATED** | confirmed close beyond the invalidation level | stop adding, thesis broken, reassess |

The **early tell** for a fader is long-term score *deceleration* (the −90 stops
getting more negative), well before any short-term reversal prints. That is the
"don't miss it" lever — it needs the score time series, which this repo
accumulates day by day.

### Ladder

Zones are **bands, not points**. Each band is split into **5 back-weighted
rungs** — more size at better prices:

- Accumulation weights (top→bottom of band): **10 / 15 / 20 / 25 / 30 %** of the
  zone budget. Largest rung sits just above the invalidation level.
- Distribution mirrors it (bottom→top of band): **10 / 15 / 20 / 25 / 30 %** —
  more size higher. Distribution is **mechanical and symmetric**: rungs fire into
  strength even when it feels too early, by design, so exits aren't worse than
  entries.
- A confirmed break of the invalidation level **voids remaining rungs** and stops
  further adds.

Rung `state`: `armed` (triggerable now) · `pending` (waiting for price) ·
`filled` · `inactive` (opposite side) · `voided` (invalidation hit).

## File naming

`btc-digests/YYYY-MM-DD.md` — one per day, dated by the run date.

## YAML front matter schema

```yaml
---
date: "2026-06-22"
close: 63904.00
change: -518.14
scores:        # current Investtech scores
  kort: -54
  medel: -39
  lang: -90
  total: -78
slopes:        # score change vs previous digest (null at baseline)
  kort: null
  medel: null
  lang: null
  total: null
recs:
  kort: "Sälj"
  medel: "Svag sälj"
  lang: "Sälj"
  total: "Sälj"
levels:
  support: [63000, 60800, 56890]      # verbatim from Investtech
  resistance: [66000, 74000]
regime: "ACCUMULATE"                   # ACCUMULATE | DISTRIBUTE | HOLD | INVALIDATED
ladder:
  accumulation:
    band_high: 63000                   # start nibbling here
    band_low: 56900                    # largest rung, just above invalidation
    invalidation: 56890                # confirmed close below voids the thesis
    rungs:                             # back-weighted: more size lower
      - {price: 63000, weight: 10, state: "armed"}
      - {price: 61400, weight: 15, state: "pending"}
      - {price: 60800, weight: 20, state: "pending"}
      - {price: 58800, weight: 25, state: "pending"}
      - {price: 56900, weight: 30, state: "pending"}
  distribution:
    band_low: 66000                    # start trimming here
    band_high: 74000                   # largest rung, into the broken-support resistance
    invalidation: null
    rungs:                             # back-weighted: more size higher
      - {price: 66000, weight: 10, state: "inactive"}
      - {price: 68500, weight: 15, state: "inactive"}
      - {price: 70500, weight: 20, state: "inactive"}
      - {price: 72500, weight: 25, state: "inactive"}
      - {price: 74000, weight: 30, state: "inactive"}
---
```

`slopes` are `null` on the baseline day and computed from the prior digest
thereafter. Rung prices are seeded from Investtech's stated levels and
interpolated across the band; verify against the charts before trading.

## Reading the digest

Swedish body, led by **bottom line → regime → ladder status**. Order: regime &
ladder (where you are, next rung, invalidation), medium/long summary, score
slopes (momentum of the model itself), a four-timeframe table, level map, and
warning patterns. Short-term gets one line — fill timing only.

> Levels and rung prices are derived from Investtech text and should be verified
> against Investtech's charts before trading.
