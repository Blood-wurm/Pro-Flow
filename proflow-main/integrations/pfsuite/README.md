# PFSUITE exporter (draft)

`pf-export.lsp` is the PFSUITE V6 side of the exchange described in `docs/pfsuite-network-exchange.md`. Its command, `PFEXPORT`, writes `<drawing>.pfsuite.json` beside the drawing. Pro-Flow then reads that file with `proflow network import` or the Sewer line page.

**Status: draft, not yet run in CAD.** It was written against the V6 module APIs as of 2026-10-16:

- `pfr:read`, `pfr:src-get`, `pfr:asserted-p`
- `pfg:usable`, `pfg:anchor-of`, `pfg:copy-p`
- `pfp:all`, `pfp:ends`, `pfp:size`, `pfp:mat`, `pfp:wall`, `pfp:userdir`
- `pfc:cl-range`, `pfc:metric-p`

## Using it

1. APPLOAD `pf-load.lsp` from the V6 folder as usual.
2. APPLOAD this file.
3. Run `PFEXPORT`. The command line reports how many structures, pipes and grids were written, and the path.

## Rules it keeps

- **Read-only.** It never writes the drawing. Only `pf-record` and `pf-draw` may do that.
- **Name contract.** Tags, block names and library file names come from `pf-cfg`'s variables, never from literals.
- **Metric drawings are refused.**
- **Raw facts only.** It writes what the drawing holds and does not resolve links. Pro-Flow links pipe ends to structures and reports anything it cannot link. Problems the exporter does notice go in `diagnostics` (copied anchors, a missing `.cl`, pipes off any grid, blank `PFSIZE`).

## Moving it into PFSUITE

If it proves out, it could become a PFSUITE module (`pf-export/`, loaded after `pf-pipe`). That is a PFSUITE decision. Until then it lives here, so nothing in the V6 folder changes.

## First checks in CAD

1. Run `PFEXPORT` on `V6_Test.dwg`, then `proflow network import V6_Test.pfsuite.json`.
2. Check the report:
   - every pipe links to two structures;
   - centre-to-centre lengths agree with the plan distances;
   - inverts match the profile labels.
3. Pick one pipe and compare its imported inverts with PFSUITE's own invert labels at those stations.
