# Black Ops 4 terrain intake research

[Documentation index](README.md) | [Contribution walkthrough](contributing.md)

This reference consolidates measured findings and their limitations.
Capture counts and local output paths below identify development samples,
not bundled fixtures or guarantees for every game build. Historical
validation is distinct from tests run on your current checkout.


## BO4 offline intake: verified progress, 2026-09-12

The Greyhound producer exports source evidence. Native BO4 intake is implemented
in the separate TerrainReconstructor project; see that project's
`docs/BO4_NATIVE_INTAKE_2026_09_12.md` when available. The source package described
here does not itself create a GDT or install assets into BO3.

### Source package

`tools/black_ops_4/capture/package_bo4_terrain.py` packages the measured zm_white v45 capture.
Current output: `test-output/bo4-zm-white-source-package`.

- 2 sectors, 17 ordered sector-local bindings, 12 material identities.
- 55 source PNGs, including 4 engine defaults; GDT's flat importer sees 51 images.
- Full BC4 layer arrays, R16 heights, cutout bits, tile masks, UV matrices and
  uninterpreted material constants. Copied files are SHA-256 checked.
- A material's full recovered name is preserved. A TXT basename alias is needed
  because the GDT flat importer keys declarations by filename basename.
- `materials/superterrain_materials.json` is an intake recipe, not a GDT.
- Height/reveal is deliberately not relabelled roughness. The old v45 export
  record is retained as evidence alongside corrected consumer semantics.
- Unknown semantic bindings remain explicitly unknown. No tint/roughness/blend
  constants are inferred from their position in an untraced shader buffer.

Run `tools/black_ops_4/capture/verify_bo4_gdt_intake.cjs <GDT project> <materials directory>`
to exercise the existing GDT source parser and material builder in memory.
All 12 definitions / 24 declared opaque and blend variants passed, including
color/normal identity and zero missing referenced images. This does not prove
the separately built desktop executable has identical code or BO3 compilation.
The GDT project's generic test incorrectly infers variant from `_blend` at the
end of the name; BO4 has an original material with that suffix, so the dedicated
checker uses the recipe's declared field instead. No consumer fix was made.

**Initial blocker (native dispatch now added):** the CW `ompv.load_export` path requires a discrete
index plane. Its coverage path derives weights from that plane, not from BO4's
independent overlapping BC4 fields. The native package intentionally has no
fabricated index. A successful material import is not full reconstruction intake.
Runtime blend arithmetic is not established by a nonzero-support bitmask test.

### Greyhound world-pool probe

`BO4WorldPoolProbe.h`, invoked by the existing terrain producer when
**Settings > Terrain** selects *Map world pools* (or the process environment
contains `GREYHOUND_BO4_WORLD_PROBE=1`, which still overrides it), captures only
bounded pool evidence. See [bo4.md](bo4.md). Normal terrain capture behavior is unchanged. The opt-in path skips
the large terrain/image/shader scan, while retaining the ordinary terrain run
and process identification machinery.

Captured through Greyhound with BO4 PID 28596. Result relocated from the run
directory to `test-output/bo4-world-probe` so the two full terrain captures remain
the only entries in the map's terrain directory. Probe plus audit is about 334 KB.
Greyhound capture process PID 29232 exited before relocation.

The free-list traversal and loaded counts agree for all six pools:

| Pool | Reference name | Header bytes | Loaded |
| --- | --- | ---: | ---: |
| 11 | clipmap / col_map | 728 | 1 |
| 12 | comworld | 96 | 1 |
| 13 | gameworld | 96 | 1 |
| 14 | gfxworld | 6832 | 1 |
| 147 | streamerworld | 256 | 1 |
| 118 | entity_list | 32 | 1 |

The 24-target bound was reached for clipmap and gfxworld. This is a one-hop
sample, not a complete pointer graph. Full pool header bytes are retained.

`tools/black_ops_4/brushes/audit_bo4_world_probe.py` checks the capture against
BO4-specific structures from atian-cod-tools. Gfxworld's basename pointer reads
`zm_white`; header fields interpreted by that reference give 1,146 surfaces,
214 brush models, 32,227 static-model entries, and 1,948 volume decals. These are
counts, not extracted models. The entity-list header declares 3,418 records;
85 complete 48-byte records fit in the initial sample. The first audit tried
the external origin/angles offsets 20/32; finite numbers alone did not validate
them. The full runtime capture corrected these offsets to 24/36, below.
Their property arrays/strings were not followed yet.

