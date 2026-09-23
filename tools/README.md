# Scripts by game

Pick the **source game**, then the task. CW-to-BO3 converters belong to Cold War;
BO3's stock material and tool definitions belong to Black Ops 3. Code used by
multiple games lives once under `shared/`.

```text
tools/
  cold_war/
    capture/          # capture, decode and organize map/entity/FX evidence
      templates/      # script templates consumed by the CW helpers
    placements/       # model placement counts, budgets and source splitting
    brushes/          # CW collision decoding, hulls and Radiant conversion
    research/         # development investigations and capture comparisons
  black_ops_4/
    capture/          # terrain packaging and GDT intake verification
    placements/       # BO4 static placement auditing
    brushes/          # BO4 world/model physics, triggers and conversion
    research/         # handler disassembly and typed-prefab investigations
  black_ops_3/
    reference/        # target-game catalogue, material definitions and GDT
  shared/
    capture/          # source organization and sealed inventory verification
    core/             # source layout contract
    brushes/          # common export layout and progress handling
    models/           # common placement-name normalization
    name_db/          # name database importer used by CW and BO4
    runtime/          # packaging, cross-game export entry point and checks
  tool_bootstrap.py   # shared import resolver for source and installed tools
```

## Find a starting script

| Task | Script |
| --- | --- |
| Organize CW placements | [organize_cw_placements.py](cold_war/capture/organize_cw_placements.py) |
| Decode saved CW entities | [decode_cw_entitylist.py](cold_war/capture/decode_cw_entitylist.py) |
| Audit CW placement counts | [audit_cw_placement_counts.py](cold_war/placements/audit_cw_placement_counts.py) |
| Offline CW spline bake with per-model images and material info | [bake_cw_splines.py](cold_war/placements/bake_cw_splines.py) |
| Audit BO4 placements | [audit_bo4_placements.py](black_ops_4/placements/audit_bo4_placements.py) |
| Package BO4 terrain evidence | [package_bo4_terrain.py](black_ops_4/capture/package_bo4_terrain.py) |
| Regenerate the BO3 reference | [build_reference.py](black_ops_3/reference/build_reference.py) |
| Import alternate CW/BO4 names | [import_echo_bo4.py](shared/name_db/import_echo_bo4.py) |
| Package installed tools | [package_runtime.py](shared/runtime/package_runtime.py) |
| Check the installed runtime | [verify_runtime.py](shared/runtime/verify_runtime.py) |

From the repository root, use the full path to a script. For example:

```powershell
python tools/cold_war/capture/organize_cw_placements.py --help
python tools/black_ops_4/capture/package_bo4_terrain.py --help
python tools/black_ops_3/reference/build_reference.py --help
python -m pytest tests -q
```

Read a research script before running it: some require a particular saved
capture, optional dependencies, or a live game. Research directories contain
investigations, not a promise of complete game support. NumPy/SciPy are required
for packaging/conversion; the alternate name importer and some live CW research
helpers also require `lz4` in the developer interpreter.

## Runtime and contribution rules

The installed `tools/` folder mirrors these game/task paths. Its `runtime/`
directory contains the isolated Python distribution; `manifest.json` inventories
the shipped helpers and data. The build packages these together. Upgrading a
previous installation moves its old tool directories into a sibling
`tools-legacy-layout-*` archive, preserving local files outside the active tree.

Scripts bootstrap their imports from `tool_bootstrap.py`, so entry points also
work from another working directory and with isolated Python (`-I`). Filenames
remain descriptive and keep game prefixes; shared modules are not copied into
each game folder. The name importer retains its historical `bo4` filename but
serves both CW and BO4, which is why it is under `shared/name_db/`.

BO4 converters also reuse some geometry functions from CW-owned converter
modules. Follow their imports for those dependencies; shared geometry is not
evidence that the games use the same binary layouts.

Python and Node tests live under `tests/<game>/<task>/`; common runtime tests
are in `tests/shared/`. Standalone C++ tests and their PowerShell runner remain
at the test root. Project-wide build scripts remain at the repository root.

For a new game, add its folder when adding actual scripts. Use the existing task
names, register its import directories in `tool_bootstrap.py`, update the
packager's game allowlist, and add a direct-entry-point test. Do not infer support
by creating empty game folders or copying another game's offsets.

See [build and CLI usage](../docs/README.md) and the
[contribution walkthrough](../docs/contributing.md) for the full workflow.
