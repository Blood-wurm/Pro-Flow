"""Hydraflow custom design storm (.cds) files.

Format as documented in the Hydraflow Hydrographs manual, "Custom Design
Storms" (printed p. 66), one value per line:

    Time Interval in minutes
    Precip Ratio at Time Interval 1
    Precip Ratio at Time Interval 2
    ...
    Precip Ratio at Time Interval n        (n <= 2,880)

The ratio at time zero is not written; it is zero. Ratios are cumulative
fractions of the storm depth and "typically ... begin at 0 and increase to
1.0". The manual says nothing more, so this reader is strict: every non-blank
line must be one number, blank lines are allowed only at the end, and the
ratios must never decrease and must end at 1 (as any Pro-Flow mass curve must).

Hydraflow requires the runoff time step to equal the storm's interval (same
page). Pro-Flow instead interpolates the cumulative curve onto any step, as for
every other storm.
"""

from __future__ import annotations

import math

import numpy as np

from proflow.engine.rainfall import MassCurve

MAX_RATIOS = 2880


class CdsError(ValueError):
    pass


def read_cds(text: str, name: str = "") -> tuple[MassCurve, float]:
    """Return the storm as a mass curve (minutes) and its interval in minutes."""
    lines = text.lstrip("﻿").splitlines()
    while lines and not lines[-1].strip():
        lines.pop()
    if len(lines) < 2:
        raise CdsError("need an interval line and at least one ratio")
    values = []
    for k, line in enumerate(lines, start=1):
        try:
            values.append(float(line.strip()))
        except ValueError:
            raise CdsError(f"line {k}: {line.strip()!r} is not a number") from None
    interval, ratios = values[0], values[1:]
    if not interval > 0:
        raise CdsError(f"line 1: time interval must be positive, got {interval:g}")
    if len(ratios) > MAX_RATIOS:
        raise CdsError(f"{len(ratios)} ratios; the format allows {MAX_RATIOS}")
    times = interval * np.arange(len(ratios) + 1)
    try:
        curve = MassCurve.from_table(times, [0.0, *ratios], name)
    except ValueError as exc:
        raise CdsError(str(exc)) from None
    return curve, interval


def write_cds(curve: MassCurve, interval: float) -> str:
    """Sample a mass curve every interval minutes, to the first step >= its end."""
    if not interval > 0:
        raise CdsError("time interval must be positive")
    n = math.ceil(curve.duration / interval - 1e-9)
    if n > MAX_RATIOS:
        raise CdsError(
            f"{n} ratios needed at {interval:g} min; the format allows {MAX_RATIOS}"
        )
    ratios = np.atleast_1d(curve.fraction(interval * np.arange(1, n + 1)))
    lines = [f"{interval:g}", *(repr(float(r)) for r in ratios)]
    return "\n".join(lines) + "\n"
