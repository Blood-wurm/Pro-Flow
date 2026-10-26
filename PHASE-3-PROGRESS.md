# Phase 3 progress: Express calculators

Status 2026-10-26: channel solver and one runnable Express channel screen are done. The weir screen, on-screen rating plot, and app shell are not built yet. 303 tests pass in the developer environment, Ruff clean, `proflow fixtures` 39/39 complete cases pass. All methods remain **experimental**.

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

## Not yet built in slice 3.1

- Express channel shapes: circular (pipe), gutter, user-defined station/elevation with composite n (HEC-RAS eq. 2-6, manual p. 27).
- Weir types beyond rectangular: compound, circular, V-notch, trapezoidal (Cipoletti), proportional (Sutro); weir rating tables.
- Form, result table view, cross-section and rating-curve plots, printable report for channel and weir (the "form, results, plot, report together" rule of the plan). No GUI toolkit is installed yet (PySide6 is listed in requirements.txt).

## Storm note carried from Phase 2

The IDF-based synthetic storm stays experimental / unbuilt until a complete output case can check its block ordering.

## UI prototype (2026-10-26): one Express channel screen, for the framework decision

Run: `proflow-main/.venv/Scripts/python.exe -m proflow.gui.channel_screen` (PySide6 6.12, optional extra `pip install -e .[gui]`).

- Qt-free layers built first, so they serve PySide6 or a web frontend alike: `model/express.py` (inputs, `calculate_channel` / `calculate_weir`, depth-reporting labels), `graph/express.py` (cross-section and rating plot data), `reports/express.py` (report HTML). Weir solver gained EGL and a Q vs. depth table.
- PySide6 screen (`gui/`): inputs with units, results with units, warnings and notes, cross-section plot (W.S., Yc, EGL, elevations), Q vs. depth table with row selection, report preview, PDF / HTML export and print, all in one style (`gui/style.py`, light palette fixed so the Windows dark theme does not leak in). Chips show the method id, Exact vs. Express stepped depths, and Experimental.
- Checked as real windows on this machine: Dell U2720Q at 150 % (native) and 100 % (emulated with QT_SCALE_FACTOR; the 100 % monitor seen in the first run was no longer attached). Report PDF checked by rendering page 1.
- Qt friction met and fixed: styled spin boxes with `NoButtons` hide their text in Qt 6.12 (arrows hidden by stylesheet instead); combo-box arrows need an SVG asset once styled; Windows dark mode leaks into Fusion unless a palette is set; the `offscreen` platform on Windows has no fonts (PDFs exported there show boxes; the app and native-platform exports are fine).
- Decision: continue in PySide6 after reviewing the runnable screen at 100 % and 150 % scaling. Next: weir panel, on-screen rating plot, app shell, and PySide6 GUI tests in CI. Remaining shapes follow that complete workflow.
