# Cold War pool capture for future BO3 reconstruction

## Current source-data validation mode

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
node tools/capture/audit_cw_map_data.cjs report.json CAPTURE_DIRECTORY [ANOTHER_CAPTURE_DIRECTORY]
```

See [latest validation and retained paths](CW_DATA_VALIDATION_20260905.md).
The initial-capture sections below describe how the layouts were discovered.

## Live-tested CLI extension (2026-09-05)

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
The native exporter only invokes capture organization/finalization helpers.
This work adds no reconstruction to Greyhound.

## Source and confidence

Reference: [ProjectDonetsk/T9 Main.hpp](https://github.com/ProjectDonetsk/T9/blob/048a1a0d7ca75ccb190a45a32c7882e4ac1e3ebb/hook_lib/Main.hpp).
Its enum explicitly warns that the originating update is unknown and values may
have changed. These are Cold War research selectors, not BO3 asset IDs. An enum
name does not establish a header or nested payload layout. Validate pool shape,
name/hash references, and repeated captures for the installed build first.

The local exporter is C:/SuperTerrain/repos/Greyhound (origin Kxboo/Greyhound).
The requested superterrainhoundprivate URL could not be accessed in this session;
no comparison with its contents or synchronization to that repository is claimed.

## Exposed pools and intended future use

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

## Use

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

## Optional one-hop probe

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

## Suggested testing sequence

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

## Validation

The existing exporter/reconstructor boundary tests pass (3 tests). A native
synthetic probe test passes for address filtering, deduplication, offsets,
invalid/truncated headers, slot limits and candidate limits. Native Release
x64 compilation passed (existing compiler/linker warnings remain). No Cold War process was running during
this session, so pool population, real capture output and GUI appearance still
require an in-game smoke test. A successful build is not evidence of correct
collision layouts or compatible pool IDs on a particular installed game build.
