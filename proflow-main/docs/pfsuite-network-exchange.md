# PFSUITE network exchange, format version 1

`pfsuite-network` is how a storm network drawn with PFSUITE V6 (AutoCAD and Carlson) gets into Pro-Flow.

- **What it carries:** the facts PFSUITE already stores in the drawing, plus what is needed to turn them into a Pro-Flow network.
- **What it leaves out:** hydraulic inputs PFSUITE does not hold (Manning's n, tailwater, catchments). Those are left out on purpose, and the importer lists them as missing.

This document is the contract between the two programs. `proflow.io.pfsuite` implements the Pro-Flow side. `integrations/pfsuite/pf-export.lsp` is a draft of the PFSUITE side and has not yet been run in CAD.

## File

- **Encoding:** UTF-8 JSON, one network per file, conventionally `*.pfsuite.json`.
- **Numbers:** written at full precision, as PFSUITE's `pfr:real` does (`rtos x 2 15`).
- **Ids:** AutoCAD entity handles, which stay the same for an entity across saves.

## Versioning

- `format_version` is an integer. Bump it only when a version-1 reader could not safely interpret a newly written file: a field changes meaning or unit, a field becomes required, or a resolution rule changes.
- Adding an optional field is not a bump. A version-1 reader keeps any field it does not know in the imported element's `source.extra` and reports it.
- This version is independent of the Pro-Flow project schema and of PFSUITE's own record schema (`*pf-schema*`). The latter is carried in `producer.record_schema`.

## Top level

| Key | Required | Meaning |
|---|---|---|
| `format` | yes | `"pfsuite-network"` |
| `format_version` | yes | `1` |
| `producer` | yes | `{"name": "PFSUITE", "version": "V6", "exporter": "pf-export", "exporter_version": 1, "record_schema": 1}`. `name` is required. |
| `exported_at` | yes | ISO 8601 local date and time, e.g. `"2026-10-26T17:30:00"` |
| `drawing` | yes | `{"name": "V6_Test.dwg", "path": "E:\\..."}`. `name` is required. |
| `units` | yes | `{"length": "ft", "pipe_size": "in"}`. A metric drawing is refused by the exporter (Carlson `IS_METRIC`), and the importer accepts only `ft` and `in`. |
| `coordinates` | yes | `{"plan": "drawing", "crs": null}`. Plan coordinates are drawing coordinates in `units.length`. `crs` names a coordinate reference system, or is `null` when the drawing does not record one. |
| `settings` | no | `{"pipe_snap_ft": 8.0, "membership_tol_ft": 0.15}`. These are the PFSUITE tolerances used when exporting (`*pf-pipe-snap*`, `*pf-memb-tol*`). The defaults are those values. |
| `lines` | yes | The centerlines (below) |
| `grids` | yes | The profile grids (below) |
| `structures` | yes | Plan structures (below) |
| `pipes` | yes | Profile pipes (below) |
| `materials` | no | `[{"name": "RCP III", "n": 0.013, "source": "pipen.dta"}]`, Carlson's material library. A suggestion only: n is never applied without the user. |
| `diagnostics` | no | `[{"level": "error"\|"warning"\|"info", "code": "...", "ref": "<id>", "message": "..."}]`. What the exporter found. Errors stop the import. |

### `lines[]`

| Key | Required | Meaning |
|---|---|---|
| `id` | yes | The line name as structure membership records it: the `.cl` file's base name in upper case, e.g. `"STORM_BA"` (`pfg:line-name`) |
| `cl_file` | no | Path of the Carlson `.cl` file |
| `station_range` | no | `[start, end]` in ft (`pfc:cl-range`) |

### `grids[]`

A profile grid maps sheet coordinates to station and elevation, the same conversion as `pfl:x->sta` and `pfl:y->elev`:

```
station   = sta0  + (x - leftx)
elevation = datum + (y - basey) / vscale        vscale = hplot / vplot
```

| Key | Required | Meaning |
|---|---|---|
| `id` | yes | Handle of the grid's `PFSUITE_ANCHOR` (or V5 anchor) |
| `line` | yes | The `lines[].id` this profile shows |
| `sta0`, `datum`, `leftx`, `basey`, `vscale` | yes | The numbers above. `vscale` > 0. |
| `title` | no | E.g. `"STORM 'BA'"` |

### `structures[]`

These are plan structures: the "alpha block" in the `PLAN` view. Profile copies are not exported.

| Key | Required | Meaning |
|---|---|---|
| `id` | yes | Handle of the plan insert |
| `block` | yes | Effective block name (`pfl:effname`), e.g. `"PFSUITE_CBI"` |
| `type` | yes | `PFTYPE`, e.g. `CBI`, `DBI`, `MH`, `SMH`, `DMH`, `HDWL` |
| `size` | no | `PFSIZE` as text |
| `name` | no | `PFNAME`, e.g. `"BA-5/BC-1"` |
| `plan` | yes | `{"x": ..., "y": ..., "rotation_deg": ...}`: the insertion point and rotation |
| `rim` | yes | `{"value": number \| null, "source": "CL"\|"TIN"\|"RULE"\|"ASSERTED"\|"NONE"}`. This is `PFRIM` and its `SRC` entry. `NONE` (value `null`) means not on record, **never zero**. |
| `position` | no | `PFPOS` (`ONGRADE`, `SAG`, `SURFACE`) |
| `inlet` | no | `PFINLET`, the Carlson inlet-library entry. `""` = no inlet flow. |
| `library` | no | `PFSTRUCT`, the Carlson structure-library entry |
| `lines` | yes | Membership (`MEMB`): `[{"line": "STORM_BA", "station": 150.0, "offset": -0.02}]`. A signed offset, negative to the left. Two or more entries make a junction. |
| `record_schema` | no | The `SCHEMA` XDATA value |

### `pipes[]`

These are profile pipes (`PFSUITE_PIPE`). **Their coordinates are sheet coordinates on a profile grid, not plan coordinates.** Plan positions come from the structures the pipe ends link to.

| Key | Required | Meaning |
|---|---|---|
| `id` | yes | Handle of the pipe insert |
| `grid` | yes | `grids[].id` of the grid the pipe is drawn on (`pfg:anchor-of` its midpoint) |
| `upstream` | yes | `{"sheet": {"x": ..., "y": ...}}`: the block's base point. PFPIPE's first click is the upstream invert. |
| `downstream` | yes | `{"sheet": {"x": ..., "y": ...}}`: base point plus the `PFRUN` grip (`pfp:ends`) |
| `size_in` | yes | Inside diameter in inches (`PFSIZE`) |
| `material` | no | `PFMAT` |
| `wall_in` | no | Wall thickness from `pipesize.dta`, in inches |

## How Pro-Flow resolves the file

These steps run in order. `proflow network import` prints the report they produce.

1. **Check.** The format, version, units and every required field are checked, along with references between ids. An exporter `error` diagnostic stops the import.
2. **Ends to station and invert.** Each pipe end's sheet point goes through its grid's conversion. The result is the station on the grid's line and the invert elevation at the drawn end.
3. **Ends to structures.** An end links to the structure on the same line whose membership station is nearest. It must be within `settings.pipe_snap_ft`, since pipes are drawn to the structure wall, not its centre. Any of these cases is an unresolved link:
   - no structure is in range;
   - a second structure is within 0.01 ft of the nearest;
   - both ends link to one structure.
4. **Plan geometry.** A structure's plan point is its insertion point. A pipe runs between the plan points of its two structures. Its length is the distance between junction centres, as the Storm Sewers manual defines it (p. 47). That is the difference of the two structures' membership stations on the line. If the straight plan distance differs from that length by more than 0.5 ft or 1 %, Pro-Flow warns: the centerline bends between the structures, or a record is out of date.
5. **Direction and slope.** Upstream is the end PFPIPE placed first. Slope = (upstream invert − downstream invert) / length. A flat or adverse line is a warning, not an error. The drawn run (the station difference of the two ends) is reported alongside, because the pipe label's slope uses it.
6. **Kinds.**
   - **Outfall:** a structure that pipes enter but none leave.
   - **Inlet:** a structure with a non-empty `inlet`, or of type `CBI`, `CBI_BOX` or `DBI`.
   - **Manhole:** any other structure.
7. **Missing hydraulic inputs.** Pro-Flow lists:
   - Manning's n for every pipe, with the `materials` value offered as a suggestion;
   - the outfall's tailwater (starting HGL);
   - a catchment or known flow at each upstream end;
   - rims whose source is `NONE`.
8. **Acceptance.** The native network is built only when there are no errors and no unresolved links. Until then the import report is all there is, and nothing is written to the project.

Every imported element keeps a `source` record in the project:

- `format` (`pfsuite-network/1`)
- the handle (`id`)
- the drawing name
- `provenance`: which program field each value came from
- `attributes`: PFSUITE fields Pro-Flow carries but does not compute with
- `extra`: unknown fields, preserved verbatim

A value the user later edits is marked `user` in `provenance`.

## Not in version 1

- Box, elliptical and arch pipes: `pipesize.dta` round pipe only.
- Crossings and other utilities.
- Drop and invert labels. Pro-Flow reads inverts from the pipe ends, not from labels.
- Surfaces.
- An export back to PFSUITE.
- `.stm` and LandXML (planned separately).
- DXF, as a read-only background (planned separately).
