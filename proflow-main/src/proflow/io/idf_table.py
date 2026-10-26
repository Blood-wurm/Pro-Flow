"""Intensity-duration-frequency tables in and out.

Two text formats.

NOAA Atlas 14 point precipitation frequency CSV, as downloaded from the NOAA
HDSC Precipitation Frequency Data Server (fe_text_mean.csv). NOAA publishes no
formal specification for this file, so the reader accepts only the layout the
files themselves show and rejects anything else:

    Point precipitation frequency estimates (<inches|inches/hour|millimeters|
                                             millimeters/hour>)
    ...
    Data type: Precipitation <depth|intensity>
    Time series type: <Partial duration|...>
    ...
    by duration for ARI (years):, 1,2,5,...
    5-min:, 0.428,0.489,...
    2-hr:, ...
    2-day:, ...

Depths are converted to intensity by dividing by the duration.

Pro-Flow IDF table CSV, "proflow-idf-table/1":

    # proflow-idf-table/1
    # name: <free text>
    # duration_unit: min
    # intensity_unit: in/hr
    duration,2,5,10,25,50,100
    5,5.57,6.52,7.40,8.51,9.47,10.31
    ...

"# key: value" lines come first; the header row is "duration" followed by
return periods in years; every cell must be a number.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from proflow.engine.idf import FhaFit, IdfCurve, fit_fha_report
from proflow.engine.result import SolveResult
from proflow.io.units import UnitError, from_internal, to_internal

PROFLOW_FORMAT = "proflow-idf-table/1"

_NOAA_UNITS = {
    "inches": ("depth", "in"),
    "inches/hour": ("intensity", "in/hr"),
    "millimeters": ("depth", "mm"),
    "millimeters/hour": ("intensity", "mm/hr"),
}
_NOAA_DURATION = re.compile(r"^(\d+)-(min|hr|day):$")
_NOAA_DURATION_MIN = {"min": 1, "hr": 60, "day": 1440}


class IdfTableError(ValueError):
    pass


@dataclass(frozen=True)
class IdfTable:
    """Intensities (in/hr) for each return period (rows) and duration (columns)."""

    durations: np.ndarray  # minutes, strictly increasing
    return_periods: tuple[int, ...]
    intensities: np.ndarray  # in/hr, shape (len(return_periods), len(durations))
    name: str = ""
    source: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        shape = (len(self.return_periods), len(self.durations))
        if self.intensities.shape != shape:
            raise IdfTableError(
                f"intensity table is {self.intensities.shape}, not {shape}"
            )
        if np.any(np.diff(self.durations) <= 0):
            raise IdfTableError("durations must strictly increase")
        if len(set(self.return_periods)) != len(self.return_periods):
            raise IdfTableError("return periods must be unique")

    def row(self, return_period: int) -> np.ndarray:
        try:
            return self.intensities[self.return_periods.index(return_period)]
        except ValueError:
            raise IdfTableError(f"no {return_period}-yr row") from None

    def window(self, min_duration: float, max_duration: float) -> IdfTable:
        """The columns with min_duration <= duration <= max_duration (minutes)."""
        keep = (self.durations >= min_duration) & (self.durations <= max_duration)
        return IdfTable(
            self.durations[keep],
            self.return_periods,
            self.intensities[:, keep],
            self.name,
            dict(self.source),
        )

    def fit(self, **kwargs) -> dict[int, SolveResult[FhaFit]]:
        """FHA fit for every return period; kwargs go to fit_fha_report."""
        return {
            rp: fit_fha_report(self.durations, self.row(rp), **kwargs)
            for rp in self.return_periods
        }


def _number(text: str, where: str) -> float:
    try:
        return float(text)
    except ValueError:
        raise IdfTableError(f"{where}: {text!r} is not a number") from None


# --- NOAA Atlas 14 -----------------------------------------------------------


def read_noaa_pfds(text: str) -> IdfTable:
    lines = [line.rstrip() for line in text.splitlines()]
    title = re.match(r"^Point precipitation frequency estimates \((.+)\)$", lines[0])
    if not title or title.group(1) not in _NOAA_UNITS:
        raise IdfTableError("not a NOAA Atlas 14 point estimate file (title line)")
    quantity, unit = _NOAA_UNITS[title.group(1)]
    meta = {}
    for line in lines[1:]:
        if ": " in line and not line.startswith("by duration"):
            key, _, value = line.partition(": ")
            meta[key.strip()] = value.strip()
    data_type = meta.get("Data type", "")
    if data_type != f"Precipitation {quantity}":
        raise IdfTableError(f"data type {data_type!r} does not match units {unit}")
    try:
        start = next(
            k for k, line in enumerate(lines) if line.startswith("by duration for ")
        )
    except StopIteration:
        raise IdfTableError("no 'by duration for ...' header row") from None
    head = [c.strip() for c in lines[start].split(",")]
    if head[0] != "by duration for ARI (years):":
        raise IdfTableError(f"unsupported header {head[0]!r}")
    rps = tuple(int(_number(c, "return period")) for c in head[1:])

    durations, rows = [], []
    for line in lines[start + 1 :]:
        if not line.strip():
            break
        cells = [c.strip() for c in line.split(",")]
        m = _NOAA_DURATION.match(cells[0])
        if not m:
            raise IdfTableError(f"unrecognized duration label {cells[0]!r}")
        minutes = int(m.group(1)) * _NOAA_DURATION_MIN[m.group(2)]
        values = [_number(c, cells[0]) for c in cells[1:]]
        if len(values) != len(rps):
            raise IdfTableError(f"{cells[0]} has {len(values)} values for {len(rps)}")
        durations.append(minutes)
        rows.append(values)
    if not rows:
        raise IdfTableError("no data rows")

    t = np.array(durations, dtype=float)
    values = np.array(rows, dtype=float).T  # (rp, duration)
    if quantity == "depth":
        intensity = to_internal("depth", values, unit) / (t / 60)
    else:
        intensity = to_internal("intensity", values, unit)
    source = {"format": "NOAA Atlas 14 PFDS CSV", "units": title.group(1), **meta}
    name = (
        " ".join(lines[1:2])
        + f" ({meta.get('Latitude', '?')}, {meta.get('Longitude', '?')})"
    )
    return IdfTable(t, rps, intensity, name, source)


# --- Pro-Flow table ----------------------------------------------------------


def read_proflow_table(text: str) -> IdfTable:
    lines = text.splitlines()
    meta: dict[str, str] = {}
    body_start = 0
    for k, line in enumerate(lines):
        if not line.startswith("#"):
            body_start = k
            break
        content = line[1:].strip()
        if content == PROFLOW_FORMAT:
            meta["format"] = PROFLOW_FORMAT
        elif ":" in content:
            key, _, value = content.partition(":")
            meta[key.strip()] = value.strip()
    if meta.get("format") != PROFLOW_FORMAT:
        raise IdfTableError(f"first line must be '# {PROFLOW_FORMAT}'")
    for key in ("duration_unit", "intensity_unit"):
        if key not in meta:
            raise IdfTableError(f"missing '# {key}: ...' line")
    rows = [r for r in csv.reader(lines[body_start:]) if r]
    if not rows or rows[0][0].strip() != "duration":
        raise IdfTableError("header row must start with 'duration'")
    rps = tuple(int(_number(c, "return period")) for c in rows[0][1:])
    try:
        t = np.array(
            [
                to_internal("time", _number(r[0], "duration"), meta["duration_unit"])
                for r in rows[1:]
            ]
        )
        cells = []
        for r in rows[1:]:
            if len(r) != len(rps) + 1:
                raise IdfTableError(
                    f"row {r[0]} has {len(r) - 1} values for {len(rps)}"
                )
            cells.append([_number(c, f"duration {r[0]}") for c in r[1:]])
        values = to_internal(
            "intensity", np.array(cells, dtype=float).T, meta["intensity_unit"]
        )
    except UnitError as exc:
        raise IdfTableError(str(exc)) from None
    return IdfTable(t, rps, values, meta.get("name", ""), {"format": PROFLOW_FORMAT})


def write_proflow_table(
    table: IdfTable, duration_unit: str = "min", intensity_unit: str = "in/hr"
) -> str:
    out = io.StringIO()
    out.write(f"# {PROFLOW_FORMAT}\n")
    if table.name:
        out.write(f"# name: {table.name}\n")
    out.write(f"# duration_unit: {duration_unit}\n# intensity_unit: {intensity_unit}\n")
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(["duration", *table.return_periods])
    # repr() keeps every digit, so a write-read cycle loses nothing.
    for j, t in enumerate(table.durations):
        values = from_internal("intensity", table.intensities[:, j], intensity_unit)
        duration = from_internal("time", float(t), duration_unit)
        writer.writerow([repr(duration), *(repr(float(v)) for v in values)])
    return out.getvalue()


def table_from_curves(
    curves: dict[int, IdfCurve], durations: list[float], name: str = ""
) -> IdfTable:
    """Evaluate equations at chosen durations (minutes), e.g. for export."""
    rps = tuple(sorted(curves))
    t = np.asarray(durations, dtype=float)
    values = np.array([np.atleast_1d(curves[rp].intensity(t)) for rp in rps])
    return IdfTable(t, rps, values, name)


def read_table(path: Path) -> IdfTable:
    """Read either format, chosen by the file's first line."""
    text = Path(path).read_text(encoding="utf-8")
    first = text.lstrip("﻿").splitlines()[0] if text.strip() else ""
    if first.startswith("Point precipitation frequency estimates"):
        return read_noaa_pfds(text.lstrip("﻿"))
    if first.startswith("#"):
        return read_proflow_table(text)
    raise IdfTableError(f"{path}: not a NOAA Atlas 14 CSV or a {PROFLOW_FORMAT} file")
