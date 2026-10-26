"""Weir hydraulics.

Rectangular weir (Hydraflow Express manual, ch. 6): Q = Cw * L * H^1.5, with
Cw = 3.33 sharp crested or 2.6 broad crested, H the head above the crest
excluding velocity head, and no end-contraction correction.
"""

from __future__ import annotations

from dataclasses import dataclass

from proflow.engine.result import SolveResult, Status

DEFAULT_CW = {"sharp": 3.33, "broad": 2.6}
METHOD = "weir.rectangular/1"


@dataclass(frozen=True)
class WeirSection:
    """Flow properties at one depth over a rectangular weir."""

    depth: float  # ft
    flow: float  # cfs
    area: float  # ft^2
    velocity: float  # ft/s, Q / area
    top_width: float  # ft


def _section(length: float, depth: float, flow: float) -> WeirSection:
    area = length * depth
    velocity = flow / area if area > 0 else 0.0
    return WeirSection(depth, flow, area, velocity, length)


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
