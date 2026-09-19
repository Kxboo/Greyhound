# Black Ops 4 workflows and measured layouts

[Documentation index](README.md) | [Contribution walkthrough](contributing.md)

This reference consolidates measured findings and their limitations.
Capture counts and local output paths below identify development samples,
not bundled fixtures or guarantees for every game build. Historical
validation is distinct from tests run on your current checkout.


## BO4 static model placements

Load a BO4 map, then use Greyhound's **Model placements** action or run:

```powershell
.\Greyhound.exe placements
```

The output is independent of terrain, world brushes and model collision:
`exported_files/black_ops_4/placements/run_XX/static_models.json`.
The document is a plain array with the same placement fields as Cold War:
`Name`, `SourceName`, `Position`, `RotationDegrees`, `RotationQuaternion`,
`ModelScale`, `BoundsMin`, and `BoundsMax`. Positions remain in BO4 world units.
`Name` uses the shared model-export filename cleaner; `SourceName` retains the
live asset identifier. Unresolved names use `xmodel_<hash>` and set
`NameResolved: false`. This command does not export mesh or image assets.

`placement_report.json` records completeness and unresolved names. `diagnostics/`
retains the small source tables and referenced model headers for offline checks.
Runtime visibility, proxy replacement, deformation and dynamic/script-spawned
models are not decoded by this static gfxworld export.

### BO4 evidence

The gfxworld pool is 14, with a 6,832-byte header. The static count at `+0x1BC`
is 32,227 in the measured zm_white capture. `+0x400` references 56-byte model
records; each record's `+0x00` points to a pool-4 XModel and `+0x18` selects a
64-byte transform in the array at gfxworld `+0x408`. This is a permutation,
not a matching array order. Every transform has a reverse reference at `+0x38`
whose low 31 bits reproduce its referring model-record index.

| Transform offset | Data |
| --- | --- |
| `0x00` | Quaternion XYZW, four float32 values |
| `0x10` | World position XYZ |
| `0x1C` | Uniform render scale |
| `0x20` | World bounds minimum XYZ |
| `0x2C` | World bounds maximum XYZ |
| `0x38` | Reverse reference index plus a high-bit flag |

The arrays and each referenced model header are double-read. References must
resolve within the model pool; transform references must be aligned, bijective,
and agree with reverse indices. Quaternions, scale and bounds are validated
before publishing the user-facing JSON.

21,016 render instances independently match BO4 collision instances by model
identity and world position. All their normalized rotations agree within
0.0000042 per matrix component. Multiple collision entries at the same origin
are considered rather than choosing an arbitrary nearest neighbor. 209 matched
instances have different collision/render scale; the render scale is preserved.
Collision data is only a validation reference, never a replacement placement.

Euler angles use XYZ components of a ZYX rotation, matching the CW JSON
convention. A singularity branch preserves heading at +/-90-degree pitch.
The original quaternion is always retained. The read-only audit compares every
serialized field against the capture and reconstructs a matrix from the Euler
angles to check it against the quaternion:

```powershell
python tools/black_ops_4/placements/audit_bo4_placements.py <placement-run> --collision <collision-source>
```

The external BO4 reference supplied the initial 56-byte reference-record shape.
The transform mapping and field meanings above were measured on BO4 data;
Cold War supplies the output contract, not evidence of BO4 offsets.

### Delivered capture

The latest audited capture is `placements/run_03`: 32,227 placements referencing
2,779 models using the echo000 database. Serialized raw fields match the capture
exactly; reconstructed Euler matrices agree with the original quaternions within
1.22e-7. 182 distinct model names remain unresolved (1,073 instances).

The preceding GUI failures left empty diagnostics directories, so their original
cause could not be recovered. The diagnostic build now writes
`diagnostics/placement_error.json` with the stage, read sizes and changed offsets
when validation fails. It preserves all existing validation checks. A fresh CLI
export passed; the failing GUI session became unresponsive, so this is not yet a
verified fix for that GUI failure.


## BO4 / Cold War name database selector

In **Settings > General**, choose **BO4 / CW name database**:

- **Bundled Greyhound database** (the existing default).
- **echo000 / cod-name-db** (the separately imported local CSV checkout).

Click **Load Game** after changing the choice. The BO4 name cache is cleared
before loading the selected database, so switching does not merge the two.
Cold War uses the same selected five FNV1a asset dictionaries, also replacing
its cache on every Load Game. The legacy setting key `bo4namedatabase` and import
directory `echo000_bo4` are retained so existing installations work for both.
Already-written exports are unchanged. Other games retain their existing name
database behavior. If the alternate database is missing, selecting it reports
that explicitly; it does not silently use the bundled names.

