# Storm Sewers progress (plan phase 5)

**Status, 2026-10-26.** Two slices are built.

1. **One line:** imported from a PFSUITE network exchange, completed with Manning's n, the starting HGL and the inlet's catchment, calculated (Rational flow, full-flow capacity, HGL/EGL by the standard step), shown as a profile, saved and reopened.
2. **Branching networks (tree to one outfall):** topology validation, Rational accumulation downstream with travel time (HEC-22), HGL/EGL upstream from the outfall through each junction, and every pipe's results in the CLI and the desktop app. See "Branching networks" below.

The same path works from the CLI and from the desktop app.

**Checks:**
- 450 tests pass, including the GUI tests. Ruff is clean.
- `proflow fixtures`: 50 of 50 complete cases pass, out of 52 in total. The two Storm Sewers report cases are informational.

All methods remain **experimental**.

## PFSUITE network exchange, format version 1

- **Specification:** `proflow-main/docs/pfsuite-network-exchange.md`, with its own `format_version`, separate from the project schema.
- **Producer:** PFSUITE V6 keeps its facts in the drawing: block attributes, plus XDATA for membership (`MEMB`) and value sources (`SRC`). The exporter writes those facts unresolved.
  - Structures: plan inserts with their membership and rim source.
  - Pipes: both ends in **sheet** coordinates, the grid each is drawn on, size and material.
  - Grids: their sheet-to-station/elevation numbers (`pfl:x->sta`, `pfl:y->elev`).
- **Importer:** `proflow.io.pfsuite` resolves the file.
  1. Pipe ends go through the grid conversion to station and invert.
  2. Each end links to the nearest structure on the same line, within PFSUITE's 8 ft profile snap.
  3. Plan geometry comes from the structures' plan inserts.
  4. Length is junction centre to centre, from the membership stations. The drawn run is reported alongside.
- **Unresolved links block the import.** These are: no structure in range, two equally near, both ends on one structure, or a pipe with no grid. The report lists them, and nothing reaches the project. The same applies to errors, including an exporter error diagnostic.
- **Missing hydraulic inputs are listed, never guessed:** Manning's n, the outfall's starting HGL, a catchment or known flow at the upstream inlet, and rims with source `NONE`.
- **Carlson material n:** the `pipen.dta` value is offered as a suggestion. The GUI applies it only through an explicit Use button.
- **Field sources:** every imported element keeps a `source` record. `provenance` says which program field each value came from, and a value the user later edits is marked `user`. PFSUITE fields Pro-Flow does not compute with are kept in `attributes`, and unknown fields in `extra`, both verbatim.
- **Field coverage (plan rule 3):** a test follows every supported exchange field through import, save and reopen. Others cover unknown fields, Windows-1252 text from AutoLISP, and each unresolved and invalid case.
- **Exporter draft:** `proflow-main/integrations/pfsuite/pf-export.lsp` (`PFEXPORT`). It is read-only, uses only `pf-cfg` names, and refuses metric drawings. **It has not been run in CAD.** It sits in Pro-Flow's repo, so nothing in the V6 folder changed.
- **Example:** `examples/pfsuite/one-pipe.pfsuite.json` is synthetic. It was written by hand to the spec, with the grid conversion worked out by hand. No real export exists yet.

## Hydraulics (`engine/sewer.py`, `sewer.standard_step/1`)

From the Storm Sewers manual's Computational Methods (pp. 63-66) and Starting HGLs (p. 42):

