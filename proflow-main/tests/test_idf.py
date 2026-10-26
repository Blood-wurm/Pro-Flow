import math

import numpy as np
import pytest

from proflow.engine.idf import FhaCurve, IdfSet, PolynomialCurve, fit_fha

DURATIONS = [5, 10, 15, 30, 60]


def test_fha_intensity():
    curve = FhaCurve(b=60.0, d=10.0, e=0.8)
    assert curve.intensity(15) == pytest.approx(60.0 / 25**0.8)


def test_fha_constant_rate():
    # Hydraflow's documented trick: d = e = 0 gives a flat line at b in/hr.
    curve = FhaCurve(b=2.5, d=0.0, e=0.0)
    np.testing.assert_allclose(curve.intensity(DURATIONS), 2.5)


def test_fha_array_in_array_out():
    out = FhaCurve(60.0, 10.0, 0.8).intensity(DURATIONS)
    assert isinstance(out, np.ndarray) and out.shape == (5,)
    assert np.all(np.diff(out) < 0)


def test_polynomial_intensity():
    curve = PolynomialCurve(a=2.0, b=-0.1, c=-0.05, d=0.001)
    x = math.log(30)
    expected = 2.0 - 0.1 * x - 0.05 * x**2 + 0.001 * x**3
    assert curve.intensity(30) == pytest.approx(expected)


def test_nonpositive_duration_rejected():
    with pytest.raises(ValueError):
        FhaCurve(60.0, 10.0, 0.8).intensity(0)


@pytest.mark.parametrize(
    "b,d,e", [(60.0, 10.0, 0.8), (95.3, 17.2, 0.91), (40.0, 0.0, 0.7)]
)
def test_fit_recovers_exact_coefficients(b, d, e):
    true = FhaCurve(b, d, e)
    fit = fit_fha(DURATIONS, true.intensity(DURATIONS))
    assert fit.b == pytest.approx(b, rel=1e-3)
    assert fit.d == pytest.approx(d, abs=0.01)
    assert fit.e == pytest.approx(e, rel=1e-3)


def test_fit_close_to_noisy_data():
    true = FhaCurve(70.0, 12.0, 0.85).intensity(DURATIONS)
    noisy = true * np.array([1.02, 0.99, 1.01, 0.98, 1.01])
    fit = fit_fha(DURATIONS, noisy)
    np.testing.assert_allclose(fit.intensity(DURATIONS), noisy, rtol=0.03)


def test_fit_needs_three_points():
    with pytest.raises(ValueError):
        fit_fha([5, 60], [6.0, 2.0])


def test_idf_set_from_table():
    durations = [5, 15, 30, 60]
    table = {
        rp: FhaCurve(b, 10.0, 0.8).intensity(durations)
        for rp, b in [(2, 50.0), (100, 90.0)]
    }
    idf = IdfSet.fit_table(durations, table, name="Sample")
    assert idf.intensity(100, 20) > idf.intensity(2, 20)
    assert idf.intensity(2, 20) == pytest.approx(50.0 / 30**0.8, rel=1e-3)
    with pytest.raises(KeyError, match="25-yr"):
        idf.intensity(25, 20)


# --- fit diagnostics ---------------------------------------------------------

from proflow.engine.idf import fit_fha_report  # noqa: E402
from proflow.engine.result import Status  # noqa: E402


def test_fit_report_on_exact_data_is_clean():
    true = FhaCurve(60.0, 10.0, 0.8)
    r = fit_fha_report(DURATIONS, true.intensity(DURATIONS))
    assert r.ok and r.warnings == ()
    assert r.diagnostics["max_relative_residual"] < 1e-4
    assert r.value.duration_range == (5.0, 60.0)


def test_fit_report_flags_concave_data():
    # Express manual p. 54: points that plot concave on log scale fit poorly.
    concave = [6.0, 5.2, 4.8, 2.2, 1.0]
    r = fit_fha_report(DURATIONS, concave)
    assert r.ok
    assert any("concave" in w for w in r.warnings)
    assert r.diagnostics["max_relative_residual"] > 0.01


def test_fit_report_flags_rising_intensity():
    r = fit_fha_report([5, 10, 15, 30], [5.0, 5.5, 4.0, 3.0])
    assert any("does not decrease from 5 to 10 min" in w for w in r.warnings)


def test_fit_report_three_points_is_exact():
    r = fit_fha_report([5, 15, 60], [6.0, 4.0, 1.7])
    assert any("exactly" in w for w in r.warnings)


def test_fit_report_rejects_bad_input():
    assert fit_fha_report([5, 15], [6, 4]).status is Status.INVALID_INPUT
    assert fit_fha_report([15, 5, 60], [4, 6, 1.7]).status is Status.INVALID_INPUT


def test_d_step_restricts_d_to_multiples():
    true = FhaCurve(60.0, 10.04, 0.8)
    r = fit_fha_report(DURATIONS, true.intensity(DURATIONS), d_step=0.1)
    d = r.value.curve.d
    assert d == pytest.approx(round(d * 10) / 10, abs=1e-9)
    assert d == pytest.approx(10.0)
