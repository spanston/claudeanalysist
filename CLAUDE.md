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

## Data sources & integrity (read second)

Investtech is **one vendor's technical model** — a set of *conditions*, not a
standalone decision system. Treat it that way. Three tiers:

1. **Primary — Investtech** (the four pages below): defines scores, recs, and the
   structural levels the zones are seeded from.
2. **Cross-check — public venue price** (`tools/venue_crosscheck.py`, runs
   everywhere incl. the cloud routine): pulls live BTC spot + daily OHLCV from
   Coinbase (and Binance when reachable), computes **ATR(14)**, and measures each
   Investtech level against live venue price in $, % and **ATRs**. Investtech may
   quote a different feed than you execute on, so its stated close can differ from
   venue spot — the digest must surface that gap, not hide it.
3. **Local confirmation — TradingView MCP** (interactive sessions only; see
   below): visual chart, RSI/volume study values, alerts. **Not available in the
   unattended cloud routine.**

**Separate facts from interpretation everywhere.** Tag claims as one of:
`Rapporterat (Investtech)` · `Korsverifierat (venue/ATR)` · `Härlett (zoner)` ·
`Mitt beslut (trade)`. Numbers carried verbatim from a source are facts; zones,
regimes and trade plans are *derived* and must be labelled as such. This is the
guard against polished-but-hallucinated conviction.

**This digest is a daily alerting + decision-support layer, not an auto-trader.**
Every actionable line carries its invalidation and a confidence tag; live
chart/price confirmation is required before execution.

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

### Mechanical zone rules (no eyeballing)

Zones are derived from Investtech levels but made mechanical with venue ATR:

- **Primär köpzon** = confluence of **long + total** support (or the nearest
  structural support to price) widened to a band of **±0.5 × ATR(14)** around the
  level. Rung 1 (first nibble) sits at the band top.
- **Sekundär köpzon** = the next deeper support with better reward/risk, same
  ±0.5 ATR band.
- A rung is **`armed`** when live venue price is within **1 ATR** of its level (it
  can realistically trade there next session), **`pending`** when further away.
- **"Fånga inte fallande kniv"** = any of: venue price below the invalidation
  level · a daily *close* below the band's support · short-term score still
  *accelerating* down (slope more negative than yesterday). When flagged, hold the
  rung — do not pre-empt the band.
- Distances and ATR come from `tools/venue_crosscheck.py`; quote them in the
  digest so "where is price vs the zone" is a number, not a vibe.

### Trade plan & confidence

Every digest states a single **status**: `inget köp` · `bevaka` · `starter`
(rung 1 only) · `add` (deeper rung) · `invaliderad`. Alongside it: entry trigger,
stop/invalidation, first target, max allocation (the rung weight cap), and an
approximate **reward/risk** (target distance ÷ invalidation distance). A
**confidence** tag (`låg/medel/hög`) reflects source agreement: high when
Investtech + venue + ATR placement align, low when they diverge (e.g. Investtech
close far from venue spot, or short-term still accelerating down). The push
notification must carry status + invalidation + confidence — never a bare "köp".

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

### 2. Extract from each page (numbers verbatim + provenance)
Senaste slutkurs + daglig förändring · rekommendation + numerisk score · den
automatiska TA-paragrafen · ALLA stöd-/motståndsnivåer, trendkanalgränser,
målkurser · volymbalans · RSI-status. **Record source integrity** as you go:
fetch timestamp (UTC), the source symbol/feed, Investtech's own analysis
date/time if visible, whether all four pages returned complete data, and a short
**quoted snippet** for each level you extract (so a misread is auditable).

### 2b. Venue cross-check (run after writing the front matter, before finalizing)
```bash
python3 tools/venue_crosscheck.py btc-digests/<date>.md --json
```
Pulls live BTC spot + daily OHLCV from Coinbase (Binance when reachable),
computes ATR(14), and measures every level/rung against venue price in $/%/ATR.
Carry into the digest: venue spot, **Investtech-close − venue gap**, ATR(14), and
the per-rung ATR distances. A large gap or "fallande kniv" condition lowers
confidence and may downgrade the day's status. (Runs in the cloud routine; needs
no key. Binance often returns HTTP 451 by region — that's fine, Coinbase carries.)

### 3. Compute the model
- **Slopes**: each score minus yesterday's (`null` at baseline). Long-term slope
  is the key momentum tell.
- **Regime**: apply the state machine to medium/long level + slope.
- **Ladders (mechanical)**: build/refresh bands per *Mechanical zone rules* —
  ±0.5 ATR bands, rung `armed` when venue price is within 1 ATR. Mark `armed`
  from **venue** distance, not Investtech's stated close.
- **Trade plan**: derive status / entry / stop / target / max alloc / reward-risk
  / confidence per *Trade plan & confidence*.
- **Changes vs yesterday**: score moves, rec changes, broken levels, regime
  transitions (e.g. "lång score −78 → −90", "regim HOLD → ACCUMULATE").
- **Falsifiability**: state what would prove today's thesis wrong, and review how
  prior signals resolved (1/3/7 days later) when earlier digests exist.

