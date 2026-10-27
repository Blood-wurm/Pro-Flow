"""Documented Hydraflow junction-loss coefficient from plan deflection.

Storm Sewers manual, pp. 16 and 65-66: the coefficient belongs to the pipe
leaving the junction. The manual does not identify which incoming pipe's angle
governs when several enter. The caller must disclose its selection convention.
"""

from __future__ import annotations

import math


def deflection_degrees(
    incoming_upstream: tuple[float, float],
    junction: tuple[float, float],
    outgoing_downstream: tuple[float, float],
) -> float:
    """Absolute turn from incoming flow to outgoing flow, 0 to 180 degrees."""
    a = (junction[0] - incoming_upstream[0], junction[1] - incoming_upstream[1])
    b = (outgoing_downstream[0] - junction[0], outgoing_downstream[1] - junction[1])
    ma, mb = math.hypot(*a), math.hypot(*b)
    if not ma or not mb:
        raise ValueError("plan coordinates coincide at a pipe end")
    cosine = max(-1.0, min(1.0, (a[0] * b[0] + a[1] * b[1]) / (ma * mb)))
    return math.degrees(math.acos(cosine))


def automatic_k(angle: float, kind: str) -> float:
    """Hydraflow's angle rule, with the manual's inlet/manhole minimum."""
    if not math.isfinite(angle) or not 0 <= angle <= 180:
        raise ValueError("deflection angle must be between 0 and 180 degrees")
    if kind not in ("inlet", "manhole", "junction"):
        raise ValueError("junction kind must be inlet, manhole or junction")
    inlet = kind == "inlet"
    if angle >= 90:
        return 1.5 if inlet else 1.0
    coefficient = 1.0 - ((90.0 - angle) / 90.0) ** 2
    return max(0.5 if inlet else 0.15, coefficient * (1.5 if inlet else 1.0))
