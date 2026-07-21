"""Completed-root + reversal-tail readings (DESIGN.md §4: "pattern just
completed, larger-degree reversal just began"). The root must not be forced
to partition the whole window into its own components: when a degree-2
pattern completes before the right edge, the trailing counter-move is the
first wave of the NEXT pattern, reported as a primed label (e.g. A').
"""

from elliott.anchor import _uplift, run_tournament
from elliott.guidelines import fit_null_model
from elliott.parser import WaveUnit, build_pattern_memo, _reversal_readings
from elliott.pivots import Pivot
from elliott.report import build_position, build_report, render_svg_labeled, walk_labels
from .test_grammar_roundtrip import _textured3, _textured5, _flip


# ---------------------------------------------------------------------------
# unit: pairing guards in _reversal_readings
# ---------------------------------------------------------------------------

def _leaf(i, j, direction, total=0.0, open_=False):
    return WaveUnit(i=i, j=j, pattern=None, start_price=1.0, end_price=2.0,
                    hi=2.0, lo=1.0, direction=direction, n_pivots=j - i,
                    start_bar=i, end_bar=j, total_ll=total, open=open_)


def test_reversal_pairing_guards():
    # completed root [0,5], last child moves up
    core = (_leaf(0, 3, "down", total=2.0), _leaf(3, 5, "up", total=3.0))
    root = WaveUnit(i=0, j=5, pattern="zigzag", start_price=1.0, end_price=2.0,
                    hi=2.0, lo=1.0, direction="up", n_pivots=5, start_bar=0, end_bar=5,
                    children=core, ll=1.0, total_ll=5.0)

    def tail(direction, n_closed, n_open, name="zigzag"):
        kids = tuple(_leaf(5, 6, "down", open_=False) for _ in range(n_closed)) + \
               tuple(_leaf(6, 9, direction, open_=True) for _ in range(n_open))
        t = WaveUnit(i=5, j=9, pattern=name, start_price=2.0, end_price=1.5,
                     hi=2.0, lo=1.5, direction=direction, n_pivots=4, start_bar=5,
                     end_bar=9, children=kids, total_ll=-0.5, open=True)
        return t

    memo = {
        (5, 9, "zigzag", True): [
            tail("down", 2, 1),   # eligible: final-open, >=2 closed, opposite dir
            tail("up", 2, 1),     # rejected: same direction as root's last child
            tail("down", 1, 1),   # rejected: only one closed component
            tail("down", 1, 2),   # rejected: len(children) == 3 but two open... actually 3 kids -> final-open with 1 closed -> rejected
        ],
    }
    out = _reversal_readings(memo, {5: [root]}, 10)
    assert len(out) == 1
    w = out[0]
    assert w.reversal and w.j == 9 and len(w.children) == 3
    assert w.direction == "down"           # live move is the tail's
    assert abs(w.total_ll - (5.0 - 0.5)) < 1e-9


def test_uplift_excludes_tail():
    core = (_leaf(0, 3, "down", total=2.0), _leaf(3, 5, "up", total=3.0))
    t = _leaf(5, 9, "down", total=1.0, open_=True)
    w = WaveUnit(i=0, j=9, pattern="zigzag", start_price=1.0, end_price=1.5,
                 hi=2.0, lo=1.0, direction="down", n_pivots=9, start_bar=0, end_bar=9,
                 children=core + (t,), ll=1.0, total_ll=6.0, open=True, reversal=True)
    # (6.0 - 1.0) - max(2.0, 3.0) = 2.0
    assert _uplift(w) == 2.0


# ---------------------------------------------------------------------------
# end-to-end: nested 2-degree impulse that completed, then a decline tail
# ---------------------------------------------------------------------------

def _nested(start, end, kind0, slot, depth):
    """Recursively textured pivot path start->end. depth 2 gives each big
    leg enough monowaves to parse as a degree-1 pattern of leaf runs."""
    if depth == 0:
        return [(start, kind0), (end, _flip(kind0))]
    pts, kinds = _textured5(start, end, kind0) if slot == "5" else _textured3(start, end, kind0)
    out = []
    for a, b, ka in zip(pts, pts[1:], kinds):
        sub_slot = "5" if (b > a) == (end > start) else "3"
        seg = _nested(a, b, ka, sub_slot, depth - 1)
        out.extend(seg if not out else seg[1:])
    return out


def _build_two_degree_impulse_with_decline():
    """A clean self-similar degree-2 impulse completing at 450, followed by
    a degree-1 zigzag decline (A, B closed; C underway)."""
    segs = [
        (100, 200, "L", "5"), (200, 150, "H", "3"), (150, 380, "L", "5"),
        (380, 320, "H", "3"), (320, 450, "L", "5"),
    ]
    pts = []
    for start, end, k0, slot in segs:
        seg = _nested(start, end, k0, slot, 2)
        pts.extend(seg if not pts else seg[1:])

    a = _textured5(450, 300, "H")          # A down: 5 monowaves
    b = _textured3(300, 360, "L")          # B up: 3 monowaves, 40% retrace
    c_pts = [325.0, 290.0]                 # C underway: 360 -> 310 -> 325 -> 290
    tail = list(zip(a[0][1:], a[1][1:])) + list(zip(b[0][1:], b[1][1:]))
    tail += [(310.0, "L"), (325.0, "H"), (290.0, "L")]
    pts.extend(tail)

    return [Pivot(i, i * 2, f"d{i}", pr, kd) for i, (pr, kd) in enumerate(pts)]


