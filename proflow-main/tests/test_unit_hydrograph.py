import json
from pathlib import Path

import numpy as np
import pytest

from proflow.engine import unit_hydrograph as uh
from proflow.engine.rainfall import MassCurve
from proflow.engine.result import Status

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "nrcs"


def _fixture(name):
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def test_duh_table_matches_its_mass_curve():
    # Table 16-1 also tabulates the mass curve; 0.375 of the volume is
    # under the rising limb (Hydraflow manual: "3/8 of its area").
    volume = np.trapezoid(uh.DUH_Q, uh.DUH_T)
    rising = np.trapezoid(uh.DUH_Q[:11], uh.DUH_T[:11])
    assert rising / volume == pytest.approx(0.375, abs=0.005)


def test_unit_hydrograph_holds_one_inch():
    area, tp, dt = 640.0, 60.0, 6.0  # 1 mi^2, Tp = 1 h, dt = 0.1 Tp
    one_inch = area * uh.CUFT_PER_INCH_ACRE
    for ordinates in (uh.curvilinear(area, tp, dt), uh.triangular(area, tp, dt)):
        assert np.trapezoid(ordinates, dx=dt * 60) == pytest.approx(one_inch, rel=0.01)


def test_triangular_base_is_2_67_tp_for_484():
    ordinates = uh.triangular(640.0, 60.0, 1.0)
    assert len(ordinates) - 1 == pytest.approx(2.67 * 60, abs=1)
    assert ordinates.max() == pytest.approx(484.0)


def test_triangular_other_shape_factor_keeps_volume():
    area, tp, dt = 640.0, 60.0, 1.0
    one_inch = area * uh.CUFT_PER_INCH_ACRE
    flat = uh.triangular(area, tp, dt, shape_factor=300)
    assert flat.max() == pytest.approx(300.0)
    assert np.trapezoid(flat, dx=dt * 60) == pytest.approx(one_inch, rel=0.01)


def test_convolution_alignment():
    # One inch in the first interval reproduces the unit hydrograph itself;
    # one inch in the second interval shifts it by one step.
    u = np.array([0.0, 10.0, 5.0, 0.0])
    np.testing.assert_allclose(uh.convolve([1.0], u), u)
    np.testing.assert_allclose(uh.convolve([0.0, 1.0], u), [0, 0, 10, 5, 0])
    # Linearity: depths add.
    np.testing.assert_allclose(
        uh.convolve([2.0, 1.0], u),
        2 * uh.convolve([1.0], np.append(u, 0)) + [0, 0, 10, 5, 0],
    )


def _appendix_21b_storm():
    data = _fixture("nrcs-21b-incremental-runoff")["inputs"]
    return MassCurve.from_table(
        np.array(data["times"]["values"]) * 60, data["fractions"]["values"]
    )


def test_appendix_21b_end_to_end():
    """Storm -> excess -> table 16-1 UH -> convolution, against table 21B-7.

    The source's own convolution used 22 cfs at hour 20 of the unit
    hydrograph where table 21B-6 has 16; that value first affects hour 21, so
    the comparison runs through hour 20. Hour 6 is the printed 3335 typo.

    The appendix rounds as it goes (excess to 0.001 in, unit hydrograph to
    1 cfs); Pro-Flow does not. The allowed difference at each hour is what
    that rounding can move the sum: 0.5 cfs per inch of excess so far, plus
    0.0005 in times each contributing unit ordinate, plus 0.5 for the output.
    """
    r = uh.scs_runoff_hydrograph(
        area=15 * 640,
        cn=80,
        tc=7.1 * 60,
        storm=_appendix_21b_storm(),
        total_depth=38.0,
        dt=60.0,
        tp=300.0,
    )
    assert r.ok, r.message
    published = [
        int(v) for v in _fixture("nrcs-21b-convolution")["expected"]["flows"]["values"]
    ]
    computed = r.value.hydrograph.flows
    excess, unit = r.value.excess, r.value.unit_hydrograph
    for hour in range(21):
        if hour == 6:
            continue
        bound = 0.5 * excess[:hour].sum() + 0.0005 * unit[: hour + 1].sum() + 0.5
        assert abs(computed[hour] - published[hour]) <= bound, (hour, bound)
    assert r.value.hydrograph.time_to_peak == 14 * 60
    # App. 21B step 7: runoff equation and mass curve both give 35.16 in.
    assert r.diagnostics["runoff_depth_equation_in"] == pytest.approx(35.16, abs=0.005)


