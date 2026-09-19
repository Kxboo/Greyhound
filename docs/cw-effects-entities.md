# Cold War effects, animation and entities

[Documentation index](README.md) | [Contribution walkthrough](contributing.md)

This reference consolidates measured findings and their limitations.
Capture counts and local output paths below identify development samples,
not bundled fixtures or guarantees for every game build. Historical
validation is distinct from tests run on your current checkout.


## FX and animation placement data

Latest organized capture: `exported_files/black_ops_cw/placements/zm_silver_capture_10`
on `zm_silver`, from `run_10` plus verified native light decoding from `run_11`.
Start with its `README.md` and `derived_catalog.json`. The native source run
still uses the filenames below and `fx_anm_catalog.json`. Greyhound writes these
additional files when **Include non-static placements and entity classes (CW)**
is selected, or with `Greyhound.exe placements --name-db echo000 --non-static`.

| File | Contents |
| --- | --- |
| `fx_placements.json` | 2,482 FX placement records: source IDs, candidate position/angles, asset pointer/hash, attached names and raw data. |
| `fx_assets.json` | 139 referenced FX assets with raw and masked name hashes, name-resolution status and 144-byte source headers. |
| `fx_entity_references.json` | 21 authored entities carrying FX-related keys/names, including every original property and the source transform. |
| `animation_model_placements.json` | 196 model placements selected by `fxanim`/`fxanm` names or attached animation properties; 161 static and 35 entity-model rows. Retains original model-batch fields. |
| `animation_entity_references.json` | 40 entities carrying animation-related properties, source transforms and complete original properties. |
| `named_animation_references.json` | 328 verbatim property references, with entity ID, property name, candidate lookup hash and loaded-animation match result. |
| `animation_assets.json` | 221 named animation assets: 48 referenced by entity properties plus 173 selected only by an `fxanim`/`fxanm` name hint. Includes frame rate, frequency, frame count, bone count and raw headers. |

### Names carried by FX placements

606 FX placements reference 646 attached name records, containing 52 distinct
strings. Examples include `lgt_env_powered_on_room_04` and
`lgt_env_powered_off_room_04`. They are attached reference names; they have not
been identified as the effect asset's pathname. Their event/state semantics
remain unverified.

The measured 80-byte placement has candidate position at +8, pitch/yaw/roll at
+20, attached-record count at +56 and attached-record pointer at +72. Attached
records are 32 bytes, with a string pointer at +0. `RawFieldsU32` preserves all
six following 32-bit fields by offset. Their meanings and units are not guessed.
The native reader bounds counts to 64, bounds string reads to the readable
region/1024 bytes, retains raw bytes, and rereads captured records and strings.

All 139 effect asset names remain unresolved in the selected asset dictionary
and bundled string index; the supplied `fnv1a_strings.csv` also had no matches.
`EffectName` is null in that case. Use `EffectHashMasked` for a 60-bit name
lookup and `EffectHash` to retain the original flags/hash value. Join placement
`EffectPointer` to the same field in `fx_assets.json` within this capture.

### Names carried by animation-related entities

Examples of actual property names are `previewanim1`, `animscript`,
`zbarrierboardAnim1..6`, `zbarriertearAnim1..6`, and `script_bundle`.
One preserved bundle is `p9_fxanim_zm_ndu_explosive_door_bundle`.

314 of the 328 named references match a loaded XAnim hash. Follow
`SourceEntityId` back to the entity and `AnimationHash` to `animation_assets.json`.
The other 14 references are retained without inventing an animation asset match.
Names such as an `animscript` value can identify a script rather than an XAnim.
The 173 animation assets selected only by their names do **not** gain placement
links just because their names resemble a model name.

Model rows retain their exact original transforms. `SourcePlacementFile` and
`SourcePlacementIndex` identify the original row. `AttachedEntityProperties`
retains all properties where an authored entity exists; `SelectionEvidence`
explains why each row was included. A name/property hint does not prove that
the animation is currently playing.

The existing Greyhound XAnim layout provides name hash +0x70, frame rate +0xB0,
frequency +0xB4, total bone count +0xFE, notification count +0x100, and frame
count +0x104 in a 288-byte record. The focused capture uses the counted loaded
pool and preserves the source bytes for these values.

Two pointers previously exported as unresolved `AnimationReference` candidates
in `dynmodel_assets.json` actually align with physics pool 2, stride 112. New
exports label them `PhysicsReference`; they must not be used as animation links.

### Validation

The Release build, native selection tests and live focused audit passed.
`fx_anm_validation.json` records counts. Re-run the offline audit with:

```powershell
python tools/cold_war/capture/verify_cw_fx_anm.py <placement-run-directory>
```