def test_reversal_readings_deduped_by_pattern_and_completion():
    """Variants of the same reading (same pattern, same completion point)
    must collapse to the best one -- the k-best is for genuinely different
    readings, not duplicates of one."""
    def mk_root(m, total):
        return WaveUnit(i=0, j=m, pattern="zigzag", start_price=1.0, end_price=2.0,
                        hi=2.0, lo=1.0, direction="up", n_pivots=m, start_bar=0, end_bar=m,
                        children=(_leaf(0, 3, "down", total=1.0), _leaf(3, m, "up", total=total)),
                        ll=0.5, total_ll=total)

    pts = [(1.0, "L"), (1.5, "H"), (1.2, "L"), (1.8, "H"), (1.4, "L"), (2.0, "H"),
           (1.7, "L"), (1.9, "H"), (1.5, "L"), (1.6, "H")]
    pivots = [Pivot(i, i, f"d{i}", pr, kd) for i, (pr, kd) in enumerate(pts)]

    same_m = [mk_root(5, 4.0), mk_root(5, 6.0)]   # duplicates: keep the 6.0 one
    out = _reversal_readings({}, {5: same_m}, 10, pivots=pivots)
    assert len(out) == 1
    assert out[0].total_ll == 6.0

    two_ms = [mk_root(5, 4.0), mk_root(7, 5.0)]   # different completions: both kept
    out = _reversal_readings({}, {5: [two_ms[0]], 7: [two_ms[1]]}, 10, pivots=pivots)
    assert len(out) == 2


def test_bare_tail_must_not_exceed_completion_point():
    # closed root (last child up, ending at 200) + young counter-move
    root = WaveUnit(i=0, j=5, pattern="zigzag", start_price=100.0, end_price=200.0,
                    hi=200.0, lo=100.0, direction="up", n_pivots=5, start_bar=0, end_bar=5,
                    children=(_leaf(0, 3, "down", total=2.0), _leaf(3, 5, "up", total=3.0)),
                    ll=1.0, total_ll=5.0)

    def pivots_with(high_after):
        pts = [(100, "L"), (150, "H"), (120, "L"), (180, "H"), (140, "L"), (200, "H"),
               (170, "L"), (high_after, "H"), (150, "L"), (165, "H"), (130, "L"), (145, "H")]
        return [Pivot(i, i, f"d{i}", pr, kd) for i, (pr, kd) in enumerate(pts)]

    # clean young decline: no new high above the 200 completion point
    out = _reversal_readings({}, {5: [root]}, 12, pivots=pivots_with(185.0))
    assert len(out) == 1 and out[0].reversal
    # tail containing a new high at 210: the "reversal" is falsified
    out = _reversal_readings({}, {5: [root]}, 12, pivots=pivots_with(210.0))
    assert out == []


def test_completed_impulse_plus_reversal_tail_is_found():
    pivots = _build_two_degree_impulse_with_decline()
    null = fit_null_model(pivots)
    ctx = {"atr_epsilon": 0.0}
    memo = build_pattern_memo(pivots, null, ctx, k=4)
    tournament = run_tournament(pivots, memo, null, ctx, k=4)

    assert not tournament.no_clean_count
    root = tournament.winner.root
    assert root.reversal, (
        f"expected a completed-root+tail reading, got {root.pattern} "
        f"({','.join(c.label + ('~' if c.open else '') for c in root.children)})")

    tail = root.children[-1]
    assert tail.pattern == "zigzag" and tail.direction == "down"

    pos = build_position(root)
    assert "complete" in pos["text_en"] and "underway" in pos["text_en"]

    labels = [lw.label for lw in walk_labels(root)]
    assert "A'" in labels  # the tail is the next pattern's first wave, primed

    report = build_report("TEST", "2026-01-01", pivots, tournament, pivot_k=1.0)
    pref = report["preferred"]
    assert pref["completed"] is True
    assert pref["reversal_tail"]["pattern"] == "zigzag"
    assert pref["reversal_tail"]["direction"] == "down"
    assert pref["reversal_tail"]["structured"] is True
    assert pref["reversal_tail"]["completed_at"]["price"] == 450.0

    svg = render_svg_labeled(pivots, root, report)
    assert svg.startswith("<svg") and "</svg>" in svg


def _build_two_degree_impulse_with_young_decline():
    """Same completed degree-2 impulse, but the counter-move is a single
    monowave -- too young for any structured tail (the MU case)."""
    segs = [
        (100, 200, "L", "5"), (200, 150, "H", "3"), (150, 380, "L", "5"),
        (380, 320, "H", "3"), (320, 450, "L", "5"),
    ]
    pts = []
    for start, end, k0, slot in segs:
        seg = _nested(start, end, k0, slot, 2)
        pts.extend(seg if not pts else seg[1:])
    pts.append((425.0, "L"))  # one monowave down from the 450 high
    return [Pivot(i, i * 2, f"d{i}", pr, kd) for i, (pr, kd) in enumerate(pts)]


def test_young_reversal_gets_bare_tail():
    pivots = _build_two_degree_impulse_with_young_decline()
    null = fit_null_model(pivots)
    ctx = {"atr_epsilon": 0.0}
    memo = build_pattern_memo(pivots, null, ctx, k=4)
    tournament = run_tournament(pivots, memo, null, ctx, k=4)

    assert not tournament.no_clean_count
    root = tournament.winner.root
    assert root.reversal, (
        f"expected a completed-root+tail reading, got {root.pattern} "
        f"({','.join(c.label + ('~' if c.open else '') for c in root.children)})")
    tail = root.children[-1]
    assert tail.pattern is None and tail.direction == "down"  # bare, unstructured

    pos = build_position(root)
    assert "complete at 450" in pos["text_en"]
    assert "too young to structure" in pos["text_en"]

    report = build_report("TEST", "2026-01-01", pivots, tournament, pivot_k=1.0)
    assert report["preferred"]["reversal_tail"]["structured"] is False
    labels = [lw.label for lw in walk_labels(root)]
    assert "?'" in labels
