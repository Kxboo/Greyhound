# Black Ops 4 terrain and collision research

[Documentation index](README.md) | [BO4 workflows](bo4.md) | [Contributing](contributing.md)

This page describes producer contracts, measured BO4 layouts and remaining
decoder work. Most measurements originated from `zm_white`; validate them
against the game build and map you are studying. Counts from a historical
capture are not requirements for another map.

## Terrain source packaging

[package_bo4_terrain.py](../tools/black_ops_4/capture/package_bo4_terrain.py)
assembles the measured `zm_white` v45 probe into a
`superterrain-bo4-source-package-v1` package:

```powershell
$probe = '<path to your compatible BO4 terrain probe>'
$output = '<path to a new source-package folder>'
python tools/black_ops_4/capture/package_bo4_terrain.py $probe $output
```

This packager is calibrated to that probe, including fixed layer-weight names.
Inspect the implementation before adapting it to another asset. It is not
automatically invoked by Greyhound's terrain export.

The package preserves:

- Sector-local material ordering, image bindings and original identities.
- Independent BC4 layer weights, R16 heights, cutout bits and tile masks.
- UV matrices and uninterpreted material constants.
- Source files with SHA-256 comparisons.
- A `materials/superterrain_materials.json` intake recipe.

The recipe is not a GDT. Full material names remain distinct from basename
aliases used by a consumer. Height/reveal is not automatically roughness, and
unknown semantic bindings remain unknown.

BO4's independently overlapping weights must not be replaced with a fabricated
discrete index plane or silently normalized. A consumer needs a BO4-specific
intake path. Terrain reconstruction and OMPV baking are external to Greyhound;
this repository does not ship a configured consumer workspace.

[verify_bo4_gdt_intake.cjs](../tools/black_ops_4/capture/verify_bo4_gdt_intake.cjs)
requires a separately supplied GDT project and materials directory. It checks
that consumer's source parser in memory, not a distributed desktop binary or
a compiled BO3 map.

## Find the relevant capture