The audit checks raw placement/asset bytes, attached strings and integer fields,
unchanged source reads, exact source-row transforms, all entity properties,
animation metadata and entity-to-animation hash joins.

### Authored scene object placement, capture 10

The scriptbundle reader now accepts both literal bundle names and preserved
hexadecimal bundle-hash properties. It captured 53/53 referenced loaded bundles.
Forty scene bundles match all 9,387 fields in the pinned CW dump at commit
`edd94bdfa2b37693cdb77c1493855ad14ddc435a`. Twelve intel bundles and one item
spawn-list bundle remain raw; their placement semantics are not claimed.

| Organized file | Contents |
| --- | --- |
| `animation/object_placements.json` | 99 scene objects, keyed by source entity, bundle and object index; model/type/name references and shots. |
| `animation/scene_objects/<bundle>.json` | The same objects partitioned into 40 separate bundle files. |
| `animation/scene_placements.json` | 231 object/shot references with source entity, alignment target, position, pitch/yaw/roll, BO3 origin/angles references and animation links. |
| `animation/scene_bundle_data.json` | Enriched captured fields, reference evidence and original bundle structure. |
| `animation/scriptbundles_decoded/` | Original capture and 1,233 byte-evidence reads; referenced through `EvidenceBaseDirectory`. |
| `metadata/scene_placement_validation.json` | Independent capture, entity-link and zero-offset alignment audit. |

The CW scene consumer resolves named alignment targets by entity `targetname`,
then by authored structs. Fourteen unique `script_struct` markers resolve 154
shot references; the other 77 use their authored scene root. The 231 references
belong to 99 objects anchored by 54 source entities. These are **authored animation
alignment transforms**, before animation root/bone motion, rather than observed
runtime object poses. Source entity scale is retained; inheritance by scene
children is not assumed. A player-type scene object is not asserted to spawn a
particular static model simply because its alignment is known.

The pinned `scene_shared.csc` consumer identifies world-space position addition
and pitch/yaw/roll addition, with whole-vector nonzero shot/object/scene offset
precedence. All these offsets are zero in this capture. Tags, ambiguous targets,
invalid transforms and preserved runtime angles remain explicit unresolved
statuses when encountered. Appearance and further playback decoding are outside
the requested placement scope.

After the native capture, run from the repository root:

```powershell
python tools/cold_war/capture/capture_cw_scriptbundles.py <raw-run> <raw-run>/animation/scriptbundles_decoded
python tools/cold_war/capture/organize_cw_placements.py <raw-run> <new-organized-folder>
python tools/cold_war/capture/enrich_cw_scene_bundle.py <organized>/animation/scriptbundles_decoded/bundles.json <bocw-source> <organized>/animation/scene_bundle_data.json
python tools/cold_war/capture/resolve_cw_scene_placements.py <organized>
## This last audit intentionally targets zm_silver's measured counts/zero offsets.
python tools/cold_war/capture/verify_cw_silver_scenes.py <organized>
```

The live game must remain on the same map during native and bundle capture.
Organization, enrichment and audits are offline. Scene organization/enrichment
is currently this Python workflow; the GUI does not automatically run it.


## Cold War ENTITYLIST JSON

`tools/cold_war/capture/decode_cw_entitylist.py` independently reads the saved pool 0x8E
capture bytes and checks them against the native candidate decoder. It emits
conversion input without discarding the original property records. It does not
convert game scripts or supply missing BO3 assets.

The September 15, 2026 `zm_silver` result is at:

`C:\SuperTerrain\research\cw-clip\stock-first-review-20260915\entitylist`

| File | Use |
| --- | --- |
| `entities.json` | Compact conversion input; the existing `Entities` array of string dictionaries, with precise record transforms. |
| `entities.decoded.json` | All ordered typed properties, raw bytes, original named transforms, precise transforms, source hashes, target matches and BO3 class checks. |
| `summary.json` | Counts by class and property type, unresolved references and conversion limits. |
| `unresolved-assets.json` | Current capture's unresolved asset references, indexed by entity and property. |
| `verification.json` | Independent saved-JSON float round-trip checks and file hashes. |

The first three files are generated by the reusable decoder; the last two are
additional checks produced for this Silver review.

### Results and precision

The capture contains 2,380 entities and 36,787 properties: 30,508 strings,
4,773 float3 values, 1,036 asset hashes, 250 floats, and 220 integers. All counted
entries are preserved. This capture has no unknown property tags, duplicate
keys or omitted keyvalues. A second capture read was unchanged; it was not an
atomic snapshot of the whole game.

