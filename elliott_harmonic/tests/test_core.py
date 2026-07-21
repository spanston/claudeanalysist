"""Unit tests for the HEW engine core: ratio helpers, fractal enumeration,
hard-rule gates, harmony scoring, and refusal behavior."""

from __future__ import annotations

from elliott.pivots import Pivot

from elliott_harmonic import ratios as R
from elliott_harmonic.engine import analyze_series
from elliott_harmonic.fractals import enumerate_fractals
from elliott_harmonic.score import pick_best
from elliott.data import Series


def mk_pivots(prices: list[float], first: str = "L") -> list[Pivot]:
    """Alternating-kind pivot list from a price path (default: first = trough).
    Pass first="H" for paths that start at a peak."""
    out = []
    for i, price in enumerate(prices):
        kind = first if i % 2 == 0 else ("H" if first == "L" else "L")
        out.append(Pivot(i=i, bar=i * 5, date=f"2026-01-{i + 1:02d}", price=price, kind=kind))
    return out


# Textbook up fractal: (i)=100->110 (len 10), (ii) 1-leg to 105 (50%),
# (iii)=105->127.36 (223.6% of (i), c3 > a3), (iv) 1-leg to 118.8 (38.2%,
# alt sum 0.882), (v)=118.8->134.98 (50% of (i)+(iii)); then a small tail.
TEXTBOOK = [100, 106, 103, 110,          # (i) a-b-c
            105,                          # (ii)
            118, 114, 127.36,             # (iii) a-b-c
            118.8,                        # (iv)
            126, 123, 134.98,             # (v) a-b-c
            130, 132]                     # tail (no new extreme)


def test_ratio_fit_hits_and_misses():
    assert R.nearest(2.24, R.W3_CLUSTERS) == 2.236
    assert R.ratio_fit(2.236, R.W3_CLUSTERS) == 1.0
    assert R.ratio_fit(2.11, R.W3_CLUSTERS, tol=0.06) == 0.0  # mid-gap between clusters
    assert 0.4 < R.ratio_fit(2.27, R.W3_CLUSTERS, tol=0.06) < 0.8
    assert R.alternation_fit(0.88) == 1.0
    assert R.alternation_fit(0.50) < 1.0
    assert R.alternation_fit(0.40) == 0.0


def test_textbook_fractal_found_and_scores_high():
    pivots = mk_pivots(TEXTBOOK)
    cands = enumerate_fractals(pivots)
    assert cands, "no candidates on a textbook fractal"
    best, ranked = pick_best(cands, pivots)
    assert best is not None
    assert best.direction == "up"
    assert best.complete
    sc = dict(ranked)[best] if isinstance(ranked, dict) else next(s for f, s in ranked if f is best)
    assert sc["harmony"] >= 0.7, f"textbook fractal should score high: {sc}"
    assert best.start == 0
    assert pivots[best.end_v].price == 134.98


def _one_fractal_pivots(prices):
    """Exactly one fractal, no tail."""
    return mk_pivots(prices)


def test_rule6_wave3_floor_rejects():
    # (iii) only 150% of (i) -> below the 172% rare floor.
    bad = [100, 106, 103, 110, 105, 116, 111, 120, 116, 122, 119, 124]
    cands = enumerate_fractals(_one_fractal_pivots(bad))
    assert not any(c.complete for c in cands), "rule 6 (176.4% floor) not enforced"


def test_rule4_iv_breach_rejects():
    # (iv) dips under the (b)-of-(iii) low (114 -> 113.5).
    bad = [100, 106, 103, 110, 105, 118, 114, 127.36, 113.5, 126, 123, 134.98]
    cands = enumerate_fractals(_one_fractal_pivots(bad))
    for c in cands:
        assert not (c.complete and c.start == 0), "rule 4 ((iv) vs (b) of (iii)) not enforced"


def test_rule1_ii_beyond_start_rejects():
    # (ii) retraces 100%+ of (i).
    bad = [100, 106, 103, 110, 99, 118, 114, 127.36, 118.8, 126, 123, 134.98]
    cands = enumerate_fractals(_one_fractal_pivots(bad))
    assert not any(c.complete and c.start == 0 for c in cands), "rule 1 not enforced"


def test_rule1_interior_leg_breach_rejects():
    # 3-leg (ii) whose INTERIOR leg prints 99.5 below the start of (i) (100)
    # but recovers to 105: the net depth (5 < 10) passes the endpoint check;
    # the interior extreme must still invalidate the count.
    from elliott_harmonic.fractals import Fractal, check_hard_rules
    bad = [100, 106, 103, 110, 99.5, 108, 105, 118, 114, 127.36, 118.8, 126, 123, 134.98]
    pivots = _one_fractal_pivots(bad)
    fr = Fractal("up", 0, 3, 1, len(bad) - 1, True, "done")
    assert "r1_ii_beyond_start_of_i" in check_hard_rules(fr, pivots)
    cands = enumerate_fractals(pivots)
    assert not any(c.complete and c.start == 0 for c in cands), \
        "rule 1 must gate on the (ii)-span extreme, not the (ii) endpoint"


