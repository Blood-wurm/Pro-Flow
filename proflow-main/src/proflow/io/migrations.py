"""Upgrade older "proflow-project" documents to the current schema version.

Bump the schema version only when a build that reads the older version could
not safely interpret a newly written file. Each bump adds one step here; the
reader always validates the fully migrated document.

v1 -> v2 (storm library and SCS catchments; Standard Rational limb factors):
a v1 reader rejects rainfall.storms, SCS catchments and ascending limb
factors, so files that may contain them are v2. Migration writes the v2
defaults explicitly and keeps any of those fields a v1 file already holds
(pre-release builds wrote them under v1).

v2 -> v3 (named standard storm distributions): a v2 reader rejects a storm
distribution given as {"standard", "duration"}. Every v2 file is already a
valid v3 file, so the step only sets the version.
"""

from __future__ import annotations

import copy

CURRENT_VERSION = 3

SCS_DEFAULTS = {"tp_equation": "16A-10", "ia_ratio": 0.2}
RATIONAL_DEFAULTS = {"ascending_limb_factor": 1.0, "receding_limb_factor": 1.0}


def _v1_to_v2(data: dict) -> dict:
    rainfall = data.get("rainfall")
    if isinstance(rainfall, dict):
        rainfall.setdefault("idf_sets", [])
        rainfall.setdefault("storms", [])
    for catchment in data.get("catchments") or []:
        if not isinstance(catchment, dict):
            continue
        method = catchment.get("method")
        if method == "rational":
            for key, value in RATIONAL_DEFAULTS.items():
                catchment.setdefault(key, value)
        elif method == "scs":
            for key, value in SCS_DEFAULTS.items():
                catchment.setdefault(key, value)
    data["schema_version"] = 2
    return data


def _v2_to_v3(data: dict) -> dict:
    data["schema_version"] = 3
    return data


STEPS = {1: _v1_to_v2, 2: _v2_to_v3}


def migrate(data: dict) -> tuple[dict, list[int]]:
    """Return (a migrated copy, the versions it passed through).

    Leaves the input untouched. Versions this build does not know are left for
    the reader to reject.
    """
    out = copy.deepcopy(data)
    passed = []
    version = out.get("schema_version")
    while version in STEPS:
        passed.append(version)
        out = STEPS[version](out)
        version = out["schema_version"]
    return out, passed
