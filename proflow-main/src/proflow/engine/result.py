"""Common result type for solvers that can fail for reasons other than bad code."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Generic, TypeVar

T = TypeVar("T")


class Status(StrEnum):
    SUCCESS = "success"
    INVALID_INPUT = "invalid_input"
    UNSUPPORTED_REGIME = "unsupported_regime"
    NO_CONVERGENCE = "no_convergence"


@dataclass(frozen=True)
class SolveResult(Generic[T]):
    """A solver outcome. value is None unless status is SUCCESS.

    method identifies the equation/algorithm and its revision, e.g.
    "weir.rectangular/1", so saved results record what produced them.
    """

    status: Status
    method: str
    value: T | None = None
    warnings: tuple[str, ...] = ()
    message: str = ""
    iterations: int | None = None
    diagnostics: dict[str, float] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status is Status.SUCCESS
