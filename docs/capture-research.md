# Capture contracts and research

[Documentation index](README.md) | [Contributing](contributing.md)

Use this guide when collecting evidence for a decoder, investigating an
unsupported layout, or checking a saved export. For normal exports, start with
[CW placements](cw-placements.md), [CW brushes](cw-collision.md) or [BO4](bo4.md).

## Choose the smallest useful capture

**Settings > Dev Tools** groups Cold War asset pools, Cold War capture options,
BO4 diagnostics, and export workflows/checks. Enable the pools you need, then
**Load Game** again to refresh the list. Capture options are read at export time.

| Workflow | Route | Output and limits |
| --- | --- | --- |
| CW terrain | Terrain settings and terrain asset export | Source data with a sealed inventory; terrain reconstruction is external. |
| CW placements | Map & Model Export | Rigid placements and optional entities, FX, lights and probes; [Spline models from JSON](cw-placements.md#static-spline-model-export) bakes each instance in the selected model formats, with per-model images and material info. |
| CW brushes | Radiant Brushes | Supported collision hulls and trigger/volume prefabs; unresolved material/layout decisions remain in reports. |
| CW pool diagnostics | Dev Tools, then export `cw_pool_` RawFile rows | Headers, bounded prefixes or supported counted arrays, depending on mode. |
| BO4 terrain | Terrain settings | Measurement probe, separate from the sealed CW capture contract. |
| BO4 diagnostics | Dev Tools, Run | World pools, model collision, physics, placements, handlers or surface declarations. |
| Runtime checks | Dev Tools, Check runtime | Packaged hashes, imports, catalogue and helper startup. |
| Saved-export checks | Dev Tools, Check saved export | Published prefab hashes or sealed terrain inventory. |

A failed capture should retain diagnostics when possible. Read its status and
coverage fields before using the output. A successful byte audit does not prove
visual equivalence, a successful Radiant compile or equivalent gameplay.

## Cold War pool discovery

Enable the relevant groups and search the asset list for `cw_pool_`. Research
rows are RawFiles ending in `_headers`; the ordinary Raw Files setting is
independent. CLI discovery uses the same loaded game:

```powershell
$gh = '.\bin\cli\Greyhound-cli.exe'
& $gh assets list --type rawfile --glob 'cw_pool_*' --json
```

| Group | Pool selectors to investigate |
| --- | --- |
| Collision / clips | physpreset 0x02, physconstraints 0x03, xcollision 0x07, col_map 0x17, clip_map 0x18 |
| Map worlds | com_map 0x19, game_map 0x1A, gfx_map 0x1B |
| Navigation | navmesh 0x75, navvolume 0x76, navinput 0xC2 |
| Effects | fx 0x33, staticlevelfxlist 0x7F |
| Entities / dynamic models | destructibledef 0x04, glasses 0x43, keyvaluepairs 0x4B, scriptbundle 0x57, entitylist 0x8E, dynmodel 0xD1 |
| Triggers | triggerlist 0x80, triggereffectdesc 0xD7, triggeractions 0xD8 |
| AI / animation tables | animtree 0x3E, aimtable 0x5C, animstatemachine 0x62, behaviortree 0x63, behaviorstatemachine 0x64 |

These 27 selectors are research entry points. An enum name alone does not
establish a header shape, nested payload type or BO3 equivalent. Check the
active build's pool shape, occupancy and asset identity before interpreting it.

## Capture modes

| Mode | Purpose | Important boundary |
| --- | --- | --- |
| Headers only | Preserve the pool descriptor and header bytes | Full capacity is captured; occupied entries are not assumed contiguous. |
| `--cw-probe` | Sample one hop of referenced prefixes | Aligned integers can resemble pointers; prefixes are untyped evidence. |
| `--cw-deep-probe` | Explore a bounded two-hop graph | Free-list checks, node/edge limits and skipped ranges remain explicit. |
| `--cw-map-data` | Capture supported entity/trigger arrays and properties | Structural validation and second-read equality are required. |
| `--cw-collision-code-probe` | Save a fixed collision-reader code span | Build-specific diagnostic; replaces the ordinary pool capture. |

`--cw-map-data` takes precedence over graph flags. The collision code probe is
a diagnostic override; see [its build restriction](cw-collision.md#collision-reader-code-probe).

One-hop mode samples at most 256 slots and 256 distinct addresses, with at most
4,096 bytes per prefix. It does not recursively follow those bytes. Deep mode
samples at most 256 eligible headers, 16,384 edges and 512 addresses, with at
most 64 KiB per address and two hops. Refer to each report for actual coverage.

Headers are bounded by readable memory and a 256 MiB cap. A probe prefix can
contain adjacent unrelated bytes. Missing a pointer within a sample does not
prove that an asset has no payload.

## Capture entities and triggers

With Cold War running on the target map:

```powershell
$gh = '.\bin\cli\Greyhound-cli.exe'
& $gh assets export --type rawfile --name cw_pool_080_triggerlist_headers --name cw_pool_08E_entitylist_headers --cw-map-data --json
```

Use the directories reported by that invocation. Each pool reserves a fresh
folder below `exported_files/black_ops_cw/xrawfiles/`.

Typical evidence includes `evidence.json`, start/end descriptors, header
bytes, packed source records and `decoded_candidates.json`. The evidence
manifest maps logical reads to their stored byte ranges; do not assume one
separate file per record.

The supported entity layout has 48-byte records and 32-byte properties.
Trigger geometry uses measured 8-byte models, 32-byte hulls and 20-byte slabs.
Counts, ranges, finite bounds, nonnegative half-extents and approximately unit
slab normals are checked.

| Property tag | Interpretation retained in candidate JSON |
| --- | --- |
| 2 | String |
| 3 | Three-component vector |
| 4 | Asset hash, preserved as hexadecimal |
| 5 | Float |
| 6 | Integer, with signed and unsigned interpretations |

Raw values remain alongside decoded fields. Unknown tags are not assigned
invented meanings. Model/hull association needs independent evidence; matching
counts or array order alone are insufficient.

Every captured array and terminated string is reread uncached. Differing bytes
are retained separately and fail validation. Verification shares the scene
budget and retains at most 32 MiB of expected bytes at a time. Equal reads
still do not provide an atomic snapshot of the game.

## Audit saved evidence

The Node.js audit reads saved bytes without attaching to the game:

```powershell
$capture = '<path to your entity or trigger capture>'
$report = '<path for a new audit report.json>'
node tools/cold_war/capture/audit_cw_map_data.cjs $report $capture
```

Additional capture directories can follow `$capture` for comparison by pool,
map hash, raw-array hashes and semantic hashes. The audit checks packed spans
and decoded properties against their original bytes.

For a precise ENTITYLIST conversion document, use the
[entity decoder](cw-effects-entities.md#decode-a-saved-entity-list). Placement,
FX and probe auditors have their own input contracts; some expect a completed
flat run and cannot consume an organized directory directly.

## Sealed terrain source boundary

CW terrain source evidence is organized under `_source/capture/` and described
by `_source/research_capture.report.json`. Once its SHA-256 inventory is written,
treat that evidence as immutable. Write experiments and derived artifacts to a
separate output directory.

The source layout and finalizer live in
[shared core](../tools/shared/core/layout.py) and
[shared capture tools](../tools/shared/capture/finalize_research_capture.py).
Greyhound owns discovery/capture and supported brush conversion. Terrain
reconstruction and OMPV baking belong to a separate consumer.

BO4 probes use their own layouts and completeness reports. Do not apply CW
finalization or offsets to a BO4 capture.

## What reviewers should check

1. Record game/build and map identity, selected pools, options and database.
2. Confirm occupancy, count/capacity checks and every pointer/range bound.
3. Follow source bytes into decoded fields, then into the consuming exporter.
4. Account for rejected, unresolved and omitted records as well as successes.
5. Separate saved-data tests from fresh live capture, compile and gameplay tests.
6. Repeat promising layout findings on a reloaded map and another map/build.

Use the relevant synthetic tests in `tests/cold_war/`, `tests/black_ops_4/`
and the native runner. See [validation](contributing.md#validation-and-sharing).

The checked-in [map-data audit](cw-map-data-validation.json) and
[probe-bounds evidence](cw-probe-bounds-evidence.json) preserve historical
measurements. Machine-local path prefixes have been replaced with descriptive
placeholders; captured hashes and measured values are unchanged. Referenced
captures/disassembly are not bundled fixtures and those records are not tests
of your current checkout.
