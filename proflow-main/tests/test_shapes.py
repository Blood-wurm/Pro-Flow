"""Channel sections and weir shapes beyond the rectangle and trapezoid."""

import math

import pytest

from proflow.engine import channel, weir
from proflow.engine.result import Status
from proflow.engine.sections import Circular, Gutter, StationElevation, Trapezoid

# --- circular pipe -----------------------------------------------------------


def test_pipe_geometry_half_and_full():
    pipe = Circular(2.0)
    assert pipe.area(1.0) == pytest.approx(math.pi * 4 / 8)
    assert pipe.wetted_perimeter(1.0) == pytest.approx(math.pi)
    assert pipe.top_width(1.0) == pytest.approx(2.0)
    assert pipe.area(2.0) == pytest.approx(math.pi)
    assert pipe.top_width(2.0) == pytest.approx(0.0, abs=1e-9)


def test_pipe_full_flow_closed_form():
    d, s, n = 1.5, 0.01, 0.013
    full = 1.486 / n * (math.pi * d * d / 4) * (d / 4) ** (2 / 3) * math.sqrt(s)
    assert Circular(d).flow(d, s, n) == pytest.approx(full)


def test_pipe_peak_flow_near_0_94_diameter():
    # A classic result: a pipe carries about 7.6 % more than full at ~0.938 D.
    pipe, s, n = Circular(1.0), 0.01, 0.013
    peak = channel._peak_depth(pipe, 1.0, s, n)
    assert peak == pytest.approx(0.938, abs=0.002)
    assert pipe.flow(peak, s, n) / pipe.flow(1.0, s, n) == pytest.approx(
        1.076, abs=0.002
    )


def test_pipe_two_depth_warning_and_capacity():
    pipe, s, n = Circular(1.0), 0.01, 0.013
    full = pipe.flow(1.0, s, n)
    r = channel.normal_depth(pipe, full * 1.03, s, n)
    assert r.ok and r.value.depth < 0.94
    assert any("second, higher normal depth" in w for w in r.warnings)
    over = channel.normal_depth(pipe, full * 1.2, s, n)
    assert over.status is Status.UNSUPPORTED_REGIME
    assert over.diagnostics["capacity_cfs"] == pytest.approx(full * 1.076, rel=0.003)


def test_pipe_depth_limited_by_diameter():
    r = channel.flow_at_depth(Circular(1.0), 1.2, 0.01, 0.013)
    assert r.status is Status.UNSUPPORTED_REGIME
    assert channel.critical_depth(Circular(1.0), 50.0) < 1.0


# --- gutter ------------------------------------------------------------------


def test_uniform_gutter_matches_hec22_eq_4_2():
    # Sw = Sx: Q = 0.56/n Sx^(5/3) S^(1/2) T^(8/3).
    g, s, n = Gutter(0.02, 0.02, 2.0), 0.01, 0.016
    y = 0.12
    t = y / 0.02
    expected = 0.56 / n * 0.02 ** (5 / 3) * math.sqrt(s) * t ** (8 / 3)
    assert g.spread(y) == pytest.approx(t)
    assert g.flow(y, s, n) == pytest.approx(expected)


def test_composite_gutter_matches_hec22_eo_form():
    # HEC-22 eq. 4-4: Q = Qs / (1 - Eo), coded independently here.
    sx, sw, w, s, n = 0.02, 0.08, 2.0, 0.077, 0.013
    g = Gutter(sx, sw, w)
    t = 4.2
    y = g.depth_for_spread(t)
    k = 0.56 / n * math.sqrt(s)
    qs = k * sx ** (5 / 3) * (t - w) ** (8 / 3)
    ratio = sw / sx
    eo = 1 / (1 + ratio / ((1 + ratio / (t / w - 1)) ** (8 / 3) - 1))
    assert g.flow(y, s, n) == pytest.approx(qs / (1 - eo), rel=1e-9)


