#!/usr/bin/env python3
"""Venue cross-check for the BTC Investtech digest.

Investtech is the PRIMARY source for levels/zones, but it may quote a different
feed than the venue you execute on. This tool pulls live BTC price + daily OHLCV
from public venues (no key needed), computes ATR(14), and measures each
Investtech level against live price so zones become mechanical instead of
eyeballed:

  - venue spot price(s) and how far Investtech's stated close is from them,
  - ATR(14) daily (a volatility-scaled buffer for zone edges),
  - distance from current price to every support/resistance level
    (absolute, %, and in ATRs),
  - an ATR-buffered band around each accumulation rung.

Usage:
    python3 tools/venue_crosscheck.py btc-digests/<date>.md
    python3 tools/venue_crosscheck.py btc-digests/<date>.md --json

Dependency-free (stdlib only). Network failures degrade gracefully: any venue
that doesn't answer is reported as unavailable and the rest still compute.
"""
import json
import sys
import urllib.request
from datetime import datetime, timezone

UA = {"User-Agent": "Mozilla/5.0 (btc-digest venue-crosscheck)"}
TIMEOUT = 12


def _get(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode())


def coinbase():
    """Spot + ~300 daily candles from Coinbase Exchange (BTC-USD)."""
    spot = float(_get("https://api.exchange.coinbase.com/products/BTC-USD/ticker")["price"])
    raw = _get("https://api.exchange.coinbase.com/products/BTC-USD/candles?granularity=86400")
    # [time, low, high, open, close, volume], newest first
    candles = [{"high": c[2], "low": c[1], "close": c[4]} for c in raw]
    candles.reverse()  # oldest first
    return spot, candles


def binance():
    """Spot from Binance (BTCUSDT) — may be geo-blocked; optional."""
    return float(_get("https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT")["price"])


def atr(candles, period=14):
    """Wilder ATR on daily candles (oldest-first)."""
    if len(candles) < period + 1:
        return None
    trs = []
    for i in range(1, len(candles)):
        h, l, pc = candles[i]["high"], candles[i]["low"], candles[i - 1]["close"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    a = sum(trs[:period]) / period
    for tr in trs[period:]:
        a = (a * (period - 1) + tr) / period
    return a


def parse_front_matter(path):
    """Tiny YAML-ish reader for the fields this tool needs."""
    txt = open(path, encoding="utf-8").read()
    if not txt.startswith("---"):
        raise SystemExit(f"{path}: no YAML front matter")
    fm = txt.split("---", 2)[1]
    out = {"close": None, "support": [], "resistance": [], "rungs": []}
    in_acc = in_rungs = False
    for line in fm.splitlines():
        s = line.strip()
        if s.startswith("close:"):
            out["close"] = float(s.split(":", 1)[1])
        elif s.startswith("support:"):
            out["support"] = _nums(s)
        elif s.startswith("resistance:"):
            out["resistance"] = _nums(s)
        elif s.startswith("accumulation:"):
            in_acc = True
        elif s.startswith("distribution:"):
            in_acc = in_rungs = False
        elif in_acc and s.startswith("rungs:"):
            in_rungs = True
        elif in_rungs and s.startswith("- {"):
            price = _field(s, "price")
            if price is not None:
                out["rungs"].append({"price": price, "weight": _field(s, "weight"),
                                     "state": _strfield(s, "state")})
        elif in_rungs and s and not s.startswith("-") and ":" in s and not s[0].isspace():
            in_rungs = in_acc = False
    return out


def _nums(s):
    inside = s[s.find("[") + 1:s.find("]")] if "[" in s else ""
    return [float(x) for x in inside.replace(" ", "").split(",") if x]


def _field(s, key):
    for part in s.strip("- {}").split(","):
        if part.strip().startswith(key + ":"):
            try:
                return float(part.split(":", 1)[1].strip())
            except ValueError:
                return None
    return None


def _strfield(s, key):
    for part in s.strip("- {}").split(","):
        if part.strip().startswith(key + ":"):
            return part.split(":", 1)[1].strip().strip('"')
    return None


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    as_json = "--json" in sys.argv
    if not args:
        raise SystemExit(__doc__)
    fm = parse_front_matter(args[0])

    venues, errors = {}, {}
    candles = []
    try:
        spot, candles = coinbase()
        venues["coinbase_btc_usd"] = spot
    except Exception as e:  # noqa: BLE001
        errors["coinbase"] = str(e)
    try:
        venues["binance_btc_usdt"] = binance()
    except Exception as e:  # noqa: BLE001
        errors["binance"] = str(e)

    ref = next(iter(venues.values()), fm["close"])
    a = atr(candles) if candles else None

    def measure(level):
        d = ref - level
        return {
            "level": level,
            "dist_abs": round(d, 2),
            "dist_pct": round(d / ref * 100, 2) if ref else None,
            "dist_atr": round(d / a, 2) if a else None,
        }

    report = {
        "as_of": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "digest_close": fm["close"],
        "venues": {k: round(v, 2) for k, v in venues.items()},
        "venue_errors": errors,
        "ref_price": round(ref, 2) if ref else None,
        "investtech_vs_venue_abs": round(fm["close"] - ref, 2) if (fm["close"] and ref) else None,
        "atr14_daily": round(a, 2) if a else None,
        "atr14_pct": round(a / ref * 100, 2) if (a and ref) else None,
        "support": [measure(x) for x in fm["support"]],
        "resistance": [measure(x) for x in fm["resistance"]],
        "rungs": [
            {**measure(r["price"]), "weight": r["weight"], "state": r["state"],
             "atr_band": [round(r["price"] - 0.5 * a, 2), round(r["price"] + 0.5 * a, 2)] if a else None}
            for r in fm["rungs"]
        ],
    }

    if as_json:
        print(json.dumps(report, indent=2))
        return

    print(f"# Venue cross-check  ({report['as_of']})")
    print(f"Digest close (Investtech): {fm['close']}")
    for k, v in report["venues"].items():
        print(f"  {k:22s} {v}")
    for k, v in errors.items():
        print(f"  {k:22s} UNAVAILABLE: {v}")
    if report["investtech_vs_venue_abs"] is not None:
        print(f"Investtech close − venue ref: {report['investtech_vs_venue_abs']:+.2f}")
    if a:
        print(f"ATR(14) daily: {report['atr14_daily']}  ({report['atr14_pct']}% of price)")
    print(f"Reference price: {report['ref_price']}\n")

    def show(label, rows):
        print(f"## {label}  (− = price is above the level)")
        for m in rows:
            extra = ""
            if "weight" in m:
                extra = f"  w={m['weight']}% [{m['state']}]"
                if m.get("atr_band"):
                    extra += f"  ±½ATR band {m['atr_band']}"
            atr_s = f"{m['dist_atr']:+.2f} ATR" if m["dist_atr"] is not None else "n/a"
            print(f"  {m['level']:>9}  {m['dist_abs']:+9.2f}  {m['dist_pct']:+6.2f}%  {atr_s}{extra}")
        print()

    show("Accumulation rungs", report["rungs"])
    show("Support", report["support"])
    show("Resistance", report["resistance"])


if __name__ == "__main__":
    main()