### 4. Write `btc-digests/<today YYYY-MM-DD>.md`
YAML front matter per the schema in `btc-digests/README.md` (`date, close, change,
scores, slopes, recs, levels, regime, ladder, source_integrity, cross_check,
trade_plan, falsifiability`), then a scannable Swedish body in this order:
1. **Bottom line** — status + regime + armed rung + invalidation + confidence
   (the phone banner).
2. **Handelsplan** — status / entry-trigger / stop (invalidering) / första mål /
   max-allokering / reward-risk / konfidens. One scannable block.
3. **Regim & stege** — ladder table with rung states *and venue ATR-distance*;
   distribution band noted.
4. **Korsverifiering (venue/ATR)** — venue spot, Investtech−venue gap, ATR(14),
   and the "fallande kniv" check.
5. **Score-slopes** — momentum of the model itself.
6. Four-timeframe summary table (rek + score); short sikt flagged as fill-timing.
7. Level map (motstånd → pris → stöd, rungs marked).
8. Warning patterns + invalidation + **falsifierbarhet** (what proves this wrong;
   how prior signals resolved).
9. **Källintegritet** — fetch time, feed, completeness, quoted level snippets.
Label every claim `Rapporterat` / `Korsverifierat` / `Härlett` / `Mitt beslut`.
Add one short note that levels/rung prices must be verified against Investtech's
charts before trading.
Embed the zone chart near the top: `![Zonkarta](<date>.svg)`.

### 4b. Render the zone chart (`btc-digests/<date>.svg`)
Fetch ~50 daily candles and render the chart from the digest's own front matter:
```bash
curl -s --max-time 12 \
  "https://api.exchange.coinbase.com/products/BTC-USD/candles?granularity=86400" \
  -H "User-Agent: Mozilla/5.0" -o /tmp/btc_prices.json
python3 tools/plot_zones.py btc-digests/<date>.md /tmp/btc_prices.json \
  btc-digests/<date>.svg
```
The SVG overlays the accumulation/distribution bands, back-weighted rungs
(bar length ∝ weight; solid = armed, dashed = pending), current price and the
invalidation line on real candles — it renders inline on GitHub and on mobile,
no plotting dependencies. Candles are price-action *context* (Coinbase BTC-USD);
zones/levels come from Investtech via the front matter, so the candle close may
differ slightly from Investtech's stated close. If candles are unavailable, pass
`-` for the prices arg and the chart renders zones only.

### 5. Commit & push
`git add btc-digests/<date>.md btc-digests/<date>.svg && git commit && git push
-u origin <branch>`. On network error, retry up to 4× with exponential backoff
(2s, 4s, 8s, 16s). Do **not** open a pull request unless explicitly asked.

### 6. Notify (push notification / `<routine_summary>`)
First sentence = bottom line: **status + regime + armed rung (or level to wait
for) + invalidation + confidence**. Then the four-timeframe table + ladder status
+ the venue gap if it's large, so the trader can act without opening the session.
Never send a bare "köp" — always pair it with its invalidation and confidence.
Only notify when there's something to act on — a quiet, unchanged, healthy day
warrants silence.

### 7. Resilience
If a page is unavailable or data is missing, note which, continue with available
data, and still write + notify with what you have.

## TradingView MCP (local confirmation layer — interactive only)

`tradesdontlie/tradingview-mcp` is registered in `.mcp.json` as the `tradingview`
server. It bridges to the **TradingView Desktop app** over Chrome DevTools
Protocol (`localhost:9222`), so it has hard prerequisites:

- TradingView Desktop installed and **running with `--remote-debugging-port=9222`**,
- a **paid TradingView subscription** for full data,
- the Node server installed locally: `bash tools/setup-tradingview-mcp.sh`
  (clones + `npm install` into `vendor/`, which is git-ignored).

**It does NOT work in the unattended Claude Code web/cloud routine** — there is no
desktop app or `:9222` endpoint there. The cloud routine relies on Investtech +
`tools/venue_crosscheck.py` only. The MCP is for *interactive* sessions on your
own machine, to confirm a digest before you execute.

When available (check with `tv_health_check` → `cdp_connected: true`), use it to
strengthen — never to override — the digest:

| Goal | Tool(s) |
|------|---------|
| Match the execution venue | `chart_set_symbol` → e.g. `BINANCE:BTCUSDT` / `COINBASE:BTCUSD` |
| Confirm price vs zone on real bars | `data_get_ohlcv` (1D/4h/1h), `quote_get`, `chart_get_state` |
| RSI / volume / ATR confirmation | `chart_manage_indicator` then `data_get_study_values` |
| Draw the zones on the chart | `draw_shape` (rectangle per rung band) |
| Arm alerts at rung prices | `alert_create` at each rung / invalidation |

Workflow when confirming interactively: set the venue symbol, pull 1D/4h OHLCV,
read RSI/volume, compare against the digest's rungs and invalidation, and only
then act. Treat anything the MCP returns as `Korsverifierat`, and reconcile it
with the venue cross-check rather than trusting either feed blindly.

## Conventions
- Output language: **Swedish** for the digest body; English fine in commits/chat.
- Develop on the branch specified by the session; never push elsewhere.
- Schema reference and rung details live in `btc-digests/README.md`.
- The cloud routine never depends on the TradingView MCP; it must run with
  Investtech + `venue_crosscheck.py` alone (resilience).
- Do not put model identifiers in commits, code, or pushed artifacts.
