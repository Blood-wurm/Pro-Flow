"""A branching storm sewer: Rational flow downstream, HGL/EGL upstream.

Flow (method "sewer.rational.accumulate/1"), after FHWA HEC-22, 3rd ed.
(FHWA-NHI-10-009, 2009, rev. 2013), section 7.5 steps 3-4 (pp. 7-31 to 7-34)
and section 7.2.2 (pp. 7-26 to 7-27):

- Each pipe carries the total C x A of every catchment upstream of it,
  including the one at its own upstream structure (Columns 7-8).
- Its system time is the longest of the incoming routes: an incoming pipe's
  time plus its section time, L / V (Column 10 plus Column 17; at a junction
  the longest flow path, section 7.2.2). The pipe's time of concentration is
  the larger of that and its own inlet time (Columns 9-10).
- Intensity comes from the IDF curve at that time, and Q = (sum CA) x i
  (Columns 11-12). Peaks of the branches are never added.
- Section time uses the design-flow velocity: Manning velocity at normal
  depth for the pipe's own Q (Chart 24 in the example). A pipe with no
  normal depth (flow over its open-channel capacity, or a flat or adverse
  line) uses Q / full area, and says so.
- Known flows are added to Q and carried downstream, as Hydraflow Storm
  Sewers does with "Accumulate Known Qs" (manual p. 16).

Hydraflow's own default bases pipe travel time on its Design Velocity code
unless Enhanced Modeling is selected (manual p. 43); Pro-Flow uses HEC-22's
design-flow velocity instead. A flow lower than an upstream pipe's is kept
and warned about (HEC-22 7.2.2 discusses when to check it).

Hydraulics (the line solver, Storm Sewers manual pp. 63-66): pipes into the
outfall start at its starting HGL; every other pipe starts at the HGL
Junct of the pipe it flows into -- that pipe's HGL Up plus its junction
loss K V^2/2g, the loss belonging to the line leaving the junction.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from proflow.engine.channel import normal_depth
from proflow.engine.result import SolveResult, Status
from proflow.engine.sewer import Line, LineHydraulics, line_hydraulics

RATIONAL_ACCUMULATE = "sewer.rational.accumulate/1"
HYDRAFLOW_EMS = "sewer.rational.hydraflow_ems_3pass/1"


@dataclass(frozen=True)
class Inflow:
    """What enters the system at a pipe's upstream structure."""

    ca: float = 0.0  # C x area, ac
    inlet_time: float | None = None  # min; None without a catchment
    known_flow: float = 0.0  # cfs


@dataclass(frozen=True)
class PipeFlow:
    ca_local: float
    ca_total: float
    known_total: float
    inlet_time: float | None
    system_time: float | None  # longest incoming route; None at a headwater
    tc: float | None  # min; time used for the intensity
    intensity: float  # in/hr; 0 with no catchment upstream
    flow: float  # cfs
    velocity: float  # ft/s, used for the section time
    velocity_basis: str  # "normal depth" or "full pipe"
    travel_time: float  # min, L / V
    controlling: str | None  # incoming pipe whose route sets the time


def _design_velocity(line: Line, flow: float) -> tuple[float, str, str]:
    """(velocity, basis, warning) for the section time."""
    full = flow / line.area(line.diameter)
    if line.slope <= 0:
        return full, "full pipe", "no normal depth on a flat or adverse line"
    r = normal_depth(line.shape, flow, line.slope, line.n)
    if not r.ok:
        return full, "full pipe", "flow exceeds the pipe's open-channel capacity"
    return flow / line.area(r.value.depth), "normal depth", ""


