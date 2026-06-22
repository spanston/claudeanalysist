# CLAUDE.md — BTC Investtech Daily Digest

This repo produces a daily Bitcoin (BTCUSDT) technical-analysis digest from
Investtech, in **Swedish**, serving an **aggressive mid-to-long-term
accumulation & distribution** trader. Every scheduled run follows the workflow
below. Be direct. If today is not an action day, say so plainly and give the
levels to wait for — don't hedge every sentence.

## Who this serves (read first — it drives every choice)

The trader is a **fader**: accumulate into weakness, distribute into strength,
and accept being early as the price of not missing the move. Therefore:

- **Lead at the medium/long-term altitude.** Short-term is fill-timing only —
  one line, never an entry gate.
- **Confirmation is a dial, not a gate.** Do not wait for short-term to turn
  Köp. The early tell is **long-term score deceleration** (the −90 stops getting
  more negative) — that is when to lean in.
- **Zones are bands with laddered rungs, not single prices.**
- **Distribution is mechanical and symmetric** with accumulation — it fires into
  strength even when it feels early, by design.

## Strategy model

### Regime state machine

Driven mainly by **medium + long-term score level and slope**:

| Regime | Trigger | Action |
|--------|---------|--------|
| **ACCUMULATE** | long/med score deep-negative, slope flattening or up | buy ladder armed across the support band |
| **DISTRIBUTE** | long/med score high-positive, slope flattening or down | sell ladder armed across the resistance band |
| **HOLD** | mid-range, or slope still accelerating against us | no adds; map the band and wait |
| **INVALIDATED** | confirmed close beyond the invalidation level | stop adding, thesis broken, reassess |

When deep-negative score coincides with price entering the structural support
band, default to **ACCUMULATE (early)** even before slope confirms — the fader
starts, doesn't wait.

### Ladder (5 rungs, back-weighted)

- **Accumulation** band = nearest structural support (top, first nibble) down to
  the **invalidation level** (bottom). Weights top→bottom: **10 / 15 / 20 / 25 /
  30 %** — more size at better prices. Largest rung sits just above invalidation.
- **Distribution** mirrors it: nearest resistance (bottom) up to the broken-
  support / target resistance (top). Weights bottom→top: **10 / 15 / 20 / 25 /
  30 %** — more size higher.
- A **confirmed close beyond the invalidation level voids remaining rungs** and
  stops further adds.
- Rung prices are seeded from Investtech's stated levels and interpolated across
  the band. Rung weights are a **hard cap**, not a suggestion — the back-weighted
  bottom rung sits at the invalidation line, so over-sizing is how aggressive
  fading turns into ruin.
- Rung `state`: `armed` · `pending` · `filled` · `inactive` · `voided`.

## Workflow (every run)

### 0. Read previous data
Read the highest-dated file in `btc-digests/` (`YYYY-MM-DD.md`), parse its YAML
front matter for yesterday's close, scores, recs, levels, regime, and ladder. If
none exists, this run is the **baseline** (slopes are `null`).

### 1. Fetch (web_fetch) — BTCUSDT, CompanyID 99400001
- Kort sikt:   `https://www.investtech.com/se/market.php?CompanyID=99400001&product=5`
- Medellång:   `https://www.investtech.com/se/market.php?CompanyID=99400001&product=4`
- Lång sikt:   `https://www.investtech.com/se/market.php?CompanyID=99400001&product=6`
- Totalanalys: `https://www.investtech.com/se/market.php?CompanyID=99400001&product=211`

### 2. Extract from each page (numbers verbatim)
Senaste slutkurs + daglig förändring · rekommendation + numerisk score · den
automatiska TA-paragrafen · ALLA stöd-/motståndsnivåer, trendkanalgränser,
målkurser · volymbalans · RSI-status.

### 3. Compute the model
- **Slopes**: each score minus yesterday's (`null` at baseline). Long-term slope
  is the key momentum tell.
- **Regime**: apply the state machine to medium/long level + slope.
- **Ladders**: build/refresh accumulation and distribution bands and rung states
  from the current levels and price. Mark which rung is `armed`.
- **Changes vs yesterday**: score moves, rec changes, broken levels, regime
  transitions (e.g. "lång score −78 → −90", "regim HOLD → ACCUMULATE").

### 4. Write `btc-digests/<today YYYY-MM-DD>.md`
YAML front matter per the schema in `btc-digests/README.md`
(`date, close, change, scores, slopes, recs, levels, regime, ladder`), then a
scannable Swedish body in this order:
1. **Bottom line** — regime + which rung is armed + invalidation (the phone banner).
2. **Regim & stege** — ladder table with rung states; distribution band noted.
3. **Score-slopes** — momentum of the model itself.
4. Four-timeframe summary table (rek + score); short sikt flagged as fill-timing.
5. Level map (motstånd → pris → stöd, rungs marked).
6. Warning patterns + invalidation.
Add one short note that levels/rung prices must be verified against Investtech's
charts before trading.

### 5. Commit & push
`git add btc-digests/<date>.md && git commit && git push -u origin <branch>`.
On network error, retry up to 4× with exponential backoff (2s, 4s, 8s, 16s).
Do **not** open a pull request unless explicitly asked.

### 6. Notify (push notification / `<routine_summary>`)
First sentence = bottom line: regime + armed rung (or which level to wait for).
Then the four-timeframe table + ladder status, so the trader can act without
opening the session. Only notify when there's something to act on — a quiet,
unchanged, healthy day warrants silence.

### 7. Resilience
If a page is unavailable or data is missing, note which, continue with available
data, and still write + notify with what you have.

## Conventions
- Output language: **Swedish** for the digest body; English fine in commits/chat.
- Develop on the branch specified by the session; never push elsewhere.
- Schema reference and rung details live in `btc-digests/README.md`.
- Do not put model identifiers in commits, code, or pushed artifacts.
