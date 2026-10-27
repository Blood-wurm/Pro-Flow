"""Calculate a project without any GUI and build its results document."""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace

from proflow import __version__
from proflow.engine.hydrograph import Hydrograph
from proflow.engine.idf import POLYNOMIAL_RANGE, PolynomialCurve
from proflow.engine.junction import automatic_k, deflection_degrees
from proflow.engine.rational import (
    MODIFIED,
    STANDARD,
    modified_rational,
    standard_rational,
)
from proflow.engine.result import SolveResult, Status
from proflow.engine.sewer import STANDARD_STEP, Line, LineHydraulics
from proflow.engine.sewer_network import (
    HYDRAFLOW_EMS,
    RATIONAL_ACCUMULATE,
    Inflow,
    network_hydraulics,
    rational_flows,
)
from proflow.engine.unit_hydrograph import scs_runoff_hydrograph
from proflow.model.project import (
    SCHEMA_VERSION,
    Project,
    RationalCatchment,
    ScsCatchment,
)
from proflow.model.topology import Topology, network_topology

RESULTS_SCHEMA = "proflow-results"
RESULTS_SCHEMA_VERSION = 1

# No method has recorded validation evidence yet (see the implementation plan).
METHOD_STATUS = "experimental"


@dataclass(frozen=True)
class CatchmentResult:
    catchment: str
    event: int
    result: SolveResult[Hydrograph]
    # Method-specific values worth reporting, name -> (value, unit).
    quantities: dict[str, tuple[float, str]] = field(default_factory=dict)
    # Where the inputs came from, e.g. the storm distribution and its source.
    labels: dict[str, str] = field(default_factory=dict)


def _rational(
    project: Project, c: RationalCatchment, event: int, dt: float
) -> CatchmentResult:
    curve = project.idf_set(c.idf).curve(event)
    area = c.area.internal("drainage_area")
    tc = c.tc.internal("time")
    if c.method == "rational":
        method, duration = STANDARD, tc
    else:
        method, duration = MODIFIED, tc * c.storm_duration_factor
    try:
        intensity = float(curve.intensity(duration))
    except ValueError as exc:
        failed = SolveResult(Status.INVALID_INPUT, method, message=str(exc))
        return CatchmentResult(c.id, event, failed)
    if not intensity > 0:
        message = f"IDF gives {intensity:g} in/hr at {duration:g} min"
        failed = SolveResult(Status.INVALID_INPUT, method, message=message)
        return CatchmentResult(c.id, event, failed)
    if c.method == "rational":
        result = standard_rational(
            c.c,
            area,
            tc,
            curve,
            receding_limb_factor=c.receding_limb_factor,
            dt=dt,
            ascending_limb_factor=c.ascending_limb_factor,
        )
    else:
        result = modified_rational(c.c, area, tc, curve, c.storm_duration_factor, dt)
    low, high = POLYNOMIAL_RANGE
    if isinstance(curve, PolynomialCurve) and not low <= duration <= high:
        note = (
            f"polynomial IDF evaluated at {duration:g} min, outside the "
            f"{low:g}-{high:g} min range the Hydrographs manual gives (p. 80)"
        )
        result = replace(result, warnings=(*result.warnings, note))
    return CatchmentResult(c.id, event, result, {"intensity": (intensity, "in/hr")})