def test_rule4_interior_leg_breach_rejects():
    # 3-leg (iv) whose interior (a) leg prints 113.5 under the (b)-of-(iii)
    # low (114) but recovers to 118.8: the endpoint check passes, the
    # interior extreme must not.
    from elliott_harmonic.fractals import Fractal, check_hard_rules
    bad = [100, 106, 103, 110, 105, 118, 114, 127.36, 113.5, 122, 118.8, 126, 123, 134.98]
    pivots = _one_fractal_pivots(bad)
    fr = Fractal("up", 0, 1, 3, len(bad) - 1, True, "done")
    assert "r4_iv_breaches_b_of_iii" in check_hard_rules(fr, pivots)
    cands = enumerate_fractals(pivots)
    assert not any(c.complete and c.start == 0 for c in cands), \
        "rule 4 must gate on the (iv)-span extreme, not the (iv) endpoint"


def test_c3_below_a3_rejects():
    # (c) of (iii) shorter than (a) of (iii): a3 = 13, c3 = 9.36.
    bad = [100, 106, 103, 110, 105, 118, 116, 125.36, 120, 126, 123, 130]
    cands = enumerate_fractals(_one_fractal_pivots(bad))
    assert not any(c.complete and c.start == 0 for c in cands), "c-of-(iii) >= a-of-(iii) not enforced"


def test_refusal_on_directionless_chop():
    # Sawtooth with no trend: no fractal should survive the span floor + rules.
    chop = [100 + (5 if i % 2 else 0) for i in range(30)]
    pivots = mk_pivots(chop)
    cands = enumerate_fractals(pivots, min_span_frac=0.5)
    assert not cands


def test_open_fractal_in_wave_iii():
    # Fractal truncated inside (iii): (i), (ii) done, (iii) leg (c) at the edge.
    partial = [100, 106, 103, 110, 105, 118, 114, 122]
    pivots = mk_pivots(partial)
    cands = enumerate_fractals(pivots)
    opens = [c for c in cands if not c.complete]
    assert opens, "expected an open (in-progress) candidate at the right edge"
    best, _ = pick_best(cands, pivots)
    assert best is not None and not best.complete
    assert best.stage == "iii"


def test_youngest_candidate_not_dropped():
    # 6 pivots = (i) 3 legs + (ii) 1 leg + (a)-of-(iii) at the right edge:
    # a feasible open stage-(iii) start that an off-by-one used to skip.
    pivots = mk_pivots([100, 106, 103, 110, 105, 116])
    cands = enumerate_fractals(pivots)
    assert any(not c.complete and c.stage == "iii" and c.start == 0 for c in cands)


def test_open_wave_v_must_hold_iv_extreme():
    # The right edge breaks below the (iv) low: the in-(v) reading must be
    # rejected (ratchet guard -- the count is already invalidated by price).
    prices = [100, 106, 103, 110, 105, 118, 114, 127.36, 118.8, 122, 117.0]
    pivots = mk_pivots(prices)
    cands = enumerate_fractals(pivots)
    assert not any(c.start == 0 and c.stage == "v" for c in cands)


def test_superseded_completion_dropped():
    # A "completed" fractal whose tail makes a new extreme beyond (v) was
    # overrun: not a completion, drop it.
    prices = TEXTBOOK + [131, 136]  # tail exceeds the 134.98 (v) extreme
    pivots = mk_pivots(prices)
    cands = enumerate_fractals(pivots)
    assert not any(c.complete and c.start == 0 and pivots[c.end_v].price == 134.98
                   for c in cands)


def _analyze_with_pivots(monkeypatch, pivots, last_close=None):
    from elliott_harmonic import engine as eng
    monkeypatch.setattr(eng, "calibrate_pivots", lambda *a, **kw: (1.0, pivots))
    n = 60
    dates = [f"2026-{(i // 28) + 1:02d}-{(i % 28) + 1:02d}" for i in range(n)]
    closes = [100 + i * 0.1 for i in range(n)]
    if last_close is not None:
        closes[-1] = last_close
    series = Series(dates=dates, opens=closes, highs=[c * 1.001 for c in closes],
                    lows=[c * 0.999 for c in closes], closes=closes, volumes=[1e6] * n)
    return eng.analyze_series(series, "TEST", "2026-07-21", horizon=None)


def test_corrective_fallback_on_zigzag_decline(monkeypatch):
    # Clean zigzag down (A=120->100, B=106.7, C=106.7->86.7, C=A equality):
    # no impulse candidate clears the floor, so the corrective reading leads.
    pivots = mk_pivots([120, 110, 113, 100, 106.7, 100, 103, 86.7], first="H")
    report = _analyze_with_pivots(monkeypatch, pivots)
    assert not report["no_clean_count"], report["message"]
    pref = report["preferred"]
    assert pref["status"] == "corrective"
    assert pref["stage"] == "zigzag"
    assert pref["direction"] == "down"
    assert pref["targets"] and pref["invalidations"][0]["binding"]


