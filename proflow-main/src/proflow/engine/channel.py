"""Uniform flow in prismatic open channels (Hydraflow Express, ch. 3).

Sections (engine.sections): rectangular, triangular and trapezoidal (one
Trapezoid with bottom width b and side slopes z1, z2), circular pipe flowing
part full, curb-and-gutter (HEC-22), and user-defined station/elevation
points with composite n.

Equations (Express manual pp. 26-27, 42):
- Manning: Q = (k / n) A R^(2/3) S^(1/2). The manual prints k = 1.49, but the
  published Express channel reports reproduce with k = 1.486 and are 0.2 to
  0.3 % high with 1.49 (fixtures/express/), so K_MANNING = 1.486.
- Gutter: HEC-22 gutter flow, see engine.sections.Gutter.
- Critical depth: Q^2 / g = A^3 / T, solved iteratively.
- Velocity = Q / A; EGL (energy) = depth + V^2 / 2g, measured from the invert.

Iterated depths: by default the exact normal and critical depths. Published
Express reports show critical depth rounded up to the next 0.01 ft (all
reports), and the known-Q normal depth rounded up too for Manning sections
(B-B: exact 0.7819, printed 0.79, with area and velocity at 0.79), but not for
gutters (the gutter reports' areas and spreads fit the exact depth).
depth_step reproduces that reporting on request, under ".stepped" method ids.

Lengths ft, flow cfs, slope ft/ft.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from proflow.engine.result import SolveResult, Status
from proflow.engine.sections import (
    K_MANNING,
    Circular,
    Gutter,
    StationElevation,
    Trapezoid,
)
from proflow.engine.solve import bisect

Section = Trapezoid | Circular | Gutter | StationElevation

G = 32.174  # ft/s^2
MAX_INCREMENTS = 50  # Express manual p. 22

_LAW_ID = {
    "manning": "manning",
    "manning.composite": "manning_composite",
    "hec22": "hec22_gutter",
}

__all__ = [
    "G",
    "K_MANNING",
    "Circular",
    "FlowState",
    "Gutter",
    "Section",
    "StationElevation",
    "Trapezoid",
    "critical_depth",
    "flow_at_depth",
    "manning_flow",
    "normal_depth",
    "rating",
]


def _method(shape: Section, mode: str, depth_step: float | None) -> str:
    stepped = ".stepped" if depth_step is not None else ""
    return f"channel.{_LAW_ID[shape.flow_law]}.{mode}{stepped}/1"


# Kept for the original Manning-section ids used across the code and fixtures.
KNOWN_DEPTH = "channel.manning.known_depth/1"
KNOWN_Q = "channel.manning.known_q/1"
RATING = "channel.manning.rating/1"


def _step_up(y: float, depth_step: float | None) -> float:
    if depth_step is None:
        return y
    return math.ceil(y / depth_step - 1e-9) * depth_step


@dataclass(frozen=True)
class FlowState:
    depth: float
    flow: float
    area: float
    velocity: float
    wetted_perimeter: float
    hydraulic_radius: float
    top_width: float  # for a gutter, the spread
    critical_depth: float
    egl: float  # depth + velocity head, above the invert
    froude: float

    @property
    def regime(self) -> str:
        if math.isclose(self.froude, 1.0, rel_tol=1e-6):
            return "critical"
        return "supercritical" if self.froude > 1 else "subcritical"


def manning_flow(shape: Section, y: float, slope: float, n: float) -> float:
    """Flow at depth y by the section's own law (Manning, or HEC-22 for gutters)."""
    return shape.flow(y, slope, n) if y > 0 else 0.0


def critical_depth(shape: Section, flow: float) -> float:
    """Depth where Q^2/g = A^3/T (minimum specific energy)."""
    if flow <= 0:
        return 0.0
    target = flow * flow / G

    def f(y: float) -> float:
        t = shape.top_width(y)
        return (shape.area(y) ** 3 / t if t > 0 else math.inf) - target

    limit = shape.max_depth
    if limit is not None:
        return bisect(f, 1e-12, limit * (1 - 1e-9)).x
    high = 1.0
    while f(high) < 0:
        high *= 2
    return bisect(f, 1e-12, high).x


def _state(
    shape: Section, y: float, flow: float, depth_step: float | None = None
) -> FlowState:
    a = shape.area(y)
    p = shape.wetted_perimeter(y)
    t = shape.top_width(y)
    v = flow / a if a > 0 else 0.0
    froude = v / math.sqrt(G * a / t) if a > 0 and t > 0 else 0.0
    return FlowState(
        depth=y,
        flow=flow,
        area=a,
        velocity=v,
        wetted_perimeter=p,
        hydraulic_radius=a / p if p > 0 else 0.0,
        top_width=t,
        critical_depth=_step_up(critical_depth(shape, flow), depth_step),
        egl=y + v * v / (2 * G),
        froude=froude,
    )


def _limit(shape: Section, total: float | None) -> float | None:
    """The deepest depth analysed: total depth, capped by the section itself."""
    caps = [d for d in (total, shape.max_depth) if d is not None]
    return min(caps) if caps else None


def _inputs_problem(
    shape: Section, slope: float, n: float, total: float | None, step: float | None
) -> str:
    bad_step = step is not None and step <= 0
    return (
        shape.problem()
        or ("depth_step must be positive" if bad_step else "")
        or ("Manning's n must be positive" if n <= 0 else "")
        or ("total depth must be positive" if total is not None and total <= 0 else "")
        or ("slope must be a number" if math.isnan(slope) else "")
    )


def _slope_regime(method: str, slope: float) -> SolveResult | None:
    if slope <= 0:
        kind = "horizontal" if slope == 0 else "adverse"
        return SolveResult(
            Status.UNSUPPORTED_REGIME,
            method,
            message=f"no uniform flow on a {kind} slope ({slope:g} ft/ft)",
        )
    return None


