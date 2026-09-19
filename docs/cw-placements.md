# Cold War placement reference

[Documentation index](README.md) | [Contribution walkthrough](contributing.md)

Load a Cold War map and use **Map & Model Export**, or run from the checkout:

```powershell
$gh = '.\bin\cli\Greyhound-cli.exe'
& $gh placements --name-db bundled --non-static --verify --organize
```

Use the output path reported by your executable. This guide describes the
placement contract and measured layouts; validate offsets against the active
game build before extending a reader.


## Current organized layout

Use `placements --non-static --verify --organize` for one categorized CW run.
The layout and recovery procedure are in [Start here](README.md#placement-folders-and-duplication).
The historical flat names below remain source aliases in `catalog.json`:
`static_models.json` becomes `models/static.json`, `non_static_models.json`
becomes `models/non_static.json`, and reports move under `metadata/`.
Raw `diagnostics/` bytes are retained. Separate instances are never deduplicated.


## Cold War streamed model placements

`Export Model Placements` uses the shared DISTRICTS reader in
`CWMapWorldCapture.h`. It writes the existing plain `static_models.json` array
and a separate `placement_report.json`. `Models from JSON` can consume that
array using the existing naming and LOD settings.

The optional **Include non-static placements and entity classes (CW)** setting
adds separate entity, FX, light, reflection-probe, sun-volume and source-evidence
JSONs. See [effects and entities](cw-effects-entities.md).
`static_models.json` retains the rigid district scope described below.

Normal exports now contain **rigid static placements only**. Rows marked
`RequiresSplineDeformation`, or carrying a valid `SplineInstanceIndex`, are
excluded until spline controls/deformation are supported. The complete capture
remains in `diagnostics/static_models.json`; `placement_report.json` records
captured, published and deferred counts. The completion dialog reports the
published count rather than the unfiltered capture count.

CW `Models from JSON` applies the same rule to older input JSONs, including
resumed batches. If a model also has a rigid placement, that rigid use and its
model export remain eligible. Deferred rows are preserved before replacing a
resumed batch's placement file. Manual model-asset export and BO4 behavior are
unchanged.

The reader follows the loaded map's counted district table and each populated
placement descriptor. It first tries stable live placement arrays. If the
header, arrays, identities or readback cannot be validated, it looks up the
descriptor's package key in Greyhound's local game package cache. This does not
depend on a map name, a particular district number, fixed process addresses,
known model names, an offline reconstruction script or a user-supplied key list.

### Layout and validation

The 0x88-byte district record points to a 56-byte placement stream descriptor at
+0x68. Descriptor +8 is the package key, +0x20 the live allocation, and the low
u32 at +0x30 its decoded allocation size. Lookup is local-only and decompression
uses a bounded XSUB command plan; the resulting size must match the descriptor.

For supported packaged placement data, +0x108 and +0x10c contain the global
start and count. Four pointer slots at +0x110..+0x128 are unrelocated zeros.
64-byte references start at +0x130, followed by count 64-byte transforms.
The full allocation is `304 + 240*count + (count%2 ? 8 : 0)` bytes. The leading
u32 excludes the first 256 bytes and must not be used as the allocation length.
Unknown layouts are reported as unresolved rather than forced into this layout.

Reference +0x10 is a model hash on disk and a model pointer in live memory.
Packaged hashes use the existing 60-bit XModel hash/name database. Transform
+0x38, masked with 0x7fffffff, indexes the reference table. The runtime can reorder
transforms, so physical row number is not a cross-source join key.

Every accepted district requires a complete reference-index permutation,
nonempty model identities, finite transforms and bounds, unit quaternions,
positive scale, and ordered bounds. Model hashes without a resolved name remain
valid hashed model names. District descriptors and the table are reread to check
source stability. Sorted placement ranges must tile from zero without overlaps
or gaps before reporting a complete export. Limits produce an explicit partial
export, not silent omission. Package reads share the scene package budget.

### Provenance and limits

- `PlacementSource`: `live` or `local_package`.
- `District` + `ReferenceIndex`: join key within this map capture.
- `RecordSlot`: runtime array slot for live rows; null for packaged rows.
- `PackageRecordSlot`: source slot for packaged rows.
- `BoundsMin` / `BoundsMax`: captured world bounds, retained without fitting.
- `ReferenceFlagsRaw`: source flags; packaged and runtime values may differ.
- `SplineInstanceIndex` / `RequiresSplineDeformation`: retained in diagnostic
  capture evidence; dependent rows are excluded from normal static placement
  publication because spline controls and deformation are not supplied.

The report includes recovered and unresolved district counts, per-district live
failure reasons, package path/key/offset, validation results and range coverage.
Expected failed live reads do not fail the export when that entire district has
been validated from its package. Evidence write failures still fail research
exports. Package recovery does not assert a successful live readback.

Source proxy placements remain in the output. Their runtime visibility and
replacement rules are not decoded. Recovering district XModels does not establish
that every kind of rendered world geometry has been recovered.

### Validate changes

The native tests include district payload sizes, pointer relocation, reference
permutations, finite transforms, bounds, range coverage and rigid/spline filtering.
Start with [cw_district_payload_test.cpp](../tests/cw_district_payload_test.cpp)
and the [native runner](../tests/run-native-tests.ps1). Saved map comparisons
must join by district/reference identity rather than physical array order.

## Cold War placement catalog and BO3 references

For the focused FX/animation placement and name export, see
[cw-effects-entities.md](cw-effects-entities.md).

In **Settings > Map & Model Export**, select **Include non-static placements and
entity classes (CW)**, then **Export Model Placements JSON**. The choice is
saved as `cwnonstaticplacements`. The command-line equivalent is:

```powershell
$gh = '.\bin\cli\Greyhound-cli.exe'
& $gh placements --name-db bundled --non-static
# Explicitly omit the additional captures:
& $gh placements --name-db bundled --static-only
```

Every invocation reserves a new run directory. Start with `placement_catalog.json`
for a flat run, or `catalog.json` and `metadata/placement_catalog.json` after organization.
The optional captures do not depend on enabling the older Dev Tools checkboxes.
They read the game and local packages; they do not change game memory.

### Files

These are native flat filenames. In an organized run, use the aliases in
`catalog.json` to locate each file; for example, `light_placements.json` becomes
`lights/decoded_placements.json` and probe bounds become `probes/bounds.json`.

| File | Meaning and use |
| --- | --- |
| `static_models.json` | Existing rigid district placements. Input to Models from JSON. |
| `non_static_models.json` | Authored entities with a model identity and validated transform. Input to Models from JSON. |
| `non_static_models/class_*.json` | Same model rows grouped by original entity class. Also valid model-batch input. |
| `entities/entitylist/class_*.json` | Every captured map entity, grouped by classname, including entities without models. |
| `entities/triggers/class_*.json` | Trigger entities grouped by classname. |
| `spline_models.json` | The spline-dependent district rows omitted from rigid export. Requires deformation controls, not a rigid placement. |
| `fx_placement_candidates.json` | Counted level-FX records, asset hashes/pointers, candidate origin/angles, raw bytes. Not model-batch input. |
| `light_placement_candidates.json` | Primary light records, candidate origin/direction/radius/linear RGB, raw type and bytes. |
| `light_placements.json` | Validated compiled-light GUID, position, orientation basis, pitch/yaw/roll and BO3 origin/angles references. |
| `reflection_probes.json` | Compiled probe records with GUID, descriptor membership, origin, axes, outer extents and raw bytes. Invalid/unresolved records have null Position. |
| `reflection_probes/volume_*_descriptor_*.json` | The same probe records separated by sun volume and observed descriptor. |
| `reflection_probe_bounds.json` | Influence volumes with explicit parent probe IDs, inner sizes, blend margins, oriented box corners, world AABBs and local/world clipping planes. |
| `reflection_probe_bounds/volume_*_descriptor_*.json` | The same bounds separated by sun volume and descriptor. |
| `sun_volumes.json` | Sun-volume source headers and candidate global-probe origins. |
| `dynmodel_assets.json` | Dynamic-model definitions, pool-checked model/physics reference candidates, and raw fields. Not instance transforms. |
| `trigger_geometry_candidates.json` | Trigger model/hull/slab evidence and indices. Origin alone is insufficient for a trigger brush. |
| `bo3_mapping.json` | Coordinate conventions, documented BO3 keys, explicit unresolved conversions and local reference bibliography. |
| `non_static_report.json` | Per-source counts, capture coverage, source stability, rejected model rows and saved-file status. |
| `placement_report.json` | Static and optional-export summary. |
| `diagnostics/non_static/` | Pool descriptors, original headers/arrays/properties, and readback/evidence reports. |

Entity filenames encode unsafe characters and have a `class_` prefix. Every
individual entity retains its `EntityId`, original record index/address, complete
typed `properties` (including unknown types and raw value hex), and convenient
decoded `Properties`. `SourceEntityId` and `SourceEntityFile` on a model row join
directly to its source entity. Different entities using the same model remain
distinct. Per-class files are arrays, not one file per individual instance.

### BO3 transform and asset mapping

World coordinates retain CoD world units (inches), Z up, with no axis swap,
recentring or unit conversion. Source entity angles are **pitch, yaw, roll**.
Placement `RotationDegrees` is **X=roll, Y=pitch, Z=yaw**. Quaternions are xyzw
and encode `Rz(yaw) * Ry(pitch) * Rx(roll)`.

CW entity properties contain rounded origin/angles. Record offsets +24 and +36
retain precision. They are accepted only when finite and within 0.501 units or
degrees of the named properties (angles compared modulo 360). These precise
values populate `Position`, `SourceAngles`, and the BO3 model `origin`/`angles`.
Uniform scale comes from `modelscale` or an explicitly recorded default of one.
Invalid transforms, duplicate keys, inline brush model names and unsupported
scales retain their entity evidence but do not become importable model rows.

The `BO3` object provides reference values for `origin`, `angles`, `modelscale`
and the model name. The name still needs a corresponding imported BO3 XModel/GDT
asset. `script_model`, `script_origin` and `script_struct` preserve those class
names, with script behavior explicitly unported. Other classes retain their CW
name and have no invented BO3 classname. Spawn markers are not asserted to be
visible models. No animation playback, current skeletal pose, runtime spawning,
entity attachment or game-script behavior is reconstructed.

#### FX and fxanim

An XModel containing `fxanim` or `fxanm` in its name may occur in either a static
district or a script entity. There is no name-based filter excluding it from the
static file. The previous exporter did not traverse the entity list at all.
The new non-static JSON includes model-bearing entities, including such names.
The separate level-FX array describes effect instances, not XModels or XAnims.
Effect-internal particle/light emitters and animation curves are not decoded.

The measured FX list uses pool 0x7F, a 40-byte header, count +8, array pointer
+16, and 80-byte records. Record +0 is checked against the 144-byte FX asset pool
0x33; +8 and +20 hold candidate position and angles. Raw bytes preserve all
other flags/references. Its BO3 reference values remain explicitly **candidate**.

#### Lights

Lighting pool 0xAA has a 472-byte header. Primary lights use count +8, pointer
+16 and measured 688-byte records. GUID is +0x48 and position is +0x68.
The vectors at +0x74, +0x80 and +0x8C are **Up, Back and Right**, respectively.
The old `CandidateDirection` at +0x74 is retained in the legacy evidence file;
it must not be interpreted as forward. Local XYZ axes expressed in world
coordinates are `[-Back, -Right, Up]`. `light_placements.json` validates finite
position, orthonormal axes and positive determinant before emitting position
and pitch/yaw/roll. Invalid placements have null transforms.

Placement checks compare authored light GUIDs/origins and signed orientation
bases with the compiled records, then round-trip the derived rotations. See
[verify_cw_light_placements.py](../tools/cold_war/capture/verify_cw_light_placements.py)
for the saved-data audit and its required inputs.

Linear RGB +0xC8, repeated RGB +0x284, radius +0x200 and raw type byte +0x40
remain candidate/appearance fields outside the placement work.

BO3 uses `classname=light`, `_color`, `stops`, `PRIMARY_TYPE` values such as
`PRIMARY_OMNI`/`PRIMARY_SPOT`, `radius`, `fov_outer`, `falloffdistance`, and `def`.
CW numeric light type and linear RGB do **not** receive a guessed conversion
to BO3's type or intensity stops. Their BO3 fields remain null. The new decoded
file supplies validated BO3 `origin` and `angles` placement reference values.

BO3 animated/flickering lights use an **.efx Dynamic Light** visual. The official
FX guide states that color, intensity, radius and FOV curves, movement rotation
and generation offsets live in the effect asset; instance overrides are limited
to entity parameters such as origin, angles and lighting state. A list of effect
locations cannot reproduce those light curves.

#### Reflection probes and global probes

The lighting header's +0x38/+0x40 pair locates measured 0x26A0-byte sun-volume
headers. Three observed probe descriptors are at +0x2340, +0x2398 and +0x23F0.
Each has count +0 and array pointer +16. **Descriptor slot is not asserted to
equal BO3 lighting state.** Arrays may share storage. All memberships survive
export; do not deduplicate by model name or GUID alone.

The measured probe stride is 376 bytes: origin +0x5C, three basis vectors +0x68,
outer negative extents +0x8C, outer positive extents +0x98 and GUID +0x148.
GUID membership is checked against the lighting header's +0x60/+0x68 table;
finite transforms and orthonormal axes are required before publishing Position.
GUID zero records need global-probe interpretation, not an invented local-probe
classname. Unresolved/inactive records remain with raw bytes and null Position.

BO3 distinguishes capture origin, influence bounds and blend margins. For the
authored heli-cabin probe found in the current map, the compiled origin and GUID
match its entity record, and compiled outer extents equal `size_min/max` plus
`blend_mins/maxs`. Do not copy these outer extents into BO3 `size_min/max` and
then add blending again. When available, the authored probe's `BO3ProbeKeys`
preserves the separate documented fields. The influence-volume decoder now
recovers this split for other compiled probes too. Reflection/parallax planes
and grid density remain undecoded.
Rebuild BO3 cubemaps and GI after importing the supported authoring data.

#### Reflection-probe influence bounds

Each 88-byte descriptor additionally stores a bounds pointer at +24 and a
32-bit bounds count at +84. Every 376-byte probe stores the first bound index
as a uint16 at +0x58 and its count at +0x5A. These ranges are validated for
overflow, overlap and complete coverage before publishing `SourceProbeId`.
This is an explicit source relationship, not a nearest-position match.

The influence-volume stride is **604 bytes (0x25C)**:

| Offset | Decoded field |
| --- | --- |
| +0x00 | Volume origin; independent of the parent cubemap capture origin. |
| +0x0C | Three local basis vectors expressed in world coordinates. |
| +0x30 / +0x3C | Inner negative / positive extents, corresponding to BO3 `size_min` / `size_max`. |
| +0x48 / +0x54 | Negative / positive blend margins, corresponding to `blend_mins` / `blend_maxs`. |
| +0x60 | Clipping-plane count; zero denotes a box. |
| +0x64 | Up to 30 local float4 clipping planes. All record bytes survive export. |
| +0x244 | Stored outer-box center, checked against origin, axes and asymmetric extents. |
| +0x250 / +0x254 | Unmapped uint32 fields, retained. |
| +0x258 | Include/subtract role byte. Current map contains only zero/include. |

`world = origin + sum(local[i] * axis[i])`. The exported inner/outer corners
and AABBs use this transform. Axes are checked for orthonormality and positive
determinant. Derived pitch/yaw/roll is round-trip checked by the offline audit,
including the helicopter's rotated descriptor. For multiface volumes, these
boxes are enclosing bounds; the clipping planes define the shape, not the box.

Plane convention is `dot(normal, point) + D <= 0`. World-space normals and D
are also exported. These are **influence clipping planes**, not the six
reflection/parallax planes documented for cubemap correction. BO3 supports
multiface probes using `facePlaneN` and `faceBlendN`, but a lossless conversion
of CW's compiled plane/blend representation to those authoring fields has not
been established. No unverified face keys are emitted.

Read the joined data as follows:

1. Select a sun volume and `ProbeDescriptorSlot`; these are not asserted to be
   BO3's numbered lighting states.
2. Read the parent in `reflection_probes.json`. Its `Position` is the cubemap
   capture origin; GUID and `SourceId` retain identity.
3. Follow `InfluenceVolumeIds` to `reflection_probe_bounds.json`. Each bounds
   record points back with `SourceProbeId`; never join solely by array position.
4. For a single box whose origin and axes match its parent, the parent `BO3`
   object contains the direct size/blend/angle reference keys. Otherwise keep
   the individual volume transforms and parent/child relationship. Independent
   volumes must not become independent cubemap captures.

The live CW consumers substantiate the strides and ownership at module-relative
RVA 0x8B6B174 (probe +0x58/+0x5A, descriptor +0x18, stride 0x25C) and
0xBE9696C (box extents, plane count, plane sign and subtract branch). The latter
negates plane D using the measured -1.0 constant at RVA 0xD669FD8 and halves
summed box sizes using 0.5 at RVA 0xD6694D0. These RVAs are evidence for this
measured build, not signatures or promises about other versions. The
[probe-bounds evidence](cw-probe-bounds-evidence.json) records the findings;
the original capture and disassembly are not bundled fixtures.

Global probe placement is associated with sun volumes. The BO3 workflow allows
a sun volume to target an `info_null` to move its probe; it must not automatically
be collapsed to the influence box center.

### BO3 authoring references

Use `docs_modtools/` inside your own Black Ops III installation. Relevant
shipped documents include:

- `Lighting_Parameters.pdf`, pages 1–3 and 8–11: light types, intensity stops,
  shaping, cookie parameters, states and shadows.
- `FX_Lights.pdf`, pages 1–2: dynamic light asset setup, animation and instance limits.
- `Lighting_Probe_Workflow.pdf`, pages 1–3: global probes, sun volumes and target origins.
- `Probe/Reflection_Probes.pdf`, pages 1–6: independent origin, size/blend bounds,
  reflection planes and GI grids.
- `Probe/Probe_Editing_Handles.pdf`: independent capture-center and box edits.
- `Probe/Multiface_Probes.pdf`: convex planes, up to 24 authoring faces, child
  volumes and per-face blending.
- `Probe/Subtract_Probes.pdf`: subtract applies to child probes and cancels
  overlapping parent influence.
- Shipped `map_source/_prefabs/zm/zm_giant/zm_giant_light.map`, entity 16:
  confirms the actual keys `_color`, `stops`, `PRIMARY_TYPE`, `radius`,
  `lightingstate1..4`, `def`, and others in a BO3 .map.

These references establish BO3 authoring semantics. They do not prove CW
memory offsets. The latter are separately measured and retain raw evidence.

### Review coverage and limits

Counted arrays must pass unchanged readback, but that is not an atomic scene
snapshot. Unsupported pool shapes, invalid occupancy and map mismatches must
remain explicit failures. A `complete` report covers the requested capture
and writes, not all runtime entities or a finished BO3 conversion.

Use [verify_cw_placement_catalog.py](../tools/cold_war/capture/verify_cw_placement_catalog.py)
and the focused FX/light auditors to compare decoded fields with source bytes.
Check each tool's help and input schema before running it against an organized
run. The native `--verify` route performs its audit before organization.

[Probe-bound tests](../tests/cw_probe_bounds_test.cpp) cover rotated boxes,
world plane conversion, gimbal-lock angles, invalid sizes/axes/counts and
ownership gaps/overlaps. Add synthetic coverage for new layouts and report
live-map tests separately.

Useful next work includes spline controls, dynamic-model instance relationships,
light appearance conversion, probe face/blend mapping and validation on other
maps/builds. Preserve original bytes and unresolved values while investigating.
