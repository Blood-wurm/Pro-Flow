"""NRCS unit hydrographs and convolution.

Sources: NRCS NEH 630 ch. 16 (March 2007) table 16-1 and appendix 16A
equations; worked checks in example 16-1 and ch. 21 appendix 21B (May 2019).
The triangular form is the one the Hydraflow Hydrographs manual describes
(pp. 73-74).

Units: area acres, times minutes, flows cfs. Unit hydrograph ordinates are cfs
per inch of runoff, at t = 0, dt, 2*dt, ...
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import ArrayLike

from proflow.engine.hydrograph import Hydrograph
from proflow.engine.rainfall import MassCurve
from proflow.engine.result import SolveResult, Status
from proflow.engine.scs import excess_increments, runoff_depth

# NEH 630 table 16-1: dimensionless unit hydrograph, t/Tp and q/qp.
DUH_T = np.array(
    [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.3, 1.4,
     1.5, 1.6, 1.7, 1.8, 1.9, 2.0, 2.2, 2.4, 2.6, 2.8, 3.0, 3.2, 3.4, 3.6, 3.8,
     4.0, 4.5, 5.0]
)  # fmt: skip
DUH_Q = np.array(
    [0.000, 0.030, 0.100, 0.190, 0.310, 0.470, 0.660, 0.820, 0.930, 0.990, 1.000,
     0.990, 0.930, 0.860, 0.780, 0.680, 0.560, 0.460, 0.390, 0.330, 0.280, 0.207,
     0.147, 0.107, 0.077, 0.055, 0.040, 0.029, 0.021, 0.015, 0.011, 0.005, 0.000]
)  # fmt: skip

SHAPE_FACTOR = 484.0  # peak rate factor of the standard NRCS unit hydrograph
CUFT_PER_INCH_ACRE = 43560 / 12

# NEH 630 app. 16A: dt should be about 0.2 Tp and no more than 0.25 Tp.
MAX_STEP_RATIO = 0.25
# NEH 630 example 16-1 step 3: a unit hydrograph volume within 1 percent of
# 1 inch is negligible error.
UH_VOLUME_TOLERANCE = 0.01


def tp_from_lag(tc: float, dt: float) -> float:
    """Tp = dt/2 + 0.6 Tc (NEH 630 eq. 16A-7, lag = 0.6 Tc)."""
    return dt / 2 + 0.6 * tc


def tp_from_inflection(tc: float, dt: float) -> float:
    """Tp = (Tc + dt) / 1.7 (NEH 630 eq. 16A-10; Hydraflow manual p. 74)."""
    return (tc + dt) / 1.7


def peak_rate(area: float, tp: float, shape_factor: float = SHAPE_FACTOR) -> float:
    """qp = K A Q / Tp in cfs for Q = 1 inch, A in mi^2 and Tp in hours."""
    return shape_factor * (area / 640) / (tp / 60)


def curvilinear(area: float, tp: float, dt: float) -> np.ndarray:
    """NRCS dimensionless unit hydrograph scaled to qp and Tp, sampled every dt.

    Ordinates between table points are linearly interpolated, as in NEH 630
    table 16-2. The curve ends at 5 Tp.
    """
    n = int(np.ceil(5 * tp / dt - 1e-9)) + 1
    t = np.arange(n) * dt / tp
    return peak_rate(area, tp) * np.interp(t, DUH_T, DUH_Q, right=0.0)


def triangular(
    area: float, tp: float, dt: float, shape_factor: float = SHAPE_FACTOR
) -> np.ndarray:
    """Triangular unit hydrograph: rises to qp at Tp, base chosen to hold 1 inch.

    With K = 484 the base is 2.67 Tp (Hydraflow manual p. 74). For other K the
    base keeps the volume at one inch over the area: Tb = 2 V / qp.
    """
    qp = peak_rate(area, tp, shape_factor)
    tb = 2 * area * CUFT_PER_INCH_ACRE / (qp * 60)
    return Hydrograph.from_breakpoints([0.0, tp, tb], [0.0, qp, 0.0], dt).flows


def convolve(excess: ArrayLike, unit_hydrograph: ArrayLike) -> np.ndarray:
    """Direct runoff from incremental excess (in) and a unit hydrograph (cfs/in).

    excess[k] falls in the interval (k dt, (k+1) dt]; its response starts at
    k dt, so Q(n dt) = sum_k excess[k] * U[n - k] (NEH 630 app. 21B step 6).
    """
    r = np.asarray(excess, dtype=float)
    u = np.asarray(unit_hydrograph, dtype=float)
    return np.convolve(r, u)


@dataclass(frozen=True)
class ScsHydrograph:
    hydrograph: Hydrograph
    unit_hydrograph: np.ndarray
    tp: float
    cumulative_precip: np.ndarray
    excess: np.ndarray


def scs_runoff_hydrograph(
    area: float,
    cn: float,
    tc: float,
    storm: MassCurve,
    total_depth: float,
    dt: float,
    form: str = "curvilinear",
    tp_equation: str = "16A-10",
    shape_factor: float = SHAPE_FACTOR,
    ia_ratio: float = 0.2,
    tp: float | None = None,
) -> SolveResult[ScsHydrograph]:
    """Runoff hydrograph: storm -> CN excess -> unit hydrograph -> convolution.

    tp, if given, replaces the computed time to peak (e.g. app. 21B rounds
    4.76 h to 5 h). Diagnostics report the runoff depth from the runoff
    equation and from the hydrograph volume, so mass balance is visible; both
    are inches.
    """
    method = f"scs.uh.{form}/1"
    if area <= 0 or tc <= 0 or dt <= 0:
        return SolveResult(
            Status.INVALID_INPUT, method, message="area, Tc and dt must be positive"
        )
    if form not in ("curvilinear", "triangular"):
        return SolveResult(Status.INVALID_INPUT, method, message=f"unknown {form=}")
    if form == "curvilinear" and shape_factor != SHAPE_FACTOR:
        return SolveResult(
            Status.UNSUPPORTED_REGIME,
            method,
            message="table 16-1 is the K = 484 unit hydrograph; use triangular",
        )
    tp_of = {"16A-7": tp_from_lag, "16A-10": tp_from_inflection}.get(tp_equation)
    if tp_of is None:
        return SolveResult(
            Status.INVALID_INPUT, method, message=f"unknown {tp_equation=}"
        )
    try:
        precip = storm.cumulative_depths(total_depth, dt)
        excess = excess_increments(precip, cn, ia_ratio)
    except ValueError as exc:
        return SolveResult(Status.INVALID_INPUT, method, message=str(exc))

    if tp is None:
        tp = tp_of(tc, dt)
    elif tp <= 0:
        return SolveResult(Status.INVALID_INPUT, method, message="tp must be positive")
    if form == "curvilinear":
        uh = curvilinear(area, tp, dt)
    else:
        uh = triangular(area, tp, dt, shape_factor)
    flows = np.append(convolve(excess, uh), 0.0)
    hyd = Hydrograph(dt, flows)

    warnings = []
    if dt > MAX_STEP_RATIO * tp:
        warnings.append(
            f"time step {dt:g} min exceeds {MAX_STEP_RATIO} Tp ({tp:.4g} min); "
            "the unit hydrograph shape is under-sampled (NEH 630 app. 16A)"
        )
    uh_depth = np.trapezoid(uh, dx=dt * 60) / (area * CUFT_PER_INCH_ACRE)
    if abs(uh_depth - 1) > UH_VOLUME_TOLERANCE:
        warnings.append(
            f"sampled unit hydrograph holds {uh_depth:.4f} in, not 1 in "
            f"({uh_depth - 1:+.2%}); runoff volume is off by the same ratio"
        )
    equation_depth = float(runoff_depth(precip[-1], cn, ia_ratio))
    hydrograph_depth = hyd.volume / (area * CUFT_PER_INCH_ACRE)
    return SolveResult(
        Status.SUCCESS,
        method,
        ScsHydrograph(hyd, uh, tp, precip, excess),
        warnings=tuple(warnings),
        diagnostics={
            "tp_min": tp,
            "unit_hydrograph_depth_in": float(uh_depth),
            "runoff_depth_equation_in": equation_depth,
            "runoff_depth_hydrograph_in": float(hydrograph_depth),
            "mass_balance_residual_in": float(hydrograph_depth - equation_depth),
        },
    )
