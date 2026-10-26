"""Named, source-backed dimensionless storm distributions.

Each entry carries its exact source and edition, and is only added once every
printed ordinate has been checked against that source (fixtures in
fixtures/storms/). Distributions without a sourced table stay out; see
PHASE-2-PROGRESS.md for the list.

A distribution is stored in percent of storm time and percent of storm
rainfall, and scaled to a storm duration as a MassCurve, so it is
interpolated linearly on the cumulative curve like any other storm.
"""

from __future__ import annotations

from dataclasses import dataclass

from proflow.engine.rainfall import MassCurve


@dataclass(frozen=True)
class StandardDistribution:
    id: str
    name: str
    source: str  # citation, including table and edition
    time_percent: tuple[float, ...]
    rain_percent: tuple[float, ...]
    max_duration_min: float | None = None  # recommended upper limit, if any
    duration_guidance: str = ""  # where that limit comes from
    status_note: str = ""  # e.g. superseded

    def mass_curve(self, duration_min: float) -> MassCurve:
        if duration_min <= 0:
            raise ValueError("storm duration must be positive")
        times = [duration_min * p / 100 for p in self.time_percent]
        fractions = [p / 100 for p in self.rain_percent]
        return MassCurve.from_table(times, fractions, self.name)

    def duration_warnings(self, duration_min: float) -> tuple[str, ...]:
        if self.max_duration_min is None or duration_min <= self.max_duration_min:
            return ()
        limit = self.max_duration_min / 60
        return (
            f"{self.name} is recommended for storms of {limit:g} h or less "
            f"({self.duration_guidance}); this storm lasts {duration_min / 60:g} h",
        )


# ISWS Circular 173 (Huff, 1990), Table 3, "Median Time Distributions of Heavy
# Storm Rainfall at a Point", first-quartile column, 5 to 95 % of storm time.
# Identical in ISWS Bulletin 71 (Huff and Angel, 1992), Table 10, and in the
# Hydraflow Hydrographs manual, "Huff Distributions". The 0 % and 100 % points
# are definitional; of these sources only the Hydraflow manual prints them.
# fmt: off
_HUFF_Q1_POINT_C173 = (
    0, 16, 33, 43, 52, 60, 66, 71, 75, 79, 82,
    84, 86, 88, 90, 92, 94, 96, 97, 98, 100,
)
# fmt: on
HUFF_Q1_POINT_C173 = StandardDistribution(
    id="huff-q1-point-median-isws-c173-1990",
    name="Huff first-quartile, point, median (ISWS Circular 173, 1990, Table 3)",
    source=(
        "Huff, F.A., 1990. Time Distributions of Heavy Rainstorms in Illinois. "
        "Illinois State Water Survey Circular 173, Table 3, first-quartile column."
    ),
    time_percent=tuple(range(0, 101, 5)),
    rain_percent=_HUFF_Q1_POINT_C173,
    max_duration_min=6 * 60,
    duration_guidance=(
        "ISWS Bulletin 71 recommends first-quartile curves for design durations "
        "of 6 h and less; Circular 173 recommends first- or second-quartile for "
        "12 h or less, first-quartile being more prevalent up to 6 h; Hydraflow "
        "lists Huff 1st for durations <= 6 h"
    ),
    status_note=(
        "ISWS Bulletin 75 states that it supersedes the time distributions of "
        "Bulletin 70, Circular 172 and Circular 173."
    ),
)

STANDARD_DISTRIBUTIONS: dict[str, StandardDistribution] = {
    d.id: d for d in (HUFF_Q1_POINT_C173,)
}
