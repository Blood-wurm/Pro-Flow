"""One storm sewer line: capacity, starting HGL and the HGL/EGL by standard step.

Follows the Hydraflow Storm Sewers manual, Computational Methods (pp. 63-66)
and Starting HGLs (p. 42):

- Friction slope by Manning, Sf = (Q n / (1.486 A R^(2/3)))^2, averaged between
  the two ends of the line; head loss = Sf_avg * L.
- Standard step: z_up + y_up + V_up^2/2g = z_dn + y_dn + V_dn^2/2g + hf, solved
  for y_up, one step between the ends of the line, as the manual describes.
- Starting HGL at the outfall: a known elevation, the crown, normal depth,
  critical depth or (dc + D)/2 (HDS-5). It never starts below critical depth;
  a lower value is reset to critical. Normal depth below critical also
  becomes critical.
- Starting HGL of any other line ("junction" boundary): the HGL Junct of its
  downstream line (manual p. 64). Where that is below critical depth at this
  line's outlet -- the line drops into the structure -- the line starts at
  critical depth. The manual's Minimum Starting Depth and Correct EGL
  Discrepancies design codes are not applied.
- When the energy equation cannot balance above critical depth, the upstream
  end is set to critical depth (the manual's subcritical pass). The
  supercritical profile and hydraulic jump the manual then computes are not
  built here; the result says so.
- Junction loss at the upstream end: HGL Junct = HGL Up + K V_up^2/2g, not
  applied at critical depth. EGL = HGL + velocity head.
- Above the crown the line flows full: area and hydraulic radius are the
  full-pipe values (pressure flow).
- Capacity is full-flow Manning on the invert slope; it does not exist on a
  flat or adverse line.

Units: ft, cfs, ft/s. Line length is junction centre to junction centre, as
the manual defines it (p. 47).
"""

from __future__ import annotations

from dataclasses import dataclass

from proflow.engine.channel import G, critical_depth, normal_depth
from proflow.engine.result import SolveResult, Status
from proflow.engine.sections import K_MANNING, Circular
from proflow.engine.solve import bisect

STANDARD_STEP = "sewer.standard_step/1"
CAPACITY = "sewer.capacity.manning_full/1"

# Starting HGL choices at an outfall (Storm Sewers manual p. 42).
TAILWATER_MODES = ("elevation", "crown", "normal", "critical", "dc_d_half")
TAILWATER_LABELS = {
    "elevation": "Known elevation",
    "crown": "Crown",
    "normal": "Normal depth",
    "critical": "Critical depth",
    "dc_d_half": "(dc + D)/2",
}

# Downstream boundaries the line solver accepts: an outfall's starting HGL,
# or the HGL in the junction a line discharges into.
BOUNDARY_MODES = (*TAILWATER_MODES, "junction")

# Default junction loss coefficient for a line at the end of a branch
# (Storm Sewers manual p. 66).
END_OF_BRANCH_K = 1.0


@dataclass(frozen=True)
class Line:
    """A circular line. Inverts are elevations at its two ends (ft)."""

    diameter: float
    length: float
    invert_up: float
    invert_down: float
    n: float

    @property
    def slope(self) -> float:
        return (self.invert_up - self.invert_down) / self.length

    @property
    def shape(self) -> Circular:
        return Circular(self.diameter)

    def problem(self) -> str:
        if not self.diameter > 0:
            return "diameter must be positive"
        if not self.length > 0:
            return "length must be positive"
        if not 0 < self.n < 1:
            return "Manning's n must be in (0, 1)"
        return ""

    # --- section properties, full-pipe above the crown --------------------

    def area(self, y: float) -> float:
        return self.shape.area(min(y, self.diameter))

    def hydraulic_radius(self, y: float) -> float:
        y = min(y, self.diameter)
        return self.shape.area(y) / self.shape.wetted_perimeter(y)

    def velocity(self, flow: float, y: float) -> float:
        return flow / self.area(y)

    def friction_slope(self, flow: float, y: float) -> float:
        conveyance = (
            K_MANNING / self.n * self.area(y) * self.hydraulic_radius(y) ** (2 / 3)
        )
        return (flow / conveyance) ** 2

    def full_flow(self) -> float | None:
        """Full-flow Manning capacity on the invert slope; None unless it falls."""
        if self.slope <= 0:
            return None
        return self.shape.flow(self.diameter, self.slope, self.n)


@dataclass(frozen=True)
class EndState:
    """Hydraulics at one end of the line."""

    invert: float
    depth: float
    velocity: float
    surcharged: bool
    at_critical: bool

    @property
    def hgl(self) -> float:
        return self.invert + self.depth

    @property
    def velocity_head(self) -> float:
        return self.velocity**2 / (2 * G)

    @property
    def egl(self) -> float:
        return self.hgl + self.velocity_head


@dataclass(frozen=True)
class LineHydraulics:
    flow: float
    slope: float
    capacity: float | None  # full-flow Manning; None on a flat/adverse line
    full_velocity: float  # Q / full area
    normal_depth: float | None
    critical_depth: float
    tailwater_mode: str
    tailwater_elevation: float | None  # as entered, before any reset
    down: EndState
    up: EndState
    friction_slope: float  # average of the two ends
    friction_loss: float
    junction_k: float
    junction_loss: float

    @property
    def hgl_junction(self) -> float:
        return self.up.hgl + self.junction_loss

    @property
    def egl_junction(self) -> float:
        return self.hgl_junction + self.up.velocity_head


def _end(line: Line, flow: float, invert: float, y: float, dc: float) -> EndState:
    return EndState(
        invert=invert,
        depth=y,
        velocity=line.velocity(flow, y),
        surcharged=y > line.diameter,
        at_critical=abs(y - dc) <= 1e-9 * max(1.0, line.diameter),
    )