References:

- https://github.com/ate47/t8-atian-menu/blob/master/docs/notes/xassetpools.csv
- https://github.com/ate47/t8-atian-menu/blob/master/docs/notes/xasset_origins.csv
- https://github.com/ate47/atian-cod-tools/blob/main/src/core/acts/tools/fastfile/handlers/bo4/bo4_unlinker_map.hpp
- https://github.com/ate47/atian-cod-tools/blob/main/src/core/acts/tools/fastfile/handlers/bo4/bo4_unlinker_map_gfx.cpp
- https://github.com/ate47/atian-cod-tools/blob/main/src/core/acts/tools/fastfile/handlers/bo4/bo4_unlinker_map_entitylist.cpp

The map header explicitly marks clipmap and terraingfx as unfinished. External
field names guide validation; they do not substitute for BO4 measurements. The
old pinned pool.hpp URL in TerrainReconstructor's catalog returns 404; current
main and the menu's independent pool notes were read instead.

### Full brush arrays and ownership: world probe v3

The v3 capture is in `test-output/bo4-world-probe-v3/_source`; v2 is retained
for comparison. Cleanup of the 334 KB v1 batch was rejected by automatic tool
policy, so v1 still remains pending deletion. The two ordinary terrain captures
remain unchanged. These captures used Greyhound only against BO4
PID 28596, with two equal reads required for each selected full array.

`decode_bo4_collision.py` validates the following BO4 measurements:

- clipmap +0x2B0 count / +0x2B8 pointer: 15,499 brush records, stride 64.
- Brush +0x00 side pointer (stride 20), +0x08 vertex pointer (float3),
  +0x10 minimum xyz, +0x1C raw contents, +0x20 maximum xyz,
  +0x2C six raw u16 axial-material candidates,
  +0x38 u16 vertex count, +0x3A u16 side count.
- All brush ranges exactly partition 126,155 vertices and 29,496 sides.
  Side normal lengths agree with one to within 2e-7. Source bounds are kept:
  maximum vertex-bound discrepancy is 1.351318; maximum side-plane residual
  is 0.106174. These are diagnostics, not silently corrected coordinates.
- clipmap +0x278 points to stride-32 leafbrush nodes, not brush records.
  Positive i32 at +4 denotes leaf reference count with pointer at +16.
  Counts 0/-1 denote branches with positive node-relative children at +24/+28;
  -1 also visits the node immediately following the branch.
- clipmap +0x68 holds 233 stride-56 collision leaves; their root index is +40.
  Each leaf's six bounds at +12 equal its referenced brush union expanded by
  0.125 per side, maximum error 3.82e-6. All 233 raw contents fields equal
  the bitwise OR of their referenced brush contents.
- The 19 stride-24 BSP nodes at +0x58 have two signed-i16 children at +16.
  Root 0 reaches leaves 0..19 using negative child = -(leaf+1).
  Those leaves own exactly 15,279 world brushes.
- The 214 stride-88 clip models join the 214 stride-80 gfx models by index:
  clip bounds are gfx local bounds expanded by one, max error 1.91e-6.
  Inline models 1..213 reference roots at clipmodel +72. Their brush sets
  match collision leaf sets and gfx-local union bounds within 0.001353.
  They own 220 brushes, disjoint from world brushes. Together these two
  ownership sets cover all 15,499 brushes.

The header's +0x280 value 17,223 equals the **sum of leaf references**.
It must not be interpreted as the length of a unique physical index allocation:
some leaves share pointer ranges. Valid roots reference only the first 17,100
u32 elements at +0x288. Node 11,714 is unreachable from the validated roots
and references the next, invalid brush index 15,499. The bounded candidate
capture includes a tail overlapping the next allocation; that tail is retained
as raw evidence and explicitly excluded from decoding. No sentinel meaning is
assumed for the unreachable node.

#### Reconstructed source hulls

`build_bo4_brush_hulls.py` passes the BO4-owned vertex ranges into Greyhound's
existing exact-predicate `cw_brush_hull.checked_hull` backend. Its mathematical
hull operations are reused; no CW binary layout or contents meanings are used.
`brush_hulls.json` contains **15,498 closed hulls**: 15,278 world and 220 inline
local. Original point coordinates are unchanged; maximum containment error is
5.69e-14. One world record, brush 12,930, has three points and cannot define a
volume. It remains explicitly rejected with its original source range.

