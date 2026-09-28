# Greyhound documentation

Use this index to locate measured layouts, decoder entry points, and
saved evidence. For building and running Greyhound, see [Build on Windows](#build-on-windows)
and [Run Greyhound](#run-greyhound).

## Research map

| Question | Findings | Code or evidence |
| --- | --- | --- |
| How is Cold War terrain found and decoded? | [CW terrain](cw-terrain.md) · [TerrainGfx comparison](terraingfx-reference.md) | [CW reader](../src/WraithXCOD/WraithXCOD/games/cold_war/reader/GameBlackOpsCW.cpp) · [terrain capture](../src/WraithXCOD/WraithXCOD/games/cold_war/terrain/CWTerrainBake.h) |
| How does BO4 TerrainGfx differ? | [BO4 terrain and collision](bo4-terrain-research.md) · [TerrainGfx comparison](terraingfx-reference.md) | [BO4 reader](../src/WraithXCOD/WraithXCOD/games/black_ops_4/reader/GameBlackOps4.cpp) · [source packager](../tools/black_ops_4/capture/package_bo4_terrain.py) |
| Where are placements and scene objects? | [CW placements](cw-placements.md) · [CW effects and entities](cw-effects-entities.md) · [BO4](bo4.md) | [CW reader](../src/WraithXCOD/WraithXCOD/games/cold_war/reader/GameBlackOpsCW.cpp) · [BO4 reader](../src/WraithXCOD/WraithXCOD/games/black_ops_4/reader/GameBlackOps4.cpp) |
| Where are collision and navigation decoded? | [CW collision](cw-collision.md) · [CW navigation](cw-navigation.md) · [BO4 research](bo4-terrain-research.md) | [Script directory](../tools/README.md) · [BO4 brush workflow](bo4-radiant-export.md) |
| Which names and preview data are reliable? | [Saluki names](saluki-names.md) · [Library preview](library-preview.md) · [reader audit](preview-reader-audit.md) | [Preview builder](../src/WraithXCOD/WraithXCOD/assets/preview/PreviewData.cpp) |
| How should captures be checked? | [Capture contracts](capture-research.md) · [contribution guide](contributing.md) | [Saved map-data audit](cw-map-data-validation.json) · [probe bounds](cw-probe-bounds-evidence.json) |

For implementation paths, use the [source walkthrough](contributing.md#walk-through-the-source)
and [script directory](../tools/README.md). [Code organization](code-organization.md)
records the repository move; [model LOD numbering](model-lod-numbering.md)
documents that separate model setting.

## Paths used in these guides

Run repository commands from your Greyhound checkout. Source paths such as
`tools/cold_war/` are relative to that checkout, wherever you cloned it.

Export paths such as `exported_files/black_ops_cw/` are relative to the active
Greyhound installation. Follow the path reported by the executable you used.
GUI, CLI and build-only installations can have separate settings and exports.

Examples use variables such as `$capture`, `$output` and `$bo3` for paths you
choose. Replace quoted placeholder values before running them. No personal
capture folder, Steam library location or developer virtual environment is
required. Captured game data is not included in this repository.

## Build on Windows

Requirements:

- Windows x64.
- Visual Studio 2022 with Desktop development with C++, the v143 toolset,
  a Windows SDK and **C++ MFC for latest v143 build tools (x86 & x64)**.
- Python 3.10+ with NumPy and SciPy for packaging. pytest is used for tests.
- The repository's recorded submodules and external-library dependencies.

Clone the fork, then open PowerShell in the checkout:

```powershell
git clone --recurse-submodules https://github.com/Kxboo/Greyhound.git
cd Greyhound
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install numpy scipy pytest
$env:SUPERTERRAIN_PYTHON = (Resolve-Path .\.venv\Scripts\python.exe).Path
.\build-greyhound.ps1
```

For an existing clone, run `git submodule update --init --recursive` first.
The environment variable keeps its existing name for compatibility; it points
to your own interpreter and does not require a SuperTerrain checkout.

Later examples use `python` for your configured interpreter. If the virtual
environment is not activated, substitute `.\.venv\Scripts\python.exe`.

The [build script](../build-greyhound.ps1) builds Release x64 and stages:

| Purpose | Executable, relative to the checkout |
| --- | --- |
| GUI | `bin/Greyhound.exe` |
| CLI | `bin/cli/Greyhound-cli.exe` |
| Build-only output | `src/WraithXCOD/x64/Release/Greyhound.exe` |

`-BuildOnly` stages the runtime only beside the build-only executable.
Keep the packaged `tools/`, required runtime libraries and appropriate
`package_index/` databases beside the executable. The EXE alone is not a
complete release. See [runtime packaging](../tools/shared/runtime/README.md#developer-packaging)
when changing the shipped helpers.

## Run Greyhound

For the GUI, launch `bin/Greyhound.exe`, load a supported game/data source, then
select the assets you want. Load a map before using placement or brush actions.
Settings for these workflows are under **Map & Model Export**, **Radiant Brushes**,
**Terrain** and **Dev Tools**.

For the CLI, use the executable shown above. Help and capabilities work without
a running game; asset listing and export need a supported game/data source.
Use a game copy you own. General game support and settings are described in
the [upstream wiki](https://scobalula.github.io/Greyhound/); this folder documents
the additional workflows in this fork.

## CLI: discover before exporting

```powershell
$gh = '.\bin\cli\Greyhound-cli.exe'
& $gh assets --help
& $gh assets capabilities --json
& $gh assets list --type model --limit 10 --json
& $gh assets export --type model --name 'EXACT_NAME_FROM_LIST' --dry-run --json
& $gh assets export --type model --name 'EXACT_NAME_FROM_LIST' --model-format cast --json
```

Repeat `--name` for exact selections or `--glob` for patterns. Exporting every
asset requires explicit `--all`; inspect `--dry-run` with `--limit` first.
Format switches can be repeated. `--largest-lod` is the default; use
`--all-lods` when needed. Existing files are skipped unless `--overwrite`
is supplied. `--jsonl` is available for line-oriented output.

Capabilities describe asset formats, defaults and dedicated placement-command
metadata. Use the executable's help for the full list of flags.

| Asset CLI exit code | Meaning |
| --- | --- |
| 0 | Success |
| 1 | Invalid usage |
| 2 | Could not attach |
| 3 | No matching assets |
| 4 | Export failed |
| 5 | Terrain finalization failed |

The dedicated placement command has its own parser and switches:

```powershell
# Cold War: capture, verify and organize one run.
& $gh placements --name-db bundled --non-static --verify --organize
# Black Ops 4: static placements.
& $gh placements --name-db bundled
```

Do not mix `assets` switches with `placements` switches. The CW optional
capture, verification and organization switches do not imply BO4 feature parity.
For the alternate name database, see [BO4 / CW names](bo4.md#name-databases).

Placements contain transforms, not meshes. In **Map & Model Export**, use
**Models from JSON** with the exported placement file to export referenced models.
For an organized CW run, select `models/static.json` or `models/non_static.json`.
To resume a batch, select its `static_models.json` and retain its export settings.

## Placement folders and duplication

An organized CW export keeps one run under
`exported_files/black_ops_cw/placements/run_NN/`:

```text
run_NN/
  catalog.json                  # file locations and source/output hashes
  README.md                     # guide to this run
  models/                       # static, non-static and spline rows
  animation/                    # placements and named references
  fx/                           # effect placements, assets and candidates
  entities/                     # source entity classes
  lights/  probes/  sun/         # decoded data and source candidates
  triggers/                     # hull references
  diagnostics/                  # raw capture evidence
  metadata/                     # reports, validation and mappings
  logs/                         # helper logs, when present
```

Enable **Sort the finished export into per-category folders** with non-static
CW capture, or use the CLI above. Organization stages a temporary copy,
checks hashes and unchanged inputs, then swaps it into the same run path.
It needs temporary disk space; success leaves no second `_organized` run.

A cleanup failure or interruption between renames may leave an
`*.organizing-*/original` recovery directory. Inspect the reported paths and
`placements/logs/terrain_pipeline.log` before attempting recovery or cleanup.

Old exports are not migrated automatically. To preview a completed flat run:

```powershell
$capture = '<path to your completed flat placement run>'
$output = '<path to a new preview folder>'
python tools/cold_war/capture/organize_cw_placements.py $capture $output
# To reorganize the original run after closing its writers:
python tools/cold_war/capture/organize_cw_placements.py $capture --in-place
```

Raw evidence and decoded data serve different purposes. Repeated model
instances are separate placements; matching names or positions do not justify
merging them. See [CW placements](cw-placements.md) for field meanings.

## Troubleshooting

- **Build fails:** confirm the C++/MFC components, submodules and referenced
  external libraries. Read the first error in the build log.
- **Attach fails:** check the game, loaded map and supported executable build.
- **Missing helper:** check the runtime beside the executable you launched.
  Rebuild packaging and check `terrain-python.txt` and `SUPERTERRAIN_PYTHON`.
- **Organization fails:** inspect the helper log and surviving run/recovery
  folder. A missing interpreter leaves the flat export available.
- **Names remain hashed:** record the selected database. An unresolved name
  does not mean the asset is missing.
- **Capture is partial:** inspect completeness, readback and unresolved counts.
  File generation alone does not prove complete decoding or gameplay parity.
