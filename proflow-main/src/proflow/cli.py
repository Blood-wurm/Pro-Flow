"""Command-line entry point: `proflow run PROJECT` and `proflow fixtures`."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from proflow import cli_channel, cli_idf, cli_storm, fixtures
from proflow.calculate import calculate, results_document
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
    if args.output:
        write_json(results_document(project, results), args.output)
        print(f"results written to {args.output}")
    return EXIT_OK if all(r.result.ok for r in results) else EXIT_FAILED


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
    run.set_defaults(func=_run)

    fix = sub.add_parser("fixtures", help="check reference-case fixtures")
    fix.add_argument("paths", nargs="*", type=Path, help="files or directories")
    fix.set_defaults(func=_fixtures)

    cli_idf.add_parser(sub)
    cli_storm.add_parser(sub)
    cli_channel.add_parser(sub)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
