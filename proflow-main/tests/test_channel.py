import math

import pytest

from proflow import fixtures
from proflow.engine import channel
from proflow.engine.channel import (
    G,
    Trapezoid,
    critical_depth,
    flow_at_depth,
    manning_flow,
    normal_depth,
    rating,
)
from proflow.engine.result import Status

TRAP = Trapezoid(5.0, 2.0, 3.0)


def test_geometry():
    assert TRAP.area(2.0) == pytest.approx(5 * 2 + 2.5 * 4)
    assert TRAP.wetted_perimeter(2.0) == pytest.approx(
        5 + 2 * math.sqrt(5) + 2 * math.sqrt(10)
    )
    assert TRAP.top_width(2.0) == pytest.approx(15.0)
    assert Trapezoid.rectangular(4).area(1.5) == pytest.approx(6.0)
    assert Trapezoid.triangular(3, 3).area(2) == pytest.approx(12.0)


def test_rectangular_critical_depth_closed_form():
    # yc = (q^2 / g)^(1/3) with q = Q / b (any open-channel text).
    b, q_total = 4.0, 60.0
    expected = ((q_total / b) ** 2 / G) ** (1 / 3)
    assert critical_depth(Trapezoid.rectangular(b), q_total) == pytest.approx(expected)


def test_symmetric_triangle_critical_depth_closed_form():
    # yc = (2 Q^2 / (g z^2))^(1/5).
    z, q_total = 3.0, 40.0
    expected = (2 * q_total**2 / (G * z**2)) ** 0.2
    assert critical_depth(Trapezoid.triangular(z, z), q_total) == pytest.approx(
        expected
    )


def test_froude_is_one_at_critical_depth():
    yc = critical_depth(TRAP, 120.0)
    a, t = TRAP.area(yc), TRAP.top_width(yc)
    assert (120.0 / a) / math.sqrt(G * a / t) == pytest.approx(1.0)


def test_normal_depth_inverts_flow_at_depth():
    r = normal_depth(TRAP, 80.0, 0.004, 0.035, 5.0)
    assert r.ok and r.method == "channel.manning.known_q/1"
    back = flow_at_depth(TRAP, r.value.depth, 0.004, 0.035, 5.0)
    assert back.value.flow == pytest.approx(80.0)
    assert r.diagnostics["exact_depth_ft"] == pytest.approx(r.value.depth)


def test_velocity_and_energy():
    s = flow_at_depth(TRAP, 1.5, 0.004, 0.035, 5.0).value
    assert s.velocity == pytest.approx(s.flow / s.area)
    assert s.egl == pytest.approx(1.5 + s.velocity**2 / (2 * G))


def test_regime_follows_slope():
    mild = normal_depth(TRAP, 80.0, 0.0005, 0.035, 10.0).value
    steep = normal_depth(TRAP, 80.0, 0.05, 0.013, 10.0).value
    assert mild.regime == "subcritical" and mild.depth > mild.critical_depth
    assert steep.regime == "supercritical" and steep.depth < steep.critical_depth


def test_rating_rows_and_monotonic():
    r = rating(TRAP, 5.0, 10, 0.004, 0.035)
    depths = [s.depth for s in r.value]
    assert depths[0] == pytest.approx(0.5) and depths[-1] == pytest.approx(5.0)
    flows = [s.flow for s in r.value]
    assert flows == sorted(flows)


def test_stepped_mode_rounds_iterated_depths_up():
    exact = normal_depth(TRAP, 80.0, 0.004, 0.035, 5.0)
    stepped = normal_depth(TRAP, 80.0, 0.004, 0.035, 5.0, depth_step=0.01)
    assert stepped.method == "channel.manning.known_q.stepped/1"
    assert stepped.value.depth == pytest.approx(
        math.ceil(exact.value.depth * 100) / 100
    )
    assert stepped.value.depth >= exact.value.depth
    assert stepped.value.flow == 80.0  # reported at the known flow
    yc = stepped.value.critical_depth
    assert yc == pytest.approx(math.ceil(exact.value.critical_depth * 100) / 100)