The headless placement and terrain commands accept a per-run override:

```powershell
.\Greyhound.exe placements --name-db echo000
.\Greyhound.exe placements --name-db bundled
```

BO4 and CW placement reports record the database actually loaded. CLI overrides do not
change the saved GUI preference.

### Import or refresh the local copy

The source project is https://github.com/echo000/cod-name-db. Its CSV sources
can be converted into Greyhound WNI files without installing its CDB runtime:

```powershell
C:\SuperTerrain\.venv\Scripts\python.exe tools/shared/name_db/import_echo_bo4.py `
    C:\Users\kuboo\Downloads\cod-name-db-main `
    src/WraithXCOD/x64/Release/package_index/echo000_bo4
```

The importer accepts the extra nested directory produced by extracting the ZIP.
It imports the five non-v2 FNV1a asset files used by BO4 and CW: animations, images,
materials, models and sounds. It verifies names against BO4's 60-bit FNV1a hash,
rejects malformed or mismatching rows, and excludes ambiguous hash entries.
It writes compressed WNI files plus `source.json` with source/output checksums
and rejection counts. The original checkout and bundled WNI files are untouched.

Installed binaries use the database beside their own executable. Import to that
executable's `package_index/echo000_bo4` when using a different runtime folder.
Saluki's `.cdb` container is not parsed directly: the user's uncompressed CSV
checkout is converted to WNI. The five installed source/output checksums were
verified against `C:\Users\kuboo\Downloads\cod-name-db-main` on 2026-09-13.
The running Cold War map loaded 942,836 names with the echo000 choice.

### Measured zm_white comparison

The same previously captured 2,779 distinct render models were checked against
both sources. Bundled resolved 2,248; the imported local echo000 checkout resolved
2,597: **349 additional names, zero previously resolved names lost**, leaving 182
unresolved names. This is specific to this map and these database versions.
The change affects identity labels; position, rotation and scale are unchanged.

Both selections were also loaded successfully against the running BO4 map using
`superterrain --list --name-db ...`, without generating another terrain capture.

### Cold War live comparison (2026-09-13)

On the same 38,243 rigid `zm_silver` placements, bundled hashes resolved 34,440
rows / 1,559 unique models. The imported echo000 files resolved 37,843 rows /
1,631 unique models: 3,403 additional resolved placement rows and 72 additional
model names, with no previously resolved names lost. This is a map/version
measurement, not a global coverage claim.


## Black Ops 4 terrain capture modes

Black Ops 4 is the only game besides Cold War with a `TerrainGfx` pool
(`ASSET_TYPE_TERRAINGFX` 152, pool index `0x98`), and its TerrainGfx structure
has not been reversed. Exporting a BO4 terrain asset therefore runs a
**measurement capture**, not the Cold War reconstruction capture: `CoDAssets::ExportTerrainAsset`
hands BO4 to `GameBlackOps4::ExportTerrainProbe` rather than replaying Cold War
header offsets against a header whose layout is unknown.

The same Export button also reaches six other BO4 world captures. Those
previously existed only as values of the `GREYHOUND_BO4_WORLD_PROBE` environment
variable, which had to be set before launch and appeared nowhere in the
interface, so the button silently did different things depending on the
environment it was started in.

### Choosing a capture

In **Settings > Terrain**, choose **Black Ops 4 capture run by Export**. The
selection is remembered, the hint below the list describes the files the chosen
capture writes, and the status line states plainly when terrain assets are not
being captured. Cold War terrain export is unaffected by this setting.

The same catalogue is available under **Settings > Dev Tools > Black Ops 4:
diagnostic captures**. With BO4 loaded, its Run button starts modes 1–7 directly,
without selecting a TerrainGfx asset. Mode 5 uses the regular brush export
workflow. Mode 0 still requires selecting and exporting a terrain asset; the
Terrain settings button provides access to its options. Both pages share the
stored selection and honor the environment override below.

| Mode | Selection | Writes |
| --- | --- | --- |
| 0 | Terrain source probe (default) | `header.terraingfx.bin`, `terraingfx_probe.json`, referenced regions, resident height / cutout / layer weight mips, shader scan |
| 1 | Map world pools | `world_pools_probe.json` and the per-pool / per-slot payload dumps |
| 2 | Model collision references | `model_collision_probe.json`, `collision_surface_headers.bin`, `model_collision_triangles.bin` |
| 3 | Model collision (physics only) | `model_physics_probe.json`, `model_physics.bin` |
| 4 | Model placements | `model_placement_capture.json`, `static_models.json`, `placement_report.json` |
| 5 | Radiant brush prefabs | the full BO4 brush / clip / model-physics prefab export, in its own export folder |
| 6 | Collision handler tables | `collision_handlers.json` and the located handler byte ranges |
| 7 | Named surface-flag declarations only | `surface_flags_probe.json`, with no map-pool capture |