def test_mass_balance_diagnostics():
    r = uh.scs_runoff_hydrograph(
        area=100.0, cn=75, tc=30.0, storm=_appendix_21b_storm(), total_depth=5.0, dt=5.0
    )
    d = r.diagnostics
    assert d["runoff_depth_hydrograph_in"] == pytest.approx(
        d["runoff_depth_equation_in"] * d["unit_hydrograph_depth_in"], rel=1e-9
    )
    assert d["unit_hydrograph_depth_in"] == pytest.approx(1.0, abs=0.01)
    assert not r.warnings


def test_coarse_step_warns():
    r = uh.scs_runoff_hydrograph(
        area=100.0,
        cn=75,
        tc=30.0,
        storm=_appendix_21b_storm(),
        total_depth=5.0,
        dt=15.0,
    )
    assert r.ok and any("0.25 Tp" in w for w in r.warnings)


def test_zero_rain_gives_zero_flow():
    r = uh.scs_runoff_hydrograph(
        area=100.0, cn=75, tc=30.0, storm=_appendix_21b_storm(), total_depth=0.0, dt=5.0
    )
    assert r.ok and r.value.hydrograph.peak == 0.0


@pytest.mark.parametrize(
    "kwargs,status",
    [
        ({"area": 0.0}, Status.INVALID_INPUT),
        ({"form": "kinematic"}, Status.INVALID_INPUT),
        ({"tp_equation": "16A-99"}, Status.INVALID_INPUT),
        ({"shape_factor": 300.0}, Status.UNSUPPORTED_REGIME),
        ({"total_depth": -1.0}, Status.INVALID_INPUT),
    ],
)
def test_rejected_inputs(kwargs, status):
    args = {
        "area": 100.0,
        "cn": 75,
        "tc": 30.0,
        "storm": _appendix_21b_storm(),
        "total_depth": 5.0,
        "dt": 5.0,
    } | kwargs
    assert uh.scs_runoff_hydrograph(**args).status is status


@pytest.mark.parametrize("dt", [1.0, 2.0, 5.0, 9.0])
def test_unit_hydrograph_volume_warning_matches_diagnostic(dt):
    r = uh.scs_runoff_hydrograph(
        area=50.0,
        cn=75,
        tc=20.0,
        storm=_appendix_21b_storm(),
        total_depth=3.0,
        dt=dt,
        form="triangular",
    )
    d = r.diagnostics
    off = abs(d["unit_hydrograph_depth_in"] - 1) > uh.UH_VOLUME_TOLERANCE
    assert off == any("unit hydrograph holds" in w for w in r.warnings)
    assert d["mass_balance_residual_in"] == pytest.approx(
        d["runoff_depth_hydrograph_in"] - d["runoff_depth_equation_in"]
    )


def test_curvilinear_and_triangular_stay_distinct():
    args = {
        "area": 50.0,
        "cn": 75,
        "tc": 20.0,
        "storm": _appendix_21b_storm(),
        "total_depth": 3.0,
        "dt": 2.0,
    }
    nrcs = uh.scs_runoff_hydrograph(**args, form="curvilinear")
    tri = uh.scs_runoff_hydrograph(**args, form="triangular")
    assert nrcs.method == "scs.uh.curvilinear/1"
    assert tri.method == "scs.uh.triangular/1"
    u_nrcs, u_tri = nrcs.value.unit_hydrograph, tri.value.unit_hydrograph
    # Curvilinear runs to 5 Tp, the triangle only to 2.67 Tp.
    assert len(u_tri) < len(u_nrcs)
    assert not np.allclose(u_nrcs[: len(u_tri)], u_tri)
