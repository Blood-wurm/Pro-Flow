# Pro-Flow

Pro-Flow is an experimental Python hydrology and hydraulics suite in development. Its planned workspaces cover Express calculations, watershed hydrographs and routing, and storm sewer networks. The current code implements selected hydrology methods and a small rectangular-weir calculation; it is **not yet a design-ready replacement** for the full Hydraflow suite.

## Run the current project

The Python package lives in `proflow-main/` and requires Python 3.11 or newer.

```powershell
cd proflow-main
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m proflow fixtures
.\.venv\Scripts\python.exe -m proflow run examples\scs-user-storm.proflow.json -o results.json
```

For development checks, install `pytest` and `ruff` into the virtual environment, then run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\ruff.exe check .
```

The fixture runner distinguishes complete published examples from a partial Storm Sewers report. See `reference/public_cases/README.md` and the `source` fields in `proflow-main/fixtures/` for links, page numbers, and known source limitations.

## Project notes

- `CLAUDE-IMPLEMENTATION-PLAN.md`: full-suite implementation order and acceptance checks.
- `FIRST-PASS-CHECKLIST.md` and `PHASE-2-PROGRESS.md`: completed slices, evidence, and open items.
- `HYDRAFLOW-RESEARCH.md`: earlier research and scope notes.

Reference PDFs and installation media are kept locally and are excluded from Git. The tracked notes and fixtures record their source links and hashes where available. No third-party binaries or installer files are part of this repository.
