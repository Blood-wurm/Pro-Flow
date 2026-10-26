# Phase 3 progress: Express calculators

Status 2026-10-26: slice 3.1 covers every Express channel section (rectangular, triangular, trapezoidal, circular, gutter, user-defined with composite n) and every Express weir type (rectangular, compound, circular, V-notch, Cipoletti, Sutro). Each has a solver, form, results, cross-section and rating plots, a Q vs. depth table and a printable report in the PySide6 desktop app. 349 tests pass, including the GUI smoke tests. Ruff is clean. `proflow fixtures` passes 50/50 complete cases. CI installs the GUI extra and requires the GUI tests. All methods remain **experimental**. Pipe and gutter flow is still not reconciled with Express (see below).

## Channel solver (`engine/channel.py`, `proflow channel`)

- Sections: rectangular, triangular (symmetric or not) and trapezoidal, as one trapezoid (b, z_left, z_right).
- Modes, as in Express (manual ch. 3): known Q (normal depth), known depth (flow), Q vs. depth (1 to 50 increments, default 10 in Express).
- Outputs: depth, Q, area, velocity (Q / A), wetted perimeter, hydraulic radius, critical depth, top width, EGL (depth + V^2/2g), Froude number and regime.
- Explicit outcomes: horizontal or adverse slope (no uniform flow), Q above full-depth capacity (capacity in diagnostics, as Express aborts), depth above total depth, invalid geometry/n/increments.
- Root finding: bisection on bracketed monotone functions (`engine/solve.py`), with iteration count.

## Findings from published Express reports

Ten Hydraflow Express Channel Reports (`fixtures/express/`): one in the Express weir source PDF (p. 119, 2020) and nine in the Hydrographs source PDF (pp. 82-89, 106, 2025); rectangular, triangular (incl. 13:1 / 20:1) and trapezoidal; known Q, known depth and Q vs. depth. All 80 printed values reproduce.

| Finding | Evidence | Pro-Flow |
|---|---|---|
| Manning constant is **1.486**, not the manual's printed 1.49 (Express manual p. 27) | Known-depth cases A-A and D-D reproduce to the printed digit with 1.486; with 1.49 four of the five known-depth cases fail on Q and velocity (a test pins this) | `K_MANNING = 1.486` |
| Iterated depths are reported **rounded up to 0.01 ft** | Critical depth: 10 of 10 reports (rounding to nearest: 4). Known-Q normal depth: B-B exact 0.7819, printed 0.79, with area and velocity at 0.79; area at the stepped depth also in A-A, C-C, D-D. Manual says only "an iterative procedure". | Exact by default. `depth_step=0.01` (CLI `--express-steps`) reproduces Express, under `.stepped` method ids. Stepped depth is deeper and velocity lower than exact. |
| g | Not distinguishable at the printed precision | 32.174 ft/s^2 |

Fixture tolerance: half the printed digit plus the output's change when the slope moves by the 0.005 % hidden by the reports' 0.01 % slope precision (published Q residuals with 1.486 run both ways, consistent with rounded slope inputs). n-values are assumed typed exactly as printed. Independent checks: closed-form critical depth for rectangular and symmetric triangular sections, Froude = 1 at critical depth, normal depth inverts flow at depth.

## Remaining channel sections and weir types (2026-10-26)

Code: `engine/sections.py` holds the section geometry and flow laws. `engine/channel.py` runs the generic solvers for normal depth, critical depth and the rating table. `engine/weir.py` holds the weir shapes and the flow, head and rating functions.

Method ids are `channel.{manning|manning_composite|hec22_gutter}.{known_q|known_depth|rating}[.stepped]/1` and `weir.{type}[.rating]/1`.

| Section / weir | Equation | Evidence | Status |
|---|---|---|---|
| Circular pipe | Manning on segment geometry. Q peaks near 0.938 D. The solver takes the rising branch and warns when a higher second depth also carries Q. | 3 published reports (Junipero Serra PR-1A 18 in and PR-1E 12 in; San Diego SWQMP 302-301). Geometry and critical depth match. **Express carries 2.5 to 6 % less flow at a given depth.** | Fixtures gate critical depth only (`"gate": false` on the rest). |
| Gutter | Express manual, HEC-22 form: Q = 0.56/n S^1/2 Z D^8/3 per triangle (the Sw triangle minus its part beyond W, plus the Sx triangle beyond W). This equals HEC-22's Eo form. | 3 published reports (Junipero Serra cobble swale O-1 twice; proposed gutter PR-1A). Geometry and critical depth match. **Express carries 0.6 to 2.7 % less flow.** | Fixtures gate critical depth only. "Top width" shows as "Spread width". |
| User-defined | Station/elevation points (up to 50), with n applying from the previous point. Composite n by HEC-RAS eq. 2-6 (manual p. 27). Depth is limited by the lower end bank, and the invert is the lowest point. | No published case. Hand-worked checks in `tests/test_shapes.py`. | Manual equation only. |
| Rectangular weir | Q = Cw L H^1.5 | 3 published reports | Reproduces |
| Compound weir | Rectangular equation on the lower notch (x by a), plus the full length above a. **This split is Pro-Flow's reading.** The manual (pp. 70-73) does not spell it out. | No published case | Manual equation only |
| Circular weir | Q = Cw A H^1/2 | No published case | Manual equation only |
| V-notch | Q = Cw H^2.5, Cw = 2.54 tan(angle/2), angle up to 120 deg | No published case | Manual equation only |
| Cipoletti | Q = 3.1 (B + 0.8 H z) H^1.5, z up to 4 | No published case | Manual equation only |
| Sutro | Q = 4.96 a^1/2 B (H - a/3), for heads at least a. The profile is X = B[1 - (2/pi) atan sqrt(y/a)]. | No published case | Manual equation only. Rating rows below a are left out, with a warning. |

