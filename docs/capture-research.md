# Capture contracts and measured validation

[Documentation index](README.md) | [Contribution walkthrough](contributing.md)

This reference consolidates measured findings and their limitations.
Capture counts and local output paths below identify development samples,
not bundled fixtures or guarantees for every game build. Historical
validation is distinct from tests run on your current checkout.


## Dev Tools integration — 2026-09-15

The Dev Tools page is divided into Cold War asset pool groups, Cold War capture
options, Black Ops 4 diagnostic captures, and export workflows/checks. The
former CW Map Export page is named Map & Model Export because its placement
and model actions also support BO4. Selecting pool groups controls the assets
listed after loading the game; selecting a capture mode controls their export.

| Workflow | Exposed route | Scope and remaining limits |
| --- | --- | --- |
| CW terrain | Terrain settings, terrain asset export | Source capture and sealed inventory; reconstruction belongs to TerrainReconstructor. |
| BO4 terrain | Terrain settings, terrain asset export | Measurement probe; TerrainGfx layout is not fully decoded and the probe is not a sealed CW capture. |
| CW clips and brushes | Brush export settings/action | Supported hulls, per-brush BO3 material matching, traversal tools, separate collision and tool prefabs, trigger/volume exports and local model collision. Unknown or approximate assignments remain in reports. |
| CW optional triangle collision | Brush export option | Float triangle OBJ sidecar now reads both loose and packed native payloads. This does not complete the compact/quantized collision branches. |
| BO4 clips and brushes | Brush export settings/action or diagnostic mode 5 | Supported world and model-physics prefabs plus trigger exports. Optional model collision triangles are decoded evidence, not a completed mesh export. |
| CW placements and models | Map & Model Export | Existing static/nonstatic placement controls, lights/probes and FX/animation evidence; model batch export and resume. Source spline capture does not implement spline deformation. |
| BO4 placements and models | Map & Model Export; diagnostic mode 4 | Static placements and model batch export. No claim of CW nonstatic feature parity. |
| BO4 diagnostics | Dev Tools, direct Run button | World pools, model collision references, physics, placements, collision handlers and surface declarations; no TerrainGfx selection needed. |
| Installed runtime | Dev Tools, Check runtime | Packaged file hashes, Python imports, material catalogue and terrain helper startup. |
| Saved export | Dev Tools, Check saved export | Published prefab hashes or sealed terrain inventory; source data is read only. |

The Cold War collision code probe is confined to pool diagnostics. It cannot
override an explicit Radiant export. Its fixed RVA remains specific to the
measured executable build, even if readback succeeds on another build.

### Validation

The implementation passed the Release x64 native build, 39 Python tests with
11 subtests, and all 14 standalone native test programs. The native suite covers
pool bounds, placements, lights, model naming/selection/LOD/proxy filtering,
resume checkpoints and XSUB layout. Python checks cover the conversion helpers,
packed/loose float triangles, saved-export verification, source-only terrain
boundaries, scene controls and actual runtime staging in temporary directories.

Reproduce from the repository using:

```powershell
& C:\SuperTerrain\.venv\Scripts\python.exe -m pytest tests -q
.\tests\run-native-tests.ps1
.\build-greyhound.ps1 -BuildOnly
```

Native test logs and their summary are under `test-output/native-tests`.
Installed-runtime and saved-capture checks are under
`test-output/dev-tools-integration`. The installed runtime passed all 12 checks
and the headless CLI help command exited successfully. Silver's four saved
prefabs passed their hashes. Tungsten's collision and other-brush prefabs passed,
but its older report lacks hashes for volumes and triggers; those two cannot be
verified against that report. The verifier reports this limitation as a failure
and does not rewrite the source inventory.
The saved sealed CW terrain capture also passed: all 7,128 inventoried files
matched, with no added files. Saved-capture checks have a 30-minute worker timeout
to accommodate large inventories; runtime startup checks retain two minutes.

Replaying Silver's saved capture through the packaged float-triangle decoder
produced 59,322 vertices and 85,631 triangles across 51 supported models, with
zero group-bounds violations. Its remaining 1,322 records were reported as
unsupported by this particular decoder. This validates saved-data decoding;
the OBJ retains captured coordinates without applying world placements.

These tests do not establish fresh live-game
capture success, visual UI layout correctness, Radiant compilation or BO3
gameplay equivalence. No UI automation is required to run them.


## Cold War pool capture for future BO3 reconstruction

