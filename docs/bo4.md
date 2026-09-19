# Black Ops 4 workflows

[Documentation index](README.md) | [Contributing](contributing.md)

BO4 supports static placements, model batches, supported brush exports and
diagnostic captures. Its terrain probe and binary layouts are separate from
Cold War's. Start with [build and CLI usage](README.md).

## Static placements

Load a BO4 map and use **Map & Model Export**, or run from the checkout:

```powershell
$gh = '.\bin\cli\Greyhound-cli.exe'
& $gh placements --name-db bundled
```

Find the result in the reported
`exported_files/black_ops_4/placements/run_NN/` directory:

| File | Purpose |
| --- | --- |
| `static_models.json` | Plain placement array, usable with Models from JSON |
| `placement_report.json` | Completeness, database and unresolved-name counts |
| `diagnostics/` | Captured tables, model headers and failure evidence |

Each placement preserves `Name`, `SourceName`, `Position`,
`RotationDegrees`, `RotationQuaternion`, `ModelScale`, `BoundsMin`
and `BoundsMax`. `Name` matches the cleaned export filename;
`SourceName` retains the lookup identity. Unresolved names use
`xmodel_<hash>` with `NameResolved: false`.

This command exports transforms, not meshes/images. Use **Models from JSON**
for referenced assets. Static gfxworld data does not decode dynamic spawning,
runtime visibility, proxy replacement or deformation.

### Placement reader and audit

The measured gfxworld pool is 14, with a 6,832-byte header. The static count
is at +0x1BC. The array at +0x400 contains 56-byte model records:
+0 points to a pool-4 XModel, and +0x18 selects a 64-byte transform from
the array at gfxworld +0x408.

| Transform offset | Data |
| --- | --- |
| +0x00 | Quaternion XYZW |
| +0x10 | World position XYZ |
| +0x1C | Uniform render scale |
| +0x20 / +0x2C | World bounds minimum / maximum |
| +0x38 | Reverse reference index plus a high-bit flag |

The mapping is a permutation, not matching physical row order. The reader
checks aligned, bijective references and reverse indices, validates transforms
and bounds, and requires stable readback. Render scale is preserved even when
a collision instance uses a different scale.

Euler values use XYZ components of a ZYX rotation. The original quaternion
is retained; a singularity branch preserves heading near 90-degree pitch.

```powershell
$run = '<path to your BO4 placement run>'
python tools/black_ops_4/placements/audit_bo4_placements.py $run
```

Optionally pass `--collision` with a matching collision source. The audit
compares serialized fields and quaternion/Euler matrices. Collision is an
independent comparison, not a replacement for render placement data.
On capture failure, inspect `diagnostics/placement_error.json` when present.

## Name databases

**Settings > General > BO4 / CW name database** selects the bundled database
or a separately imported echo000 database. Click **Load Game** after changing
it. Caches are replaced on reload, not merged, and old exports are unchanged.

The legacy setting key `bo4namedatabase` and directory `echo000_bo4`
serve both BO4 and CW. Missing alternate files produce an explicit error.
CLI `--name-db bundled` or `--name-db echo000` overrides only that run;
reports record the database actually loaded.

