# Hydraflow investigation and Pro-Flow plan

Status: full-suite static investigation underway, 2026-10-25. Official Civil 3D 2027 installation media is saved under `installers/Civil3D-2027-English/` (see its README for provenance and hashes). Signed Express, Hydrographs, and Storm Sewers binaries and packaged sample projects have been extracted for static analysis; none of the applications has been run for differential testing. See `analysis/BINARY-FINDINGS.md` and `analysis/Civil3D-2027/samples/README.md` for the evidence ledger and sample inventory.

## Scope and evidence

The supplied `Hydraflow-Manual.pdf` is the **2010 Hydraflow Express Extension** guide (84 PDF pages). Autodesk's 2010 [Hydrographs guide](https://images.autodesk.com/adsk/files/hydrographs.pdf) and [Storm Sewers guide](https://images.autodesk.com/adsk/files/storm_sewers.pdf) are saved under `reference/`. Express covers culverts, channels, inlets, hydrology, and weirs; Hydrographs covers watershed and detention routing; Storm Sewers covers pipe-network analysis. **All three are in scope**, with separate file formats and solvers. The existing `.stm` examples and `Hydraflow Extension` program in this workspace concern Storm Sewers reports; that program is not an Autodesk Hydraflow executable. The 2010 manuals may not describe every 2027 binary behavior.