This is source hull geometry, not an installed Radiant map or proof that all
map collision has been recovered. The 40,060 triangle vertices / 58,117 indexed
triangles, static-model collision, and BO4 contents interpretation are separate.

#### Runtime entity correction

All 3,418 entity records were captured at stride 48. Their runtime layout is
model index +16, unknown integer +20, origin +24, angles +36. There are 81
entities with inline model indices, all with zero captured angles. Using these
origins, 62 gfx-world bounds agree, 7 differ, and 12 are unavailable (zero).
Runtime motion is a possible explanation for some differences, not established.
Authored positions and differences remain explicit; no automatic adjustment.
The old sample audit now uses the corrected offsets and labels their basis.

Next work: entity properties and model/decal identities; BO4 contents mapping
and Radiant brush serialization; remaining collision sources; lossless native
BC4-weight intake under the no-consumer-edit constraint.


### Greyhound Radiant brush inspection and original collision surfaces

`export_bo4_radiant_brushes.py` reuses Greyhound's exact support-plane and
canonical BO3 face writer, with BO4-owned hulls as its input. It writes no
terrain and no GDT. Output: `test-output/bo4-zm-white-brush-inspection`.

- 15,365 placed grey brush hulls: 15,278 world, 68 from inline entities whose
  gfx bounds agree, and 19 from authored inline placements marked REVIEW.
- Those 87 inline hulls belong to 81 entities. Other inline model assets remain
  unplaced in source data; they are not dumped together at world origin.
- Maximum 47 support planes per brush; no hull requires face-limit splitting.
- Maximum serialized plane/source vertex error 1.37e-12. Final file was reopened
  and its brush/plane totals checked. Radiant opening and compilation are not
  claimed. Grey placeholder surfaces do not reproduce BO4 clip behavior.

`decode_bo4_triangle_collision.py` separately resolves the stride-36 surface
records at clipmap +0x98. Fields: bounds6f at 0, triangle start u32 at +24,
vertex-reference start u32 at +28, triangle count u8 at +32, vertex-reference
count u8 at +33, raw material index u16 at +34. The referenced vertex-index
array is clipmap +0x2A8, not a sequential slice of the float3 vertex pool.

All 9,869 surface ranges exactly partition 58,117 triangles and 73,154 vertex
references into 40,060 unique vertices. Every surface's triangle vertex set
matches its vertex-reference list, and all 9,869 bounds match exactly. No
zero-area triangles. Original topology is preserved in the capture; these
surfaces have not been thickened into invented brush solids. Their ownership
and material lookup remain to be traced.

Model-attached collision is a separate branch, not covered by the 220 inline
brushes: the 22,594 stride-96 collision instances reference 2,130 unique model
pointers. Of those instances, 21,174 share their pointer with a captured gfx
static-model entry (2,123 distinct pointers). Their complete 3x3 transform must
be preserved, including scale. A dedicated model-header probe follows this
branch through Greyhound; no renderer model is substituted for its collider.


### Model-attached collision capture and decoding

`BO4ModelCollisionProbe.h` is the Greyhound-only focused mode selected by
*Model collision references* in **Settings > Terrain**, `--bo4-capture-mode 2`,
or the `GREYHOUND_BO4_WORLD_PROBE=2` override. Normal terrain capture remains unchanged. Two
model-probe runs are retained at `test-output/bo4-model-probe-v1` and `-v2`;
no new full terrain/texture capture was made. The model probe validates the
clipmap active slot and every referenced XModel pointer against BO4 pool 4.
It captures every referenced model header and counted surface/triangle arrays
with duplicate-read agreement. Sixteen models also retain bounded unknown
pointer samples. Source model names resolve only when their hash matches.

The 22,594 instances reference 2,130 valid model headers, with 1,715 recovered
names and zero unresolved model pointers. Each 96-byte instance retains its
model pointer at 0, raw flags at +8, position at +12, 3x3 basis at +24 and
captured world bounds at +60. The stored basis maps world-relative coordinates into local coordinates. Its
lengths are inverse scales (about 1/6 through 10); actual forward scales are
about 0.1 through 6. Maximum normalized similarity-transform residual is
2.20e-6. Position alone is not an adequate placement representation.

BO4's model +0x50 pointer and +0x140 count lead to 56-byte collision surface
records. Their layout is triangle pointer +0, count +16, bounds six floats +20,
bone index +44, contents +48 and packed flags +52. Across sampled multi-surface
models, triangle pointer distances agree exactly with count*48 bytes. V2 reads
each pointer independently; it does not assume contiguous allocations.

