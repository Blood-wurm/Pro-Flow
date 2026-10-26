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

import math
from dataclasses import dataclass

from proflow.engine.rainfall import MassCurve


@dataclass(frozen=True)
class StandardDistribution:
    id: str
    name: str
    source: str  # citation, including table and edition
    time_percent: tuple[float, ...]
    rain_percent: tuple[float, ...]
    # Recommended storm durations in minutes, (low, high]: low exclusive,
    # high inclusive, math.inf for no upper limit.
    recommended_duration_min: tuple[float, float] | None = None
    duration_guidance: str = ""  # where that range comes from
    legacy: bool = False
    status_note: str = ""  # e.g. superseded by a later publication
    hydraflow_check: str = ""  # how this compares with Hydraflow's version

    def mass_curve(self, duration_min: float) -> MassCurve:
        if duration_min <= 0:
            raise ValueError("storm duration must be positive")
        times = [duration_min * p / 100 for p in self.time_percent]
        fractions = [p / 100 for p in self.rain_percent]
        return MassCurve.from_table(times, fractions, self.name)

    def duration_warnings(self, duration_min: float) -> tuple[str, ...]:
        if self.recommended_duration_min is None:
            return ()
        low, high = self.recommended_duration_min
        if low < duration_min <= high:
            return ()
        lower = f"over {low / 60:g} h" if low > 0 else ""
        upper = "" if math.isinf(high) else f" up to {high / 60:g} h"
        span = f"{lower}{upper}".strip()
        return (
            f"{self.name} is recommended for storms {span} "
            f"({self.duration_guidance}); this storm lasts {duration_min / 60:g} h",
        )


_TIME = tuple(range(0, 101, 5))

# ISWS Circular 173 (Huff, 1990), Table 3, "Median Time Distributions of Heavy
# Storm Rainfall at a Point", 5 to 95 % of storm time, one column per quartile.
# Identical in ISWS Bulletin 71 (Huff and Angel, 1992), Table 10. Only the
# first quartile is also printed in the Hydraflow Hydrographs manual. The 0 %
# and 100 % points are definitional.
# fmt: off
_C173_TABLE_3 = {
    1: (0, 16, 33, 43, 52, 60, 66, 71, 75, 79, 82,
        84, 86, 88, 90, 92, 94, 96, 97, 98, 100),
    2: (0, 3, 8, 12, 16, 22, 29, 39, 51, 62, 70,
        76, 81, 85, 88, 91, 93, 95, 97, 98, 100),
    3: (0, 3, 6, 9, 12, 15, 19, 23, 27, 32, 38,
        45, 57, 70, 79, 85, 89, 92, 95, 97, 100),
    4: (0, 2, 5, 8, 10, 13, 16, 19, 22, 25, 28,
        32, 35, 39, 45, 51, 59, 72, 84, 92, 100),
}
# fmt: on

_ORDINAL = {1: "first", 2: "second", 3: "third", 4: "fourth"}
_SHORT = {1: "1st", 2: "2nd", 3: "3rd", 4: "4th"}

# Recommended durations (min, (low, high]) and where they come from.
_DURATIONS = {
    1: (
        (0.0, 360.0),
        "ISWS Bulletin 71: first-quartile for design durations of 6 h and less; "
        "Circular 173: first- or second-quartile for 12 h or less; "
        "Hydraflow: Huff 1st for <= 6 h",
    ),
    2: (
        (360.0, 720.0),
        "ISWS Bulletin 71: second-quartile for 6.1 to 12 h; Circular 173: first- "
        "or second-quartile for 12 h or less; Hydraflow: Huff 2nd for > 6 to 12 h",
    ),
    3: (
        (720.0, 1440.0),
        "ISWS Circular 173: 12.1 to 24 h storms most likely third-quartile; "
        "Bulletin 71: 12.1-24 h storms tend to the third quartile; "
        "Hydraflow: Huff 3rd for > 12 to 24 h",
    ),
    4: (
        (1440.0, math.inf),
        "ISWS Circular 173: fourth-quartile recommended beyond 24 h; Bulletin 71: "
        "storms over 24 h tend to the fourth quartile; Hydraflow: Huff 4th > 24 h",
    ),
}

_SUPERSEDED = (
    "Legacy: ISWS Bulletin 75 states that it supersedes the time distributions "
    "of Bulletin 70, Circular 172 and Circular 173."
)


def _huff(quartile: int) -> StandardDistribution:
    ordinal = _ORDINAL[quartile]
    durations, guidance = _DURATIONS[quartile]
    if quartile == 1:
        check = (
            "Matches the Huff 1st table printed in the Hydraflow Hydrographs manual."
        )
    else:
        check = (
            f"Open: the Hydraflow Hydrographs manual does not print its Huff "
            f"{_SHORT[quartile]} table, so equivalence with Hydraflow is unconfirmed."
        )
    return StandardDistribution(
        id=f"huff-q{quartile}-point-median-isws-c173-1990",
        name=(
            f"Huff {ordinal}-quartile, point, median "
            "(legacy; ISWS Circular 173, 1990, Table 3)"
        ),
        source=(
            "Huff, F.A., 1990. Time Distributions of Heavy Rainstorms in Illinois. "
            f"Illinois State Water Survey Circular 173, Table 3, {ordinal}-quartile "
            "column. Same values: ISWS Bulletin 71 (Huff and Angel, 1992), Table 10."
        ),
        time_percent=_TIME,
        rain_percent=_C173_TABLE_3[quartile],
        recommended_duration_min=durations,
        duration_guidance=guidance,
        legacy=True,
        status_note=_SUPERSEDED,
        hydraflow_check=check,
    )


HUFF_Q1_POINT_C173 = _huff(1)
HUFF_Q2_POINT_C173 = _huff(2)
HUFF_Q3_POINT_C173 = _huff(3)
HUFF_Q4_POINT_C173 = _huff(4)

STANDARD_DISTRIBUTIONS: dict[str, StandardDistribution] = {
    d.id: d
    for d in (
        HUFF_Q1_POINT_C173,
        HUFF_Q2_POINT_C173,
        HUFF_Q3_POINT_C173,
        HUFF_Q4_POINT_C173,
    )
}
