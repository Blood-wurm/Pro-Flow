"""Weir hydraulics.

Rectangular weir (Hydraflow Express manual, ch. 6): Q = Cw * L * H^1.5, with
Cw = 3.33 sharp crested or 2.6 broad crested, H the head above the crest
excluding velocity head, and no end-contraction correction. Energy (EGL) is
H + V^2/2g with V = Q / (L H), as Express reports it.

Depths are exact: the published Express weir report (fixtures/public) prints
velocity 4.01 ft/s, which is Q / A at the exact head 1.4532 ft, not at 1.45
(4.02) or a stepped 1.46 (3.99). So no stepped mode is offered here.
"""

from __future__ import annotations

from dataclasses import dataclass

from proflow.engine.result import SolveResult, Status

DEFAULT_CW = {"sharp": 3.33, "broad": 2.6}
METHOD = "weir.rectangular/1"
RATING = "weir.rectangular.rating/1"
G = 32.174  # ft/s^2
MAX_INCREMENTS = 50  # Express manual ch. 6


@dataclass(frozen=True)
class WeirSection:
    """Flow properties at one depth over a rectangular weir."""

    depth: float  # ft
    flow: float  # cfs
    area: float  # ft^2
    velocity: float  # ft/s, Q / area
    top_width: float  # ft
    egl: float  # ft above the crest, depth + V^2/2g


def _section(length: float, depth: float, flow: float) -> WeirSection:
    area = length * depth
    velocity = flow / area if area > 0 else 0.0
    egl = depth + velocity**2 / (2 * G)
    return WeirSection(depth, flow, area, velocity, length, egl)


def _check(length: float, cw: float, total_depth: float) -> str:
    if length <= 0:
        return "crest length must be positive"
    if cw <= 0:
        return "weir coefficient must be positive"
    if total_depth <= 0:
        return "total depth must be positive"
    return ""


def rectangular_flow(
    length: float, depth: float, cw: float, total_depth: float
) -> SolveResult[WeirSection]:
    """Flow over a rectangular weir at a known head."""
    problem = _check(length, cw, total_depth) or (
        "depth must not be negative" if depth < 0 else ""
    )
    if problem:
        return SolveResult(Status.INVALID_INPUT, METHOD, message=problem)
    if depth > total_depth:
        return SolveResult(
            Status.UNSUPPORTED_REGIME,
            METHOD,
            message=f"depth {depth:g} ft exceeds total depth {total_depth:g} ft",
        )
    flow = cw * length * depth**1.5
    return SolveResult(Status.SUCCESS, METHOD, _section(length, depth, flow))


def rectangular_depth(
    length: float, flow: float, cw: float, total_depth: float
) -> SolveResult[WeirSection]:
    """Head over a rectangular weir for a known flow (closed-form inverse)."""
    problem = _check(length, cw, total_depth) or (
        "flow must not be negative" if flow < 0 else ""
    )
    if problem:
        return SolveResult(Status.INVALID_INPUT, METHOD, message=problem)
    depth = (flow / (cw * length)) ** (2 / 3)
    if depth > total_depth:
        return SolveResult(
            Status.UNSUPPORTED_REGIME,
            METHOD,
            message=f"flow {flow:g} cfs needs {depth:.3f} ft of head, more than "
            f"the total depth of {total_depth:g} ft",
            diagnostics={"required_depth": depth},
        )
    return SolveResult(Status.SUCCESS, METHOD, _section(length, depth, flow))


def rectangular_rating(
    length: float, cw: float, total_depth: float, increments: int = 10
) -> SolveResult[list[WeirSection]]:
    """Q vs. depth at total_depth / increments steps ("Q vs. Depth")."""
    problem = _check(length, cw, total_depth)
    if not problem and not 1 <= increments <= MAX_INCREMENTS:
        problem = f"increments must be 1 to {MAX_INCREMENTS}"
    if problem:
        return SolveResult(Status.INVALID_INPUT, RATING, message=problem)
    rows = []
    for k in range(1, increments + 1):
        h = total_depth * k / increments
        rows.append(_section(length, h, cw * length * h**1.5))
    return SolveResult(Status.SUCCESS, RATING, rows)