2,102 models have these surfaces; 28 have zero count. All 3,573 surface arrays
and 278,908 triangles were captured completely. `decode_bo4_model_collision.py`
reconstructs each triangle from three float4 equations:

- n dot p = d
- s.xyz dot p = s.w + u
- t.xyz dot p = t.w + v

Solve at barycentrics (0,0), (1,0), (0,1), then choose winding to agree with the
captured plane normal. All matrices are nonsingular, all values finite, and
maximum equation residual is 7.28e-12. This recovers coordinates from stored
float32 equations; it is not a claim of bit-exact original authored vertices.
Normals have maximum length error 1.44e-7. Comparing reconstructed bounds with
the surface's 0.001-expanded bounds gives median error 2.83e-6, 99th percentile
0.000463, maximum 0.015176. These discrepancies are retained per surface, without
clamping, snapping or substitution of a convex hull for concave geometry.

Outputs under `bo4-model-probe-v2/_source`:

- original model headers, surface headers and equation records;
- `decoded_model_collision_triangles.f64`, float64 [triangle][vertex][xyz];
- `model_collision_data.json`, with model names/hashes, surfaces, source hashes,
  all 22,594 instance links/transforms, bone references and diagnostics.

After correcting the inverse basis and transforming surface bounds before
union, the unposed collision-bounds check agrees within 0.01 for 19,901
instances. 2,558 need further bounds/collision-path investigation; 135 reference
a model with zero collision surface count. There are 105 surfaces with a nonzero bone index. These facts
support following the skeleton/other collision branch next, but do not explain
all mismatches yet. No automatic transform correction is applied and these
model-attached triangles have not been added to the verified brush map.

User separation is maintained: Greyhound reconstructs brushes/clips and exports
terrain source data. TerrainReconstructor owns terrain reconstruction. Neither
TerrainReconstructor nor the GDT creator was edited in these goal turns.


### Corrected model transform and model-attached physics brushes

The original model-collision-data-v1 reader applied the stored basis forwards.
That was wrong for scaled instances. Example: instance 7,
`p7_pipe_metal_hp_4_straight_64_grey_dk`, has stored basis length 2 but actual
forward scale 0.50000005. Forward application made its bounds 96 units too long;
inverting the basis gives an error of 0.0000181.

Current `model_collision_data.json` uses schema v2. It retains
`world_to_local_linear` and writes an explicit column-vector `matrix_world`
whose linear part is its inverse. It no longer exposes the misleading forward
`basis_rows`/`uniform_scale_candidate` fields. Each surface box is transformed
before combining bounds, avoiding invented corners between separate surfaces.
The resulting 19,901 bound matches are measured across the source instances,
not derived solely from matrix inversion identities.

890 of the remaining instances differ by a uniform one-unit world bound
expansion. That does not justify expanding their collision geometry; culling
bounds can be conservative. No automatic shape adjustment was applied.

#### The +0x60 path is actual brush/primitive geometry

`decode_bo4_physgeom_samples.py` reads the two existing bounded +0x60 samples;
no new live capture was needed for this finding. A first pointer in the root
leads to a 24-byte geometry-list header: u32 count, u32 contents, pointer at +8.
That pointer addresses 16-byte entries with separate brush/primitive pointers.
The remaining root/list fields are retained raw and unresolved.

For `p7_zm_isl_medical_stool`, six entries point to the same 64-byte BO4 brush
layout decoded in world collision. All six bounds exactly match their original
vertices; Greyhound's exact hull backend builds six closed hulls. The raw point
counts are 48,24,24,24,24,24 (duplicates preserved in the source arrays).
Their instance 7304 retains its model link and corrected matrix; all brush
vertices are contained by its captured instance bounds. The list/brush contents
are 0x20430600; instance flags are 0x20430601. This single correspondence does
not establish a global contents conversion.

For `p7_fir_ball_sports_soccer`, three entries point to 64-byte primitive records
with type 3. Their bytes and float fields are preserved in `physgeom_samples.json`;
no sphere/capsule/box meaning is assigned to that number yet.

