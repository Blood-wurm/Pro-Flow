"""`proflow storm ...`: list standard distributions, import and export .cds."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from proflow.engine.storm_library import STANDARD_DISTRIBUTIONS
from proflow.io.cds import CdsError, read_cds, write_cds
from proflow.io.project_json import load_project, write_json
from proflow.io.units import UnitError, to_internal
from proflow.model.project import ProjectError

EXIT_OK, EXIT_FAILED, EXIT_INVALID = 0, 1, 2


def _list(args: argparse.Namespace) -> int:
    for d in STANDARD_DISTRIBUTIONS.values():
        print(d.id)
        print(f"  {d.name}")
        print(f"  source: {d.source}")
        if d.recommended_duration_min is not None:
            low, high = (v / 60 for v in d.recommended_duration_min)
            span = f"{low:g} h < duration" + (
                "" if high == float("inf") else f" <= {high:g} h"
            )
            print(f"  recommended: {span} ({d.duration_guidance})")
        if d.status_note:
            print(f"  status: {d.status_note}")
        if d.hydraflow_check:
            print(f"  Hydraflow: {d.hydraflow_check}")
    return EXIT_OK


def _depths(pairs: list[str], unit: str) -> list[dict]:
    out = []
    for pair in pairs:
        rp, _, value = pair.partition("=")
        try:
            out.append(
                {
                    "return_period": int(rp),
                    "depth": {"value": float(value), "unit": unit},
                }
            )
        except ValueError:
            raise ValueError(
                f"--depth {pair!r}: expected RETURN_PERIOD=DEPTH"
            ) from None
    return out


def _import_cds(args: argparse.Namespace) -> int:
    try:
        to_internal("depth", 1.0, args.depth_unit)
        depths = _depths(args.depth, args.depth_unit)
        curve, interval = read_cds(args.file.read_text(encoding="utf-8"))
    except (CdsError, UnitError, ValueError, OSError) as exc:
        print(f"{args.file}: {exc}", file=sys.stderr)
        return EXIT_INVALID
    storm = {
        "id": args.id,
        "name": f"Custom storm from {args.file.name} (.cds, {interval:g}-min interval)",
        "distribution": {
            "times": {"values": curve.times.tolist(), "unit": "min"},
            "fractions": curve.fractions.tolist(),
        },
        "depths": depths,
    }
    write_json(storm, args.output)
    print(
        f"{len(curve.times) - 1} ratios at {interval:g} min ({curve.duration:g} min) "
        f"-> rainfall.storms entry {args.output}"
    )
    return EXIT_OK


def _export_cds(args: argparse.Namespace) -> int:
    try:
        project = load_project(args.project)
    except ProjectError as exc:
        print(exc, file=sys.stderr)
        return EXIT_INVALID
    storms = {s.id: s for s in project.storms}
    if args.storm not in storms:
        print(f"no storm {args.storm!r}; have {sorted(storms)}", file=sys.stderr)
        return EXIT_INVALID
    try:
        text = write_cds(storms[args.storm].mass_curve(), args.interval)
    except CdsError as exc:
        print(exc, file=sys.stderr)
        return EXIT_INVALID
    args.output.write_text(text, encoding="utf-8")
    print(f"storm {args.storm!r} at {args.interval:g} min -> {args.output}")
    return EXIT_OK


def add_parser(sub) -> None:
    storm = sub.add_parser("storm", help="storm distributions and .cds files")
    cmds = storm.add_subparsers(dest="storm_command", required=True)

    lst = cmds.add_parser("list", help="list built-in standard distributions")
    lst.set_defaults(func=_list)

    imp = cmds.add_parser("import-cds", help="make a rainfall.storms entry")
    imp.add_argument("file", type=Path)
    imp.add_argument("--id", required=True)
    imp.add_argument(
        "--depth", action="append", default=[], help="RP=DEPTH, repeat per event"
    )
    imp.add_argument("--depth-unit", default="in")
    imp.add_argument("-o", "--output", type=Path, required=True)
    imp.set_defaults(func=_import_cds)

    exp = cmds.add_parser("export-cds", help="write a project storm as .cds")
    exp.add_argument("project", type=Path)
    exp.add_argument("--storm", required=True, help="storm id")
    exp.add_argument("--interval", type=float, required=True, help="minutes")
    exp.add_argument("-o", "--output", type=Path, required=True)
    exp.set_defaults(func=_export_cds)
