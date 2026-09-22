# Cold War collision and brushes

[Documentation index](README.md) | [Contributing](contributing.md)

Export supported world brushes, clips, trigger/volume hulls and model-local
collision from a loaded Cold War map. Unknown collision layouts remain in
diagnostics; this workflow does not reconstruct terrain.

## Export and inspect

1. Load the map in Greyhound.
2. Open **Settings > Radiant Brushes** and choose the required options.
3. Select **Export brushes now**.
4. Open the reported run and read `metadata/export_report.json`.
5. Inspect material differences and rejected geometry before using the prefabs.

The packaged converter, isolated Python runtime and BO3 reference catalogue
ship beside Greyhound. Generating prefabs does not require a local BO3 install.
Opening, compiling and testing them requires your own target-game tools.

User-facing maps are grouped under `prefabs/`; diagnostic bytes and metadata
stay outside that folder. Use the report's `prefabs` entries to locate outputs.

| Output | Use |
| --- | --- |
| `<map>_brush_collision.map` | Assigned collision/clip families |
| `<map>_other_brushes.map` | Other tools, including supported traversal brushes |
| `<map>_nonblocking_reference.map` | Excluded shapes on the visible no-compile reference layer |
| `<map>_render_surfaces.map` | Verified supplied material/UV surfaces, when available |
| `<map>_volumes.map` | Captured volume entities, when enabled |
| `<map>_triggers.map` | Supported trigger geometry, when enabled |
| `metadata/collision_metadata.json` | Source identities, instances, transforms and geometry checks |
| `metadata/material_assignments.json` | Source properties, selected material and added/omitted behavior |
| `metadata/triggers.json` | Source entities, hulls, output links and omissions |

Import world-coordinate prefabs at **origin 0 0 0, angles 0 0 0, scale 1**.
Model-local collmaps below use a different coordinate contract.

For the supported CLI route, discover the pool row first, then use:

```powershell
$gh = '.\bin\cli\Greyhound-cli.exe'
& $gh assets export --type rawfile --name cw_pool_018_clip_map_headers --cw-radiant-brushes --json
```

## Materials and geometry

The capture saves filter tables and named contents, surface and traversal
declarations. A surface label is accepted only when its pointer association
and per-brush contents union agree. Unjoined indices remain unresolved.

Material selection prioritizes omitted collision properties, added non-item
queries, and slick/nonSolid behavior. Within these constraints it prefers exact
surface enums, then documented related families, before a generic tool. Added
itemClip is explicitly recorded. Mixed source surfaces use their most
frequent named type with a deterministic tie break. The selected tool and
every approximation remain in the assignment report.

One source brush receives one material decision. Partitioning a hull to meet
BO3's plane limit can create several pieces, but does not make overlapping
copies to combine material behavior. Exact hull predicates, partition checks
and serialized plane checks protect the source geometry.

A matching material name does not prove identical engine behavior. `noDraw`,
`nonSolid`, surface type, traversal and collision-query flags are separate
properties. Unknown fields are not silently interpreted as BO3 flags.

## Model-local collision

Model collmaps are written below
`exported_files/collmaps/black_ops_cw/<map>/<model>.map`, relative to the
active installation.

Ownership uses an exact join from `BOCWXModel.XCollisionPtr` to captured
96-byte collision assets. Pool occupancy and headers are verified by readback.
Repeated instances reuse one model file. Sanitized filename collisions receive
an identity hash; a differing existing file is retained and reported.

Only supported convex brush components are exported. Compact triangle
components can be missing even when a brush component from that model succeeds.
Read `manifest.json`: `complete_model_collision=false` and missing-component
entries describe that boundary. No guessed boxes replace unsupported shapes.

Collmaps preserve model-local coordinates without instance translation,
rotation, scale or recentering. They contain no render mesh. Do not insert them
at world origin and treat them as already placed world collision.

The local compound reader follows its binding table and counted 80-byte
surface headers. It respects the separate byte/word/group/header alignments;
tree byte counts are not rounded between surfaces. The supported brush
component uses the 208-byte brush header at its own measured offset.

## Physics policy

Model-local physics-only shapes remain in the nonblocking reference output.
The proposed clip material is recorded, but it is not applied as player collision.

The manifest records source materials, substitutions and
`physics_conversion_verified=false`. Original assignments remain in
`diagnostics/radiant_work/physics_research/`. Mass, inertia, constraints,
dynamics and compact-triangle reconstruction are outside this policy.
World-brush assignments are separate.

## Texture transfer

The direct exporter can consume independently verified material/UV associations
from `verified_render_surfaces.jsonl` beside a capture, or the converter CLI's
`--surfaces` option. It emits nonColliding render patches separately from brush
collision and preserves the supplied material, UV and optional color data.
`metadata/render_transfer.json` records availability on every export. The saved
collision-only captures do not contain those associations; surface categories
and render-model ownership are not sufficient to reconstruct original textures.
See the [runtime contract](../tools/shared/runtime/README.md#verified-texture-transfer).

## Other collision and navigation

The optional float-triangle OBJ exporter reads supported loose and packed
native payloads. It retains capture coordinates and applies no world placement.
It does not complete compact/quantized branches or turn a mesh into Radiant
brushes. See [runtime options](../tools/shared/runtime/README.md#optional-collision-surfaces).

ENTITYLIST negotiation nodes and GAME_MAP navigation data are separate from
clip-map brushes and TRIGGERLIST hulls. Use the [navigation guide](cw-navigation.md)
for their capture, pairing and conversion rules. A traversal material alone
does not port directed links, actor restrictions or animation scripts.

Trigger/volume geometry likewise does not install gameplay scripts. Keep
source properties, omitted fields and original entity namespaces when reviewing
the [entity data](cw-effects-entities.md).

## Collision reader code probe

**Dev Tools > Cold War capture options** exposes the collision-reader code
probe; the CLI switch is `--cw-collision-code-probe`.
`GREYHOUND_CW_COLLISION_CODE_PROBE` can force it on.

This diagnostic reads a 16 MiB code span at module-relative RVA `0xC800000`
and writes `collision_reader_code.bin` with identification/readback metadata.
It replaces the normal pool evidence export, including in headers-only mode.
Explicit Radiant brush exports bypass this override.

The RVA belongs to a measured executable build. Equal readback on another
build can still be the wrong code. Verify the build and consumer instructions
before interpreting the span; this option is not a general collision decoder.

## Contributing to collision support

Start in [CW brush tools](../tools/cold_war/brushes/) and the native readers in
`src/WraithXCOD/WraithXCOD/`. Trace capture ownership before changing hulls
or material selection.

Useful work includes compact triangle decoding, unresolved side-filter joins,
additional build profiles and cross-map validation. Preserve rejected shapes
and bounds disagreements instead of modifying coordinates to hide them.

The bundled target reference is
[bo3_reference.json](../tools/black_ops_3/reference/bo3_reference.json).
To regenerate it, use your BO3 installation:

```powershell
$bo3 = '<path to your Black Ops III installation>'
$output = '<path for a new reference.json>'
python tools/black_ops_3/reference/build_reference.py --bo3 $bo3 --output $output
```

Relevant files inside that installation include `texture_assets/tools.gdt`,
`art_assets/t6_legacy/texture_assets/clip.gdt`, `deffiles/material.awi` and
`bin/t7.def.json`. Their definitions explain target authoring semantics;
they do not establish CW binary offsets.

Report geometry checks, Radiant compilation and gameplay tests separately.
A saved-data replay or a successful isolated fixture is not a clean compile
of an assembled map. See [contribution checks](contributing.md#validation-and-sharing).