### Current source-data validation mode

Use `--cw-map-data` for repeat entity/trigger captures. It captures counted
candidate records without the speculative graph, decodes property tags 2/3/4/5/6
as string/vector/asset-hash/float/integer candidates, and includes the exact
16-byte value field alongside each property. Hashes stay hexadecimal; both
signed and unsigned interpretations of integer values are retained.

```powershell
.\Greyhound-cli.exe assets export --type rawfile --name cw_pool_080_triggerlist_headers --name cw_pool_08E_entitylist_headers --cw-map-data --json
```

This mode fails rather than claiming success for unsupported layouts or unknown
slot occupancy. It bounds candidate geometry ranges, checks finite bounds,
nonnegative half-extents and approximately unit slab normals, and performs an
uncached second read of every captured array and each terminated string through
its NUL byte. Headers are reread too. Any differing bytes are saved separately;
changed/failed verification makes the export fail. Verification shares the
resident-scene budget and holds at most 32 MiB of expected bytes. No second copy
is written for unchanged data. Matching reads do not create an atomic snapshot.

`decoded_candidates.json` now uses schema v2. Its `complete` field means reads,
candidate structural checks, and second-read equality passed. The detailed
`geometry_validation`, `readback_unchanged`, `verification_ranges` and raw-value
fields make the scope inspectable. Evidence.json contains each verification
outcome and timing. `--cw-map-data` takes precedence over graph flags.

Offline audit (Node.js) verifies packed spans and compares the decoded values
against their raw property bytes; optional additional captures are compared by
pool, map hash, raw-array SHA-256 and semantic SHA-256:

```powershell
node tools/cold_war/capture/audit_cw_map_data.cjs report.json CAPTURE_DIRECTORY [ANOTHER_CAPTURE_DIRECTORY]
```

See [latest validation and retained paths](capture-research.md).
The initial-capture sections below describe how the layouts were discovered.

### Live-tested CLI extension (2026-09-05)

The rebuilt `bin/cli/Greyhound-cli.exe` supports `--cw-probe` for the original
one-hop mode and `--cw-deep-probe` for the new bounded two-hop mode. These flags
are per invocation. The GUI probe checkbox retains its original one-hop behavior.

Example, with Cold War running and a map loaded:

```powershell
.\Greyhound-cli.exe assets export --type rawfile --name cw_pool_080_triggerlist_headers --name cw_pool_08E_entitylist_headers --cw-deep-probe --json
```

Deep mode checks the free-list chain against capacity/loaded count before
excluding free slots. If that check fails, occupancy remains unknown. It samples
at most 256 eligible headers, records up to 16,384 incoming reference edges,
deduplicates up to 512 candidate addresses, reads at most 64 KiB per address,
and follows at most two hops. Code/image mappings are skipped. Limits and all
read outcomes remain in evidence.json. These prefixes can overlap and contain
unrelated adjacent bytes; addresses and count-like integers are not proven types.

For a single occupied entitylist (24-byte header) or triggerlist (72-byte header),
deep mode also attempts the candidate counted layouts measured in our live
sample. It saves 48-byte entity records, 32-byte property records, unique bounded
string prefixes, and trigger arrays with candidate strides 8/32/20. Every count
and read is bounded. String tag 2 and vector tag 3 are decoded as candidates;
other tags retain their raw bytes. `decoded_candidates.json` preserves names,
values, source addresses, record indices and unresolved fields. Small source
records are packed into `small_records.bin`, indexed by evidence.json/storage.

The `complete` flag covers successful reads under these candidate layouts and
terminated string prefixes. It does not mean full semantic decoding, an atomic
snapshot, original editor brush recovery, or validated BO3 geometry. No decoder
for the clip_map pool has been established yet.

Live validation on the map identified by captured `zm_silver` strings recovered:

- 2,380 entitylist records and 327 separately stored triggerlist records.
- Triggerlist classes: 187 info_volume, 82 trigger_multiple, 23 trigger_damage,
  22 trigger_use_touch, 8 trigger_use, 4 trigger_box, and 1 trigger_hurt.
- Counted candidate geometry arrays: 323 trigger models, 357 hulls, 576 slabs.
- All requested typed arrays and string reads succeeded. Unknown property tags
  4/5/6 remain undecoded. Model-to-entity association, hull/slab semantics and
  collision contents still require validation; do not infer them from ordering.

