# Pro-Flow full-suite implementation plan for Claude

## Goal

Build an original, usable Pro-Flow application covering the workflows of **Hydraflow Express, Hydraflow Hydrographs, and Hydraflow Storm Sewers**. Use the three product manuals, published engineering methods, and documented input/output reports as references. Implement methods independently and make every supported input, assumption, unit, result, and limitation visible to the user.

This is a build plan, not a claim of complete vendor equivalence. A method is ready for engineering use only after its stated validity range, independent calculations, conservation checks where applicable, and representative project workflows pass. Label unvalidated methods experimental in the application and reports.

## Starting point and references

- Code: `proflow-main/src/proflow/engine/` implements FHA and polynomial IDF evaluation, an FHA fit, time-of-concentration methods, Rational hydrographs, and SCS curve-number runoff. `model/`, `io/`, `graph/`, `reports/`, and `gui/` are empty package shells. Keep the engine independent of the UI.
- Tests: `proflow-main/tests/` has 53 passing tests. One checks a rounded public Hydrographs Rational case. Use `proflow-main/.venv/Scripts/python.exe -m pytest -q` and `proflow-main/.venv/Scripts/ruff.exe check .` on this machine.
- Manuals: `Hydraflow-Manual.pdf` (Express), `reference/Hydraflow-Hydrographs-Manual.pdf`, `reference/Hydraflow-Storm-Sewers-Manual.pdf`, and `HEC-HMS_Users_Manual_4.2.pdf`. Record the edition/page that supports each implemented workflow or equation; verify against current public agency guidance before claiming standards compliance.
- Published reports: `reference/public_cases/README.md` identifies one small case per product, with original PDFs and scope limits. The Express weir case is reproducible; the Hydrographs Rational case is reproducible given the printed intensity; the Storm Sewers row lacks settings needed for strict numerical acceptance.

## Established product findings to carry forward

The earlier investigation established these narrow 2027 product facts. Use them as requirements already captured here; no further product-internals investigation is part of this implementation plan.

- Express Rational and Hydrographs modified Rational evaluate the FHA IDF form as `i = B / (t + D)^E` and the polynomial form as `i = A + B ln(t) + C ln(t)^2 + D ln(t)^3`. The cubic is the intensity itself. `engine/idf.py` was corrected accordingly; preserve that behavior and its regression test.
- Express Rational calculates peak flow from intensity, runoff coefficient, and area. This identifies a calculation path, but does not establish its complete time stepping, rounding, unit conversion, or input validation behavior.
- The three products have separate calculation paths. Shared-looking rainfall and time-of-concentration features should use common Pro-Flow components, while their user workflows and acceptance cases remain distinct.
- The earlier investigation identified Express Rational/SCS/storage/channel/weir, Hydrographs runoff/combine/reach/pond, and Storm Sewers pipe sizing/HGL/inlet calculations as real product scope. It did **not** establish the full equations, defaults, regimes, or numerical outputs for those methods. Implement and validate them from documented engineering methods and complete reference cases.

## Rules for the implementation

1. Use one internal unit convention per quantity and convert at the UI/import/export boundary. Store dimensional units in the model; show both entered and normalized values where rounding matters. Never mix slope percent with ft/ft or time minutes with seconds implicitly.
2. Separate immutable input models, numerical results, and presentation. Solvers receive explicit inputs and return values, diagnostics, convergence status, and method identifiers; they do not read GUI state.
3. Version the native Pro-Flow project schema from its first release. Preserve unknown fields during documented imports when practical. Implement exchange formats only from published specifications, with round-trip tests for every supported field.
4. Keep evidence with each method: source, equation/algorithm, units, supported domain, fixture cases, numerical tolerance, and remaining gaps. Compare unrounded values when available; otherwise compare within the source report's displayed precision.
5. Treat hydraulic transitions, surcharge, overtopping, reverse slopes, disconnected networks, and nonconvergence as explicit outcomes. Do not silently force a result outside a supported regime.
6. Add tests for methods, conversions, file round trips, and end-to-end workflows when they establish a meaningful behavior. Avoid tests that merely copy the implementation's own numbers.

## Shared architecture

Use these modules as a target layout; adjust names if the code calls for it, while preserving the boundaries:

