# First pass checklist (plan phases 0–1)

Scope: the "Practical work order for the first Claude pass" in `CLAUDE-IMPLEMENTATION-PLAN.md`. Nothing here claims suite completion; every method stays **experimental** until its validation evidence is recorded.

## Starting state (read 2026-10-25)

- Engine: FHA + polynomial IDF (`i = A + B ln t + C ln²t + D ln³t`, confirmed on Express manual p. 57), FHA fit, Tc methods, Standard/Modified Rational, SCS CN runoff depth. 53 tests pass, Ruff clean.
- Manuals read for scope: Express (weir equation p. 74 `Q = Cw L H^1.5`, Cw 3.33 sharp / 2.6 broad); Hydrographs (computational methods pp. 79–96: SCS UH, Tc, design storms, FHA/poly IDF, SBUH, Rational/Modified/DeKalb, combine, channel routing, pond stage-discharge, stage-storage, routing); Storm Sewers (standard step, junction losses, inlet control, Rational, inlets in sag/on grade, gutter spread, LandXML/DXF).
- Public cases (`reference/public_cases/`): see completeness below.

## Deliverable

- [x] Fixture format `proflow-fixture/1` (JSON): product + version, source URL/local PDF/page/SHA-256, completeness, method id, inputs with units, displayed outputs as printed (tolerance = half the last displayed digit unless stated), missing fields, assumptions.
- [x] Fixtures for the three public cases:
  - [x] Express rectangular weir — **complete**. Bottom length 0.90 ft, total depth 1.50 ft, sharp, Cw 3.33, Q 5.25 cfs → depth 1.45, area 1.31, velocity 4.01, top width 0.90.
  - [x] Hydrographs Rational (v2024, 5-yr) — **complete given the printed intensity** 3.693 in/hr; IDF file unavailable. Asc/Rec limb factors 1/1.
  - [x] Storm Sewers one-line (2008 v12.02, 100-yr) — **partial / informational**: Manning n, tailwater/starting HGL, junction and design settings absent.
- [x] Fixture runner + CLI: complete vs partial, per-output pass/fail with units and tolerance; non-zero exit only when a complete case fails.
- [x] Hydrographs Rational pytest moved onto the shared fixture.
- [x] Shared solver result type (`status`, method id, warnings, iterations, diagnostics).
- [x] Unit boundary module (one internal unit per quantity kind).
- [x] Minimal versioned project model (`proflow-project` v1): rainfall library (FHA/poly IDF), events, Rational catchments, settings; strict validation with path-qualified errors; JSON open/save round trip.
- [x] CLI `run` on a project file → result file recording method ids, method status, project schema version and Pro-Flow version; example project reproducing the Hydrographs Rational fixture.
- [x] Tests + Ruff; report files changed, case results, open questions, next phase.

## Known gaps found while reading

- Hydrographs has an **ascending** limb factor as well as receding (case prints `Asc/Rec limb fact = 1/1`); engine models receding only.
- Storm Sewers row: `62.28/(15+10.10)^0.66 = 7.42 in/hr` × 0.96 = 7.13 cfs vs reported 7.07 — do not tune.
- SCS 24-hr distribution tables must come from an official NRCS tabulation (not yet obtained).
- TR-55 Example 3-1 channel inputs unverified (`tests/test_tc.py`).
- Off-grid hydrograph end times (e.g. Modified Rational base 32.5 min at 1-min step) currently append one zero ordinate at the next step; Phase 2 must define the endpoint/integration rule.
- `reference/public_cases/README.md` Storm Sewers SHA-256 is 62 characters (missing `9D` after `...C3409D`); the fixture uses the full hash `c43dacab…a53d9e` computed from the file.
- `proflow fixtures` with no path reads `proflow-main/fixtures/`, so it works from a source checkout (editable install), not from a wheel.

## Result (2026-10-25)

102 tests pass, Ruff clean, fresh-venv editable install runs `proflow fixtures` and `proflow run`. Fixtures: Express weir PASS, Hydrographs Rational PASS, Storm Sewers one-line INFORMATIONAL (7.13 vs 7.07 cfs; capacity/HGL not computed). Next: Phase 2 (rainfall and runoff foundation).