The older CLI runtime did not expose research rows. Rebuilding/staging the
current source restored discovery of 25 populated research pools. Release x64
build and synthetic planner tests passed. Temporary redundant captures should
be removed after verification; retain one useful source capture per pool.

The current split is appropriate: Greyhound discovers and exports game data;
the desktop SuperTerrain/Terrain Reconstructor consumes saved exports offline.
At this initial research stage, the native exporter invoked only capture
organization/finalization helpers. Current builds also package supported brush
conversion; terrain reconstruction remains external.

### Source and confidence

Reference: [ProjectDonetsk/T9 Main.hpp](https://github.com/ProjectDonetsk/T9/blob/048a1a0d7ca75ccb190a45a32c7882e4ac1e3ebb/hook_lib/Main.hpp).
Its enum explicitly warns that the originating update is unknown and values may
have changed. These are Cold War research selectors, not BO3 asset IDs. An enum
name does not establish a header or nested payload layout. Validate pool shape,
name/hash references, and repeated captures for the installed build first.

These measurements describe this Greyhound fork; they do not establish parity
with any separate private exporter.

### Exposed pools and intended future use

| In-Game Settings group | T9 enum candidates | Future BO3 use after layout validation |
| --- | --- | --- |
| Collision / clips | physpreset 0x02, physconstraints 0x03, xcollision 0x07, col_map 0x17, clip_map 0x18 | Collision meshes, contents/surface flags, clip volumes; investigate planes/brushes before converting to Radiant collision |
| Map worlds | com_map 0x19, game_map 0x1A, gfx_map 0x1B | Shared world data, placement/entity candidates, render-world geometry and lighting references |
| Navigation | navmesh 0x75, navvolume 0x76, navinput 0xC2 | Traversability and volume evidence; BO3 navigation will need its own build/translation |
| Effects | fx 0x33, staticlevelfxlist 0x7F | Effect definitions and possible static placement records |
| Entities / dynamic models | destructibledef 0x04, glasses 0x43, keyvaluepairs 0x4B, scriptbundle 0x57, entitylist 0x8E, dynmodel 0xD1 | Investigate authored properties, model references, placements and breakables |
| Triggers | triggerlist 0x80, triggereffectdesc 0xD7, triggeractions 0xD8 | Investigate volumes and action references |
| AI / animation tables | animtree 0x3E, aimtable 0x5C, animstatemachine 0x62, behaviortree 0x63, behaviorstatemachine 0x64 | Preserve evidence for future behavior translation |

There are 27 pool selectors. Surface responses (0x4E, 0x4F, 0x50) remain future
candidates. All purposes above are research hypotheses based on enum names.

### Use

1. Open Settings > In-Game Settings and enable the CW research groups needed.
2. Click Load Game again with a supported Cold War process/map loaded.
3. Search for `cw_pool_`. Each row is one populated pool, displayed as RawFile;
   its name ends in `_headers`. The ordinary Raw Files checkbox is independent.
4. Optionally enable **Probe referenced bytes (experimental)** before exporting.
   This setting is read at export time; no reload is needed for this switch.
5. Export the desired rows normally. Under the normal `xrawfiles` output,
   each export reserves a new `cw_pool_<hex>_<tick>` directory.

Each directory contains evidence.json, descriptor_start.bin, headers.bin and
descriptor_end.bin when those reads succeed. Metadata includes process identity,
UTC timing, enum provenance, capacity, loaded count, free-list head, requested
and actual read sizes, per-read failures, and descriptor stability. Pool header
reads are capped at 256 MiB, validated against readable memory, and preserve full
capacity rather than assuming occupied slots are packed at the beginning.
Failed or partial reads/writes and changed descriptors fail the export while
retaining an explanatory manifest when possible. Captures are not atomic.

### Optional one-hop probe

The default remains headers only. The probe visits at most the first 256 slots
(including potentially free slots), skips the first word of each header, and
looks for aligned 64-bit words in the user-address range. It deduplicates addresses
and attempts at most 256 distinct prefixes per pool. Each prefix is at most
4096 bytes, clipped to the containing virtual-memory region and checked for
readability before reading. Maximum requested prefix bytes: 1 MiB per pool.
It never recursively follows captured bytes or guesses array strides.

The manifest records slot index, parent address, field offset, candidate address,
requested/read bytes, file and status, plus slots omitted and address-limit
coverage. Repeated references retain the first occurrence only. Unreadable
candidates are expected and recorded; they do not invalidate an otherwise saved
header capture. Write failures do fail the export. Descriptor checks still only
cover the descriptor, not stability of headers or pointed-to contents.

`probe_0x<address>.bin` files are unverified prefixes, potentially including adjacent
unrelated bytes. `payloads_captured: false` continues to mean there is no complete
asset payload claim. A missing match does not mean the pool has no payload:
pointers can have other encodings, and occupied slots can fall outside the sample.

### Suggested testing sequence

1. Capture collision/clips, entities/dynamic models and triggers with probe off.
2. Export the same pools with probe on while the same map is loaded.
3. Repeat after a map reload and on a second map. Keep every capture directory.
4. Compare pool shapes, candidate field offsets, name/hash words and saved bytes;
   process addresses alone are not stable asset identities.
5. Use the evidence to establish slot occupancy and counted array layouts before
   adding typed extraction or BO3 conversion. Navvolume and FX are useful next.

No complete collision meshes, brushes, entity placements, trigger volumes, nav
polygons or behavior graphs are decoded yet. These files use a research schema;
they cannot already be fed to the terrain reconstructor.

### Validation

The existing exporter/reconstructor boundary tests pass (3 tests). A native
synthetic probe test passes for address filtering, deduplication, offsets,
invalid/truncated headers, slot limits and candidate limits. Native Release
x64 compilation passed (existing compiler/linker warnings remain). No Cold War process was running during
this session, so pool population, real capture output and GUI appearance still
require an in-game smoke test. A successful build is not evidence of correct
collision layouts or compatible pool IDs on a particular installed game build.


## Source-data validation, 2026-09-05

This pass uses only Greyhound's own Cold War captures. No conversion was run.
The loaded map is identified by captured zm_silver strings. Verification is on
the same loaded map and process; no map reload or second-map validation is claimed.

### Results

- 2,380 entity-list records with 36,787 properties.
- 327 trigger-list records with 4,905 properties.
- Previous and new captures: identical counted-array bytes and identical decoded
  semantic values, checked with SHA-256 by an independent offline reader.
- 4,472 array/string ranges and two pool-header ranges matched a second live
  read. Changed/failed verification would fail the export and retain evidence.
- Candidate geometry checks passed: 323 models reference all 357 hulls, and
  those hulls reference all 576 slabs with no out-of-range spans. Bounds were
  finite with nonnegative half-extents. Slab normals were approximately unit
  length, and slab half-widths were nonnegative.

The previously unresolved hull fields at +28/+30 fit separate uint16 slab
count/start fields; +24 remains raw contents bits. The four trailing entity
records are trigger_box, whereas the first 323 records have other classes.
That supports a possible ordering relationship but does not prove model/entity
association. The tool deliberately leaves that association unassigned.

### Property evidence

| Tag | Current interpretation | Observed properties |
| --- | --- | ---: |
| 2 | String candidate | 34,751 |
| 3 | Vector candidate | 5,427 |
| 4 | 64-bit asset-hash candidate | 1,036 |
| 5 | Float candidate | 250 |
| 6 | Integer candidate, signed and unsigned retained | 228 |

Tag 4 occurs on model, script_sound and scriptbundlename. Tag 5 includes
modelscale and numeric timing/cost properties. Tag 6 contains values such as
script_int, zombie_cost and boolean-like fields. Raw 16-byte values remain in
JSON and source property records so these hypotheses can be revised without
another capture. No unknown hash was replaced with an invented asset name.

### Retained captures

Relative to C:/SuperTerrain/repos/Greyhound:

- `bin/cli/exported_files/black_ops_cw/xrawfiles/cw_pool_080_556267703/`
  Latest trigger capture, source arrays, v2 decoded candidates and verification.
- `bin/cli/exported_files/black_ops_cw/xrawfiles/cw_pool_08E_556268156/`
  Latest entity capture, source properties, v2 decoded candidates and verification.
- `bin/cli/exported_files/black_ops_cw/xrawfiles/cw_pool_018_555287812/`
  Retained clip-map exploratory graph. This remains undecoded and is not covered
  by the new typed-array correctness claims.

The previous entity/trigger captures were removed after equality was proven,
freeing 47,820,802 bytes. The comparison record retains their raw-array digests,
semantic digests and original paths for provenance. Existing user captures under
bin/exported_files were left untouched.

### Tests and limits

Release x64 builds and live CLI export passed. Native tests exercise truncated
geometry, invalid ranges, nonfinite/negative bounds, invalid slab normals, and
probe traversal limits. Offline audit tests reject corrupted packed ranges,
truncated data and disagreements between raw bytes and decoded JSON. All three
source/exporter boundary tests passed. Existing compiler/linker warnings remain.

Next: repeat on a reloaded/different map, establish the trigger/entity association,
resolve asset hashes against independently identified assets, and investigate
the clip-map physics layouts. Repeatability and structural checks are evidence;
they do not prove gameplay semantics or recover original editor brushes.

Machine-readable evidence: [cw-map-data-validation.json](cw-map-data-validation.json).


## Own-source Cold War entity and trigger capture

Historical first-capture report. The entity/trigger directories listed below
were superseded by byte-identical, readback-verified captures and removed to
avoid bloat. See [current retained captures](capture-research.md) and
the persisted [comparison evidence](cw-map-data-validation.json).

Tested 2026-09-05 against the running Cold War process. Captured strings identify
the map as zm_silver. No C2M or third-party exported entity data was used to derive
these layouts. Local source and both Greyhound.exe / cli/Greyhound-cli.exe were
updated and the CLI was exercised against the loaded map.

### Retained source evidence

Paths are relative to the Greyhound repository:

- `bin/cli/exported_files/black_ops_cw/xrawfiles/cw_pool_018_555287812/`
  Clip-map header and bounded two-hop graph. No typed clip decoder yet.
- `bin/cli/exported_files/black_ops_cw/xrawfiles/cw_pool_080_555477921/`
  Trigger records and counted candidate geometry arrays, with decoded_candidates.json.
- `bin/cli/exported_files/black_ops_cw/xrawfiles/cw_pool_08E_555478593/`
  Entity/property records, with decoded_candidates.json.

The two earlier probe-only entity/trigger test exports were deleted after the
targeted captures succeeded. The user's pre-existing bin/exported_files captures
were left intact. Temporary native test binaries and redundant inventory logs
were removed.

### What was recovered

| Source | Records | Details |
| --- | ---: | --- |
| Entity list | 2,380 | Includes 1,611 script_struct, 140 script_model, 122 node_negotiation_volume |
| Trigger list | 327 | 187 info_volume, 82 trigger_multiple, 23 trigger_damage, 22 trigger_use_touch, 8 trigger_use, 4 trigger_box, 1 trigger_hurt |
| Trigger-model candidate array | 323 | 8-byte records |
| Trigger-hull candidate array | 357 | 32-byte records |
| Trigger-slab candidate array | 576 | 20-byte records |

All candidate counted arrays and requested string prefixes were readable and
saved; strings were terminated within the bound. There were 1,533 unique strings
in the entity-list capture and 227 in the trigger-list capture. The saved property
type tags include 2 (string candidate), 3 (three-float candidate), and unresolved
4/5/6. Unresolved values remain in the raw property records, indexed by source
entity and the evidence storage map. Property ordering and source indices survive.

Candidate model record fields at +4/+6, interpreted as unsigned 16-bit hull
count/start, reference all 357 hull records with zero out-of-range spans. This is
evidence for that relationship, not proof of all trigger semantics. The first
six floats in each hull and five floats in each slab were finite. Hull trailing
fields are packed/unknown and must not be treated as a simple unmasked index.

### Remaining work

1. Validate the same layouts after a map reload and against a second map.
2. Establish trigger-entity-to-model association. There are 327 entity records
   and 323 model records; do not blindly zip arrays or discard four records.
3. Resolve packed hull/slab ranges and contents flags. Then verify reconstructed
   convex volumes against known trigger positions and bounds.
4. Decode scalar property tags 4/5/6 with raw-value comparisons.
5. Investigate the clip-map graph for physics shape ownership, planes/meshes,
   transforms and entity links. Saved speculative prefixes are not full assets.

The native tool remains a source dumper. It does not fabricate brush geometry or
claim that this data is already a compilable BO3 map.

### Validation

Release x64 build passed (existing compiler/linker warnings remain). Synthetic
probe tests passed for free-list cycles/alignment/count mismatches, graph cycles,
duplicate incoming references, depth/node/edge limits and original one-hop limits.
All three exporter/reconstructor boundary tests passed. Live inventory found 25
populated research pools; targeted export returned success. Captures are explicitly
non-atomic; an unchanged pool descriptor does not prove unchanged nested data.
