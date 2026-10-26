"""Express calculator inputs and calculations, independent of any UI.

The desktop form, the CLI and the printable report all go through
calculate_channel / calculate_weir, so they show the same numbers, method
ids, warnings and depth-reporting notes. Values are US customary: lengths ft,
flow cfs, slope in percent (as Express takes it).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from proflow.engine import channel, weir
from proflow.engine.channel import FlowState, Trapezoid
from proflow.engine.result import SolveResult, Status
from proflow.engine.weir import WeirSection

SECTIONS = ("rectangular", "triangular", "trapezoidal")
COMPUTE_BY = ("known_q", "known_depth", "rating")
COMPUTE_LABELS = {
    "known_q": "Known Q",
    "known_depth": "Known depth",
    "rating": "Q vs. depth",
}
DEPTH_REPORTING = ("exact", "express_stepped")
EXPRESS_STEP_FT = 0.01

METHOD_STATUS = "Experimental: not validated for engineering use"

DEPTH_LABELS = {
    "exact": "Exact: normal and critical depths as solved",
    "express_stepped": (
        "Express stepped: iterated depths rounded up to the next 0.01 ft, as "
        "published Hydraflow Express channel reports show"
    ),
}
WEIR_DEPTH_LABEL = (
    "Exact: head from Q = Cw L H^1.5 in closed form (the published Express weir "
    "report agrees with the exact head)"
)


@dataclass(frozen=True)
class ChannelInputs:
    title: str = ""
    section: str = "trapezoidal"
    bottom_width: float = 0.0  # ft
    left_slope: float = 0.0  # z (H:1V)
    right_slope: float = 0.0
    total_depth: float = 1.0  # ft
    invert_elevation: float = 0.0  # ft
    slope_percent: float = 1.0  # %
    n: float = 0.030
    compute_by: str = "known_q"
    known_q: float = 0.0  # cfs
    known_depth: float = 0.0  # ft
    increments: int = 10
    depth_reporting: str = "exact"

    def shape(self) -> Trapezoid:
        if self.section == "rectangular":
            return Trapezoid(self.bottom_width, 0.0, 0.0)
        if self.section == "triangular":
            return Trapezoid(0.0, self.left_slope, self.right_slope)
        return Trapezoid(self.bottom_width, self.left_slope, self.right_slope)


@dataclass(frozen=True)
class WeirInputs:
    title: str = ""
    crest: str = "sharp"  # "sharp" or "broad"
    bottom_length: float = 1.0  # ft
    total_depth: float = 1.0  # ft
    cw: float | None = None  # None: Express default for the crest
    compute_by: str = "known_q"
    known_q: float = 0.0
    known_depth: float = 0.0
    increments: int = 10

    @property
    def weir_coefficient(self) -> float:
        return weir.DEFAULT_CW[self.crest] if self.cw is None else self.cw


@dataclass(frozen=True)
class Calculation:
    kind: str  # "channel" or "weir"
    inputs: ChannelInputs | WeirInputs
    status: Status
    method: str
    message: str = ""
    rows: tuple[FlowState | WeirSection, ...] = ()
    highlighted: int = -1  # index into rows of the reported state
    warnings: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    depth_reporting: str = ""
    diagnostics: dict[str, float] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status is Status.SUCCESS

    @property
    def state(self) -> FlowState | WeirSection | None:
        return self.rows[self.highlighted] if self.ok and self.rows else None


def _from(kind, inputs, r: SolveResult, depth_reporting, notes=(), warnings=()):
    if not r.ok:
        return Calculation(
            kind,
            inputs,
            r.status,
            r.method,
            r.message,
            depth_reporting=depth_reporting,
            notes=tuple(notes),
            warnings=tuple(warnings) + r.warnings,
            diagnostics=dict(r.diagnostics),
        )
    rows = tuple(r.value) if isinstance(r.value, list) else (r.value,)
    return Calculation(
        kind,
        inputs,
        r.status,
        r.method,
        rows=rows,
        highlighted=len(rows) - 1,
        warnings=tuple(warnings) + r.warnings,
        notes=tuple(notes),
        depth_reporting=depth_reporting,
        diagnostics=dict(r.diagnostics),
    )


def _bad(kind, inputs, method, message, depth_reporting) -> Calculation:
    return Calculation(
        kind,
        inputs,
        Status.INVALID_INPUT,
        method,
        message,
        depth_reporting=depth_reporting,
    )


def calculate_channel(x: ChannelInputs) -> Calculation:
    label = DEPTH_LABELS.get(x.depth_reporting, "")
    if x.section not in SECTIONS:
        return _bad("channel", x, "", f"unknown section {x.section!r}", label)
    if x.compute_by not in COMPUTE_BY:
        return _bad("channel", x, "", f"unknown mode {x.compute_by!r}", label)
    if x.depth_reporting not in DEPTH_REPORTING:
        return _bad(
            "channel", x, "", f"unknown depth reporting {x.depth_reporting!r}", label
        )
    step = EXPRESS_STEP_FT if x.depth_reporting == "express_stepped" else None
    shape, s = x.shape(), x.slope_percent / 100
    if x.compute_by == "known_q":
        r = channel.normal_depth(shape, x.known_q, s, x.n, x.total_depth, step)
    elif x.compute_by == "known_depth":
        r = channel.flow_at_depth(shape, x.known_depth, s, x.n, x.total_depth, step)
    else:
        r = channel.rating(shape, x.total_depth, x.increments, s, x.n, step)
    notes = []
    if step and r.ok and "exact_depth_ft" in r.diagnostics:
        exact = r.diagnostics["exact_depth_ft"]
        notes.append(f"Exact normal depth {exact:.4f} ft; reported rounded up.")
    return _from("channel", x, r, label, notes)


def calculate_weir(x: WeirInputs) -> Calculation:
    if x.crest not in weir.DEFAULT_CW:
        return _bad(
            "weir", x, weir.METHOD, f"unknown crest {x.crest!r}", WEIR_DEPTH_LABEL
        )
    if x.compute_by not in COMPUTE_BY:
        return _bad(
            "weir", x, weir.METHOD, f"unknown mode {x.compute_by!r}", WEIR_DEPTH_LABEL
        )
    cw = x.weir_coefficient
    if x.compute_by == "known_q":
        r = weir.rectangular_depth(x.bottom_length, x.known_q, cw, x.total_depth)
    elif x.compute_by == "known_depth":
        r = weir.rectangular_flow(x.bottom_length, x.known_depth, cw, x.total_depth)
    else:
        r = weir.rectangular_rating(x.bottom_length, cw, x.total_depth, x.increments)
    default = weir.DEFAULT_CW[x.crest]
    warnings = []
    if x.cw is not None and x.cw != default:
        warnings.append(
            f"Weir coefficient overridden: Cw = {cw:g} (Express default for a "
            f"{x.crest} crest is {default:g})"
        )
    notes = [
        f"Cw = {cw:g} ({'user' if x.cw is not None else 'default'}, {x.crest} crest)"
    ]
    return _from("weir", x, r, WEIR_DEPTH_LABEL, notes, warnings)
