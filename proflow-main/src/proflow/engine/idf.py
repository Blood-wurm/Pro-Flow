"""Intensity-duration-frequency (IDF) curves.

Two equation forms are supported, matching Hydraflow:

- FHA:        i = B / (t + D)^E
- Polynomial: i = A + B*x + C*x^2 + D*x^3, where x = ln(t)

Durations are in minutes and intensities in in/hr throughout.

Interpolation policy: intensities between tabulated durations come from the
equation, never from interpolating the table. A fitted FHA curve is supported
over the durations it was fitted to (FhaFit.duration_range); the Hydrographs
manual (p. 80) gives 8 to 180 minutes as the appropriate range for the
polynomial form (POLYNOMIAL_RANGE). Callers report evaluations outside these.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol

import numpy as np
from numpy.typing import ArrayLike

from proflow.engine.result import SolveResult, Status

# Return periods (years) Hydraflow stores per IDF file.
STANDARD_RETURN_PERIODS = (1, 2, 3, 5, 10, 25, 50, 100)

POLYNOMIAL_RANGE = (8.0, 180.0)  # minutes; Hydrographs manual p. 80

FIT_METHOD = "idf.fha.fit/1"
# Pro-Flow default: warn when a fitted point misses its entered value by more
# than 1 percent. The Hydraflow manual (Express p. 54) notes that points
# plotting concave on log scale fit poorly; this makes that visible.
FIT_TOLERANCE = 0.01


class IdfCurve(Protocol):
    def intensity(self, duration: ArrayLike) -> np.ndarray | float: ...


def _durations(duration: ArrayLike) -> np.ndarray:
    t = np.asarray(duration, dtype=float)
    if np.any(t <= 0):
        raise ValueError("duration must be positive")
    return t


def _result(value: np.ndarray) -> np.ndarray | float:
    return float(value) if value.ndim == 0 else value


@dataclass(frozen=True)
class FhaCurve:
    """i = b / (t + d)^e. With d = e = 0 this is a constant rate of b in/hr."""

    b: float
    d: float
    e: float

    def intensity(self, duration: ArrayLike) -> np.ndarray | float:
        t = _durations(duration)
        return _result(self.b / (t + self.d) ** self.e)


@dataclass(frozen=True)
class PolynomialCurve:
    """i = a + b*x + c*x^2 + d*x^3, x = ln(t). Used by e.g. FDOT zone curves."""

    a: float
    b: float
    c: float
    d: float

    def intensity(self, duration: ArrayLike) -> np.ndarray | float:
        x = np.log(_durations(duration))
        return _result(self.a + x * (self.b + x * (self.c + x * self.d)))


def _regress(t: np.ndarray, y: np.ndarray, d: np.ndarray):
    """Least squares of ln(i) on ln(t + d) for each candidate d (rows)."""
    x = np.log(t[None, :] + d[:, None])
    xm = x.mean(axis=1, keepdims=True)
    ym = y.mean()
    slope = ((x - xm) * (y - ym)).sum(axis=1) / ((x - xm) ** 2).sum(axis=1)
    intercept = ym - slope * xm[:, 0]
    sse = ((y - (intercept[:, None] + slope[:, None] * x)) ** 2).sum(axis=1)
    return slope, intercept, sse


def _checked(durations: Sequence[float], intensities: Sequence[float]):
    t = _durations(durations)
    i = np.asarray(intensities, dtype=float)
    if t.shape != i.shape or t.ndim != 1:
        raise ValueError("durations and intensities must be equal-length 1-D")
    if len(t) < 3:
        raise ValueError("at least three points are needed to fit b, d and e")
    if np.any(i <= 0):
        raise ValueError("intensities must be positive")
    if np.any(np.diff(t) <= 0):
        raise ValueError("durations must strictly increase")
    return t, i


def fit_fha(
    durations: Sequence[float],
    intensities: Sequence[float],
    d_max: float = 100.0,
    d_step: float | None = None,
) -> FhaCurve:
    """Fit FHA coefficients to tabulated IDF points by least squares in log space.

    For a fixed d, ln(i) = ln(b) - e*ln(t + d) is linear, so b and e follow from
    ordinary regression (the Hydrographs manual, p. 79, describes the same
    straight-line-on-log-paper idea). d is searched over [0, d_max]: by default
    a coarse grid then a fine one around the best value; with d_step, only
    multiples of d_step are tried.
    """
    t, i = _checked(durations, intensities)
    y = np.log(i)
    if d_step is not None:
        if d_step <= 0:
            raise ValueError("d_step must be positive")
        grid = np.arange(0.0, d_max + d_step / 2, d_step)
        slope, intercept, sse = _regress(t, y, grid)
        k = int(np.argmin(sse))
        return FhaCurve(float(np.exp(intercept[k])), float(grid[k]), float(-slope[k]))
    step = d_max / 1000
    grid = np.linspace(0.0, d_max, 1001)
    _, _, sse = _regress(t, y, grid)
    best = grid[np.argmin(sse)]
    fine = np.linspace(max(best - step, 0.0), min(best + step, d_max), 2001)
    slope, intercept, sse = _regress(t, y, fine)
    k = int(np.argmin(sse))
    return FhaCurve(b=float(np.exp(intercept[k])), d=float(fine[k]), e=float(-slope[k]))


@dataclass(frozen=True)
class FhaFit:
    curve: FhaCurve
    durations: np.ndarray  # minutes, as entered
    intensities: np.ndarray  # in/hr, as entered
    fitted: np.ndarray  # in/hr from the curve at the same durations

    @property
    def residuals(self) -> np.ndarray:
        return self.fitted - self.intensities

    @property
    def relative_residuals(self) -> np.ndarray:
        return self.residuals / self.intensities

    @property
    def duration_range(self) -> tuple[float, float]:
        return float(self.durations[0]), float(self.durations[-1])


def fit_fha_report(
    durations: Sequence[float],
    intensities: Sequence[float],
    d_max: float = 100.0,
    d_step: float | None = None,
    tolerance: float = FIT_TOLERANCE,
) -> SolveResult[FhaFit]:
    """fit_fha plus the diagnostics needed to judge the fit."""
    try:
        t, i = _checked(durations, intensities)
        curve = fit_fha(t, i, d_max, d_step)
    except ValueError as exc:
        return SolveResult(Status.INVALID_INPUT, FIT_METHOD, message=str(exc))
    fit = FhaFit(curve, t, i, np.asarray(curve.intensity(t)))
    rel = fit.relative_residuals
    worst = int(np.argmax(np.abs(rel)))
    warnings = []
    if len(t) == 3:
        warnings.append(
            "three points fix b, d and e exactly; residuals cannot show misfit"
        )
    rises = np.nonzero(np.diff(i) >= 0)[0]
    if rises.size:
        k = int(rises[0])
        warnings.append(
            f"intensity does not decrease from {t[k]:g} to {t[k + 1]:g} min; "
            "an IDF curve should fall with duration"
        )
    if abs(rel[worst]) > tolerance:
        warnings.append(
            f"fitted intensity at {t[worst]:g} min is {fit.fitted[worst]:.4g} in/hr "
            f"vs {i[worst]:.4g} entered ({rel[worst]:+.2%}); points that plot concave "
            "on log scale fit poorly (Hydraflow Express manual p. 54)"
        )
    if curve.d >= d_max - (d_step or d_max / 1000) / 2:
        warnings.append(
            f"d reached the search limit {d_max:g} min; the fit may be poor"
        )
    return SolveResult(
        Status.SUCCESS,
        FIT_METHOD,
        fit,
        warnings=tuple(warnings),
        diagnostics={
            "b": curve.b,
            "d": curve.d,
            "e": curve.e,
            "n_points": float(len(t)),
            "duration_min": float(t[0]),
            "duration_max": float(t[-1]),
            "max_abs_residual_in_hr": float(np.abs(fit.residuals).max()),
            "max_relative_residual": float(np.abs(rel).max()),
            "rms_log_residual": float(np.sqrt(np.mean(np.log(fit.fitted / i) ** 2))),
        },
    )


@dataclass
class IdfSet:
    """IDF curves for one location, keyed by return period in years."""

    curves: dict[int, IdfCurve] = field(default_factory=dict)
    name: str = ""

    @classmethod
    def fit_table(
        cls,
        durations: Sequence[float],
        table: Mapping[int, Sequence[float]],
        name: str = "",
    ) -> IdfSet:
        """Build FHA curves from a table of intensities per return period."""
        return cls({rp: fit_fha(durations, row) for rp, row in table.items()}, name)

    def intensity(self, return_period: int, duration: ArrayLike) -> np.ndarray | float:
        try:
            curve = self.curves[return_period]
        except KeyError:
            raise KeyError(f"no IDF curve for {return_period}-yr storm") from None
        return curve.intensity(duration)
