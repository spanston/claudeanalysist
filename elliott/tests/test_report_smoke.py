"""End-to-end smoke test: pivots -> parser -> anchor tournament -> report,
on the same textured-impulse fixture used by the grammar round-trip test,
extended with an open (in-progress) tail so the right-edge logic is
exercised too."""

from elliott.anchor import run_tournament
from elliott.guidelines import fit_null_model
from elliott.parser import build_pattern_memo
from elliott.pivots import Pivot
from elliott.report import build_report, render_svg_labeled
from .test_grammar_roundtrip import _build_impulse_pivots


def test_report_end_to_end():
    base = _build_impulse_pivots()
    # extend with a couple more legs so wave 5 reads as "in progress"
    extra = [
        Pivot(len(base), base[-1].bar + 2, "d_extra1", base[-1].price + 40, "H" if base[-1].kind == "L" else "L"),
        Pivot(len(base) + 1, base[-1].bar + 4, "d_extra2", base[-1].price + 20, base[-1].kind),
    ]
    pivots = base + extra  # open tail included: exercises the right-edge logic
    null = fit_null_model(pivots)
    ctx = {"atr_epsilon": 0.0}
    memo = build_pattern_memo(pivots, null, ctx, k=4)
    tournament = run_tournament(pivots, memo, null, ctx, k=4)

    report = build_report("TEST", "2026-01-01", pivots, tournament, pivot_k=1.0)
    assert "meta" in report
    assert report["meta"]["monowaves"] == len(pivots)

    if not report["no_clean_count"]:
        assert "position" in report["preferred"]
        assert report["preferred"]["position"]["text_en"]
        root = tournament.winner.root
        svg = render_svg_labeled(pivots, root, report)
        assert svg.startswith("<svg")
        assert "</svg>" in svg
    else:
        assert "message" in report
