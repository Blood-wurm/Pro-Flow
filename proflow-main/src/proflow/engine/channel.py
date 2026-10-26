"""Uniform flow in prismatic open channels (Hydraflow Express, ch. 3).

Shapes: rectangular, triangular and trapezoidal, all described as a
trapezoid with bottom width b and side slopes z1, z2 (horizontal per 1
vertical); a rectangle has z1 = z2 = 0 and a triangle b = 0.

Equations (Express manual pp. 26-27):
- Manning: Q = (k / n) A R^(2/3) S^(1/2). The manual prints k = 1.49, but ten
  published Express channel reports reproduce with k = 1.486 and are 0.2 to
  0.3 % high with 1.49 (fixtures/express/), so K_MANNING = 1.486.
- Critical depth: Q^2 / g = A^3 / T, solved iteratively.
- Velocity = Q / A; EGL (energy) = depth + V^2 / 2g, measured from the invert.

Iterated depths: by default the exact normal and critical depths. Published
Express reports show every depth Express iterates for rounded up to the next
0.01 ft: the known-Q normal depth (B-B: exact 0.7819, printed 0.79, with area
and velocity at 0.79) and the critical depth (10 of 10 reports; rounding to
nearest matches 4). The manual only says "an iterative procedure".
depth_step reproduces that reporting on request, under ".stepped" method ids.

Lengths ft, flow cfs, slope ft/ft.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from proflow.engine.result import SolveResult, Status
from proflow.engine.solve import bisect

K_MANNING = 1.486  # US customary; see module docstring
G = 32.174  # ft/s^2
MAX_INCREMENTS = 50  # Express manual p. 22

KNOWN_DEPTH = "channel.manning.known_depth/1"
KNOWN_Q = "channel.manning.known_q/1"
RATING = "channel.manning.rating/1"


def _stepped(method: str, depth_step: float | None) -> str:
    return method if depth_step is None else method.replace("/1", ".stepped/1")


def _step_up(y: float, depth_step: float | None) -> float:
    if depth_step is None:
        return y
    return math.ceil(y / depth_step - 1e-9) * depth_step


@dataclass(frozen=True)
class Trapezoid:
    bottom_width: float = 0.0
    left_slope: float = 0.0  # z, horizontal : 1 vertical
    right_slope: float = 0.0

    @classmethod
    def rectangular(cls, width: float) -> Trapezoid:
        return cls(width, 0.0, 0.0)

    @classmethod
    def triangular(cls, left: float, right: float) -> Trapezoid:
        return cls(0.0, left, right)

    def problem(self) -> str:
        if self.bottom_width < 0 or self.left_slope < 0 or self.right_slope < 0:
            return "bottom width and side slopes must not be negative"
        if self.bottom_width == 0 and self.left_slope + self.right_slope == 0:
            return "a section needs a bottom width or side slopes"
        return ""

    def area(self, y: float) -> float:
        return y * (self.bottom_width + y * (self.left_slope + self.right_slope) / 2)

    def wetted_perimeter(self, y: float) -> float:
        sides = math.hypot(1, self.left_slope) + math.hypot(1, self.right_slope)
        return self.bottom_width + y * sides

    def top_width(self, y: float) -> float:
        return self.bottom_width + y * (self.left_slope + self.right_slope)


@dataclass(frozen=True)
class FlowState:
    depth: float
    flow: float
    area: float
    velocity: float
    wetted_perimeter: float
    hydraulic_radius: float
    top_width: float
    critical_depth: float
    egl: float  # depth + velocity head, above the invert
    froude: float

    @property
    def regime(self) -> str:
        if math.isclose(self.froude, 1.0, rel_tol=1e-6):
            return "critical"
        return "supercritical" if self.froude > 1 else "subcritical"


def manning_flow(shape: Trapezoid, y: float, slope: float, n: float) -> float:
    if y <= 0:
        return 0.0
    a, p = shape.area(y), shape.wetted_perimeter(y)
    return K_MANNING / n * a * (a / p) ** (2 / 3) * math.sqrt(slope)


def critical_depth(shape: Trapezoid, flow: float) -> float:
    """Depth where Q^2/g = A^3/T (minimum specific energy)."""
    if flow <= 0:
        return 0.0
    target = flow * flow / G

    def f(y: float) -> float:
        return shape.area(y) ** 3 / shape.top_width(y) - target

    high = 1.0
    while f(high) < 0:
        high *= 2
    return bisect(f, 1e-12, high).x


def _state(
    shape: Trapezoid, y: float, flow: float, depth_step: float | None = None
) -> FlowState:
    a = shape.area(y)
    p = shape.wetted_perimeter(y)
    t = shape.top_width(y)
    v = flow / a if a > 0 else 0.0
    froude = v / math.sqrt(G * a / t) if a > 0 else 0.0
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


def _inputs_problem(
    shape: Trapezoid, slope: float, n: float, total: float, step: float | None
) -> str:
    bad_step = step is not None and step <= 0
    return (
        shape.problem()
        or ("depth_step must be positive" if bad_step else "")
        or ("Manning's n must be positive" if n <= 0 else "")
        or ("total depth must be positive" if total <= 0 else "")
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
    shape: Trapezoid,
    depth: float,
    slope: float,
    n: float,
    total_depth: float,
    depth_step: float | None = None,
) -> SolveResult[FlowState]:
    """Normal flow for a known depth ("Known Depth")."""
    method = _stepped(KNOWN_DEPTH, depth_step)
    problem = _inputs_problem(shape, slope, n, total_depth, depth_step) or (
        "depth must be positive" if depth <= 0 else ""
    )
    if problem:
        return SolveResult(Status.INVALID_INPUT, method, message=problem)
    if (bad := _slope_regime(method, slope)) is not None:
        return bad
    if depth > total_depth:
        return SolveResult(
            Status.UNSUPPORTED_REGIME,
            method,
            message=f"depth {depth:g} ft exceeds total depth {total_depth:g} ft",
        )
    q = manning_flow(shape, depth, slope, n)
    return SolveResult(Status.SUCCESS, method, _state(shape, depth, q, depth_step))


def normal_depth(
    shape: Trapezoid,
    flow: float,
    slope: float,
    n: float,
    total_depth: float,
    depth_step: float | None = None,
) -> SolveResult[FlowState]:
    """Normal depth for a known flow ("Known Q").

    As in Express (manual p. 22), a flow that needs more than the total depth
    is not solved: the result is unsupported, with the full-depth capacity in
    the diagnostics. With depth_step, the depth is rounded up to a multiple
    of it (capped at the total depth) and the section is reported there, at
    the known flow; the exact depth stays in the diagnostics.
    """
    method = _stepped(KNOWN_Q, depth_step)
    problem = _inputs_problem(shape, slope, n, total_depth, depth_step) or (
        "flow must be positive" if flow <= 0 else ""
    )
    if problem:
        return SolveResult(Status.INVALID_INPUT, method, message=problem)
    if (bad := _slope_regime(method, slope)) is not None:
        return bad
    capacity = manning_flow(shape, total_depth, slope, n)
    if flow > capacity:
        return SolveResult(
            Status.UNSUPPORTED_REGIME,
            method,
            message=(
                f"{flow:g} cfs exceeds the {capacity:.4g} cfs capacity at the total "
                f"depth of {total_depth:g} ft"
            ),
            diagnostics={"capacity_cfs": capacity},
        )
    root = bisect(lambda y: manning_flow(shape, y, slope, n) - flow, 0.0, total_depth)
    if not root.converged:
        return SolveResult(
            Status.NO_CONVERGENCE, method, iterations=root.iterations
        )  # pragma: no cover - bisection on a bracket always converges
    depth = min(_step_up(root.x, depth_step), total_depth)
    return SolveResult(
        Status.SUCCESS,
        method,
        _state(shape, depth, flow, depth_step),
        iterations=root.iterations,
        diagnostics={"capacity_cfs": capacity, "exact_depth_ft": root.x},
    )


def rating(
    shape: Trapezoid,
    total_depth: float,
    increments: int,
    slope: float,
    n: float,
    depth_step: float | None = None,
) -> SolveResult[list[FlowState]]:
    """Q vs. depth at total_depth / increments steps ("Q vs. Depth").

    Express (manual pp. 22, 26): rows from one increment to the total depth,
    default 10 increments, at most 50.
    """
    method = _stepped(RATING, depth_step)
    problem = _inputs_problem(shape, slope, n, total_depth, depth_step)
    if not problem and not 1 <= increments <= MAX_INCREMENTS:
        problem = f"increments must be 1 to {MAX_INCREMENTS}"
    if problem:
        return SolveResult(Status.INVALID_INPUT, method, message=problem)
    if (bad := _slope_regime(method, slope)) is not None:
        return bad
    rows = []
    for k in range(1, increments + 1):
        y = total_depth * k / increments
        rows.append(_state(shape, y, manning_flow(shape, y, slope, n), depth_step))
    return SolveResult(Status.SUCCESS, method, rows)
