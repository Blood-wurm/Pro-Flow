"""Unit conversion at the boundary between stored/entered values and the engine.

Each quantity kind has one internal unit, which is what engine functions take:

    length ft, area ft^2, drainage_area ac, flow cfs, velocity ft/s,
    volume ft^3, time min, intensity in/hr, depth in, slope ft/ft

Percent slope and minutes vs. seconds are only ever converted here, never
assumed inside a solver.
"""

from __future__ import annotations

from dataclasses import dataclass

FT_PER_M = 1 / 0.3048

# kind -> {unit: factor}, where internal = value * factor.
_FACTORS: dict[str, dict[str, float]] = {
    "length": {"ft": 1.0, "in": 1 / 12, "m": FT_PER_M, "mm": FT_PER_M / 1000},
    "area": {"ft2": 1.0, "in2": 1 / 144, "m2": FT_PER_M**2},
    "drainage_area": {
        "ac": 1.0,
        "ha": FT_PER_M**2 * 1e4 / 43560,
        "ft2": 1 / 43560,
        "mi2": 640.0,
    },
    "flow": {"cfs": 1.0, "cms": FT_PER_M**3},
    "velocity": {"ft/s": 1.0, "m/s": FT_PER_M},
    "volume": {"ft3": 1.0, "m3": FT_PER_M**3, "ac-ft": 43560.0},
    "time": {"min": 1.0, "s": 1 / 60, "hr": 60.0},
    "intensity": {"in/hr": 1.0, "mm/hr": 1 / 25.4},
    "depth": {"in": 1.0, "mm": 1 / 25.4},
    "slope": {"ft/ft": 1.0, "%": 0.01},
    "dimensionless": {"-": 1.0},
}

INTERNAL_UNITS = {
    kind: next(u for u, f in units.items() if f == 1.0)
    for kind, units in _FACTORS.items()
}


class UnitError(ValueError):
    pass


def _factor(kind: str, unit: str) -> float:
    try:
        units = _FACTORS[kind]
    except KeyError:
        raise UnitError(f"unknown quantity kind {kind!r}") from None
    try:
        return units[unit]
    except KeyError:
        allowed = ", ".join(units)
        raise UnitError(f"unit {unit!r} is not valid for {kind} ({allowed})") from None


def to_internal(kind: str, value: float, unit: str) -> float:
    return value * _factor(kind, unit)


def from_internal(kind: str, value: float, unit: str) -> float:
    return value / _factor(kind, unit)


@dataclass(frozen=True)
class Quantity:
    """A value as entered, with its unit. Serialized as {"value", "unit"}."""

    value: float
    unit: str

    def internal(self, kind: str) -> float:
        return to_internal(kind, self.value, self.unit)

    def to_dict(self) -> dict:
        return {"value": self.value, "unit": self.unit}

    @classmethod
    def from_dict(cls, data: object, kind: str) -> Quantity:
        if not isinstance(data, dict) or set(data) != {"value", "unit"}:
            raise UnitError('expected {"value": <number>, "unit": <string>}')
        value, unit = data["value"], data["unit"]
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise UnitError(f"value must be a number, got {value!r}")
        _factor(kind, unit)
        return cls(float(value), unit)
