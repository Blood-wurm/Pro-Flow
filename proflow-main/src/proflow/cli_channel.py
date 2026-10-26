"""`proflow channel`: uniform flow in a rectangular, triangular or trapezoidal
channel (Express "Channels"): known Q, known depth, or a Q vs. depth table."""

from __future__ import annotations

import argparse
import sys

from proflow.engine import channel
from proflow.engine.channel import FlowState, Trapezoid
from proflow.io.units import UnitError, to_internal

EXIT_OK, EXIT_FAILED, EXIT_INVALID = 0, 1, 2

COLUMNS = (
    ("Depth ft", "depth", "{:.3f}"),
    ("Q cfs", "flow", "{:.3f}"),
    ("Area ft2", "area", "{:.3f}"),
    ("Vel ft/s", "velocity", "{:.3f}"),
    ("Wp ft", "wetted_perimeter", "{:.3f}"),
    ("Yc ft", "critical_depth", "{:.3f}"),
    ("Top W ft", "top_width", "{:.3f}"),
    ("EGL ft", "egl", "{:.3f}"),
    ("Froude", "froude", "{:.3f}"),
)


def _side_slopes(text: str) -> tuple[float, float]:
    values = [float(v) for v in text.split(",")]
    if len(values) == 1:
        values *= 2
    if len(values) != 2:
        raise argparse.ArgumentTypeError("give z or z_left,z_right")
    return values[0], values[1]


def _shape(args: argparse.Namespace) -> Trapezoid:
    z1, z2 = args.side_slopes or (0.0, 0.0)
    b = args.bottom_width or 0.0
    if args.section == "rectangular" and (z1 or z2):
        raise ValueError("a rectangular section has no side slopes")
    if args.section == "triangular" and b:
        raise ValueError("a triangular section has no bottom width")
    return Trapezoid(b, z1, z2)


def _table(rows: list[FlowState]) -> str:
    head = "  ".join(f"{h:>9}" for h, _, _ in COLUMNS)
    lines = [head]
    for s in rows:
        lines.append(
            "  ".join(f"{fmt.format(getattr(s, k)):>9}" for _, k, fmt in COLUMNS)
        )
    return "\n".join(lines)


def _run(args: argparse.Namespace) -> int:
    try:
        shape = _shape(args)
        slope = to_internal("slope", args.slope, args.slope_unit)
    except (ValueError, UnitError) as exc:
        print(exc, file=sys.stderr)
        return EXIT_INVALID
    step = 0.01 if args.express_steps else None
    if args.known_q is not None:
        r = channel.normal_depth(
            shape, args.known_q, slope, args.n, args.total_depth, step
        )
        rows = [r.value] if r.ok else []
    elif args.known_depth is not None:
        r = channel.flow_at_depth(
            shape, args.known_depth, slope, args.n, args.total_depth, step
        )
        rows = [r.value] if r.ok else []
    else:
        r = channel.rating(shape, args.total_depth, args.rating, slope, args.n, step)
        rows = r.value or []
    title = f"{args.section} channel, S = {slope:g} ft/ft, n = {args.n:g}"
    print(f"{title}  [{r.method}, experimental]")
    if not r.ok:
        print(f"{r.status}: {r.message}")
        return EXIT_INVALID if r.status == "invalid_input" else EXIT_FAILED
    print(_table(rows))
    if len(rows) == 1:
        print(f"flow regime: {rows[0].regime}")
    if step:
        print("depths rounded up to 0.01 ft as published Express reports show")
    return EXIT_OK


def add_parser(sub) -> None:
    p = sub.add_parser("channel", help="uniform flow in a prismatic channel")
    p.add_argument("section", choices=["rectangular", "triangular", "trapezoidal"])
    p.add_argument("--bottom-width", type=float, help="ft")
    p.add_argument("--side-slopes", type=_side_slopes, help="z or z_left,z_right")
    p.add_argument("--total-depth", type=float, required=True, help="ft")
    p.add_argument("--slope", type=float, required=True)
    p.add_argument("--slope-unit", default="%", help="%% (as Express) or ft/ft")
    p.add_argument("--n", type=float, required=True, help="Manning's n")
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--known-q", type=float, help="cfs")
    mode.add_argument("--known-depth", type=float, help="ft")
    mode.add_argument("--rating", type=int, metavar="INCREMENTS", help="1 to 50")
    p.add_argument(
        "--express-steps",
        action="store_true",
        help="report iterated depths rounded up to 0.01 ft, as Express does",
    )
    p.set_defaults(func=_run)
