# Contributing and reviewing

Start with [build and CLI usage](README.md), then the page for the relevant game.
Prefer one reproducible issue and one bounded change per review. Existing local
changes may belong to another contributor: inspect `git status` before editing.

All source paths are relative to your checkout. Capture inputs and derived output
folders are supplied by you; the project does not require a maintainer's workspace.
See the [path conventions](README.md#paths-used-in-these-guides).

## Walk through the source

Scripts are grouped by source game under `tools/cold_war/`, `tools/black_ops_4/`
and `tools/black_ops_3/`, then by task. Common code lives in `tools/shared/`.
Use the [script directory guide](../tools/README.md) to find entry points,
understand shared imports and add support for another game. Related Python/Node
tests follow `tests/<game>/<task>/`.

| Area | Entry point | What to inspect |
| --- | --- | --- |
| Process/game discovery | `src/WraithXCOD/WraithXCOD/CoDAssets.cpp` | Game dispatch, asset pools and exporter selection |
| Structured asset CLI | `src/WraithXCOD/WraithXCOD/AssetCli.cpp` | Parsing, capabilities, settings overrides, selection, exit status |
| Dedicated placement CLI | `src/WraithXCOD/WraithXCOD/Main.cpp` | `placements` parser, run reservation, game dispatch |
| GUI workflows | `GeneralSettings.cpp`, `TerrainSettings.cpp`, `WraithXCOD.rc` in the same directory | Controls, settings keys, progress and displayed paths |
| CW readers | `GameBlackOpsCW.cpp`, `CWNonStaticCapture.h`, `CWNonStaticPlacements.h` | Pool occupancy, bounded reads, identities and transforms |
| BO4 readers | `GameBlackOps4.cpp`, `BO4ModelPlacementCapture.h` | BO4-specific layouts, source checks and placement validation |
| Model batches | `CoDAssets.cpp`, `ModelBatchResume.h` | Identity, LOD completion, portable image paths and retry behavior |
| Placement layout | `CWPlacementOrganize.h`, `tools/cold_war/capture/organize_cw_placements.py` | Transaction, public path rewrites and raw evidence preservation |
| Brush conversion | `tools/cold_war/brushes/`, `tools/black_ops_4/brushes/` | Saved-byte decoding, material decisions and verification reports |
| Terrain source contract | `tools/shared/core/layout.py`, `tools/shared/capture/finalize_research_capture.py` | Capture inventory and sealed source boundary |

Use searches to follow an action end to end:

```powershell
rg -n 'ExportModelPlacements|cworganizeplacements' src/WraithXCOD/WraithXCOD
rg -n 'SourcePlacementFile|static_models.json' tools/cold_war/capture tests
rg -n 'SupportedGames|BeginGameMode' src/WraithXCOD/WraithXCOD/CoDAssets.cpp
```

Confirm each filename and function in the checkout you are reviewing. File
organization may change; searching an action or schema is more robust than
copying an old line number.

## A useful issue or PR

1. State the game, executable build, map, selected name database and options.
2. Give the smallest command or GUI sequence that reproduces the issue.
3. Describe expected and actual behavior with counts and a relevant report field.
4. Trace the source reader, saved representation and consumer separately.
5. Add a small synthetic fixture for a decoder or data-integrity regression.
6. Report exact validation commands, results and any untested live behavior.

Do not commit personal captures, exported game assets, process dumps, installed
binaries, local virtual environments or machine-specific runtime paths. Use
small artificial records for tests. Keep copyright/license and attribution files.
Do not claim a live test from a synthetic test or a byte audit from a screenshot.

Write reusable documentation with repository-relative paths and explicit input
variables. Keep the docs set to 5–10 Markdown pages, each at most 500 lines.
Update an existing topic instead of adding a session diary. Label map-specific
research tools and list inputs that are not included in the repository.

## Extending CW, BO4, or another game

Find the game's existing `Game*.cpp` implementation and its dispatch in
`CoDAssets.cpp`. Trace one supported asset through discovery, reading and export
before adding another type. Reuse common export contracts where appropriate,
but measure that game's offsets, strides, hash rules and coordinate conventions.
CW offsets and flag meanings do not establish BO4 or another game's layouts.

For a new pool or record layout, record:

- Build identifier, map identity, pool selector, header size and field offsets.
- Count/capacity checks, free-list handling and readable address ranges.
- Raw bytes and their hash, source index, original name/hash, and resolved name.
- Readback results and failures. Two equal reads are not an atomic snapshot.
- Transform order, handedness, quaternion order, scale, bounds and units.
- Independent evidence tying a field to its meaning; unknown bits remain unknown.

Use bounded reads and explicit limits for nested pointers. Reject truncated or
inconsistent input; retain diagnostics so another reviewer can reproduce the
failure offline. Test zero/maximum counts, invalid indices, duplicate identities,
unresolved names, nonfinite transforms and unsupported layouts as applicable.

For brushes, preserve one-to-one source accounting and report added/omitted
collision categories. For placements, keep separate instances and distinguish
render placement from collision placement, proxies, splines and dynamic state.
For terrain, keep sealed capture evidence immutable; reconstruction is external.

## Working with an AI assistant

Give the assistant the repository root, this page, the game's reference page,
the failing command and the smallest sanitized report/fixture. Ask it to inspect
the actual parser and consumer before proposing flags, offsets or new schemas.
Use a prompt such as:

```text
Read docs/README.md, docs/contributing.md and docs/cw-placements.md.
Inspect git status and preserve existing work. Trace this failing placement
case from its native reader through JSON into the consumer: [reproduction].
Separate measured facts from hypotheses. Propose a small fix, add a synthetic
regression test, run the relevant checks, and show the diff and limits.
Do not invent offsets or filenames. Do not commit or push until I review it.
```

Ask for evidence at each boundary: source bytes -> decoded fields -> serialized
output -> consumer interpretation. Review generated shell commands and diffs,
especially deletion, path rewriting, broad export selectors and source-layout
assumptions. Supply saved evidence instead of repeatedly taking full captures.

## Validation and sharing

Run the checks relevant to your change from the repository root using your
configured Python interpreter. The full validation sequence is:

```powershell
python -m pytest tests -q
.\tests\run-native-tests.ps1
.\build-greyhound.ps1 -BuildOnly
& .\src\WraithXCOD\x64\Release\Greyhound.exe assets --help
& .\src\WraithXCOD\x64\Release\Greyhound.exe assets capabilities --json
git diff --check
git status --short
```

For documentation-only edits, check local links/anchors, command paths and
`git diff --check`; a native rebuild is unnecessary. For decoder changes, run
the affected synthetic tests and any available saved-data audit before widening
validation. Include the full build when changing native code or packaging.

Native logs go to `test-output/native-tests`. The build stages capture helpers
and a hash-checked brush runtime; test the staged installation as well as source
Python when changing packaging. Use Dev Tools **Check runtime** and **Check saved
export** for the appropriate artifacts. Placement catalogs list source/output
hashes; older capture-specific auditors may expect the flat source layout.

Before sharing, inspect untracked files, generated data size, docs links, runtime
dependencies and the complete diff. A commit description should explain the user
problem, resulting behavior, tests and remaining limitations. Report pre-existing
failures separately. Show the review results before pushing when requested.
