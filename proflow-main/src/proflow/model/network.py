"""Storm sewer network inputs: structures, pipes and the outfall boundary.

Part of the native project (schema v4, key "network"). A network may be saved
incomplete -- an import leaves Manning's n and the tailwater for the user --
so the reader accepts those as missing and `missing_inputs()` lists what a
calculation still needs.

Each structure and pipe keeps a `source` record: where it came from (for
example the PFSUITE exchange and the drawing handle), which fields were
imported and which the user entered (`provenance`), and any exchange fields
Pro-Flow does not model (`extra`), preserved verbatim.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from proflow.engine.sewer import TAILWATER_MODES
from proflow.io.units import Quantity, UnitError

STRUCTURE_KINDS = ("inlet", "manhole", "junction", "outfall")
PLAN_UNITS = ("ft",)


@dataclass(frozen=True)
class Tailwater:
    """Starting HGL at an outfall (Storm Sewers manual p. 42)."""

    mode: str  # see engine.sewer.TAILWATER_MODES
    elevation: Quantity | None = None  # length; mode "elevation" only


@dataclass(frozen=True)
class Structure:
    id: str
    name: str
    kind: str
    x: float  # plan coordinates, network.plan_unit
    y: float
    rim: Quantity | None = None  # length (elevation)
    catchment: str | None = None  # a Rational catchment draining to it
    known_flow: Quantity | None = None  # flow, added to any catchment runoff
    tailwater: Tailwater | None = None  # outfalls only
    source: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Pipe:
    id: str
    name: str
    upstream: str
    downstream: str
    length: Quantity  # junction centre to junction centre
    diameter: Quantity
    invert_up: Quantity  # elevations
    invert_down: Quantity
    n: float | None = None
    material: str = ""
    junction_k: float = 1.0  # at the upstream end; 1.0 = end of a branch
    source: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Network:
    name: str
    structures: tuple[Structure, ...]
    pipes: tuple[Pipe, ...]
    plan_unit: str = "ft"
    crs: str | None = None  # None = drawing coordinates, no recorded CRS
    source: dict = field(default_factory=dict)

    def structure(self, id_: str) -> Structure:
        return next(s for s in self.structures if s.id == id_)

    def pipe(self, id_: str) -> Pipe:
        return next(p for p in self.pipes if p.id == id_)

    def outfalls(self) -> list[Structure]:
        return [s for s in self.structures if s.kind == "outfall"]

    def missing_inputs(self) -> list[tuple[str, str]]:
        """What a calculation still needs, as (path, message) pairs."""
        out = []
        for i, p in enumerate(self.pipes):
            if p.n is None:
                out.append((f"network.pipes[{i}].n", f"pipe {p.id}: Manning's n"))
        for i, s in enumerate(self.structures):
            if s.kind == "outfall" and s.tailwater is None:
                out.append(
                    (
                        f"network.structures[{i}].tailwater",
                        f"outfall {s.id}: starting HGL / tailwater",
                    )
                )
        downstream = {p.downstream for p in self.pipes}
        for i, s in enumerate(self.structures):
            upstream_end = s.id not in downstream and s.kind != "outfall"
            if upstream_end and s.catchment is None and s.known_flow is None:
                out.append(
                    (
                        f"network.structures[{i}].catchment",
                        f"{s.kind} {s.id}: a catchment or known flow",
                    )
                )
        return out

    def with_pipe(self, pipe: Pipe) -> Network:
        pipes = tuple(pipe if p.id == pipe.id else p for p in self.pipes)
        return replace(self, pipes=pipes)

    def with_structure(self, structure: Structure) -> Network:
        items = tuple(structure if s.id == structure.id else s for s in self.structures)
        return replace(self, structures=items)

    # --- serialization -------------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "plan_unit": self.plan_unit,
            "crs": self.crs,
            "source": self.source,
            "structures": [_structure_dict(s) for s in self.structures],
            "pipes": [_pipe_dict(p) for p in self.pipes],
        }


def mark_user(source: dict, *fields: str) -> dict:
    """A copy of a source record with these fields marked as user-entered."""
    out = dict(source)
    provenance = dict(out.get("provenance", {}))
    for f in fields:
        provenance[f] = "user"
    out["provenance"] = provenance
    return out


def _opt(q: Quantity | None):
    return None if q is None else q.to_dict()


def _structure_dict(s: Structure) -> dict:
    out = {
        "id": s.id,
        "name": s.name,
        "kind": s.kind,
        "x": s.x,
        "y": s.y,
        "rim": _opt(s.rim),
        "catchment": s.catchment,
        "known_flow": _opt(s.known_flow),
        "source": s.source,
    }
    if s.kind == "outfall":
        out["tailwater"] = (
            None
            if s.tailwater is None
            else {"mode": s.tailwater.mode, "elevation": _opt(s.tailwater.elevation)}
        )
    return out


def _pipe_dict(p: Pipe) -> dict:
    return {
        "id": p.id,
        "name": p.name,
        "upstream": p.upstream,
        "downstream": p.downstream,
        "length": p.length.to_dict(),
        "diameter": p.diameter.to_dict(),
        "invert_up": p.invert_up.to_dict(),
        "invert_down": p.invert_down.to_dict(),
        "n": p.n,
        "material": p.material,
        "junction_k": p.junction_k,
        "source": p.source,
    }


class NetworkReader:
    """Parses the "network" section; problems are (path, message) pairs."""

    def __init__(self, problems: list[tuple[str, str]]) -> None:
        self.problems = problems

    def fail(self, path: str, message: str) -> None:
        self.problems.append((path, message))

    def _obj(self, data, path, required, optional=frozenset()):
        if not isinstance(data, dict):
            self.fail(path, "expected an object")
            return None
        for key in sorted(required - set(data)):
            self.fail(f"{path}.{key}", "required")
        for key in sorted(set(data) - required - set(optional)):
            self.fail(f"{path}.{key}", "unknown field")
        return data

    def _number(self, d, key, path):
        v = d.get(key)
        if isinstance(v, bool) or not isinstance(v, int | float):
            self.fail(f"{path}.{key}", f"expected a number, got {v!r}")
            return 0.0
        return float(v)

    def _text(self, d, key, path, allow_empty=False) -> str:
        v = d.get(key)
        if not isinstance(v, str) or (not v and not allow_empty):
            self.fail(f"{path}.{key}", "expected a non-empty string")
            return ""
        return v

    def _quantity(self, d, key, kind, path, positive=False, optional=False):
        raw = d.get(key)
        if raw is None and optional:
            return None
        try:
            q = Quantity.from_dict(raw, kind)
        except UnitError as exc:
            self.fail(f"{path}.{key}", str(exc))
            return None
        if positive and q.value <= 0:
            self.fail(f"{path}.{key}", "must be positive")
        return q

    def _source(self, d, path) -> dict:
        s = d.get("source", {})
        if not isinstance(s, dict):
            self.fail(f"{path}.source", "expected an object")
            return {}
        return s

    def network(self, data, catchments: dict) -> Network | None:
        d = self._obj(
            data,
            "network",
            {"name", "structures", "pipes"},
            {"plan_unit", "crs", "source"},
        )
        if d is None:
            return None
        plan_unit = d.get("plan_unit", "ft")
        if plan_unit not in PLAN_UNITS:
            self.fail("network.plan_unit", f"expected one of {PLAN_UNITS}")
        crs = d.get("crs")
        if crs is not None and not isinstance(crs, str):
            self.fail("network.crs", "expected a string or null")
        structures = [
            self.structure(raw, f"network.structures[{i}]", catchments)
            for i, raw in enumerate(d.get("structures") or [])
        ]
        structures = [s for s in structures if s is not None]
        ids = [s.id for s in structures]
        for i, sid in enumerate(ids):
            if sid in ids[:i]:
                self.fail(f"network.structures[{i}].id", f"duplicate id {sid!r}")
        pipes = [
            self.pipe(raw, f"network.pipes[{i}]", set(ids))
            for i, raw in enumerate(d.get("pipes") or [])
        ]
        pipes = [p for p in pipes if p is not None]
        pids = [p.id for p in pipes]
        for i, pid in enumerate(pids):
            if pid in pids[:i]:
                self.fail(f"network.pipes[{i}].id", f"duplicate id {pid!r}")
        return Network(
            name=self._text(d, "name", "network"),
            structures=tuple(structures),
            pipes=tuple(pipes),
            plan_unit=plan_unit,
            crs=crs,
            source=self._source(d, "network"),
        )

    def structure(self, raw, path, catchments) -> Structure | None:
        d = self._obj(
            raw,
            path,
            {"id", "name", "kind", "x", "y"},
            {"rim", "catchment", "known_flow", "tailwater", "source"},
        )
        if d is None:
            return None
        kind = d.get("kind")
        if kind not in STRUCTURE_KINDS:
            self.fail(f"{path}.kind", f"expected one of {STRUCTURE_KINDS}")
        catchment = d.get("catchment")
        if catchment is not None:
            if catchment not in catchments:
                self.fail(f"{path}.catchment", f"no catchment with id {catchment!r}")
            elif catchments[catchment] != "rational":
                self.fail(
                    f"{path}.catchment",
                    "a sewer inlet takes a Standard Rational catchment (Q = CiA)",
                )
        tailwater = None
        if d.get("tailwater") is not None:
            if kind != "outfall":
                self.fail(f"{path}.tailwater", "only an outfall has a tailwater")
            tailwater = self.tailwater(d["tailwater"], f"{path}.tailwater")
        return Structure(
            id=self._text(d, "id", path),
            name=self._text(d, "name", path, allow_empty=True),
            kind=kind,
            x=self._number(d, "x", path),
            y=self._number(d, "y", path),
            rim=self._quantity(d, "rim", "length", path, optional=True),
            catchment=catchment,
            known_flow=self._quantity(
                d, "known_flow", "flow", path, positive=True, optional=True
            ),
            tailwater=tailwater,
            source=self._source(d, path),
        )

    def tailwater(self, raw, path) -> Tailwater | None:
        d = self._obj(raw, path, {"mode"}, {"elevation"})
        if d is None:
            return None
        mode = d.get("mode")
        if mode not in TAILWATER_MODES:
            self.fail(f"{path}.mode", f"expected one of {TAILWATER_MODES}")
        elevation = self._quantity(d, "elevation", "length", path, optional=True)
        if mode == "elevation" and elevation is None:
            self.fail(f"{path}.elevation", "required for a known elevation")
        if mode != "elevation" and elevation is not None:
            self.fail(f"{path}.elevation", "only for mode 'elevation'")
        return Tailwater(mode, elevation)

    def pipe(self, raw, path, structure_ids) -> Pipe | None:
        d = self._obj(
            raw,
            path,
            {
                "id",
                "name",
                "upstream",
                "downstream",
                "length",
                "diameter",
                "invert_up",
                "invert_down",
            },
            {"n", "material", "junction_k", "source"},
        )
        if d is None:
            return None
        up = self._text(d, "upstream", path)
        down = self._text(d, "downstream", path)
        for key, sid in (("upstream", up), ("downstream", down)):
            if sid and sid not in structure_ids:
                self.fail(f"{path}.{key}", f"no structure with id {sid!r}")
        if up and up == down:
            self.fail(
                f"{path}.downstream", "a pipe cannot start and end at one structure"
            )
        n = d.get("n")
        if n is not None:
            n = self._number(d, "n", path)
            if not 0 < n < 1:
                self.fail(f"{path}.n", "Manning's n must be in (0, 1)")
        k = self._number(d, "junction_k", path) if "junction_k" in d else 1.0
        if k < 0:
            self.fail(f"{path}.junction_k", "must not be negative")
        material = d.get("material", "")
        if not isinstance(material, str):
            self.fail(f"{path}.material", "expected a string")
            material = ""
        return Pipe(
            id=self._text(d, "id", path),
            name=self._text(d, "name", path, allow_empty=True),
            upstream=up,
            downstream=down,
            length=self._quantity(d, "length", "length", path, positive=True),
            diameter=self._quantity(d, "diameter", "length", path, positive=True),
            invert_up=self._quantity(d, "invert_up", "length", path),
            invert_down=self._quantity(d, "invert_down", "length", path),
            n=n,
            material=material,
            junction_k=k,
            source=self._source(d, path),
        )