def rational_flows(
    order_upstream_first: tuple[str, ...],
    upstream: dict[str, tuple[str, ...]],
    inflows: dict[str, Inflow],
    lines: dict[str, Line],
    intensity: Callable[[float], float],
    *,
    travel_velocities: dict[str, float] | None = None,
    travel_basis: str = "supplied velocity",
    method: str = RATIONAL_ACCUMULATE,
) -> dict[str, SolveResult[PipeFlow]]:
    """Accumulate C x A, time and known flow from the headwaters downstream."""
    out: dict[str, SolveResult[PipeFlow]] = {}
    for pid in order_upstream_first:
        inflow = inflows.get(pid, Inflow())
        incoming = upstream.get(pid, ())
        failed = [u for u in incoming if not out[u].ok]
        if failed:
            out[pid] = SolveResult(
                Status.INVALID_INPUT,
                method,
                message=f"not calculated: upstream pipe {failed[0]} failed",
            )
            continue
        ups = [out[u].value for u in incoming]
        ca_total = inflow.ca + sum(u.ca_total for u in ups)
        known_total = inflow.known_flow + sum(u.known_total for u in ups)
        system_time, controlling = None, None
        for uid, u in zip(incoming, ups, strict=True):
            if u.tc is None:
                continue
            t = u.tc + u.travel_time
            if system_time is None or t > system_time:
                system_time, controlling = t, uid
        times = [t for t in (inflow.inlet_time, system_time) if t is not None]
        tc = max(times) if times else None
        if tc is not None and system_time is not None and tc == inflow.inlet_time:
            controlling = None  # the local inlet time governs
        warnings = []
        i = 0.0
        if ca_total > 0:
            if tc is None:  # pragma: no cover - CA always comes with a time
                raise ValueError("C x A without a time of concentration")
            try:
                i = float(intensity(tc))
            except ValueError as exc:
                out[pid] = SolveResult(Status.INVALID_INPUT, method, message=str(exc))
                continue
        flow = ca_total * i + known_total
        if flow <= 0:
            out[pid] = SolveResult(
                Status.INVALID_INPUT,
                method,
                message="no flow reaches this pipe (no catchment or known flow "
                "upstream)",
            )
            continue
        biggest = max((u.flow for u in ups), default=0.0)
        if flow < biggest:
            warnings.append(
                f"flow {flow:.3f} cfs is less than the {biggest:.3f} cfs of an "
                f"incoming pipe: the longer time of concentration lowers the "
                f"intensity more than the added area raises C x A (HEC-22 7.2.2 "
                f"discusses checking such cases); not adjusted"
            )
        line = lines[pid]
        if travel_velocities is None:
            velocity, basis, note = _design_velocity(line, flow)
        else:
            velocity = travel_velocities[pid]
            basis, note = travel_basis, ""
        if note:
            warnings.append(f"section time uses the full-pipe velocity: {note}")
        out[pid] = SolveResult(
            Status.SUCCESS,
            method,
            PipeFlow(
                ca_local=inflow.ca,
                ca_total=ca_total,
                known_total=known_total,
                inlet_time=inflow.inlet_time,
                system_time=system_time,
                tc=tc,
                intensity=i,
                flow=flow,
                velocity=velocity,
                velocity_basis=basis,
                travel_time=line.length / velocity / 60.0,
                controlling=controlling,
            ),
            warnings=tuple(warnings),
        )
    return out


def network_hydraulics(
    order_downstream_first: tuple[str, ...],
    downstream: dict[str, str | None],
    lines: dict[str, Line],
    flows: dict[str, float | None],
    junction_k: dict[str, float],
    tailwater_mode: str,
    tailwater_elevation: float | None,
) -> dict[str, SolveResult[LineHydraulics]]:
    """HGL/EGL from the outfall upstream, each line from its junction boundary."""
    out: dict[str, SolveResult[LineHydraulics]] = {}
    for pid in order_downstream_first:
        flow = flows.get(pid)
        below = downstream.get(pid)
        if flow is None:
            out[pid] = SolveResult(
                Status.INVALID_INPUT,
                "sewer.standard_step/1",
                message="not calculated: no flow for this pipe",
            )
            continue
        if below is None:
            mode, elevation = tailwater_mode, tailwater_elevation
        elif not out[below].ok:
            out[pid] = SolveResult(
                Status.INVALID_INPUT,
                "sewer.standard_step/1",
                message=f"not calculated: downstream pipe {below} failed",
            )
            continue
        else:
            mode, elevation = "junction", out[below].value.hgl_junction
        out[pid] = line_hydraulics(
            lines[pid], flow, mode, elevation, junction_k.get(pid, 1.0)
        )
    return out
