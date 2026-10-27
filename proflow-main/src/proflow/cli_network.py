"""`proflow network import`: read a PFSUITE exchange and add it to a project."""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path

from proflow.engine.sewer import TAILWATER_MODES
from proflow.io.pfsuite import read_exchange
from proflow.io.project_json import read_project, save_project
from proflow.io.units import Quantity
from proflow.model.network import Network, Tailwater, mark_user
from proflow.model.project import Project, ProjectError

EXIT_OK, EXIT_FAILED, EXIT_INVALID = 0, 1, 2


def _tailwater(text: str) -> Tailwater:
    mode, _, elevation = text.partition("=")
    if mode not in TAILWATER_MODES:
        raise argparse.ArgumentTypeError(f"expected one of {TAILWATER_MODES}")
    if mode == "elevation":
        try:
            return Tailwater(mode, Quantity(float(elevation), "ft"))
        except ValueError:
            raise argparse.ArgumentTypeError(
                "give the elevation as elevation=<ft>"
            ) from None
    if elevation:
        raise argparse.ArgumentTypeError("only mode 'elevation' takes a value")
    return Tailwater(mode)


def _apply(net: Network, args: argparse.Namespace) -> Network:
    """The user's explicit inputs, each marked as user-entered."""
    if args.n is not None:
        for p in net.pipes:
            net = net.with_pipe(replace(p, n=args.n, source=mark_user(p.source, "n")))
    downstream = {p.downstream for p in net.pipes}
    for s in net.structures:
        if s.kind == "outfall" and args.tailwater is not None:
            net = net.with_structure(
                replace(
                    s,
                    tailwater=args.tailwater,
                    source=mark_user(s.source, "tailwater"),
                )
            )
        elif s.kind != "outfall" and s.id not in downstream:
            changed = {}
            if args.catchment is not None:
                changed["catchment"] = args.catchment
            if args.known_flow is not None:
                changed["known_flow"] = Quantity(args.known_flow, "cfs")
            if changed:
                net = net.with_structure(
                    replace(s, **changed, source=mark_user(s.source, *changed))
                )
    return net


def _import(args: argparse.Namespace) -> int:
    result = read_exchange(args.exchange)
    print(f"{args.exchange}: pfsuite-network import")
    for line in result.report():
        print(f"  {line}")
    if not result.ok:
        print("import failed: nothing written", file=sys.stderr)
        return EXIT_INVALID
    net = _apply(result.network, args)
    print(f"resolved {len(net.pipes)} pipe(s) and {len(net.structures)} structure(s)")
    if args.into is None:
        return EXIT_OK
    try:
        base, _ = read_project(args.into)
        project = replace(base, network=net)
        # Validate the combination (catchment ids, methods) before writing.
        project = Project.from_dict(project.to_dict())
    except ProjectError as exc:
        print("cannot add the network to the project:", file=sys.stderr)
        for path, msg in exc.problems:
            print(f"  {path}: {msg}", file=sys.stderr)
        return EXIT_INVALID
    out = args.output or args.into
    save_project(project, out)
    still = project.network.missing_inputs()
    for _, message in still:
        print(f"  still missing: {message}")
    print(f"project written to {out}")
    return EXIT_OK


def add_parser(sub) -> None:
    net = sub.add_parser("network", help="storm sewer networks")
    nsub = net.add_subparsers(dest="network_command", required=True)
    imp = nsub.add_parser(
        "import",
        help="import a PFSUITE network exchange (docs/pfsuite-network-exchange.md)",
    )
    imp.add_argument("exchange", type=Path)
    imp.add_argument(
        "--into", type=Path, help="project to add the network to (replaces its network)"
    )
    imp.add_argument("-o", "--output", type=Path, help="write here instead of --into")
    imp.add_argument("--n", type=float, help="Manning's n for every imported pipe")
    imp.add_argument(
        "--tailwater",
        type=_tailwater,
        help=f"outfall starting HGL: one of {', '.join(TAILWATER_MODES)}; "
        f"elevation=<ft> for a known tailwater",
    )
    imp.add_argument(
        "--catchment", help="Rational catchment id draining to the upstream inlet"
    )
    imp.add_argument(
        "--known-flow", type=float, help="known flow at the upstream inlet, cfs"
    )
    imp.set_defaults(func=_import)