def test_gutter_geometry_beyond_the_gutter():
    g = Gutter(0.02, 0.08, 2.0)
    y = 0.204  # gutter edge at 0.16 ft, so 2.2 ft of road is wet
    assert g.spread(y) == pytest.approx(4.2)
    assert g.area(y) == pytest.approx(2 * (0.204 + 0.044) / 2 + 0.044**2 / 0.04)
    assert g.wetted_perimeter(y) == pytest.approx(
        0.204 + math.hypot(2, 0.16) + 2.2 * math.hypot(1, 0.02)
    )


def test_gutter_known_q_reports_exact_depth_even_when_stepped():
    g = Gutter(0.02, 0.08, 2.0)
    exact = channel.normal_depth(g, 2.25, 0.077, 0.013)
    stepped = channel.normal_depth(g, 2.25, 0.077, 0.013, depth_step=0.01)
    assert stepped.value.depth == exact.value.depth
    assert stepped.value.critical_depth == pytest.approx(0.33)  # rounded up
    assert stepped.method == "channel.hec22_gutter.known_q.stepped/1"


@pytest.mark.parametrize(
    "args", [(0.0, 0.08, 2.0), (0.02, 0.01, 2.0), (0.02, 0.08, -1.0)]
)
def test_gutter_invalid(args):
    assert Gutter(*args).problem()


# --- user-defined station / elevation ----------------------------------------


def test_points_reproduce_a_trapezoid():
    trap = Trapezoid(5.0, 2.0, 3.0)
    pts = StationElevation((0.0, 6.0, 11.0, 20.0), (3.0, 0.0, 0.0, 3.0), (0.03,) * 3)
    for y in (0.4, 1.3, 2.9):
        assert pts.area(y) == pytest.approx(trap.area(y))
        assert pts.wetted_perimeter(y) == pytest.approx(trap.wetted_perimeter(y))
        assert pts.top_width(y) == pytest.approx(trap.top_width(y))
        assert pts.flow(y, 0.004, 0.0) == pytest.approx(trap.flow(y, 0.004, 0.03))


def test_composite_n_hec_ras_eq_2_6():
    # A V of two 1:1 sides with n 0.02 and 0.04: equal wetted lengths.
    pts = StationElevation((0.0, 2.0, 4.0), (2.0, 0.0, 2.0), (0.02, 0.04))
    expected = ((0.02**1.5 + 0.04**1.5) / 2) ** (2 / 3)
    assert pts.composite_n(1.0) == pytest.approx(expected)


def test_points_depth_limit_and_island():
    pts = StationElevation((0, 2, 3, 4, 6), (3.0, 0.0, 0.5, 0.0, 2.0), (0.03,) * 4)
    assert pts.max_depth == pytest.approx(2.0)  # the lower bank
    # At 0.4 ft the 0.5 ft hump splits the water in two. Wet widths by hand:
    # 0.4/1.5 on the left bank, 0.8 up and 0.8 down the hump, 0.4 on the right.
    assert pts.top_width(0.4) == pytest.approx(0.4 / 1.5 + 0.8 + 0.8 + 0.4)
    assert pts.area(0.6) > pts.area(0.4)
    assert (
        channel.flow_at_depth(pts, 2.5, 0.01, 0.03).status is Status.UNSUPPORTED_REGIME
    )


def test_from_points_uses_express_row_layout():
    pts = StationElevation.from_points([(0, 3, 0), (5, 0, 0.035), (10, 3, 0.04)])
    assert pts.n_values == (0.035, 0.04)
    assert pts.problem() == ""


@pytest.mark.parametrize(
    "points",
    [
        [(0, 3, 0), (5, 0, 0.03)],  # too few
        [(0, 3, 0), (5, 0, 0.03), (4, 3, 0.03)],  # stations not increasing
        [(0, 3, 0), (5, 0, 0.0), (10, 3, 0.03)],  # zero n
        [(0, 0, 0), (5, 1, 0.03), (10, 3, 0.03)],  # left end is the low point
    ],
)
def test_points_invalid(points):
    assert StationElevation.from_points(points).problem()