To import CSV sources from
[echo000/cod-name-db](https://github.com/echo000/cod-name-db):

```powershell
$checkout = '<path to your extracted cod-name-db checkout>'
$installation = '<folder containing the Greyhound executable you use>'
$output = Join-Path $installation 'package_index/echo000_bo4'
python -m pip install lz4
python tools/shared/name_db/import_echo_bo4.py $checkout $output
```

The importer handles the nested folder from ZIP extraction. It imports the
five non-v2 FNV1a dictionaries for animations, images, materials, models and
sounds. It validates 60-bit hashes, rejects malformed/mismatching rows and
excludes ambiguous entries. `source.json` records checksums and rejection
counts. Bundled databases and source CSVs are preserved.

The `.cdb` container is not parsed directly. Name coverage varies with map
and database revision; a resolved name neither changes placement transforms
nor guarantees that a corresponding target-game asset exists.

## Capture modes

**Settings > Terrain > Black Ops 4 capture run by Export** controls the terrain
export route. The same catalogue appears under **Dev Tools > Black Ops 4:
diagnostic captures**.

Modes 1–7 can run from Dev Tools without selecting a TerrainGfx asset. Mode 5
uses the brush workflow. Mode 0 requires selecting and exporting a terrain asset.

| Mode | Capture | Main evidence |
| --- | --- | --- |
| 0 | Terrain source probe | `header.terraingfx.bin`, `terraingfx_probe.json`, referenced regions and resident image mips |
| 1 | Map world pools | `world_pools_probe.json`, pool/slot payloads |
| 2 | Model collision references | `model_collision_probe.json`, surface headers and triangle equations |
| 3 | Model physics | `model_physics_probe.json`, `model_physics.bin` |
| 4 | Model placements | Placement capture, static JSON and report |
| 5 | Radiant brush prefabs | Separate brush/clip/model-physics export |
| 6 | Collision handler tables | `collision_handlers.json`, handler byte ranges |
| 7 | Named surface declarations | `surface_flags_probe.json`, without a map-pool capture |

CLI asset exports accept `--bo4-capture-mode`. Discover a terrain asset,
then select it explicitly:

```powershell
$gh = '.\bin\cli\Greyhound-cli.exe'
& $gh assets list --type terrain --json
& $gh assets export --type terrain --name 'EXACT_NAME_FROM_LIST' --bo4-capture-mode 3 --json
```

`GREYHOUND_BO4_WORLD_PROBE` overrides the GUI and CLI selection when set.
The GUI identifies and disables the forced choice. Check inherited environment
variables when a diagnostic run differs from the selected mode.

BO4 TerrainGfx is pool 0x98. Its export is a measurement probe, not the sealed
CW terrain contract. Do not run CW finalization against it. The separate
[terrain packager and layout notes](bo4-terrain-research.md) explain its limits.

## Radiant brushes

Load a BO4 map, open **Radiant Brushes**, then **Export brushes now**.
The automatic collision-pool checkbox is CW-only; use the explicit BO4 action.

Outputs live in `exported_files/black_ops_4/brushes/run_NN/`. Under
`prefabs/`, categories are `brushes`, `clips` and `model clips`.
World/inline geometry remains separate from model-attached physics.
Metadata and capture diagnostics stay outside the prefab tree.

Import world-coordinate maps at **origin 0 0 0, angles 0 0 0, scale 1**.
The workflow does not export terrain, render models, GDT assets or ported scripts.

### Material decisions

The decoder validates brush ranges, ownership, leaf contents and captured
surface declarations using BO4 evidence. CW bit meanings are not substituted.

Each source brush receives one output brush/material decision. The selector
minimizes omitted collision categories, then added categories, then
slick/solidity differences and surface properties. Native BO3 brush flags can
represent supported weapon/sight behavior without overlapping duplicate hulls.

Read `metadata/material_assignments.json` for source flags, selected tools,
native flags and every deviation. Unknown bits and unresolved surface codes
remain explicit. A nonSolid source with no clip categories must not acquire
an arbitrary solid placeholder. Named-property agreement does not prove
identical compiled gameplay.

### Review limitations

- Unidentified model primitive layouts remain raw evidence; no guessed boxes
  replace them.
- Trigger model/hull/slab association has structural evidence but still needs
  independent runtime-dispatch confirmation. Related prefabs are marked
  `ASSOCIATION_REVIEW`.
- Parameter-only boxes with unverified dimensions/origins stay in JSON.
- Authored and runtime transforms remain separate. Disagreements keep review
  status rather than being adjusted to fit.
- Triangle evidence is optional and separate from brush geometry.
- Trigger hulls do not port BO4 scripts or guarantee BO3 trigger behavior.

Read `metadata/export_report.json` and `verification.json` before using
the output. `exported_with_review` and `all_placed_brushes_present: false`
must remain visible when omissions exist. Successful plane serialization
does not establish Radiant compilation or gameplay equivalence.

## Where to contribute

Start in [BO4 tools](../tools/black_ops_4/) and
`src/WraithXCOD/WraithXCOD/GameBlackOps4.cpp`. Capture probes,
placement validation and brush conversion have separate contracts.
The [research guide](bo4-terrain-research.md) identifies measured layouts
and unresolved branches; the [contribution guide](contributing.md) explains
fixtures, validation and support for additional games.
