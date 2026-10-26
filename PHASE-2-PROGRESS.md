# Phase 2 progress: rainfall and runoff foundation

Status 2026-10-25: two slices done. Slice 1: limb and endpoint rules, mass-curve storms, incremental excess, NRCS unit hydrographs, convolution. Slice 2: SCS catchments in the project model and CLI, user-supplied storm library, hydrograph resampling and combination with volume checks. 171 tests pass, Ruff clean, `proflow fixtures` 7/7 complete cases pass. All methods remain **experimental**.

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

## Open items

- **NRCS Type I/IA/II/III 24-h tables**: still no official tabulation in hand; NEH 630 ch. 4 describes but does not tabulate them. `MassCurve` accepts any table once one is sourced.
- **Hydraflow SCS storms** are built from piecewise cubic polynomials whose coefficients the manual does not give (p. 77). Pro-Flow's tabulated storms will not be claimed equal to Hydraflow's until compared.
- **Hydraflow Tp snapping**: the manual says Tp is recomputed to fall on a time-step increment when D changes (p. 75). Pro-Flow only offers an explicit Tp override; the snapping rule is unconfirmed.
- **Off-grid Rational peak**: Pro-Flow reports the sampled peak plus a warning. Whether Hydraflow prints CiA or the sampled ordinate for off-grid Tc is unknown; needs a published case with Tc not a whole minute.
- **Project-level combination**: `combine` exists in the engine only; combine/divert nodes in the project model belong with Phase 4 watershed objects.
- **Hydrograph start offsets**: all hydrographs start at t = 0 (as the manual's combine does). Lagged inputs from routing will need an offset rule.
- **Not yet built in Phase 2**: IDF table import/export and fit diagnostics, synthetic (IDF-based) and Huff storms, hydrograph splitting/diversion, SBUH and DeKalb Rational.