def _scs(project: Project, c: ScsCatchment, event: int, dt: float) -> CatchmentResult:
    storm = project.storm(c.storm)
    depth = storm.depth(event).internal("depth")
    r = scs_runoff_hydrograph(
        area=c.area.internal("drainage_area"),
        cn=c.cn,
        tc=c.tc.internal("time"),
        storm=storm.mass_curve(),
        total_depth=depth,
        dt=dt,
        form=c.unit_hydrograph,
        tp_equation=c.tp_equation,
        shape_factor=c.shape_factor,
        ia_ratio=c.ia_ratio,
        tp=None if c.tp is None else c.tp.internal("time"),
    )
    dist = storm.distribution
    labels = {"storm": storm.id}
    if dist is not None:
        labels |= {"storm_distribution": dist.id, "storm_source": dist.source}
        if dist.legacy:
            labels["storm_legacy"] = "yes"
        if dist.status_note:
            labels["storm_source_status"] = dist.status_note
        if dist.hydraflow_check:
            labels["storm_hydraflow_check"] = dist.hydraflow_check
    else:
        labels["storm_distribution"] = "user mass curve"
    if not r.ok:
        failed = SolveResult(r.status, r.method, message=r.message)
        return CatchmentResult(c.id, event, failed, labels=labels)
    warnings = r.warnings
    if dist is not None:
        warnings += dist.duration_warnings(storm.duration.internal("time"))
    result = SolveResult(
        r.status,
        r.method,
        r.value.hydrograph,
        warnings=warnings,
        diagnostics=r.diagnostics,
    )
    quantities = {
        "precipitation": (depth, "in"),
        "runoff_depth": (r.diagnostics["runoff_depth_equation_in"], "in"),
        "unit_hydrograph_tp": (r.value.tp, "min"),
    }
    return CatchmentResult(c.id, event, result, quantities, labels)


def calculate(project: Project) -> list[CatchmentResult]:
    dt = project.settings.time_step.internal("time")
    out = []
    for event in project.events:
        for c in project.catchments:
            if isinstance(c, ScsCatchment):
                out.append(_scs(project, c, event, dt))
            else:
                out.append(_rational(project, c, event, dt))
    return out


@dataclass(frozen=True)
class LineResult:
    """One sewer line for one event."""

    pipe: str
    event: int
    result: SolveResult[LineHydraulics]
    # Flow build-up and other reported values, name -> (value, unit).
    quantities: dict[str, tuple[float, str]] = field(default_factory=dict)
    downstream: str | None = None  # the pipe it flows into; None at the outfall
    upstream: tuple[str, ...] = ()  # pipes joining at its upstream end
    flow_method: str = RATIONAL_ACCUMULATE
    junction_loss_method: str = "entered"


def _line_failure(
    pipe: str,
    event: int,
    status: Status,
    message: str,
    flow_method: str = RATIONAL_ACCUMULATE,
    junction_loss_method: str = "entered",
) -> LineResult:
    return LineResult(
        pipe,
        event,
        SolveResult(status, STANDARD_STEP, message=message),
        flow_method=flow_method,
        junction_loss_method=junction_loss_method,
    )


def calculate_network(
    project: Project,
    *,
    sewer_method: str = "hec22",
    junction_losses: str = "entered",
    design_velocity: float | None = None,
) -> list[LineResult]:
    """Flow, capacity, travel time and HGL/EGL for every pipe, per event.

    The network must be a tree draining to one outfall (see
    proflow.model.topology); splits, cycles, dead ends and several outfalls
    are reported for every pipe instead of being approximated. Flow follows
    HEC-22 section 7.5 (proflow.engine.sewer_network); hydraulics run from the
    outfall upstream with the Storm Sewers manual's standard step.
    """
    if sewer_method not in ("hec22", "hydraflow_ems"):
        raise ValueError("sewer_method must be 'hec22' or 'hydraflow_ems'")
    if junction_losses not in ("entered", "automatic"):
        raise ValueError("junction_losses must be 'entered' or 'automatic'")
    if sewer_method != "hydraflow_ems" and design_velocity is not None:
        raise ValueError("design_velocity only applies to hydraflow_ems")
    if sewer_method == "hydraflow_ems" and (
        design_velocity is None
        or not math.isfinite(design_velocity)
        or design_velocity <= 0
    ):
        raise ValueError("hydraflow_ems requires a positive design_velocity in ft/s")
    net = project.network
    if net is None:
        return []
    pids = [p.id for p in net.pipes] or ["-"]
    topo, issues = network_topology(net)
    problem, status = "", Status.INVALID_INPUT
    if topo is None:
        bad = [i for i in issues if i.level != "info"]
        if all(i.level == "unsupported" for i in bad):
            status = Status.UNSUPPORTED_REGIME
        problem = "network: " + "; ".join(
            f"{i.code}" + (f" at {i.ref}" if i.ref else "") + f": {i.message}"
            for i in bad
        )
    elif missing := net.missing_inputs():
        problem = "missing: " + "; ".join(m for _, m in missing)
    else:
        idfs = sorted({c.idf for c in _network_catchments(project).values()})
        if len(idfs) > 1:
            problem = (
                f"the network's catchments use different IDF sets ({', '.join(idfs)}); "
                f"one system takes one IDF set"
            )
    out = []
    flow_method = (
        HYDRAFLOW_EMS if sewer_method == "hydraflow_ems" else RATIONAL_ACCUMULATE
    )
    for event in project.events:
        if problem:
            out += [
                _line_failure(pid, event, status, problem, flow_method, junction_losses)
                for pid in pids
            ]
        else:
            out += _event(
                project, topo, event, sewer_method, junction_losses, design_velocity
            )
    return out


