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
`exported_files/black_ops_4/placements/run_NN/` directory. `exported_files` is the
export folder set in Greyhound's settings (`exportroot`), or `--export-root PATH`
for one run; without either it is `exported_files` beside the executable.

The run contains:

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
| +0x38 | Reverse reference index plus a high-bit flag. Transforms are stored in one contiguous run per model, and the flag marks the last transform of each run (all 1,751 zm_towers and 2,779 zm_white models) |
| +0x3C | Bounding-sphere radius: half the world-bounds diagonal |

The 56-byte reference record, measured on zm_towers:

| Offset | Data |
| --- | --- |
| +0x00 | Pool-4 XModel pointer |
| +0x08 | Runtime state pointer into the executable; present with flag 0x4 |
| +0x10 | Runtime bookkeeping pointer (222 instances); not placement data |
| +0x18 | Transform record pointer |
| +0x20 | Small group index or -1; meaning unknown. Each value holds one model family. zm_towers (215 instances): stone pillar halves 0, flowering ivy 2, rubble scatter 4–26, backlit oil lamps 28 and 31. zm_white: electrical cables 0 (10 instances). A model can have instances in several groups and outside them, and none of these instances has a script string |
| +0x24 | Script string id (`ScriptStringIdRaw`); this build's string table is not located |
| +0x28 | Per-instance random value, 16 bits wide. Its distinct-value count matches uniform random draws: 25,377 against an expected 25,454 on zm_white, and 28,873 against 28,941 on zm_towers. 88 zm_towers instances (flags 3 and 35) have wider values |
| +0x2C | Flags word (`StaticModelFlagsRaw`) |
| +0x2E | 1-based spline instance index, 0xFFFF otherwise |
| +0x30 | Spatially ordered id (`SpatialOrderIdRaw`) |
| +0x34 | Always -1 |

### Spline-deformed models

`splm/` models (4,686 zm_towers instances: chains, trims, arches) have an
identity transform at the world origin. The game places them from two arrays
that the capture now saves: 48-byte instances behind gfxworld +0x460 (slot 0
reserved) and 192-byte segments behind +0x468. Each pointer leads to a
resource header `{data, stride, count}`. Rows carry `SplineInstanceIndex` and
`RequiresSplineDeformation`; do not import them at their raw transform.

Instances hold `modelXExtent`, `instanceLength`, `modelSplineOrigin`,
`distFromStartNode`, `modelScale`, up/down and left/right offsets, an exclusive
segment range and `spliningAxisType` (0..5 = +X, -X, +Y, -Y, +Z, -Z of the
model). Segments use CW's 192-byte layout. Each curve is a cubic in power form,
`p(t) = a + b t + c t^2 + d t^3` for t in [0,1], and
`world = modelToWld_origin + entToAligned @ p`. `modelXExtent` is the model's
native length along the splining axis times `modelScale`.

The game stretches that length over `instanceLength` of curve. Only 27 of
zm_white's 2,750 instances and 77 of zm_towers' 4,686 are unstretched; the
ratio `instanceLength / modelXExtent` runs from 0.20 to 5.99. Segment
`bankAngleBezierEval` is a bank angle in radians, a power-form cubic in t like
the curve. It turns the lateral frame about the tangent, up toward side.
Read this way, the bank is continuous across all 337 zm_white and 553 zm_towers
segment joins. 248 zm_white and 1,192 zm_towers instances sit on a bank.

```powershell
python tools/black_ops_4/placements/resolve_bo4_splines.py '<placements run>'
```

The resolver writes `splined_models.json` and `static_models_resolved.json`.
The latter gives each spline row a rigid placement:

- The model origin sits at curve distance
  `distFromStartNode − modelSplineOrigin.x × stretch`, where stretch is
  `instanceLength / modelXExtent`. When that distance lies beyond either end
  of the instance's segments, the origin continues along the end tangent. It is
  not clamped to the curve. On Blackout this rule reproduces the render box for
  22 of 24 such straight rows; clamping reproduces none, and was off by up to
  139 units.
- The splining axis is scaled by `modelScale × stretch` and the other two by
  `modelScale`, so `ModelScale` is non-uniform on stretched rows.
