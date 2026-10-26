import numpy as np
import pytest

from proflow.engine.rainfall import MassCurve
from proflow.engine.scs import excess_increments, runoff_depth

# App. 21B table 21B-2: 5-point distribution at 6-h points (minutes here).
FIVE_POINT = MassCurve.from_table(
    [0, 360, 720, 1080, 1440], [0, 0.053, 0.816, 0.947, 1]
)


def test_linear_interpolation_between_points():
    # Table 21B-3 interpolates table 21B-2 to hours: hour 7 -> 0.180.
    assert FIVE_POINT.fraction(420) == pytest.approx(0.053 + (0.816 - 0.053) / 6)
    assert round(FIVE_POINT.fraction(420), 3) == 0.180


def test_outside_storm():
    assert FIVE_POINT.fraction(-5) == 0.0
    assert FIVE_POINT.fraction(2000) == 1.0


def test_cumulative_depths_on_grid():
    depths = FIVE_POINT.cumulative_depths(38.0, 60.0)
    assert len(depths) == 25
    assert depths[-1] == pytest.approx(38.0)
    assert np.all(np.diff(depths) >= 0)


def test_off_grid_end_adds_one_step():
    storm = MassCurve.from_table([0, 50], [0, 1])
    depths = storm.cumulative_depths(2.0, 15.0)
    np.testing.assert_allclose(depths, [0, 0.6, 1.2, 1.8, 2.0])


@pytest.mark.parametrize(
    "times,fractions",
    [
        ([0, 60], [0, 0.9]),  # does not reach 1
        ([0, 60, 60], [0, 0.5, 1]),  # repeated time
        ([10, 60], [0, 1]),  # does not start at 0
        ([0, 30, 60], [0, 0.6, 0.5]),  # decreasing
    ],
)
def test_invalid_tables(times, fractions):
    with pytest.raises(ValueError):
        MassCurve.from_table(times, fractions)


def test_excess_increments_sum_to_total_runoff():
    depths = FIVE_POINT.cumulative_depths(6.0, 30.0)
    inc = excess_increments(depths, 80)
    assert inc.sum() == pytest.approx(runoff_depth(6.0, 80))
    assert np.all(inc >= 0)


def test_no_excess_before_initial_abstraction():
    # CN 80: Ia = 0.5 in. The 21B storm x 2 in has 0.36 in by hour 7 and
    # 0.61 in by hour 8, so the first excess falls in the hour 7-8 interval.
    inc = excess_increments(FIVE_POINT.cumulative_depths(2.0, 60.0), 80)
    assert np.all(inc[:7] == 0)
    assert inc[7] > 0
