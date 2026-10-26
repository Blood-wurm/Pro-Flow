# Pro-Flow project handoff

Read `CLAUDE-IMPLEMENTATION-PLAN.md` and the phase progress notes for scope and evidence. The user's latest priority supersedes the original phase order: **build the first Storm Sewers vertical slice next**. Do not wait for the remaining Express CLI work or Hydrographs routing.

## Next slice

- Define a versioned, documented **PFSUITE-to-Pro-Flow network exchange**. PFSUITE V6 is at `E:\Work\Automation\PFSUITE\V6`. Its profile pipe X/Y coordinates are sheet station/elevation coordinates, not plan X/Y. Resolve plan coordinates from the plan structure and centerline records; report unresolved links. Start with one pipe between two structures.
- Carry stable source IDs, units/coordinate reference, plan coordinates, structure type and rim, pipe connections, end inverts, diameter, material, and provenance. Identify missing hydraulic inputs explicitly. Keep the exchange separate from the native Pro-Flow project until import validation succeeds.
- Use DXF as a read-only visual underlay. SHP is a later background layer. `.stm` is allowed if proven useful for Hydraflow/Civil 3D interoperability, but is not the first exchange format; LandXML is also later.
- Build the one-catchment/inlet/node/pipe/outfall Pro-Flow workflow: import, edit missing Manning's n and tailwater, calculate flow, capacity, HGL/EGL, show a profile, save and reopen. Check an independent complete one-pipe example and adverse conditions. The public Hydraflow one-line report lacks n and boundary settings, so it remains a partial comparison.

## Evidence and gates

- All methods remain experimental. Published Express pipe and gutter cases currently match geometry and critical depth but **not flow**; do not fit a correction factor to rounded output. See `PHASE-3-PROGRESS.md`.
- Use published manuals, public reports, and independent engineering references. Do not inspect product binaries for this work.
- Preserve the existing project-schema rule: bump its version when an older reader cannot safely read a newly written file. Give the network exchange its own version.
- Before handing off a slice, run Ruff, pytest including GUI tests, and `proflow fixtures`; report complete fixture gates separately from informational comparisons. CI covers Windows and Ubuntu on Python 3.11 and 3.12.