- The frame is the tangent, up = world +Z (the segment's own frame on vertical
  curves) and side = up × tangent, banked by the angle at the origin.
- Before banking, the model faces up with +Z for X and Y splining axes, with −X
  for +Z and with +X for −Z. That is, the model turns about Z, or about Y for a
  Z axis, until its splining axis leads.

Bending, and a bank that varies along one instance (`SplineTwistIgnored`), are
not representable.

The report checks these rules against the game. On straight, axis-aligned
spans, each model's render box (XModel header +0x10C / +0x118) placed by the
rule reproduces the game's bounds within 0.05 units:

| Map | Rows matched | The old rule (no stretch or bank, +X up for +Z) |
| --- | ---: | ---: |
| zm_white | 202 of 204 | 27 |
| zm_towers | 1,075 of 1,155 | 32 |

All six axis types are covered. The zm_towers misses are twisted chain links
and stair blocks, within 0.53 units; the zm_white misses are a dirt road (1.74)
and a sloping plywood board (0.13). Neither map has a banked instance with
up/down or left/right offsets, so applying offsets in the banked frame is
unverified. Curve spans lie inside the game's render bounds for 96.5%
(zm_towers) and 97.7% (zm_white) of rows, with segment joins within 7e-4 and
2.2e-3.

gfxworld +0x1B8 is the per-frame `smodelUpdateFrame` counter. The capture's
stability checks exclude it; before that fix, placement capture failed on any
map that was rendering.

