"""Incremental cache updater: probe-then-bridge refreshes only when new
candles exist, with full-refetch fallbacks for gaps and split basis
changes. All network is faked via the injectable fetcher."""

import pandas as pd
import pytest

from elliott.data import update_ohlcv


def _df(dates, closes):
    return pd.DataFrame({
        "Date": dates, "Open": closes, "High": closes,
        "Low": closes, "Close": closes, "Volume": [0.0] * len(dates),
    })


def _fake_fetcher(history, probe, bridge, full):
    """fetcher(ticker, range_, interval) dispatching on the range string;
    records calls so tests can assert no needless download happened.
    None probe/bridge falls back to `full` (tests that never reach them)."""
    calls = []
    mapping = {"5d": probe, "3mo": bridge}
    def fetch(ticker, range_, interval):
        calls.append(range_)
        df = mapping.get(range_)
        if df is None:
            df = full
        return df.copy()
    fetch.calls = calls
    return fetch


def test_no_cache_full_fetch(tmp_path):
    full = _df(["2026-07-15", "2026-07-16", "2026-07-17"], [100, 101, 102])
    fetch = _fake_fetcher(None, None, None, full)
    series, status = update_ohlcv("TEST", cache_dir=str(tmp_path), fetcher=fetch)
    assert status["refreshed"] == "full" and status["added"] == 3
    assert series.closes == [100, 101, 102]
    assert (tmp_path / "TEST_1d_10y.parquet").exists()


def test_up_to_date_probes_only(tmp_path):
    hist = _df(["2026-07-15", "2026-07-16", "2026-07-17"], [100, 101, 102])
    hist.to_parquet(tmp_path / "TEST_1d_10y.parquet")
    probe = _df(["2026-07-16", "2026-07-17"], [101, 102])
    fetch = _fake_fetcher(None, probe, None, None)
    series, status = update_ohlcv("TEST", cache_dir=str(tmp_path), fetcher=fetch)
    assert status["refreshed"] == "none" and status["added"] == 0
    assert fetch.calls == ["5d"]  # no bridge, no full download
    assert series.closes == [100, 101, 102]


def test_stale_cache_bridged_incrementally(tmp_path):
    hist = _df(["2026-07-13", "2026-07-14", "2026-07-15"], [100, 101, 102])
    hist.to_parquet(tmp_path / "TEST_1d_10y.parquet")
    probe = _df(["2026-07-16", "2026-07-17"], [103, 104])
    bridge = _df(["2026-07-14", "2026-07-15", "2026-07-16", "2026-07-17"],
                 [101, 102, 103, 104])
    fetch = _fake_fetcher(None, probe, bridge, None)
    series, status = update_ohlcv("TEST", cache_dir=str(tmp_path), fetcher=fetch)
    assert status["refreshed"] == "incremental" and status["added"] == 2
    assert series.dates == ["2026-07-13", "2026-07-14", "2026-07-15",
                            "2026-07-16", "2026-07-17"]
    assert series.closes == [100, 101, 102, 103, 104]


def test_gap_triggers_full_refetch(tmp_path):
    hist = _df(["2026-01-05", "2026-01-06"], [100, 101])  # months stale
    hist.to_parquet(tmp_path / "TEST_1d_10y.parquet")
    probe = _df(["2026-07-16", "2026-07-17"], [103, 104])
    bridge = _df(["2026-04-20", "2026-04-21"], [102, 103])  # starts after cache end -> gap
    full = _df(["2026-01-05", "2026-01-06", "2026-07-16", "2026-07-17"],
               [100, 101, 103, 104])
    fetch = _fake_fetcher(None, probe, bridge, full)
    series, status = update_ohlcv("TEST", cache_dir=str(tmp_path), fetcher=fetch)
    assert status["refreshed"] == "full"
    assert series.dates[-1] == "2026-07-17"


def test_split_basis_change_triggers_full_refetch(tmp_path):
    hist = _df(["2026-07-15", "2026-07-16"], [1000, 1010])  # pre-split basis
    hist.to_parquet(tmp_path / "TEST_1d_10y.parquet")
    probe = _df(["2026-07-16", "2026-07-17"], [101, 102])   # 10:1 adjusted
    full = _df(["2026-07-15", "2026-07-16", "2026-07-17"], [100, 101, 102])
    fetch = _fake_fetcher(None, probe, None, full)
    series, status = update_ohlcv("TEST", cache_dir=str(tmp_path), fetcher=fetch)
    assert status["refreshed"] == "full"
    assert series.closes == [100, 101, 102]


def test_split_during_gap_stale_beyond_probe_window(tmp_path):
    """Cache 15 sessions stale (probe "5d" has NO overlap with cache end),
    split inside the gap: the bridge reveals the basis change and the
    updater must full-refetch, never merge a mixed-basis series."""
    hist = _df([f"2026-06-{d:02d}" for d in (22, 23, 24, 25, 26)],
               [1000, 1010, 1005, 1020, 1000])
    hist.to_parquet(tmp_path / "TEST_1d_10y.parquet")
    probe = _df(["2026-07-16", "2026-07-17"], [101, 102])  # no 2026-06-26 row
    bridge = _df(["2026-06-25", "2026-06-26", "2026-07-16", "2026-07-17"],
                 [100.5, 100.0, 101, 102])                  # adjusted basis
    full = _df(["2026-06-22", "2026-06-23", "2026-07-17"], [100, 101, 102])
    fetch = _fake_fetcher(None, probe, bridge, full)
    series, status = update_ohlcv("TEST", cache_dir=str(tmp_path), fetcher=fetch)
    assert status["refreshed"] == "full", "split during a probe-invisible gap must full-refetch"
    assert series.closes == [100, 101, 102]


def test_empty_probe_raises_value_error(tmp_path):
    hist = _df(["2026-07-15"], [100])
    hist.to_parquet(tmp_path / "TEST_1d_10y.parquet")
    fetch = _fake_fetcher(None, _df([], []), None, None)
    with pytest.raises(ValueError):
        update_ohlcv("TEST", cache_dir=str(tmp_path), fetcher=fetch)


def test_empty_full_frame_raises_before_writing_cache(tmp_path):
    """An empty frame on the no-cache path must raise BEFORE the parquet
    write: writing it poisons the cache (every later call reads the empty
    frame and fails the same way) instead of self-healing."""
    fetch = _fake_fetcher(None, None, None, _df([], []))
    with pytest.raises(ValueError, match="No data returned"):
        update_ohlcv("TEST", cache_dir=str(tmp_path), fetcher=fetch)
    assert not (tmp_path / "TEST_1d_10y.parquet").exists()


def test_empty_full_refetch_preserves_existing_cache(tmp_path):
    """Same guard on the gap-fallback full refetch: the existing cache must
    survive untouched when the re-download comes back empty."""
    hist = _df(["2026-01-05", "2026-01-06"], [100, 101])  # months stale
    hist.to_parquet(tmp_path / "TEST_1d_10y.parquet")
    probe = _df(["2026-07-16", "2026-07-17"], [103, 104])
    bridge = _df(["2026-04-20", "2026-04-21"], [102, 103])  # starts after cache end -> gap
    fetch = _fake_fetcher(None, probe, bridge, _df([], []))
    with pytest.raises(ValueError, match="No data returned"):
        update_ohlcv("TEST", cache_dir=str(tmp_path), fetcher=fetch)
    cached = pd.read_parquet(tmp_path / "TEST_1d_10y.parquet")
    assert cached["Close"].tolist() == [100, 101]
