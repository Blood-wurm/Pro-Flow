"""Conditional DOT-report comparison; requires PyMuPDF (not a runtime dependency).

Run from anywhere with ``python tools/compare_dot_reports.py``. This reads the
public DOT PDFs only; it does not inspect Hydraflow binaries or write projects.
The reports omit n, design codes and K inputs. We assume n = 0.013, use their
printed IDF and outfall HGL, and infer K from the 10-year report for each
network before comparing both methods on the 25- and 100-year reports. A
design-code velocity of 5 ft/s is illustrative, not fitted to the reports.
These are diagnostic errors, not independent validation fixtures.
"""

import json
import re
import statistics
import sys
from pathlib import Path

import pymupdf

root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root / "proflow-main" / "src"))
from proflow.calculate import calculate_network  # noqa: E402
from proflow.engine.sewer import G, Line  # noqa: E402
from proflow.model.project import Project  # noqa: E402

folder = root / "reference" / "DOT_Reports"
base = json.loads(
    (root / "proflow-main" / "examples" / "storm-y-network.proflow.json").read_text()
)
keys = (
    "no",
    "to",
    "length",
    "area_incr",
    "area_total",
    "c",
    "ca_incr",
    "ca_total",
    "tc_inlet",
    "tc_system",
    "intensity",
    "q",
    "capacity",
    "velocity",
    "size",
    "slope",
    "invert_up",
    "invert_dn",
    "hgl_up",
    "hgl_dn",
    "rim_up",
    "rim_dn",
)


def parse(path):
    lines = pymupdf.open(path)[0].get_text().splitlines()
    match = re.search(
        r"Intensity\s*=\s*([\d.]+)\s*/\s*\(Inlet time\s*\+\s*([\d.]+)\)"
        r"\s*\^\s*([\d.]+)",
        "\n".join(lines),
    )
    rows = {}
    for at, token in enumerate(lines):
        if not re.fullmatch(r"Line [A-Z]+-\d+", token):
            continue
        row = dict(zip(keys, lines[at - len(keys) : at], strict=True))
        row["id"] = token
        for key in keys:
            if key != "to":
                row[key] = float(row[key])
        rows[int(row["no"])] = row
    return rows, tuple(float(x) for x in match.groups())


def inferred_ks(rows):
    ks = {}
    for i, r in rows.items():
        incoming = [u for u, x in rows.items() if x["to"] == str(i)]
        if not incoming:
            ks[i] = 1.0
            continue
        line = Line(r["size"] / 12, r["length"], r["invert_up"], r["invert_dn"], 0.013)
        v = line.velocity(r["q"], r["hgl_up"] - r["invert_up"])
        vh = v * v / (2 * G)
        vals = [(rows[u]["hgl_dn"] - r["hgl_up"]) / vh for u in incoming]
        ks[i] = statistics.median(vals)
    return ks


def q(value, unit):
    return {"value": value, "unit": unit}


def project_for(path, rows, bde, ks):
    period = int(path.name[:3])
    doc = json.loads(json.dumps(base))
    doc["events"] = [period]
    doc["rainfall"] = {
        "idf_sets": [
            {
                "id": "report",
                "name": "Printed DOT IDF",
                "form": "fha",
                "curves": [
                    {"return_period": period, "b": bde[0], "d": bde[1], "e": bde[2]}
                ],
            }
        ]
    }
    doc["catchments"] = []
    out = next(r for r in rows.values() if r["to"] == "End")
    network = {
        "name": path.stem,
        "plan_unit": "ft",
        "crs": None,
        "source": {},
        "structures": [
            {
                "id": "OUT",
                "name": "Outfall",
                "kind": "outfall",
                "x": 0.0,
                "y": 0.0,
                "tailwater": {"mode": "elevation", "elevation": q(out["hgl_dn"], "ft")},
            }
        ],
        "pipes": [],
    }
    for i, r in rows.items():
        network["structures"].append(
            {
                "id": f"U{i}",
                "name": r["id"],
                "kind": "inlet",
                "x": 0.0,
                "y": 0.0,
                "catchment": f"C{i}",
            }
        )
        doc["catchments"].append(
            {
                "id": f"C{i}",
                "name": r["id"],
                "method": "rational",
                "idf": "report",
                "area": q(r["area_incr"], "ac"),
                "c": r["c"],
                "tc": q(r["tc_inlet"], "min"),
                "ascending_limb_factor": 1,
                "receding_limb_factor": 1,
            }
        )
        network["pipes"].append(
            {
                "id": f"L{i}",
                "name": r["id"],
                "upstream": f"U{i}",
                "downstream": "OUT" if r["to"] == "End" else f"U{int(r['to'])}",
                "length": q(r["length"], "ft"),
                "diameter": q(r["size"], "in"),
                "invert_up": q(r["invert_up"], "ft"),
                "invert_down": q(r["invert_dn"], "ft"),
                "n": 0.013,
                "junction_k": ks[i],
            }
        )
    doc["network"] = network
    return Project.from_dict(doc)


errors = {
    "hec22": {"tc": [], "q": [], "hgl": []},
    "hydraflow_ems": {"tc": [], "q": [], "hgl": []},
}
for stem in ("AA-AE", "AF-AG", "AH", "BA-BF", "BG-BH", "CA"):
    training, _ = parse(folder / f"010_{stem}.pdf")
    ks = inferred_ks(training)
    for period in (25, 100):
        path = folder / f"{period:03}_{stem}.pdf"
        rows, bde = parse(path)
        project = project_for(path, rows, bde, ks)
        for mode in errors:
            results = calculate_network(
                project,
                sewer_method=mode,
                design_velocity=5.0 if mode == "hydraflow_ems" else None,
            )
            for result in results:
                i = int(result.pipe[1:])
                r = rows[i]
                if not result.result.ok:
                    print("FAILED", path.name, mode, i, result.result.message)
                    continue
                errors[mode]["tc"].append(
                    abs(result.quantities["tc"][0] - r["tc_system"])
                )
                errors[mode]["q"].append(abs(result.quantities["flow"][0] - r["q"]))
                errors[mode]["hgl"].append(
                    abs(result.result.value.up.hgl - r["hgl_up"])
                )

for mode, values in errors.items():
    print(mode)
    for name, items in values.items():
        print(
            name,
            len(items),
            "median",
            round(statistics.median(items), 4),
            "mean",
            round(statistics.mean(items), 4),
            "worst",
            round(max(items), 4),
        )