The mapping is a permutation, not matching physical row order. The reader
checks aligned, bijective references and reverse indices, validates transforms
and bounds, and requires stable readback. Render scale is the placement scale.
Collision disagrees with it only for models with attachments, whose collision
is built at scale 1 (see [attached models](#attached-models)).

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

### Verifying every instance from its bounds

Collision covers only instances that have a collision copy (20,658 of 33,495
non-spline instances on zm_towers). The transform's own world bounds cover the
rest, because the game computed them from the model and that transform:

```powershell
python tools/black_ops_4/placements/verify_bo4_placement_bounds.py $run '<xmodels export folder>'
```

Export the placed models first with `--all-lods` and the same name database as
the run. The tool reads CAST first, then SEModel, OBJ or SMD; all four give the
same bounds. CAST, SEModel and OBJ are written in centimetres (x2.54) and SMD
in game inches; the tool converts each back. The tool writes `placement_verification.json` with one status per row.
zm_towers results:

| Status | Instances | Meaning |
| --- | ---: | --- |
| `mesh_bounds_exact` | 29,321 | AABB of the most detailed LOD under the row's transform equals the stored bounds |
| `pose_box_rotation_proven` | 3,859 | Flag 0x4 (animated: arena crowd, fxanim `_smod`); one pose box explains instances with different rotations |
| `pose_box_consistent` | 174 | Flag 0x4; pose box fits, but no second rotation proves it |
| `mesh_bounds_partial` | 61 | Four or more faces exact; bounds extended upward (chaos strands) |
| `unverified` | 80 | Shackles (bounds padded 1-4 units), chaos puddles/strands, `xmodel_d87a01f651d83ad` |

The 185 instances whose collision scale differs from render scale all
reproduce their bounds with the render scale and not with the collision scale,
so render scale is the placement scale. 184 of them are models with
attachments, whose collision is always unscaled. Animated models export in bind pose
(the crowd as a T-pose), so their placement is right but the mesh is not what
the game shows.

`--largest-lod` previously chose BO4 LODs by distance, which is not ordered by
detail (LOD1 of 8 for `p8_zm_gla_column_block_04_dmg`). BO4 now uses CW's
face/vertex-count selection, the LOD the game's bounds are built from.

Without exported meshes, the XModel header gives a weaker check. The 336-byte
header holds the render bounds minimum at +0x10C and maximum at +0x118. +0x13C
is the distance from the origin to the farthest corner of those bounds, on all
2,779 zm_white models. Under an axis-aligned rotation, the placed box's AABB
is the mesh's AABB; under any other rotation it contains it. zm_white's 29,477
non-spline instances:

| Result | Instances |
| --- | ---: |
| Exact (12,876 axis-aligned, 1,721 rotated) | 14,597 |
| Stored bounds inside the placed box | 14,519 |
| Outside: a hanging planter and ceiling-fan blades, probably moving parts without flag 0x4 | 16 |
| Animated (flag 0x4), pose boxes | 345, 56 of them outside |

330 axis-aligned instances, across 83 models, sit inside rather than on the
box, so those models' header bounds are looser than their mesh.

1,358 clip_map collision instances belong to four models with no render
instance and no entity (`p8_zm_gla_egy_coin_gold`, `p8_zm_esc_skull_sgl`,
`p8_zm_gla_cel_floor_cut_01_sgl_08`, `p8_zm_gla_trim_05_straight_128_01a`).
Most coins lie inside rendered `coin_gold_pile_med` instances. They are not
emitted as placements. On zm_white, every collision-only model turned out to
be an [instanced model](#instanced-models). zm_towers has not been re-checked
for them.

### Transform order between sessions

Placements survive a game restart except for their order. Two zm_white
sessions gave the same 32,227 references and transforms, byte for byte, except
in the following fields:

- Transform runs are sorted by XModel pointer, which is an allocation address.
  The order changes with every load: 31,293 references pointed at a different
  transform slot. 3,168 transforms changed only in their +0x38 reverse index.
- The +0x24 script string id changed on 19 references, because the ids are
  session-local.

To match instances across sessions, compare model and transform, not index.

### Attached models

An XModel can carry attached child models. The 336-byte model header holds the
list pointer at +0x70 and the list count at +0x14A (u8). The count is nonzero
exactly when the pointer is set: 139 of zm_white's 2,779 placed models, and 73 of
zm_towers' 1,255 collision models. Each record is 40 bytes:

| Offset | Data |
| --- | --- |
| +0x00 | Child XModel pointer |
| +0x08 | Tag: 0 for the model origin, otherwise a parent bone id (u32 script string, as in the header's bone list at +0x10) |
| +0x0C | Offset XYZ |
| +0x18 / +0x1C / +0x20 | Pitch / yaw / roll in degrees, composed like CoD's `AnglesToAxis`: yaw about Z, then pitch about Y, then roll about X |
| +0x24 | Zero |

The child's world transform is built in three steps:

1. Start from the parent's transform.
2. If the record is tagged, apply that bone's base pose from header +0x40.
3. Apply the record's offset, multiplied by the parent's scale, and its
   angles.

The child takes the parent's scale.

The game places every child as its own instance, so `static_models.json` needs
no expansion. Expanding the lists again would duplicate the children. zm_white
expects 4,837 children:

- 3,014 origin-tagged and 1,259 bone-tagged children are static instances at
  the expected transform. The worst rotation error on a tagged child is 4e-6.
- 544 paper cups on 34 `p7_cup_coffee_paper_stack_01` stacks are
  [instanced models](#instanced-models), within 6e-5 units.
- 20 gutter brackets belong to `splm/` gutters. Their parents' raw transform is
  the spline identity at the origin, and the brackets are placed along the
  curve.

Attached children never get a collision instance. None of zm_white's 4,273
static children has one, including 420 whose model has collision when placed
on its own. The parent's collision does not contain them either: in all 41
testable pairs, none of the child's collision vertices appears in the parent's
collision surfaces.

Collision instances of models with attachments are always built at scale 1,
whatever their render scale:

- zm_white: all 209 such instances, across 50 models.
- zm_towers: 184 of 185. The 185th is a `p8_zm_chaos_strands_hanging_02`
  instance that shares its origin with another instance.

No model without attachments shows this. Their collision does not match their
rendered size; render scale is authoritative.

### Instanced models

gfxworld +0x470 holds a second placement system, used for foliage, grass kits,
pipes, bricks and cups. `static_models.json` does not include it yet. Its
header:

| Offset | Data |
| --- | --- |
| +0x00 | Instance count (u32) |
| +0x04 / +0x08 | Instance total with each cell's count padded to a multiple of 4 / of 64 (15,204 / 17,024 on zm_white) |
| +0x10 | Instance count again |
| +0x14 | Surface count: rows of the 12-byte resource (688 on zm_white) |
| +0x18 | LOD count summed over the models (280) |
| +0x20 | Model count |
| +0x28 | 128-byte model entries |
| +0x50 / +0x58 / +0x60 | Resource headers `{data, stride, count}` for the 20-byte instances, 144-byte per-model records and 12-byte records |

| Record | Fields |
| --- | --- |
| Model entry, 128 bytes | Bounds +0x08, XModel pointer +0x20, LOD/draw structure +0x38, cell count +0x40, cell pointer +0x48 |
| Cell, 52 bytes | First instance +0x00; running offsets in the 4- and 64-padded arrays +0x04 / +0x08; 16 × cell index +0x0C; instance count +0x10 and again +0x14; -1 at +0x18; bounds +0x1C. The cells partition the instance array |
| Instance, 20 bytes | Four float16 holding the rotation quaternion XYZW multiplied by sqrt(scale), then the float32 position; scale = \|q\|² |
| Per-model record, 144 bytes | Model-space bounds +0x00, LOD count +0x18, first surface row +0x2C, surfaces per LOD +0x30 (u32 × 8, zero past the LOD count), one float per LOD +0x70 (decreasing; probably switch distances, units unverified). Floats at +0x1C and +0x50 are not decoded |
| Surface, 12 bytes | Draw arguments: index count (a multiple of 3), base vertex, first index. Within each LOD the first index is the running index count (280 of 280 LODs) |

LODs run from coarsest to finest: the first LOD of `p8_foliage_brush_desert_03`
is one 2-triangle card, and its last has 6,363 indices.

zm_white has 15,142 instances of 38 models, with scales from 0.2 to 5.0:

- 1,578 clip_map collision instances belong to them. Each matches an instance
  within 1e-4 units in position, 7e-4 in rotation and 2e-3 in scale, the
  precision of float16.
- Grass kits sit a median of 0.02–0.07 units above the terrain.

### Dynamic entities

Clipmap +0x148 / +0x150 is a count and a pointer to 392-byte dynamic-entity
definitions. zm_white has 194 of them, covering 44 prop models such as cans,
plates, bottles and helmets.

| Offset | Data |
| --- | --- |
| +0x00 | Quaternion XYZW |
| +0x10 | Position |
| +0x20 | XModel pointer |
| +0x130 | Physics preset pointer |
| +0x148 | Contents |
| +0x14C | Scale, 0.45 to 1.5; 97 of the 194 are not 1 |

Clipmap +0x160 points to the runtime poses. Each is 176 bytes: quaternion
+0x10, position +0x20 and world bounds +0x2C / +0x38. At capture time all 194
poses equalled their definitions. Dynamic entities are not in
`static_models.json`.

The pose bounds are physics bounds, and they prove the scale:

- All 9 upright scaled instances, across 6 models, are exactly +0x14C times
  their render height (XModel header +0x10C / +0x118), within 0.001.
- An electrical panel stands 95.686 tall at 1.0 and 43.059 at 0.45.
- Unscaled instances instead carry a 1-unit margin on every face; 66 of them
  match the collision box plus 1 exactly. That margin made a pot at 0.5 look
  like 0.42 of the one at 1.0 (5.0 against 12.0).
- Models under 2 units tall (a can, a plate) come out 2.0 × scale tall.

### Collision accounting: zm_white

Every one of zm_white's 22,594 clip_map collision instances is accounted for:

- 21,016 match static instances, with rotation within 4.4e-6. 209 of them
  differ in scale, all because of the attachment rule.
- 1,578 match instanced models.

587 static instances have no collision even though their model has collision
elsewhere:

- 420 are attached children.
- 44 share their origin with another instance of the same model.
- 123 are backdrop props. 108 chain-link fences run along y ≈ −2,600 from
  x = −11,773 to 15,935, and 15 telephone poles run south to y = −30,098. 98 of
  them lie outside the xy box of every instance that has collision. They look
  like props authored without collision, which the render record does not
  store: their flags match those of instances with collision.

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
`src/WraithXCOD/WraithXCOD/games/black_ops_4/reader/GameBlackOps4.cpp`. Capture probes,
placement validation and brush conversion have separate contracts.
The [research guide](bo4-terrain-research.md) identifies measured layouts
and unresolved branches; the [contribution guide](contributing.md) explains
fixtures, validation and support for additional games.
