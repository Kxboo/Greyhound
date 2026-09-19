# Greyhound fork: start here

This fork extracts game assets and preserves source evidence for map research.
Cold War and BO4 have additional placement, brush and diagnostic workflows.
Terrain reconstruction remains external. A successful byte audit does not prove
visual equivalence, Radiant compilation or equivalent gameplay in another game.

## Reading order

| Task | Read |
| --- | --- |
| Build, run the CLI, understand outputs | This page |
| Find scripts by game and task | [Script directory guide](../tools/README.md) |
| Review code, contribute, or use an AI assistant | [Contributing](contributing.md) |
| Export meshes, materials, LODs and resume batches | [Models](models.md) |
| Understand CW static/nonstatic placements | [CW placements](cw-placements.md) |
| Investigate FX, animation and entity properties | [CW effects and entities](cw-effects-entities.md) |
| Investigate navigation and progression | [CW navigation](cw-navigation.md) |
| Investigate brushes and collision | [CW collision](cw-collision.md) |
| Understand capture boundaries and earlier audits | [Capture research](capture-research.md) |
| Work on BO4 placements, names and brushes | [BO4](bo4.md) |
| Investigate BO4 terrain source intake | [BO4 terrain research](bo4-terrain-research.md) |

The reference pages retain dated measurements and their limits. Local capture
paths in those records are examples from development, not prerequisites or
downloadable fixtures. Use your own saved capture. There are ten documentation
pages, each limited to 500 lines; extend the relevant page instead of adding a
new dated diary. Repository policy/license files are separate.

## Build on Windows

1. Clone this fork and initialize its recorded submodules:
   `git submodule update --init --recursive`.
2. Install Visual Studio 2022 C++ desktop tools, the v143 toolset, Windows SDK,
   and **C++ MFC for latest v143 build tools (x86 & x64)**.
3. Install Python 3.10+ with NumPy and SciPy. For tests, install pytest as well.
4. In PowerShell at the repository root:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install numpy scipy pytest
$env:SUPERTERRAIN_PYTHON = (Resolve-Path .\.venv\Scripts\python.exe).Path
.\build-greyhound.ps1
```

The build script stages `bin/Greyhound.exe`, `bin/cli/Greyhound-cli.exe`, Python
capture helpers and the packaged brush runtime. `-BuildOnly` stages only beside
`src/WraithXCOD/x64/Release/Greyhound.exe`. Keep runtime dependencies and the
appropriate `package_index` databases beside the executable; the EXE alone is
not a complete release. Missing external-library build errors require checking
the solution's referenced dependencies as well as the submodules.

## CLI: discover before exporting

Run from the repository root after building. Capabilities and help work without
a game; listing and exporting require a supported game/data source to be loaded.

```powershell
$gh = '.\bin\cli\Greyhound-cli.exe'
& $gh assets --help
& $gh assets capabilities --json
& $gh assets list --type model --limit 10 --json
& $gh assets export --type model --name 'EXACT_NAME_FROM_LIST' --dry-run --json
& $gh assets export --type model --name 'EXACT_NAME_FROM_LIST' --model-format cast --json
```

Repeat `--name` for exact selections or `--glob` for patterns. Exporting every
asset requires explicit `--all`; combine it with `--dry-run` and `--limit` first.
Model and animation format switches can be repeated to emit multiple formats.
Use `--all-lods` only when needed; `--largest-lod` is the default. Existing files
are skipped unless `--overwrite` is supplied. `--jsonl` is also available.
Use executable help for the full flag list. Capabilities provide structured asset
formats/defaults and dedicated placement-command metadata for automation.

| Asset CLI exit code | Meaning |
| --- | --- |
| 0 | Success |
| 1 | Invalid usage |
| 2 | Could not attach |
| 3 | No matching assets |
| 4 | Export failed |
| 5 | Terrain finalization failed |

The dedicated placement command has its own switches:

```powershell
# CW: load a map first. Audit, then categorize one completed run.
& $gh placements --name-db bundled --non-static --verify --organize
# BO4: static placements; CW organization/auditing is not BO4 feature parity.
& $gh placements --name-db bundled
```

`placements` exports transforms, not model meshes. In the GUI, use **Map & Model
Export** to export placements, then **Models from JSON** for meshes. Select
`models/static.json` or `models/non_static.json` in an organized CW run.
`--name-db echo000` requires a separately imported local name database; see BO4.
Do not mix `assets` options with `placements` options: their parsers differ.

## Placement folders and duplication

An organized CW export keeps a single run under
`exported_files/black_ops_cw/placements/run_NN/`:

```text
run_NN/
  catalog.json                  # output paths and source/output SHA-256
  README.md
  models/                       # static.json, non_static.json, spline.json
  animation/                    # placements and named references
  fx/                           # placements, assets, source candidates
  entities/                     # source entity classes
  lights/  probes/  sun/         # decoded data and source candidates
  triggers/                     # hull references
  diagnostics/                  # unchanged raw evidence
  metadata/                     # reports, validation and mappings
  logs/                         # helper logs, when present
```

Use **Sort the finished export into per-category folders** with non-static CW
capture enabled, or the CLI command above. Organization stages a temporary copy,
verifies checksums and unchanged inputs, then swaps it into the same run path.
This needs temporary disk space but leaves no second `_organized` run on success.
A cleanup failure may retain an `*.organizing-*/original` recovery directory;
inspect `placements/logs/terrain_pipeline.log` before removing it. A process crash during the two-rename
publication window may also require restoring that directory manually.

Old exports are not migrated automatically. To preview organization without
altering an existing flat run:

```powershell
python tools/cold_war/capture/organize_cw_placements.py 'C:\captures\run_01' 'C:\captures\preview'
# Explicitly reorganize a saved, completed run after closing writers:
python tools/cold_war/capture/organize_cw_placements.py 'C:\captures\run_01' --in-place
```

Raw diagnostics and decoded outputs intentionally coexist: they have different
roles. Repeated model *instances* are not duplicate model assets; never collapse
placements just because names or positions match. Captured authoring properties
are preserved, even when a string resembles an old filename.

## Troubleshooting

- Attach failed: check the loaded game, active map and supported build first.
- Missing Python/helper: rebuild the staged runtime; check `SUPERTERRAIN_PYTHON`
  and `terrain-python.txt` beside that executable.
- Organization failed: inspect the helper log and surviving run/recovery folder.
  A missing interpreter leaves the flat layout available.
- Missing names: record the selected database; unresolved hashes are valid
  evidence, not proof that an asset is absent.
- Partial capture: read the completeness/readback fields and unresolved counts.
  Do not silently treat a partial run as a complete map.
