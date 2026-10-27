"""One storm sewer line: capacity, starting HGL, standard step HGL/EGL.

Expected values come from closed forms (full-pipe Manning, uniform flow) or
from an independent gradually-varied-flow integration, not from the solver.
"""

import math

import pytest

from proflow.engine.result import Status
from proflow.engine.sewer import Line, line_hydraulics

G = 32.174


def _full_sf(d, n, q):
    """Closed-form friction slope of a full circular pipe."""
    area = math.pi * d * d / 4
    return (q * n / (1.486 * area * (d / 4) ** (2 / 3))) ** 2


def _circle(d, y):
    t = 2 * math.acos(1 - 2 * y / d)
    return d * d / 8 * (t - math.sin(t)), d * t / 2, d * math.sin(t / 2)


LINE = Line(diameter=1.5, length=200.0, invert_up=101.0, invert_down=100.0, n=0.013)


def test_full_flow_capacity_is_manning_on_the_invert_slope():
    area, r = math.pi * 1.5**2 / 4, 1.5 / 4
    expected = 1.486 / 0.013 * area * r ** (2 / 3) * math.sqrt(1 / 200)
    assert LINE.full_flow() == pytest.approx(expected, rel=1e-9)
    assert expected == pytest.approx(7.428, abs=0.001)  # hand check


def test_pressure_flow_loses_full_pipe_friction_over_the_length():
    # Tailwater 2 ft over the crown: the line flows full end to end, both
    # velocity heads are equal, so HGL rises by exactly Sf_full * L.
    q = 10.0
    r = line_hydraulics(LINE, q, "elevation", 100.0 + 1.5 + 2.0)
    assert r.ok
    h = r.value
    hf = _full_sf(1.5, 0.013, q) * 200
    assert hf == pytest.approx(1.8126, abs=1e-3)  # hand check
    assert h.up.hgl - h.down.hgl == pytest.approx(hf, abs=1e-6)
    assert h.friction_loss == pytest.approx(hf, abs=1e-6)
    assert h.down.surcharged and h.up.surcharged
    v = q / (math.pi * 1.5**2 / 4)
    assert h.up.egl - h.up.hgl == pytest.approx(v * v / (2 * G))
    assert any("surcharged" in w for w in r.warnings)
    assert any("exceeds the full-flow capacity" in w for w in r.warnings)


def test_normal_depth_start_stays_at_normal_depth_upstream():
    # Uniform flow: Sf equals the invert slope at normal depth, so the
    # standard step must return the same depth at the upstream end.
    r = line_hydraulics(LINE, 4.0, "normal")
    h = r.value
    area, perim, _ = _circle(1.5, h.normal_depth)
    manning = 1.486 / 0.013 * area * (area / perim) ** (2 / 3) * math.sqrt(1 / 200)
    assert manning == pytest.approx(4.0, rel=1e-7)
    assert h.down.depth == pytest.approx(h.normal_depth)
    assert h.up.depth == pytest.approx(h.normal_depth, abs=1e-6)
    assert h.up.hgl - h.down.hgl == pytest.approx(1.0, abs=1e-6)


def test_tailwater_below_critical_is_reset_to_critical():
    r = line_hydraulics(LINE, 4.0, "elevation", 100.1)
    h = r.value
    area, _, top = _circle(1.5, h.critical_depth)
    assert 4.0**2 * top / (G * area**3) == pytest.approx(1.0, rel=1e-6)
    assert h.down.depth == pytest.approx(h.critical_depth)
    assert h.down.at_critical
    assert any("reset to critical" in w for w in r.warnings)


def test_dc_d_half_and_crown_starts():
    h = line_hydraulics(LINE, 4.0, "dc_d_half").value
    assert h.down.depth == pytest.approx((h.critical_depth + 1.5) / 2)
    h = line_hydraulics(LINE, 4.0, "crown").value
    assert h.down.hgl == pytest.approx(101.5)