Use [BO4 capture modes](bo4.md#capture-modes) to collect only the branch needed.

| Area | Native entry point | Offline tools |
| --- | --- | --- |
| World pools | `BO4WorldPoolProbe.h` | `audit_bo4_world_probe.py`, `decode_bo4_collision.py` |
| Static placements | `BO4ModelPlacementCapture.h` | `audit_bo4_placements.py` |
| Model triangle collision | `BO4ModelCollisionProbe.h` | `decode_bo4_model_collision.py` |
| Model physics | Mode 3 capture | `decode_bo4_model_physics.py` |
| Primitive investigation | Saved model-physics evidence | `analyze_bo4_physics_primitives.py` |

Native headers are under `src/WraithXCOD/WraithXCOD/`; offline decoders are
under [BO4 brushes](../tools/black_ops_4/brushes/) unless listed in
[placements](../tools/black_ops_4/placements/). Read each script's `--help`
and source before choosing inputs.

The measured world pools include:

| Pool | Reference name | Header bytes |
| --- | --- | ---: |
| 11 | clipmap / col_map | 728 |
| 12 | comworld | 96 |
| 13 | gameworld | 96 |
| 14 | gfxworld | 6,832 |
| 147 | streamerworld | 256 |
| 118 | entity_list | 32 |

An initial one-hop probe can hit its target limit without capturing a complete
graph. Check occupancy, free-list agreement and the capture's actual read
coverage before treating a field as a fully recovered array.

## World brush layout and ownership

The supported BO4 world decoder uses these measured fields:

| Location | Interpretation |
| --- | --- |
| clipmap +0x2B0 / +0x2B8 | Brush count / pointer |
| Brush +0x00 / +0x08 | 20-byte side records / float3 vertices |
| Brush +0x10 / +0x20 | Minimum / maximum XYZ |
| Brush +0x1C | Raw contents |
| Brush +0x2C | Six axial filter indices, uint16 |
| Brush +0x38 / +0x3A | Vertex / side counts, uint16 |
| clipmap +0x278 | 32-byte leafbrush nodes, not brush records |
| clipmap +0x68 | 56-byte collision leaves |
| clipmap +0x58 | 24-byte BSP nodes |

Brush records are 64 bytes. Validate all vertex/side spans and ownership.
Positive leafbrush-node counts reference indices through +16. Branches use
node-relative children at +24/+28; a -1 count also visits the following node.
BSP signed children encode leaves as `-(leaf + 1)`.

The header count at +0x280 can describe the sum of leaf references rather than
one unique physical allocation. Shared pointer ranges and unreachable nodes
must not extend the trusted decode into adjacent memory.

World ownership follows BSP roots. Inline ownership follows clipmodel roots
and is checked against gfx-model bounds. Unused inline-library shapes stay
unplaced; they must not be emitted at an invented world origin.

The exact hull backend is shared with CW for mathematical operations only.
It does not imply shared binary layouts or contents meanings. A record with
too few points to form a volume remains rejected. Bounds/plane discrepancies
are retained rather than hidden by clamping or snapping coordinates.

## Entity transforms

Measured runtime entity records are 48 bytes: model index +16, unknown word
+20, origin +24 and angles +36. Earlier external 20/32 offset candidates did
not establish this runtime layout.

Keep authored transforms, runtime record transforms and gfx bounds separately.
A disagreement can have several causes; runtime motion is a hypothesis until
independently established.

## World triangle collision

`decode_bo4_triangle_collision.py` reads 36-byte surface records at
clipmap +0x98:

| Offset | Field |
| --- | --- |
| +0 | Six bounds floats |
| +24 | Triangle start, uint32 |
| +28 | Vertex-reference start, uint32 |
| +32 / +33 | Triangle / vertex-reference counts, uint8 |
| +34 | Raw material index, uint16 |

The vertex-reference array comes from clipmap +0x2A8. It is not a sequential
slice of the vertex pool. Check topology, range accounting and bounds while
preserving original triangles. Their ownership/material lookup still needs
separate evidence; do not thicken surfaces into guessed brush solids.

## Model-attached collision

Each measured 96-byte instance contains model pointer +0, flags +8, position
+12, a 3x3 basis at +24 and world bounds at +60.

The stored basis maps world-relative coordinates into local coordinates.
Its lengths are inverse scales. The decoder retains
`world_to_local_linear` and emits a column-vector `matrix_world` using
the inverse linear transform. Apply that transform once; do not use the stored
basis as a forward matrix. Transform each surface box before combining bounds.

Model +0x50 and count +0x140 identify 56-byte surface records: triangle pointer
+0, count +16, bounds +20, bone index +44, contents +48 and packed flags +52.
Each pointer must be captured independently; separate surfaces need not be
contiguous allocations.

Triangles are reconstructed from three float4 equations:

```text
n.xyz dot p = n.w
s.xyz dot p = s.w + u
t.xyz dot p = t.w + v
```

Solve at barycentrics (0,0), (1,0) and (0,1), then select winding against the
captured normal. Validate singularity, finite values and equation residuals.
These coordinates are recovered from stored float32 equations; they are not
claimed bit-identical to original authored vertices.

Bone references, mismatching bounds and zero-surface models remain diagnostics.
Do not substitute a render mesh or resize geometry to match culling bounds.

## Model physics and unknown primitives

The model +0x60 path leads to brush/primitive geometry. The measured list header
is 24 bytes with count, contents and a pointer to 16-byte entries. Entries hold
separate brush and primitive pointers.

Mode 3 creates a self-contained physics capture with its own headers,
instance transforms and geometry bytes. The decoder validates every count,
pointer and instance relationship before building supported brush hulls.

Primitive type 3 remains unresolved. A cylinder interpretation has geometric
support, but another game's enum is only a lead. Trace BO4's type dispatch
before claiming a shape and preserve unknown primitive bytes until then.
Unsupported primitive instances stay out of the published brush geometry.

## Useful next contributions

- Validate supported layouts after reloads and on other BO4 maps/builds.
- Trace triangle ownership, surface lookup and bone-dependent collision.
- Confirm trigger associations through runtime dispatch.
- Identify primitive types from BO4 consumers.
- Generalize terrain packaging without losing independent weight fields.
- Test assembled brush outputs in Radiant and gameplay.

Keep source accounting and rejected records in every report. Describe what a
check proves: file hashes, equation residuals, matching bounds, compilation
and gameplay are different evidence. Start with the
[contribution walkthrough](contributing.md), and add small synthetic fixtures
instead of personal captures.