Sources: local Express manual, PDF pages 5-11, 13-30, 33-46, 47-67, 69-78; [Autodesk feature overview](https://help.autodesk.com/cloudhelp/2025/ENU/Civil3D-UserGuide/files/GUID-F11FAAD6-F3D3-4FC7-8315-BF8329E5E35B.htm); [Autodesk launch instructions](https://help.autodesk.com/cloudhelp/2025/ENU/Civil3D-UserGuide/files/GUID-51E33273-8631-4320-A8A1-7FA7B6B8B3CC.htm).

The local search found no installed Civil 3D. Autodesk says Hydraflow is normally included in Civil 3D; the official 2027 installer and extracted, signed binaries are now available locally for static payload inspection. The installer version, origin, hashes, and launcher signature are recorded in `installers/Civil3D-2027-English/README.md`; binary hashes and call-path evidence are in `analysis/BINARY-FINDINGS.md`. Do not infer numerical behavior from names or strings alone.

Small published Express, Hydrographs, and Storm Sewers report cases are captured in `reference/public_cases/README.md`. The Express weir has enough inputs for a hand calculation. The Hydrographs Rational case has enough inputs to check the hydrograph given its printed rainfall intensity and is covered by a source test. The Storm Sewers report lacks roughness and boundary settings, so it is reconnaissance rather than a strict parity fixture. All three reports predate the extracted 2027 binaries.

Online acquisition check (2026-10-25): Autodesk lists Hydraflow as part of the main Civil 3D installation ([installation components](https://help.autodesk.com/cloudhelp/2025/ENU/Civil3D-Installation/files/GUID-0155E9D7-D48B-4849-AD47-A8993A44B023.htm)); I found no separate official public Hydraflow download. Autodesk offers Civil 3D through its [trial and education page](https://www.autodesk.com/products/civil-3d/free-trial), but says available installers appear in the user's [Autodesk Account](https://www.autodesk.com/support/download-install/individuals/download/where-to-download-software-and-updates) after trial or education access is established. Its **Direct download** format provides offline installation media ([download method](https://www.autodesk.com/support/download-install/individuals/configure/install-your-product)). Public Autodesk-hosted URLs from an Autodesk Community post supplied both installer parts, which were downloaded and verified locally as described above. No authenticated Autodesk account is connected here.

## Current Pro-Flow boundary

`proflow-main/src/proflow/engine/` contains:

| Area | Implemented now | Express behavior still to establish or build |
| --- | --- | --- |
| IDF | FHA and polynomial evaluation; FHA fit from a table | `.idf` parsing/writing, exact Autodesk fit and interpolation, precipitation manager, version and round-trip behavior |
| Time of concentration | Sheet, shallow, channel, Kirpich, FAA, SCS lag | Exact dialog rules, defaults, unit conversions, limits and rounding |
| Rational hydrographs | Standard and modified triangular/trapezoidal curves | Vendor ordinate/time-step equivalence, detention storage, target-Q/outlet sizing, drawdown and duration optimization |
| SCS runoff | Curve-number excess depth and composite values | Design-storm distributions, unit hydrograph, convolution, hydrograph outputs |
| Culverts, channels, inlets, weirs | None | Geometry, regimes, rating curves, design options and solver validation |
| Application | Engine functions and 53 passing source tests, including one rounded public Hydrographs output check | Project model, GUI, file I/O, reports, export and user workflow |

The manual explicitly describes an input grid, Run action, result grid, graph, reports, `.hxp` projects, `.idf` curves and `.pcp` precipitation files (PDF pages 7-11). Its hydrology chapter describes the SCS unit hydrograph, Rational variants, IDF setup and detention outputs (PDF pages 47-67). These are documented behaviors, **not** proof of the private numerical implementation. Most current tests check formulas and internally generated examples. The one public Hydrographs comparison checks rounded output from an older version, not 2027 parity.

## Reverse-engineering workflow

1. **Acquire and preserve evidence.** The official Civil 3D/Hydraflow files are now acquired. Keep product, build, file hashes, Authenticode signatures and exact source recorded. Keep reference inputs and outputs separate from Pro-Flow-generated results.
2. **Map the actual product.** Identify Express, Hydrographs and Storm Sewers executables/modules, their project formats, dialogs, callable solver paths and shared libraries. Treat embedded names as leads. Trace call paths or observe controlled runs before claiming an algorithm.
3. **Build a differential corpus.** In all three products, vary one input at a time for each chosen solver. Include ordinary, boundary and invalid cases, both unit systems, known Q/depth and rating curves where applicable. Save input files, screenshots/reports and output tables with version and display precision.
4. **Explain discrepancies.** Compare raw or maximally precise results where available. Separate numeric method, defaults, unit conversion, rounding and plotting differences. Inspect binary control flow for unresolved behavior, then rerun a discriminating input. Do not fit code merely to displayed rounded values.
5. **Implement independently.** Use public hydrology/hydraulics references and observed behavior to write original Pro-Flow code. Record which behavior is verified against Hydraflow, independently validated, approximated or still unsupported.

Priority probes for the current code: IDF coefficient fitting; sub-minute and non-integral time steps; SCS excess and convolution; modified Rational duration factor; target-Q storage; and `.idf` import/export. For later calculators, prioritize hydraulic transitions and failure boundaries (critical/normal depth, inlet/culvert control, overtopping and weir submergence), where a plausible formula can produce a misleading design result.

## Gated implementation plan

| Gate | Work | Acceptance evidence | Stop or replace criterion |
| --- | --- | --- | --- |
| 0. Reference corpus | Capture versioned cases in all three applications and build comparators with explicit units/tolerances | Repeatable vendor input/output fixtures plus independent hand/reference checks | If a product cannot be run under authorized access, keep its vendor-equivalence claims open and proceed only with independently sourced methods |
| 1. Hydrology parity | Complete IDF/precipitation I/O, SCS storm and unit hydrograph, Rational/detention workflow | Mass balance, edge cases, reference calculations and differential outputs across multiple storms | Investigate every material discrepancy before promoting a method |
| 2. Channel and weir solvers | Geometry, Manning flow, critical depth and rating curves | Monotonicity/conservation checks, published examples and vendor comparisons | Refuse unsupported geometries/regimes rather than silently extrapolate |
| 3. Inlets and culverts | HEC-22/HDS-5 regimes, transitions and sizing | Regime-boundary matrix, independent examples and vendor comparisons | Keep design outputs experimental until transitions and adverse cases pass |
| 4. Operator workflow | Project persistence, transparent inputs/defaults, run/results, plots, reports and export | Open-save-open invariance and end-to-end user workflow on real projects | Do not present a report as design-ready without provenance and method status |
| 5. Hydrographs model/routing | Runoff, combine/divert, reach and pond routing using its own binary, manual and samples | Versioned project round trips, hydrograph mass balance and independent routing benchmarks | Keep routing outputs experimental until conservation and adverse cases pass |
| 6. Storm Sewers network | Pipe and inlet model, hydraulic/energy grade, design, `.stm` and LandXML I/O | Versioned network round trips, regime-boundary cases and independent hydraulic benchmarks | Refuse unsupported network topologies and hydraulic regimes |

For engineering use, every calculation needs an explicit validity domain and independent acceptance evidence. A passing source test, a matching screenshot or a parseable `.stm` alone is insufficient evidence for design equivalence.

## Immediate next dependency

Use the packaged sample projects to map all three file formats, and continue IL tracing from the identified calculation paths. Expand the small public corpus with complete boundary cases, then run controlled 2027 input/output fixtures when authorized access is available. Signed binaries, sample inputs, manuals, and older public reports are available, but exact 2027 solver behavior and vendor parity remain open until call paths, equations, and current-version outputs have been checked.