Depth reporting, checked against the published reports:

- **Critical depth** is printed rounded up to 0.01 ft for every section: 6 of 6 pipe and gutter reports, on top of the 10 earlier ones.
- **Normal depth** is printed exact for pipes and gutters (the printed value is the nearest 0.01 ft of the depth Express used). Only Manning trapezoids round it up.
- **Weir heads** are printed exact (3 of 3 reports).
- `.stepped` mode follows these rules and adds a note when the normal depth stays exact.

New fixtures:

- 9 Express channel reports in `fixtures/express/`, from `reference/public_cases/express-more/`:
  - pipes: 3
  - gutters: 3
  - trapezoid/triangle: 3, fully gated
- 2 rectangular-weir reports in `fixtures/public/`: Forebay DP 3.0, and Future Forebay DP 3.1.

`eakle-hardin.pdf` in that folder is a blank template with no values.

**Open question.** The pipe and gutter flow difference is not a rounding effect: it is too large and does not match any constant k or Kc. Possible causes:

- an undocumented flow reduction
- a different gutter or pipe formulation in the program than in the manual
- n handling

It needs either an Express case with known inputs run on a licensed copy, or documentation that states the formula. Until then Pro-Flow uses the textbook equations and says so in the evidence note on every result. Do not fit a factor to these reports (plan rule: no tuning to rounded outputs).

GUI:

- Section- and type-specific rows show and hide with the selection. Total depth appears only where it applies.
- User sections are entered in an editable points table. A bad cell gives an invalid-input result that names the cell.
- Broad crest is offered for rectangular and compound weirs only. The Cw override is offered for rectangular, compound and circular weirs.
- Every result's first note is that method's evidence text.
- Plots clip water to each pool, and lines span the waterline crossings. A pipe's EGL stays a chord, and a split user section shows two pools.
- Checked as real windows at 150 %: pipe, gutter, user-defined, V-notch, Sutro and compound.

Not yet done:

- The `proflow channel` CLI still takes only rectangular, triangular and trapezoidal sections.
- The pipe and gutter flow difference above is unresolved.

## Storm note carried from Phase 2

The IDF-based synthetic storm stays experimental / unbuilt until a complete output case can check its block ordering.

## UI prototype (2026-10-26): one Express channel screen, for the framework decision

Superseded by the desktop app below; the prototype `gui/channel_screen.py` became `gui/channel_panel.py`.

- Qt-free layers built first, so they serve PySide6 or a web frontend alike: `model/express.py` (inputs, `calculate_channel` / `calculate_weir`, depth-reporting labels), `graph/express.py` (cross-section and rating plot data), `reports/express.py` (report HTML). Weir solver gained EGL and a Q vs. depth table.
- PySide6 screen (`gui/`): inputs with units, results with units, warnings and notes, cross-section plot (W.S., Yc, EGL, elevations), Q vs. depth table with row selection, report preview, PDF / HTML export and print, all in one style (`gui/style.py`, light palette fixed so the Windows dark theme does not leak in). Chips show the method id, Exact vs. Express stepped depths, and Experimental.
- Checked as real windows on this machine: Dell U2720Q at 150 % (native) and 100 % (emulated with QT_SCALE_FACTOR; the 100 % monitor seen in the first run was no longer attached). Report PDF checked by rendering page 1.
- Qt friction met and fixed: styled spin boxes with `NoButtons` hide their text in Qt 6.12 (arrows hidden by stylesheet instead); combo-box arrows need an SVG asset once styled; Windows dark mode leaks into Fusion unless a palette is set; the `offscreen` platform on Windows has no fonts (PDFs exported there show boxes; the app and native-platform exports are fine).
- Decision: continue in PySide6 after reviewing the runnable screen at 100 % and 150 % scaling. Next: weir panel, on-screen rating plot, app shell, and PySide6 GUI tests in CI. Remaining shapes follow that complete workflow.

## Desktop app (2026-10-26)

Run: `proflow-gui`, or `proflow-main/.venv/Scripts/python.exe -m proflow.gui` (install with `pip install -e .[gui]`).

- Shell (`gui/app.py`): sidebar with an EXPRESS group (Channel, Weir), one page per calculator, version and "experimental" in the footer.
- `gui/panel.py` `CalculatorPanel`: the shared layout and behaviour; `ChannelPanel` and `WeirPanel` supply only the form, result fields and calculation. Both open on their published Express case (Sec B-B @ Q100; Forebay @ DP 4.3 Notch).
- Plot card has two tabs: section (cross-section / weir section) and **rating curve** (Q vs. depth over the total depth, reported state marked; follows the selected table row). Depth and flow axes start at zero.
- Weir panel: crest, bottom length, total depth, Cw with an "Express default" box (3.33 sharp / 2.6 broad; an override is a warning, kept even when the head then exceeds the total depth), Known Q / Known depth / Q vs. depth. Depths exact only (the published weir report agrees with the exact head).
- Report: weir input rows and weir result fields; "Weir section" heading for weirs; Q vs. depth table width 99 % (100 % plus borders overflowed by 1 px and gave the preview a horizontal scrollbar).
- Checked as real windows at 150 % and emulated 100 %: channel rating curve, weir results, weir Q vs. depth table, weir report preview.
- CI: installs `.[gui]` with PySide6 pinned to 6.12.0, Qt's Linux libraries (libegl1, libgl1, libxkbcommon0, libfontconfig1, libdbus-1-3), `QT_QPA_PLATFORM=offscreen` and `PROFLOW_REQUIRE_GUI=1`, so `tests/test_gui.py` must run: a missing PySide6 fails collection (checked locally in an environment without PySide6).

Remaining shapes and weir types: see the section above.
