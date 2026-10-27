"""Reference-case fixtures: published or hand-checked results the engine must match.

A fixture (schema "proflow-fixture/1") is a JSON file recording where a case
comes from, its inputs with units, and the outputs as the source displays them.
Expected values are strings so the displayed precision survives; unless a
fixture states a tolerance, it is half the last displayed digit.

Inputs are {"value", "unit"} or, for a series, {"values": [...], "unit"}.
Expected outputs are {"value": "1.45", "unit"} or {"values": ["0.013", ...],
"unit", "start": k}, where start is the index of the first listed value in the
computed series (default 0). Each series element is checked on its own and
named "name[i]".

An expected entry with "gate": false is compared and shown but never fails
the case, e.g. fitted coefficients compared with a vendor's own fit.

"known_source_errors" maps a check name to a note for a published value that
the source's own inputs contradict. Such a check is reported as
"source_error" and does not gate the case; the value is never edited.

Completeness:
- "complete": every input the method needs is known; outputs are gated.
- "partial": inputs are missing; outputs are compared for information only.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

import numpy as np

from proflow.engine import channel
from proflow.engine import unit_hydrograph as uh
from proflow.engine.idf import FhaCurve, fit_fha_report
from proflow.engine.rainfall import MassCurve
from proflow.engine.rational import peak_flow, standard_rational
from proflow.engine.result import SolveResult, Status
from proflow.engine.scs import excess_increments, runoff_depth
from proflow.engine.sewer import Line, line_hydraulics
from proflow.engine.storm_library import STANDARD_DISTRIBUTIONS
from proflow.engine.weir import rectangular_depth
from proflow.io.units import UnitError, from_internal, to_internal

SCHEMA = "proflow-fixture/1"
COMPLETENESS = ("complete", "partial")
FIXTURE_DIR = Path(__file__).resolve().parents[2] / "fixtures"


class FixtureError(ValueError):
    pass


# --- Methods a fixture can name ----------------------------------------------
# Each takes internal-unit inputs and returns a SolveResult whose value maps
# output names to internal-unit numbers or arrays.

Outputs = dict[str, float | np.ndarray]


@dataclass(frozen=True)
class Method:
    inputs: dict[str, str | None]  # name -> quantity kind, None if categorical
    outputs: dict[str, str]
    run: Callable[[dict], SolveResult[Outputs]]
    optional: frozenset[str] = frozenset()  # inputs a complete case may omit


def _express_weir_known_q(x: dict) -> SolveResult[Outputs]:
    if x["crest"] != "sharp":
        return SolveResult(Status.UNSUPPORTED_REGIME, "weir.rectangular/1")
    r = rectangular_depth(x["crest_length"], x["flow"], x["cw"], x["total_depth"])
    if not r.ok:
        return SolveResult(r.status, r.method, message=r.message)
    s = r.value
    values = {
        "depth": s.depth,
        "flow": s.flow,
        "area": s.area,
        "velocity": s.velocity,
        "top_width": s.top_width,
    }
    return SolveResult(Status.SUCCESS, r.method, values)


def _hydrographs_rational_user_intensity(x: dict) -> SolveResult[Outputs]:
    r = standard_rational(
        x["c"],
        x["area"],
        x["tc"],
        FhaCurve(b=x["intensity"], d=0.0, e=0.0),
        receding_limb_factor=x["receding_limb_factor"],
        dt=x["time_step"],
        ascending_limb_factor=x["ascending_limb_factor"],
    )
    if not r.ok:
        return SolveResult(r.status, r.method, message=r.message)
    hyd = r.value
    values = {"peak": hyd.peak, "time_to_peak": hyd.time_to_peak, "volume": hyd.volume}
    return SolveResult(Status.SUCCESS, r.method, values, warnings=r.warnings)


def _storm_rational_line_flow(x: dict) -> SolveResult[Outputs]:
    intensity = FhaCurve(x["idf_b"], x["idf_d"], x["idf_e"]).intensity(x["tc"])
    flow = peak_flow(x["c"], intensity, x["area"])
    return SolveResult(
        Status.SUCCESS, "rational.peak/1", {"intensity": intensity, "flow": flow}
    )


def _storm_line_hgl(x: dict) -> SolveResult[Outputs]:
    line = Line(x["diameter"], x["length"], x["invert_up"], x["invert_down"], x["n"])
    r = line_hydraulics(
        line,
        x["flow"],
        x["tailwater"],
        x.get("tailwater_elevation"),
        x.get("junction_k", 1.0),
    )
    if not r.ok:
        return SolveResult(r.status, r.method, message=r.message)
    h = r.value
    values = {
        "full_capacity": h.capacity,
        "hgl_down": h.down.hgl,
        "hgl_up": h.up.hgl,
        "velocity_average": (h.down.velocity + h.up.velocity) / 2,
        "critical_depth": h.critical_depth,
    }
    return SolveResult(Status.SUCCESS, r.method, values, warnings=r.warnings)


def _scs_excess_mass_curve(x: dict) -> SolveResult[Outputs]:
    storm = MassCurve.from_table(x["times"], x["fractions"])
    precip = storm.cumulative_depths(x["total_depth"], x["time_step"])
    values = {
        "cumulative_precip": precip,
        "cumulative_runoff": np.asarray(runoff_depth(precip, x["cn"])),
        "incremental_runoff": excess_increments(precip, x["cn"]),
    }
    return SolveResult(Status.SUCCESS, "scs.excess/1", values)


def _nrcs_uh_peak(x: dict) -> SolveResult[Outputs]:
    equations = {"16A-7": uh.tp_from_lag, "16A-10": uh.tp_from_inflection}
    tp = equations[x["tp_equation"]](x["tc"], x["time_step"])
    values = {"tp": tp, "qp": uh.peak_rate(x["area"], tp)}
    return SolveResult(Status.SUCCESS, f"nrcs.uh.tp.{x['tp_equation']}/1", values)


def _nrcs_uh_curvilinear(x: dict) -> SolveResult[Outputs]:
    ordinates = uh.curvilinear(x["area"], x["tp"], x["time_step"])
    values = {"qp": uh.peak_rate(x["area"], x["tp"]), "ordinates": ordinates}
    return SolveResult(Status.SUCCESS, "scs.uh.curvilinear/1", values)


def _idf_fha_evaluate(x: dict) -> SolveResult[Outputs]:
    curve = FhaCurve(x["b"], x["d"], x["e"])
    values = {"intensities": np.atleast_1d(curve.intensity(x["durations"]))}
    return SolveResult(Status.SUCCESS, "idf.fha/1", values)


def _idf_fha_fit(x: dict) -> SolveResult[Outputs]:
    r = fit_fha_report(x["durations"], x["intensities"])
    if not r.ok:
        return SolveResult(r.status, r.method, message=r.message)
    c = r.value.curve
    values = {"fitted": r.value.fitted, "b": c.b, "d": c.d, "e": c.e}
    return SolveResult(Status.SUCCESS, r.method, values, warnings=r.warnings)


def _storm_standard_mass_curve(x: dict) -> SolveResult[Outputs]:
    dist = STANDARD_DISTRIBUTIONS.get(x["distribution"])
    if dist is None:
        return SolveResult(
            Status.INVALID_INPUT, "storm.standard/1", message="unknown distribution"
        )
    curve = dist.mass_curve(x["duration"])
    values = {"fractions": np.atleast_1d(curve.fraction(x["times"]))}
    return SolveResult(Status.SUCCESS, f"storm.standard.{dist.id}", values)


_CHANNEL_OUTPUTS = {
    "depth": "length",
    "flow": "flow",
    "area": "area",
    "velocity": "velocity",
    "wetted_perimeter": "length",
    "critical_depth": "length",
    "top_width": "length",
    "egl": "length",
}
_CHANNEL_INPUTS = {
    "section": None,
    "bottom_width": "length",
    "left_slope": "dimensionless",
    "right_slope": "dimensionless",
    "diameter": "length",
    "cross_slope": "slope",
    "gutter_slope": "slope",
    "gutter_width": "length",
    "total_depth": "length",
    "slope": "slope",
    "n": "dimensionless",
}
_CHANNEL_OPTIONAL = frozenset(
    {
        "bottom_width",
        "left_slope",
        "right_slope",
        "diameter",
        "cross_slope",
        "gutter_slope",
        "gutter_width",
        "total_depth",
    }
)


def _section(x: dict) -> channel.Section:
    kind = x["section"]
    if kind == "circular":
        return channel.Circular(x["diameter"])
    if kind == "gutter":
        return channel.Gutter(x["cross_slope"], x["gutter_slope"], x["gutter_width"])
    b = x.get("bottom_width", 0.0)
    z1, z2 = x.get("left_slope", 0.0), x.get("right_slope", 0.0)
    expected = {"rectangular": z1 == z2 == 0, "triangular": b == 0}
    if not expected.get(kind, True):
        raise ValueError(f"inputs do not describe a {kind} section")
    return channel.Trapezoid(b, z1, z2)


def _channel_values(r) -> SolveResult[Outputs]:
    if not r.ok:
        return SolveResult(r.status, r.method, message=r.message)
    s = r.value
    return SolveResult(
        Status.SUCCESS, r.method, {k: getattr(s, k) for k in _CHANNEL_OUTPUTS}
    )


def _express_channel_known_q(x: dict) -> SolveResult[Outputs]:
    step = x.get("depth_step")
    return _channel_values(
        channel.normal_depth(
            _section(x), x["known_q"], x["slope"], x["n"], x.get("total_depth"), step
        )
    )


def _express_channel_known_depth(x: dict) -> SolveResult[Outputs]:
    return _channel_values(
        channel.flow_at_depth(
            _section(x),
            x["known_depth"],
            x["slope"],
            x["n"],
            x.get("total_depth"),
            x.get("depth_step"),
        )
    )


def _express_channel_rating_row(x: dict) -> SolveResult[Outputs]:
    r = channel.rating(
        _section(x),
        x.get("total_depth"),
        int(x["increments"]),
        x["slope"],
        x["n"],
        x.get("depth_step"),
    )
    if not r.ok:
        return SolveResult(r.status, r.method, message=r.message)
    row = r.value[int(x["row"]) - 1]
    return SolveResult(
        Status.SUCCESS, r.method, {k: getattr(row, k) for k in _CHANNEL_OUTPUTS}
    )


def _uh_convolve(x: dict) -> SolveResult[Outputs]:
    flows = np.append(uh.convolve(x["excess"], x["unit_hydrograph"]), 0.0)
    return SolveResult(Status.SUCCESS, "uh.convolve/1", {"flows": flows})


METHODS: dict[str, Method] = {
    "express.weir.rectangular.known_q": Method(
        inputs={
            "crest": None,
            "crest_length": "length",
            "total_depth": "length",
            "cw": "dimensionless",
            "flow": "flow",
        },
        outputs={
            "depth": "length",
            "flow": "flow",
            "area": "area",
            "velocity": "velocity",
            "top_width": "length",
        },
        run=_express_weir_known_q,
    ),
    "hydrographs.rational.user_intensity": Method(
        inputs={
            "area": "drainage_area",
            "c": "dimensionless",
            "tc": "time",
            "intensity": "intensity",
            "time_step": "time",
            "ascending_limb_factor": "dimensionless",
            "receding_limb_factor": "dimensionless",
        },
        outputs={"peak": "flow", "time_to_peak": "time", "volume": "volume"},
        run=_hydrographs_rational_user_intensity,
    ),
    "storm.rational.line_flow": Method(
        inputs={
            "area": "drainage_area",
            "c": "dimensionless",
            "tc": "time",
            "idf_b": "dimensionless",
            "idf_d": "dimensionless",
            "idf_e": "dimensionless",
        },
        outputs={"intensity": "intensity", "flow": "flow"},
        run=_storm_rational_line_flow,
    ),
    "storm.line_hgl": Method(
        inputs={
            "flow": "flow",
            "length": "length",
            "diameter": "length",
            "invert_up": "length",
            "invert_down": "length",
            "n": "dimensionless",
            "tailwater": None,
            "tailwater_elevation": "length",
            "junction_k": "dimensionless",
        },
        outputs={
            "full_capacity": "flow",
            "hgl_down": "length",
            "hgl_up": "length",
            "velocity_average": "velocity",
            "critical_depth": "length",
        },
        run=_storm_line_hgl,
        optional=frozenset({"tailwater_elevation", "junction_k"}),
    ),
    "nrcs.scs.excess.mass_curve": Method(
        inputs={
            "times": "time",
            "fractions": "dimensionless",
            "total_depth": "depth",
            "cn": "dimensionless",
            "time_step": "time",
        },
        outputs={
            "cumulative_precip": "depth",
            "cumulative_runoff": "depth",
            "incremental_runoff": "depth",
        },
        run=_scs_excess_mass_curve,
    ),
    "nrcs.uh.peak": Method(
        inputs={
            "area": "drainage_area",
            "tc": "time",
            "time_step": "time",
            "tp_equation": None,
        },
        outputs={"tp": "time", "qp": "flow"},
        run=_nrcs_uh_peak,
    ),
    "nrcs.uh.curvilinear": Method(
        inputs={"area": "drainage_area", "tp": "time", "time_step": "time"},
        outputs={"qp": "flow", "ordinates": "flow"},
        run=_nrcs_uh_curvilinear,
    ),
    "idf.fha.evaluate": Method(
        inputs={
            "b": "dimensionless",
            "d": "dimensionless",
            "e": "dimensionless",
            "durations": "time",
        },
        outputs={"intensities": "intensity"},
        run=_idf_fha_evaluate,
    ),
    "idf.fha.fit": Method(
        inputs={"durations": "time", "intensities": "intensity"},
        outputs={
            "fitted": "intensity",
            "b": "dimensionless",
            "d": "dimensionless",
            "e": "dimensionless",
        },
        run=_idf_fha_fit,
    ),
    "storm.standard.mass_curve": Method(
        inputs={"distribution": None, "duration": "time", "times": "time"},
        outputs={"fractions": "dimensionless"},
        run=_storm_standard_mass_curve,
    ),
    "express.channel.known_q": Method(
        inputs={**_CHANNEL_INPUTS, "known_q": "flow", "depth_step": "length"},
        outputs=_CHANNEL_OUTPUTS,
        run=_express_channel_known_q,
        optional=_CHANNEL_OPTIONAL | {"depth_step"},
    ),
    "express.channel.known_depth": Method(
        inputs={**_CHANNEL_INPUTS, "known_depth": "length", "depth_step": "length"},
        outputs=_CHANNEL_OUTPUTS,
        run=_express_channel_known_depth,
        optional=_CHANNEL_OPTIONAL | {"depth_step"},
    ),
    "express.channel.rating_row": Method(
        inputs={
            **_CHANNEL_INPUTS,
            "increments": "dimensionless",
            "row": "dimensionless",
            "depth_step": "length",
        },
        outputs=_CHANNEL_OUTPUTS,
        run=_express_channel_rating_row,
        optional=_CHANNEL_OPTIONAL | {"depth_step"},
    ),
    "uh.convolve": Method(
        inputs={"excess": "depth", "unit_hydrograph": "flow"},
        outputs={"flows": "flow"},
        run=_uh_convolve,
    ),
}


# --- Fixture data ------------------------------------------------------------


@dataclass(frozen=True)
class Expected:
    output: str  # method output name
    index: int | None  # element of a series output, else None
    text: str  # as displayed by the source, e.g. "1.45"
    unit: str
    tolerance: float  # in `unit`
    gated: bool = True

    @property
    def name(self) -> str:
        return self.output if self.index is None else f"{self.output}[{self.index}]"

    @property
    def value(self) -> float:
        return float(self.text)


@dataclass(frozen=True)
class Fixture:
    id: str
    product: str
    product_version: str | None
    completeness: str
    method: str
    source: dict
    inputs: dict
    expected: tuple[Expected, ...]
    missing: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()
    known_source_errors: dict[str, str] = field(default_factory=dict)
    notes: str = ""
    path: Path | None = None


def displayed_tolerance(text: str) -> float:
    """Half a unit in the last displayed place: "1.45" -> 0.005, "9884" -> 0.5."""
    exponent = Decimal(text).as_tuple().exponent
    return 0.5 * 10.0 ** int(exponent)


def _expected(name: str, entry: dict, where: str) -> list[Expected]:
    unit, tol, gated = entry["unit"], entry.get("tolerance"), entry.get("gate", True)
    if "values" in entry:
        texts, start = entry["values"], entry.get("start", 0)
        indices = range(start, start + len(texts))
    else:
        texts, indices = [entry["value"]], [None]
    out = []
    for i, text in zip(indices, texts, strict=True):
        if not isinstance(text, str):
            raise FixtureError(f"{where}: expected.{name} must be strings as shown")
        out.append(
            Expected(
                name,
                i,
                text,
                unit,
                displayed_tolerance(text) if tol is None else tol,
                gated,
            )
        )
    return out


def load_fixture(path: Path) -> Fixture:
    data = json.loads(path.read_text(encoding="utf-8"))
    where = path.name
    if data.get("schema") != SCHEMA:
        raise FixtureError(f"{where}: schema must be {SCHEMA!r}")
    if data.get("completeness") not in COMPLETENESS:
        raise FixtureError(f"{where}: completeness must be one of {COMPLETENESS}")
    if data.get("method") not in METHODS:
        raise FixtureError(f"{where}: unknown method {data.get('method')!r}")
    method = METHODS[data["method"]]
    inputs = data.get("inputs", {})
    absent = set(method.inputs) - set(inputs) - method.optional
    if absent and data["completeness"] == "complete":
        raise FixtureError(f"{where}: complete case lacks inputs {sorted(absent)}")
    expected = []
    for name, entry in data.get("expected", {}).items():
        # A partial case may record outputs for a solver that does not exist yet.
        if name not in method.outputs and data["completeness"] == "complete":
            raise FixtureError(f"{where}: {data['method']} has no output {name!r}")
        expected += _expected(name, entry, where)
    known = data.get("known_source_errors", {})
    unknown = set(known) - {e.name for e in expected}
    if unknown:
        raise FixtureError(f"{where}: known_source_errors names {sorted(unknown)}")
    return Fixture(
        id=data["id"],
        product=data["product"],
        product_version=data.get("product_version"),
        completeness=data["completeness"],
        method=data["method"],
        source=data["source"],
        inputs=inputs,
        expected=tuple(expected),
        missing=tuple(data.get("missing", ())),
        assumptions=tuple(data.get("assumptions", ())),
        known_source_errors=known,
        notes=data.get("notes", ""),
        path=path,
    )


def discover(directory: Path = FIXTURE_DIR) -> list[Fixture]:
    return [load_fixture(p) for p in sorted(directory.rglob("*.json"))]


# --- Running -----------------------------------------------------------------


@dataclass(frozen=True)
class Check:
    expected: Expected
    computed: float | None
    status: str  # pass | fail | info | not_computed | source_error

    @property
    def name(self) -> str:
        return self.expected.name

    @property
    def unit(self) -> str:
        return self.expected.unit


@dataclass(frozen=True)
class CaseResult:
    fixture: Fixture
    status: str  # pass | fail | informational | error
    method_id: str = ""
    message: str = ""
    checks: list[Check] = field(default_factory=list)


def _internal_inputs(fixture: Fixture) -> dict:
    method = METHODS[fixture.method]
    values = {}
    for name, kind in method.inputs.items():
        if name not in fixture.inputs:
            continue
        entry = fixture.inputs[name]
        if kind is None:
            values[name] = entry
        elif "values" in entry:
            values[name] = np.array(
                [to_internal(kind, v, entry["unit"]) for v in entry["values"]]
            )
        else:
            values[name] = to_internal(kind, entry["value"], entry["unit"])
    return values


def _computed(values: Outputs, exp: Expected) -> float | None:
    if exp.output not in values:
        return None
    value = values[exp.output]
    if exp.index is None:
        return float(value)
    return float(value[exp.index]) if exp.index < len(value) else None


def run_fixture(fixture: Fixture) -> CaseResult:
    method = METHODS[fixture.method]
    gated = fixture.completeness == "complete"
    if set(method.inputs) - set(fixture.inputs) - method.optional:
        values: Outputs = {}
        method_id, message = "", "inputs missing; nothing computed"
    else:
        try:
            result = method.run(_internal_inputs(fixture))
        except (UnitError, ValueError) as exc:
            return CaseResult(fixture, "error", message=str(exc))
        if not result.ok:
            return CaseResult(
                fixture, "error", result.method, f"{result.status}: {result.message}"
            )
        values, method_id, message = result.value, result.method, ""

    checks = []
    for exp in fixture.expected:
        raw = _computed(values, exp)
        if raw is None:
            checks.append(Check(exp, None, "not_computed"))
            continue
        computed = from_internal(method.outputs[exp.output], raw, exp.unit)
        close = abs(computed - exp.value) <= exp.tolerance * (1 + 1e-9)
        if exp.name in fixture.known_source_errors:
            status = "source_error"
        elif not gated or not exp.gated:
            status = "info"
        else:
            status = "pass" if close else "fail"
        checks.append(Check(exp, computed, status))

    if not gated:
        case_status = "informational"
    elif all(c.status in ("pass", "source_error", "info") for c in checks):
        case_status = "pass"
    else:
        case_status = "fail"
    return CaseResult(fixture, case_status, method_id, message, checks)


def _check_line(c: Check) -> str:
    got = "—" if c.computed is None else f"{c.computed:.6g}"
    tol = f"±{c.expected.tolerance:g}"
    return (
        f"    {c.name:<22} expected {c.expected.text:>9} {tol:<8}"
        f" {c.unit:<6} computed {got:>10}  {c.status}"
    )


def format_results(results: list[CaseResult]) -> str:
    lines = []
    for r in results:
        f = r.fixture
        version = f" {f.product_version}" if f.product_version else ""
        lines.append(
            f"[{r.status.upper()}] {f.id} ({f.product}{version}, {f.completeness})"
        )
        if r.method_id:
            lines.append(f"    method {r.method_id} (experimental)")
        if r.message:
            lines.append(f"    {r.message}")
        series: dict[str, list[Check]] = {}
        for c in r.checks:
            if c.expected.index is None:
                lines.append(_check_line(c))
            else:
                series.setdefault(c.expected.output, []).append(c)
        for name, checks in series.items():
            passed = sum(c.status in ("pass", "info") for c in checks)
            diffs = [
                abs(c.computed - c.expected.value)
                for c in checks
                if c.computed is not None and c.status != "source_error"
            ]
            worst = f", max |diff| {max(diffs):.4g} {checks[0].unit}" if diffs else ""
            lines.append(f"    {name}: {passed}/{len(checks)} within tolerance{worst}")
            lines += [
                _check_line(c) for c in checks if c.status not in ("pass", "info")
            ]
        for name, note in f.known_source_errors.items():
            lines.append(f"    source error {name}: {note}")
        for m in f.missing:
            lines.append(f"    missing: {m}")
    passed = sum(r.status == "pass" for r in results)
    complete = sum(r.fixture.completeness == "complete" for r in results)
    lines.append(f"{passed}/{complete} complete cases pass; {len(results)} total")
    return "\n".join(lines)


def failed(results: list[CaseResult]) -> bool:
    """True if any complete case failed or any case errored."""
    return any(r.status in ("fail", "error") for r in results)
