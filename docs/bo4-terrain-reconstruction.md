# From BO4 asset memory to a Radiant terrain patch

[Terrain research](bo4-terrain-research.md) | [Export commands](bo4-terrain-export.md)

This walkthrough follows the measured BO4 terrain path from a live asset to saved
arrays and then to a Radiant `mesh`. It covers terrain; visible world surfaces
and solid brush collision have different owners and layouts. A terrain height
lattice is recoverable. Original editor patches and the selected tessellated GPU
mesh are not encoded by that lattice alone.

## 1. Find the asset and establish the base addresses

Start in [GameBlackOps4.cpp](../src/WraithXCOD/WraithXCOD/games/black_ops_4/reader/GameBlackOps4.cpp):
`LoadAssets`, `ExportTerrainProbe` and the `BO4Sector*` constants. Use the current
build's resolved `DBAssetPools`, not a virtual address from somebody else's run.
The descriptor is `BO4XAssetPoolData`, 0x20 bytes:

| Relative to pool descriptor | Type | Meaning |
| --- | --- | --- |
| +0x00 | u64 pointer | Pool allocation |
| +0x08 | u32 | Asset stride |
| +0x0C | u32 | Capacity |
| +0x14 | u32 | Loaded count |
| +0x18 | u64 pointer | Free-list head |

TerrainGfx is pool **0x98 (152)**. Let `A` be an occupied asset address from that
pool; use its reported stride and validate occupancy rather than treating every
slot as loaded. The name/hash is at `A+0x00`. Record the executable/build, asset
hash, pool bounds and capture time. Addresses are valid only in that process.

| Relative to `A` | Type | Meaning |
| --- | --- | --- |
| +0x10 | u64 | Sector count |
| +0x18 | u64 pointer | Sector array; stride **0x148** |
| +0x88 / +0x90 | u64 count / pointer | Terrain image registry; **48-byte** entries |

Read `S = read_u64(A+0x18) + sector_index*0x148`. Check every span before reading
it and reject truncated reads. Do not infer an array's extent from adjacent
readable memory. A probe is a non-atomic snapshot: repeat identity/count checks
if the map is changing or streaming.

## 2. Walk one sector, then verify the same layout on another

| Relative to sector `S` | Type | Meaning |
| --- | --- | --- |
| +0x48 / +0x50 | u64 count / pointer | Quadtree levels; **16-byte** entries |
| +0x58 | 12 float32 | World-to-local transform: translation then 3x3 rotation |
| +0x88 | 12 float32 | Local-to-world transform, same storage |
| +0xB8 | 6 float32 | Content bounds minXYZ/maxXYZ |
| +0xE0 / +0xE4 | u32 / u32 | Grid-array class / height-and-cutout array slice |
| +0xF0 | u32 | Grid-side marker, **33** |
| +0xF4 / +0xF8 | float32 / float32 | Local grid minimum X/Y |
| +0xFC | float32 | World units per source sample |
| +0x100 / +0x104 | float32 / float32 | Local height bias / height range |
| +0x108 | float32 | Half extent |
| +0x110 / +0x118 | u64 count / pointer | Expanded layer bindings; **0x108-byte** entries |
| +0x138 / +0x140 | u64 count / pointer | u16 weight-slice table |

