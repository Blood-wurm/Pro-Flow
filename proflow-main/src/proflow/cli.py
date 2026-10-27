"""Command-line entry point: `proflow run PROJECT`, `proflow fixtures`, and tools."""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

from proflow import cli_channel, cli_idf, cli_network, cli_storm, fixtures
from proflow.calculate import calculate, calculate_network, results_document
from proflow.io.project_json import read_project, write_json
from proflow.model.project import SCHEMA_VERSION, ProjectError

EXIT_OK, EXIT_FAILED, EXIT_INVALID = 0, 1, 2

_LABELS = {
    "intensity": "i",
    "precipitation": "P",
    "runoff_depth": "Q",
    "unit_hydrograph_tp": "UH Tp",
}


def _run(args: argparse.Namespace) -> int:
    if args.sewer_method == "hydraflow_ems" and args.design_velocity is None:
        print(
            "--sewer-method hydraflow_ems requires --design-velocity FT/S",
            file=sys.stderr,
        )
        return EXIT_INVALID
    if args.design_velocity is not None and (
        not math.isfinite(args.design_velocity) or args.design_velocity <= 0
    ):
        print("--design-velocity must be positive", file=sys.stderr)
        return EXIT_INVALID
    if args.design_velocity is not None and args.sewer_method != "hydraflow_ems":
        print(
            "--design-velocity requires --sewer-method hydraflow_ems",
            file=sys.stderr,
        )
        return EXIT_INVALID
    try:
        project, version = read_project(args.project)
    except ProjectError as exc:
        print(f"{args.project}: invalid project", file=sys.stderr)
        for path, msg in exc.problems:
            print(f"  {path}: {msg}", file=sys.stderr)
        return EXIT_INVALID
    if version != SCHEMA_VERSION:
        print(
            f"note: {args.project} is schema v{version}; read through migration, "
            f"saving writes v{SCHEMA_VERSION}"
        )
    results = calculate(project)
    print(f"{project.name}  (all methods experimental)")
    for r in results:
        hyd = r.result.value
        if hyd is None:
            print(
                f"  {r.catchment} {r.event}-yr  {r.result.status}: {r.result.message}"
            )
        else:
            extra = "  ".join(
                f"{_LABELS.get(name, name)}={value:.3f} {unit}"
                for name, (value, unit) in r.quantities.items()
            )
            print(
                f"  {r.catchment} {r.event}-yr  {extra}  "
                f"Qp={hyd.peak:.2f} cfs  Tp={hyd.time_to_peak:g} min  "
                f"V={hyd.volume:,.0f} ft3  [{r.result.method}]"
            )
            for warning in r.result.warnings:
                print(f"    warning: {warning}")
    lines = calculate_network(
        project,
        sewer_method=args.sewer_method,
        junction_losses=args.junction_losses,
        design_velocity=args.design_velocity,
    )
    for r in lines:
        _print_line(r)
    if args.output:
        write_json(results_document(project, results, lines), args.output)
        print(f"results written to {args.output}")
    ok = all(r.result.ok for r in results) and all(r.result.ok for r in lines)
    return EXIT_OK if ok else EXIT_FAILED


def _print_line(r) -> None:
    into = f" -> {r.downstream}" if r.downstream else " -> outfall"
    head = f"  line {r.pipe} {r.event}-yr{into}"
    h = r.result.value
    if h is None:
        print(f"{head}  {r.result.status}: {r.result.message}")
        return
    q = r.quantities
    parts = [f"CA={q['ca'][0]:.3f} ac"]
    if "tc" in q:
        parts.append(f"Tc={q['tc'][0]:.2f} min  i={q['intensity'][0]:.3f} in/hr")
    if "known_flow" in q:
        parts.append(f"known Q={q['known_flow'][0]:.2f} cfs")
    cap = "none" if h.capacity is None else f"{h.capacity:.2f} cfs"
    parts += [
        f"Q={q['flow'][0]:.2f} cfs",
        f"capacity={cap}",
        f"Tt={q['travel_time'][0]:.2f} min",
    ]
    print(f"{head}  " + "  ".join(parts))
    print(
        f"      HGL dn/up/jct={h.down.hgl:.2f}/{h.up.hgl:.2f}/{h.hgl_junction:.2f} ft"
        f"  EGL dn/up/jct={h.down.egl:.2f}/{h.up.egl:.2f}/{h.egl_junction:.2f} ft"
        f"  [{r.flow_method}, {r.result.method}]"
    )
    for warning in r.result.warnings:
        print(f"    warning: {warning}")


def _fixtures(args: argparse.Namespace) -> int:
    try:
        if args.paths:
            loaded = [
                f
                for p in args.paths
                for f in (
                    fixtures.discover(p) if p.is_dir() else [fixtures.load_fixture(p)]
                )
            ]
        else:
            loaded = fixtures.discover()
    except fixtures.FixtureError as exc:
        print(exc, file=sys.stderr)
        return EXIT_INVALID
    results = [fixtures.run_fixture(f) for f in loaded]
    print(fixtures.format_results(results))
    return EXIT_FAILED if fixtures.failed(results) else EXIT_OK


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(prog="proflow")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="calculate a project file")
    run.add_argument("project", type=Path)
    run.add_argument("-o", "--output", type=Path, help="write a results JSON file")
    run.add_argument(
        "--sewer-method",
        choices=("hec22", "hydraflow_ems"),
        default="hec22",
        help="storm sewer travel-time method (hydraflow_ems uses three passes)",
    )
    run.add_argument(
        "--design-velocity",
        type=float,
        metavar="FT/S",
        help="Hydraflow design-code velocity for the first pass",
    )
    run.add_argument(
        "--junction-losses",
        choices=("entered", "automatic"),
        default="entered",
        help="use entered K or compute K from plan angles",
    )
    run.set_defaults(func=_run)

    fix = sub.add_parser("fixtures", help="check reference-case fixtures")
    fix.add_argument("paths", nargs="*", type=Path, help="files or directories")
    fix.set_defaults(func=_fixtures)

    cli_idf.add_parser(sub)
    cli_storm.add_parser(sub)
    cli_channel.add_parser(sub)
    cli_network.add_parser(sub)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
