#!/usr/bin/env python3
"""Render a BTC zone/price-action chart (SVG) from a digest's YAML front matter.

Reads a btc-digests/<date>.md file and a JSON file of Coinbase daily candles,
and writes a self-contained SVG next to the digest. SVG renders inline on
GitHub and on mobile, and needs no plotting dependencies.

Usage:
    python3 tools/plot_zones.py btc-digests/2026-06-22.md prices.json [out.svg]

prices.json is the raw Coinbase response from:
    https://api.exchange.coinbase.com/products/BTC-USD/candles?granularity=86400
each row: [time, low, high, open, close, volume]  (newest first)
If prices.json is "-" or missing, the chart renders zones only (no candles).
"""
import sys
import json
import html
import yaml

W, H = 960, 560
ML, MR, MT, MB = 64, 210, 56, 44       # margins; MR is the ladder gutter
PLOT_R = W - MR                         # right edge of candle area
COL = {
    "accum": "#1f9d55", "dist": "#d64545", "price_up": "#2f855a",
    "price_dn": "#c53030", "grid": "#e2e8f0", "axis": "#475569",
    "now": "#2563eb", "inval": "#b91c1c", "text": "#1a202c", "muted": "#718096",
}


def load_front_matter(md_path):
    with open(md_path) as f:
        txt = f.read()
    assert txt.startswith("---"), "no YAML front matter"
    fm = txt.split("---", 2)[1]
    return yaml.safe_load(fm)


def load_candles(path, n=50):
    if not path or path == "-":
        return []
    try:
        with open(path) as f:
            rows = json.load(f)
    except Exception:
        return []
    if not isinstance(rows, list):
        return []
    rows = sorted(rows, key=lambda r: r[0])[-n:]      # oldest -> newest
    return [{"t": r[0], "low": r[1], "high": r[2], "open": r[3], "close": r[4]}
            for r in rows]


def esc(s):
    return html.escape(str(s))


