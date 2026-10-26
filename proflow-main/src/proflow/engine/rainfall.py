"""Design-storm temporal distributions as dimensionless mass curves.

A mass curve gives the fraction of total storm depth fallen by time t. Values
between tabulated points are linearly interpolated on the cumulative curve, as
in NRCS NEH 630 appendix 21B, step 2.4. Times are minutes.

No standard NRCS Type I/IA/II/III table ships yet: those need an official
tabulation (NEH 630 ch. 4 describes them but does not tabulate them).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

# Allowed misclosure of a tabulated curve at its end (tables print 3 decimals).
END_TOLERANCE = 0.0005


@dataclass(frozen=True)
class MassCurve:
    times: np.ndarray  # minutes, strictly increasing, starting at 0
    fractions: np.ndarray  # non-decreasing, 0 at t = 0, 1 at the end
    name: str = ""

    @classmethod
    def from_table(
        cls, times: Sequence[float], fractions: Sequence[float], name: str = ""
    ) -> MassCurve:
        t = np.asarray(times, dtype=float)
        f = np.asarray(fractions, dtype=float)
        if t.ndim != 1 or t.shape != f.shape or len(t) < 2:
            raise ValueError("need two or more (time, fraction) pairs")
        if t[0] != 0 or np.any(np.diff(t) <= 0):
            raise ValueError("times must start at 0 and strictly increase")
        if f[0] != 0 or np.any(np.diff(f) < 0):
            raise ValueError("fractions must start at 0 and never decrease")
        if abs(f[-1] - 1) > END_TOLERANCE:
            raise ValueError(f"fractions must end at 1, not {f[-1]:g}")
        return cls(t, f, name)

    @property
    def duration(self) -> float:
        return float(self.times[-1])

    def fraction(self, t: np.ndarray | float) -> np.ndarray | float:
        out = np.interp(t, self.times, self.fractions, left=0.0, right=1.0)
        return float(out) if np.ndim(out) == 0 else out

    def cumulative_depths(self, total_depth: float, dt: float) -> np.ndarray:
        """Cumulative depth at t = 0, dt, ... through the first step >= the end."""
        if dt <= 0:
            raise ValueError("time step must be positive")
        if total_depth < 0:
            raise ValueError("total depth must not be negative")
        n = int(np.ceil(self.duration / dt - 1e-9)) + 1
        return total_depth * np.asarray(self.fraction(np.arange(n) * dt))