Headless runs take the same choice per run:

```powershell
.\Greyhound-cli.exe assets export --type terrain --all --bo4-capture-mode 3
```

`GREYHOUND_BO4_WORLD_PROBE` still overrides both, so existing scripts keep
working unedited. When it is set, the list shows the mode it forces, is
disabled, and the status line says where the choice came from.

### What Black Ops 4 terrain export does not do

The probe measures; it does not reconstruct. Only Cold War reaches the organize
and seal finalization — `FinishTerrainExport` calls
`GameBlackOpsCW::ExportTerrainDecals`, which walks Cold War pool offsets and
would read unrelated memory in a BO4 process. A BO4 terrain run is consequently
not sealed and carries no SHA-256 inventory.

`tools/black_ops_4/capture/package_bo4_terrain.py` can assemble a probe into a
`superterrain-bo4-source-package-v1` package without discarding overlapping
layer weights, but it is calibrated against `zm_white` by its own description
and is not invoked by Greyhound. Its layer weight file names are fixed to that
map's two hashes, so another asset must be decoded explicitly before the
packager can be used on it.


## BO4 Radiant brush export

In Settings → **Radiant Brushes**, load a BO4 map and click **Export brushes now**.
The same button retains its Cold War path when CW is loaded. The automatic
collision-pool checkbox remains CW-only; BO4 uses the explicit button.

Output: `exported_files/black_ops_4/brushes/run_NN/`. User-facing maps live in
`prefabs/`, with exactly three category folders: `brushes`, `clips`, and
`model clips`. Metadata and capture diagnostics stay outside `prefabs/`.
Each `.map` uses world coordinates, inserted at origin with identity rotation
and scale:

- World brush geometry.
- World clips together in one prefab, with selected tools/materials on layers.
- Inline-model brush/clip geometry.
- Model-attached physics brushes.
- Trigger and volume hulls, in separate **REVIEW** prefabs.

This follows Cold War's category grouping (`split_cw_brush_roles.py` and the
separate trigger/volume writer), not a separate prefab per material. BO4 keeps
source world and inline entities separate in subfolders. `brushes` contains
ordinary, non-colliding and traversal brushes plus optional review volumes and
triggers; `clips` contains world/inline clip prefabs; `model clips` keeps
model-attached collision separate for later. Assigned clip-family materials
remain in the clip category even when their source classification differs.

No terrain, render-model export, GDT, or gameplay-script conversion is involved.
The bundled Python converter reads only Greyhound's saved captures.

### BO4 evidence

The world decoder validates brush vertex/side ranges, exact array accounting,
BSP/leaf ownership, clipmodel/gfxmodel bounds, and leaf contents unions. The
64-byte source brush contains six axial filter indices; its additional plane
records contain further indices. A BO4 module-global table of 8-byte
`surface,contents` pairs was located using observed brush contents, then checked
against **every brush**, not just the search pattern.

The capture also reads BO4's own named material-flag declarations from the
executable. These supply player/AI/missile/bullet/vehicle/item/sight clipping,
slick, caulk, traversal and other names. Their bit values are not taken from CW.
BO3 choices compare these names against the bundled stock material catalogue.
Added and omitted properties remain in `metadata/material_assignments.json`;
named-property similarity is not a claim about identical compiled behavior.
Unknown source bit 1 remains explicit. Surface-type codes now resolve through
BO4's captured enum declarations; any code absent from those declarations stays
in `unresolved_surface_type_codes`.

BO3 native `contents weaponClip ai_nosight;` flags can retain weapon and sight
collision without selecting a broader material. The local BO3 compiler's
keyword table and application code are recorded in `bo3_brush_contents.json`:
weaponClip adds bullet/missile bits and clears default solid; ai_nosight adds
sight clipping. These numeric bits were checked against BO4's own declarations,
and the brush syntax occurs in shipped BO3 maps.

**One source brush produces one output brush.** If no exact single stock tool
plus native flags exists, the selector minimizes omitted collision categories
first, then added categories, then slick/nonSolid differences, then surface
type and other surface properties. It never
duplicates a hull to combine tools. Writers reject multiple components; resume
checks compare the complete type decision, including native flags.

