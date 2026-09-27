# TerrainGfx reference: Cold War and Black Ops 4

[Documentation index](README.md) | [Cold War terrain export](cw-terrain.md) | [BO4 terrain research](bo4-terrain-research.md) | [Library preview](library-preview.md)

This page is a map of the TerrainGfx findings in this repository. It separates
what the game data and saved captures establish from what the lightweight
Greyhound preview assumes. Capture files and game assets are not shipped here.
The offsets, formats and examples below apply to the game builds measured by
this fork; check a new build or map before treating them as universal.

## What TerrainGfx contains

TerrainGfx is a live rendering asset. Greyhound finds it in the game's asset
pool, reads its image and sector references, and can show a coarse terrain
preview. It is **not** a complete map scene: placed models, collision, decals,
entities and effects have separate capture or export paths. The current preview
does not parse a `.d3dbsp` file. In this codebase, `maps/.../*.d3dbsp` paths can
also be used to resolve map hashes; that use alone says nothing about which
payloads a BSP contains. See [CW map-name lookup](../src/WraithXCOD/WraithXCOD/shared/CWRadiantExport.h),
[CW placements](cw-placements.md), [BO4 workflows](bo4.md) and
[BO4 terrain/collision research](bo4-terrain-research.md).

| Route | Cold War | Black Ops 4 |
| --- | --- | --- |
| TerrainGfx pool | `0xB1`; measured header size `0x128` | `0x98`; live headers in the examples below are 184 bytes |
| Normal Terrain export | Baked model packages with separate material images | No baked model package route; use source capture |
| Raw source | Terrain source capture and sealed evidence | Mode 0 TerrainGfx measurement probe |
| Library Preview | One coarse map grid using the live combined color and R16 height images | A coarse grid per sector, with source layer color maps and weights |

Pool discovery and asset registration are in the
[CW reader](../src/WraithXCOD/WraithXCOD/games/cold_war/reader/GameBlackOpsCW.cpp)
and [BO4 reader](../src/WraithXCOD/WraithXCOD/games/black_ops_4/reader/GameBlackOps4.cpp).
The native [preview builder](../src/WraithXCOD/WraithXCOD/assets/preview/PreviewData.cpp)
feeds the [WebGL viewer](../src/WraithXCOD/WraithXCOD/ui/preview.js) through
the [UI bridge](../src/WraithXCOD/WraithXCOD/ui/native/UiBridge.cpp).

## Cold War layout and preview

The measured header points to a mapping root at `+0x10` and an image-pointer
table at `+0x38`, with matching counts at `+0x30` and `+0x40`. The mapping root
contains origin XY at `+0xE8/+0xEC`, cell size at `+0xF0`, height bias and
range at `+0xF4/+0xF8`, and runtime grid width/height at `+0x100/+0x102`.
The coarse preview uses:

```text
world_x = origin_x + grid_x * cell_size
world_y = origin_y + grid_y * cell_size
world_z = height_bias + R16_UNORM_sample * height_range
```

The named `terrain_combined_maps_*_0` image is the preferred color source.
When names are unresolved, the preview looks for a map-sized BC3 image
(format 78) immediately followed by a BC5 normal image (format 83 or 84).
It reads an R16 image (format 56) at either the mapping dimensions or
`(2 * width - 1) × (2 * height - 1)`. The preview **assumes** the latter
spans the same XY area at twice the sample density; that registration still
needs an independent render or landmark check. The preview samples at most a
128 × 128 cell grid and displays the selected **source combined color image**.
It does not run the Cold War composition shader. The displayed image is at most
1024 pixels per side. See [the implementation](../src/WraithXCOD/WraithXCOD/assets/preview/PreviewData.cpp)
and [image decoding](../src/WraithXCOD/WraithXCOD/assets/preview/PreviewImage.cpp).

### Live `zm_tungsten` observation

