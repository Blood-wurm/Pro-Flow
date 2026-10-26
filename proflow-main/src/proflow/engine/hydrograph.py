"""Hydrograph container: flows sampled at a fixed time step.

Time-grid rules (Pro-Flow, after Hydraflow Hydrographs manual p. 81, which
samples Rational hydrographs at a fixed interval with straight-line
interpolation between computed points):

- Ordinates sit at t = k * dt, k = 0, 1, ...; breakpoints that fall between
  grid times are not inserted, so every hydrograph can be combined and routed
  ordinate by ordinate.
- A shape that ends between grid times gets one more ordinate, at the first
  grid time at or after the end, with zero flow.
- Peak, time to peak and volume are taken from the ordinates; volume is the
  trapezoidal integral, i.e. the exact area under the straight lines joining
  the ordinates. When sampling misses the shape's true peak or area by more
  than SAMPLING_TOLERANCE, the solver says so in a warning and reports the
  continuous values as diagnostics.
- A hydrograph has zero flow after its last ordinate. One whose last ordinate
  is not zero is treated as truncated, and operations that extend it say so.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from proflow.engine.result import SolveResult, Status

SAMPLING_TOLERANCE = 0.001  # relative
RESAMPLE = "hydrograph.resample/1"
COMBINE = "hydrograph.combine/1"


@dataclass(frozen=True)
class Hydrograph:
    """Flow ordinates in cfs at t = 0, dt, 2*dt, ... minutes."""

    dt: float
    flows: np.ndarray

    @classmethod
    def from_breakpoints(
        cls, times: list[float], flows: list[float], dt: float
    ) -> Hydrograph:
        """Sample a piecewise-linear hydrograph defined by (time, flow) points."""
        if dt <= 0:
            raise ValueError("time step must be positive")
        n = int(np.ceil(times[-1] / dt - 1e-9)) + 1
        t = np.arange(n) * dt
        return cls(dt, np.interp(t, times, flows, right=0.0))

    @staticmethod
    def shape_diagnostics(times: list[float], flows: list[float]) -> dict[str, float]:
        """Peak and volume (ft^3) of the continuous piecewise-linear shape."""
        return {
            "shape_peak_cfs": float(max(flows)),
            "shape_volume_ft3": float(np.trapezoid(flows, times) * 60.0),
        }

    def sampling_warnings(
        self, times: list[float], flows: list[float]
    ) -> tuple[str, ...]:
        shape = self.shape_diagnostics(times, flows)
        warnings = []
        for label, sampled, exact, unit in (
            ("peak", self.peak, shape["shape_peak_cfs"], "cfs"),
            ("volume", self.volume, shape["shape_volume_ft3"], "ft3"),
        ):
            if exact > 0 and abs(sampled - exact) / exact > SAMPLING_TOLERANCE:
                warnings.append(
                    f"sampled {label} {sampled:.6g} {unit} differs from the "
                    f"continuous {label} {exact:.6g} {unit}: a breakpoint falls "
                    f"between {self.dt:g}-min ordinates"
                )
        return tuple(warnings)

    @property
    def times(self) -> np.ndarray:
        return np.arange(len(self.flows)) * self.dt

    @property
    def peak(self) -> float:
        return float(self.flows.max())

    @property
    def time_to_peak(self) -> float:
        return float(self.times[np.argmax(self.flows)])

    @property
    def volume(self) -> float:
        """Runoff volume in cubic feet."""
        return float(np.trapezoid(self.flows, dx=self.dt * 60.0))


def _truncated(hyd: Hydrograph) -> bool:
    return len(hyd.flows) > 0 and hyd.flows[-1] != 0


def _relative(residual: float, reference: float) -> float:
    return abs(residual) / reference if reference > 0 else abs(residual)


def resample(hyd: Hydrograph, dt: float) -> SolveResult[Hydrograph]:
    """Re-sample a hydrograph onto a new time step.

    The new ordinates lie on the straight lines joining the old ones, out to the
    first new grid time at or after the old end. Refining loses nothing;
    coarsening can cut the peak and change the volume, and both are reported.
    """
    if dt <= 0:
        return SolveResult(Status.INVALID_INPUT, RESAMPLE, message="dt must be > 0")
    if len(hyd.flows) == 0:
        return SolveResult(Status.INVALID_INPUT, RESAMPLE, message="no ordinates")
    end = hyd.times[-1]
    n = int(np.ceil(end / dt - 1e-9)) + 1
    flows = np.interp(np.arange(n) * dt, hyd.times, hyd.flows, right=0.0)
    out = Hydrograph(dt, flows)
    residual = out.volume - hyd.volume
    warnings = []
    if _truncated(hyd):
        warnings.append(
            f"input ends at {hyd.flows[-1]:.6g} cfs, not zero; flow after its last "
            "ordinate is taken as zero"
        )
    if _relative(residual, hyd.volume) > SAMPLING_TOLERANCE:
        warnings.append(
            f"resampling to {dt:g} min changes volume by {residual:.6g} ft3 "
            f"({residual / hyd.volume:+.2%})"
            if hyd.volume > 0
            else f"resampling to {dt:g} min changes volume by {residual:.6g} ft3"
        )
    if _relative(out.peak - hyd.peak, hyd.peak) > SAMPLING_TOLERANCE:
        warnings.append(
            f"resampling to {dt:g} min lowers the peak from {hyd.peak:.6g} to "
            f"{out.peak:.6g} cfs"
        )
    return SolveResult(
        Status.SUCCESS,
        RESAMPLE,
        out,
        warnings=tuple(warnings),
        diagnostics={
            "volume_in_ft3": hyd.volume,
            "volume_out_ft3": out.volume,
            "volume_residual_ft3": residual,
            "peak_in_cfs": hyd.peak,
            "peak_out_cfs": out.peak,
        },
    )


def combine(
    hydrographs: list[Hydrograph], dt: float | None = None
) -> SolveResult[Hydrograph]:
    """Ordinate-by-ordinate sum, all starting at t = 0.

    Hydraflow requires equal time steps (Hydrographs manual p. 83); so does
    this, unless dt is given, in which case every input is resampled to dt
    first and any resampling warnings are passed on. Shorter hydrographs are
    padded with zero flow. The combined volume is checked against the sum of
    the (resampled) input volumes; padding a hydrograph that ends above zero is
    the one way they can differ, and it is reported.
    """
    if not hydrographs:
        return SolveResult(Status.INVALID_INPUT, COMBINE, message="nothing to combine")
    warnings: list[str] = []
    if dt is None:
        steps = sorted({h.dt for h in hydrographs})
        if len(steps) > 1:
            listed = ", ".join(f"{s:g}" for s in steps)
            return SolveResult(
                Status.INVALID_INPUT,
                COMBINE,
                message=f"time steps differ ({listed} min); resample or pass dt",
            )
        inputs = list(hydrographs)
    else:
        inputs = []
        for i, h in enumerate(hydrographs):
            r = resample(h, dt)
            if not r.ok:
                return SolveResult(r.status, COMBINE, message=f"input {i}: {r.message}")
            warnings += [f"input {i}: {w}" for w in r.warnings]
            inputs.append(r.value)
    step = inputs[0].dt
    n = max(len(h.flows) for h in inputs)
    total = np.zeros(n)
    for i, h in enumerate(inputs):
        total[: len(h.flows)] += h.flows
        if len(h.flows) < n and _truncated(h):
            warnings.append(
                f"input {i} ends at {h.flows[-1]:.6g} cfs and is padded with zero "
                "flow, adding volume"
            )
    out = Hydrograph(step, total)
    volume_in = float(sum(h.volume for h in inputs))
    residual = out.volume - volume_in
    if _relative(residual, volume_in) > SAMPLING_TOLERANCE:
        warnings.append(
            f"combined volume differs from the inputs by {residual:.6g} ft3"
        )
    return SolveResult(
        Status.SUCCESS,
        COMBINE,
        out,
        warnings=tuple(warnings),
        diagnostics={
            "volume_in_ft3": volume_in,
            "volume_out_ft3": out.volume,
            "volume_residual_ft3": residual,
        },
    )