- **Standard step:** one step between the two ends of the line, with the friction slope averaged between the ends, as the manual describes.
- **Starting HGL:** known elevation, crown, normal depth, critical depth or (dc + D)/2. A start below critical depth is reset to critical, with a warning.
- **Supercritical flow:** when the energy equation cannot balance above critical depth, the upstream end is set to critical (the manual's subcritical pass) and a warning says so. The supercritical profile and hydraulic jump are **not built**.
- **Junction loss:** K·V²/2g at the upstream end, with K = 1.0 by default (end of a branch, p. 66). It is not applied at critical depth.
- **Pressure flow:** above the crown, the full-pipe area and hydraulic radius are used.
- **Capacity:** full-flow Manning on the invert slope. None on a flat or adverse line.
- **Critical depth:** solved exactly (minimum specific energy). The manual uses a closed-form equation below 0.85 D.
- **Flow:** Q = C·i(Tc)·A from the inlet's Standard Rational catchment, plus any known flow.

**Explicit outcomes:**

| Case | Outcome |
|---|---|
| Missing inputs | Invalid input, listing them |
| A network of more than one line | Unsupported |
| A downstream structure that is not an outfall | Invalid |
| Surcharge | Warning |
| Flow over capacity | Warning |
| Flat or adverse line | Warning, no capacity; normal-depth start refused |
| HGL above a rim | Warning |

## Evidence

**Independent checks** (`tests/test_sewer.py`). Expected values come from closed forms or separate integrations, not from the solver:

- Full-flow capacity matches closed-form Manning.
- Full-pipe pressure flow: the HGL rises by exactly Sf_full·L (closed form, hand check 1.813 ft).
- A normal-depth start returns normal depth upstream (uniform flow).
- Critical depth satisfies Q²T/(gA³) = 1.
- **M1 backwater:** the one-step result is within 0.01 ft of a 4000-step RK4 integration of the gradually-varied-flow equation over 150 ft. The actual difference is 0.006 ft, which is the one-step truncation the manual's method carries, kept visible rather than tuned.

**No published, fully specified one-pipe HGL example was found.** The Storm Sewers manual has none with numbers. TxDOT's HGL section describes the method without a worked example. HEC-22 was not obtained this session. A published complete case remains open.

**Public one-line report** (Wichita, 2008, `fixtures/public/storm-one-line-hgl-assumed-n.json`): **partial, informational only.** The report prints neither n nor the starting HGL. With n = 0.013 assumed, and the start inferred as critical depth (HGL Dn is the invert plus about 1.02 ft, the critical depth of 7.07 cfs in 18 in):

| Value | Printed | Pro-Flow |
|---|---|---|
| Full capacity | 5.99 cfs | 5.98 cfs |
| HGL down | 1389.77 ft | 1389.78 ft |
| HGL up | 1390.85 ft | 1390.83 ft |
| Average of the end velocities | 4.76 ft/s | 4.73 ft/s |

The ~0.01 ft at HGL Dn is consistent with the manual's approximate critical-depth equation, against Pro-Flow's exact solution. Do not tune n or the method to these numbers.

## Branching networks (second slice)

### Topology (`model/topology.py`)

A supported network is a tree draining to one outfall. Pipes may join at a structure; flow never splits.

| Code | Level | Meaning |
|---|---|---|
| `flow_split` | unsupported | two or more pipes leave one structure (splits, diversions, parallel pipes) |
| `several_outfalls` | unsupported | pipes reach more than one outfall: calculate one system per network |
| `cycle` | error | pipes form a loop |
| `dead_end` | error | pipes end at a structure with no outlet that is not an outfall |
| `disconnected` | error | a pipe's route does not reach the outfall |
| `no_outfall`, `outfall_has_outlet`, `self_loop`, `unknown_structure`, `no_pipes` | error | as named |
| `isolated_structure` | info | a structure no pipe reaches |

Several pipes may discharge into the outfall structure itself; each starts from its tailwater. The analyser works on plain links, so the real `.stm` topology below is checked without inventing hydraulic values.

### Flow (`engine/sewer_network.py`, `sewer.rational.accumulate/1`)

From FHWA HEC-22, 3rd ed. (FHWA-NHI-10-009, 2009, rev. 2013; archived since the 4th ed., 2024). The PDF is in `reference/` (SHA-256 `9f7517de…`).

- **Section 7.5, steps 3-4 (pp. 7-31 to 7-34)**:
  - Sum C × A is carried downstream (Columns 7-8).
  - A pipe's system time is the upstream run's system time plus its section time (Column 10 + 17).
  - The intensity uses the larger of the inlet and system times (Columns 9-11).
  - Q = (sum CA) × i (Column 12).
  - Section time = L / design-flow velocity (Column 17). Example 7-3 takes that velocity from Chart 24, the partial-flow velocity at Q/Qf, which is the Manning normal-depth velocity used here.
- **Section 7.2.2 (pp. 7-26 to 7-27)**: the discharge at a point is not the sum of the inlet flows, and the flow path with the longest time defines the duration. So at a junction, the system time is the longest incoming route. Branch peaks are never added.
- **Known flows** are added and carried downstream, as Hydraflow's "Accumulate Known Qs" (Storm Sewers manual p. 16).
- **No normal depth:** a pipe with flow over its open-channel capacity, or a flat or adverse pipe, uses Q / full area for its section time, with a warning.
- **Lower flow downstream:** a flow lower than an incoming pipe's is kept, with a warning (HEC-22 7.2.2 discusses checking such cases).
- **Difference from Hydraflow:** Hydraflow's default bases pipe travel time on its Design Velocity code. Only its Enhanced Modeling option iterates on actual velocities (manual p. 43). Pro-Flow follows HEC-22's design-flow velocity instead.
- **One IDF set per system:** a network whose catchments use different IDF sets is refused.

### Hydraulics

- Pipes into the outfall start at its starting HGL.
- Every other pipe starts at the HGL Junct of the pipe it flows into (Storm Sewers manual p. 64): that pipe's HGL Up plus its junction loss K·V²/2g. The loss belongs to the line leaving the junction (p. 47). Every incoming branch starts from the same HGL Junct.
- The line solver gained a `junction` boundary. Where the junction HGL is below critical depth at an incoming pipe's outlet (the pipe drops into the structure), that pipe starts at critical depth, with a warning.
- A failed line stops the lines upstream of it, each with a message.
- **Not applied:**
  - the manual's Minimum Starting Depth;
  - Correct EGL Discrepancies;
  - automatic junction K from angles (manual pp. 16, 66). K is a per-pipe input; 1.0 is the manual's conservative value.

### Example and evidence

- **`examples/storm-y-network.proflow.json`:** two branches (A: 1.5 ac, C 0.5, inlet time 10 min; B: 1.0 ac, C 0.7, 15 min) join at manhole J1 above a 24 in outfall pipe. **Every hydraulic input is an example value**, marked `origin: example` with `provenance: example` on each element. The rainfall is the Sedgwick 100-yr FHA set used elsewhere.
- **Results:**
  - P1: Tc = max(10 + 0.881, 15 + 0.441) = 15.44 min, Q = 1.45 ac × 7.281 in/hr = 10.56 cfs.
  - The branch peaks would add to 11.56 cfs; they are not added.
  - PA and PB both start at P1's HGL Junct, 102.37 ft.
- **Independent checks** (`tests/test_sewer_network.py`). Expected values come from the IDF equation, segment geometry, Manning and the test's own root finding, not from the solver:
  - branch flows and section times;
  - sum CA, longest time, intensity and Q at P1;
  - P1's junction loss;
  - both branches starting at P1's HGL Junct;
  - the energy equation balancing on every line;
  - known-flow accumulation;
  - lower-flow and full-pipe-velocity warnings;
  - critical-depth start when a branch drops into the junction;
  - upstream failure propagation;
  - missing inputs, cycles and different IDF sets.
- **One-pipe regression:** `examples/storm-one-pipe.proflow.json` gives the same flow, capacity, HGL and EGL as the one-line solver. Its pinned values are 7.071 cfs, 6.460 cfs, 752.800 / 754.496 / 755.012 ft. It now also reports a travel time and Tc.

### A real topology: Hydraflow project file CA_CB

- **Source:** `C:\Users\jaked\.bloodwurm\Hydraflow Extension\System CA_CB_edited.stm`, SHA-256 `22b1dd9c…`, "Hydraflow Storm Sewers 2003" format, six lines.
- **How it was read:** parsed read-only by Storm-Profile.py's own `parse_stm`. Its venv's base Python is gone, so `tools/extract_stm_topology.py` takes `parse_stm` and `_convert_value` unchanged from its source. The facts are in `tests/data/stm-system-ca-cb.topology.json`, with both files' hashes. The `.stm` files were not modified, and the extension's binary was not opened.
- **Topology** (`tests/test_topology.py`): one tree. Lines 2 (CA-2) and 5 (CB-1) join at line 1's upstream junction, which the file itself names "CA-2/CB-1". The headwaters are CA-4 and CB-2, and the routes are CA-4 → CA-3 → CA-2 → CA-1 and CB-2 → CB-1 → CA-1.
- **Geometry:**
  - Each line's downstream coordinate equals its downstream line's upstream coordinate exactly.
  - Coordinates are printed to 7 significant digits (x to the foot, y to 0.1 ft). Stated lengths agree with the coordinate distances within that print precision; the worst is line CA-1, 39.74 against 40.01 ft.
- **Not a hydraulic case:** the file's diameters, inverts, rims and drainage areas are zero. Nothing is calculated on it, and no Hydraflow hydraulic equivalence is claimed.

### Interfaces

- **CLI:** `proflow run` prints, for every pipe:
  - what it flows into;
  - sum CA, Tc, i, Q, capacity and travel time;
  - HGL and EGL down / up / junction;
  - the flow and hydraulic method ids, and its warnings.

  The results document's network rows add `upstream_pipes`, `downstream_pipe`, `flow_method`, `ca_local`, `system_time`, `tc`, `travel_time` and `travel_velocity`. The earlier one-pipe keys keep their meaning.
- **Desktop:** STORM SEWERS → Sewer network.
  - A table of every pipe, plus a details card for the selected pipe.
  - Per-pipe n and K, and the upstream structure's catchment and known Q, edited for the selected pipe. Outfall and rainfall apply network-wide.
  - A profile along the selected pipe's route to the outfall, stepping at each junction. Stations are used when the route lies on one PFSUITE line.
  - Checked as real windows at 150 %: the Y network (PA and PB selected) and the one-pipe example.

## Project schema v4

The project gains an optional `network`: structures, pipes, the outfall tailwater, and the inlet's catchment link and known flow. A v3 reader rejects that key, so the schema went to v4. The v3-to-v4 migration sets the version only (`tests/data/v3-scs-user-storm.proflow.json`).

A network may be saved incomplete. `Network.missing_inputs()` lists what a calculation still needs. `examples/storm-one-pipe.proflow.json` was built with `proflow network import ... --n 0.013 --tailwater elevation=752.8 --catchment BA-2`.

## Interfaces

- **CLI:** `proflow network import FILE [--into PROJECT] [-o OUT] [--n N] [--tailwater MODE[=ELEV]] [--catchment ID] [--known-flow CFS]`. It prints the import report and writes nothing on failure. `proflow run` prints each line's flow, capacity, HGL and EGL, and `-o` adds a `network` section to the results document.
- **Desktop:** the STORM SEWERS → Sewer line page (now Sewer network; see above).
  - Import PFSUITE…, Open… and Save….
  - Manning's n shows "required" until entered, with the material n offered beside it.
  - Starting HGL, inlet catchment, and IDF and event (or a new FHA curve).
  - Results, warnings, missing inputs and the import report.
  - A profile with pipe, rims, water, HGL, EGL and Yc, the junction step at the upstream end, and the starting HGL in the title.
  - Checked as a real window at 150 %: imported (missing inputs), calculated, and failed import.

## Not built yet (next in this phase)

- **Exporter in CAD:** run `PFEXPORT` on `V6_Test.dwg` and import it. This is the first real exchange.
- **Network cases still unsupported:**
  - flow splits, diversions and parallel pipes;
  - more than one outfall per network;
  - loops;
  - Minimum Starting Depth and Correct EGL Discrepancies;
  - inlet control;
  - supercritical profiles and hydraulic jumps;
  - a minimum Tc for intensity (enter inlet times of at least 5 min where a code requires it);
  - bypass flow between inlets.
- **More checks:** a published complete one-pipe or branching case, with sizes, inverts, n and tailwater all given. CA_CB lacks them.
- **Other formats and pieces:**
  - DXF as a read-only underlay;
  - SHP background, LandXML and `.stm` (later);
  - inlets (capture, bypass, spread);
  - printable Storm Sewers report.

## Opt-in Hydraflow comparison mode (experimental)

`proflow run PROJECT --sewer-method hydraflow_ems --design-velocity V`
selects the three-pass Enhanced Modeling sequence described in the Storm
Sewers manual (pp. 43, 80): first-pass pipe travel times use the supplied
Design Velocity code in ft/s; each following pass uses the average of the
previous HGL pass's upstream and downstream pipe velocities. The final result
names `sewer.rational.hydraflow_ems_3pass/1` and reports both the travel
velocity used in pass 3 and the final hydraulic average. The original HEC-22
mode remains the default. The selected mode is a command-line calculation
option and is not stored in the v4 project file or exposed in the GUI.

`--junction-losses automatic` computes K from the plan deflection and the
upstream structure kind using the manual's pp. 16, 65-66 formula, inlet
multiplier and floors. A line at a branch end has K = 1.0. Where several pipes
enter one structure, this mode takes the largest deflection and warns: the
manual does not specify which angle governs the one K assigned to the outgoing
pipe. Coincident plan coordinates give an error rather than a guessed angle.
The default remains the project's entered per-pipe K values.

The 18 DOT tabulations are **conditional checks**, not complete fixtures:
their matching source projects and option settings are unavailable. In a
diagnostic reconstruction of the 25- and 100-year reports (74 pipe rows),
reproducible with `python proflow-main/tools/compare_dot_reports.py` when
PyMuPDF is installed,
Manning n = 0.013, the printed IDF coefficients, each report's printed outfall
HGL, and K inferred from the *10-year* report were held the same for both
modes; Design Velocity was set to an illustrative 5 ft/s, not fitted. Against
the printed Tc, mean absolute error changed from 0.218 min (default) to
0.052 min (comparison). Mean absolute flow error changed from 0.180 to
0.145 cfs. Mean absolute upstream HGL error changed from 0.402 to 0.502 ft,
so the HGL comparison did not improve. Printed inputs are rounded, the actual
Design Velocity and starting-depth/EGL options are unknown, and using
report-inferred K is not independent validation. No Hydraflow equivalence is
claimed. The manual's Minimum Starting Depth, Correct EGL Discrepancies,
inlet control, supercritical profiles and jumps remain unsupported.
