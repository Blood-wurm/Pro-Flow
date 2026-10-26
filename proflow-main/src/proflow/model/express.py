"""Express calculator inputs and calculations, independent of any UI.

The desktop form, the CLI and the printable report all go through
calculate_channel / calculate_weir, so they show the same numbers, method
ids, warnings and depth-reporting notes. Values are US customary: lengths ft,
flow cfs, slope in percent (as Express takes it).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from proflow.engine import channel, weir
from proflow.engine.channel import FlowState
from proflow.engine.result import SolveResult, Status
from proflow.engine.sections import Circular, Gutter, StationElevation, Trapezoid
from proflow.engine.weir import WeirSection

SECTIONS = ("rectangular", "triangular", "trapezoidal", "circular", "gutter", "user")
SECTION_LABELS = {
    "rectangular": "Rectangular",
    "triangular": "Triangular",
    "trapezoidal": "Trapezoidal",
    "circular": "Circular (pipe)",
    "gutter": "Gutter",
    "user": "User-defined",
}
WEIR_TYPES = (
    "rectangular",
    "compound",
    "circular",
    "v_notch",
    "trapezoidal",
    "proportional",
)
WEIR_LABELS = {
    "rectangular": "Rectangular",
    "compound": "Compound (two-stage)",
    "circular": "Circular",
    "v_notch": "V-notch",
    "trapezoidal": "Trapezoidal (Cipoletti)",
    "proportional": "Proportional (Sutro)",
}
BROAD_CREST_TYPES = ("rectangular", "compound")  # Express: others sharp only
CW_OVERRIDE_TYPES = ("rectangular", "compound", "circular")

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
    "Exact: head solved directly (published Express weir reports print the exact head)"
)

# What each calculation rests on; shown with every result and in the report.
SECTION_EVIDENCE = {
    "rectangular": "Manning; reproduces published Express channel reports.",
    "triangular": "Manning; reproduces published Express channel reports.",
    "trapezoidal": "Manning; reproduces published Express channel reports.",
    "circular": (
        "Manning on pipe geometry. Geometry and critical depth match three "
        "published Express pipe reports, but Express carries 2.5 to 6 % less flow "
        "at a given depth than Manning's equation; the difference is unexplained."
    ),
    "gutter": (
        "Gutter equation as the Express manual gives it (HEC-22 form, Kc = 0.56). "
        "Geometry and critical depth match three published Express gutter "
        "reports, but Express carries 0.6 to 2.7 % less flow at a given depth; "
        "the difference is unexplained."
    ),
    "user": (
        "Manning with composite n (HEC-RAS eq. 2-6, as the Express manual cites). "
        "No published Express case checks it yet."
    ),
}
WEIR_EVIDENCE = {
    "rectangular": "Q = Cw L H^1.5; reproduces three published Express weir reports.",
    "compound": (
        "Rectangular equation on a lower notch plus the full-width weir above it "
        "(Pro-Flow's reading; the manual does not spell out the split). No "
        "published Express case."
    ),
    "circular": (
        "Q = Cw A H^0.5 as the Express manual prints it. No published Express case."
    ),
    "v_notch": (
        "Q = Cw H^2.5, Cw = 2.54 tan(angle/2), as the Express manual prints it. "
        "No published Express case."
    ),
    "trapezoidal": (
        "Q = 3.1 (B + 0.8 H z) H^1.5 as the Express manual prints it. "
        "No published Express case."
    ),
    "proportional": (
        "Q = 4.96 a^0.5 B (H - a/3) as the Express manual prints it, for heads "
        "from a up. No published Express case."
    ),
}

_TRAPEZOID_EXAMPLE_POINTS = (
    (0.0, 3.0, 0.0),
    (6.0, 0.0, 0.035),
    (11.0, 0.0, 0.035),
    (20.0, 3.0, 0.035),
)


@dataclass(frozen=True)
class ChannelInputs:
    title: str = ""
    section: str = "trapezoidal"
    bottom_width: float = 0.0  # ft
    left_slope: float = 0.0  # z (H:1V)
    right_slope: float = 0.0
    diameter: float = 1.5  # ft, circular
    cross_slope: float = 0.02  # Sx ft/ft, gutter
    gutter_slope: float = 0.08  # Sw ft/ft, gutter
    gutter_width: float = 2.0  # ft, gutter
    points: tuple[tuple[float, float, float], ...] = _TRAPEZOID_EXAMPLE_POINTS  # user
    total_depth: float = 1.0  # ft (trapezoids; gutter Q vs. depth range)
    invert_elevation: float = 0.0  # ft
    slope_percent: float = 1.0  # %
    n: float = 0.030
    compute_by: str = "known_q"
    known_q: float = 0.0  # cfs
    known_depth: float = 0.0  # ft
    increments: int = 10
    depth_reporting: str = "exact"

    def shape(self) -> channel.Section:
        if self.section == "rectangular":
            return Trapezoid(self.bottom_width, 0.0, 0.0)
        if self.section == "triangular":
            return Trapezoid(0.0, self.left_slope, self.right_slope)
        if self.section == "circular":
            return Circular(self.diameter)
        if self.section == "gutter":
            return Gutter(self.cross_slope, self.gutter_slope, self.gutter_width)
        if self.section == "user":
            return StationElevation.from_points(self.points)
        return Trapezoid(self.bottom_width, self.left_slope, self.right_slope)

    @property
    def invert(self) -> float:
        """Invert elevation; a user-defined section takes it from its points."""
        if self.section == "user" and self.points:
            return min(p[1] for p in self.points)
        return self.invert_elevation

    def depth_limit(self) -> float | None:
        """Total depth passed to the solver for this section and mode."""
        if self.section in ("circular", "user"):
            return None  # the section's own limit
        if self.section == "gutter":
            return self.total_depth if self.compute_by == "rating" else None
        return self.total_depth


@dataclass(frozen=True)
class WeirInputs:
    title: str = ""
    weir_type: str = "rectangular"
    crest: str = "sharp"  # "sharp" or "broad"
    bottom_length: float = 1.0  # ft, L (rectangular, compound, Sutro) or B
    total_depth: float = 1.0  # ft
    cw: float | None = None  # None: Express default for the crest
    notch_length: float = 0.5  # ft, x (compound)
    notch_depth: float = 0.5  # ft, a (compound, proportional)
    diameter: float = 1.0  # ft (circular)
    angle: float = 90.0  # degrees (V-notch)
    side_slope: float = 4.0  # z (trapezoidal / Cipoletti)
    compute_by: str = "known_q"
    known_q: float = 0.0
    known_depth: float = 0.0
    increments: int = 10

    @property
    def weir_coefficient(self) -> float:
        if self.weir_type in CW_OVERRIDE_TYPES:
            return weir.DEFAULT_CW[self.crest] if self.cw is None else self.cw
        return self.shape().cw

    def shape(self) -> weir.Shape:
        t = self.weir_type
        cw = (
            (weir.DEFAULT_CW[self.crest] if self.cw is None else self.cw)
            if t in CW_OVERRIDE_TYPES
            else None
        )
        if t == "compound":
            return weir.Compound(
                self.bottom_length, self.notch_length, self.notch_depth, cw
            )
        if t == "circular":
            return weir.CircularWeir(self.diameter, cw)
        if t == "v_notch":
            return weir.VNotch(self.angle)
        if t == "trapezoidal":
            return weir.Cipoletti(self.bottom_length, self.side_slope)
        if t == "proportional":
            return weir.Sutro(self.bottom_length, self.notch_depth)
        return weir.Rectangular(self.bottom_length, cw)


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
    shape, s, limit = x.shape(), x.slope_percent / 100, x.depth_limit()
    if x.compute_by == "known_q":
        r = channel.normal_depth(shape, x.known_q, s, x.n, limit, step)
    elif x.compute_by == "known_depth":
        r = channel.flow_at_depth(shape, x.known_depth, s, x.n, limit, step)
    else:
        r = channel.rating(shape, limit, x.increments, s, x.n, step)
    notes = [SECTION_EVIDENCE[x.section]]
    if step and r.ok and "exact_depth_ft" in r.diagnostics:
        exact = r.diagnostics["exact_depth_ft"]
        if shape.steps_normal_depth:
            notes.append(f"Exact normal depth {exact:.4f} ft; reported rounded up.")
        else:
            notes.append(
                f"Normal depth {exact:.4f} ft reported exact for this section, as "
                "published Express reports show; critical depth rounded up."
            )
    if x.section == "user":
        notes.append(f"Invert elevation {x.invert:g} ft taken from the lowest point.")
    return _from("channel", x, r, label, notes)


def calculate_weir(x: WeirInputs) -> Calculation:
    method = f"weir.{x.weir_type}/1"
    if x.weir_type not in WEIR_TYPES:
        return _bad(
            "weir", x, method, f"unknown weir type {x.weir_type!r}", WEIR_DEPTH_LABEL
        )
    if x.crest not in weir.DEFAULT_CW:
        return _bad("weir", x, method, f"unknown crest {x.crest!r}", WEIR_DEPTH_LABEL)
    if x.crest == "broad" and x.weir_type not in BROAD_CREST_TYPES:
        return _bad(
            "weir", x, method,
            f"{WEIR_LABELS[x.weir_type]} weirs are sharp crested only in Express",
            WEIR_DEPTH_LABEL,
        )  # fmt: skip
    if x.compute_by not in COMPUTE_BY:
        return _bad(
            "weir", x, method, f"unknown mode {x.compute_by!r}", WEIR_DEPTH_LABEL
        )
    shape = x.shape()
    if x.compute_by == "known_q":
        r = weir.head_for_flow(shape, x.known_q, x.total_depth)
    elif x.compute_by == "known_depth":
        r = weir.flow_at_head(shape, x.known_depth, x.total_depth)
    else:
        r = weir.weir_rating(shape, x.total_depth, x.increments)
    warnings = []
    notes = [WEIR_EVIDENCE[x.weir_type]]
    if x.weir_type in CW_OVERRIDE_TYPES:
        default = weir.DEFAULT_CW[x.crest]
        cw = x.weir_coefficient
        if x.cw is not None and x.cw != default:
            warnings.append(
                f"Weir coefficient overridden: Cw = {cw:g} (Express default for a "
                f"{x.crest} crest is {default:g})"
            )
        source = "user" if x.cw is not None else "default"
        notes.append(f"Cw = {cw:g} ({source}, {x.crest} crest)")
    elif x.weir_type == "v_notch":
        notes.append(f"Cw = 2.54 tan({x.angle:g}/2) = {shape.cw:.4f}")
    return _from("weir", x, r, WEIR_DEPTH_LABEL, notes, warnings)
