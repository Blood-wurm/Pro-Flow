"""Import a PFSUITE network exchange ("pfsuite-network", format version 1).

The format and its resolution rules are documented in
docs/pfsuite-network-exchange.md. The import is a separate step from the
native project: it produces a report, and a Network only when there are no
errors and no unresolved links.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path

from proflow.io.units import Quantity
from proflow.model.network import Network, Pipe, Structure

FORMAT = "pfsuite-network"
FORMAT_VERSION = 1
SOURCE_TAG = f"{FORMAT}/{FORMAT_VERSION}"

DEFAULT_SETTINGS = {"pipe_snap_ft": 8.0, "membership_tol_ft": 0.15}  # pf-cfg V6
INLET_TYPES = frozenset({"CBI", "CBI_BOX", "DBI"})
TIE_FT = 0.01  # two structures this close to an end's best match: ambiguous
LENGTH_CHECK_FT, LENGTH_CHECK_REL = 0.5, 0.01
RIM_SOURCES = ("CL", "TIN", "RULE", "ASSERTED", "NONE")
END_OF_BRANCH_NOTE = "default: end of branch (Storm Sewers manual p. 66)"

_TOP = {
    "format",
    "format_version",
    "producer",
    "exported_at",
    "drawing",
    "units",
    "coordinates",
    "lines",
    "grids",
    "structures",
    "pipes",
}
_TOP_OPTIONAL = {"settings", "materials", "diagnostics"}
_STRUCTURE = {"id", "block", "type", "plan", "rim", "lines"}
_STRUCTURE_OPTIONAL = {"size", "name", "position", "inlet", "library", "record_schema"}
_PIPE = {"id", "grid", "upstream", "downstream", "size_in"}
_PIPE_OPTIONAL = {"material", "wall_in"}
_GRID = {"id", "line", "sta0", "datum", "leftx", "basey", "vscale"}


@dataclass(frozen=True)
class Finding:
    level: str  # "error", "unresolved", "warning", "info"
    code: str
    message: str
    ref: str = ""

    def __str__(self) -> str:
        where = f" [{self.ref}]" if self.ref else ""
        return f"{self.level}: {self.code}{where}: {self.message}"


@dataclass(frozen=True)
class PipeEnd:
    """One resolved pipe end: where the drawing puts it on its line."""

    station: float
    invert: float
    structure: str | None


@dataclass
class ExchangeImport:
    network: Network | None = None
    findings: list[Finding] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    # pipe id -> (Manning's n, where it came from); offered, never applied.
    suggested_n: dict[str, tuple[float, str]] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.network is not None

    def of(self, level: str) -> list[Finding]:
        return [f for f in self.findings if f.level == level]

    def report(self) -> list[str]:
        lines = [str(f) for f in self.findings]
        lines += [f"missing: {m}" for m in self.missing]
        lines += [
            f"suggested: pipe {pid} n = {n:g} ({src}); not applied"
            for pid, (n, src) in self.suggested_n.items()
        ]
        return lines


class _Checker:
    def __init__(self, result: ExchangeImport) -> None:
        self.result = result

    def add(self, level, code, message, ref=""):
        self.result.findings.append(Finding(level, code, message, ref))

    def error(self, path, message):
        self.add("error", "invalid", message, path)

    def obj(self, data, path, required, optional=frozenset(), extra=None):
        """Check an object; unknown keys go to `extra` when given, else warn."""
        if not isinstance(data, dict):
            self.error(path, "expected an object")
            return None
        for key in sorted(required - set(data)):
            self.error(f"{path}.{key}", "required")
        for key in sorted(set(data) - required - set(optional)):
            if extra is not None:
                extra[key] = data[key]
            self.add(
                "info",
                "unknown_field",
                "not in format version 1; kept",
                f"{path}.{key}",
            )
        return data

    def number(self, data, key, path, positive=False):
        v = data.get(key)
        if (
            isinstance(v, bool)
            or not isinstance(v, int | float)
            or not math.isfinite(v)
        ):
            self.error(f"{path}.{key}", f"expected a number, got {v!r}")
            return None
        if positive and v <= 0:
            self.error(f"{path}.{key}", "must be positive")
            return None
        return float(v)

    def text(self, data, key, path, required=True):
        v = data.get(key, None if required else "")
        if not isinstance(v, str) or (required and not v):
            self.error(f"{path}.{key}", "expected a non-empty string")
            return ""
        return v

    def point(self, data, key, path):
        p = self.obj(data.get(key), f"{path}.{key}", {"x", "y"}, {"rotation_deg"})
        if p is None:
            return None
        x, y = (
            self.number(p, "x", f"{path}.{key}"),
            self.number(p, "y", f"{path}.{key}"),
        )
        return None if x is None or y is None else (x, y)


def read_exchange(path: Path) -> ExchangeImport:
    """Read a file. AutoLISP writes the system code page, so text that is not
    UTF-8 is read as Windows-1252, and the report says so."""
    note = None
    try:
        raw = Path(path).read_bytes()
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = raw.decode("cp1252", errors="replace")
            note = Finding("info", "encoding", "not UTF-8; read as Windows-1252")
        data = json.loads(text)
    except (OSError, json.JSONDecodeError) as exc:
        out = ExchangeImport()
        out.findings.append(Finding("error", "unreadable", str(exc), str(path)))
        return out
    result = import_exchange(data)
    if note is not None:
        result.findings.insert(0, note)
    return result


def import_exchange(data: object) -> ExchangeImport:
    result = ExchangeImport()
    c = _Checker(result)
    top_extra: dict = {}
    root = c.obj(data, "exchange", _TOP, _TOP_OPTIONAL, top_extra)
    if root is None:
        return result
    if root.get("format") != FORMAT:
        c.error("exchange.format", f"expected {FORMAT!r}")
        return result
    if root.get("format_version") != FORMAT_VERSION:
        c.error(
            "exchange.format_version",
            f"version {root.get('format_version')!r} is not supported "
            f"(this build reads {FORMAT_VERSION})",
        )
        return result

    producer = c.obj(
        root.get("producer"),
        "exchange.producer",
        {"name"},
        {"version", "exporter", "exporter_version", "record_schema"},
    )
    drawing = c.obj(root.get("drawing"), "exchange.drawing", {"name"}, {"path"})
    exported_at = c.text(root, "exported_at", "exchange")
    units = c.obj(root.get("units"), "exchange.units", {"length", "pipe_size"})
    if units and (units.get("length"), units.get("pipe_size")) != ("ft", "in"):
        c.error(
            "exchange.units",
            f"expected length 'ft' and pipe_size 'in', got {units!r} (metric "
            f"drawings are not supported)",
        )
    coords = c.obj(
        root.get("coordinates"), "exchange.coordinates", {"plan", "crs"}, {"note"}
    )
    if coords and coords.get("plan") != "drawing":
        c.error("exchange.coordinates.plan", "expected 'drawing'")
    crs = coords.get("crs") if coords else None
    if crs is not None and not isinstance(crs, str):
        c.error("exchange.coordinates.crs", "expected a string or null")
    settings = dict(DEFAULT_SETTINGS)
    if "settings" in root:
        s = c.obj(root["settings"], "exchange.settings", set(), set(DEFAULT_SETTINGS))
        for key in DEFAULT_SETTINGS:
            if s and key in s:
                v = c.number(s, key, "exchange.settings", positive=True)
                if v is not None:
                    settings[key] = v

    for i, d in enumerate(root.get("diagnostics") or []):
        dd = c.obj(
            d, f"exchange.diagnostics[{i}]", {"level", "code", "message"}, {"ref"}
        )
        if dd is None:
            continue
        level = dd.get("level")
        if level not in ("error", "warning", "info"):
            c.error(
                f"exchange.diagnostics[{i}].level", "expected error, warning or info"
            )
            continue
        c.add(
            level,
            f"exporter:{dd.get('code')}",
            str(dd.get("message")),
            str(dd.get("ref", "")),
        )

    lines = _lines(c, root.get("lines"))
    grids = _grids(c, root.get("grids"), lines)
    structures = _structures(c, root.get("structures"), lines)
    pipes = _pipes(c, root.get("pipes"), grids)
    materials = _materials(c, root.get("materials"))
    if result.of("error"):
        return result

    # --- resolve ------------------------------------------------------------
    snap = settings["pipe_snap_ft"]
    resolved = []
    for p in pipes:
        g = grids[p["grid"]]
        ends = []
        for which in ("upstream", "downstream"):
            x, y = p[which]
            station = g["sta0"] + (x - g["leftx"])
            invert = g["datum"] + (y - g["basey"]) / g["vscale"]
            sid = _link(c, structures, g["line"], station, snap, p["id"], which)
            ends.append(PipeEnd(station, invert, sid))
        up, down = ends
        if up.structure and up.structure == down.structure:
            c.add(
                "unresolved",
                "same_structure",
                f"both ends link to structure {up.structure}",
                p["id"],
            )
            continue
        if up.structure and down.structure:
            resolved.append((p, g, up, down))
    if not resolved and not result.of("unresolved"):
        c.add("error", "no_pipes", "the exchange has no pipes to import")
    if result.of("error") or result.of("unresolved"):
        return result

    used = {sid for _, _, u, d in resolved for sid in (u.structure, d.structure)}
    downstream_of = {d.structure for _, _, _, d in resolved}
    upstream_of = {u.structure for _, _, u, _ in resolved}
    for sid in sorted(set(structures) - used):
        c.add("info", "not_connected", "no imported pipe reaches this structure", sid)

    tag = {"format": SOURCE_TAG, "drawing": drawing.get("name", "")}
    net_structures = []
    for sid in sorted(used):
        s = structures[sid]
        if sid in downstream_of and sid not in upstream_of:
            kind = "outfall"
        elif s["inlet"] or s["type"].upper() in INLET_TYPES:
            kind = "inlet"
        else:
            kind = "manhole"
        rim = s["rim"]
        provenance = {"x": "pfsuite:plan insert", "y": "pfsuite:plan insert"}
        if rim["value"] is not None:
            provenance["rim"] = f"pfsuite:PFRIM ({rim['source']})"
        else:
            result.missing.append(
                f"structure {sid} ({s['name'] or s['type']}): rim (source NONE)"
            )
        net_structures.append(
            Structure(
                id=sid,
                name=s["name"],
                kind=kind,
                x=s["plan"][0],
                y=s["plan"][1],
                rim=None if rim["value"] is None else Quantity(rim["value"], "ft"),
                source=tag
                | {
                    "id": sid,
                    "provenance": provenance,
                    "attributes": {
                        k: s[k]
                        for k in (
                            "block",
                            "type",
                            "size",
                            "position",
                            "inlet",
                            "library",
                            "rotation_deg",
                            "record_schema",
                            "lines",
                        )
                    }
                    | {"rim_source": rim["source"]},
                    "extra": s["extra"],
                },
            )
        )

    net_pipes = []
    for p, g, up, down in resolved:
        su, sd = structures[up.structure], structures[down.structure]
        length = abs(_memb(su, g["line"]) - _memb(sd, g["line"]))
        plan = math.dist(su["plan"], sd["plan"])
        if abs(plan - length) > max(LENGTH_CHECK_FT, LENGTH_CHECK_REL * length):
            c.add(
                "warning",
                "length_mismatch",
                f"centre-to-centre length along {g['line']} is {length:.2f} ft but the "
                f"plan points are {plan:.2f} ft apart: the centerline bends between "
                f"the structures, or a record is out of date",
                p["id"],
            )
        run = abs(up.station - down.station)
        slope = (up.invert - down.invert) / length if length > 0 else math.nan
        if length <= 0:
            c.add("error", "zero_length", "both structures sit at one station", p["id"])
            continue
        if slope < 0:
            c.add("warning", "adverse_slope", f"slope {slope * 100:.3f} %", p["id"])
        elif slope == 0:
            c.add(
                "warning", "flat", "upstream and downstream inverts are equal", p["id"]
            )
        c.add(
            "info",
            "geometry",
            f"length {length:.2f} ft centre to centre (drawn run {run:.2f} ft), "
            f"inverts {up.invert:.3f} / {down.invert:.3f} ft, "
            f"slope {slope * 100:.3f} %",
            p["id"],
        )
        result.missing.append(f"pipe {p['id']}: Manning's n")
        if p["material"] in materials:
            result.suggested_n[p["id"]] = materials[p["material"]]
        net_pipes.append(
            Pipe(
                id=p["id"],
                name="",
                upstream=up.structure,
                downstream=down.structure,
                length=Quantity(length, "ft"),
                diameter=Quantity(p["size_in"], "in"),
                invert_up=Quantity(up.invert, "ft"),
                invert_down=Quantity(down.invert, "ft"),
                material=p["material"],
                source=tag
                | {
                    "id": p["id"],
                    "provenance": {
                        "length": f"pfsuite:membership stations on {g['line']}",
                        "diameter": "pfsuite:PFSIZE",
                        "invert_up": f"pfsuite:profile grid {g['id']}",
                        "invert_down": f"pfsuite:profile grid {g['id']}",
                        "material": "pfsuite:PFMAT",
                        "junction_k": END_OF_BRANCH_NOTE,
                    },
                    "attributes": {
                        "line": g["line"],
                        "grid": g["id"],
                        "upstream_sheet": list(p["upstream"]),
                        "downstream_sheet": list(p["downstream"]),
                        "upstream_station": up.station,
                        "downstream_station": down.station,
                        "drawn_run_ft": run,
                        "wall_in": p["wall_in"],
                    },
                    "extra": p["extra"],
                },
            )
        )
    if result.of("error"):
        return result

    for s in net_structures:
        if s.kind == "outfall":
            result.missing.append(f"outfall {s.id}: starting HGL / tailwater")
        elif s.id not in downstream_of:
            result.missing.append(f"{s.kind} {s.id}: a catchment or known flow")

    result.network = Network(
        name=drawing.get("name", "") or "PFSUITE network",
        structures=tuple(net_structures),
        pipes=tuple(net_pipes),
        plan_unit="ft",
        crs=crs,
        source={
            "format": SOURCE_TAG,
            "producer": producer,
            "exported_at": exported_at,
            "drawing": drawing,
            "settings": settings,
            "lines": list(lines.values()),
            "grids": list(grids.values()),
            "extra": top_extra,
        },
    )
    return result


def _memb(structure: dict, line: str) -> float:
    return next(m["station"] for m in structure["lines"] if m["line"] == line)


def _link(c, structures, line, station, snap, pipe_id, which) -> str | None:
    candidates = sorted(
        (abs(m["station"] - station), sid)
        for sid, s in structures.items()
        for m in s["lines"]
        if m["line"] == line
    )
    near = [(d, sid) for d, sid in candidates if d <= snap]
    if not near:
        best = (
            f"; nearest is {candidates[0][1]} at {candidates[0][0]:.2f} ft"
            if candidates
            else ""
        )
        c.add(
            "unresolved",
            "end_unlinked",
            f"{which} end at station {station:.2f} on {line}: no structure within "
            f"{snap:g} ft{best}",
            pipe_id,
        )
        return None
    if len(near) > 1 and near[1][0] - near[0][0] < TIE_FT:
        c.add(
            "unresolved",
            "end_ambiguous",
            f"{which} end at station {station:.2f} on {line}: structures "
            f"{near[0][1]} and {near[1][1]} are equally near",
            pipe_id,
        )
        return None
    return near[0][1]


def _list(c, data, path):
    if not isinstance(data, list):
        c.error(path, "expected a list")
        return []
    return data


def _unique(c, ids, path):
    seen = set()
    for i, x in enumerate(ids):
        if x in seen:
            c.error(f"{path}[{i}].id", f"duplicate id {x!r}")
        seen.add(x)


def _lines(c, data) -> dict:
    out = {}
    items = _list(c, data, "exchange.lines")
    for i, raw in enumerate(items):
        path = f"exchange.lines[{i}]"
        d = c.obj(raw, path, {"id"}, {"cl_file", "station_range"})
        if d is None:
            continue
        lid = c.text(d, "id", path)
        out[lid] = {
            "id": lid,
            "cl_file": d.get("cl_file"),
            "station_range": d.get("station_range"),
        }
    _unique(c, [d.get("id") for d in items if isinstance(d, dict)], "exchange.lines")
    return out


def _grids(c, data, lines) -> dict:
    out = {}
    items = _list(c, data, "exchange.grids")
    for i, raw in enumerate(items):
        path = f"exchange.grids[{i}]"
        d = c.obj(raw, path, _GRID, {"title"})
        if d is None:
            continue
        gid = c.text(d, "id", path)
        line = c.text(d, "line", path)
        if line and line not in lines:
            c.error(f"{path}.line", f"no line with id {line!r}")
        nums = {k: c.number(d, k, path) for k in ("sta0", "datum", "leftx", "basey")}
        nums["vscale"] = c.number(d, "vscale", path, positive=True)
        if None in nums.values():
            continue
        out[gid] = {"id": gid, "line": line, "title": d.get("title", "")} | nums
    _unique(c, [d.get("id") for d in items if isinstance(d, dict)], "exchange.grids")
    return out


def _structures(c, data, lines) -> dict:
    out = {}
    items = _list(c, data, "exchange.structures")
    for i, raw in enumerate(items):
        path = f"exchange.structures[{i}]"
        extra: dict = {}
        d = c.obj(raw, path, _STRUCTURE, _STRUCTURE_OPTIONAL, extra)
        if d is None:
            continue
        sid = c.text(d, "id", path)
        plan = c.point(d, "plan", path)
        rotation = (d.get("plan") or {}).get("rotation_deg", 0.0)
        rim = c.obj(d.get("rim"), f"{path}.rim", {"value", "source"})
        rim_out = {"value": None, "source": "NONE"}
        if rim is not None:
            if rim.get("source") not in RIM_SOURCES:
                c.error(f"{path}.rim.source", f"expected one of {RIM_SOURCES}")
            elif rim.get("value") is None:
                if rim["source"] != "NONE":
                    c.error(f"{path}.rim.value", "null only with source NONE")
            else:
                v = c.number(rim, "value", f"{path}.rim")
                if rim["source"] == "NONE":
                    c.error(f"{path}.rim.source", "NONE means no value is on record")
                rim_out = {"value": v, "source": rim["source"]}
        memb = []
        for j, m in enumerate(_list(c, d.get("lines"), f"{path}.lines")):
            mpath = f"{path}.lines[{j}]"
            md = c.obj(m, mpath, {"line", "station", "offset"})
            if md is None:
                continue
            line = c.text(md, "line", mpath)
            if line and line not in lines:
                c.error(f"{mpath}.line", f"no line with id {line!r}")
            station, offset = (
                c.number(md, "station", mpath),
                c.number(md, "offset", mpath),
            )
            if station is not None and offset is not None:
                memb.append({"line": line, "station": station, "offset": offset})
        if plan is None:
            continue
        out[sid] = {
            "id": sid,
            "block": c.text(d, "block", path),
            "type": c.text(d, "type", path),
            "size": str(d.get("size", "")),
            "name": str(d.get("name", "")),
            "position": str(d.get("position", "")),
            "inlet": str(d.get("inlet", "")),
            "library": str(d.get("library", "")),
            "record_schema": d.get("record_schema"),
            "plan": plan,
            "rotation_deg": rotation,
            "rim": rim_out,
            "lines": memb,
            "extra": extra,
        }
    _unique(
        c, [d.get("id") for d in items if isinstance(d, dict)], "exchange.structures"
    )
    return out


def _pipes(c, data, grids) -> list[dict]:
    out = []
    items = _list(c, data, "exchange.pipes")
    for i, raw in enumerate(items):
        path = f"exchange.pipes[{i}]"
        extra: dict = {}
        d = c.obj(raw, path, _PIPE, _PIPE_OPTIONAL, extra)
        if d is None:
            continue
        pid = c.text(d, "id", path)
        grid = c.text(d, "grid", path)
        if grid and grid not in grids:
            c.add(
                "unresolved", "pipe_no_grid", f"no grid with id {grid!r}", pid or path
            )
            continue
        ends = {}
        for which in ("upstream", "downstream"):
            e = c.obj(d.get(which), f"{path}.{which}", {"sheet"})
            ends[which] = c.point(e, "sheet", f"{path}.{which}") if e else None
        size = c.number(d, "size_in", path, positive=True)
        wall = c.number(d, "wall_in", path, positive=True) if "wall_in" in d else None
        if None in ends.values() or size is None:
            continue
        out.append(
            {
                "id": pid,
                "grid": grid,
                "upstream": ends["upstream"],
                "downstream": ends["downstream"],
                "size_in": size,
                "material": str(d.get("material", "")),
                "wall_in": wall,
                "extra": extra,
            }
        )
    _unique(c, [d.get("id") for d in items if isinstance(d, dict)], "exchange.pipes")
    return out


def _materials(c, data) -> dict:
    out = {}
    for i, raw in enumerate(data or []):
        path = f"exchange.materials[{i}]"
        d = c.obj(raw, path, {"name", "n"}, {"source"})
        if d is None:
            continue
        n = c.number(d, "n", path, positive=True)
        if n is not None:
            out[c.text(d, "name", path)] = (n, f"{d.get('source', 'materials')}")
    return out
