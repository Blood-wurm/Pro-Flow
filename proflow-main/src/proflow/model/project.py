"""Native Pro-Flow project model, schema "proflow-project" version 4.

The project holds user-entered inputs only; calculated values live in a
separate results document. Dimensional inputs keep the unit they were entered
in (see proflow.io.units.Quantity) and are normalized when calculated.

Version 3 covers the rainfall library (FHA and polynomial IDF sets, and
storms with a depth per return period whose distribution is either a
user-supplied dimensionless mass curve or a named, source-backed distribution
from proflow.engine.storm_library scaled to a duration),
design events, calculation settings, and Rational, Modified Rational and SCS
catchments. Version 4 adds an optional storm sewer network
(proflow.model.network). Older files are read through proflow.io.migrations;
saving always writes the current version. Hydrographs and scenarios arrive in
later versions.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from proflow.engine.idf import FhaCurve, IdfCurve, PolynomialCurve
from proflow.engine.rainfall import MassCurve
from proflow.engine.storm_library import STANDARD_DISTRIBUTIONS, StandardDistribution
from proflow.engine.unit_hydrograph import SHAPE_FACTOR
from proflow.io.migrations import CURRENT_VERSION, migrate
from proflow.io.units import Quantity, UnitError, to_internal
from proflow.model.network import Network, NetworkReader

SCHEMA = "proflow-project"
SCHEMA_VERSION = CURRENT_VERSION

IDF_FORMS = {"fha": ("b", "d", "e"), "polynomial": ("a", "b", "c", "d")}
CATCHMENT_METHODS = ("rational", "modified_rational", "scs")
UNIT_HYDROGRAPHS = ("curvilinear", "triangular")  # NRCS table 16-1 / Hydraflow
TP_EQUATIONS = ("16A-7", "16A-10")


class ProjectError(ValueError):
    """Validation failure; problems are (path, message) pairs."""

    def __init__(self, problems: list[tuple[str, str]]):
        self.problems = problems
        super().__init__("\n".join(f"{path}: {msg}" for path, msg in problems))


@dataclass(frozen=True)
class IdfCurveDef:
    return_period: int
    coefficients: dict[str, float]


@dataclass(frozen=True)
class IdfSetDef:
    """IDF equations for one location. Coefficients give in/hr from minutes."""

    id: str
    name: str
    form: str
    curves: tuple[IdfCurveDef, ...]

    def curve(self, return_period: int) -> IdfCurve:
        for c in self.curves:
            if c.return_period == return_period:
                k = c.coefficients
                if self.form == "fha":
                    return FhaCurve(k["b"], k["d"], k["e"])
                return PolynomialCurve(k["a"], k["b"], k["c"], k["d"])
        raise KeyError(f"IDF set {self.id!r} has no {return_period}-yr curve")


@dataclass(frozen=True)
class StormDepth:
    return_period: int
    depth: Quantity  # depth


@dataclass(frozen=True)
class StormDef:
    """A storm's temporal distribution and its total depth per event.

    Either a user-supplied mass curve (times, fractions) or a named standard
    distribution scaled to a duration; never both.
    """

    id: str
    name: str
    times: tuple[float, ...]  # in time_unit
    time_unit: str
    fractions: tuple[float, ...]
    depths: tuple[StormDepth, ...]
    standard: str | None = None  # key of STANDARD_DISTRIBUTIONS
    duration: Quantity | None = None  # time; with standard only

    @property
    def distribution(self) -> StandardDistribution | None:
        return STANDARD_DISTRIBUTIONS.get(self.standard) if self.standard else None

    def mass_curve(self) -> MassCurve:
        if self.standard is not None:
            dist = STANDARD_DISTRIBUTIONS[self.standard]
            return dist.mass_curve(self.duration.internal("time"))
        times = [to_internal("time", t, self.time_unit) for t in self.times]
        return MassCurve.from_table(times, self.fractions, self.name)

    def depth(self, return_period: int) -> Quantity:
        for d in self.depths:
            if d.return_period == return_period:
                return d.depth
        raise KeyError(f"storm {self.id!r} has no {return_period}-yr depth")


@dataclass(frozen=True)
class RationalCatchment:
    id: str
    name: str
    method: str  # "rational" or "modified_rational"
    idf: str
    area: Quantity  # drainage_area
    c: float
    tc: Quantity  # time
    receding_limb_factor: float = 1.0  # rational only
    ascending_limb_factor: float = 1.0  # rational only
    storm_duration_factor: float | None = None  # modified_rational only


@dataclass(frozen=True)
class ScsCatchment:
    id: str
    name: str
    storm: str
    area: Quantity  # drainage_area
    cn: float
    tc: Quantity  # time
    unit_hydrograph: str  # see UNIT_HYDROGRAPHS
    tp_equation: str = "16A-10"
    shape_factor: float = SHAPE_FACTOR  # triangular only
    ia_ratio: float = 0.2
    tp: Quantity | None = None  # overrides the computed time to peak
    method: str = "scs"


Catchment = RationalCatchment | ScsCatchment


@dataclass(frozen=True)
class Settings:
    time_step: Quantity = field(default_factory=lambda: Quantity(1.0, "min"))


@dataclass(frozen=True)
class Project:
    name: str
    idf_sets: tuple[IdfSetDef, ...]
    events: tuple[int, ...]
    catchments: tuple[Catchment, ...]
    settings: Settings = field(default_factory=Settings)
    storms: tuple[StormDef, ...] = ()
    network: Network | None = None

    def idf_set(self, id_: str) -> IdfSetDef:
        return next(s for s in self.idf_sets if s.id == id_)

    def storm(self, id_: str) -> StormDef:
        return next(s for s in self.storms if s.id == id_)

    # --- serialization -------------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "schema": SCHEMA,
            "schema_version": SCHEMA_VERSION,
            "name": self.name,
            "settings": {"time_step": self.settings.time_step.to_dict()},
            "events": list(self.events),
            "rainfall": {
                "idf_sets": [_idf_set_dict(s) for s in self.idf_sets],
                "storms": [_storm_dict(s) for s in self.storms],
            },
            "catchments": [_catchment_dict(c) for c in self.catchments],
        } | ({} if self.network is None else {"network": self.network.to_dict()})

    @classmethod
    def from_dict(cls, data: object) -> Project:
        return _Reader().project(data)


def _idf_set_dict(s: IdfSetDef) -> dict:
    return {
        "id": s.id,
        "name": s.name,
        "form": s.form,
        "curves": [
            {"return_period": c.return_period, **c.coefficients} for c in s.curves
        ],
    }


def _storm_dict(s: StormDef) -> dict:
    if s.standard is not None:
        distribution = {"standard": s.standard, "duration": s.duration.to_dict()}
    else:
        distribution = {
            "times": {"values": list(s.times), "unit": s.time_unit},
            "fractions": list(s.fractions),
        }
    return {
        "id": s.id,
        "name": s.name,
        "distribution": distribution,
        "depths": [
            {"return_period": d.return_period, "depth": d.depth.to_dict()}
            for d in s.depths
        ],
    }


def _catchment_dict(c: Catchment) -> dict:
    if isinstance(c, ScsCatchment):
        out = {
            "id": c.id,
            "name": c.name,
            "method": c.method,
            "storm": c.storm,
            "area": c.area.to_dict(),
            "cn": c.cn,
            "tc": c.tc.to_dict(),
            "unit_hydrograph": c.unit_hydrograph,
            "tp_equation": c.tp_equation,
            "ia_ratio": c.ia_ratio,
        }
        if c.unit_hydrograph == "triangular":
            out["shape_factor"] = c.shape_factor
        if c.tp is not None:
            out["tp"] = c.tp.to_dict()
        return out
    out = {
        "id": c.id,
        "name": c.name,
        "method": c.method,
        "idf": c.idf,
        "area": c.area.to_dict(),
        "c": c.c,
        "tc": c.tc.to_dict(),
    }
    if c.method == "rational":
        out["ascending_limb_factor"] = c.ascending_limb_factor
        out["receding_limb_factor"] = c.receding_limb_factor
    if c.storm_duration_factor is not None:
        out["storm_duration_factor"] = c.storm_duration_factor
    return out


class _Reader:
    """Parses a project dict, collecting every problem before raising."""

    def __init__(self) -> None:
        self.problems: list[tuple[str, str]] = []

    def fail(self, path: str, message: str) -> None:
        self.problems.append((path, message))

    def obj(self, data: object, path: str, required: set, optional=frozenset()):
        if not isinstance(data, dict):
            self.fail(path, "expected an object")
            return None
        for key in sorted(required - set(data)):
            self.fail(f"{path}.{key}", "required")
        for key in sorted(set(data) - required - set(optional)):
            self.fail(f"{path}.{key}", "unknown field")
        return data

    def number(self, data: dict, key: str, path: str, positive=False):
        value = data.get(key)
        if isinstance(value, bool) or not isinstance(value, int | float):
            self.fail(f"{path}.{key}", f"expected a number, got {value!r}")
            return None
        if positive and value <= 0:
            self.fail(f"{path}.{key}", "must be positive")
        return float(value)

    def text(self, data: dict, key: str, path: str) -> str:
        value = data.get(key)
        if not isinstance(value, str) or not value:
            self.fail(f"{path}.{key}", "expected a non-empty string")
            return ""
        return value

    def quantity(self, data: dict, key: str, kind: str, path: str):
        try:
            q = Quantity.from_dict(data.get(key), kind)
        except UnitError as exc:
            self.fail(f"{path}.{key}", str(exc))
            return None
        if q.value <= 0:
            self.fail(f"{path}.{key}", "must be positive")
        return q

    def unique_ids(self, items: list, path: str) -> None:
        seen = set()
        for i, item in enumerate(items):
            if item.id in seen:
                self.fail(f"{path}[{i}].id", f"duplicate id {item.id!r}")
            seen.add(item.id)

    def project(self, data: object) -> Project:
        if isinstance(data, dict) and data.get("schema") == SCHEMA:
            data, _ = migrate(data)
        root = self.obj(
            data,
            "project",
            {"schema", "schema_version", "name", "events", "rainfall", "catchments"},
            {"settings", "network"},
        )
        if root is None:
            raise ProjectError(self.problems)
        if root.get("schema") != SCHEMA:
            self.fail("project.schema", f"expected {SCHEMA!r}")
        version = root.get("schema_version")
        if version != SCHEMA_VERSION:
            self.fail(
                "project.schema_version",
                f"version {version!r} is not supported (this build reads "
                f"1 to {SCHEMA_VERSION})",
            )
            raise ProjectError(self.problems)

        name = self.text(root, "name", "project")
        settings = self.settings(root.get("settings", {}))
        events = self.events(root.get("events"))
        rainfall = (
            self.obj(root.get("rainfall"), "rainfall", set(), {"idf_sets", "storms"})
            or {}
        )
        idf_sets = self.idf_sets(rainfall.get("idf_sets", []))
        storms = self.storms(rainfall.get("storms", []))
        catchments = self.catchments(root.get("catchments"), idf_sets, storms, events)
        network = None
        if root.get("network") is not None:
            methods = {c.id: c.method for c in catchments}
            network = NetworkReader(self.problems).network(root["network"], methods)
        if self.problems:
            raise ProjectError(self.problems)
        return Project(name, idf_sets, events, catchments, settings, storms, network)

    def settings(self, data: object) -> Settings:
        d = self.obj(data, "settings", set(), {"time_step"})
        if not d or "time_step" not in d:
            return Settings()
        q = self.quantity(d, "time_step", "time", "settings")
        return Settings(q) if q else Settings()

    def events(self, data: object) -> tuple[int, ...]:
        if not isinstance(data, list) or not data:
            self.fail("events", "expected a non-empty list of return periods (yr)")
            return ()
        for i, rp in enumerate(data):
            if isinstance(rp, bool) or not isinstance(rp, int) or rp <= 0:
                self.fail(f"events[{i}]", "return period must be a positive integer")
        if len(set(data)) != len(data):
            self.fail("events", "return periods must be unique")
        return tuple(data)

    def idf_sets(self, data: object) -> tuple[IdfSetDef, ...]:
        if not isinstance(data, list):
            self.fail("rainfall.idf_sets", "expected a list")
            return ()
        sets = []
        for i, raw in enumerate(data):
            path = f"rainfall.idf_sets[{i}]"
            d = self.obj(raw, path, {"id", "name", "form", "curves"})
            if d is None:
                continue
            form = d.get("form")
            if form not in IDF_FORMS:
                self.fail(f"{path}.form", f"expected one of {sorted(IDF_FORMS)}")
                continue
            curves = []
            for j, rc in enumerate(d.get("curves") or []):
                cpath = f"{path}.curves[{j}]"
                cd = self.obj(rc, cpath, {"return_period", *IDF_FORMS[form]})
                if cd is None:
                    continue
                rp = self.return_period(cd, cpath)
                coeffs = {k: self.number(cd, k, cpath) for k in IDF_FORMS[form]}
                curves.append(IdfCurveDef(rp, coeffs))
            sets.append(
                IdfSetDef(
                    self.text(d, "id", path), d.get("name", ""), form, tuple(curves)
                )
            )
        self.unique_ids(sets, "rainfall.idf_sets")
        return tuple(sets)

    def return_period(self, data: dict, path: str) -> int:
        rp = data.get("return_period")
        if isinstance(rp, bool) or not isinstance(rp, int) or rp <= 0:
            self.fail(f"{path}.return_period", "must be a positive integer")
        return rp

    def storms(self, data: object) -> tuple[StormDef, ...]:
        if not isinstance(data, list):
            self.fail("rainfall.storms", "expected a list")
            return ()
        storms = []
        for i, raw in enumerate(data):
            path = f"rainfall.storms[{i}]"
            d = self.obj(raw, path, {"id", "name", "distribution", "depths"})
            if d is None:
                continue
            dpath = f"{path}.distribution"
            raw_dist = d.get("distribution")
            if isinstance(raw_dist, dict) and "standard" in raw_dist:
                storm = self.standard_storm(d, raw_dist, path, dpath)
                if storm is not None:
                    storms.append(storm)
                continue
            dist = self.obj(raw_dist, dpath, {"times", "fractions"}) or {}
            times = self.obj(dist.get("times"), f"{dpath}.times", {"values", "unit"})
            times = times or {"values": [], "unit": "hr"}
            storm = StormDef(
                id=self.text(d, "id", path),
                name=d.get("name", ""),
                times=tuple(times.get("values") or ()),
                time_unit=times.get("unit", ""),
                fractions=tuple(dist.get("fractions") or ()),
                depths=tuple(self.storm_depths(d.get("depths"), path)),
            )
            try:
                storm.mass_curve()
            except (TypeError, ValueError) as exc:  # ValueError includes UnitError
                self.fail(dpath, str(exc))
            storms.append(storm)
        self.unique_ids(storms, "rainfall.storms")
        return tuple(storms)

    def standard_storm(self, d, raw_dist, path, dpath) -> StormDef | None:
        dist = self.obj(raw_dist, dpath, {"standard", "duration"})
        if dist is None:
            return None
        standard = dist.get("standard")
        if standard not in STANDARD_DISTRIBUTIONS:
            self.fail(
                f"{dpath}.standard",
                f"unknown distribution {standard!r}; supported: "
                f"{sorted(STANDARD_DISTRIBUTIONS)}",
            )
            standard = None
        return StormDef(
            id=self.text(d, "id", path),
            name=d.get("name", ""),
            times=(),
            time_unit="",
            fractions=(),
            depths=tuple(self.storm_depths(d.get("depths"), path)),
            standard=standard,
            duration=(
                self.quantity(dist, "duration", "time", dpath)
                if "duration" in dist
                else None
            ),
        )

    def storm_depths(self, data: object, path: str) -> list[StormDepth]:
        if not isinstance(data, list) or not data:
            self.fail(f"{path}.depths", "expected a non-empty list")
            return []
        out = []
        for j, raw in enumerate(data):
            jpath = f"{path}.depths[{j}]"
            d = self.obj(raw, jpath, {"return_period", "depth"})
            if d is None:
                continue
            rp = self.return_period(d, jpath)
            try:
                depth = Quantity.from_dict(d.get("depth"), "depth")
            except UnitError as exc:
                self.fail(f"{jpath}.depth", str(exc))
                continue
            if depth.value < 0:
                self.fail(f"{jpath}.depth", "must not be negative")
            out.append(StormDepth(rp, depth))
        rps = [d.return_period for d in out]
        if len(set(rps)) != len(rps):
            self.fail(f"{path}.depths", "return periods must be unique")
        return out

    def catchments(self, data, idf_sets, storms, events) -> tuple[Catchment, ...]:
        if not isinstance(data, list):
            self.fail("catchments", "expected a list")
            return ()
        out = []
        for i, raw in enumerate(data):
            path = f"catchments[{i}]"
            method = raw.get("method") if isinstance(raw, dict) else None
            if method == "scs":
                c = self.scs_catchment(raw, path, storms, events)
            elif method in CATCHMENT_METHODS:
                c = self.rational_catchment(raw, path, idf_sets, events)
            else:
                self.fail(f"{path}.method", f"expected one of {CATCHMENT_METHODS}")
                continue
            if c is not None:
                out.append(c)
        self.unique_ids(out, "catchments")
        return tuple(out)

    def scs_catchment(self, raw, path, storms, events) -> ScsCatchment | None:
        d = self.obj(
            raw,
            path,
            {"id", "name", "method", "storm", "area", "cn", "tc", "unit_hydrograph"},
            {"tp_equation", "shape_factor", "ia_ratio", "tp"},
        )
        if d is None:
            return None
        storm = self.text(d, "storm", path)
        by_id = {s.id: s for s in storms}
        if storm and storm not in by_id:
            self.fail(f"{path}.storm", f"no storm with id {storm!r}")
        elif storm:
            have = {x.return_period for x in by_id[storm].depths}
            for rp in sorted(set(events) - have):
                self.fail(f"{path}.storm", f"storm {storm!r} has no {rp}-yr depth")
        cn = self.number(d, "cn", path)
        if cn is not None and not 0 < cn <= 100:
            self.fail(f"{path}.cn", "curve number must be in (0, 100]")
        form = d.get("unit_hydrograph")
        if form not in UNIT_HYDROGRAPHS:
            self.fail(f"{path}.unit_hydrograph", f"expected one of {UNIT_HYDROGRAPHS}")
        tp_equation = d.get("tp_equation", "16A-10")
        if tp_equation not in TP_EQUATIONS:
            self.fail(f"{path}.tp_equation", f"expected one of {TP_EQUATIONS}")
        shape_factor = SHAPE_FACTOR
        if "shape_factor" in d:
            if form != "triangular":
                self.fail(
                    f"{path}.shape_factor",
                    "only for triangular (table 16-1 is the K = 484 hydrograph)",
                )
            else:
                shape_factor = self.number(d, "shape_factor", path, positive=True)
        ia_ratio = 0.2
        if "ia_ratio" in d:
            ia_ratio = self.number(d, "ia_ratio", path)
            if ia_ratio is not None and not 0 <= ia_ratio < 1:
                self.fail(f"{path}.ia_ratio", "must be in [0, 1)")
        tp = self.quantity(d, "tp", "time", path) if "tp" in d else None
        return ScsCatchment(
            id=self.text(d, "id", path),
            name=d.get("name", ""),
            storm=storm,
            area=self.quantity(d, "area", "drainage_area", path),
            cn=cn,
            tc=self.quantity(d, "tc", "time", path),
            unit_hydrograph=form,
            tp_equation=tp_equation,
            shape_factor=shape_factor,
            ia_ratio=ia_ratio,
            tp=tp,
        )

    def rational_catchment(self, raw, path, idf_sets, events):
        by_id = {s.id: s for s in idf_sets}
        d = self.obj(
            raw,
            path,
            {"id", "name", "method", "idf", "area", "c", "tc"},
            {
                "ascending_limb_factor",
                "receding_limb_factor",
                "storm_duration_factor",
            },
        )
        if d is None:
            return None
        method = d["method"]
        idf = self.text(d, "idf", path)
        if idf and idf not in by_id:
            self.fail(f"{path}.idf", f"no IDF set with id {idf!r}")
        elif idf:
            have = {c.return_period for c in by_id[idf].curves}
            for rp in sorted(set(events) - have):
                self.fail(f"{path}.idf", f"IDF set {idf!r} has no {rp}-yr curve")
        c = self.number(d, "c", path)
        if c is not None and not 0 < c <= 1:
            self.fail(f"{path}.c", "runoff coefficient must be in (0, 1]")
        limbs = {"ascending_limb_factor": 1.0, "receding_limb_factor": 1.0}
        for key in limbs:
            if key not in d:
                continue
            if method != "rational":
                self.fail(f"{path}.{key}", "only for rational (Standard Rational)")
            else:
                limbs[key] = self.number(d, key, path, positive=True)
        sdf = None
        if method == "modified_rational":
            if "storm_duration_factor" not in d:
                self.fail(f"{path}.storm_duration_factor", "required")
            else:
                sdf = self.number(d, "storm_duration_factor", path)
                if sdf is not None and sdf < 1:
                    self.fail(f"{path}.storm_duration_factor", "must be >= 1")
        elif "storm_duration_factor" in d:
            self.fail(f"{path}.storm_duration_factor", "only for modified_rational")
        return RationalCatchment(
            id=self.text(d, "id", path),
            name=d.get("name", ""),
            method=method,
            idf=idf,
            area=self.quantity(d, "area", "drainage_area", path),
            c=c,
            tc=self.quantity(d, "tc", "time", path),
            receding_limb_factor=limbs["receding_limb_factor"],
            ascending_limb_factor=limbs["ascending_limb_factor"],
            storm_duration_factor=sdf,
        )
