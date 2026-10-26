import pytest

from proflow.engine.idf import FhaCurve
from proflow.engine.rational import modified_rational, peak_flow, standard_rational
from proflow.engine.result import Status

CONSTANT = FhaCurve(b=4.0, d=0.0, e=0.0)  # 4 in/hr at every duration
DECAYING = FhaCurve(b=60.0, d=10.0, e=0.8)


def _std(*args, **kwargs):
    r = standard_rational(*args, **kwargs)
    assert r.ok, r.message
    return r.value


def _mod(*args, **kwargs):
    r = modified_rational(*args, **kwargs)
    assert r.ok, r.message
    return r.value


def test_peak_flow():
    # Impervious acre at 1 in/hr -> 1 cfs.
    assert peak_flow(1.0, 1.0, 1.0) == 1.0
    assert peak_flow(0.5, 4.0, 10.0) == pytest.approx(20.0)


def test_standard_rational_triangle():
    hyd = _std(c=0.5, area=10.0, tc=10.0, idf=CONSTANT)
    assert hyd.peak == pytest.approx(20.0)
    assert hyd.time_to_peak == 10.0
    assert hyd.times[-1] == 20.0 and hyd.flows[-1] == 0.0
    # Triangle area: 1/2 * base * peak, in cubic feet.
    assert hyd.volume == pytest.approx(0.5 * 20 * 60 * 20.0)


def test_standard_rational_uses_intensity_at_tc():
    hyd = _std(c=0.9, area=2.0, tc=15.0, idf=DECAYING)
    assert hyd.peak == pytest.approx(0.9 * DECAYING.intensity(15.0) * 2.0)


def test_receding_limb_factor_stretches_recession():
    hyd = _std(0.5, 10.0, 10.0, CONSTANT, receding_limb_factor=2.0)
    assert hyd.times[-1] == 30.0
    assert hyd.time_to_peak == 10.0
    assert hyd.volume == pytest.approx(0.5 * 30 * 60 * 20.0)


def test_ascending_limb_factor_delays_peak():
    # Hydraflow Hydrographs manual p. 24: ALF = 1.5 -> rising side 1.5 Tc.
    hyd = _std(0.5, 10.0, 10.0, DECAYING, ascending_limb_factor=1.5)
    assert hyd.time_to_peak == 15.0
    assert hyd.times[-1] == 25.0
    # Intensity is still taken at Tc, not at the delayed peak.
    assert hyd.peak == pytest.approx(0.5 * DECAYING.intensity(10.0) * 10.0)
    assert hyd.volume == pytest.approx(0.5 * 25 * 60 * hyd.peak)


def test_both_limb_factors():
    hyd = _std(0.5, 10.0, 10.0, CONSTANT, 2.0, ascending_limb_factor=0.5)
    assert hyd.time_to_peak == 5.0
    assert hyd.times[-1] == 25.0


def test_modified_rational_manual_example():
    # Hydraflow manual: Tc = 20 min, factor 2.25 -> 65 min hydrograph base.
    hyd = _mod(0.5, 10.0, 20.0, DECAYING, storm_duration_factor=2.25)
    assert hyd.times[-1] == 65.0
    qp = 0.5 * DECAYING.intensity(45.0) * 10.0
    assert hyd.peak == pytest.approx(qp)
    # Trapezoid with rise and fall of Tc: volume = peak * storm duration.
    assert hyd.volume == pytest.approx(qp * 45.0 * 60)


def test_longer_storm_lower_peak_more_volume():
    short = _mod(0.5, 10.0, 20.0, DECAYING, storm_duration_factor=1.0)
    long = _mod(0.5, 10.0, 20.0, DECAYING, storm_duration_factor=3.0)
    assert long.peak < short.peak
    assert long.volume > short.volume


def test_factor_one_matches_standard():
    std = _std(0.5, 10.0, 20.0, DECAYING)
    mod = _mod(0.5, 10.0, 20.0, DECAYING, storm_duration_factor=1.0)
    assert mod.peak == pytest.approx(std.peak)
    assert mod.volume == pytest.approx(std.volume)


def test_on_grid_shape_has_no_sampling_warning():
    r = standard_rational(0.5, 10.0, 10.0, CONSTANT)
    assert r.warnings == ()
    assert r.diagnostics["shape_peak_cfs"] == pytest.approx(r.value.peak)


def test_off_grid_end_gets_one_zero_ordinate():
    # Modified Rational base 32.5 min at 1-min steps: last ordinate at 33 min.
    r = modified_rational(0.5, 10.0, 10.0, CONSTANT, storm_duration_factor=2.25)
    assert r.value.times[-1] == 33.0 and r.value.flows[-1] == 0.0
    assert r.value.flows[-2] > 0


def test_off_grid_peak_is_reported_not_hidden():
    # Tc = 7.5 min at 2-min steps: the true peak (20 cfs) at 7.5 min is missed.
    r = standard_rational(0.5, 10.0, 7.5, CONSTANT, dt=2.0)
    hyd = r.value
    assert hyd.peak < 20.0
    assert r.diagnostics["shape_peak_cfs"] == pytest.approx(20.0)
    assert r.diagnostics["shape_volume_ft3"] == pytest.approx(0.5 * 15 * 60 * 20.0)
    assert any("sampled peak" in w for w in r.warnings)
    # Volume is the exact trapezoid through the ordinates.
    assert hyd.volume == pytest.approx(
        sum((a + b) / 2 * 120 for a, b in zip(hyd.flows, hyd.flows[1:], strict=False))
    )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"c": 0.0},
        {"c": 1.2},
        {"area": 0.0},
        {"tc": -1.0},
        {"ascending_limb_factor": 0.0},
        {"dt": 0.0},
    ],
)
def test_invalid_inputs_rejected(kwargs):
    args = {"c": 0.5, "area": 10.0, "tc": 10.0, "idf": CONSTANT} | kwargs
    r = standard_rational(**args)
    assert r.status is Status.INVALID_INPUT and r.value is None and r.message


def test_storm_duration_factor_below_one_rejected():
    r = modified_rational(0.5, 10.0, 10.0, CONSTANT, storm_duration_factor=0.5)
    assert r.status is Status.INVALID_INPUT
