"""Yahoo Finance OHLCV fetch with a parquet cache.

Fetches directly against Yahoo's public chart JSON endpoint via `requests`
rather than through the `yfinance` package's session machinery: yfinance's
default HTTP client (curl_cffi, for TLS-fingerprint impersonation) does not
tunnel cleanly through a TLS-re-terminating proxy, which this environment
sits behind. `requests` respects HTTPS_PROXY correctly and hits the same
endpoint yfinance itself wraps, so the data and ticker conventions are
identical -- only the transport differs.

DESIGN.md §1: guideline ratios are computed arithmetically per wave (scale
-free already); log prices are used only for channel/trendline fits and
rendering, not baked into the fetch layer.
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone

import pandas as pd
import requests

CACHE_DIR = os.path.join(os.path.dirname(__file__), ".cache")
CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"


@dataclass(frozen=True)
class Series:
    dates: list[str]
    opens: list[float]
    highs: list[float]
    lows: list[float]
    closes: list[float]
    volumes: list[float]


def _fetch_chart(ticker: str, range_: str, interval: str) -> pd.DataFrame:
    resp = requests.get(
        CHART_URL.format(ticker=ticker),
        params={"range": range_, "interval": interval},
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=15,
    )
    resp.raise_for_status()
    payload = resp.json()
    chart = payload.get("chart", {})
    if chart.get("error"):
        raise ValueError(f"Yahoo chart API error for {ticker!r}: {chart['error']}")
    result = chart.get("result")
    if not result:
        raise ValueError(f"Yahoo chart API returned no data for {ticker!r}")

    r = result[0]
    granularity = r.get("meta", {}).get("dataGranularity")
    if granularity and granularity != interval:
        # Yahoo silently downgrades to a coarser granularity for very long
        # ranges (observed: range="max" on BTC-USD returns monthly bars
        # even though interval="1d" was requested) rather than erroring --
        # fail loudly instead of quietly parsing monthly bars as daily.
        raise ValueError(
            f"Yahoo returned {granularity!r} bars for {ticker!r}, not the requested "
            f"{interval!r} (this happens with very long `range` values, e.g. 'max' -- "
            f"use an explicit bound like '10y' instead)"
        )
    ts = r["timestamp"]
    quote = r["indicators"]["quote"][0]

    rows = []
    for i, t in enumerate(ts):
        o, h, lo, c, v = (quote[k][i] for k in ("open", "high", "low", "close", "volume"))
        if None in (o, h, lo, c):
            continue
        date = datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%d")
        rows.append((date, o, h, lo, c, v or 0.0))

    df = pd.DataFrame(rows, columns=["Date", "Open", "High", "Low", "Close", "Volume"])
    # Multiple intraday timestamps can share a UTC date for some tickers;
    # keep the last bar of each date so output is strictly one row/day.
    df = df.drop_duplicates(subset="Date", keep="last").reset_index(drop=True)
    return df


def fetch_ohlcv(ticker: str, period: str = "10y", interval: str = "1d",
                  max_age_hours: float = 12.0, cache_dir: str | None = None) -> Series:
    """Fetch daily OHLCV for `ticker`, cached to parquet under
    elliott/.cache/. Re-fetches when the cache is older than
    `max_age_hours` or absent. `period` accepts Yahoo Finance range strings
    ("10y", "5y", "2y", "1y", "6mo", ...) -- avoid "max": Yahoo silently
    downgrades very long ranges to monthly bars even when interval="1d" is
    requested (see the granularity check in _fetch_chart)."""
    cache_dir = cache_dir or CACHE_DIR
    os.makedirs(cache_dir, exist_ok=True)
    safe_ticker = re.sub(r"[^A-Za-z0-9._-]+", "_", ticker)
    safe_period = re.sub(r"[^A-Za-z0-9._-]+", "_", period)
    cache_path = os.path.join(cache_dir, f"{safe_ticker}_{interval}_{safe_period}.parquet")

    df = None
    if os.path.exists(cache_path):
        age_hours = (time.time() - os.path.getmtime(cache_path)) / 3600.0
        if age_hours <= max_age_hours:
            df = pd.read_parquet(cache_path)

    if df is None:
        df = _fetch_chart(ticker, period, interval)
        if df.empty:
            raise ValueError(f"No data returned for {ticker!r}")
        df.to_parquet(cache_path)

    return Series(
        dates=df["Date"].tolist(),
        opens=df["Open"].astype(float).tolist(),
        highs=df["High"].astype(float).tolist(),
        lows=df["Low"].astype(float).tolist(),
        closes=df["Close"].astype(float).tolist(),
        volumes=df["Volume"].astype(float).tolist(),
    )