| Package | Responsibility |
| --- | --- |
| `model/` | Versioned project, rainfall/IDF, catchment, hydrograph, structure, node, pipe, and scenario input/result types; validation rules |
| `engine/` | Hydrology, open-channel flow, culvert/inlet/weir hydraulics, routing, pipe network, and numerical root-solving utilities |
| `io/` | Native project format, documented exchange formats, schema migration, unit conversion, provenance |
| `graph/` | Time-series, rating-curve, profile, and network-view data preparation |
| `reports/` | Reproducible tabular and plotted reports with units, inputs, assumptions, warnings, method status, and source/version |
| `gui/` | Three connected workspaces: Express calculators, Hydrographs project/routing, Storm Sewers network; shared rainfall library and project browser |

Define stable solver result types early. Include `status` (success, invalid input, unsupported regime, no convergence), warnings, iteration count where relevant, and diagnostic values. A single scenario should be runnable without a GUI so tests and batch work can use the same path.

## Delivery sequence

### 0. Baseline and reference cases

**Build:** Create a small machine-readable fixture format recording product/version, source page, input units, inputs, displayed outputs, tolerances, and missing fields. Enter the three public cases without inventing absent values. Add independent hand or published-method checks for each initial solver. Keep source PDFs and fixture data separate from generated results.

**Done when:** A fixture runner can identify complete versus partial cases and report pass/fail with units and tolerances. The existing 53 tests continue to pass. The Storm Sewers public row is marked informational until its boundary settings are known.

### 1. Core project model and native persistence

**Build:** Define a versioned native project with shared rainfall library, units, scenarios, catchments, structures, hydrographs, nodes, pipes, and calculation settings. Add validation and JSON-based open/save. Separate user-entered values from calculated values. Provide a small command-line runner for a project or fixture before building the GUI.

**Done when:** Open-save-open preserves every modeled input; invalid units/references produce actionable errors; result files record method and project version; a clean environment can run the CLI and tests.

### 2. Rainfall and runoff foundation

**Build:** Finish IDF tables, import/export, precipitation distributions, interpolation policy, and fit diagnostics. Extend existing Rational and SCS code to time-varying rainfall, runoff excess, unit hydrograph convolution, explicit time-grid handling, and mass balance. Add reusable hydrograph resampling, combination, splitting, and volume calculations. Make numerical integration and endpoint rules explicit.

**Done when:** Published IDF/runoff cases and the public Hydrographs Rational case match at stated precision; rainfall and runoff volume checks pass; off-grid time steps, zero rainfall, extreme coefficients, and both display unit systems behave predictably. Do not infer an unavailable IDF file from a report's one printed intensity.

### 3. Express calculators

**Build in vertical slices:**

1. Weirs and open channels: rectangular/trapezoidal geometry, Manning normal depth, critical depth, specific energy, rating curves, and supported sharp-/broad-crested weir cases.
2. Hydrology calculator: connect IDF, time of concentration, Rational and SCS outputs, detention target calculations, and printed reports.
3. Inlets and culverts: supported inlet capture/bypass cases; culvert inlet/outlet control, tailwater, headwater, critical/normal depth, overtopping, and sizing.

For each slice, implement input form, solver, result table, plot, and report together. State supported geometries and flow regimes; show a clear unsupported result outside them.

**Done when:** The public Express weir case reproduces its reported depth/area/velocity within display rounding; each other calculator has independent worked examples, regime-boundary tests, monotonicity checks where appropriate, and at least one end-to-end project/report workflow. Do not promote inlet or culvert design outputs until transition cases pass.

### 4. Hydrographs project and routing

**Build:** Model watershed objects and dependencies; Rational, modified Rational, SCS and user-supplied hydrographs; combine/divert; reach routing; pond stage-storage-discharge; outlet structures; detention sizing and drawdown. Compute in dependency order and detect cycles or missing upstream references. Expose hydrograph ordinates, volume, peak, time to peak, storage, and mass-balance residuals.

**Done when:** Multi-watershed and pond projects open, calculate, graph, save, and report; routing conserves volume within a documented tolerance; pond storage never becomes silently negative; dry, full, overflow, and nonconvergent cases have explicit outcomes.

### 5. Storm Sewers network

