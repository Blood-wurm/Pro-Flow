"""Time of concentration methods.

Lengths are feet and slopes are ft/ft (Hydraflow's UI takes percent; convert
before calling). Every function returns Tc or travel time in minutes.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# TR-55 limits sheet flow to 300 ft; beyond that it becomes shallow concentrated.
MAX_SHEET_FLOW_LENGTH = 300.0

# TR-55 Figure 3-1 shallow concentrated velocity coefficients: V = k * sqrt(s).
SHALLOW_K = {"paved": 20.3282, "unpaved": 16.1345}


def _positive(**values: float) -> None:
    for name, value in values.items():
        if value <= 0:
            raise ValueError(f"{name} must be positive")


def sheet_flow(n: float, length: float, p2: float, slope: float) -> float:
    """TR-55 sheet flow travel time.

    n is Manning's roughness for sheet flow and p2 the 2-yr, 24-hr rainfall in
    inches: Tt = 0.007 (nL)^0.8 / (P2^0.5 s^0.4) hours.
    """
    _positive(n=n, length=length, p2=p2, slope=slope)
    if length > MAX_SHEET_FLOW_LENGTH:
        raise ValueError(f"sheet flow length is limited to {MAX_SHEET_FLOW_LENGTH} ft")
    return 60 * 0.007 * (n * length) ** 0.8 / (p2**0.5 * slope**0.4)


def shallow_concentrated_flow(length: float, slope: float, paved: bool) -> float:
    """TR-55 shallow concentrated flow travel time."""
    _positive(length=length, slope=slope)
    velocity = SHALLOW_K["paved" if paved else "unpaved"] * math.sqrt(slope)
    return length / velocity / 60


def channel_flow(
    length: float, slope: float, n: float, area: float, wetted_perimeter: float
) -> float:
    """TR-55 open channel travel time at bank-full flow, by Manning's equation.

    area is the bank-full flow area (sq ft) and wetted_perimeter is in feet.
    """
    _positive(
        length=length, slope=slope, n=n, area=area, wetted_perimeter=wetted_perimeter
    )
    radius = area / wetted_perimeter
    velocity = 1.49 / n * radius ** (2 / 3) * math.sqrt(slope)
    return length / velocity / 60


@dataclass(frozen=True)
class SheetFlow:
    n: float
    length: float
    p2: float
    slope: float

    def travel_time(self) -> float:
        return sheet_flow(self.n, self.length, self.p2, self.slope)


@dataclass(frozen=True)
class ShallowFlow:
    length: float
    slope: float
    paved: bool

    def travel_time(self) -> float:
        return shallow_concentrated_flow(self.length, self.slope, self.paved)


@dataclass(frozen=True)
class ChannelFlow:
    length: float
    slope: float
    n: float
    area: float
    wetted_perimeter: float

    def travel_time(self) -> float:
        return channel_flow(
            self.length, self.slope, self.n, self.area, self.wetted_perimeter
        )


def tr55(segments: list[SheetFlow | ShallowFlow | ChannelFlow]) -> float:
    """TR-55 Tc: the sum of the segment travel times along the flow path."""
    if not segments:
        raise ValueError("at least one flow segment is required")
    return sum(segment.travel_time() for segment in segments)


def kirpich(length: float, slope: float) -> float:
    """Kirpich (1940): Tc = 0.0078 L^0.77 S^-0.385."""
    _positive(length=length, slope=slope)
    return 0.0078 * length**0.77 * slope**-0.385


def faa(c: float, length: float, slope: float) -> float:
    """FAA airfield method: Tc = 1.8 (1.1 - C) L^0.5 / S^(1/3), S in percent."""
    _positive(length=length, slope=slope)
    if not 0 < c <= 1:
        raise ValueError("runoff coefficient must be in (0, 1]")
    return 1.8 * (1.1 - c) * length**0.5 / (100 * slope) ** (1 / 3)


def scs_lag(cn: float, length: float, slope: float) -> float:
    """NRCS lag method, with Tc = lag / 0.6.

    lag = l^0.8 (S + 1)^0.7 / (1900 Y^0.5) hours, where S = 1000/CN - 10 and Y
    is the average basin slope in percent.
    """
    _positive(length=length, slope=slope)
    if not 0 < cn <= 100:
        raise ValueError("curve number must be in (0, 100]")
    retention = 1000 / cn - 10
    lag = length**0.8 * (retention + 1) ** 0.7 / (1900 * (100 * slope) ** 0.5)
    return 60 * lag / 0.6