`terraingfx_1eb4c22555338af` has 60 image bindings. Its mapping root reports
2048 × 2048 samples, origin `(−65536, −65536)`, 64 units per mapping cell,
and an XY extent of 131008 units. Binding 0 is an R16 4095 × 4095 image;
bindings 5–6 are a 2048 × 2048 BC3/BC5 pair, and bindings 35–36 are another
2048 × 2048 BC3/BC5 pair. The name database did not resolve either pair as
`terrain_combined_maps_*` during the live check. The preview chooses the
first BC3/BC5 pair and samples the R16 image across the same XY span.

The live `assets preview` packet passed structural verification with 16,641
vertices, 32,768 triangles, one 1024 × 1024 displayed color texture and no
missing texture. This verifies that the asset can be read and displayed. **The
first-pair choice and visual registration on `zm_tungsten` have not been
independently checked against an in-game reference render.** A person viewing
the preview could not confidently judge whether it was mapped correctly.
Treat this route as a coarse study preview, not verified color/height parity.

For a high-fidelity CW output, [the separate baked-model workflow](cw-terrain.md)
uses the captured composition shader, native material records, controls and
distortion. Its raw source path records evidence and integrity separately.
The [native export](../src/WraithXCOD/WraithXCOD/assets/CoDAssets.cpp),
[research capture](../src/WraithXCOD/WraithXCOD/games/cold_war/reader/GameBlackOpsCW.cpp),
[bake](../tools/cold_war/terrain/bake.py) and
[finalizer](../tools/cold_war/terrain/finalize.py) are the main entry points.

## Black Ops 4 layout and preview

The BO4 TerrainGfx header gives a sector count at `+0x10` and a sector-array
pointer at `+0x18`. The measured sector stride is `0x148`. A sector selects
its height, cutout and weight image triple; sectors can share image arrays and
select different slices. For `n` tiles across, the captured image layouts are:

| Source | Format | Dimensions | Preview use |
| --- | --- | --- | --- |
| Height | R16, format 56 | `(32n + 4)²` | Height, with sector bias/range |
| Cutout | R32, format 42 | `(4n + 1) × (8n + 1)` | Skip hole cells |
| Layer weights | BC4, format 80 | `(32n + 4)²` per slice | Opacity for each layer |

The useful height grid is `32n + 1` samples wide; the last three image rows
and columns are padding. Sector XY placement, units per sample, right-angle
rotation, image slice and layer tables come from the live sector records. The
preview builds up to 128 × 128 cells per sector and retains holes at that
detail. It samples each layer material's `colorMap` using its UV transform and
composites the BC4 weights. A weight sentinel of 4094 means a full base layer;
4095 disables the layer. See [the preview implementation](../src/WraithXCOD/WraithXCOD/assets/preview/PreviewData.cpp)
and [the source packager](../tools/black_ops_4/capture/package_bo4_terrain.py).

