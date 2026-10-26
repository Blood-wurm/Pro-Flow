import numpy as np
import pytest

from proflow.engine.scs import composite, potential_retention, runoff_depth


def test_potential_retention():
    assert potential_retention(100) == 0.0
    assert potential_retention(80) == pytest.approx(2.5)


# Values from TR-55 (1986) Table 2-1.
@pytest.mark.parametrize(
    "precip,cn,expected",
    [(5.0, 80, 2.89), (3.0, 70, 0.72), (6.0, 90, 4.85), (2.0, 60, 0.06)],
)
def test_runoff_matches_tr55_table(precip, cn, expected):
    assert runoff_depth(precip, cn) == pytest.approx(expected, abs=0.01)


def test_no_runoff_below_initial_abstraction():
    # CN 80: Ia = 0.2 * 2.5 = 0.5 in.
    assert runoff_depth(0.5, 80) == 0.0
    assert runoff_depth(0.0, 80) == 0.0


def test_cn_100_runs_off_everything():
    assert runoff_depth(3.2, 100) == pytest.approx(3.2)


def test_cumulative_array():
    q = runoff_depth([0.0, 0.5, 1.0, 2.0, 5.0], 80)
    assert isinstance(q, np.ndarray)
    assert q[0] == q[1] == 0.0
    assert np.all(np.diff(q[1:]) > 0)
    assert q[-1] == pytest.approx(2.893, abs=1e-3)


def test_ia_ratio():
    # The 0.05 ratio (Hawkins et al.) starts runoff sooner than the default 0.2.
    assert runoff_depth(1.0, 70, ia_ratio=0.05) > runoff_depth(1.0, 70)


def test_composite():
    assert composite([98, 61], [2.0, 6.0]) == pytest.approx(70.25)
    assert composite([0.9, 0.3], [1.0, 1.0]) == pytest.approx(0.6)


@pytest.mark.parametrize(
    "values,areas", [([98], [0.0]), ([98, 61], [1.0]), ([], []), ([98], [-1.0])]
)
def test_composite_rejects_bad_areas(values, areas):
    with pytest.raises(ValueError):
        composite(values, areas)
