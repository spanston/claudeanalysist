"""Horizon-adaptive degree selection: horizon parsing, window refinement
mechanics, duration measurement, and an end-to-end run over a synthetic
multi-scale OHLC series (fetch injected, no network)."""

from datetime import date, timedelta

import pytest

from elliott import horizon as H
from elliott.data import Series
from elliott.parser import WaveUnit


# ---------------------------------------------------------------------------
# parse_horizon
# ---------------------------------------------------------------------------

def test_parse_horizon_valid():
    assert H.parse_horizon("90d") == 90
    assert H.parse_horizon("26w") == 130
    assert H.parse_horizon("3m") == 63
    assert H.parse_horizon("6m") == 126
    assert H.parse_horizon("12m") == 252
    assert H.parse_horizon("1y") == 252
    assert H.parse_horizon("6M") == 126      # case-insensitive
    assert H.parse_horizon(" 6m ") == 126    # surrounding whitespace tolerated


def test_parse_horizon_invalid():
    for bad in ("", "6", "6x", "-3m", "0m", "m", "6mm", "1.5y"):
        with pytest.raises(ValueError):
            H.parse_horizon(bad)


# ---------------------------------------------------------------------------
# next_window
# ---------------------------------------------------------------------------

def test_next_window_within_tolerance_stops():
    # 0.75*126 = 94.5, 1.33*126 = 167.58
    assert H.next_window(1000, 94.5, 126, 5000) is None
    assert H.next_window(1000, 126, 126, 5000) is None
    assert H.next_window(1000, 167.5, 126, 5000) is None
    assert H.next_window(1000, 168.0, 126, 5000) is not None


def test_next_window_rescales_by_ratio():
    assert H.next_window(1000, 63, 126, 5000) == 2000   # waves too fast -> widen
    assert H.next_window(1000, 300, 126, 5000) == 420   # waves too slow -> narrow


def test_next_window_clamps():
    assert H.next_window(400, 500, 63, 5000) == H.WINDOW_MIN_BARS  # below floor
    assert H.next_window(1000, 30, 126, 3000) == 3000              # above history


def test_next_window_degenerate_median_stops():
    assert H.next_window(1000, 0, 126, 5000) is None


# ---------------------------------------------------------------------------
# closed_d1_durations
# ---------------------------------------------------------------------------

def _unit(start_bar, end_bar, open_=False):
    return WaveUnit(i=0, j=1, pattern=None, start_price=1.0, end_price=2.0,
                    hi=2.0, lo=1.0, direction="up", n_pivots=1,
                    start_bar=start_bar, end_bar=end_bar, open=open_)


def test_closed_d1_durations_excludes_open_edge():
    root = _unit(0, 100)
    root.children = (_unit(0, 40), _unit(40, 80), _unit(80, 100, open_=True))
    assert H.closed_d1_durations(root) == [40, 40]


def test_slice_series_takes_last_bars():
    s = Series(dates=[f"d{i}" for i in range(10)], opens=[0] * 10, highs=[1] * 10,
               lows=[0] * 10, closes=[float(i) for i in range(10)], volumes=[0] * 10)
    out = H.slice_series(s, 4)
    assert out.dates == ["d6", "d7", "d8", "d9"]
    assert out.closes == [6.0, 7.0, 8.0, 9.0]


# ---------------------------------------------------------------------------
# end-to-end: run_for_horizon over a synthetic multi-scale series
# ---------------------------------------------------------------------------

def _texture(prices, depth):
    """Self-similar textured path: every leg replaced by a 5-leg textured
    sub-path, `depth` levels deep (5^depth smallest legs)."""
    if depth == 0:
        return prices
    out = [prices[0]]
    for a, b in zip(prices, prices[1:]):
        p1 = a + 0.5 * (b - a)
        p2 = p1 - 0.3 * (p1 - a)
        p3 = p1 + 0.6 * (b - p1)
        p4 = p3 - 0.3 * (p3 - p2)
        out.extend(_texture([p1, p2, p3, p4, b], depth - 1))
    return out


def _synthetic_series(n_bars=700):
    path = _texture([100.0, 450.0], 3)  # 125 smallest legs, prices stay > 0
    step = (n_bars - 1) / (len(path) - 1)
    closes = []
    for t in range(n_bars):
        x = t / step
        idx = min(int(x), len(path) - 2)
        frac = x - idx
        closes.append(path[idx] + frac * (path[idx + 1] - path[idx]))
    d0 = date(2023, 1, 1)
    return Series(
        dates=[(d0 + timedelta(days=t)).isoformat() for t in range(n_bars)],
        opens=closes,
        highs=[c * 1.001 for c in closes],
        lows=[c * 0.999 for c in closes],
        closes=closes,
        volumes=[0.0] * n_bars,
    )


def test_run_for_horizon_end_to_end():
    n_bars = 700
    fake = lambda ticker, period="10y": _synthetic_series(n_bars)
    res = H.run_for_horizon("TEST", "3m", fetcher=fake, run_date="2026-07-20")
    report = res["report"]
    hz = report["meta"]["horizon"]

    assert hz["target_bars"] == 63
    assert hz["fit"] in ("ok", "unresolved", "no_clean_count", "history_limited")
    assert 1 <= len(hz["iterations"]) <= H.MAX_ITERS
    assert all(H.WINDOW_MIN_BARS <= it["window_bars"] <= n_bars
               for it in hz["iterations"])
    assert hz["window_bars"] in [it["window_bars"] for it in hz["iterations"]]

    # Window mechanics: each refinement must equal next_window() applied to
    # the previous iteration's own measurement.
    its = hz["iterations"]
    for a, b in zip(its, its[1:]):
        assert a["median_d1_bars"] is not None
        assert b["window_bars"] == H.next_window(
            a["window_bars"], a["median_d1_bars"], hz["target_bars"], n_bars)

    if hz["fit"] == "ok":
        assert hz["degree1_median_bars"] is not None
        assert H.TOL_LO * hz["target_bars"] <= hz["degree1_median_bars"] \
               <= H.TOL_HI * hz["target_bars"]
        assert its[-1]["decision"] == "accept"
    if hz["fit"] in ("unresolved", "history_limited") and not report["no_clean_count"]:
        assert any(w.startswith(f"horizon_fit_{hz['fit']}") for w in report["warnings"])


def test_run_for_horizon_history_limited():
    # Source pool far smaller than the 8x initial window -> clamp, warn.
    n_bars = 300
    fake = lambda ticker, period="10y": _synthetic_series(n_bars)
    res = H.run_for_horizon("TEST", "1y", fetcher=fake, run_date="2026-07-20")
    hz = res["report"]["meta"]["horizon"]
    assert hz["iterations"][0]["window_bars"] == n_bars  # clamped to available
