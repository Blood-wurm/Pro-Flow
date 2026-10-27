# Pro-Flow

Pro-Flow is an experimental Python hydrology and hydraulics suite in development. Its planned workspaces cover Express calculations, watershed hydrographs and routing, and storm sewer networks. The current code implements the Express channel and weir calculators, rainfall and runoff methods, and Storm Sewers networks: a branching tree imported from PFSUITE or entered in a project, with Rational accumulation, capacity, travel time and an HGL/EGL profile. Every method is labelled experimental; Pro-Flow is **not yet a design-ready replacement** for the full Hydraflow suite.

## Run the current project

The Python package lives in `proflow-main/` and requires Python 3.11 or newer.

```powershell
cd proflow-main
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m proflow fixtures
.\.venv\Scripts\python.exe -m proflow run examples\scs-user-storm.proflow.json -o results.json
.\.venv\Scripts\python.exe -m proflow network import examples\pfsuite\one-pipe.pfsuite.json
.\.venv\Scripts\python.exe -m proflow run examples\storm-one-pipe.proflow.json
```

The desktop app (`pip install -e .[gui]`, then `proflow-gui`) has the Express Channel and Weir calculators and the Storm Sewers Sewer network page.

For a documented Hydraflow Storm Sewers comparison from the command line, use
`proflow run PROJECT --sewer-method hydraflow_ems --design-velocity 5 --junction-losses automatic`.
Replace `5` with the project's actual Design Velocity code in ft/s. The option
uses three flow and HGL passes; after the first pass, pipe travel time uses the
average of its upstream and downstream hydraulic velocities. Automatic junction
K uses plan deflection and structure kind. At a branch, the largest incoming
deflection is used and the result warns that Hydraflow's manual does not name
which branch angle governs. Coordinates that cannot define an angle cause an
error. Omit `--junction-losses automatic` to use the project's entered K values.
The desktop app continues to use the existing HEC-22 calculation path.

For development checks, install `pytest` and `ruff` into the virtual environment, then run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\ruff.exe check .
```

The fixture runner distinguishes complete published examples from a partial Storm Sewers report. See `reference/public_cases/README.md` and the `source` fields in `proflow-main/fixtures/` for links, page numbers, and known source limitations.

## Project notes

- `CLAUDE-IMPLEMENTATION-PLAN.md`: full-suite implementation order and acceptance checks.
- `FIRST-PASS-CHECKLIST.md`, `PHASE-2-PROGRESS.md`, `PHASE-3-PROGRESS.md` and `STORM-SEWERS-PROGRESS.md`: completed slices, evidence, and open items.
- `proflow-main/docs/pfsuite-network-exchange.md`: the PFSUITE-to-Pro-Flow network exchange, format version 1.
- `HYDRAFLOW-RESEARCH.md`: earlier research and scope notes.

Reference PDFs and installation media are kept locally and are excluded from Git. The tracked notes and fixtures record their source links and hashes where available. No third-party binaries or installer files are part of this repository.
