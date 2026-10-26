import numpy as np
import pytest

from proflow.engine.hydrograph import Hydrograph, combine, resample
from proflow.engine.idf import FhaCurve
from proflow.engine.rational import standard_rational
from proflow.engine.result import Status


def _hyd(dt, *flows):
    return Hydrograph(dt, np.array(flows, dtype=float))


def test_resample_same_step_is_identity():
    h = _hyd(1.0, 0, 4, 10, 6, 2, 0)
    r = resample(h, 1.0)
    np.testing.assert_array_equal(r.value.flows, h.flows)
    assert r.warnings == () and r.diagnostics["volume_residual_ft3"] == 0


def test_refining_keeps_shape_volume_and_peak():
    # New ordinates lie on the straight lines, so the trapezoid area is exact.
    h = _hyd(2.0, 0, 4, 10, 6, 0)
    r = resample(h, 0.5)
    out = r.value
    np.testing.assert_allclose(out.flows[::4], h.flows)
    assert out.flows[1] == pytest.approx(1.0)  # quarter of the way to 4 cfs
    assert out.volume == pytest.approx(h.volume)
    assert out.peak == h.peak and r.warnings == ()


def test_coarsening_that_misses_the_peak_is_reported():
    h = _hyd(1.0, 0, 10, 5, 0)  # peak at 1 min, end at 3 min
    r = resample(h, 2.0)
    out = r.value
    np.testing.assert_allclose(out.flows, [0, 5, 0])  # t = 0, 2, 4 min
    assert r.diagnostics["volume_in_ft3"] == pytest.approx(15 * 60)
    assert r.diagnostics["volume_out_ft3"] == pytest.approx(10 * 60)
    assert any("changes volume" in w for w in r.warnings)
    assert any("lowers the peak" in w for w in r.warnings)


def test_resample_truncated_input_warns():
    r = resample(_hyd(1.0, 0, 5, 8), 0.5)
    assert any("not zero" in w for w in r.warnings)
    assert r.value.flows[-1] == 8.0  # last old ordinate is on the new grid


@pytest.mark.parametrize("dt", [0.0, -1.0])
def test_resample_rejects_bad_step(dt):
    assert resample(_hyd(1.0, 0, 1, 0), dt).status is Status.INVALID_INPUT


def test_combine_sums_ordinates_and_volumes():
    a = _hyd(1.0, 0, 4, 2, 0)
    b = _hyd(1.0, 0, 1, 3, 5, 1, 0)
    r = combine([a, b])
    np.testing.assert_allclose(r.value.flows, [0, 5, 5, 5, 1, 0])
    assert r.value.volume == pytest.approx(a.volume + b.volume)
    assert r.diagnostics["volume_residual_ft3"] == pytest.approx(0)
    assert r.warnings == ()


def test_combine_rational_hydrographs_conserves_volume():
    idf = FhaCurve(60.0, 10.0, 0.8)
    hyds = [
        standard_rational(0.5, 10.0, 10.0, idf).value,
        standard_rational(0.9, 2.0, 5.0, idf).value,
        standard_rational(0.3, 25.0, 30.0, idf, receding_limb_factor=2.0).value,
    ]
    r = combine(hyds)
    assert r.value.volume == pytest.approx(sum(h.volume for h in hyds))
    assert r.value.peak <= sum(h.peak for h in hyds)


def test_combine_requires_equal_steps_unless_dt_given():
    a, b = _hyd(1.0, 0, 6, 0), _hyd(2.0, 0, 4, 0)
    r = combine([a, b])
    assert r.status is Status.INVALID_INPUT and "time steps differ" in r.message
    r = combine([a, b], dt=1.0)
    assert r.ok and r.value.dt == 1.0
    np.testing.assert_allclose(r.value.flows, [0, 8, 4, 2, 0])
    assert r.value.volume == pytest.approx(a.volume + b.volume)


def test_combine_passes_on_resampling_warnings():
    peaky = _hyd(1.0, 0, 10, 5, 0)
    r = combine([peaky, _hyd(2.0, 0, 1, 0)], dt=2.0)
    assert r.ok and any(w.startswith("input 0:") for w in r.warnings)


def test_padding_a_truncated_input_is_reported():
    short = _hyd(1.0, 0, 4, 6)  # ends at 6 cfs
    long = _hyd(1.0, 0, 1, 1, 1, 0)
    r = combine([short, long])
    # Padding adds the triangle from 6 cfs to 0 over one step.
    assert r.diagnostics["volume_residual_ft3"] == pytest.approx(6 / 2 * 60)
    assert any("padded" in w for w in r.warnings)


def test_combine_nothing():
    assert combine([]).status is Status.INVALID_INPUT
