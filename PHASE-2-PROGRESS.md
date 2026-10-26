# Phase 2 progress: rainfall and runoff foundation

Status 2026-10-26: five slices done. Slice 1: limb and endpoint rules, mass-curve storms, incremental excess, NRCS unit hydrographs, convolution. Slice 2: SCS catchments in the project model and CLI, user-supplied storm library, hydrograph resampling and combination with volume checks. Slice 3: CI, IDF table import/export, FHA fit diagnostics. Slice 4: Huff first-quartile storm (source-checked), `.cds` import/export, schema v3. Slice 5: Huff second to fourth quartiles (legacy, source-checked). Totals now in PHASE-3-PROGRESS.md. All methods remain **experimental**.

## Rules settled

| Rule | Decision | Source |
|---|---|---|
| Rational limbs | Rising limb = ALF × Tc (peak at ALF·Tc), receding = RLF × Tc; intensity always at Tc. ALF/RLF allowed on Standard Rational only; the project model rejects them on Modified. | Hydrographs manual pp. 23–24, 81 |
| Time grid | Equal-interval ordinates at k·dt from 0; breakpoints between grid times are not inserted; straight-line interpolation. | Hydrographs manual p. 81 (1-min interval, straight-line interpolation) |
| Off-grid end | One extra ordinate at the first grid time ≥ the end, flow 0. | Pro-Flow rule |
| Peak / volume | From ordinates; volume = trapezoid through ordinates. If sampling misses the continuous peak or volume by > 0.1 %, the result carries a warning and `shape_peak_cfs` / `shape_volume_ft3` diagnostics. | Pro-Flow rule (rule 5 of plan: no silent forcing) |
| Storm interpolation | Linear on the cumulative mass curve; 0 before the storm, 1 after. | NEH 630 app. 21B step 2.4 |
| Excess | Runoff equation on accumulated rainfall, differenced per interval. | NEH 630 ch. 10; table 21B-4 |
| Convolution | Excess in (k·dt, (k+1)·dt] drives the unit hydrograph from k·dt: Q(n·dt) = Σ R_k U_(n−k). | NEH 630 app. 21B step 6; reproduces table 21B-7 |
| Tp | Two named equations: 16A-7 `dt/2 + 0.6 Tc` and 16A-10 `(Tc + dt)/1.7` (Hydraflow's form). Optional override for a rounded Tp. | NEH 630 app. 16A; Hydrographs manual p. 74 |
| Unit hydrograph | `curvilinear` = table 16-1 scaled, linear interpolation, ends at 5 Tp, K = 484 only. `triangular` = Hydraflow's form: peak K·A/Tp at Tp, base sized to hold 1 in (2.67 Tp at K = 484). | NEH 630 ch. 16; Hydrographs manual pp. 73–74 |
| Step size | Warning when dt > 0.25 Tp. | NEH 630 app. 16A |
| SCS mass balance | Hydrograph runoff depth = equation depth × sampled unit-hydrograph depth; `mass_balance_residual_in` always reported; warning when the sampled unit hydrograph holds more than 1 % away from 1 in. | NEH 630 example 16-1 step 3 (< 1 % negligible) |
| Resample | New ordinates on the straight lines through the old ones, out to the first new grid time ≥ the old end. Volume and peak in/out reported; warning when either changes by > 0.1 %. Refining is exact. | Pro-Flow rule, same interpolant as the time grid |
| Combine | Ordinate sum from t = 0. Equal time steps required (Hydraflow); with an explicit `dt` every input is resampled first and its warnings passed on. Shorter inputs padded with zero; a truncated input (last ordinate ≠ 0) is reported because padding adds volume. Volume residual reported. | Hydrographs manual p. 83 |
| Zero after the end | A hydrograph has zero flow after its last ordinate. | Pro-Flow rule |

## Evidence (fixtures in `proflow-main/fixtures/nrcs/`, PDFs in `reference/nrcs/`)

| Fixture | Checks | Result |
|---|---|---|
| `nrcs-21b-incremental-runoff` | 25 cumulative rain, 24 cumulative runoff, 23 incremental runoff (tables 21B-3/4) | pass, max diff 0.00047 in |
| `nrcs-21b-unit-hydrograph-tp` | Tp by 16A-10 = 4.76 h | pass |
| `nrcs-21b-unit-hydrograph` | qp 1452, 25 ordinates (table 21B-6) | pass, max diff 0.49 cfs |
| `nrcs-21b-convolution` | 49 ordinates (table 21B-7) | pass, max diff 0.49 cfs; hour 6 printed `3335` is a recorded source error (column total requires 335) |
| `nrcs-ch16-example-16-1-uh-peak` | Tp by 16A-7 = 1.53 h, qp 1455 | pass |
| `test_appendix_21b_end_to_end` | full pipeline vs 21B-7 through hour 20, tolerance derived from the appendix's intermediate rounding | pass |

Source discrepancy recorded, not edited: table 21B-7 column (c) prints 22 cfs at hour 20, table 21B-6 (and table 16-1) give 16. The convolution fixture uses 21B-7's column as printed; the unit-hydrograph fixture checks 21B-6.

## Project model and CLI (slice 2)

- `rainfall.storms`: user-supplied mass curve (`times` with unit, `fractions`) plus a depth per return period. Validated with the same rules as `MassCurve`; every SCS catchment's storm must have a depth for every project event.
- `method: "scs"` catchments: `storm`, `area`, `cn`, `tc`, `unit_hydrograph` (`curvilinear` = NRCS table 16-1, `triangular` = Hydraflow-described), `tp_equation` (default 16A-10), `ia_ratio` (default 0.2), `shape_factor` (triangular only; rejected on curvilinear), optional `tp` override.
- Results rows carry method-specific quantities (Rational: intensity; SCS: precipitation, runoff depth, unit-hydrograph Tp) and diagnostics. CLI prints them with any warnings.
- `examples/scs-user-storm.proflow.json`: one basin through both unit-hydrograph forms, 2- and 100-yr. Illustrative only; the storm is app. 21B's 5-point curve with example depths.
- Schema is now `proflow-project` **v2**: a v1 reader rejects `rainfall.storms`, SCS catchments and `ascending_limb_factor`, so files that can hold them get a new version. v1 files load through an explicit migration (`proflow/io/migrations.py`) that writes the v2 defaults (`storms: []`, Rational limb factors 1, SCS `tp_equation` 16A-10 and `ia_ratio` 0.2) and keeps any of those fields a pre-release v1 file already has. Saving always writes v2; `proflow run` notes when it read an older file. Policy: bump only when an older reader cannot safely interpret a newly written file.

## IDF tables and fit diagnostics (slice 3)

- **Import**: NOAA Atlas 14 point-frequency CSV (depth or intensity, English or metric; no published spec, so the reader accepts only the layout NOAA's files show and rejects anything else) and Pro-Flow's own `proflow-idf-table/1` CSV (documented in `io/idf_table.py`, explicit duration and intensity units). Hydraflow `.IDF` files are **not** read: no published format.
- **Export**: `proflow idf convert` (any table to `proflow-idf-table/1`, lossless round trip) and `proflow idf export` (a project IDF set evaluated at chosen durations; default 5-60 min by 5, as in Hydraflow's rainfall report).
- **Fit**: `proflow idf fit` fits FHA per return period over a 5-60 min window by default (Hydraflow's table window), optionally with D restricted to multiples of `--d-step`, and writes an `idf_set` a project accepts plus a fit report. Diagnostics: B, D, E, point count, duration range, max absolute and relative residual, RMS log residual. Warnings: any point > 1 % off (concave data, Express manual p. 54), intensity not falling with duration, three points (exact fit), D at the search limit.
- **Interpolation policy**: between durations the equation is used, never table interpolation. Fitted curves are supported over their fit window; polynomial IDF outside 8-180 min (Hydrographs manual p. 80) gets a warning in project results.
- **Hydraflow evidence**: the Hydraflow Rainfall Report on p. 35 of the Storm Sewers source PDF (`SedgwickCoKS.IDF`, Hydrographs v9.22) gives B, D, E and a 12-duration table. Fixtures in `fixtures/idf/`: printed coefficients reproduce the printed table (6 cases) and Pro-Flow's fit to the printed table reproduces it (6 cases; B, D, E shown against Hydraflow's for information). Tolerance = 0.005 display + the effect of rounding B, D, E to 4 decimals; Hydraflow evaluates unrounded coefficients (differences fall on both sides of the table, so it is not truncation). Hydraflow's D values are multiples of 0.1 (observation only).
- **Storm Sewers flow explained**: the same report's full-precision 100-yr coefficients (62.2794, 10.1, 0.6624) give 7.365 in/hr and 7.07 cfs, matching the one-line tabulation; the 7.13 cfs gap came from the printed equation's rounded E (0.66). New complete fixture `storm-one-line-rational-flow-sedgwick-idf`, assumption stated; the original partial pipe case is unchanged.
- **NOAA source note**: NOAA's intensity file is not exactly its depth file divided by duration at 12 of 190 cells (3, 6, 12 h; up to 0.55 %). Pro-Flow converts by definition; the test pins those cells.
- **CI**: `.github/workflows/ci.yml` runs Ruff lint, Ruff format check, pytest and `proflow fixtures` on Ubuntu and Windows with Python 3.11 and 3.12, tools pinned (ruff 0.17.2, pytest 9.1.1). Python 3.11 has not been run locally.

## Huff first quartile and .cds (slice 4)

- **Source check**: every printed first-quartile ordinate (5 to 95 % of storm time) is identical in ISWS Circular 173 (Huff, 1990) Table 3 (scanned, PDF p. 18), ISWS Bulletin 71 (Huff and Angel, 1992) Table 10 (PDF p. 29) and the Hydraflow Hydrographs manual (printed pp. 67-68). Three fixtures in `fixtures/storms/`, each transcribed separately from its source. 0 and 100 % are definitional; only the Hydraflow manual prints them. PDFs in `reference/isws/` (Circular 173 from isws.illinois.edu/statecli/RF/circular173.pdf; Bulletin 71 from a third-party host, gcdcswm.com).
- **Label**: `huff-q1-point-median-isws-c173-1990`, "Huff first-quartile, point, median (ISWS Circular 173, 1990, Table 3)". Results rows carry `storm_distribution`, `storm_source` and `storm_source_status`.
- **Superseded**: ISWS Bulletin 75 states that it supersedes the time distributions of Bulletin 70, Circular 172 and Circular 173. Pro-Flow says so with every result; Bulletin 75 itself has not been obtained.
- **Duration guidance**: warning above 6 h. Bulletin 71: first-quartile for design durations of 6 h and less. Circular 173: first- or second-quartile for 12 h or less, first-quartile more prevalent up to 6 h. Hydraflow: Huff 1st for <= 6 h.
- **Interpolation**: linear on the cumulative curve between printed points, as for every storm. Hydraflow says only that it "interpolates between values as needed".
- **Project**: a storm distribution may be `{"standard": <id>, "duration": <time>}` instead of a mass curve. A v2 reader rejects that, so the schema is **v3**; v2 files migrate by version number only. `examples/scs-huff-q1.proflow.json` runs both unit-hydrograph forms for 2, 10, 100 yr with the Sedgwick report's Huff-1st depths and an illustrative 3 h duration; runoff volumes are within 0.3 % of Q x A.
- **.cds**: `proflow storm import-cds` (makes a `rainfall.storms` entry, depths from `--depth RP=DEPTH`) and `proflow storm export-cds` (any project storm, any interval, at most 2,880 ratios), per the manual's format. The reader is strict where the manual is silent (one number per line, blank lines only at the end, ratios must not fall and must end at 1). Hydraflow requires the runoff step to equal the storm interval; Pro-Flow interpolates instead. `proflow storm list` shows each built-in distribution with its source and status.

## Huff second to fourth quartiles (slice 5)

- Every printed ordinate of the second-, third- and fourth-quartile columns (19 each) checked against ISWS Circular 173 Table 3 (re-read from the scan) and Bulletin 71 Table 10 (text layer): all 57 agree. Six fixtures in `fixtures/storms/`, one per quartile per source.
- All four Huff curves are now labeled **legacy** (`legacy` flag, "legacy" in the name, results carry `storm_legacy`), since Bulletin 75 supersedes the Circular 173 / Bulletin 71 distributions. Ids unchanged: `huff-q{1-4}-point-median-isws-c173-1990`.
- Each curve has its recommended duration range with sources: Q1 up to 6 h, Q2 over 6 to 12 h, Q3 over 12 to 24 h, Q4 over 24 h (Bulletin 71, Circular 173, and Hydraflow's own table agree on the split). Outside the range: a warning, not an error.
- Hydraflow equivalence: Q1 matches the manual's printed table; Q2 to Q4 are **open** (`storm_hydraflow_check` says so in every result) because the manual does not print them.
- `examples/scs-huff-quartiles.proflow.json`: each quartile at a duration inside its range (6, 12, 24, 48 h), same illustrative 6.0 in depth, both unit-hydrograph forms. Volumes within 0.14 % of Q x A; peak time as a fraction of storm duration 0.31, 0.47, 0.66, 0.85 for quartiles 1 to 4 (a test checks the order).

## Storm methods: status

| Method | Hydraflow source | Status in Pro-Flow |
|---|---|---|
| User mass curve (any table) | — | **Supported** (`rainfall.storms`) |
| Custom design storm, `.cds` file | Hydrographs manual p. 66 documents the format (interval in minutes, then cumulative ratios; zero at t = 0 assumed; ≤ 2,880 values) | **Supported**: import and export |
| NRCS Type I, IA, II, III (24 h) | Manual names them; Hydraflow builds them from piecewise cubic polynomials whose coefficients it does not print (p. 77) | **Unsupported**: no official tabulation or coefficients in hand |
| Type II FL (24 h) | Named only (p. 65) | **Unsupported**: no source |
| SCS 6-hr | Named only (p. 65) | **Unsupported**: no source |
| Synthetic (IDF-based) | Method described: IDF depth increments over the interval, largest near the centre, others alternating symmetrically; duration ≥ 2 Tc and ≤ 6 h (pp. 66, 77) | **Experimental / not built** until a complete output case can check the block ordering |
| Huff 1st quartile | Manual p. 67-68 prints the cumulative table, citing ISWS Bulletin 70/71 and Circular 173, Table 3 | **Supported**, checked against all three sources (point, median) |
| Huff 2nd, 3rd, 4th quartile | Cited by Hydraflow but not printed in its manual | **Supported** (legacy), checked against Circular 173 Table 3 and Bulletin 71 Table 10; Hydraflow equivalence open |
| Huff Indy | Named only ("used primarily in Indianapolis") | **Unsupported**: no source identified |

The Hydraflow Rainfall Report above also prints that project's precipitation table (SCS 24-hour, SCS 6-hr, Huff-1st, Huff-Indy and Custom depths per return period), a possible source of check depths once those distributions exist.

## Open items

- **NRCS Type I/IA/II/III 24-h tables**: still no official tabulation in hand; NEH 630 ch. 4 describes but does not tabulate them. `MassCurve` accepts any table once one is sourced.
- **Hydraflow SCS storms** are built from piecewise cubic polynomials whose coefficients the manual does not give (p. 77). Pro-Flow's tabulated storms will not be claimed equal to Hydraflow's until compared.
- **Hydraflow Tp snapping**: the manual says Tp is recomputed to fall on a time-step increment when D changes (p. 75). Pro-Flow only offers an explicit Tp override; the snapping rule is unconfirmed.
- **Off-grid Rational peak**: Pro-Flow reports the sampled peak plus a warning. Whether Hydraflow prints CiA or the sampled ordinate for off-grid Tc is unknown; needs a published case with Tc not a whole minute.
- **Project-level combination**: `combine` exists in the engine only; combine/divert nodes in the project model belong with Phase 4 watershed objects.
- **Hydrograph start offsets**: all hydrographs start at t = 0 (as the manual's combine does). Lagged inputs from routing will need an offset rule.
- **Not yet built in Phase 2**: storm generation (see table above), hydrograph splitting/diversion, SBUH and DeKalb Rational, Hydro-35 / western-states map-data IDF creation (equations on Hydrographs manual pp. 78-79).
- **IDF provenance in projects**: a project's IDF set does not yet record the table or fit it came from (would be a schema change); `proflow idf fit --json` keeps the report beside it.