The BO4 preview colors are an **approximation**. It does not replay the game's
height blending, tints, soft-light operations, far tiling, detail maps or
displacement. The [BO4 research guide](bo4-terrain-research.md#the-terrain-shaders-cutout-and-blending)
documents those shader findings and the independent package verification.
It also covers collision, volume decals and streamed tile meshes; none of
those makes the Library Preview a complete map scene.

### Live BO4 checks

| Loaded map / asset | Packet result | Visual evidence |
| --- | --- | --- |
| `zm_white` / `terraingfx_1173ca83f06a352` | 2 sectors, 17 source layers, 33,282 vertices, 64,318 coarse triangles, no missing textures | Greyhound screenshot showed the large backdrop and small inset sector with cutouts. [Saved-capture cross-check](bo4-terrain-research.md#cross-check-zm_white) describes the sector geometry. |
| Blackout / `terraingfx_1ed55a7a591112c` | 27 sectors, 477 source layers, 449,307 vertices, 753,134 coarse triangles, 25,212,660-byte verified packet, no missing textures | User confirmed the live viewer worked; no shader-parity comparison was made. |

Packet verification checks byte ranges, indices, finite geometry and metadata.
It does not establish that a game shader would produce the same pixels. The
BO4 sector and shader evidence comes from live measurements and saved captures;
use [the full BO4 guide](bo4-terrain-research.md) for the verification method,
shader hashes, equations, caveats and capture-specific counts.

## Open checks

- Compare `zm_tungsten` landmarks and surface heights with the game or an
  independent capture. The first and second BC3/BC5 pairs may have different
  roles; the preview currently selects the first when their names are unknown.
- The CW coarse preview does not apply cutout masks or replay the material
  composition shader. The baked export has a separate, more detailed path.
- The BO4 coarse preview does not match the full shader pipeline. A valid
  packet and a recognizable map shape do not prove pixel or displacement parity.
- TerrainGfx alone does not supply placed models or a complete map scene.

## Reproduce and inspect

With the game running and a map loaded, list the actual terrain asset name
before requesting a preview. Use the executable and paths for your installation:

```powershell
$gh = '.\bin\cli\Greyhound-cli.exe'
& $gh assets list --type terrain --json
& $gh assets preview --type terrain --name 'EXACT_NAME_FROM_LIST' --json
```

`packet_verified: true` confirms the packed preview is structurally valid.
Inspect `preview.bounds`, `meshes`, `triangleCount`, `sourceLayerCount` and
`colorSource`, then compare the on-screen view with a known map reference.
The preview is live and does not require a saved terrain export.

For archived evidence, use [CW raw source capture](cw-terrain.md#raw-source-and-diagnostics)
or [BO4 mode 0](bo4.md#capture-modes). BO4's
[packager](../tools/black_ops_4/capture/package_bo4_terrain.py) and
[verifier](../tools/black_ops_4/capture/verify_bo4_terrain_package.py)
work on the saved probe; the
[CAST builder](../tools/black_ops_4/capture/build_bo4_terrain_cast.py)
is a separate offline output path. The source package preserves image
identities, UVs, weights, heights, cutouts and hashes, rather than asserting
that the coarse viewer reproduces the game's shader. See
[capture contracts](capture-research.md) for how to judge completeness.

## Key source references

| Question | Reference |
| --- | --- |
| How are TerrainGfx assets found? | [CW reader](../src/WraithXCOD/WraithXCOD/games/cold_war/reader/GameBlackOpsCW.cpp), [BO4 reader](../src/WraithXCOD/WraithXCOD/games/black_ops_4/reader/GameBlackOps4.cpp) |
| How is a live preview constructed? | [PreviewData.cpp](../src/WraithXCOD/WraithXCOD/assets/preview/PreviewData.cpp), [PreviewImage.cpp](../src/WraithXCOD/WraithXCOD/assets/preview/PreviewImage.cpp) |
| How does the viewer receive and draw it? | [UiBridge.cpp](../src/WraithXCOD/WraithXCOD/ui/native/UiBridge.cpp), [preview.js](../src/WraithXCOD/WraithXCOD/ui/preview.js), [Library preview contract](library-preview.md) |
| Where is CW source captured and baked? | [CoDAssets.cpp](../src/WraithXCOD/WraithXCOD/assets/CoDAssets.cpp), [GameBlackOpsCW.cpp](../src/WraithXCOD/WraithXCOD/games/cold_war/reader/GameBlackOpsCW.cpp), [CW terrain guide](cw-terrain.md) |
| Where is BO4 measured and packaged? | [GameBlackOps4.cpp](../src/WraithXCOD/WraithXCOD/games/black_ops_4/reader/GameBlackOps4.cpp), [BO4 research guide](bo4-terrain-research.md), [package_bo4_terrain.py](../tools/black_ops_4/capture/package_bo4_terrain.py) |
| What tests cover the saved decoders? | [CW terrain tests](../tests/cold_war/terrain/), [BO4 capture tests](../tests/black_ops_4/capture/) |
