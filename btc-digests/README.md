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
source_integrity:                      # provenance / facts vs interpretation
  fetched_utc: "2026-06-23T20:30:00Z"
  feed: "Investtech BTCUSDT (CompanyID 99400001)"
  analysis_time: "2026-06-23"          # Investtech's own analysis date if visible
  pages_complete: true                 # all four pages returned data
  quotes:                              # raw snippet backing each key level
    invalidation: "Etablerat genombrott under stödet vid 56845 ..."
cross_check:                           # tools/venue_crosscheck.py output (Korsverifierat)
  venue_ref: 62396.93                  # live venue spot used as reference
  venues: {coinbase_btc_usd: 62396.93, binance_btc_usdt: null}
  investtech_minus_venue: 1662.29      # gap between Investtech close and venue
  atr14_daily: 2134.89
  atr14_pct: 3.42
  falling_knife: false                 # any "don't catch it" condition active?
trade_plan:                            # Mitt beslut (derived decision)
  status: "bevaka"                     # inget köp | bevaka | starter | add | invaliderad
  entry_trigger: "test mot 63000-bandet"
  stop: 56845
  first_target: 66000
  max_alloc_pct: 10                    # rung weight cap for this action
  reward_risk: 0.5
  confidence: "låg"                    # låg | medel | hög (source agreement)
falsifiability:
  invalidated_if: "bekräftad dagsstängning under 56845"
  prior_signal_review: "baslinje 2 dagar gammal — ingen utfallshistorik ännu"
---
```

`slopes` are `null` on the baseline day and computed from the prior digest
thereafter. Rung prices are seeded from Investtech's stated levels and
interpolated across the band; verify against the charts before trading.

`source_integrity`, `cross_check`, `trade_plan` and `falsifiability` make the
digest auditable and falsifiable rather than a polished restatement of one
vendor. `cross_check` is filled by `tools/venue_crosscheck.py` (live venue spot +
ATR(14), Investtech-vs-venue gap); `trade_plan` is the single derived decision
with its invalidation, reward/risk and confidence; `falsifiability` records what
would break the thesis and how earlier signals resolved.

## Data integrity & cross-check

Investtech is one vendor's technical model — *conditions, not a decision system*.
The digest carries three tiers and labels every claim `Rapporterat (Investtech)` /
`Korsverifierat (venue/ATR)` / `Härlett (zoner)` / `Mitt beslut (trade)`:

1. **Investtech** — scores, recs, structural levels (primary).
2. **`tools/venue_crosscheck.py`** — live Coinbase/Binance spot + daily ATR(14),
   measuring every level/rung against venue price in $/%/ATR. Runs in the cloud
   routine, no key needed. Surfaces the gap when Investtech's feed differs from
   the execution venue.
3. **TradingView MCP** (`tradingview` server in `.mcp.json`) — *local, interactive
   only*: bridges to TradingView Desktop over CDP (`localhost:9222`), needs the
   desktop app running with `--remote-debugging-port=9222` and a paid
   subscription. Install with `bash tools/setup-tradingview-mcp.sh`. **Not
   available in the unattended cloud routine.** See CLAUDE.md for which tools
   (`data_get_ohlcv`, `quote_get`, `data_get_study_values`, `alert_create`, …)
   strengthen the analysis.

## Reading the digest

Swedish body, led by **bottom line → regime → ladder status**. Order: regime &
ladder (where you are, next rung, invalidation), medium/long summary, score
slopes (momentum of the model itself), a four-timeframe table, level map, and
warning patterns. Short-term gets one line — fill timing only.

## Zone chart

Each digest has a companion `YYYY-MM-DD.svg` rendered by `tools/plot_zones.py`
from the digest's own front matter, overlaid on ~50 daily Coinbase BTC-USD
candles. It draws the accumulation/distribution bands, the back-weighted rungs
(bar length ∝ weight; solid = armed, dashed = pending), the current price and
the invalidation line. SVG renders inline on GitHub and on mobile and needs no
plotting dependencies. Regenerate with:

```bash
python3 tools/plot_zones.py btc-digests/<date>.md /tmp/btc_prices.json
```

> Levels and rung prices are derived from Investtech text and should be verified
> against Investtech's charts before trading.
