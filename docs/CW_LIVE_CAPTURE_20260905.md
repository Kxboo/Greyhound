# Own-source Cold War entity and trigger capture

Historical first-capture report. The entity/trigger directories listed below
were superseded by byte-identical, readback-verified captures and removed to
avoid bloat. See [current retained captures](CW_DATA_VALIDATION_20260905.md) and
the persisted [comparison evidence](cw-map-data-validation.json).

Tested 2026-09-05 against the running Cold War process. Captured strings identify
the map as zm_silver. No C2M or third-party exported entity data was used to derive
these layouts. Local source and both Greyhound.exe / cli/Greyhound-cli.exe were
updated and the CLI was exercised against the loaded map.

## Retained source evidence

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

## What was recovered

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

## Remaining work

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

## Validation

Release x64 build passed (existing compiler/linker warnings remain). Synthetic
probe tests passed for free-list cycles/alignment/count mismatches, graph cycles,
duplicate incoming references, depth/node/edge limits and original one-hop limits.
All three exporter/reconstructor boundary tests passed. Live inventory found 25
populated research pools; targeted export returned success. Captures are explicitly
non-atomic; an unchanged pool descriptor does not prove unchanged nested data.
