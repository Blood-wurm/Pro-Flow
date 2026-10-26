"""Intensity-duration-frequency (IDF) curves.

Two equation forms are supported, matching Hydraflow:

- FHA:        i = B / (t + D)^E
- Polynomial: i = A + B*x + C*x^2 + D*x^3, where x = ln(t)

Durations are in minutes and intensities in in/hr throughout.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol

import numpy as np
from numpy.typing import ArrayLike

# Return periods (years) Hydraflow stores per IDF file.
STANDARD_RETURN_PERIODS = (1, 2, 3, 5, 10, 25, 50, 100)


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


def fit_fha(
    durations: Sequence[float],
    intensities: Sequence[float],
    d_max: float = 100.0,
) -> FhaCurve:
    """Fit FHA coefficients to tabulated IDF points by least squares in log space.

    For a fixed d, ln(i) = ln(b) - e*ln(t + d) is linear, so b and e follow from
    ordinary regression. d is found by searching [0, d_max] for the smallest
    residual: a coarse grid first, then a fine grid around the best value.
    """
    t = _durations(durations)
    i = np.asarray(intensities, dtype=float)
    if t.shape != i.shape or t.ndim != 1:
        raise ValueError("durations and intensities must be equal-length 1-D")
    if len(t) < 3:
        raise ValueError("at least three points are needed to fit b, d and e")
    if np.any(i <= 0):
        raise ValueError("intensities must be positive")
    y = np.log(i)

    def regress(d: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        # Rows are candidate d values, columns are data points.
        x = np.log(t[None, :] + d[:, None])
        xm = x.mean(axis=1, keepdims=True)
        ym = y.mean()
        slope = ((x - xm) * (y - ym)).sum(axis=1) / ((x - xm) ** 2).sum(axis=1)
        intercept = ym - slope * xm[:, 0]
        sse = ((y - (intercept[:, None] + slope[:, None] * x)) ** 2).sum(axis=1)
        return slope, intercept, sse

    step = d_max / 1000
    grid = np.linspace(0.0, d_max, 1001)
    _, _, sse = regress(grid)
    best = grid[np.argmin(sse)]
    fine = np.linspace(max(best - step, 0.0), min(best + step, d_max), 2001)
    slope, intercept, sse = regress(fine)
    k = np.argmin(sse)
    return FhaCurve(b=float(np.exp(intercept[k])), d=float(fine[k]), e=float(-slope[k]))


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