def _network_catchments(project: Project) -> dict[str, RationalCatchment]:
    """Structure id -> its Rational catchment."""
    by_id = {c.id: c for c in project.catchments}
    return {
        s.id: by_id[s.catchment]
        for s in project.network.structures
        if s.catchment is not None
    }


def _junction_coefficients(net, topo: Topology, mode: str):
    """K for the pipe leaving each junction, from entries or plan deflection."""
    if mode == "entered":
        return {p.id: p.junction_k for p in net.pipes}, {}
    ks, notes = {}, {}
    for pid in topo.order:
        incoming = topo.upstream[pid]
        if not incoming:
            ks[pid] = 1.0  # manual p. 66: lines at ends of a branch
            continue
        pipe = net.pipe(pid)
        at = net.structure(pipe.upstream)
        down = net.structure(pipe.downstream)
        angles = []
        for uid in incoming:
            up = net.structure(net.pipe(uid).upstream)
            try:
                angle = deflection_degrees((up.x, up.y), (at.x, at.y), (down.x, down.y))
            except ValueError as exc:
                raise ValueError(f"pipe {pid}: {exc}") from exc
            angles.append(angle)
        # The manual gives one K per outgoing line but does not say which
        # angle governs with several incoming lines. Disclose this convention.
        selected = max(angles)
        ks[pid] = automatic_k(selected, at.kind)
        if len(angles) > 1:
            notes[pid] = (
                f"automatic K uses the largest of {len(angles)} incoming plan "
                "deflections; the Storm Sewers manual does not specify the "
                "selection rule at a branching junction"
            )
    return ks, notes


