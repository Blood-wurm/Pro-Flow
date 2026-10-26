"""Calculate a project without any GUI and build its results document."""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from proflow import __version__
from proflow.engine.hydrograph import Hydrograph
from proflow.engine.idf import POLYNOMIAL_RANGE, PolynomialCurve
from proflow.engine.rational import (
    MODIFIED,
    STANDARD,
    modified_rational,
    standard_rational,
)
from proflow.engine.result import SolveResult, Status
from proflow.engine.unit_hydrograph import scs_runoff_hydrograph
from proflow.model.project import (
    SCHEMA_VERSION,
    Project,
    RationalCatchment,
    ScsCatchment,
)

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
        if dist.status_note:
            labels["storm_source_status"] = dist.status_note
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


def _q(value: float, unit: str) -> dict:
    return {"value": value, "unit": unit}


def results_document(project: Project, results: list[CatchmentResult]) -> dict:
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
    }
