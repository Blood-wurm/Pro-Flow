"""NRCS (SCS) curve number runoff. Depths are in inches."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
from numpy.typing import ArrayLike


def potential_retention(cn: float) -> float:
    """S = 1000/CN - 10, in inches."""
    if not 0 < cn <= 100:
        raise ValueError("curve number must be in (0, 100]")
    return 1000 / cn - 10


def runoff_depth(
    precip: ArrayLike, cn: float, ia_ratio: float = 0.2
) -> np.ndarray | float:
    """Direct runoff Q = (P - Ia)^2 / (P - Ia + S), with Ia = ia_ratio * S.

    precip may be an array of cumulative depths, giving cumulative runoff.
    """
    p = np.asarray(precip, dtype=float)
    if np.any(p < 0):
        raise ValueError("precipitation must not be negative")
    s = potential_retention(cn)
    excess = np.maximum(p - ia_ratio * s, 0.0)
    q = np.divide(excess**2, excess + s, out=np.zeros_like(excess), where=excess > 0)
    return float(q) if q.ndim == 0 else q


def excess_increments(
    cumulative_precip: ArrayLike, cn: float, ia_ratio: float = 0.2
) -> np.ndarray:
    """Runoff depth falling in each interval of a cumulative rainfall series.

    Applies the runoff equation to the accumulated rainfall and differences the
    result (NEH 630 ch. 10; app. 21B table 21B-4). Element k is the excess in
    the interval between cumulative values k and k + 1.
    """
    p = np.asarray(cumulative_precip, dtype=float)
    if p.ndim != 1 or len(p) < 2:
        raise ValueError("need a 1-D cumulative series of two or more values")
    if np.any(np.diff(p) < 0):
        raise ValueError("cumulative precipitation must never decrease")
    return np.diff(runoff_depth(p, cn, ia_ratio))


def composite(values: Sequence[float], areas: Sequence[float]) -> float:
    """Area-weighted average, for a composite CN or runoff coefficient C."""
    v = np.asarray(values, dtype=float)
    a = np.asarray(areas, dtype=float)
    if v.shape != a.shape or v.size == 0:
        raise ValueError("values and areas must be equal-length and non-empty")
    if np.any(a < 0) or a.sum() <= 0:
        raise ValueError("areas must be non-negative with a positive total")
    return float((v * a).sum() / a.sum())