Probe v49 preserves both full transforms. Earlier `placement[3]` is the first
rotation coefficient, **not a general uniform scale field**. For an unrotated
sector, the world grid origin equals translationXY minus half extent, and should
agree with boundsXY. The height bias is `S+0x100 + translationZ`; **bounds.minZ
is not the height bias**. Check the transform explicitly before using an
axis-aligned formula. Rotated sectors need local-space sampling followed by the
captured transform (or the packager's validated right-angle reindexing).

Each level entry is `{u32 width, u32 height, u64 tiles}` at offsets 0, 4 and 8.
Level 0 is the finest source grid. Tiles have **264-byte** records; tile
`row*width+column` has its u32 participation mask at **+0xA8** and stream-key
pointer at **+0x90**. Retain all 32 mask bits. A tile covers **32 sample intervals**,
so tile width is `32*units_per_sample`, not a fixed 256 units.

To establish a new layout, require the marker, finite transforms, consistent
level dimensions, mask bits within the layer count and tile bounds consistent
with the sampling grid. Test a second sector with a different layer count or
size: a plausible first sector is insufficient evidence.

## 3. Resolve image arrays and decode their bytes

Follow `ExportTerrainProbe`'s `side_arrays[].images` and `height_maps`, then
[package_bo4_terrain.py](../tools/black_ops_4/capture/package_bo4_terrain.py):
`grid_images`, `weight_slice_table` and `package`. Match **format and dimensions**
as well as names; the BC4 weight image can be hash-named. Height/cutout arrays can
be shared by sectors of the same size. Verify their slice against sector +0xE4.
Weight slices use their own table; they do not equal that height-array slice.

For `n` finest tiles across, `W=32*n+4` and used sample side `N=32*n+1`:

| Image | DXGI format | Slice size / addressing |
| --- | --- | --- |
| Height | 56, R16_UNORM | `W*W*2` bytes; LE u16 at `2*(row*W+col)` |
| Cutout | 42, R32_UINT | `(4*n+1)*(8*n+1)*4` bytes; see below |
| Layer weights | 80, BC4_UNORM | `ceil(W/4)^2*8` bytes per layer slice |

For an unrotated sector, use:

```python
x = origin_x + col * units_per_sample
y = origin_y + row * units_per_sample
z = world_height_bias + height_u16[row, col] * z_range / 65535.0
word = cutout_u32[row >> 2, col >> 3]
solid = (word >> ((col & 7) + 8 * (row & 3))) & 1
```

Rows run +Y and columns +X. The last three rows/columns are padding, not extra
terrain. Compare them with the last used row/column before inferring an offset.
Cutout zero means a hole. Test the bit orientation against an asymmetric hole;
a transposed map can look plausible on broad flat areas.

Each BC4 block covers 4x4 texels: endpoint bytes `a,b`, then six little-endian
bytes containing sixteen 3-bit indices, row-major. If `a>b`, palette entries
2..7 interpolate `(6*a+b)/7` through `(a+6*b)/7`. Otherwise entries 2..5 use
fifths and entries 6/7 are 0/255. Divide the selected value by 255. Preserve
independent slice values; do not normalize their sum. Compare a second decoder
at block interiors and edges before attributing borders to material blending.
[bo4_native_source.py](../tools/black_ops_4/capture/bo4_native_source.py),
`BC4Array` and `Sector`, provides the reusable reader and checks.

## 4. Map layers to original materials and weights

Let `L = read_u64(S+0x118) + slot*0x108`:

| Relative to expanded layer `L` | Meaning |
| --- | --- |
| +0x00 | u64 material pointer |
| +0x08 | Pointer into the per-layer side table |
| +0x10 | Eight float32 values: two UV rows |
| +0x34 | u32 index into the sector weight-slice table |
| +0x40 | Start of the 196-byte source parameter block |
| +0x60 | Per-layer flags inside that source block |

Read `slice = u16[weight_table + 2*index]`. **4094 is constant one; 4095 is
constant zero.** Other values index the shared BC4 array. In a packaged sector,
`local_slice = shared_slice - layer_weights.array_slice_base`; honor
`layers[].weight_slice` and `slice_to_layer_slot`, not a universal `slot-1` rule.
The old simple mapping is only a compatibility fallback for older probes.

Material layout is defined in
[GameBlackOps4AssetLayouts.h](../src/WraithXCOD/WraithXCOD/games/black_ops_4/reader/GameBlackOps4AssetLayouts.h):
312-byte material, name hash +0x00, image-table pointer +0x38, image count u8
+0x130. Image bindings are **32 bytes**, image pointer +0x00 and semantic hash
+0x08. The current `BO4GfxImage` uses loaded bytes pointer +0x18, name hash +0x20,
stream-mip pointer +0x30, loaded byte count +0x60, format +0x64, u16 width/height
+0x68/+0x6A and mip count u8 +0x6C. Verify the current structure for your build;
the file also retains an explicitly different historical image layout.

Resolve names with the low 60 hash bits and the selected name database. Keep
unknown semantics by raw hash. Use the packager's `SEMANTICS` mapping; old reader
comments calling reveal textures roughness are not a semantic authority.

The separate **112-byte renderer layer record** is not the 264-byte source
binding. Its UVs occupy +0..31, shared weight slice +32, flags/displacement half
+52 and reveal contrast/exponent bytes +72/+73. See `runtime_record()` for all
packed fields. Match uploads by exact UV bytes **and expected shared slice**.
When uploads are absent, [bo4_terrain_layer_source.py](../tools/black_ops_4/capture/bo4_terrain_layer_source.py)
reconstructs them from expanded inputs and image descriptors and checks against
observed uploads where available. Preserve reconstructed-versus-observed provenance.

The 48-byte terrain registry entry has image pointer +0, format +8, array slot
+20 and minimum mip +24. `image_registry()` resolves these into the native packed
texture descriptors. Guessing them from a material name loses per-layer state.

## 5. Inspect a saved package at one coordinate

Generate a source package using the [documented CLI](bo4-terrain-export.md#cli).
Keep the raw probe as well as `package/capture/terraingfx.json`. From the checkout,
save the following as a temporary Python script and pass the package root:

```python
import json, sys
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path('tools/black_ops_4/capture').resolve()))
from bo4_native_source import NativeCapture

source = NativeCapture(Path(sys.argv[1]))
s = source.sectors[0]
row, col = 16, 16  # replace with a point inside the tile under investigation
x, y = s.origin + np.array([col, row]) * s.cell
print('sector, XY, Z, solid:', s.index, x, y,
      float(s.sample_height(row, col)), bool(s.sample_solid(row, col)))
for layer in s.layers:
    k = layer['slot']
    print(k, layer['material'], 'raw weight=', float(s.sample_weight(k, row, col)),
          'UV=', s.uv(k, x, y), 'runtime=', layer.get('runtime'))
```

This reader currently accepts the validated unrotated/simple per-sector slice
layout used by Mansion; it deliberately rejects unsupported layouts. The package
can preserve more layouts than this consumer supports. Inspect package exclusions
and schema fields instead of removing those checks to make a new capture load.
A raw weight is not the shader's final reveal-adjusted opacity.

## 6. Construct the Radiant surface from those samples

For a first experiment, choose one tile and retain all 33x33 source samples.
Make control attributes `[X,Y,Z,R,G,B,A,U,V,LMU,LMV]`. At each control, calculate
world position as above and texture UV using the layer's two rows:

```text
u = m0*x + m1*y + m2*z + m3
v = m4*x + m5*y + m6*z + m7
```

The measured layers are planar (`m2=m6=0`); verify before dropping the Z terms.
CAST uses normalized repeat UVs. The Radiant writer uses texture-space UVs:
`U=u*image_width`, `V=v*image_height`. Keep original material identity, set RGB
to 255 and use `round(255*raw_weight)` for that layer's vertex alpha. A base layer
uses 255. This preserves inputs; it does not itself implement BO4 reveal blending.

Split the grid around holes. The conservative handoff keeps a cell only when all
four corner solid bits are set; report that policy separately from the native
per-pixel cutout test. Keep shared boundary coordinates identical. For each
layer, preserve its independent alpha and skip only surfaces whose alpha is
zero throughout. Overlay materials must support vertex alpha; `_blend` is an
alias using the same source images, not a new baked texture.

A BO3 patch is a `mesh` block inside worldspawn, with this structure:

```text
{
mesh
{
contents nonColliding;
toolFlags;
mc/original_material_name
lightmap_gray
ROWS COLS 0 8
(
v X Y Z c 255 255 255 A t U V LMU LMV
...one vertex per column...
)
...one parenthesized group per row...
}
}
```

Wrap it in `iwmap 4` and a worldspawn entity. For increasing +X/+Y source arrays,
the established writer reverses the column axis once for outward winding. Check
a single sloped cell in Radiant/compiler output before exporting a whole map.
Do not flip geometry, UVs or masks independently. Lightmap coordinates need their
own chart; they are not source texture UVs. Small separate layers may need an
explicit target-material/depth policy to avoid coplanar flicker; geometry offsets
are an approximation, not a recovered BO4 field.

In the separate TerrainReconstructor checkout, inspect
`tools/core/bo4_native_capture.py` (`Sector`),
`tools/bo3/bo4_native_prefabs.py` (`grid_for`, layer fitting),
`hole_patch_layout.py` (cutout-aware regions) and
`tools/bo3/coalesce_terrain_patches.py` (`serialize`). Those are the downstream
implementation points for fitting and serializing patches. Count duplicated
edges and every overlay when measuring visual controls. Count colliding controls
separately. Greyhound does not impose either budget.

Collision should use the stored clipmap heightfield where available; its pointer
chain and surface palette are in [Terrain collision](bo4-terrain-research.md#terrain-collision).
If you fit collision from render heights instead, label it derived and measure
maximum/RMS height error on solid samples. A control-count cap is not an accuracy
check. Do not derive collision surface types from the strongest visible mask.

## 7. Turn observations into a reusable finding

For each experiment record input hashes, sector/tile coordinates, original bytes,
field interpretation, reconstruction parameters and what failed. Change one
hypothesis at a time and test it on a second sector/map. Useful checks are:

- Slice bounds, payload length and sector-grid agreement before decoding.
- Padding, corner locations and asymmetric cutouts for orientation/registration.
- UV/weight-table byte matches for runtime record identity.
- Mask participation versus nonzero BC4 samples; mask +4 versus displacement +8.
- Shared patch edges, unchanged material references, alpha ranges and cell coverage.
- Sampled height error after fitting; report the worst coordinates, not only RMS.
- Actual Radiant load, BO3 compile, compiled geometry and gameplay as separate steps.

Run `verify_bo4_terrain_package.py PACKAGE --placements STATIC_MODELS_JSON` for
registration evidence and `python -m pytest tests/black_ops_4/capture -q` for the
repository regressions. Neither proves a new patch map compiles. Native image
mips, sampler state, shader reveal, tessellation LOD and lighting remain separate
questions from recovering the source height lattice. Publish small synthetic
fixtures and commands alongside a finding, rather than personal captures or only
an export inventory.
