import pytest

from proflow.io.units import (
    INTERNAL_UNITS,
    Quantity,
    UnitError,
    from_internal,
    to_internal,
)


def test_internal_units():
    assert INTERNAL_UNITS["slope"] == "ft/ft"
    assert INTERNAL_UNITS["time"] == "min"
    assert INTERNAL_UNITS["drainage_area"] == "ac"


def test_percent_slope_is_converted_explicitly():
    assert to_internal("slope", 0.33, "%") == pytest.approx(0.0033)
    assert from_internal("slope", 0.0033, "%") == pytest.approx(0.33)


def test_time_units():
    assert to_internal("time", 90, "s") == pytest.approx(1.5)
    assert from_internal("time", 14, "hr") == pytest.approx(14 / 60)


def test_si_conversions():
    # 1 ha = 2.4710538 ac; 1 m3/s = 35.314667 cfs (exact foot = 0.3048 m).
    assert to_internal("drainage_area", 1, "ha") == pytest.approx(2.4710538, rel=1e-7)
    assert to_internal("flow", 1, "cms") == pytest.approx(35.314667, rel=1e-7)
    assert to_internal("intensity", 25.4, "mm/hr") == pytest.approx(1.0)


def test_round_trip_every_unit():
    from proflow.io import units

    for kind, table in units._FACTORS.items():
        for unit in table:
            assert from_internal(kind, to_internal(kind, 3.7, unit), unit) == (
                pytest.approx(3.7)
            )


def test_unit_must_match_kind():
    with pytest.raises(UnitError, match="not valid for slope"):
        to_internal("slope", 1, "ft")
    with pytest.raises(UnitError, match="unknown quantity kind"):
        to_internal("speed", 1, "ft/s")


def test_quantity_from_dict():
    q = Quantity.from_dict({"value": 8.17, "unit": "ac"}, "drainage_area")
    assert q == Quantity(8.17, "ac")
    assert q.to_dict() == {"value": 8.17, "unit": "ac"}


@pytest.mark.parametrize(
    "data",
    [8.17, {"value": 8.17}, {"value": "8", "unit": "ac"}, {"value": 1, "unit": "ft"}],
)
def test_quantity_from_dict_rejects(data):
    with pytest.raises(UnitError):
        Quantity.from_dict(data, "drainage_area")