def _starting_depth(
    line: Line,
    flow: float,
    mode: str,
    elevation: float | None,
    dc: float,
    yn: float | None,
) -> tuple[float | None, list[str], str]:
    """Downstream depth for the chosen starting HGL: (depth, warnings, error)."""
    d = line.diameter
    if mode == "junction":
        if elevation is None:
            return None, [], "the junction HGL is required"
        y = elevation - line.invert_down
        if y < dc:
            return (
                dc,
                [
                    f"junction HGL {elevation:.3f} ft is below critical depth at "
                    f"this line's outlet ({line.invert_down + dc:.3f} ft): the line "
                    f"discharges freely into the junction and starts at critical "
                    f"depth"
                ],
                "",
            )
        return y, [], ""
    if mode == "elevation":
        if elevation is None:
            return None, [], "a known tailwater elevation is required"
        y = elevation - line.invert_down
        if y < dc:
            return (
                dc,
                [
                    f"tailwater {elevation:.3f} ft is below critical depth at the "
                    f"outlet ({line.invert_down + dc:.3f} ft); starting HGL reset to "
                    f"critical depth (Storm Sewers manual p. 42)"
                ],
                "",
            )
        return y, [], ""
    if mode == "crown":
        return d, [], ""
    if mode == "critical":
        return dc, [], ""
    if mode == "dc_d_half":
        return (dc + d) / 2, [], ""
    if mode == "normal":
        if yn is None:
            return (
                None,
                [],
                "normal depth does not exist for this line (flat or adverse slope, "
                "or the flow exceeds its open-channel capacity); choose another "
                "starting HGL",
            )
        if yn < dc:
            return (
                dc,
                ["normal depth is below critical depth; starting HGL set to critical"],
                "",
            )
        return yn, [], ""
    return None, [], f"unknown starting HGL {mode!r}; expected one of {BOUNDARY_MODES}"


def line_hydraulics(
    line: Line,
    flow: float,
    tailwater_mode: str,
    tailwater_elevation: float | None = None,
    junction_k: float = END_OF_BRANCH_K,
) -> SolveResult[LineHydraulics]:
    """HGL and EGL along one line, from its outfall starting HGL upstream."""
    problem = line.problem()
    if not problem and not flow > 0:
        problem = "flow must be positive"
    if not problem and junction_k < 0:
        problem = "junction loss coefficient must not be negative"
    if problem:
        return SolveResult(Status.INVALID_INPUT, STANDARD_STEP, message=problem)

    warnings: list[str] = []
    slope = line.slope
    capacity = line.full_flow()
    if slope < 0:
        warnings.append(
            f"adverse slope ({slope * 100:.3f} %): the upstream invert is lower than "
            f"the downstream invert; no full-flow capacity"
        )
    elif slope == 0:
        warnings.append("flat line: no full-flow capacity")
    elif flow > capacity:
        warnings.append(
            f"flow {flow:.3f} cfs exceeds the full-flow capacity {capacity:.3f} cfs"
        )

    dc = critical_depth(line.shape, flow)
    yn = None
    if slope > 0:
        r = normal_depth(line.shape, flow, slope, line.n)
        if r.ok:
            yn = r.value.depth

    y_dn, notes, error = _starting_depth(
        line, flow, tailwater_mode, tailwater_elevation, dc, yn
    )
    if error:
        return SolveResult(Status.INVALID_INPUT, STANDARD_STEP, message=error)
    warnings.extend(notes)

    down = _end(line, flow, line.invert_down, y_dn, dc)
    sf_dn = line.friction_slope(flow, y_dn)
    energy_dn = down.egl

    def imbalance(y: float) -> float:
        sf = (sf_dn + line.friction_slope(flow, y)) / 2
        upstream = line.invert_up + y + line.velocity(flow, y) ** 2 / (2 * G)
        return upstream - (energy_dn + sf * line.length)

    iterations = 0
    if imbalance(dc) >= 0:
        # No subcritical balance: the upstream end goes to critical depth.
        y_up = dc
        warnings.append(
            "the energy equation does not balance above critical depth: the "
            "upstream depth is set to critical (supercritical flow). The "
            "supercritical profile and any hydraulic jump are not computed in "
            "this version"
        )
    else:
        high = max(2 * line.diameter, dc * 2)
        while imbalance(high) < 0:
            high *= 2
        root = bisect(imbalance, dc, high, xtol=1e-9)
        if not root.converged:
            return SolveResult(  # pragma: no cover - bracketed bisection converges
                Status.NO_CONVERGENCE, STANDARD_STEP, iterations=root.iterations
            )
        y_up, iterations = root.x, root.iterations

    up = _end(line, flow, line.invert_up, y_up, dc)
    sf = (sf_dn + line.friction_slope(flow, y_up)) / 2
    junction_loss = 0.0 if up.at_critical else junction_k * up.velocity_head
    if down.surcharged or up.surcharged:
        warnings.append("the line is surcharged: the HGL is above the crown")

    result = LineHydraulics(
        flow=flow,
        slope=slope,
        capacity=capacity,
        full_velocity=flow / line.area(line.diameter),
        normal_depth=yn,
        critical_depth=dc,
        tailwater_mode=tailwater_mode,
        tailwater_elevation=tailwater_elevation,
        down=down,
        up=up,
        friction_slope=sf,
        friction_loss=sf * line.length,
        junction_k=junction_k,
        junction_loss=junction_loss,
    )
    return SolveResult(
        Status.SUCCESS,
        STANDARD_STEP,
        result,
        warnings=tuple(warnings),
        iterations=iterations,
        diagnostics={
            "energy_residual_ft": imbalance(y_up) if not up.at_critical else 0.0,
        },
    )