# --- weirs ------------------------------------------------------------------


def test_v_notch_coefficient_and_flow():
    v = weir.VNotch(90.0)
    assert v.cw == pytest.approx(2.54)
    assert v.flow(0.5) == pytest.approx(2.54 * 0.5**2.5)
    assert v.area(0.5) == pytest.approx(0.25) and v.top_width(0.5) == pytest.approx(1.0)
    assert weir.VNotch(130.0).problem()


def test_cipoletti_with_vertical_sides_is_a_3_1_rectangle():
    c = weir.Cipoletti(2.0, side_slope=1e-12)
    assert c.flow(0.7) == pytest.approx(3.1 * 2.0 * 0.7**1.5)
    full = weir.Cipoletti(2.0, 4.0)
    assert full.flow(0.5) == pytest.approx(3.1 * (2.0 + 0.8 * 0.5 * 4) * 0.5**1.5)
    assert full.top_width(0.5) == pytest.approx(6.0)
    assert weir.Cipoletti(2.0, 5.0).problem()


def test_circular_weir_half_full():
    c = weir.CircularWeir(2.0)
    assert c.flow(1.0) == pytest.approx(3.33 * math.pi / 2 * 1.0)


def test_compound_weir_is_continuous_and_sums_parts():
    c = weir.Compound(length=4.0, notch_length=1.0, notch_depth=0.5)
    assert c.flow(0.4) == pytest.approx(3.33 * 1.0 * 0.4**1.5)  # notch only
    assert c.flow(0.5 + 1e-9) == pytest.approx(c.flow(0.5), rel=1e-6)
    assert c.flow(1.0) == pytest.approx(3.33 * (1.0 * 1.0 + 3.0 * 0.5**1.5))
    assert c.area(1.0) == pytest.approx(1.0 * 0.5 + 4.0 * 0.5)
    assert weir.Compound(2.0, 2.5, 0.5).problem()


def test_sutro_is_linear_and_area_matches_integration():
    s = weir.Sutro(bottom_length=1.0, base_depth=0.2)
    q1, q2, q3 = (s.flow(h) for h in (0.4, 0.8, 1.2))
    assert q2 - q1 == pytest.approx(q3 - q2)  # proportional: straight line
    n, h = 20000, 1.2
    dy = (h - 0.2) / n
    numeric = 0.2 * 1.0 + sum(s._x((k + 0.5) * dy) * dy for k in range(n))
    assert s.area(h) == pytest.approx(numeric, rel=1e-5)


def test_sutro_below_base_is_unsupported():
    s = weir.Sutro(1.0, 0.3)
    assert weir.flow_at_head(s, 0.2, 2.0).status is Status.UNSUPPORTED_REGIME
    low_q = s.flow(0.3) * 0.5
    assert weir.head_for_flow(s, low_q, 2.0).status is Status.UNSUPPORTED_REGIME
    r = weir.weir_rating(s, 1.0, 10)
    assert r.ok and len(r.value) == 8 and "left out" in r.warnings[0]


@pytest.mark.parametrize(
    "shape",
    [
        weir.Rectangular(1.5),
        weir.Compound(4.0, 1.0, 0.5),
        weir.CircularWeir(1.5),
        weir.VNotch(60.0),
        weir.Cipoletti(2.0, 4.0),
        weir.Sutro(1.0, 0.2),
    ],
)
def test_known_q_inverts_known_head(shape):
    head = 0.9
    q = weir.flow_at_head(shape, head, 1.5).value.flow
    back = weir.head_for_flow(shape, q, 1.5)
    assert back.ok and back.value.depth == pytest.approx(head, abs=1e-8)
    assert back.method == f"weir.{shape.kind}/1"
    assert back.value.velocity == pytest.approx(q / shape.area(head))
