"""Numerical root finding shared by the hydraulic solvers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class Root:
    x: float
    iterations: int
    converged: bool


def bisect(
    f: Callable[[float], float],
    low: float,
    high: float,
    xtol: float = 1e-10,
    max_iterations: int = 200,
) -> Root:
    """Root of f in [low, high]; f(low) and f(high) must differ in sign.

    Bisection is slow but cannot fail on a bracketed, continuous function,
    which suits monotone relations such as Q(depth) and specific energy.
    """
    f_low, f_high = f(low), f(high)
    if f_low == 0:
        return Root(low, 0, True)
    if f_high == 0:
        return Root(high, 0, True)
    if (f_low > 0) == (f_high > 0):
        raise ValueError("root is not bracketed")
    for k in range(1, max_iterations + 1):
        mid = (low + high) / 2
        f_mid = f(mid)
        if f_mid == 0 or (high - low) / 2 < xtol:
            return Root(mid, k, True)
        if (f_mid > 0) == (f_low > 0):
            low, f_low = mid, f_mid
        else:
            high = mid
    return Root((low + high) / 2, max_iterations, False)
