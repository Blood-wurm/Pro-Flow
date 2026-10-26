"""`proflow idf ...`: fit, convert and export IDF tables."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from proflow.engine.idf import fit_fha_report
from proflow.io.idf_table import (
    IdfTableError,
    read_table,
    table_from_curves,
    write_proflow_table,
)
from proflow.io.project_json import load_project, write_json
from proflow.model.project import ProjectError

EXIT_OK, EXIT_FAILED, EXIT_INVALID = 0, 1, 2

# Hydraflow fits user tables over 5 to 60 minutes (Express manual p. 54).
DEFAULT_WINDOW = (5.0, 60.0)
REPORT_DURATIONS = [5.0 * k for k in range(1, 13)]  # Hydraflow rainfall report


def _floats(text: str) -> list[float]:
    return [float(v) for v in text.split(",") if v.strip()]


def _load(path: Path):
    try:
        return read_table(path), None
    except (IdfTableError, OSError) as exc:
        return None, str(exc)


def _fit(args: argparse.Namespace) -> int:
    table, error = _load(args.table)
    if error:
        print(error, file=sys.stderr)
        return EXIT_INVALID
    table = table.window(args.min_duration, args.max_duration)
    if len(table.durations) < 3:
        print("fewer than three durations in the fit window", file=sys.stderr)
        return EXIT_INVALID
    rps = args.return_periods or list(table.return_periods)
    print(f"{table.name or args.table}")
    window = f"{table.durations[0]:g}-{table.durations[-1]:g} min"
    print(f"FHA fit, i = B / (t + D)^E, over {window} ({len(table.durations)} points)")
    print("   RP       B        D       E     max |res| in/hr  max rel   status")
    curves, fits, ok = [], {}, True
    for rp in rps:
        try:
            row = table.row(int(rp))
        except IdfTableError as exc:
            print(exc, file=sys.stderr)
            return EXIT_INVALID
        r = fit_fha_report(table.durations, row, d_step=args.d_step)
        if not r.ok:
            print(f"{int(rp):5d}  {r.status}: {r.message}")
            ok = False
            continue
        c, d = r.value.curve, r.diagnostics
        print(
            f"{int(rp):5d}  {c.b:9.4f} {c.d:7.3f} {c.e:7.4f}   "
            f"{d['max_abs_residual_in_hr']:12.4f}   {d['max_relative_residual']:7.2%}"
            f"   {'warn' if r.warnings else 'ok'}"
        )
        for w in r.warnings:
            print(f"       warning: {w}")
        curves.append({"return_period": int(rp), "b": c.b, "d": c.d, "e": c.e})
        fits[str(int(rp))] = {
            "method": r.method,
            "method_status": "experimental",
            "warnings": list(r.warnings),
            "diagnostics": d,
        }
    if args.json:
        write_json(
            {
                "idf_set": {
                    "id": args.id,
                    "name": f"FHA fit to {table.name or args.table.name}, {window}",
                    "form": "fha",
                    "curves": curves,
                },
                "fit_report": {
                    "table": str(args.table),
                    "source": table.source,
                    "window_min": [table.durations[0], table.durations[-1]],
                    "d_step": args.d_step,
                    "fits": fits,
                },
            },
            args.json,
        )
        print(f"idf_set and fit report written to {args.json}")
    return EXIT_OK if ok else EXIT_FAILED


def _convert(args: argparse.Namespace) -> int:
    table, error = _load(args.table)
    if error:
        print(error, file=sys.stderr)
        return EXIT_INVALID
    text = write_proflow_table(table, intensity_unit=args.unit)
    args.output.write_text(text, encoding="utf-8")
    shape = f"{len(table.return_periods)} return periods x {len(table.durations)}"
    print(f"{shape} durations -> {args.output}")
    return EXIT_OK


def _export(args: argparse.Namespace) -> int:
    try:
        project = load_project(args.project)
    except ProjectError as exc:
        print(exc, file=sys.stderr)
        return EXIT_INVALID
    sets = {s.id: s for s in project.idf_sets}
    if args.set not in sets:
        print(f"no IDF set {args.set!r}; have {sorted(sets)}", file=sys.stderr)
        return EXIT_INVALID
    s = sets[args.set]
    curves = {c.return_period: s.curve(c.return_period) for c in s.curves}
    table = table_from_curves(curves, args.durations, s.name)
    args.output.write_text(
        write_proflow_table(table, intensity_unit=args.unit), encoding="utf-8"
    )
    print(f"IDF set {s.id!r} at {len(args.durations)} durations -> {args.output}")
    return EXIT_OK


def add_parser(sub) -> None:
    idf = sub.add_parser("idf", help="fit, convert and export IDF tables")
    cmds = idf.add_subparsers(dest="idf_command", required=True)

    fit = cmds.add_parser("fit", help="fit FHA coefficients to a table")
    fit.add_argument("table", type=Path, help="NOAA Atlas 14 CSV or proflow-idf-table")
    fit.add_argument(
        "--min-duration", type=float, default=DEFAULT_WINDOW[0], help="min"
    )
    fit.add_argument(
        "--max-duration", type=float, default=DEFAULT_WINDOW[1], help="min"
    )
    fit.add_argument("--return-periods", type=_floats, help="e.g. 2,5,10,25,50,100")
    fit.add_argument("--d-step", type=float, help="search D in steps of this (min)")
    fit.add_argument("--id", default="fitted", help="id for the written idf_set")
    fit.add_argument("--json", type=Path, help="write idf_set + fit report")
    fit.set_defaults(func=_fit)

    conv = cmds.add_parser("convert", help="write a table as proflow-idf-table")
    conv.add_argument("table", type=Path)
    conv.add_argument("-o", "--output", type=Path, required=True)
    conv.add_argument("--unit", default="in/hr", help="intensity unit to write")
    conv.set_defaults(func=_convert)

    exp = cmds.add_parser("export", help="tabulate a project's IDF set")
    exp.add_argument("project", type=Path)
    exp.add_argument("--set", required=True, help="IDF set id")
    exp.add_argument("--durations", type=_floats, default=REPORT_DURATIONS, help="min")
    exp.add_argument("--unit", default="in/hr", help="intensity unit to write")
    exp.add_argument("-o", "--output", type=Path, required=True)
    exp.set_defaults(func=_export)
