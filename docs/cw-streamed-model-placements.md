# Cold War streamed model placements

`Export Model Placements` uses the shared DISTRICTS reader in
`CWMapWorldCapture.h`. It writes the existing plain `static_models.json` array
and a separate `placement_report.json`. `Models from JSON` can consume that
array using the existing naming and LOD settings.

The reader follows the loaded map's counted district table and each populated
placement descriptor. It first tries stable live placement arrays. If the
header, arrays, identities or readback cannot be validated, it looks up the
descriptor's package key in Greyhound's local game package cache. This does not
depend on a map name, a particular district number, fixed process addresses,
known model names, an offline reconstruction script or a user-supplied key list.

## Layout and validation

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

## Provenance and limits

- `PlacementSource`: `live` or `local_package`.
- `District` + `ReferenceIndex`: join key within this map capture.
- `RecordSlot`: runtime array slot for live rows; null for packaged rows.
- `PackageRecordSlot`: source slot for packaged rows.
- `BoundsMin` / `BoundsMax`: captured world bounds, retained without fitting.
- `ReferenceFlagsRaw`: source flags; packaged and runtime values may differ.
- `SplineInstanceIndex` / `RequiresSplineDeformation`: retained; this placement
  export does not supply spline controls or apply their deformation.

The report includes recovered and unresolved district counts, per-district live
failure reasons, package path/key/offset, validation results and range coverage.
Expected failed live reads do not fail the export when that entire district has
been validated from its package. Evidence write failures still fail research
exports. Package recovery does not assert a successful live readback.

Source proxy placements remain in the output. Their runtime visibility and
replacement rules are not decoded. Recovering district XModels does not establish
that every kind of rendered world geometry has been recovered.

## Verification (2026-09-08)

- Release|x64 solution build with command-line PlatformToolset=v143; project
  files unchanged.
- Native live Zoo export: 131,589 placements / 1,988 unique models, 42 placement
  districts, 40 recovered from local packages, zero unresolved; CLI exit 0.
- All 131,589 Zoo model identities, positions, quaternions, scales, bounds and
  spline indices match an independently decoded offline dataset.
- All 41 Zoo packaged placement districts pass the native pure validator.
- Saved Silver: all 12 package districts (35,016 placements) pass the same
  validator. All 26,643 overlapping saved live placements match the packaged
  positions, rotations, scales and bounds byte-for-byte after reference-index
  joining; all 26,643 model name hashes also match. Its 8,373 previously omitted placements are structurally validated;
  those omitted rows have no saved live comparison.
- `tests/cw_district_payload_test.cpp` tests invalid sizes/counts, relocated
  pointers, duplicate/out-of-range indices, nonfinite data, invalid scale/bounds,
  and overlapping/gapped ranges. It also accepts `--package file.bin` or
  `--live references.bin transforms.bin` for saved fixture validation.

The shared path is verified on these two maps, not claimed verified on every
Cold War map or future game build.