def _event(
    project: Project,
    topo: Topology,
    event: int,
    sewer_method: str,
    junction_losses: str,
    design_velocity: float | None,
) -> list[LineResult]:
    net = project.network
    flow_method = (
        HYDRAFLOW_EMS if sewer_method == "hydraflow_ems" else RATIONAL_ACCUMULATE
    )
    catchments = _network_catchments(project)
    lines, inflows = {}, {}
    for pipe in net.pipes:
        lines[pipe.id] = Line(
            diameter=pipe.diameter.internal("length"),
            length=pipe.length.internal("length"),
            invert_up=pipe.invert_up.internal("length"),
            invert_down=pipe.invert_down.internal("length"),
            n=pipe.n,
        )
        up = net.structure(pipe.upstream)
        c = catchments.get(up.id)
        inflows[pipe.id] = Inflow(
            ca=0.0 if c is None else c.c * c.area.internal("drainage_area"),
            inlet_time=None if c is None else c.tc.internal("time"),
            known_flow=0.0 if up.known_flow is None else up.known_flow.internal("flow"),
        )
    curve = None
    if catchments:
        idf = next(iter(catchments.values())).idf
        curve = project.idf_set(idf).curve(event)
    try:
        ks, junction_notes = _junction_coefficients(net, topo, junction_losses)
    except ValueError as exc:
        return [
            _line_failure(
                pid,
                event,
                Status.INVALID_INPUT,
                str(exc),
                flow_method,
                junction_losses,
            )
            for pid in topo.downstream_first()
        ]
    outfall = net.structure(topo.outfall)
    tw = outfall.tailwater
    intensity = (lambda t: float(curve.intensity(t))) if curve else (lambda t: 0.0)
    velocities = (
        {pid: design_velocity for pid in lines}
        if sewer_method == "hydraflow_ems"
        else None
    )
    for pass_no in range(1, 4 if velocities is not None else 2):
        flows = rational_flows(
            topo.upstream_first(),
            topo.upstream,
            inflows,
            lines,
            intensity,
            travel_velocities=velocities,
            travel_basis="design code" if pass_no == 1 else "prior hydraulic pass",
            method=flow_method,
        )
        hydraulics = network_hydraulics(
            topo.downstream_first(),
            topo.downstream,
            lines,
            {pid: (r.value.flow if r.ok else None) for pid, r in flows.items()},
            ks,
            tw.mode,
            None if tw.elevation is None else tw.elevation.internal("length"),
        )
        if velocities is not None and pass_no < 3:
            failed = next((pid for pid, r in hydraulics.items() if not r.ok), None)
            if failed is not None:
                message = (
                    f"Hydraflow comparison stopped after pass {pass_no}: pipe "
                    f"{failed}: {hydraulics[failed].message}"
                )
                return [
                    _line_failure(
                        pid,
                        event,
                        hydraulics[failed].status,
                        message,
                        flow_method,
                        junction_losses,
                    )
                    for pid in topo.downstream_first()
                ]
            velocities = {
                pid: (r.value.down.velocity + r.value.up.velocity) / 2
                for pid, r in hydraulics.items()
            }
    out = []
    for pid in topo.downstream_first():
        fr, hr = flows[pid], hydraulics[pid]
        quantities: dict[str, tuple[float, str]] = {}
        if fr.ok:
            f = fr.value
            quantities |= {"ca_local": (f.ca_local, "ac"), "ca": (f.ca_total, "ac")}
            if f.inlet_time is not None:
                quantities["inlet_time"] = (f.inlet_time, "min")
            if f.system_time is not None:
                quantities["system_time"] = (f.system_time, "min")
            if f.tc is not None:
                quantities["tc"] = (f.tc, "min")
                quantities["intensity"] = (f.intensity, "in/hr")
                quantities["runoff"] = (f.ca_total * f.intensity, "cfs")
            if f.known_total:
                quantities["known_flow"] = (f.known_total, "cfs")
            quantities |= {
                "flow": (f.flow, "cfs"),
                "travel_velocity": (f.velocity, "ft/s"),
                "travel_time": (f.travel_time, "min"),
            }
            if sewer_method == "hydraflow_ems" and hr.ok:
                quantities["design_velocity"] = (design_velocity, "ft/s")
                quantities["hydraulic_average_velocity"] = (
                    (hr.value.down.velocity + hr.value.up.velocity) / 2,
                    "ft/s",
                )
            extra_note = (junction_notes[pid],) if pid in junction_notes else ()
            hr = replace(hr, warnings=(*fr.warnings, *extra_note, *hr.warnings))
        else:
            hr = SolveResult(fr.status, fr.method, message=fr.message)
        if hr.ok:
            hr = replace(
                hr, warnings=(*hr.warnings, *_rim_notes(net, pid, hr.value, topo))
            )
        out.append(
            LineResult(
                pid,
                event,
                hr,
                quantities,
                downstream=topo.downstream[pid],
                upstream=topo.upstream[pid],
                flow_method=flow_method,
                junction_loss_method=junction_losses,
            )
        )
    return out