def flow_at_depth(
    shape: Section,
    depth: float,
    slope: float,
    n: float,
    total_depth: float | None = None,
    depth_step: float | None = None,
) -> SolveResult[FlowState]:
    """Normal flow for a known depth ("Known Depth")."""
    method = _method(shape, "known_depth", depth_step)
    problem = _inputs_problem(shape, slope, n, total_depth, depth_step) or (
        "depth must be positive" if depth <= 0 else ""
    )
    if problem:
        return SolveResult(Status.INVALID_INPUT, method, message=problem)
    if (bad := _slope_regime(method, slope)) is not None:
        return bad
    limit = _limit(shape, total_depth)
    if limit is not None and depth > limit:
        return SolveResult(
            Status.UNSUPPORTED_REGIME,
            method,
            message=f"depth {depth:g} ft exceeds the section depth {limit:g} ft",
        )
    q = manning_flow(shape, depth, slope, n)
    return SolveResult(Status.SUCCESS, method, _state(shape, depth, q, depth_step))


def _peak_depth(shape: Section, limit: float, slope: float, n: float) -> float:
    """Depth of greatest flow in [0, limit]: the limit, except for pipes."""
    if not isinstance(shape, Circular):
        return limit
    lo, hi = 0.0, limit
    phi = (math.sqrt(5) - 1) / 2
    for _ in range(80):  # golden-section search on the unimodal Q(y)
        a, b = hi - phi * (hi - lo), lo + phi * (hi - lo)
        if manning_flow(shape, a, slope, n) < manning_flow(shape, b, slope, n):
            lo = a
        else:
            hi = b
    return (lo + hi) / 2


def normal_depth(
    shape: Section,
    flow: float,
    slope: float,
    n: float,
    total_depth: float | None = None,
    depth_step: float | None = None,
) -> SolveResult[FlowState]:
    """Normal depth for a known flow ("Known Q").

    As in Express (manual p. 22), a flow above the section's capacity is not
    solved: the result is unsupported, with the capacity in the diagnostics.
    A pipe carries most near 0.94 D, so a flow between its full-pipe and peak
    flow has two normal depths: the lower is reported, with a warning. With
    depth_step, the depth is rounded up to a multiple of it where Express
    does so (not for gutters), and iterated critical depth likewise.
    """
    method = _method(shape, "known_q", depth_step)
    problem = _inputs_problem(shape, slope, n, total_depth, depth_step) or (
        "flow must be positive" if flow <= 0 else ""
    )
    if problem:
        return SolveResult(Status.INVALID_INPUT, method, message=problem)
    if (bad := _slope_regime(method, slope)) is not None:
        return bad
    limit = _limit(shape, total_depth)
    warnings = []
    diagnostics = {}
    if limit is not None:
        peak = _peak_depth(shape, limit, slope, n)
        capacity = manning_flow(shape, peak, slope, n)
        diagnostics["capacity_cfs"] = capacity
        if flow > capacity:
            return SolveResult(
                Status.UNSUPPORTED_REGIME,
                method,
                message=(
                    f"{flow:g} cfs exceeds the {capacity:.4g} cfs capacity of the "
                    f"section (depth limit {limit:g} ft)"
                ),
                diagnostics=diagnostics,
            )
        full = manning_flow(shape, limit, slope, n)
        if isinstance(shape, Circular) and flow > full:
            warnings.append(
                f"{flow:g} cfs is above the full-pipe flow {full:.4g} cfs: a second, "
                f"higher normal depth also exists; the lower one is reported"
            )
        high = peak
    else:
        high = 1.0
        while manning_flow(shape, high, slope, n) < flow:
            high *= 2
    root = bisect(lambda y: manning_flow(shape, y, slope, n) - flow, 0.0, high)
    if not root.converged:
        return SolveResult(
            Status.NO_CONVERGENCE, method, iterations=root.iterations
        )  # pragma: no cover - bisection on a bracket always converges
    depth = root.x
    if shape.steps_normal_depth:
        depth = _step_up(depth, depth_step)
        if limit is not None:
            depth = min(depth, limit)
    diagnostics["exact_depth_ft"] = root.x
    return SolveResult(
        Status.SUCCESS,
        method,
        _state(shape, depth, flow, depth_step),
        warnings=tuple(warnings),
        iterations=root.iterations,
        diagnostics=diagnostics,
    )


def rating(
    shape: Section,
    total_depth: float | None,
    increments: int,
    slope: float,
    n: float,
    depth_step: float | None = None,
) -> SolveResult[list[FlowState]]:
    """Q vs. depth at depth / increments steps ("Q vs. Depth").

    Express (manual pp. 22, 26): rows from one increment to the total depth,
    default 10 increments, at most 50. Needs a depth limit (a total depth, or
    the section's own).
    """
    method = _method(shape, "rating", depth_step)
    problem = _inputs_problem(shape, slope, n, total_depth, depth_step)
    limit = _limit(shape, total_depth)
    if not problem and limit is None:
        problem = "a Q vs. depth table needs a total depth"
    if not problem and not 1 <= increments <= MAX_INCREMENTS:
        problem = f"increments must be 1 to {MAX_INCREMENTS}"
    if problem:
        return SolveResult(Status.INVALID_INPUT, method, message=problem)
    if (bad := _slope_regime(method, slope)) is not None:
        return bad
    rows = []
    for k in range(1, increments + 1):
        y = limit * k / increments
        rows.append(_state(shape, y, manning_flow(shape, y, slope, n), depth_step))
    return SolveResult(Status.SUCCESS, method, rows)
