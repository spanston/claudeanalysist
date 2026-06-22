# BTC Investtech Daily Digest

Daily Bitcoin (BTCUSDT) technical-analysis digests built from Investtech's
short-, medium-, long-term and total analysis. One file per day,
`YYYY-MM-DD.md`, focused on **buying zones** for entry timing.

## File naming

`btc-digests/YYYY-MM-DD.md` — one per day, dated by the run date.

## YAML front matter schema

Each digest starts with YAML front matter for machine-readable change tracking:

```yaml
---
date: "2026-06-22"          # YYYY-MM-DD, the run date
close: 63904.00             # latest close (number)
change: -518.14             # daily change in price terms (number)
scores:
  kort: -54                 # short-term score
  medel: -39                # medium-term score
  lang: -90                 # long-term score
  total: -78                # total analysis score
recs:
  kort: "Sälj"              # Köp / Svag köp / Håll / Svag sälj / Sälj
  medel: "Svag sälj"
  lang: "Sälj"
  total: "Sälj"
levels:
  buy_primary: 56890        # primary structural buy zone (number or null)
  buy_secondary: 60800      # secondary buy zone (number or null)
  support: [63000, 60800, 56890]   # all support levels, verbatim
  resistance: [66000, 74000]       # all resistance levels, verbatim
---
```

`buy_primary` / `buy_secondary` may be `null` when no clear zone applies.

## Reading the digest

The body is in Swedish: a bottom line, a four-timeframe summary table
(rek + score), a buying-zone section (primär/sekundär, labelled
"köp nu" / "bevaka" / "fånga inte fallande kniv"), an entry-trigger
checklist, a level map (motstånd → pris → stöd), and warning patterns +
invalidation levels.

> Levels are extracted from Investtech text and should be verified against
> Investtech's charts before trading.