**Build:** Create catchment/inlet/node/pipe/outfall model; tree/network connectivity checks; Rational accumulation and travel-time propagation; pipe capacity and hydraulic/energy grade calculations; inlet capture and bypass; tailwater/backwater; design sizing and profile view. Add LandXML exchange for fields covered by its published specification and round-trip tests. Defer unsupported loops, pumps, or special structures with clear diagnostics.

**Done when:** Independent one-pipe and branching-network examples verify units, flow accumulation, pipe capacities, and HGL/EGL; adverse cases cover surcharge, tailwater, reverse/flat slope, disconnected links, and capacity exceedance. The public one-line report is used for a qualitative comparison until its omitted roughness/boundary settings are recovered. Native projects and supported LandXML fields round-trip.

### 6. Operator application and release evidence

**Build:** A desktop UI with project browser and the three workspaces, shared rainfall library, editable tables/forms, validation before run, plots, network/profile views, and exportable reports. Show units, defaults, source of imported values, warnings, and method status at the point of use. Bundle example projects and a concise user guide. Keep the CLI available for reproducible batch checks.

**Done when:** A new user can create, save, reopen, calculate, inspect, and export a small project in each workspace. Run the test suite and fixture runner from a clean install/package, record their results, and distinguish source tests, published-example matches, and packaged-app smoke tests in the release notes.

## Practical work order for the first Claude pass

1. Read the current engine modules, four test files, three Hydraflow manuals, and public-case README. Summarize the first deliverable in an issue/checklist without rewriting the existing research notes.
2. Implement Phase 0's fixture schema and runner. Enter the three public cases with explicit completeness labels and source links; move the existing Hydrographs case to use the shared fixture if that improves clarity.
3. Implement Phase 1's minimal project model and native JSON round trip, plus a CLI path that calculates the existing Rational fixture.
4. Run tests and Ruff. Report exact files changed, case results, open questions, and which phase is ready next. Do not present a partial solver as full-suite completion.

## Prioritization and decisions

The whole suite is the scope, but ship one validated vertical slice at a time. The original order placed Hydrographs routing before Storm Sewers; the user's current priority is to start Storm Sewers now, using the Express and hydrology foundation already built. Start with the versioned PFSUITE network exchange and one-pipe Storm Sewers workflow described in `CLAUDE.md`. Return to Hydrographs routing and remaining Express CLI work after that slice. Reuse shared rainfall, hydrograph, units, project, and reporting components across all three. If a source case lacks inputs or a method's validity range is unclear, mark that gap and continue with an independently documented case rather than tuning to a rounded output.

## Phase 2 public technical sources

- [NRCS National Engineering Handbook, Part 630, Chapter 4: Storm Rainfall Depth and Distribution](https://directives.nrcs.usda.gov/sites/default/files2/1720460743/Chapter%204%20-%20Storm%20Rainfall%20Depth%20and%20Distribution.pdf), especially section 630.0403. It explains temporal distributions and the classic Type I, IA, II, and III families; it does not itself provide a ready-to-import complete numeric table for every family.
- [NRCS National Engineering Handbook, Part 630, Chapter 10: Estimation of Direct Runoff from Storm Rainfall](https://directives.nrcs.usda.gov/sites/default/files2/1720460920/Chapter%2010%20-%20Estimation%20of%20Direct%20Runoff%20from%20Storm%20Rainfall.pdf) for curve-number runoff and incremental excess.
- [NRCS National Engineering Handbook, Part 630, Chapter 16: Hydrographs](https://directives.nrcs.usda.gov/sites/default/files2/1712930620/7303.pdf) for the dimensionless unit-hydrograph ordinates, timing, convolution, and worked examples.
- [NRCS Appendix 21B](https://directives.nrcs.usda.gov/sites/default/files2/1712930631/29119.pdf), tables 21B-3 through 21B-6, gives a **specific worked** 24-hour cumulative rainfall sequence and runoff/unit-hydrograph checks. Treat that sequence as its stated example, not as a substitute for all standard Type I/IA/II/III tables.

Record the exact edition, table, time interval, units, and interpolation rule for each adopted rainfall sequence. Keep legacy standard distributions separate from location-specific NOAA-derived distributions, which may replace them in a jurisdiction.