def test_corrective_fallback_rejects_falsified_reading(monkeypatch):
    # Down zigzag 180->146 whose invalidation (start of A = 180) is already
    # exceeded by the last close (183): the reading is dead on arrival and
    # must not be emitted. Control: close at 170 keeps it alive.
    pivots = mk_pivots([180, 172, 175, 160, 166, 158, 161, 146, 168, 183], first="H")
    alive = _analyze_with_pivots(monkeypatch, pivots, last_close=170.0)
    assert not alive["no_clean_count"], alive["message"]
    assert alive["preferred"]["stage"] == "zigzag"
    assert alive["preferred"]["invalidations"][0]["price"] == 180
    dead = _analyze_with_pivots(monkeypatch, pivots, last_close=183.0)
    assert dead["no_clean_count"], "falsified corrective reading must not be emitted"
    assert dead["preferred"] is None
    # The provisional right-edge flag is unconditional (the last zigzag pivot
    # is always the unconfirmed running candidate).
    assert any("provisional" in w for w in dead["warnings"])


def test_aftermath_targets_drop_stale_levels(monkeypatch):
    # Completed up fractal + tail that already fell into the (b)-of-(v) span
    # (tail prints 126): the zone target is stale and dropped; the deeper
    # prior-(iv) target (118.8) is still live.
    tail_zigzag = [130, 131.5, 126, 129, 127, 128, 123.5]
    pivots = mk_pivots(TEXTBOOK[:12] + tail_zigzag)
    report = _analyze_with_pivots(monkeypatch, pivots)
    pref = report["preferred"]
    assert pref["status"] == "completed"
    labels = [t["label"] for t in pref["targets"]]
    assert "span of (b) of (v)" not in labels
    assert "prior (iv) extreme" in labels


def test_cli_summary_prints_zone_targets(monkeypatch, capsys):
    # A flat corrective reading carries "zone" targets, not "price": the
    # summary printer must branch instead of KeyErroring.
    from elliott_harmonic.cli import _print_summary
    pivots = mk_pivots([100, 106, 103, 110, 104, 109, 100.2, 105.7, 103.2, 110])
    report = _analyze_with_pivots(monkeypatch, pivots)
    assert not report["no_clean_count"], report["message"]
    assert report["preferred"]["stage"].startswith("flat")
    assert any("zone" in t for t in report["preferred"]["targets"])
    _print_summary(report)
    out = capsys.readouterr().out
    assert "Target (C terminal zone (A extreme))" in out


def test_aftermath_correction_on_completed_fractal(monkeypatch):
    # Textbook fractal (no tail) + a zigzag-down aftermath: preferred stays
    # the completed impulse, and the tail gets a corrective aftermath reading.
    tail_zigzag = [130, 131.5, 126, 129, 127, 128, 123.5]
    pivots = mk_pivots(TEXTBOOK[:12] + tail_zigzag)
    report = _analyze_with_pivots(monkeypatch, pivots)
    assert not report["no_clean_count"], report["message"]
    pref = report["preferred"]
    assert pref["status"] == "completed"
    ac = pref.get("aftermath_correction")
    assert ac is not None, "expected an aftermath corrective reading on the tail"
    assert ac["status"] == "corrective" and ac["direction"] == "down"
    assert ac["stage"] == "zigzag"


def test_analyze_series_end_to_end(monkeypatch):
    # Engine-level orchestration: with the zigzag stubbed to the textbook
    # corner pivots, analyze_series must prefer the completed fractal and
    # emit targets + invalidations. (Zigzag behavior itself is covered by
    # elliott/tests/test_pivots.py; a 65-bar synthetic starves its ATR warmup.)
    from elliott_harmonic import engine as eng

    pivots = mk_pivots(TEXTBOOK)
    monkeypatch.setattr(eng, "calibrate_pivots", lambda *a, **kw: (1.0, pivots))

    n = 60
    dates = [f"2026-{(i // 28) + 1:02d}-{(i % 28) + 1:02d}" for i in range(n)]
    closes = [100 + i * 0.1 for i in range(n)]
    series = Series(dates=dates, opens=closes, highs=[c * 1.001 for c in closes],
                    lows=[c * 0.999 for c in closes], closes=closes, volumes=[1e6] * n)
    report = eng.analyze_series(series, "TEST", "2026-07-21", horizon=None)
    assert not report["no_clean_count"], report["message"]
    pref = report["preferred"]
    assert pref["direction"] == "up"
    assert pref["status"] == "completed"
    assert pref["harmony"] >= 0.7
    assert pref["targets"] and pref["invalidations"]
    assert pref["end"]["price"] == 134.98
