"""Weir hydraulics (Hydraflow Express manual, ch. 6, pp. 70-73).

Equations as the manual prints them; H is the head above the crest (velocity
head excluded), lengths ft, flow cfs. Energy (EGL) is H + V^2/2g with
V = Q / A, as Express reports it.

- Rectangular: Q = Cw L H^1.5, Cw 3.33 sharp, 2.6 broad; no end contractions.
- Compound (two-stage): the manual uses the rectangular equation for it. Pro-
  Flow sums a lower notch of width x and depth a and the full-width weir
  above it: Q = Cw x H^1.5 + Cw (L - x) (H - a)^1.5 for H > a. The manual does
  not spell this split out.
- Circular: Q = Cw A H^0.5, Cw 3.33, A the flow area at head H; H up to D.
- V-notch: Q = Cw H^2.5 with Cw = 2.54 tan(angle/2); angle up to 120 deg.
- Trapezoidal (Cipoletti): Q = 3.1 (B + 0.8 H z) H^1.5; z up to 4.
- Proportional (Sutro): Q = 4.96 a^0.5 B (H - a/3) for H >= a, with the
  curved sides X = B [1 - (2/pi) atan((y/a)^0.5)], y above the base. The manual
  gives no equation for heads below a, so those are reported as unsupported.

Only the rectangular weir has published Express cases (fixtures/public); the
others rest on the manual's equations and independent checks.

Depths are exact: published Express weir reports print the exact head (e.g.
velocity 4.01 ft/s is Q / A at 1.4532 ft, not at a stepped 1.46). So no
stepped mode is offered here.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from proflow.engine.result import SolveResult, Status
from proflow.engine.solve import bisect

DEFAULT_CW = {"sharp": 3.33, "broad": 2.6}
METHOD = "weir.rectangular/1"
RATING = "weir.rectangular.rating/1"
G = 32.174  # ft/s^2
MAX_INCREMENTS = 50  # Express manual ch. 6
MAX_V_NOTCH_ANGLE = 120.0  # degrees, Express manual p. 67
MAX_CIPOLETTI_Z = 4.0  # Express manual p. 67

Point = tuple[float, float]


@dataclass(frozen=True)
class WeirSection:
    """Flow properties at one head over a weir."""

    depth: float  # ft
    flow: float  # cfs
    area: float  # ft^2
    velocity: float  # ft/s, Q / area
    top_width: float  # ft
    egl: float  # ft above the crest, depth + V^2/2g


# --- shapes ------------------------------------------------------------------


@dataclass(frozen=True)
class Rectangular:
    length: float
    cw: float = 3.33
    kind = "rectangular"

    def problem(self) -> str:
        return ("crest length must be positive" if self.length <= 0 else "") or (
            "weir coefficient must be positive" if self.cw <= 0 else ""
        )

    def flow(self, h: float) -> float:
        return self.cw * self.length * h**1.5

    def area(self, h: float) -> float:
        return self.length * h

    def top_width(self, h: float) -> float:
        return self.length

    def min_head(self) -> float:
        return 0.0

    def profile(self, depth: float) -> list[Point]:
        pad = max(0.25 * self.length, 0.5)
        n = self.length
        return [(-pad, depth), (0, depth), (0, 0), (n, 0), (n, depth), (n + pad, depth)]


@dataclass(frozen=True)
class Compound:
    length: float  # L, upper crest length
    notch_length: float  # x, lower notch, < L
    notch_depth: float  # a
    cw: float = 3.33
    kind = "compound"

    def problem(self) -> str:
        if self.length <= 0 or self.notch_length <= 0 or self.notch_depth <= 0:
            return "lengths and the notch depth must be positive"
        if self.notch_length >= self.length:
            return "the lower notch must be shorter than the bottom length"
        return "weir coefficient must be positive" if self.cw <= 0 else ""

    def flow(self, h: float) -> float:
        upper = max(h - self.notch_depth, 0.0)
        return self.cw * (
            self.notch_length * h**1.5 + (self.length - self.notch_length) * upper**1.5
        )

    def area(self, h: float) -> float:
        upper = max(h - self.notch_depth, 0.0)
        return self.notch_length * min(h, self.notch_depth) + self.length * upper

    def top_width(self, h: float) -> float:
        return self.length if h > self.notch_depth else self.notch_length

    def min_head(self) -> float:
        return 0.0

    def profile(self, depth: float) -> list[Point]:
        pad = max(0.25 * self.length, 0.5)
        left = (self.length - self.notch_length) / 2
        right = left + self.notch_length
        a = self.notch_depth
        return [
            (-pad, depth), (0, depth), (0, a), (left, a), (left, 0),
            (right, 0), (right, a), (self.length, a), (self.length, depth),
            (self.length + pad, depth),
        ]  # fmt: skip


@dataclass(frozen=True)
class CircularWeir:
    diameter: float
    cw: float = 3.33
    kind = "circular"

    def problem(self) -> str:
        return ("diameter must be positive" if self.diameter <= 0 else "") or (
            "weir coefficient must be positive" if self.cw <= 0 else ""
        )

    def _theta(self, h: float) -> float:
        return 2 * math.acos(1 - 2 * min(max(h, 0.0), self.diameter) / self.diameter)

    def area(self, h: float) -> float:
        t = self._theta(h)
        return self.diameter**2 / 8 * (t - math.sin(t))

    def flow(self, h: float) -> float:
        return self.cw * self.area(h) * math.sqrt(max(h, 0.0))

    def top_width(self, h: float) -> float:
        return self.diameter * math.sin(self._theta(h) / 2)

    def min_head(self) -> float:
        return 0.0

    def profile(self, depth: float, points: int = 72) -> list[Point]:
        """The circular opening, from its top round the left, bottom and right."""
        r = self.diameter / 2
        return [
            (
                r - r * math.sin(2 * math.pi * k / points),
                r + r * math.cos(2 * math.pi * k / points),
            )
            for k in range(points + 1)
        ]


@dataclass(frozen=True)
class VNotch:
    angle: float  # total notch angle, degrees
    kind = "v_notch"

    @property
    def cw(self) -> float:
        return 2.54 * math.tan(math.radians(self.angle) / 2)

    def problem(self) -> str:
        if not 0 < self.angle <= MAX_V_NOTCH_ANGLE:
            return (
                f"notch angle must be over 0 and at most {MAX_V_NOTCH_ANGLE:g} degrees"
            )
        return ""

    def flow(self, h: float) -> float:
        return self.cw * h**2.5

    def area(self, h: float) -> float:
        return h * h * math.tan(math.radians(self.angle) / 2)

    def top_width(self, h: float) -> float:
        return 2 * h * math.tan(math.radians(self.angle) / 2)

    def min_head(self) -> float:
        return 0.0

    def profile(self, depth: float) -> list[Point]:
        half = depth * math.tan(math.radians(self.angle) / 2)
        pad = max(0.25 * half, 0.5)
        return [
            (-pad, depth),
            (0, depth),
            (half, 0),
            (2 * half, depth),
            (2 * half + pad, depth),
        ]


@dataclass(frozen=True)
class Cipoletti:
    bottom_width: float  # B
    side_slope: float = 4.0  # z, the manual's Cipoletti value
    coefficient: float = 3.1  # the manual's constant
    kind = "trapezoidal"

    @property
    def cw(self) -> float:
        return self.coefficient

    def problem(self) -> str:
        if self.bottom_width <= 0:
            return "bottom width must be positive"
        if not 0 < self.side_slope <= MAX_CIPOLETTI_Z:
            return f"side slope z must be over 0 and at most {MAX_CIPOLETTI_Z:g}"
        return ""

    def flow(self, h: float) -> float:
        return (
            self.coefficient * (self.bottom_width + 0.8 * h * self.side_slope) * h**1.5
        )

    def area(self, h: float) -> float:
        return h * (self.bottom_width + self.side_slope * h)

    def top_width(self, h: float) -> float:
        return self.bottom_width + 2 * self.side_slope * h

    def min_head(self) -> float:
        return 0.0

    def profile(self, depth: float) -> list[Point]:
        side = self.side_slope * depth
        pad = max(0.25 * self.bottom_width, 0.5)
        right = 2 * side + self.bottom_width
        return [
            (-pad, depth),
            (0, depth),
            (side, 0),
            (side + self.bottom_width, 0),
            (right, depth),
            (right + pad, depth),
        ]


@dataclass(frozen=True)
class Sutro:
    bottom_length: float  # B
    base_depth: float  # a
    kind = "proportional"
    cw = 4.96

    def problem(self) -> str:
        if self.bottom_length <= 0 or self.base_depth <= 0:
            return "bottom length and depth a must be positive"
        return ""

    def flow(self, h: float) -> float:
        a = self.base_depth
        return 4.96 * math.sqrt(a) * self.bottom_length * (h - a / 3)

    def _x(self, y: float) -> float:
        """Opening width at height y above the base (the manual's curve)."""
        return self.bottom_length * (
            1 - 2 / math.pi * math.atan(math.sqrt(max(y, 0.0) / self.base_depth))
        )

    def area(self, h: float) -> float:
        a, b = self.base_depth, self.bottom_length
        y = max(h - a, 0.0)
        # integral of X(y) dy = B [y - (2/pi)((y + a) atan(sqrt(y/a)) - sqrt(a y))]
        curved = b * (
            y - 2 / math.pi * ((y + a) * math.atan(math.sqrt(y / a)) - math.sqrt(a * y))
        )
        return b * min(h, a) + curved

    def top_width(self, h: float) -> float:
        return (
            self.bottom_length if h <= self.base_depth else self._x(h - self.base_depth)
        )

    def min_head(self) -> float:
        return self.base_depth

    def profile(self, depth: float, points: int = 40) -> list[Point]:
        """Rectangular base of height a, then the curved sides, symmetrical."""
        b, a = self.bottom_length, self.base_depth
        pad = max(0.25 * b, 0.5)
        heights = [k / points * max(depth - a, 0.0) for k in range(points + 1)]
        left = [((b - self._x(y)) / 2, a + y) for y in heights]
        right = [((b + self._x(y)) / 2, a + y) for y in heights]
        return [
            (-pad, depth), *reversed(left), (0, 0), (b, 0), *right, (b + pad, depth),
        ]  # fmt: skip


Shape = Rectangular | Compound | CircularWeir | VNotch | Cipoletti | Sutro


# --- solvers -----------------------------------------------------------------


def _method(shape: Shape, mode: str = "") -> str:
    return f"weir.{shape.kind}{'.' + mode if mode else ''}/1"


def _state(shape: Shape, h: float, flow: float) -> WeirSection:
    area = shape.area(h)
    velocity = flow / area if area > 0 else 0.0
    return WeirSection(
        h, flow, area, velocity, shape.top_width(h), h + velocity**2 / (2 * G)
    )


def _common_problem(shape: Shape, total_depth: float) -> str:
    return shape.problem() or (
        "total depth must be positive" if total_depth <= 0 else ""
    )


def _head_limit(shape: Shape, total_depth: float) -> float:
    if isinstance(shape, CircularWeir):
        return min(total_depth, shape.diameter)
    return total_depth


def flow_at_head(
    shape: Shape, head: float, total_depth: float
) -> SolveResult[WeirSection]:
    """Flow over a weir at a known head ("Known Depth")."""
    method = _method(shape)
    problem = _common_problem(shape, total_depth) or (
        "depth must not be negative" if head < 0 else ""
    )
    if problem:
        return SolveResult(Status.INVALID_INPUT, method, message=problem)
    limit = _head_limit(shape, total_depth)
    if head > limit:
        return SolveResult(
            Status.UNSUPPORTED_REGIME, method,
            message=f"depth {head:g} ft exceeds the weir depth {limit:g} ft",
        )  # fmt: skip
    if head < shape.min_head():
        return SolveResult(
            Status.UNSUPPORTED_REGIME, method,
            message=f"head {head:g} ft is below depth a = {shape.min_head():g} ft; the "
            "manual's proportional-weir equation applies from a upward",
        )  # fmt: skip
    return SolveResult(Status.SUCCESS, method, _state(shape, head, shape.flow(head)))


def head_for_flow(
    shape: Shape, flow: float, total_depth: float
) -> SolveResult[WeirSection]:
    """Head over a weir for a known flow ("Known Q"), by bisection on Q(H)."""
    method = _method(shape)
    problem = _common_problem(shape, total_depth) or (
        "flow must not be negative" if flow < 0 else ""
    )
    if problem:
        return SolveResult(Status.INVALID_INPUT, method, message=problem)
    limit = _head_limit(shape, total_depth)
    low = shape.min_head()
    capacity = shape.flow(limit)
    if flow > capacity:
        return SolveResult(
            Status.UNSUPPORTED_REGIME, method,
            message=f"flow {flow:g} cfs needs more head than the total depth of "
            f"{limit:g} ft (capacity {capacity:.4g} cfs)",
            diagnostics={"capacity_cfs": capacity},
        )  # fmt: skip
    if flow < shape.flow(low):
        return SolveResult(
            Status.UNSUPPORTED_REGIME, method,
            message=f"flow {flow:g} cfs is below {shape.flow(low):.4g} cfs, the flow "
            f"at depth a = {low:g} ft; the manual gives no equation for lower heads",
        )  # fmt: skip
    if isinstance(shape, Rectangular):  # closed form
        head = (flow / (shape.cw * shape.length)) ** (2 / 3)
        return SolveResult(Status.SUCCESS, method, _state(shape, head, flow))
    root = bisect(lambda h: shape.flow(h) - flow, low, limit)
    return SolveResult(
        Status.SUCCESS, method, _state(shape, root.x, flow), iterations=root.iterations
    )


def weir_rating(
    shape: Shape, total_depth: float, increments: int = 10
) -> SolveResult[list[WeirSection]]:
    """Q vs. depth at total_depth / increments steps ("Q vs. Depth").

    For a proportional weir, rows below depth a are left out with a warning.
    """
    method = _method(shape, "rating")
    problem = _common_problem(shape, total_depth)
    if not problem and not 1 <= increments <= MAX_INCREMENTS:
        problem = f"increments must be 1 to {MAX_INCREMENTS}"
    if problem:
        return SolveResult(Status.INVALID_INPUT, method, message=problem)
    limit = _head_limit(shape, total_depth)
    rows, skipped = [], 0
    for k in range(1, increments + 1):
        h = limit * k / increments
        if h < shape.min_head():
            skipped += 1
            continue
        rows.append(_state(shape, h, shape.flow(h)))
    warnings = ()
    if skipped:
        warnings = (
            f"{skipped} row(s) below depth a = {shape.min_head():g} ft left out: the "
            "manual's proportional-weir equation applies from a upward",
        )
    if not rows:
        return SolveResult(
            Status.UNSUPPORTED_REGIME, method,
            message="every row is below depth a", warnings=warnings,
        )  # fmt: skip
    return SolveResult(Status.SUCCESS, method, rows, warnings=warnings)


# --- rectangular API (kept) --------------------------------------------------


def rectangular_flow(
    length: float, depth: float, cw: float, total_depth: float
) -> SolveResult[WeirSection]:
    """Flow over a rectangular weir at a known head."""
    return flow_at_head(Rectangular(length, cw), depth, total_depth)


def rectangular_depth(
    length: float, flow: float, cw: float, total_depth: float
) -> SolveResult[WeirSection]:
    """Head over a rectangular weir for a known flow (closed-form inverse)."""
    r = head_for_flow(Rectangular(length, cw), flow, total_depth)
    if r.status is Status.UNSUPPORTED_REGIME and "capacity_cfs" in r.diagnostics:
        required = (flow / (cw * length)) ** (2 / 3)
        return SolveResult(
            r.status, r.method,
            message=f"flow {flow:g} cfs needs {required:.3f} ft of head, more than the "
            f"total depth of {total_depth:g} ft",
            diagnostics={"required_depth": required, **r.diagnostics},
        )  # fmt: skip
    return r


def rectangular_rating(
    length: float, cw: float, total_depth: float, increments: int = 10
) -> SolveResult[list[WeirSection]]:
    """Q vs. depth at total_depth / increments steps ("Q vs. Depth")."""
    return weir_rating(Rectangular(length, cw), total_depth, increments)
