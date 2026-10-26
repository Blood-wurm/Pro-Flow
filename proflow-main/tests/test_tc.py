import pytest

from proflow.engine.tc import (
    ChannelFlow,
    ShallowFlow,
    SheetFlow,
    channel_flow,
    faa,
    kirpich,
    scs_lag,
    shallow_concentrated_flow,
    sheet_flow,
    tr55,
)

# Sheet and shallow segments from TR-55 (1986) Example 3-1, rounded to 0.01 hr.
# TODO: confirm the example's channel inputs against the published TR-55.
EXAMPLE_SHEET = SheetFlow(n=0.24, length=100, p2=3.6, slope=0.01)
EXAMPLE_SHALLOW = ShallowFlow(length=1400, slope=0.01, paved=False)
CHANNEL = ChannelFlow(length=7300, slope=0.005, n=0.05, area=27, wetted_perimeter=28.2)


def test_tr55_example_segments():
    assert EXAMPLE_SHEET.travel_time() / 60 == pytest.approx(0.30, abs=0.005)
    assert EXAMPLE_SHALLOW.travel_time() / 60 == pytest.approx(0.24, abs=0.005)


def test_channel_segment_by_manning():
    velocity = 1.49 / 0.05 * (27 / 28.2) ** (2 / 3) * 0.005**0.5
    assert CHANNEL.travel_time() == pytest.approx(7300 / velocity / 60)


def test_tr55_sums_segments():
    segments = [EXAMPLE_SHEET, EXAMPLE_SHALLOW, CHANNEL]
    assert tr55(segments) == pytest.approx(sum(s.travel_time() for s in segments))


def test_paved_shallow_flow_is_faster():
    unpaved = shallow_concentrated_flow(500, 0.02, paved=False)
    paved = shallow_concentrated_flow(500, 0.02, paved=True)
    assert paved < unpaved
    assert unpaved / paved == pytest.approx(20.3282 / 16.1345)


def test_sheet_flow_length_limit():
    sheet_flow(0.011, 300, 3.0, 0.02)
    with pytest.raises(ValueError, match="300"):
        sheet_flow(0.011, 301, 3.0, 0.02)


def test_channel_flow_velocity():
    # Wide rectangular channel, R = 2 ft: V = 1.49/0.03 * 2^(2/3) * 0.01^0.5.
    velocity = 1.49 / 0.03 * 2 ** (2 / 3) * 0.1
    assert channel_flow(1000, 0.01, 0.03, 40, 20) == pytest.approx(1000 / velocity / 60)


def test_tr55_requires_segments():
    with pytest.raises(ValueError):
        tr55([])


def test_kirpich():
    assert kirpich(1000, 0.01) == pytest.approx(0.0078 * 1000**0.77 * 0.01**-0.385)
    assert kirpich(1000, 0.04) < kirpich(1000, 0.01)


def test_faa_takes_slope_in_ft_per_ft():
    # S = 0.02 ft/ft is 2 percent in the FAA formula.
    assert faa(0.5, 400, 0.02) == pytest.approx(1.8 * 0.6 * 20 / 2 ** (1 / 3))


def test_faa_more_impervious_is_faster():
    assert faa(0.9, 400, 0.02) < faa(0.3, 400, 0.02)


def test_scs_lag():
    # CN 75 -> S = 3.333 in; Y = 4 percent; lag in hours, Tc = lag / 0.6.
    lag = 2000**0.8 * (1000 / 75 - 9) ** 0.7 / (1900 * 2)
    assert scs_lag(75, 2000, 0.04) == pytest.approx(60 * lag / 0.6)


@pytest.mark.parametrize(
    "call",
    [
        lambda: sheet_flow(0.24, 100, 3.6, 0),
        lambda: kirpich(-5, 0.01),
        lambda: faa(1.5, 400, 0.02),
        lambda: scs_lag(0, 2000, 0.04),
    ],
)
def test_invalid_inputs_rejected(call):
    with pytest.raises(ValueError):
        call()
