# Source-data validation, 2026-09-05

This pass uses only Greyhound's own Cold War captures. No conversion was run.
The loaded map is identified by captured zm_silver strings. Verification is on
the same loaded map and process; no map reload or second-map validation is claimed.

## Results

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

## Property evidence

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

## Retained captures

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

## Tests and limits

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