The updated saved zm_white test matches all named collision categories on
7,612 of 7,672 source clip brushes. The remaining 60 use a closest tool with
added categories and no omitted categories. All deviations remain in each row's
`type_assignment`; these counts do not establish compiled gameplay equivalence.
The comparison output is `test-output/bo4-typed-prefabs-v2/`. Model physics is
also split by use (clips, ordinary brushes, non-colliding hulls, traversal),
while remaining separate from world/inline geometry. Plane readback and
one-to-one source-instance accounting are recorded in `verification.json`.
The replaced combination test was removed.

The enlarged declaration capture reads 83 named BO4 records, including the
surface enum table. Adjacent 24-byte tables have padding between them, so the
probe searches pointer-aligned records rather than imposing one 24-byte phase.
All nonzero surface-type codes in the current 15,499-brush world capture resolve.
Glass variants share a contents bit: the surface enum now selects the name,
rather than falsely labeling ordinary glass as both car and bulletproof glass.
Surface-specific stock clip tools now participate in selection, including
wood, metal, concrete and the other captured surface types. For equal collision
and movement/solidity behavior, the source surface wins. Of 4,580 source clip
brushes with named surfaces, 1,154 retain that surface with this single-tool
policy. Generic fallbacks are recorded; changing a surface must not justify
losing or broadening a better collision match. Mixed face types use the most
frequent named source type (alphabetical tie-break); counts and the selected
type remain in the metadata. No layered/overlapping brush is generated.
Ordinary glass selects the stock `glass_clip` tool; its added clip categories
are reported. A source nonSolid hull with no clip categories selects `skip`
instead of gaining a solid grey placeholder.

*Named surface-flag declarations only* in **Settings > Terrain**
(`--bo4-capture-mode 7`, or the `GREYHOUND_BO4_WORLD_PROBE=7` override) saves only stable declaration
windows and their names (`surface_flags_probe.json`), avoiding repeated map,
texture and mesh captures. Offline comparisons can use this supplemental
snapshot; conflicting declarations are rejected and snapshot hashes are saved.

The current zm_white capture validates contents unions for all **15,499 world
brush records** and **2,088 unique model-physics brush records**. One world
record has only three vertices and cannot make a closed brush. The resulting
world/inline output contains 15,365 placed brushes; unused inline-model library
shapes are preserved in diagnostics, not placed at an invented origin.

Model physics applies each captured model transform once, with scale and plane
normal transformation checked. Its output contains 9,170 placed brushes. Bounds
disagreements are flagged; geometry is not clamped to make them disappear.

### Remaining work and limits

- 437 model-primitive instances have an unidentified type/layout. Raw bytes and
  identities are saved; the exporter does not substitute guessed boxes.
- BO4 trigger models/hulls/slabs use independently checked 8/32/20-byte records.
  There are 228 geometric trigger entities and 228 models, accounting for 231
  hulls. Their sequential association is supported by ordering/counts but is
  **not yet independently confirmed from runtime dispatch**. The generated
  trigger/volume prefabs therefore explicitly say `ASSOCIATION_REVIEW`.
- Three parameter-only trigger boxes stay in entity JSON. No box geometry is
  invented while their dimension/origin convention remains unverified.
- Authored properties and runtime record transforms are retained separately.
  Disagreeing inline-model placements stay on review layers.
- Trigger/volume files are inspection brush geometry, not ported BO4 scripts or
  claims of working BO3 trigger gameplay.
- Plane serialization and prefab counts are verified. Radiant opening,
  compilation, and BO3 gameplay have not been tested for this export.

`metadata/export_report.json` uses `exported_with_review`, with
`all_placed_brushes_present: false`, so successful file generation cannot hide
the remaining omissions. The GUI reports that distinction.

### Developer verification

*Radiant brush prefabs* in **Settings > Terrain** (`--bo4-capture-mode 5`, or
the `GREYHOUND_BO4_WORLD_PROBE=5` override) with the existing `superterrain --all`
headless entry point calls the same BO4 export function as the GUI button. This is a
developer capture route, not a second collision decoder. It saves world and
model physics under the brush run's diagnostics, and verifies map identity
before conversion. Build with `build-greyhound.ps1 -BuildOnly`; package changed
converter sources using `tools/shared/runtime/package_runtime.py`.

The saved run's prefab SHA-256 values, source identities, rejections and type
differences are the inspection record. A failed conversion preserves diagnostics
and does not claim an export completed.