The native flat exporter uses seven significant digits. The new decoder uses
nine significant digits for float32 strings and exact finite float32 values in
typed JSON numbers. This changes 44 property strings in this capture.

More significantly, all 2,380 named `origin` and `angles` properties contain
integer-valued components. The entity record float3 values at offsets +24 and
+36 retain fractional precision. For all 2,380 records, each component agrees
with the corresponding named property within 0.5. In 2,131 entities at least
one component differs. For example, entity 1 has named origin `1257 -264 33`
and record origin `1256.739990234375 -263.7449951171875 33`.

The conversion JSON uses record transforms when they agree with named
properties within 0.50001. The detailed document preserves both and records
this selection. This interpretation is supported by the measured relationship;
the engine consumer of these record fields has not been traced by this tool.
There is no axis conversion, snapping or angle normalization.

Independent verification reloaded the published JSON and reproduced the exact
float32 bytes of all 14,280 record-transform components and 14,569 property
float components. All 36,787 raw property records were checked. Four synthetic
tests cover precision, hashes larger than JavaScript's safe integer range,
signedness, duplicate/unknown properties, truncation and mismatched metadata.

### Detailed document conventions

* `entities[i].index` retains the original array index.
* `properties` contains typed original values, including original named transforms.
* `keyvalues` contains string representations of those original properties.
* `origin`, `angles`, `transform` and `conversion_keyvalues` use the documented
  transform selection. The compact JSON uses `conversion_keyvalues`.
* `property_list` preserves original order, type tags, tag high bits, all 32 raw
  bytes per property, string bytes, and any unknown tail. It is authoritative
  if a future capture contains duplicate keys; convenience dictionaries omit
  duplicates instead of silently keeping the last one.
* Hash values are hex strings, so all 64 bits survive JSON consumers. A resolved
  display name from Greyhound remains a name-cache candidate. The raw hash is
  always retained in the detailed document.
* Integer32 entries retain both signed and unsigned interpretations. String
  keyvalues preserve Greyhound's unsigned convention; no boolean or signed
  meaning is invented for a property.
* All 48 entity-record bytes are retained, including unnamed IDs, references
  and the word at offset +4. Those words are not decoded into invented semantics.

### BO3 conversion limits

There are 313 unresolved asset references representing 139 distinct hashes:
160 `script_sound`, 88 `model`, and 65 `scriptbundlename` references. These remain
hexadecimal. Name resolution is separate from having a usable BO3 asset.

Class names for 2,019 entities occur in the installed `bin/t7.def.json`; 361
entities use names absent from that file. Matching class names do not establish
matching spawnflags, keys, scripts or assets. No class or script was silently
replaced. The detailed JSON records the checked BO3 definition file and SHA-256.

There are 445 literal `target` references, of which 31 have no matching
`targetname` in this ENTITYLIST. They are retained: some may refer to dynamic
or externally defined entities. These are lookup results, not a decoded script
dependency graph.

The list includes 32 `node_negotiation_mantle`, 122 `node_negotiation_volume`,
seven negotiation begin and seven end nodes. Trigger hulls live in the separate
TRIGGERLIST capture; collision brushes live in clip_map. ENTITYLIST alone does
not contain all brush geometry or every entity spawned by scripts at runtime.

### Reproduce

Run with Python 3.10 or newer; no third-party modules are required:

```powershell
C:\SuperTerrain\.venv\Scripts\python.exe tools\cold_war\capture\decode_cw_entitylist.py `
  --capture C:\SuperTerrain\repos\Greyhound\src\WraithXCOD\x64\Release\exported_files\black_ops_cw\xrawfiles\cw_pool_08E_7971765 `
  --output C:\SuperTerrain\research\cw-clip\stock-first-review-20260915\entitylist `
  --bo3-def 'C:\Program Files (x86)\Steam\steamapps\common\Call of Duty Black Ops III\bin\t7.def.json' `
  --map-name zm_silver
```

This is currently a saved-capture developer tool. The Greyhound native
ENTITYLIST export still writes its original `entities.json`; use the separately
decoded conversion file above for these precision improvements. The native
export button has not been rewired to this decoder.


## zm_silver placement and BO3 mapping reference

Start with `reference-index.json`. It indexes all 2,380 captured ENTITYLIST entities with precise source transforms, original properties, source record IDs, BO3 class checks and links to generated navigation placements. `data/entities.json` is the compact conversion input; `data/entities.decoded.json` retains typed properties and raw bytes. Animation setup is left to the user. Every animation field in the two placement prefabs is empty; stock motion candidates remain in JSON only as optional reference.

### Prefabs

Import these at **origin 0 0 0, rotation 0 0 0, scale 1** to retain the map's coordinate system. The files are separate parts of the same map.

