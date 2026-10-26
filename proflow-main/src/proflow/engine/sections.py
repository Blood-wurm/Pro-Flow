"""Channel cross-sections for the Express channel calculator.

Every section gives area, wetted perimeter and top width at a depth above its
invert, the flow it carries at that depth, its geometric depth limit, and its
ground profile as a polyline (for plots). Lengths ft, flow cfs, slope ft/ft.

- Trapezoid: rectangular, triangular and trapezoidal (Manning).
- Circular: a pipe flowing partly full (Manning). Flow peaks near 0.94 D.
- Gutter: curb, gutter of width W at cross slope Sw, roadway at Sx. Flow by
  the gutter equation the Express manual gives (p. 42), D = (Q n / (Kc Z
  S^0.5))^0.375 with Kc = 0.56, i.e. Q = Kc/n S^0.5 Z D^(8/3) per triangle,
  with "D in the gutter (Sw) and (Sx) sections separately": the Sw triangle
  to the curb depth, less its part beyond W, plus the Sx triangle beyond W.
  (HEC-22's Eo shortcut gives about 0.5 % more flow; published Express gutter
  reports match the separate-sections sum.)
- StationElevation: user-defined points with an n per segment; composite n
  by HEC-RAS eq. 2-6 as the Express manual cites (p. 27),
  nc = (sum(P_i n_i^1.5) / P)^(2/3).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

K_MANNING = 1.486  # see engine.channel
KC_GUTTER = 0.56  # HEC-22 / Express manual p. 42

Point = tuple[float, float]


def _manning(a: float, p: float, n: float, slope: float) -> float:
    if a <= 0 or p <= 0:
        return 0.0
    return K_MANNING / n * a * (a / p) ** (2 / 3) * math.sqrt(slope)


@dataclass(frozen=True)
class Trapezoid:
    bottom_width: float = 0.0
    left_slope: float = 0.0  # z, horizontal : 1 vertical
    right_slope: float = 0.0

    kind = "trapezoid"
    max_depth = None
    steps_normal_depth = True  # Express rounds the known-Q depth up to 0.01 ft
    flow_law = "manning"

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

    def flow(self, y: float, slope: float, n: float) -> float:
        return (
            _manning(self.area(y), self.wetted_perimeter(y), n, slope) if y > 0 else 0.0
        )

    def profile(self, depth: float) -> list[Point]:
        left_toe = self.left_slope * depth
        right_toe = left_toe + self.bottom_width
        return [
            (0, depth),
            (left_toe, 0),
            (right_toe, 0),
            (right_toe + self.right_slope * depth, depth),
        ]


@dataclass(frozen=True)
class Circular:
    diameter: float

    kind = "circular"
    steps_normal_depth = False  # published Express pipe reports fit the exact depth
    flow_law = "manning"

    @property
    def max_depth(self) -> float:
        return self.diameter

    def problem(self) -> str:
        return "" if self.diameter > 0 else "diameter must be positive"

    def _theta(self, y: float) -> float:
        y = min(max(y, 0.0), self.diameter)
        return 2 * math.acos(1 - 2 * y / self.diameter)

    def area(self, y: float) -> float:
        t = self._theta(y)
        return self.diameter**2 / 8 * (t - math.sin(t))

    def wetted_perimeter(self, y: float) -> float:
        return self.diameter * self._theta(y) / 2

    def top_width(self, y: float) -> float:
        return self.diameter * math.sin(self._theta(y) / 2)

    def flow(self, y: float, slope: float, n: float) -> float:
        return (
            _manning(self.area(y), self.wetted_perimeter(y), n, slope) if y > 0 else 0.0
        )

    def profile(self, depth: float, points: int = 72) -> list[Point]:
        """The full pipe wall, from the crown round the left, bottom and right."""
        r = self.diameter / 2
        return [
            (
                r - r * math.sin(2 * math.pi * k / points),
                r + r * math.cos(2 * math.pi * k / points),
            )
            for k in range(points + 1)
        ]


@dataclass(frozen=True)
class Gutter:
    cross_slope: float  # Sx, roadway, ft/ft
    gutter_slope: float  # Sw, gutter, ft/ft
    gutter_width: float  # W, ft

    kind = "gutter"
    max_depth = None
    steps_normal_depth = False  # published Express gutter reports show exact depths
    flow_law = "hec22"

    def problem(self) -> str:
        if self.cross_slope <= 0 or self.gutter_slope <= 0:
            return "cross slopes Sx and Sw must be positive"
        if self.gutter_width < 0:
            return "gutter width must not be negative"
        if self.gutter_slope < self.cross_slope:
            return "gutter slope Sw must be at least the roadway slope Sx"
        return ""

    @property
    def _gutter_rise(self) -> float:
        return self.gutter_width * self.gutter_slope

    def spread(self, y: float) -> float:
        """Top width (spread) for a depth y at the curb."""
        if y <= self._gutter_rise:
            return y / self.gutter_slope
        return self.gutter_width + (y - self._gutter_rise) / self.cross_slope

    def depth_for_spread(self, t: float) -> float:
        if t <= self.gutter_width:
            return t * self.gutter_slope
        return self._gutter_rise + (t - self.gutter_width) * self.cross_slope

    def area(self, y: float) -> float:
        if y <= self._gutter_rise:
            return y * y / (2 * self.gutter_slope)
        edge = y - self._gutter_rise  # depth at the gutter's outer edge
        road = edge * edge / (2 * self.cross_slope)
        return self.gutter_width * (y + edge) / 2 + road

    def wetted_perimeter(self, y: float) -> float:
        if y <= self._gutter_rise:
            return y + math.hypot(y / self.gutter_slope, y)
        gutter = math.hypot(self.gutter_width, self._gutter_rise)
        road_len = (y - self._gutter_rise) / self.cross_slope
        return y + gutter + road_len * math.hypot(1, self.cross_slope)

    def top_width(self, y: float) -> float:
        return self.spread(y)

    def flow(self, y: float, slope: float, n: float) -> float:
        """Sum over the Sw and Sx parts of Q = Kc/n S^0.5 Z D^(8/3)."""
        if y <= 0:
            return 0.0
        k = KC_GUTTER / n * math.sqrt(slope)
        sw, sx = self.gutter_slope, self.cross_slope

        def triangle(slope_x: float, depth: float) -> float:
            # Q of a triangular section of cross slope slope_x and depth `depth`
            return k / slope_x * depth ** (8 / 3) if depth > 0 else 0.0

        beyond = y - self._gutter_rise  # depth at the gutter's outer edge
        gutter = triangle(sw, y) - triangle(sw, beyond)
        return gutter + triangle(sx, beyond)

    def profile(self, depth: float) -> list[Point]:
        """Curb face, gutter and roadway out to where the road reaches `depth`."""
        reach = self.spread(depth)
        return [
            (0.0, depth),
            (0.0, 0.0),
            (self.gutter_width, self._gutter_rise),
            (reach, self.depth_for_spread(reach)),
        ]


@dataclass(frozen=True)
class StationElevation:
    """User-defined section: points (station, elevation), n for each segment.

    Depths are measured above the lowest point. Water may not rise above the
    lower end point, so that end sets the depth limit. Composite n follows
    HEC-RAS eq. 2-6.
    """

    stations: tuple[float, ...]
    elevations: tuple[float, ...]
    n_values: tuple[float, ...]  # one per segment, len(stations) - 1

    kind = "user"
    steps_normal_depth = True
    flow_law = "manning.composite"

    @classmethod
    def from_points(
        cls, points: Sequence[tuple[float, float, float]]
    ) -> StationElevation:
        """Express-style rows (station, elevation, n); the first n is unused."""
        sta = tuple(float(p[0]) for p in points)
        elev = tuple(float(p[1]) for p in points)
        ns = tuple(float(p[2]) for p in points[1:])
        return cls(sta, elev, ns)

    @property
    def invert(self) -> float:
        return min(self.elevations)

    @property
    def max_depth(self) -> float:
        return min(self.elevations[0], self.elevations[-1]) - self.invert

    def problem(self) -> str:
        if len(self.stations) < 3:
            return "a user-defined section needs at least three points"
        if len(self.stations) > 50:
            return "Express allows at most 50 points"
        if (
            len(self.elevations) != len(self.stations)
            or len(self.n_values) != len(self.stations) - 1
        ):
            return "need one elevation per station and one n per segment"
        if any(b <= a for a, b in zip(self.stations, self.stations[1:])):
            return "stations must increase from left to right"
        if any(n <= 0 for n in self.n_values):
            return "every segment needs a positive n"
        if self.max_depth <= 0:
            return "both end points must be above the lowest point"
        return ""

    def _segments(self, y: float):
        """Wetted part of each segment: (width, area, wetted length, n)."""
        level = self.invert + y
        out = []
        pts = list(zip(self.stations, self.elevations))
        for (x0, z0), (x1, z1), n in zip(pts, pts[1:], self.n_values):
            d0, d1 = level - z0, level - z1
            if d0 <= 0 and d1 <= 0:
                continue
            if d0 > 0 and d1 > 0:
                xa, xb, da, db = x0, x1, d0, d1
            else:
                cross = x0 + (x1 - x0) * d0 / (d0 - d1)
                xa, xb, da, db = (
                    (x0, cross, d0, 0.0) if d0 > 0 else (cross, x1, 0.0, d1)
                )
            width = xb - xa
            length = math.hypot(width, db - da)
            out.append((width, width * (da + db) / 2, length, n))
        return out

    def area(self, y: float) -> float:
        return sum(s[1] for s in self._segments(y))

    def wetted_perimeter(self, y: float) -> float:
        return sum(s[2] for s in self._segments(y))

    def top_width(self, y: float) -> float:
        return sum(s[0] for s in self._segments(y))

    def composite_n(self, y: float) -> float:
        segs = self._segments(y)
        p = sum(s[2] for s in segs)
        if p <= 0:
            return self.n_values[0]
        return (sum(s[2] * s[3] ** 1.5 for s in segs) / p) ** (2 / 3)

    def flow(self, y: float, slope: float, n: float) -> float:
        """Manning with the composite n (the n argument is not used)."""
        if y <= 0:
            return 0.0
        return _manning(
            self.area(y), self.wetted_perimeter(y), self.composite_n(y), slope
        )

    def profile(self, depth: float) -> list[Point]:
        return [(s, e - self.invert) for s, e in zip(self.stations, self.elevations)]
