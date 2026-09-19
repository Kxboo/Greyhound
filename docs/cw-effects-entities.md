# Cold War effects, animation and entities

[Documentation index](README.md) | [Contributing](contributing.md)

This guide covers optional placement evidence and saved ENTITYLIST decoding.
It does not port effect assets, animation playback or gameplay scripts to BO3.

## Capture FX and animation references

Load a Cold War map and enable **Include non-static placements and entity
classes (CW)** under **Map & Model Export**, or run:

```powershell
$gh = '.\bin\cli\Greyhound-cli.exe'
& $gh placements --name-db bundled --non-static --verify --organize
```

Read the run's `catalog.json` and `metadata/fx_anm_catalog.json`. The catalog
maps the original flat filenames to their organized locations:

| Organized file | Contents |
| --- | --- |
| `fx/placements.json` | Source IDs, candidate transforms, effect references, attached names and raw fields |
| `fx/assets.json` | Referenced FX hashes, name-resolution status and source headers |
| `fx/entity_references.json` | Authored entities with FX-related properties |
| `animation/model_placements.json` | Model rows selected by animation properties or name hints |
| `animation/entity_references.json` | Entities carrying animation-related properties |
| `animation/named_references.json` | Original property values, candidate hashes and loaded-animation matches |
| `animation/assets.json` | Selected XAnim metadata and raw headers |

### Follow identities, not name similarity

Within a capture, join `EffectPointer` to the corresponding FX asset.
An unresolved `EffectName` remains null. `EffectHashMasked` supports the
60-bit lookup; `EffectHash` preserves the original value.

Attached strings such as lighting-state names are reference labels, not proven
effect paths or decoded event logic. An `fxanim` or `fxanm` name is a selection
hint; it does not prove that an animation is active.

Follow `SourceEntityId` to its original entity and `AnimationHash` to an
animation asset when a match exists. An `animscript` property can name a script
instead of an XAnim. Unmatched values remain unresolved.

Model rows preserve their transforms, `SourcePlacementFile`,
`SourcePlacementIndex`, `AttachedEntityProperties` and `SelectionEvidence`.
Do not create model-to-animation links solely from similar filenames.

### Reader details

The measured level-FX header is 40 bytes with count at +8 and pointer at +16.
Its 80-byte records carry candidate position at +8 and pitch/yaw/roll at +20.
Attached-reference count is +56 and pointer +72; 32-byte attached records begin
with a string pointer. Remaining integer fields retain their original offsets.

The reader bounds attached counts to 64 and string reads to 1,024 bytes/the
readable region, then rereads captured records and strings. FX references are
checked against pool 0x33's 144-byte asset records.

XAnim metadata uses 288-byte records: name hash +0x70, frame rate +0xB0,
frequency +0xB4, bone count +0xFE, notification count +0x100 and frame count
+0x104. Validate these layouts for the active game build.

Dynamic-model `PhysicsReference` fields point to physics evidence; they must
not be treated as animation links.

### Audit a saved run

```powershell
$run = '<path to your completed placement run>'
python tools/cold_war/capture/verify_cw_fx_anm.py $run
```

The auditor supports catalog aliases. It checks raw records, attached strings,
readback status, source transforms, preserved properties and animation joins.

## Authored scene objects

The optional scene workflow captures scriptbundles and resolves authored
object/shot alignment. It is a developer workflow, separate from the GUI's
automatic placement export.

| Tool | Role |
| --- | --- |
| [capture_cw_scriptbundles.py](../tools/cold_war/capture/capture_cw_scriptbundles.py) | Live bundle capture anchored to a matching placement run |
| [enrich_cw_scene_bundle.py](../tools/cold_war/capture/enrich_cw_scene_bundle.py) | Interpret saved fields against a supplied CW source dump |
| [resolve_cw_scene_placements.py](../tools/cold_war/capture/resolve_cw_scene_placements.py) | Resolve entity/struct alignment references |
| [verify_cw_silver_scenes.py](../tools/cold_war/capture/verify_cw_silver_scenes.py) | Silver-specific count and zero-offset audit |

Capture bundles while the same map remains loaded, before organizing the run.
Use each tool's `--help` and inspect its expected input schema. The source dump
and saved captures must be supplied by the contributor; they are not included.

Derived files include `animation/object_placements.json`,
`animation/scene_placements.json`, per-bundle object files and validation
metadata. They describe authored alignment before animation root/bone motion.
A player-type scene object does not imply a particular static model.

Named targets can resolve through entity `targetname` or authored structs.
Tags, ambiguous targets, invalid transforms and unsupported angle behavior
must remain unresolved. Do not generalize the Silver zero-offset validation
to nonzero offsets or another map without new evidence.

## Decode a saved entity list

First capture pool 0x8E with
[the map-data workflow](capture-research.md#capture-entities-and-triggers).
Then run the independent saved-byte decoder:

```powershell
$capture = '<path to your ENTITYLIST capture>'
$output = '<path to a new decoded-entity folder>'
python tools/cold_war/capture/decode_cw_entitylist.py --capture $capture --output $output
```

Python 3.10+ is sufficient for this decoder. Optionally pass
`--map-name MAP_NAME` and `--bo3-def` with the path to your installation's
`bin/t7.def.json` to record BO3 class-name checks.

| File | Use |
| --- | --- |
| `entities.json` | Compact `Entities` array of conversion key/value dictionaries |
| `entities.decoded.json` | Ordered typed properties, raw bytes, transforms, hashes and reference checks |
| `summary.json` | Counts, unresolved references and conversion limits |

This tool reads original pool evidence and checks the native candidate decoder.
It does not replace the native exporter's original `entities.json` in place.

### Precision and property conventions

Named origin/angle properties can be rounded while record fields retain float32
precision. The decoder selects finite record transforms at offsets +24/+36
when they agree with the named properties within 0.50001, retaining both values
and the selection evidence. The native non-static placement reader has its own
documented tolerance; see [placement transforms](cw-placements.md#bo3-transform-and-asset-mapping).

- `entities[i].index` preserves the source array index.
- `properties` and `keyvalues` retain original named values.
- `origin`, `angles`, `transform` and `conversion_keyvalues` use the selected transform.
- `property_list` preserves order, type tags, raw 32-byte records and unknown tails.
- Duplicate keys stay in the ordered list; convenience dictionaries omit them.
- Hashes remain hexadecimal strings so JSON consumers retain all 64 bits.
- Integer properties preserve signed and unsigned interpretations.
- All 48 entity-record bytes survive, including fields with unknown semantics.

There is no recentering, snapping or axis conversion. A class-name match in BO3
does not validate spawnflags, properties, scripts or required assets.
An unresolved `target` may refer to an entity created at runtime.

ENTITYLIST, TRIGGERLIST and GAME_MAP indices are separate namespaces. Join them
only through validated source relationships, never by equal numeric indices.

## Contributing and research packages

Useful next work includes FX asset-name resolution, effect-internal curves,
runtime attachment/pose evidence, unsupported entity classes and cross-map
scene validation. Add a synthetic regression fixture for each new rule.

[build_cw_placement_reference.py](../tools/cold_war/capture/build_cw_placement_reference.py)
is a Silver-specific research packager with fixed input filenames and required
intermediate reports. It is not a general placement exporter and its old
research workspace is not shipped. Inspect `build()` before adapting it to
your own inputs; the reusable decoders above accept explicit paths.

A reference package can index original entities, material decisions, trigger
hulls and navigation relationships. Preserve provenance for every derived
placement and leave unsupported behavior explicit. A package inventory does
not establish complete collision decoding or a game-ready map.
