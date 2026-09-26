# Dependency-safe code organization

The move and reference inventory is in [code-organization-manifest.json](code-organization-manifest.json).
It records present tracked and untracked files, their original hashes, exact destinations,
and inbound includes, imports, project entries, script paths, tests and documentation.
Vendor files and generated build output are excluded from moves. Existing edits are preserved.

## Scope and order

- [x] Record the inventory and obtain a successful x64 Release build and test baseline.
- [x] Add project-root include paths and register every physical application header.
- [x] Pilot the Ghosts reader, then move each remaining game reader with its helpers and native tests.
- [x] Move common native helpers into app-local `shared/` and group application code by responsibility.
- [x] Extract game-owned layouts, retaining the `DBGameAssets.h` and `DBGameFiles.h` umbrella headers.
- [x] Extract reusable script geometry, move CW-specific implementations to CW, and retain old script paths.
- [x] Verify the full suites, packaged runtime, CLI, old/new helper paths and remaining references.

Each native slice requires a successful Release build and affected tests before the next slice.
Stop at a new failure and resolve it within the current slice. The three recorded BO4 terrain
test failures remain baseline issues; behavior repairs are outside this change.

## Physical layout

Native application code lives in `src/WraithXCOD/WraithXCOD/`:

- `games/<game>/reader/`: all twenty game readers, their game layouts, and MW5/MW6 structure files.
- `games/cold_war/{capture,brushes,placements,terrain}/`: CW helpers.
- `games/black_ops_4/{capture,brushes,placements}/`: BO4 helpers.
- `shared/`: `BO4NameDatabase`, `CWRadiantExport`, and `CWModelLodSelection`.
- `cli/`, `ui/native/`, `settings/`, `assets/`, `packages/`, `exporters/`: common application code.

The game folders are `advanced_warfare`, `black_ops`, `black_ops_2`, `black_ops_3`,
`black_ops_4`, `cold_war`, `ghosts`, `infinite_warfare`, `modern_warfare`,
`modern_warfare_2`, `modern_warfare_2_remastered`, `modern_warfare_3`,
`modern_warfare_4`, `modern_warfare_5`, `modern_warfare_6`,
`modern_warfare_remastered`, `quantum_solace`, `vanguard`, `world_at_war`, and `world_war_2`.
These source names do not change runtime game-folder values, native namespaces, CLI behavior or export formats.

Resources, the application manifest, DB umbrella headers and static `ui/` files stay in place.
The WraithX library and updater retain their layouts. Native tests follow their code under
`tests/<game>/native/` or `tests/shared/native/`; the root runner discovers them recursively.
Build output stays in `src/WraithXCOD/x64/Release/`.

## Baseline and evidence

- Successful build: `build-greyhound.ps1 -Configuration Release -Platform x64 -BuildOnly`.
- Native tests: 18 passed.
- Python tests: 196 passed, 3 failed, 21 subtests passed.
- Existing failures: BO4 terrain sector pairing (`finest_width`) and two terrain cast blend cases (`layer_weights`).

Local before-change files, hashes, logs and test reports are preserved under
`test-output/reorganization-baseline/`. This folder is local validation output, not shipped code.

## Completed validation

All twenty game readers are organized. The manifest accounts for 220 native file moves;
the project and its filters register all 224 physical C++ source/header files. The
twenty extracted layout headers preserve every declaration, and standalone compilation
confirmed identical size/alignment for all 212 declaration types.

| Check | Result |
| --- | --- |
| Release x64 build, each game slice and final package | Passed; output remains `src/WraithXCOD/x64/Release/Greyhound.exe` |
| Recursive native suite | 18 passed |
| Full Python suite | 217 passed, 21 subtests passed; the same 3 BO4 terrain failures |
| Geometry and MAP compatibility | Both legacy/new APIs match 46 baseline cases and 15 signatures |
| Terrain image round trips | 6 passed; all payload bytes unchanged |
| Node map-data audit | Passed |
| Installed runtime | 32 checks passed; manifest covers 142 packaged helpers/data files |
| CLI from another directory | `assets --help` and `assets capabilities --json` passed |
| Old/new helper paths from isolated Python and another directory | Passed |
| Moves, references, project/filter entries, source preservation | All audit checks passed |
| `git diff --check` | Passed |

The supplementary SuperTerrain terrain-contract test outside this repository has
3 passes and 2 existing assertion failures. Both failures were reproduced against
the exact before-change source snapshot; only its source paths were updated.

The UI copy target excludes `ui/native/`; installed UI assets contain no native source
files. The initial generated source copies were retained with local validation output.
WraithX/updater sources, application resources, static web assets and runtime game-folder
values are preserved. No live-game capture or BO3 compilation was part of these checks.

Detailed local evidence includes `completed-slices.jsonl`, `final-packaging-build.log`,
`final-native/results.json`, `final-python.xml`, `final-runtime.json`, `cli-results.json`,
`organization-audit.json`, and the layout/geometry comparison reports under
`test-output/reorganization-baseline/`.
