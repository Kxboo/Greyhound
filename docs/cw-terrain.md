# Cold War terrain discovery and decoding

Cold War terrain is a live `TerrainGfx` asset. Greyhound locates its record in
the running game's asset pools, follows its mapping and image pointers, and
decodes height and surface data from the loaded map. The offsets below describe
the Cold War build validated by this fork; a different build needs its own
layout and shader checks.

## Finding the TerrainGfx asset

1. After attaching to the game, `GameBlackOpsCW::LoadOffsets` locates the
   `DBAssetPools` directory. It first tries known module-relative offsets and
   verifies them against the first XModel hash and expected animation, model,
   and image header sizes. If those offsets fail, it scans for the pool and
   string-table references and applies the same checks.
2. Each pool descriptor is 0x20 bytes. TerrainGfx is pool `0xB1`; its descriptor
   supplies the pool pointer, record size, capacity, loaded count, and free-list
   head. The loader walks the allocated capacity because occupied records can
   occur beyond the loaded count when the pool has holes.
3. For each record, the first eight bytes hold a name hash. A zero value or an
   in-pool pointer denotes an unused slot. Greyhound masks the hash to 60 bits,
   resolves it through the name database when possible, and otherwise lists it
   as `terraingfx_<hash>`. The record address and size become the terrain
   asset's `AssetPointer` and `AssetSize`.

This is a read of the loaded game, so the desired map must already be loaded.
The loader bounds the terrain pool to 512 MiB and requires a complete pool read
before registering its records. The path is in
[GameBlackOpsCW.cpp](../src/WraithXCOD/WraithXCOD/games/cold_war/reader/GameBlackOpsCW.cpp).

## Following the terrain record

The measured TerrainGfx header is 0x128 bytes. These fields lead to the data
used by the decoders:

| Header offset | Meaning |
| --- | --- |
| `+0x08` | Number of mapping roots in the detailed capture |
| `+0x10` | Mapping-root array pointer |
| `+0x30` | Image-binding count |
| `+0x38` | Image-pointer table |
| `+0x40` | Image-ID count in the live preview |
| `+0x48` | Image-ID table pointer in the detailed capture |
| `+0x110` / `+0x118` | Count and pointer for 96-byte layer image-pointer records in raw source capture |

Each measured mapping-root record is 472 bytes. Its origin X/Y are at
`+0xE8/+0xEC`, cell size at `+0xF0`, height bias and range at
`+0xF4/+0xF8`, and grid width/height at `+0x100/+0x102`. The detailed path
also reads the root's shared grid indices and compares its dimensions with a
separate GPU tile record before trusting the mapping order. It currently
requires an unrotated mapping and a 6144-index shared grid.

Image pointers lead to `BOCWGfxImage` records. Those records identify format,
dimensions, resident pixel data, and streamed mip keys. `LoadXImage` tries
available package mips from largest to smallest, then falls back to the mip
resident in game memory. The detailed capture checks the expected byte count
for each format and rereads headers, mip tables, and live pixels to catch a map
changing during capture. Height and control data require full resolution;
ordinary material source images can use an installed mip up to 1024 pixels.

## Decoding height, holes, and surface color

The Library Preview uses a deliberately coarse interpretation. It looks for a
named `terrain_combined_maps_*_0` BC3 image (format 78), or falls back to the
first map-sized BC3 image followed by a BC5 normal image (formats 83/84). It
chooses an R16 height image (format 56) whose dimensions equal the mapping
grid or are `2 × grid - 1`. The color DDS is decoded through DirectXTex; the
R16 samples are read as unsigned 16-bit values. At most 128 × 128 cells are
shown, using:

```text
X = origin_x + grid_x × cell_size
Y = origin_y + grid_y × cell_size
Z = height_bias + (R16_sample / 65535) × height_range
```

The preview maps a denser height image across the same XY span and displays
the selected combined color image. It does not decode terrain holes or replay
the material composition shader. If names are unresolved, the first BC3/BC5
pair is a heuristic; the live `zm_tungsten` check established that the bytes
can be read, but did not establish which of its two candidate pairs matches
the game's displayed terrain. See
[PreviewData.cpp](../src/WraithXCOD/WraithXCOD/assets/preview/PreviewData.cpp)
and [the TerrainGfx observations](terraingfx-reference.md#cold-war-layout-and-preview).

The detailed path uses more of the native data:

- It reads 316-byte GPU tile records alongside the 472-byte mapping roots.
  Packed fields at tile offset `+300` identify height and hole-mask image
  bindings (14 bits per ID). The height atlas is R16. Tile UV rows and a
  per-tile bias and scale sample that atlas; the mapping translation places
  the result in world Z.
- The hole mask is a 32-bit-per-pixel control image. Its bits expand into a
  `(grid_height + 1) × (grid_width + 1)` solid-vertex mask. A grid cell remains
  solid only when all four corner bits are set. The shared 33 × 33 tile index
  grid is filtered with that mask.
- Mapping origin and cell size place each 33 × 33 tile in XY. Height samples
  are bilinearly interpolated from the full-resolution atlas. Neighboring
  height samples provide the surface normal.
- Material appearance comes from the native layer records, their image
  bindings, height/control textures, recovered distortion image, and the
  composition shader captured from the loaded game. The detailed path checks
  the game build and shader identity before using them. The release's
  `tools/cold_war/terrain/bake.py` consumes those saved inputs and
  `run_composition.exe` runs the captured shader; no game shader is bundled.

These operations are implemented in
[CWTerrainBake.h](../src/WraithXCOD/WraithXCOD/games/cold_war/terrain/CWTerrainBake.h)
and [bake.py](../tools/cold_war/terrain/bake.py). The latter is also present
under `src/WraithXCOD/x64/Release/tools/cold_war/terrain/` in a packaged build.

## Raw source and diagnostics

The raw source capture follows the same TerrainGfx record without assuming
that the coarse preview is a complete decode. It saves the header, image
pointer tables, mapping-root prefix, referenced images, and painted material
slots. It also records related asset-pool headers and bounded candidate arrays
so a reader can audit where a dependency came from. Capture reports distinguish
confirmed reads from speculative pointer follows and record readback checks.
See `GameBlackOpsCW::ExportTerrainResearch` in
[GameBlackOpsCW.cpp](../src/WraithXCOD/WraithXCOD/games/cold_war/reader/GameBlackOpsCW.cpp)
and [capture contracts](capture-research.md).

TerrainGfx describes rendered ground, not the whole map. Collision, placed
models, entities, and independent volume decals live in other asset families.
The preview is an overview, and even the detailed material path has documented
limits: its dispatch constants are reconstructed, bindless sampling is
provisional, weather globals are omitted, and hole borders use the conservative
four-corner rule. Unsupported layouts, shaders, or missing full-resolution
height/control inputs cause a visible failure rather than an invented surface.