def _rim_notes(net, pid: str, h: LineHydraulics, topo: Topology) -> list[str]:
    pipe = net.pipe(pid)
    up = net.structure(pipe.upstream)
    notes = []
    if up.rim is not None and h.hgl_junction > up.rim.internal("length"):
        notes.append(
            f"HGL in junction {up.id} ({h.hgl_junction:.3f} ft) is above its "
            f"rim ({up.rim.internal('length'):.3f} ft): water reaches the surface"
        )
    if topo.downstream[pid] is None:
        down = net.structure(pipe.downstream)
        if down.rim is not None and h.down.hgl > down.rim.internal("length"):
            notes.append(
                f"starting HGL ({h.down.hgl:.3f} ft) is above outfall {down.id}'s "
                f"rim ({down.rim.internal('length'):.3f} ft)"
            )
    return notes


def _q(value: float, unit: str) -> dict:
    return {"value": value, "unit": unit}


def _end_dict(end) -> dict:
    return {
        "invert": _q(end.invert, "ft"),
        "depth": _q(end.depth, "ft"),
        "hgl": _q(end.hgl, "ft"),
        "velocity": _q(end.velocity, "ft/s"),
        "velocity_head": _q(end.velocity_head, "ft"),
        "egl": _q(end.egl, "ft"),
        "surcharged": end.surcharged,
        "at_critical": end.at_critical,
    }


def network_rows(results: list[LineResult]) -> list[dict]:
    rows = []
    for r in results:
        row = {
            "pipe": r.pipe,
            "event": r.event,
            "downstream_pipe": r.downstream,
            "upstream_pipes": list(r.upstream),
            "flow_method": r.flow_method,
            "junction_loss_method": r.junction_loss_method,
            "method": r.result.method,
            "method_status": METHOD_STATUS,
            "status": str(r.result.status),
            "warnings": list(r.result.warnings),
            "message": r.result.message,
            "diagnostics": dict(r.result.diagnostics),
        }
        row |= {name: _q(v, unit) for name, (v, unit) in r.quantities.items()}
        h = r.result.value
        if h is not None:
            row |= {
                "slope": _q(h.slope, "ft/ft"),
                "capacity": None if h.capacity is None else _q(h.capacity, "cfs"),
                "full_velocity": _q(h.full_velocity, "ft/s"),
                "normal_depth": (
                    None if h.normal_depth is None else _q(h.normal_depth, "ft")
                ),
                "critical_depth": _q(h.critical_depth, "ft"),
                "tailwater_mode": h.tailwater_mode,
                "down": _end_dict(h.down),
                "up": _end_dict(h.up),
                "friction_slope": _q(h.friction_slope, "ft/ft"),
                "friction_loss": _q(h.friction_loss, "ft"),
                "junction_k": h.junction_k,
                "junction_loss": _q(h.junction_loss, "ft"),
                "hgl_junction": _q(h.hgl_junction, "ft"),
                "egl_junction": _q(h.egl_junction, "ft"),
            }
        rows.append(row)
    return rows


def results_document(
    project: Project,
    results: list[CatchmentResult],
    network: list[LineResult] | None = None,
) -> dict:
    rows = []
    for r in results:
        row = {
            "catchment": r.catchment,
            "event": r.event,
            "method": r.result.method,
            "method_status": METHOD_STATUS,
            "status": str(r.result.status),
            "warnings": list(r.result.warnings),
            "message": r.result.message,
            "diagnostics": dict(r.result.diagnostics),
        }
        row |= dict(r.labels)
        row |= {name: _q(v, unit) for name, (v, unit) in r.quantities.items()}
        hyd = r.result.value
        if hyd is not None:
            row |= {
                "peak": _q(hyd.peak, "cfs"),
                "time_to_peak": _q(hyd.time_to_peak, "min"),
                "volume": _q(hyd.volume, "ft3"),
                "hydrograph": {
                    "time_step": _q(hyd.dt, "min"),
                    "flows": {"unit": "cfs", "values": hyd.flows.tolist()},
                },
            }
        rows.append(row)
    return {
        "schema": RESULTS_SCHEMA,
        "schema_version": RESULTS_SCHEMA_VERSION,
        "proflow_version": __version__,
        "project": {"name": project.name, "schema_version": SCHEMA_VERSION},
        "results": rows,
    } | ({"network": network_rows(network)} if network else {})
