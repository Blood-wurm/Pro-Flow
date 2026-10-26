"""Rational method: Q = C * i * A.

Units are acres, in/hr and cfs. As in Hydraflow, 1 in/hr over 1 acre is taken
as 1 cfs (the exact factor, 1.008, is ignored by convention). Times are minutes.

Hydrograph shapes follow the Hydraflow Hydrographs manual (pp. 23-24, 81):
the rising limb lasts Tc * ascending limb factor, the receding limb
Tc * receding limb factor, and intensity is always taken at Tc (Standard) or at
the storm duration (Modified). Ordinates are sampled on the equal-interval grid
described in proflow.engine.hydrograph.
"""

from __future__ import annotations

from proflow.engine.hydrograph import Hydrograph
from proflow.engine.idf import IdfCurve
from proflow.engine.result import SolveResult, Status

STANDARD = "rational.standard/2"
MODIFIED = "rational.modified/2"


def _problem(c: float, area: float, tc: float) -> str:
    if not 0 < c <= 1:
        return "runoff coefficient must be in (0, 1]"
    if area <= 0:
        return "drainage area must be positive"
    if tc <= 0:
        return "time of concentration must be positive"
    return ""


def peak_flow(c: float, intensity: float, area: float) -> float:
    """Peak runoff in cfs for coefficient C, intensity in in/hr and area in acres."""
    return c * intensity * area


def _sampled(
    method: str, times: list[float], flows: list[float], dt: float
) -> SolveResult[Hydrograph]:
    hyd = Hydrograph.from_breakpoints(times, flows, dt)
    return SolveResult(
        Status.SUCCESS,
        method,
        hyd,
        warnings=hyd.sampling_warnings(times, flows),
        diagnostics=Hydrograph.shape_diagnostics(times, flows),
    )


def standard_rational(
    c: float,
    area: float,
    tc: float,
    idf: IdfCurve,
    receding_limb_factor: float = 1.0,
    dt: float = 1.0,
    ascending_limb_factor: float = 1.0,
) -> SolveResult[Hydrograph]:
    """Triangular hydrograph peaking at C*i(Tc)*A at t = Tc * ascending factor."""
    problem = _problem(c, area, tc)
    if not problem and (receding_limb_factor <= 0 or ascending_limb_factor <= 0):
        problem = "limb factors must be positive"
    if not problem and dt <= 0:
        problem = "time step must be positive"
    if problem:
        return SolveResult(Status.INVALID_INPUT, STANDARD, message=problem)
    qp = peak_flow(c, float(idf.intensity(tc)), area)
    rise = tc * ascending_limb_factor
    end = rise + tc * receding_limb_factor
    return _sampled(STANDARD, [0.0, rise, end], [0.0, qp, 0.0], dt)


def modified_rational(
    c: float,
    area: float,
    tc: float,
    idf: IdfCurve,
    storm_duration_factor: float,
    dt: float = 1.0,
) -> SolveResult[Hydrograph]:
    """Trapezoidal hydrograph for a storm lasting Tc * storm_duration_factor.

    Flow rises over Tc to C*i(D)*A, holds until the storm ends at D, then
    recedes over Tc. For Tc = 20 and a factor of 2.25 the base is 65 minutes.
    """
    problem = _problem(c, area, tc)
    if not problem and storm_duration_factor < 1:
        problem = "storm duration factor must be at least 1"
    if not problem and dt <= 0:
        problem = "time step must be positive"
    if problem:
        return SolveResult(Status.INVALID_INPUT, MODIFIED, message=problem)
    duration = tc * storm_duration_factor
    qp = peak_flow(c, float(idf.intensity(duration)), area)
    times = [0.0, tc, duration, duration + tc]
    return _sampled(MODIFIED, times, [0.0, qp, qp, 0.0], dt)
