"""Record a Hydraflow .stm file's topology facts, as parsed by Storm-Profile.py.

Read-only: neither file is modified. Usage:
    python -I tools/extract_stm_topology.py <folder> <out.json>

<folder> holds System CA_CB_edited.stm and Storm-Profile.py.

Wrote tests/data/stm-system-ca-cb.topology.json (2026-10-26).
"""

import ast
import hashlib
import json
import re
import sys
from pathlib import Path

folder = Path(sys.argv[1])
out = Path(sys.argv[2])
stm = folder / "System CA_CB_edited.stm"
parser = folder / "Storm-Profile.py"
# Storm-Profile.py imports PDF and plotting libraries at the top; only its
# two parsing functions are needed, so they are taken from its source as is.
tree = ast.parse(parser.read_text(encoding="utf-8"))
wanted = [
    n
    for n in tree.body
    if isinstance(n, ast.FunctionDef) and n.name in ("parse_stm", "_convert_value")
]
assert len(wanted) == 2
ns = {"re": re}
exec(compile(ast.Module(body=wanted, type_ignores=[]), str(parser), "exec"), ns)
header, lines = ns["parse_stm"](str(stm))


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


KEEP = {
    "Line No.": "line_no",
    "Line ID": "line_id",
    "Downstream Line No.": "downstream_line_no",
    "X Coord Dn": "x_dn",
    "Y Coord Dn": "y_dn",
    "X Coord Up": "x_up",
    "Y Coord Up": "y_up",
    "Line Length": "length_ft",
    "Inlet ID": "inlet_id",
    # Recorded to show what the file does NOT provide (zeros in this file).
    "Rise": "rise_in",
    "Invert Elev Dn": "invert_dn",
    "Invert Elev Up": "invert_up",
    "Drainage Area": "drainage_area",
    "Ground / Rim Elev Up": "rim_up",
    "N-Value": "n",
    "Runoff Coeff.": "runoff_c",
    "Junction Loss Coeff": "junction_k",
}
doc = {
    "description": (
        "Topology and geometry facts of a real Hydraflow Storm Sewers project "
        "file, as parsed by Storm-Profile.py's parse_stm. Diameters, inverts, "
        "rims and drainage areas are zero in the file: this is NOT a hydraulic "
        "validation case."
    ),
    "source": {
        "file": "System CA_CB_edited.stm",
        "folder": str(folder),
        "sha256": sha(stm),
        "parser": (
            "Storm-Profile.py parse_stm and _convert_value, "
            "taken unchanged from its source"
        ),
        "parser_sha256": sha(parser),
        "format_header": "Hydraflow Storm Sewers 2003",
        "total_lines": header.get("Total No. Lines"),
        "metric": header.get("Metric Units?"),
    },
    "lines": [
        {KEEP[k]: v for k, v in rec.items() if k in KEEP}
        for _, rec in sorted(lines.items())
    ],
}
out.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
print(len(doc["lines"]), "lines;", doc["source"]["sha256"][:12])