def build_svg(fm, candles):
    close = float(fm["close"])
    regime = fm.get("regime", "—")
    lad = fm.get("ladder", {}) or {}
    acc = lad.get("accumulation", {}) or {}
    dist = lad.get("distribution", {}) or {}
    acc_rungs = acc.get("rungs", []) or []
    dist_rungs = dist.get("rungs", []) or []
    inval = acc.get("invalidation")
    levels = fm.get("levels", {}) or {}

    # ---- price range covering everything we draw -------------------------
    pts = [close]
    pts += [c["low"] for c in candles] + [c["high"] for c in candles]
    pts += [r["price"] for r in acc_rungs] + [r["price"] for r in dist_rungs]
    pts += list(levels.get("support", [])) + list(levels.get("resistance", []))
    if inval:
        pts.append(inval)
    pts = [float(p) for p in pts if p]
    pmin, pmax = min(pts), max(pts)
    pad = (pmax - pmin) * 0.04 or 1
    pmin, pmax = pmin - pad, pmax + pad

    def y(p):
        return MT + (pmax - float(p)) / (pmax - pmin) * (H - MT - MB)

    # candle x positions
    def cx(i, n):
        if n <= 1:
            return ML + (PLOT_R - ML) * 0.5
        return ML + (PLOT_R - ML) * (i / (n - 1)) * 0.96 + 6

    s = []
    s.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
        f'viewBox="0 0 {W} {H}" font-family="ui-sans-serif,Segoe UI,Helvetica,Arial">')
    s.append(f'<rect width="{W}" height="{H}" fill="white"/>')

    # title
    rc = COL["accum"] if regime == "ACCUMULATE" else (
        COL["dist"] if regime == "DISTRIBUTE" else COL["muted"])
    s.append(f'<text x="{ML}" y="30" font-size="19" font-weight="700" '
             f'fill="{COL["text"]}">BTC/USD — {esc(fm.get("date",""))}</text>')
    s.append(f'<text x="{ML}" y="48" font-size="13" fill="{rc}" '
             f'font-weight="600">Regim: {esc(regime)} · slutkurs {close:,.0f}</text>')

    # gridlines + price axis
    ticks = 6
    for k in range(ticks + 1):
        p = pmin + (pmax - pmin) * k / ticks
        yy = y(p)
        s.append(f'<line x1="{ML}" y1="{yy:.1f}" x2="{PLOT_R}" y2="{yy:.1f}" '
                 f'stroke="{COL["grid"]}" stroke-width="1"/>')
        s.append(f'<text x="{ML-8}" y="{yy+4:.1f}" font-size="11" '
                 f'text-anchor="end" fill="{COL["muted"]}">{p:,.0f}</text>')

    # ---- zone bands ------------------------------------------------------
    def band(p_hi, p_lo, color, label):
        if not p_hi or not p_lo:
            return
        yt, yb = y(p_hi), y(p_lo)
        s.append(f'<rect x="{ML}" y="{yt:.1f}" width="{PLOT_R-ML}" '
                 f'height="{abs(yb-yt):.1f}" fill="{color}" fill-opacity="0.07"/>')
        s.append(f'<text x="{ML+6}" y="{yt+14:.1f}" font-size="10" '
                 f'fill="{color}" font-weight="600">{esc(label)}</text>')

    band(acc.get("band_high"), acc.get("band_low"), COL["accum"], "ACKUMULATIONSBAND")
    band(dist.get("band_high"), dist.get("band_low"), COL["dist"], "DISTRIBUTIONSBAND")

    # ---- candles ---------------------------------------------------------
    n = len(candles)
    bw = max(2, min(9, (PLOT_R - ML) / max(n, 1) * 0.6)) if n else 0
    for i, c in enumerate(candles):
        x = cx(i, n)
        up = c["close"] >= c["open"]
        col = COL["price_up"] if up else COL["price_dn"]
        s.append(f'<line x1="{x:.1f}" y1="{y(c["high"]):.1f}" x2="{x:.1f}" '
                 f'y2="{y(c["low"]):.1f}" stroke="{col}" stroke-width="1"/>')
        yo, yyc = y(c["open"]), y(c["close"])
        s.append(f'<rect x="{x-bw/2:.1f}" y="{min(yo,yyc):.1f}" width="{bw:.1f}" '
                 f'height="{max(1,abs(yyc-yo)):.1f}" fill="{col}"/>')

    # date labels (first / mid / last)
    if n:
        import datetime as _dt
        for idx in {0, n // 2, n - 1}:
            x = cx(idx, n)
            d = _dt.datetime.utcfromtimestamp(candles[idx]["t"]).strftime("%d %b")
            s.append(f'<text x="{x:.1f}" y="{H-MB+18}" font-size="10" '
                     f'text-anchor="middle" fill="{COL["muted"]}">{d}</text>')

    # ---- rung lines + weighted bars in the gutter ------------------------
    max_w = max([r.get("weight", 0) for r in acc_rungs + dist_rungs] + [1])
    gutter = MR - 24

    def rung(r, color):
        yy = y(r["price"])
        st = r.get("state", "")
        dash = "" if st == "armed" else ' stroke-dasharray="4 3"'
        op = 1.0 if st in ("armed", "filled") else 0.55
        s.append(f'<line x1="{ML}" y1="{yy:.1f}" x2="{PLOT_R}" y2="{yy:.1f}" '
                 f'stroke="{color}" stroke-width="1.3" opacity="{op}"{dash}/>')
        # weighted bar
        blen = gutter * r.get("weight", 0) / max_w
        s.append(f'<rect x="{PLOT_R+6}" y="{yy-6:.1f}" width="{blen:.1f}" '
                 f'height="12" fill="{color}" opacity="{op}" rx="2"/>')
        tag = f'{r["price"]:,.0f} · {r.get("weight","")}%'
        if st:
            tag += f' · {st}'
        s.append(f'<text x="{PLOT_R+6}" y="{yy-9:.1f}" font-size="9.5" '
                 f'fill="{COL["text"]}">{esc(tag)}</text>')

    for r in acc_rungs:
        rung(r, COL["accum"])
    for r in dist_rungs:
        rung(r, COL["dist"])

    # ---- current price ---------------------------------------------------
    yc = y(close)
    s.append(f'<line x1="{ML}" y1="{yc:.1f}" x2="{PLOT_R}" y2="{yc:.1f}" '
             f'stroke="{COL["now"]}" stroke-width="1.6" stroke-dasharray="2 2"/>')
    s.append(f'<circle cx="{PLOT_R}" cy="{yc:.1f}" r="3.2" fill="{COL["now"]}"/>')
    s.append(f'<text x="{PLOT_R+6}" y="{yc+4:.1f}" font-size="10.5" '
             f'font-weight="700" fill="{COL["now"]}">PRIS {close:,.0f}</text>')

    # ---- invalidation ----------------------------------------------------
    if inval:
        yi = y(inval)
        s.append(f'<line x1="{ML}" y1="{yi:.1f}" x2="{PLOT_R}" y2="{yi:.1f}" '
                 f'stroke="{COL["inval"]}" stroke-width="2" stroke-dasharray="7 4"/>')
        s.append(f'<text x="{PLOT_R+6}" y="{yi+4:.1f}" font-size="10" '
                 f'font-weight="700" fill="{COL["inval"]}">INVALID {inval:,.0f}</text>')

    # frame
    s.append(f'<rect x="{ML}" y="{MT}" width="{PLOT_R-ML}" height="{H-MT-MB}" '
             f'fill="none" stroke="{COL["axis"]}" stroke-width="1"/>')
    # footnote
    s.append(f'<text x="{ML}" y="{H-8}" font-size="9" fill="{COL["muted"]}">'
             f'Barlängd ∝ rung-vikt · heldragen=armerad, streckad=pending · '
             f'verifiera nivåer mot Investtechs grafer.</text>')
    s.append('</svg>')
    return "\n".join(s)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    md = sys.argv[1]
    prices = sys.argv[2] if len(sys.argv) > 2 else "-"
    out = sys.argv[3] if len(sys.argv) > 3 else md.rsplit(".", 1)[0] + ".svg"
    fm = load_front_matter(md)
    candles = load_candles(prices)
    svg = build_svg(fm, candles)
    with open(out, "w") as f:
        f.write(svg)
    print(f"wrote {out} ({len(candles)} candles)")


if __name__ == "__main__":
    main()