The producer extension captures +0x60 geometry lists and referenced
brush/primitive records across all linked models, retaining pointer/count
bounds and explicit incomplete statuses. Mode 3 creates a separate,
self-contained model physics export with its own model references and instance
transforms. It does not merge with the terrain capture or triangle export.
Greyhound owns brush/clip reconstruction; TerrainReconstructor owns terrain
reconstruction and remains unchanged. Current world-probe v1 cleanup remains
tool-policy blocked; no additional copies of full terrain captures are warranted.

#### Separate model physics capture and reconstruction

Mode 3 built successfully and captured the live zm_white session through
Greyhound. Its completed run was moved to
`test-output/bo4-model-physics-v1/_source`; it contains 6,294,856 source bytes.
The two normal terrain runs remain unchanged. This is a self-contained export
with its own model headers, instance table and physics binary, not a merge with
the terrain or model triangle exports.

`decode_bo4_model_physics.py` validates every referenced pointer/count against
the captured bytes and reconstructs each brush independently. Among 2,130
referenced models, 297 carry this physics path: 268 have brushes, 31 have
primitives, and two have both. There are 2,088 brush records and 108 primitive
records. All requested geometry spans were readable. All 2,088 brush hulls
are closed; maximum vertex containment error is 5.69e-14. Stored brush bounds
differ from their vertices by at most 0.001953125 units; captured side-plane
residuals reach 0.0091964 units. These diagnostics are preserved, not corrected.
All 108 primitive records have raw type 3; its geometric meaning remains open.

The capture's own instance table supplies 5,036 placements for models with this
physics path, accounting for 9,170 placed brush entries. Its inverse basis is
inverted once; matrix inverse residual is at most 3.33e-16. Of 4,732 instances
with decoded brushes, 3,505 contain those brushes within their captured bounds
at a 0.01-unit threshold; 1,227 are flagged for review (1,068 of these extend
less than one unit outside). Containment cannot prove the runtime use of this
physics path. Disagreement cannot justify clamping, inflating or repositioning
captured geometry. The remaining 304 placements have primitives only.

`export_bo4_model_physics_map.py` writes a separate grey inspection artifact:
`test-output/bo4-zm-white-model-physics-inspection/zm_white_model_physics_inspection.map`.
It contains 9,170 brushes: 6,943 on contained layers and 2,227 on bounds-review
layers. The maximum is 58 faces per brush. Per-brush serialization and final
file readback pass, with maximum plane/vertex residual 1.36425e-12 units.
437 placed primitive entries are explicitly omitted pending identification.
The sidecar retains model identity, instance index, source entry, raw contents,
flags and omissions. No terrain, world-brush or model-triangle data is merged;
no GDT is generated. This file has not been opened in Radiant or compiled and
does not claim a verified BO3 gameplay contents/material conversion.

#### Primitive type 3 investigation

`analyze_bo4_physics_primitives.py` records, but does not promote, a cylinder
interpretation. All 108 records have positive dimensions, exactly equal two
radial fields and a right-handed near-orthonormal matrix (maximum orthogonality
error 1.72011e-6). T6's OpenAssetTools enum labels type 3 as cylinder and uses
orientation/offset/half-length fields; that is only a reference lead for BO4.
Independent BO4 triangle bounds support the reading: a plate's candidate
cylinder spans Z=0..1 (triangle mesh about 0..0.9406), whereas a capsule reading
would span -4.948..5.948. Can, ketchup-bottle and screwdriver dimensions also
fit the cylinder reading substantially better. BO4's type dispatch remains
untraced. No primitive was silently added to the inspection map.

#### Native terrain intake now runs through TerrainReconstructor

After explicit user approval to edit its intake, the existing BO3 geometry and
material command routes now accept the native BO4 package directly. The
separate GDT creator remains unchanged. The full zm_white run is in
`test-output/bo4-native-tool-geometry` and `test-output/bo4-native-tool-materials`:
271 prefabs, 28,710 base controls, 3,314 material patches and 206,662 total
material controls. All 12 material definitions / 24 recipe variants pass the
existing GDT source parser. Raw independent BC4 fields remain unnormalized;
no index image is fabricated.

This is validated intake with a coarse fitting budget, not final fidelity.
Readback proves control UVs/alpha/height match their source samples. Between
controls, sampled weight error reaches 1.0 (RMS 0.2260); 96 center samples
contain a layer absent at the surrounding controls. Sector height RMS is
26.661/12.042 units. Weight-aware/finer fitting remains open. See the consumer's
`docs/BO4_NATIVE_INTAKE_2026_09_12.md` and the output readback report.