def test_steep_line_goes_critical_upstream_and_says_so():
    steep = Line(1.5, 200.0, 110.0, 100.0, 0.013)  # 5 %
    r = line_hydraulics(steep, 4.0, "critical")
    h = r.value
    assert h.up.at_critical and h.up.depth == pytest.approx(h.critical_depth)
    assert h.junction_loss == 0.0  # not applied at critical depth (p. 65)
    assert any("supercritical" in w for w in r.warnings)


def _gvf_upstream_depth(line, q, y_dn, steps=4000):
    """Integrate dy/dx' = (Sf - S0) / (1 - Fr^2) upstream with RK4."""
    s0, d, n = line.slope, line.diameter, line.n

    def slope(y):
        area, perim, top = _circle(d, y)
        sf = (q * n / (1.486 * area * (area / perim) ** (2 / 3))) ** 2
        fr2 = q * q * top / (G * area**3)
        return (sf - s0) / (1 - fr2)

    h = line.length / steps
    y = y_dn
    for _ in range(steps):
        k1 = slope(y)
        k2 = slope(y + h / 2 * k1)
        k3 = slope(y + h / 2 * k2)
        k4 = slope(y + h * k3)
        y += h / 6 * (k1 + 2 * k2 + 2 * k3 + k4)
    return y


def test_backwater_matches_an_independent_profile_integration():
    # A mild line with a high tailwater (M1 backwater). One standard step
    # with an averaged friction slope (the manual's method) approximates the
    # gradually-varied profile: here it is 0.006 ft deeper than a 4000-step
    # integration over 150 ft. That is the one-step truncation error, kept
    # visible rather than tuned away.
    line = Line(1.5, 150.0, 100.75, 100.0, 0.013)
    tw = 100.0 + 1.3
    h = line_hydraulics(line, 5.0, "elevation", tw).value
    expected = _gvf_upstream_depth(line, 5.0, 1.3)
    assert h.up.depth == pytest.approx(expected, abs=0.01)
    assert h.normal_depth < h.up.depth < 1.3  # decays toward normal depth


def test_junction_loss_adds_k_velocity_heads_at_the_upstream_end():
    h = line_hydraulics(LINE, 4.0, "crown", junction_k=0.5).value
    assert h.junction_loss == pytest.approx(0.5 * h.up.velocity**2 / (2 * G))
    assert h.hgl_junction == pytest.approx(h.up.hgl + h.junction_loss)
    assert h.egl_junction == pytest.approx(h.hgl_junction + h.up.velocity_head)


def test_adverse_and_flat_lines_have_no_capacity_but_still_compute():
    adverse = Line(1.5, 200.0, 99.8, 100.0, 0.013)
    r = line_hydraulics(adverse, 3.0, "elevation", 101.0)
    assert r.ok and r.value.capacity is None
    assert any("adverse slope" in w for w in r.warnings)
    assert r.value.up.hgl > r.value.down.hgl  # friction still lost upstream
    flat = Line(1.5, 200.0, 100.0, 100.0, 0.013)
    r = line_hydraulics(flat, 3.0, "crown")
    assert r.ok and r.value.capacity is None
    assert any("flat line" in w for w in r.warnings)
    bad = line_hydraulics(adverse, 3.0, "normal")
    assert bad.status is Status.INVALID_INPUT
    assert "normal depth does not exist" in bad.message


@pytest.mark.parametrize(
    "line, q, mode, tw, message",
    [
        (Line(0, 200, 101, 100, 0.013), 4, "crown", None, "diameter"),
        (Line(1.5, 0, 101, 100, 0.013), 4, "crown", None, "length"),
        (Line(1.5, 200, 101, 100, 0), 4, "crown", None, "Manning"),
        (LINE, 0, "crown", None, "flow"),
        (LINE, 4, "elevation", None, "tailwater elevation is required"),
        (LINE, 4, "pond", None, "unknown starting HGL"),
    ],
)
def test_invalid_inputs_are_explicit(line, q, mode, tw, message):
    r = line_hydraulics(line, q, mode, tw)
    assert r.status is Status.INVALID_INPUT
    assert message in r.message