| File in `prefabs/` | Contents |
|---|---|
| `zm_silver_brush_collision.map` | 11,904 collision/clip output pieces; individual assigned materials are retained |
| `zm_silver_other_brushes.map` | 155 other brush pieces from clip_map |
| `zm_silver_volumes.map` | Volume entities and their captured hulls |
| `zm_silver_triggers.map` | Trigger entities and their captured hulls/parameters |
| `zm_silver_navigation_tools.map` | 122 `traverse` brushes and 32 mantle brushes (5 `mantle_on`, 27 `mantle_over`) |
| `zm_silver_traversal_placements.map` | 7 original begin/end pairs, 14 nodes at precise source entity coordinates |
| `zm_silver_volume_connection_placements.map` | 84 directional connections, 168 derived begin/end nodes from the 61 volume pairs |

The 154 navigation tool brushes use compiled centers, half dimensions and yaw. All 1,706 captured edge samples fit those bounds within 0.001 unit. Source pitch/roll remain in JSON; the compiled volume frame is yaw-only. Mantle-on versus mantle-over is a conversion approximation based on paired heights.

Volume connection nodes are **derived authoring placements**: sampled edge midpoint plus 16 units vertically, following installed BO3 examples. Both raw edge centers and the explicit lift are recorded in `data/volume-connection-mapping.json`. They are not claimed to be original CW point entities. The report retains all 122 source directions, including 38 with no permitted actor in the shared vocabulary. Six CW-only actor types have no automatic BO3 mapping. Restrictions do not disappear from the reference when a direction is not emitted.

### Find the original data for an output

* Entity: `reference-index.json` → `entities` → `source_entity_index`, `source_record_id`, `source_properties`, `transform`, `outputs`. A same-name BO3 class check is only a class-name check; unsupported properties are not silently declared compatible.
* Collision brush: `data/collision_metadata.json` → `rows` → `prefab_file` and `prefab_brush_index`. Each row records source asset/brush, instance, transform, world bounds and `material_assignment_key`.
* Material: use that key in `data/material_assignments.json` → `brushes`. It gives raw contents, named flags, source surface/traversal fields, chosen BO3 material, installed GDT source/line, added/omitted properties and unresolved fields.
* Traversal: `data/navigation-graph.json` → `nodes` / `volume_pairs`. All 286 compiled nodes retain their source ENTITYLIST index, raw record, compiled position, source properties, links, masks and available edge points. Compiled positions can differ from authored positions for ordinary pathnodes; both remain available.
* Mantle/tool brush: `data/navigation-tools-report.json` → `records`, linked by `source_entity_index`.
* Explicit endpoints: `data/explicit-node-mapping.json` → `pairs`, including original source animations and omitted properties.
* Trigger/volume: `data/triggers.json` → `entities`, including source IDs, hulls, emitted properties and omissions. **Its `source_entity_index` belongs to the TRIGGER pool, not ENTITYLIST. Do not join these numeric indices directly.**

### Coverage and remaining decode work

This package accounts for every entity in the saved ENTITYLIST capture and every supported exported brush. It is not a full decode of every Cold War collision layout. There are 7,865 unique supported brushes, represented by 12,059 placed/partitioned pieces. The source report also lists 1,241 collision assets outside the supported brush layout and 26 layouts without brushes. Material filter association remains unresolved for 1,781 unique brushes. Their current fallback material and status are explicit in the reports.

`data/unresolved-assets.json` preserves 313 unresolved hash references (139 unique). Unknowns remain unknown. `data/stock-first-audit.json` records stock BO3 choices and unresolved source/engine evidence; no new custom APE materials were needed for the mapped profiles. `data/bo3_reference.json` includes installed material definitions and stock traversal references.

The combined geometry check with BO3 `cod2map64.exe` produced output, but logged a map leak and 39 node-to-navmesh projection errors. It is not a clean game-ready compile. Animation and gameplay setup are outside this reference delivery. The isolated authoring fixture compiled without errors; that only checks the basic property/format contract.

The separate `review-prefabs`, `entitylist`, and `game-map-current` folders alongside this package retain the original reports and raw capture evidence. Source paths and SHA-256 hashes are in `source-manifest.json`; package file hashes are in `manifest.json`.

Regenerate with `tools/cold_war/capture/build_cw_placement_reference.py --research <research-root> --reference tools/black_ops_3/reference/bo3_reference.json --output <package-folder>`. The traversal exporters also accept `--placement-only`. These saved-capture commands do not require GUI control. This reference builder is a separate tool; it is not yet automatically invoked by Greyhound's export button.