@pytest.mark.parametrize("slope", [0.0, -0.01])
def test_no_uniform_flow_on_flat_or_adverse_slope(slope):
    for r in (
        normal_depth(TRAP, 10.0, slope, 0.03, 5.0),
        flow_at_depth(TRAP, 1.0, slope, 0.03, 5.0),
        rating(TRAP, 5.0, 10, slope, 0.03),
    ):
        assert r.status is Status.UNSUPPORTED_REGIME and "slope" in r.message


def test_flow_over_capacity_is_unsupported_with_capacity():
    cap = manning_flow(TRAP, 2.0, 0.004, 0.035)
    r = normal_depth(TRAP, cap * 1.01, 0.004, 0.035, 2.0)
    assert r.status is Status.UNSUPPORTED_REGIME
    assert r.diagnostics["capacity_cfs"] == pytest.approx(cap)


def test_depth_over_total_is_unsupported():
    assert flow_at_depth(TRAP, 3.0, 0.004, 0.035, 2.0).status is (
        Status.UNSUPPORTED_REGIME
    )


@pytest.mark.parametrize(
    "call",
    [
        lambda: normal_depth(Trapezoid(0, 0, 0), 10, 0.01, 0.03, 2),
        lambda: normal_depth(TRAP, 10, 0.01, 0.0, 2),
        lambda: normal_depth(TRAP, -1, 0.01, 0.03, 2),
        lambda: normal_depth(TRAP, 10, 0.01, 0.03, 2, depth_step=0),
        lambda: rating(TRAP, 2, 51, 0.01, 0.03),
        lambda: rating(TRAP, 2, 0, 0.01, 0.03),
    ],
)
def test_invalid_inputs(call):
    assert call().status is Status.INVALID_INPUT


def test_published_cases_reject_the_manuals_1_49(monkeypatch):
    """The Express fixtures must be able to tell 1.486 from 1.49."""
    cases = fixtures.discover(fixtures.FIXTURE_DIR / "express")
    assert len(cases) == 10
    assert all(fixtures.run_fixture(f).status == "pass" for f in cases)
    monkeypatch.setattr(channel, "K_MANNING", 1.49)
    failing = [f.id for f in cases if fixtures.run_fixture(f).status == "fail"]
    assert len(failing) >= 4, failing


# --- CLI ---------------------------------------------------------------------

from proflow.cli import EXIT_FAILED, EXIT_INVALID, EXIT_OK, main  # noqa: E402

B_B = ["channel", "trapezoidal", "--bottom-width", "5", "--side-slopes", "9",
       "--total-depth", "2.5", "--slope", "1.5", "--n", "0.05"]  # fmt: skip


def test_cli_reproduces_published_b_b_with_express_steps(capsys):
    assert main([*B_B, "--known-q", "21.33", "--express-steps"]) == EXIT_OK
    out = capsys.readouterr().out
    assert "known_q.stepped/1" in out and "0.790" in out and "9.567" in out


def test_cli_exact_by_default(capsys):
    assert main([*B_B, "--known-q", "21.33"]) == EXIT_OK
    out = capsys.readouterr().out
    assert "known_q/1" in out and "0.782" in out


def test_cli_rating_and_failures(capsys):
    assert main([*B_B, "--rating", "10"]) == EXIT_OK
    assert len(capsys.readouterr().out.splitlines()) == 12
    assert main([*B_B, "--known-q", "5000"]) == EXIT_FAILED
    assert "capacity" in capsys.readouterr().out
    bad = ["channel", "rectangular", "--side-slopes", "2", "--bottom-width",
           "3", "--total-depth", "2", "--slope", "1", "--n", "0.03",
           "--known-depth", "1"]  # fmt: skip
    assert main(bad) == EXIT_INVALID
