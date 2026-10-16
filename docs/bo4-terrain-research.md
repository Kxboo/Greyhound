# Black Ops 4 terrain and collision research

[Documentation index](README.md) | [BO4 workflows](bo4.md) | [Contributing](contributing.md)

This page describes producer contracts, measured BO4 layouts and remaining
decoder work. Early measurements used `zm_white` (Alpha Omega) and `zm_towers`
(IX); `zm_mansion` (Dead of the Night) exposed additional mask, layer-packing
and sampling distinctions. Validate each finding against the game build and map
you are studying. Historical capture counts are evidence, not format limits.
For export steps, start with [BO4 terrain export versions](bo4-terrain-export.md).

## What Mansion added

The Mansion work corrected assumptions that happened to hold on IX. The most
useful discoveries for another decoder are:

| Finding | Consequence for reconstruction | Implementation/evidence |
| --- | --- | --- |
| Painted layer weights are independent, ordered BC4 masks | Preserve each mask and layer order; do not normalize weights or fabricate a Cold War index map | [Mask reference](#mask-reference) and shader blend rule below |
| Runtime weight indices address shared arrays | Match records using the sector's slice table, then translate to the packaged slice index | [BO4TerrainRuntime.h](../src/WraithXCOD/WraithXCOD/games/black_ops_4/capture/BO4TerrainRuntime.h), `package_bo4_terrain.py` |
| Render-layer and displacement masks differ | Build node +8 from eligible displacement layers, not by copying node +4 | 36 content-matched Mansion upload records; [node masks](#mansion-node-mask-correction) |
| Layer flags are per layer instance, not per material name | Recover missing records from their own expanded inputs; never borrow another sector's flags | [Expanded layer parameters](#expanded-layer-parameters-2026-10-12-verification) |
| Albedo alpha is linear even when RGB is sRGB | Decode RGB only; gamma-transforming alpha changes tint/blend inputs | `test_bo4_texture_color.py` |
| Original mip data and exposed texture-view levels are different evidence | Preserve native DDS mips and use matching captured view limits where available | [Texture views](#captured-terrain-texture-views-2026-10-12) |

These fixes are in the decoder/export tools. They do not establish a selected
in-game draw, exact tessellation LOD, or one-to-one final lighting. Historical
Mansion captures are not shipped with the repository; the reusable synthetic
checks live in [terrain capture tests](../tests/black_ops_4/capture/).

### Mask reference

Several different fields were previously easy to confuse:

| Input | Meaning | Do not substitute |
| --- | --- | --- |
| R32 cutout bits | Whether the terrain surface exists: 0 hole, 1 solid | A painted layer weight or material alpha |
| BC4 layer-weight slice | Independent spatial opacity for one layer, before reveal blending | A normalized weight or a discrete material index |
| Tile/node layer bitmask (+4 in the 124-byte node) | Which layer slots the shader considers | Per-pixel opacity; a set bit is not weight 1 |
| Node displacement bitmask (+8) | Which considered layers may contribute height displacement | The full render-layer mask |
| Material `revealMap` red | Fine detail used to reshape opacity when flag 0x4 is set | Geometric `heightMap`, roughness, or the painted mask itself |
| Albedo alpha | Linear tint interpolation input on the non-height-blend path | sRGB colour or the BC4 painted mask |

The stored weights already represent the shipped painted/rule result. Preserve
them rather than trying to re-run guessed slope/height authoring rules. BO4's
shader consumes the stack in slot order, promotes the first nonzero layer and
then performs sequential blending. Weight sums above one are valid. For example,
two raw overlay weights of 0.5 are not mutually exclusive: ignoring reveal,
sequential lerps leave 0.25 of the base, 0.25 of the first overlay and 0.5 of the
last overlay. Normalizing those inputs would change the result.

Cold War's OMPV/index-map path is a different representation. Reusing its output
folder convention does not justify applying its alpha transforms or index-map
decoder to BO4. A source-material CAST retains material inputs, but its consumer
still needs the BO4 reveal rule to reproduce that shader's blending.

### Mansion node-mask correction

All 36 content-matched Mansion CPU upload records checked on 2026-10-12 satisfy:

```text
displacement_mask = layer_mask & bitset(layer.runtime.flags & 0x20 != 0)
```

All 36 differ from the full layer mask. Examples are render/displacement pairs
`0x3f / 0x30` in sector 0 and `0x3f / 0x16` in sector 1. IX's observed equality
was a property of its layers, not a format rule. `TerrainScene.node_records()`
now uses the restricted mask. The domain shader separately checks flag 0x2;
a layer outside the displacement mask can still attenuate accumulated relief
through `(1 - w)`. Removing it from the render stack would therefore be wrong.
These upload copies establish record contents, not which node a frame drew.

### Diagnose a blend before changing a bake

1. Verify sector placement, cutout orientation, layer order and source identities.
   Tile width is `32 * units_per_sample`; Mansion uses 512- or 1024-unit tiles,
   so the 256-unit IX example is not universal.
2. Check each runtime +32 against the captured slice table. Treat 4094/4095 as
   constant one/zero; subtract `array_slice_base` only for actual texture slices.
3. Inspect BC4 weights, layer participation bits and reveal-map red separately.
   Preserve zero-weight skipping, first-layer promotion and the ordered blend.
4. Check the layer's own flags, UV rows, packed tint, reveal contrast/exponent
   and linear alpha. Record whether each 112-byte record was captured or rebuilt.
5. Compare native mip inputs and matching texture-view limits. Distinguish a
   close-camera approximation from flag 0x400's distance-dependent behavior.
6. Compare the same coordinates and shader outputs before evaluating a lit
   Blender preview. CPU derivatives, sampler bindings, decals and lighting can
   cause differences even when the layer data is correct.

Increasing bake resolution cannot repair a wrong slice, mask, tint or layer
order. Keep the source package for these checks. Radiant patch generation and
collision/non-colliding control budgets belong to **TerrainReconstructor**, not
Greyhound.

## Mansion patch and CAST handoff

The 2026-10-12 Mansion work produced a full five-sector source folder, Radiant
terrain patches and an original-material CAST alternative. This was a downstream
reconstruction experiment, not recovery of authored Radiant patches from BO4.
Greyhound supplies the source/model packages; **TerrainReconstructor remains the
separate application responsible for patch generation and control budgets**.
The numbers below describe this saved handoff, not Greyhound defaults or universal
BO3 compiler limits.

| Saved output | Measured contents |
| --- | --- |
| `source/` | All five sectors, raw height/cutout/weight arrays, layer/shader records and original PNG/DDS textures |
| `zm_mansion_visual_only.map` | 6,497 visual patches, 810,236 controls, explicitly `nonColliding` |
| `zm_mansion_collision_only.map` | 567 collision patches, 47,241 controls, invisible `clip` material |
| `zm_mansion_full_patches.map` | Both sets: 7,064 patches and 857,477 total controls |
| `models/bocw/` | 2,564 CAST models, `_mat_info` and `_images` |
| `zm_mansion_models.map` / `zm_mansion_models_with_collision.map` | Model placements, without / with the collision patches |

The requested downstream budgets were 48,000 collision controls and 1,000,000
non-colliding visual controls. The final visual surface sampled every third
native height-grid sample while retaining cutout edges. Collision used a coarser
shared bilinear surface with an 18-source-sample step. Neither surface includes
runtime tessellation displacement. Cutouts use a conservative four-solid-corner
rule; the output is an approximation of the source terrain, not exact draw geometry.

Visual patches retain source UVs and independent vertex-alpha fields. The parsed
CAST surfaces use the same material references as the patches. `_blend` aliases
reuse original source images; no composited terrain textures or baked lighting
were created for this handoff. Material identity agreement does not establish
that BO3 or a CAST importer reproduces BO4's reveal blending.

The saved `validation.json` records 756 matching source-file hashes, 156 matching
image-file hashes, all 2,564 CASTs parsed, matching patch/CAST material references,
and structural validation of the three patch maps. It explicitly records
`compiled: false`. Collision's maximum sampled height error against the raw source
was **450.36 game inches**, with per-sector RMS errors of **15.97–55.13 inches**.
Meeting the requested control budget therefore did not establish usable gameplay
collision. Further fitting and in-engine testing are needed before treating that
collision as accurate.

For a similar handoff, retain the complete source folder containing `capture/`
and `materials/` and select that folder in TerrainReconstructor. Import the original
materials from `materials/superterrain_materials.json` and its image metadata.
Generate and report visual/collision outputs separately, including control counts,
cutout handling and height errors. Use either the visual patch set or the CAST
placement set; avoid duplicating visual surfaces or adding collision twice.
Keep source-world placement separate from any map-specific alignment offset.

The saved Mansion report and assets are local research outputs, not repository
fixtures or downloadable sample content. These historical counts do not describe
every new export. Recheck each new handoff and distinguish structural validation,
Radiant loading, BO3 compilation and gameplay verification.

## Terrain source packaging

[package_bo4_terrain.py](../tools/black_ops_4/capture/package_bo4_terrain.py)
turns any map's mode 0 terrain probe (`terraingfx_probe.json`, schema v45–v49)
into a `superterrain-bo4-source-package-v1` package. Probe v46 adds the runtime
layer records and v48 the terrain shaders; `--emulate` needs both.
[verify_bo4_terrain_package.py](../tools/black_ops_4/capture/verify_bo4_terrain_package.py)
then checks that package:

```powershell
$probe = '<mode 0 capture>\_source\terraingfx_probe.json'
$output = '<path to a new source-package folder>'
python tools/black_ops_4/capture/package_bo4_terrain.py $probe $output
python tools/black_ops_4/capture/verify_bo4_terrain_package.py $output --placements '<placements run>\static_models.json'
```

The packager runs for the [BO4 terrain export versions](bo4-terrain-export.md). The verifier remains an explicit offline check; the legacy raw diagnostic route does not package its output.

### Finding each sector's files

The packager reads per-sector files from the probe instead of fixed names. A
sector's image table can describe shared arrays grouped by sector size:

| Image | Format | Size (n = tiles across) |
| --- | --- | --- |
| `terrain_height_maps_<i>` | R16 | (32n+4)² |
| `terrain_cutout_maps_<i>` | R32 | (4n+1) × (8n+1) |
| Layer weights (hash-named) | BC4, one slice per non-base layer | (32n+4)² |

The packager resolves height/cutout array slices from the sector's size group,
and weight slices from its side array at +0x138. It writes sector-local files
while retaining the shared-array mapping. Dimensions must agree. Probe v49
preserves full transforms for supported right-angle rotations; sectors whose
rotation cannot be recovered are excluded and reported, not silently exported
unrotated. Source packaging support does not imply that every model consumer
supports rotated sectors.

### Verified conventions

Measured on zm_white (2 sectors, n = 128 and 32) and zm_towers (1 sector, n = 32):

- **Heights:** `z = height_bias_world + sample · z_range / 65535`.
- **Grid:** sample[row][col] sits at `world_xy_origin + (col, row) · units_per_sample`.
  Rows run +Y and columns run +X.
- **Padding:** only 32n+1 samples are used. On zm_white, rows and columns
  32n+1 to 32n+3 repeat 32n, which puts sample 0 at the origin.
- **Layer weights (these two maps):** BC4 slice k belongs to layer slot k+1. Slice k is nonzero
  in exactly the tiles whose layer mask has bit k+1: 99.9–100% agreement on
  every slice of every sector, and the declared slot always matches best.
- **Surface props:** props within 40 units of the surface rest on it. That
  filter matters because many props are in underground sections below the
  terrain. Props over a hole cell are also left out, under each candidate
  mapping's own reading of the cutout: they stand on whatever the hole makes
  room for, not on this sector.
  - zm_towers: under the declared mapping, 23.0% of 1,409 props are within 1.5
    units of the surface. The best flipped or transposed mapping reaches 14.3%.
    Without the hole filter the figures were 14.9% of 2,397 against 10.2%.
  - zm_white sector 1: 11.5% of 6,056 props, against 9.6%.
  - zm_white sector 0 is uninformative. Its only holes are sector 1's
    footprint, and no prop outside them is within 40 units of its surface.
  - Scaling heights by 0.9 or 1.1 drops the fraction to 2–3%.
  - Props can only pin xy registration to within about ±2 samples, because the
    terrain is smooth. The padding test on zm_white is the exact evidence.

The verifier repeats all of these checks for each map and writes
`terrain_verification.json`. A check with too little evidence is reported as
uninformative rather than passed; zm_towers' flat edges are one example.

### The terrain shaders: cutout and blending

The layer materials carry only model passes. The terrain shaders are held by
the renderer, so they were found by scanning live zm_towers memory for DXBC
containers (4,321 unique shaders).

- **The terrain vertex shaders** take an 8-byte vertex (`v0.xy`) plus a tile id
  (`v1.x`). They read three structured buffers: the tile (stride 32), the
  transform (64) and the sector record (124).
  - They sample height from one of four `texture2darray` resources. The array
    is picked by sector record +116 >> 30; the slice is +112 >> 20.
  - The simplest one, depth-only `4cfe90cbd96a2590`, has no cutout test.
- **The terrain pixel shaders** read the same sector record.
  - The four variants that `discard` also declare four
    `texture2darray (uint)` resources: the cutout arrays, parallel to the
    height arrays.
  - The variants without cutout arrays have no discard.
  - `a9b9e1f172b6f838` is the smallest discard variant.

**Cutout.** The pixel shader:

1. Takes the sector uv (rows at sector record +56 and +72).
2. Computes `p = uint(uv · (8·W − 7, 4·H − 3) − 0.5)`, where W × H is the
   cutout size in words, so both factors are 32n+1.
3. Loads word `(p.x >> 3, p.y >> 2)` and tests bit `(p.x & 7) + 8·(p.y & 3)`.
4. Runs `discard_z`: **bit 0 is a hole, bit 1 is solid.**

The uv spans 32n+1 samples: the sector record's uv row scale is
1/(ups·(32n+1)) (1/8200 on zm_towers). The height arrays' constant is
`(1028, 1028, 1025/1028, 0)`, which is width, height, uv scale and bias. So
`uv·(32n+1) − 0.5` is exactly sample i at sample i, and bit (i, j) decides the
cell from sample (i, j) to (i+1, j+1). The cutout uses the same grid and
orientation as the heights.

The data agrees with the shader:

- The declared addressing is the most spatially coherent one.
- Holes are 1.5–4.8% of samples.
- On zm_white sector 0, hole samples have a median height of −77, against +6
  for solid samples: terrain is sunk under the holes.

**Blend rule.** Layers are composited in ascending slot order, starting from
grey 0.05:

```
color = lerp(color, layer_color, w')
```

- The layer weight `w` is set by the 112-byte runtime layer record's +32 field:
  - a BC4 slice index samples that slice;
  - 4094 means always 1 (the base layer, slot 0);
  - 4095 means always 0.
- The first layer whose sampled `w > 0` is drawn at `w' = 1`.
- Otherwise `w' = w`, unless the layer's flag 0x4 (record +52) enables height
  blending. In that case, with contrast `c` and exponent `e` taken from bytes
  0 and 1 of +72 as u8/255:

```
x  = sat(0.998·w + 0.001)
lo = sat((1−x) − c·x^e)
hi = sat((1−x) + c·(1−x)^e)
w' = max(sat((h − lo) / (hi − lo)), sat(100·(w − 0.99)))
```

  - `h` is the layer's blend-height texture.
  - Flag 0x400 fades h toward 0.5 with distance (see [far tiling](#far-tiling)).
- Flag 0x1 selects textured albedo. Without it, the layer multiplies by a tint
  (`lerp(color, color·tint, w')`).

The weights are independent opacities, not a partition: per-sample sums reach
3–5. The live records on zm_towers match the package:

- Slot 0 is 4094; slots 1–5 are slices 0–4.
- The uv matrices equal `uv_matrix_2x4`.
- Slots 2–5 set flag 0x4 with c = e = 127/255. Their material constants hold
  0.5, 0.5 at floats 7–8.
- Slots 0–1 do not height-blend.

**Runtime layer records (probe v46).** Nothing in the terrain asset points at
the records; they are renderer upload copies. So the probe finds them by
content:

- It scans writable memory for each sector's layers as consecutive 112-byte
  records.
- A record matches when its uv rows (+0, +16) equal the asset's layer uv
  bit-for-bit, and its +32 equals the expected weight slice: 4094 for the base,
  the sector's captured slice-table entry for slot k. The earlier `k-1`
  assumption only held for the simple unshared arrays. +32 addresses the shared
  BC4 array; a packaged sector-local file uses `slice - array_slice_base`.
  4094/4095 remain constant one/zero, never array indices.
- Ring copies are grouped by content. The most frequent is dumped to
  `sector<i>_runtime_layers.bin` and decoded under `runtime_layer_records` in
  `terraingfx_probe.json`.

On zm_towers the probe found 9 copies, all identical; zm_white also has 9 per
sector. All sectors share one t14 buffer: zm_white's sector 1 records follow
sector 0's, and the shaders add a per-sector base to the layer index (the
domain shader's `and r0.w, r4.x, 0xFFFF`). The packager decodes each record
into `layers[].runtime`:

- the flags;
- the height-blend contrast and exponent;
- the reveal uv scale;
- the tint, which is three truncated halfs (bits 16–25 of +76, and bits 22–31
  of +80 and of +84, each shifted up 6). zm_towers slot 1's tint is
  (0.9375, 0.906, 0.844); its material constants hold (0.939, 0.918, 0.873).

The height-blend `h` is the layer's `revealMap`, red channel.

**Layer colour.**

```
layer_color = albedo.rgb · lerp(1, tint, a)
```

- `a` is 1 for height-blend layers and albedo.a otherwise.
- The tint the shader uses is the record's truncated half, not the material
  constant it was packed from. The shader itself extracts the 10 bits.
- Flag 0x300 (either bit) swaps the multiply for a Pegtop soft light. Every
  captured terrain pixel shader (`457b8be2b884842c`, `b9dc6d47c91e8bfa`,
  `a8f836d4adb17031`, `a9b9e1f172b6f838`) has the same 32 unrolled copies of
  it:

  ```
  soft(base, top) = (1 − 2·top)·base² + 2·top·base
  layer_color     = lerp(albedo.rgb, soft(albedo.rgb, tint), a)    0x100
  layer_color     = lerp(albedo.rgb, soft(tint, albedo.rgb), a)    0x200 set (swapc)
  ```

  A tint of 0.5 leaves the albedo unchanged. Values below 0.5 darken it and
  values above brighten it, so zm_white's base tint (0.406, 0.328, 0.219)
  darkens and warms the rock. Untextured layers (flag 0x1 clear) never reach
  this code; they only multiply the colour accumulated so far.
- Flag 0x400 adds distance tiling.
- Flag 0x10 (metal) samples a metal mask `m`. The layer colour is multiplied
  by `1 − m`, and the layer's F0 is `lerp(0.04, metal_rgb, m)`. Other layers
  have an F0 of 0.04.
- Flag 0x80 adds a detail normal map at its own uv scale (two halfs at +40),
  with a strength in byte 2 of +72.
- zm_towers sets none of these flags; zm_white sets 0x80, 0x100 and 0x400.
  - The CAST builder's Python layer loop runs the soft light. It bakes far
    tiling as a nearby camera sees it, where the flag changes nothing.
  - It still refuses metal and untextured layers rather than approximating
    them, since neither map uses them.
  - The shader replay below runs every path.

### Expanded layer parameters (2026-10-12 verification)

`bo4_terrain_layer_source.py` reconstructs the 112-byte shader record from the
captured 264-byte layer, rather than inferring a material constant-buffer layout.
The native preparation routine at RVA `0x3CB4450` copies a 196-byte block from
layer `+0x40`, inserts the sector weight slice, and resolves eight texture
descriptors through `0x3CBFDF0`. The packer is `0x3CBF0B0`. Their saved bytes
were verified against the running executable and executed only in an offline
CPU emulator. All 17 Mansion and six IX captured records match all 112 bytes.
The Python decoder also matches 24 native prepared Mansion layers and 64 native
packing boundary vectors. Ground-cover overrides require an additional runtime
setting and are explicitly unsupported by this source reconstruction path.

Flags at layer `+0x60` belong to the individual layer. In Mansion, the same
material has different `0x400` far-tiling flags in different sectors. Copying
flags from a material or technique-set donor is therefore invalid. The four
corrected donor records are (sector,slot) `(3,1)`, `(3,2)`, `(4,0)`, `(4,1)`.
Their missing uploads are reconstructed from their own captured expanded inputs
and image descriptors; they are not claimed as observed runtime uploads.

Half conversion truncates mantissa bits and clamps the exponent as BO4 does;
it must not use IEEE round-to-nearest conversion. Albedo sRGB conversion applies
only to RGB; alpha remains linear. Keep per-layer source values and native mips.
Selected shader path, bound sampler/filter/MaxLOD state, and in-game frame parity
remain distinct verification questions. Regression vectors are in `tests/black_ops_4/capture/fixtures/terrain_expanded_native_oracle.json`.

### Captured terrain texture views (2026-10-12)

Read-only Mansion D3D11 object metadata establishes texture/SRV mip counts:
BC1 sRGB 1024/2 slices/9 mips; BC4 1024/39/9; BC7 UNORM
2048/17/10; BC7 sRGB 2048/12/10. These resources end at 4x4.
The unused 8x8 BC3 fallback is a separate 2D view with four mips to 1x1.
Texture descriptions and SRV descriptions agree; all MostDetailedMip values
are zero. Original DDS files may retain additional 2x2/1x1 package tails.

`capture/terrain_sampling.json` is optional evidence for a particular asset
and SHA-256 of its ordered 112-byte layer records. The replay validates those
inputs and applies the recorded view mip counts before subtracting each image's
array mip offset. Source texture files are preserved. A missing profile retains
legacy behavior; these Mansion counts must not be imposed on other maps.

The engine sampler cache at RVA 0xBFEA920 and constructor at 0x34F1580 were
identified. Twenty-nine cache entries have byte-exact offline descriptor
reconstruction. This identifies available filter/address/anisotropy/LOD settings,
but does not identify a terrain draw's bound sampler slots. The replay's sampler
binding assumptions and anisotropic-filter approximation remain limitations.
No graphics API is invoked inside BO4 to read these descriptions.

### Terrain material sampler and GPU verification (2026-10-12)

The eight captured terrain material recipes bind PS/DS `s1` through native
argument hash lookup: raw word `0x4012 & 0x3fff` becomes sampler state `0x12`,
trilinear wrap with zero bias. Offline native binder execution checked 160
methods and 96 sampler calls. The graph connects the created G-buffer PS
`d437ccb01fe95d61` with DS `89585f99be39cd7f` in the tessellated recipes.
These are recipe/header links, not proof of a selected frame draw. Grid `s0`
and later overrides remain unverified; a short command-state sample did not
catch a matching terrain material. Existing texture-view mip limits still apply.

The first near-only mismatch was traced to the CPU replay's inactive-lane UV
and derivative/LOD handling. A standalone D3D11 program, using the original
compressed DDS resources and original shaders, gives bit-identical outputs for
both variants at that four-pixel group on Intel and NVIDIA. It uses its own
device, with no game process access, injection or RenderDoc. This is a finite
numeric check, not game-frame parity. CPU/GPU differences still require isolation;
the other earlier sample points have not been declared resolved. No blend
formula or export default was changed to hide the discrepancy.

The original captures and standalone GPU probe are not distributed here. The bundled replay remains approximate; choosing baked output does not certify frame parity.

### Created terrain shader variants (2026-10-12)

Read-only shader-cache metadata identifies 43 of the 76 saved terrain bytecode
files as created D3D11 shader objects: 34 vertex, 6 pixel, 1 hull and 2 domain.
The bytecode-content hash routine (RVA 0x520C30), cache lookup (0x35F98A0), and
creation dispatcher (0x35F9CA0) match current BO4 code. Offline native execution
validates all 76 hashes plus 17 boundary-length inputs. Creation is not proof of
a particular draw binding.

The existing replay's structured-buffer G-buffer PS `457b8be2b884842c` and DS
`8b5368bcb0ce612f` are absent from the captured creation cache. Created variants include PS `d437ccb01fe95d61`, G-buffer DS
`89585f99be39cd7f`, and the separate depth DS `45d57ac01db7bed8`. The
captured technique graph establishes the G-buffer pairing.
They read the same 112-byte layer layout as seven CB1 float4 rows per layer;
texture registers shift when the structured layer buffer is removed. The
comparison script records the explicit register mapping. The main replay still
uses its original variant and register taps; no export default was switched.

This exposed a replay bug: four-operand `imul` wrote the low result to destHI
and never wrote destLO. The created PS uses `imul null, index, layer, 7` for
CB1 indexing. Signed and unsigned multiply now preserve both halves, null
destinations, masks, inactive lanes and aliased sources. Four new regressions
and the 33 existing focused tests pass. Microsoft instruction references:
https://learn.microsoft.com/en-us/windows/win32/direct3dhlsl/imul--sm4---asm-
https://learn.microsoft.com/en-us/windows/win32/direct3dhlsl/umul--sm4---asm-

Offline probes use original native textures and the verified texture-view
limits at four derivative scales. For the original source far-tiling flags,
all three targets and discard masks agree bit-for-bit at 736 surviving points
out of 1,280 tested across all five sectors. This is finite shader-variant
validation, not in-game visual parity. Clearing far flags for the existing
near-only approximation leaves a sector-0 discrepancy at three sampled points;
maximum RT0 difference is 0.001323 and RT1 is 0.007479. That discrepancy remains
open. Sampler bindings, anisotropic filtering and a draw-selected path remain
unverified. These numeric comparisons do not validate exported geometry or lighting.

See `tests/black_ops_4/capture/test_bo4_integer_multiply.py` and `test_bo4_sampling_views.py` for the reusable regression checks. Historical game captures are not included in this repository.

### Shader replay

[bo4_dxbc_emulator.py](../tools/black_ops_4/capture/bo4_dxbc_emulator.py) runs
a captured shader model 5 shader's disassembly on numpy arrays, one lane per
pixel or domain point:

- Branches run under execution masks.
- A discarded lane keeps running as a helper, as on the GPU. Its 2×2 quad's
  derivatives, and so the implicit mip levels, stay valid.
- Registers hold raw 32-bit words, so bit tricks and `f16tof32` behave as they
  do on the GPU.
- Sampler states are decoded from the material's words. `0x2A2` is linear,
  clamped and unmipped; `0x12`–`0x14` wrap and filter between mips.
- An unknown opcode raises an error instead of being skipped.

[bo4_terrain_gbuffer.py](../tools/black_ops_4/capture/bo4_terrain_gbuffer.py)
rebuilds the terrain's shader resources from a package. It runs the terrain
G-buffer pixel shader (`457b8be2b884842c` on zm_towers) over a top-down grid.

- **Node records (t9).** The replay builds one 124-byte record per finest
  source tile; its size is `32 * units_per_sample` (256 units on zm_towers).
  - The game draws quadtree quadrants. A quadrant's layer mask (+4) is the OR
    of its tiles' masks, and all 124 live records on zm_towers follow that
    rule.
  - +8 is the displacement layer mask. It equals +4 on the checked zm_towers
    nodes, but differs in Mansion. Use the [restricted mask rule](#mansion-node-mask-correction).
- **Geometric normal.** A central difference of the undisplaced bilinear
  height, one height texel either side of the point:
  - the step is `s = span / cb2[30].x` (8200 / 1028 ≈ 7.977 on zm_towers);
  - the normal is `normalize(−dh/dx, −dh/dy, 1)`.

  This matches the shader exactly.
- **Validation.** Over the zm_towers region with the most layers (256 units
  at 2 texels per inch), the Python layer loop and the replayed shader differ
  in sRGB albedo by:
  - a mean of 0.16/255;
  - 1/255 at the 99th percentile;
  - at most 13/255.
- **Camera distance.** The pixel shader computes it 32 times, but only far
  tiling uses it. With every term forced to 0, the zm_towers bake is
  bit-identical.

#### Far tiling

Flag 0x400 (record +52) makes a layer tile more coarsely with distance, to
hide repetition. The pixel and domain shaders compute, per layer:

```
d²   = dot(v1, v1)                  v1 = world − eye (cb2[24])
r    = (d² · |uv_row0.xyz|²)^¼      = sqrt(distance in texture repeats)
band = floor(r / 4)
s    = 1 / (16 · band + 1)          uv scale for this band
t    = min(5 · frac(r / 4), 1)      blend over the first 20% of a band
```

- Band 0 covers the first 16 repeats from the eye, and there s = 1 and t = 1.
  Up to band 0's edge, a far-tiled layer is identical to one without the flag.
- **Pixel shader.** Albedo and normal are sampled at `uv · s`. While r > 4 and
  t < 1 they are blended from the previous band's scale:
  `lerp(sample(uv · s_prev), sample(uv · s), t)`. The height-blend reveal is
  always sampled at the unscaled uv. Over band 1's blend, the height-blended
  weight fades from its reveal-map value to the value for `h = 0.5`, and
  beyond that `h` is 0.5.
- **Domain shader.** The height map is sampled at `uv · s`, multiplied by `t`
  (fading in at each band edge instead of blending two samples), and the
  displacement term becomes `w · h · amount · t / sqrt(s)`: coarser tiling
  gets proportionally taller relief.

A bake has no single eye. `TerrainScene(far_tiling="near")`, the default,
clears 0x400 from the record copies, which is what a camera within 16 repeats
sees. On zm_white sector 1 this is bitwise identical to keeping the flag and
patching every distance term to 0, for RT0–RT2, the alive mask and the
displacement. `far_tiling="refuse"` stops instead. The CAST report lists the
affected slots under `far_tiling`.

**Displacement.** The terrain is tessellated. Its domain shader
(`8b5368bcb0ce612f`) raises every vertex along +Z:

```
acc = 0
for each layer in the node's layer mask (+4), in ascending slot order:
    skip it unless flags & 0x2
    w = the layer weight (4094 means 1, 4095 means 0); skip it if w = 0
    if the layer is in the displacement mask (+8):
        acc = max(w · h · amount, (1 − w) · acc)
    else:
        acc = acc · (1 − w)
z += fade · acc
```

- `h` is the layer's `heightMap`, slice `+80 & 0xFFFF`, sampled at mip
  `max((1 − fade) · 5, (+80 >> 16) & 0x3F)`.
- `amount` is the half in bits 16–31 of the flags (+52).
- `fade` depends on the camera distance `d`:
  `fade = 1 − smoothstep(sat((d − cb2[41].x) / (0.95 · (cb2[41].y − cb2[41].x))))`.
  The replay holds it at 1, as for a close camera.
- With flag 0x400, the `w · h · amount` term is also scaled by distance terms.
  No zm_towers layer sets that flag.

The pixel shader never sees the displacement. It shades with the normal of the
undisplaced height array. On the zm_towers arena the displacement is 0.1–4.4
inches, with a mean of 1.55.

### Volume decals

GfxWorld +0x590 holds the count and +0x598 an array of 216-byte
`GfxVolumeDecal` records. zm_towers has 1,720 decals, which use 110 materials
and 18 pixel shaders.
[bo4_volume_decals.py](../tools/black_ops_4/capture/bo4_volume_decals.py)
decodes the records. The packager copies them to `capture/decals/` along with
their materials, images, shaders, blend states and the reveal atlas.

Each decal is a box drawn after the opaque G-buffer pass. The one decal vertex
shader (`4a6c71bcf22ede16`) builds the box from a 220-byte per-decal record
(t21) and passes the record's index on. The pixel shader:

1. Rebuilds each pixel's world position from the scene depth (t0) and the
   camera rows of cb2.
2. Moves that position into the box's local space and discards it outside
   [−1, 1]³.
3. Discards the pixel if its G-buffer normal (t6) is more than the record's
   angle threshold away from the box's first axis, which is the projection
   direction.
4. Fades toward the box's edges. Per axis,
   `t = sat((|p| − f) / (1 − f))` and `fade = 1 − smoothstep(t)`; the
   minimum over the axes is kept. `f` is the record's edge feather, so 1
   gives a hard edge.
5. Multiplies the fade by the reveal atlas. The atlas is the one texture the
   shader declares that no pass argument binds: `vdreveal`, R8 at 1024².
   Each decal reads its own cell of 4², 8² or 16² texels.
6. Uses that product as `w` in the terrain's height-blend reveal, with the
   material's reveal map, contrast and exponent. The result is the decal's
   alpha.
7. Writes albedo, gloss, specular and sometimes a normal, through its
   material's blend state and write mask.

The render targets are:

- RT0: sRGB 8-bit albedo.
- RT1: 10:10:10:2, holding the normal packed on a tetrahedron, and gloss.
- RT2: 10:10:10:2, holding luma and a checkerboarded chroma for specular.

**Checked on a live frame (zm_towers).**

- *Blend states.* The engine's pass state word holds one blend state per
  render target. The words of all 110 materials match the live
  `ID3D11BlendState` objects.
- *Records.* 311 of the 403 records in the live t21 buffer belong to asset
  decals. `gpu_record()` reproduces every byte except the world-to-local
  block. The engine inverts that matrix itself, so it differs by float
  rounding.
  - The edge feather is copied as stored, for every value present: (0,1,1),
    (0.5,1,1), (0.5,1,0.9), (1,0.98,0.98) and (1,1,1).
  - +128.w is 0 on all of them, so the angle test uses the G-buffer normal.
  - +144 is (1,1,1,1) and +208 is (1,0).
  - The other 92 records are runtime decals that are not in the asset.
- *Draw order.* The buffer holds a series of lists, and a decal can appear in
  several.
  - Each list is sorted by +0xC8, the priority, descending, then by material
    pointer, ascending. Under that key the 311 records form 24 sorted runs.
    Asset order gives 175, and shuffled lists 134–156.
  - The instance buffer is 0, 1, 2, …, so within a draw call records draw in
    list order. The replay assumes the per-material draw calls follow the list
    too, which puts priority 1 last, on top.
  - The art agrees with that reading. Priorities 15–21 hold base decoration:
    stone overlays, painted murals and hieroglyphics, and wall moss.
    Priorities 1–2 hold blood, soot, footprints and water puddles. The reverse
    order would paint murals over blood handprints.
  - Decals with the same priority and material have no fixed order.
- *Vertex colour.* The vertex shader writes `(1, 1, 1, 1)`, so decals have no
  per-decal tint.
- *Time.* cb2[89].w is time. Only the puddle and waterfall shader (`dba9e9d1`)
  reads it: it scrolls two normal-map layers by `cb0[4] · time`.

[bo4_decal_composite.py](../tools/black_ops_4/capture/bo4_decal_composite.py)
replays this pass over a baked terrain G-buffer in the same draw order, at
time 0. A bake has no camera, so each draw gets a top-down one. Each pixel's
position and depth are solved so that the shader's own reconstruction lands
exactly on the texel's world point.

### CAST output

[build_bo4_terrain_cast.py](../tools/black_ops_4/capture/build_bo4_terrain_cast.py)
turns a v46 or newer package into a CAST model. Positions are in centimetres
(game inches × 2.54), like Greyhound's CAST model exports.

- **Default.** The mesh is the full-resolution height grid, with every cell
  whose cutout bit is 0 dropped. The albedo comes from the Python layer loop,
  in linear colour.
- **`--emulate`.** The builder runs the game's own shaders.
  - The mesh is the height grid with each cell edge split `--subdivide` times
    (default 2). Each vertex sits where the domain shader puts it. A sub-cell
    is dropped with its grid cell's cutout bit.
  - Vertex normals are the pixel shader's height normal.
  - The maps come from the terrain pixel shader and then every volume decal.
    They are baked in tiles with a two-texel margin and even origins, so the
    2×2 quads and the specular checkerboard match a single bake.
  - The material binds albedo (alpha 0 in holes), a tangent-space normal
    (OpenGL, +Y), roughness and specular. Gloss is written beside them.
  - Roughness is `sqrt(sqrt(2 / (2^(17·gloss) + 2)))`. That is the GGX
    roughness whose lobe matches the game's Blinn-Phong power `2^(17·gloss)`.

**Terrain shaders (probe v48).** The terrain shaders are game-global: the same
containers appear on zm_towers and zm_white. The probe keeps every DXBC
container outside compute shaders that declares the 124-byte node buffer, and
writes it as `terrain_shader_<stage>_<fnv>.dxbc`. The packager copies them to
`capture/shaders/terrain/`, and `shaders.json` gives each one a role read from
its own declarations. Every role needs structured buffers t9 (124) and t14
(112):

| Role | Shader | Rule |
| --- | --- | --- |
| `gbuffer_cutout` | `457b8be2b884842c` | pixel, 3 outputs, `discard`, four `texture2darray (uint)` |
| `gbuffer` | `b9dc6d47c91e8bfa` | pixel, 3 outputs, no `discard` |
| `domain` | `8b5368bcb0ce612f` | domain, position output only (depth pass) |
| `domain_gbuffer` | `1a197d7ce369dba3` | domain, position plus two G-buffer interpolants |

zm_white's v48 capture holds 76 such shaders: 60 vertex, 10 pixel, 4 domain
and 2 hull. The rest get no role:

- twins of the four above that take the layer records from constant buffer
  cb1 (4,095 registers) instead of t14;
- 1-output pixel variants, and two 0-output depth pixel shaders that only
  run the cutout `discard`;
- the hull and vertex shaders.

The packager raises an error if two different containers claim one role.
`--emulate` uses the package's `gbuffer_cutout` pixel and `domain` shaders
unless `--pixel-shader` or `--domain-shader` names another disassembly or
container:

```powershell
python tools/black_ops_4/capture/build_bo4_terrain_cast.py $package $output --emulate `
    --box -1700 -1600 1500 1600 --texels-per-inch 1.25
```

On zm_towers that command builds the arena in about 6 minutes:

- a 3,208 × 3,200-inch box, snapped to the grid;
- 4010 × 4000 maps;
- 569,317 vertices and 1,133,960 triangles;
- 18,655 of the 160,400 cells are holes;
- 84 decals change at least one texel.

The corpse-pit layer sits exactly on the height mounds, so the weight and
height grids register. The cutouts open under the building footprints, and
the model imports into Blender through io_scene_cast.

zm_white's Nuketown (sector 1, box −1788.5 −1717.5 1283.5 1354.5) builds in
about 13 minutes with the package's own shaders:

- 3840 × 3840 maps;
- 528,110 vertices and 1,051,088 triangles;
- 16,070 of the 147,456 cells are holes, under the house footprints;
- displacement from 0 to 6.5 inches, with a mean of 1.28;
- 263 decals change at least one texel.

Still unverified:

- A pixel comparison against an in-game frame.
- Far tiling beyond band 0. A bake shows what a camera within 16 texture
  repeats sees; distant views of a 0x400 layer tile more coarsely in game.
- The render target formats. They are inferred from the shaders' encodings,
  not read from the device.
- Anisotropic filtering. The replay approximates it as trilinear. A top-down
  bake sees every surface head-on, so the two differ only where a uv mapping
  stretches.
- The order the engine issues its per-material decal draw calls in. The replay
  assumes list order. Decals with the same priority and material have no fixed
  order in the engine.

### Cross-check: zm_white

zm_white (Alpha Omega, `terraingfx_1173ca83f06a352`) was captured fresh with
probes v47 and v48 and run through every step above. The v47 package is
byte-identical to the older zm_white fixture.

| Sector | Tiles | Units per sample | Origin | Layers | Role |
| ---: | ---: | ---: | --- | ---: | --- |
| 0 | 128 | 16 | (−32767, −32768) | 9 | 65,536-unit backdrop |
| 1 | 32 | 8 | (−3324.5, −5301.5) | 8 | Nuketown |

- Sector 0's 259,590 hole samples are exactly sector 1's footprint.
- It exercises every layer feature zm_towers lacks:
  - far tiling (0x400) on sector 0 slots 0, 1, 3, 4, 5 and 7, and sector 1
    slots 0–3;
  - the soft-light tint (0x100) on 12 of the 17 layers;
  - a detail normal (0x80) on `t8_rock_cliff_02`, strength 1.0;
  - displacement amounts of 0.6–9 inches.
- Base layers repeat every 64 (sector 0) and 32 (sector 1) units; the others
  every 32–350.
- Three layers set the displacement flag 0x2 with an amount of 0. They still
  scale the accumulated displacement by `1 − w`, and the domain shader still
  samples a height slice for them before multiplying it by 0. Where the
  material has no height map, the replay binds an inert zero slice.
- The verifier passes both sectors. Sector 0's surface-prop check is
  uninformative (see [verified conventions](#verified-conventions)).
- The soft light was checked against the replayed shader. For each sector, the
  test took the solid tile with the most soft-light layers and compared the
  Python layer loop with the replay:

  | Tile | Texels per inch | Mean | p99 | Max | Multiply rule instead |
  | --- | ---: | ---: | ---: | ---: | ---: |
  | sector 0 (63, 1), 9 layers, 7 soft light | 1 | 0.49 | 5 | 41 | 27.2 |
  | sector 0 (63, 1) | 2 | 0.70 | 8 | 69 | 27.0 |
  | sector 1 (12, 0), 8 layers, 5 soft light | 2 | 0.26 | 2 | 38 | 27.2 |

  All values are sRGB albedo differences out of 255. The large differences
  are rare: 1.4% of sector 0's pixels differ by more than 8, and 0.16% of
  sector 1's. Of those, 94–100% lie where a height-blend weight is between
  0.02 and 0.98. zm_white's contrasts are as low as 0.098, which makes the
  blend step steep. The reveal sample then decides the outcome, and the Python
  loop picks a mip level itself where the GPU filters trilinearly. zm_towers'
  contrasts are 0.5, and its maximum difference was 13. That this explains the
  outliers is an inference; it was not tested separately.
- The volume decal pass decodes 1,948 decals with 157 materials. Priorities
  1–4 (1,836 decals) hold blood, dust and puddles, and 12–22 hold dirt blends,
  rust, oil, scorch and cracks. That is the same split as zm_towers.

### Streamed tile meshes

The terrain header's level chain (+0x18) holds one tile grid per quadtree
level; zm_white sector 0 has 128², 64², … 1². Each finest-level tile record
keys, at +0x90, an object streamed from the map's `.xpak`. zm_white has 16,159
distinct objects for its 16,384 tiles, and mode 0 dumps 24 of them as
`payload_<hash>.bin`. All 24 share one 21,128-byte layout:

| Bytes | Content |
| --- | --- |
| 128 | Header: the 64-bit value −4, then zeros |
| 33 × 33 × 8 | One vertex per sample of a 32-cell tile: two points, each a (row, col) pair in 6.10 fixed point with the row in the high 16 bits |
| 2,048 × 6 | u16 triangle indices: the same regular grid on every tile, split along the top-left to bottom-right diagonal |

- The first point is the vertex's own grid position, offset by 0 or 32 samples
  per axis: its place in the 2 × 2 block of its parent tile.
- The second point lies about one sample away (at most 4.5): a morph target.
- The terrain vertex shaders rebuild each vertex's regular position from
  `vertex_id`. They then move it toward the vertex buffer's `v0.xy` by
  `sat(distance · t9[+36] + t9[+40])`, which is continuous LOD for the render.
  Which of the two points feeds `v0` depends on the input layout, which was
  not captured.

Heights still come from the height array. The objects carry no heights, holes
or materials, so they are not the terrain's collision, and a bake from the
full-resolution grid does not need them. The collision is a separate
heightfield; see [terrain collision](#terrain-collision).

### Terrain collision

Terrain collision is a heightfield per sector in the clipmap, not triangles.
Clipmap +0x1D0 is the sector count, and +0x1D8 points to 168-byte sector
records. zm_white has two. The probes do not save these records yet; the
results below come from reading the running game.

| Sector offset | Data |
| --- | --- |
| +0x00 | Tile count (u32) |
| +0x04 / +0x08 | Tiles across X / Y |
| +0x0C | Cells per tile edge (32, so a tile has 33 × 33 samples) |
| +0x10 | Half the grid size in samples (2048 / 512); the grid runs from −half to +half |
| +0x18 | Tile records, row-major: k = row × tiles across + col |
| +0x20 / +0x2C | World bounds minimum / maximum |
| +0x38 / +0x44 | World-to-grid transform: translation, then a 3 × 3 diag(1/ups, 1/ups, 1/height scale) |
| +0x68 / +0x74 | Grid-to-world transform: translation (sector centre x, centre y, height bias), then a 3 × 3 diag(ups, ups, height scale) |
| +0x98 / +0xA0 | Layer surface pointer list / count |
| +0xA4 | Units per sample |

Tile records are 80 bytes:

| Tile offset | Data |
| --- | --- |
| +0x00 / +0x0C | World bounds minimum / maximum |
| +0x18 | Grid-space origin, two floats: (col × 32 − half, row × 32 − half) |
| +0x20 | u16 sample count (1,089), width (33), height (33) and kind: 1 plain, 2 hole-masked. All four are zero on a tile with no data |
| +0x28 | Heights, u16 per sample |
| +0x30 | Kind 2 only: hole mask, one bit per sample, LSB first, set = solid |
| +0x38 | Surface block |
| +0x40 | The tile's byte offset in a clipmap-wide height stream: the number of earlier tiles with data, across sectors, × 2,178 |
| +0x44 / +0x46 | u16 palette size / bits per index. With a palette of one, +0x46 holds the layer slot itself and there is no block |
| +0x48 | Surface block bytes: palette size + ceil(1,089 × bits / 8) |

The surface block is a palette of layer slots, one byte each, followed by each
sample's palette index, bit-packed LSB first. A tile's heights, mask and surface
block are stored back to back.

Layer surface records are 32 bytes:

- material name hash +0x00 (60-bit FNV-1a);
- surfaceFlags +0x10, whose surface type is bits 0x01F00000 (see
  [materials](#materials-the-global-filter-table));
- contents +0x14;
- a float at +0x18.

In both sectors their order is the package's layer-slot order, checked by hash.

Checked on zm_white against the v48 package:

- Heights are bit-identical to the package grid on all 16,159 + 1,020 tiles
  with data.
- 225 tiles of sector 0 have no data: the 15 × 15 block at rows 54–68,
  cols 58–72 under Nuketown. 4 tiles of sector 1 have none either. The
  package marks every sample of these tiles as a hole, and no tile with data is
  entirely hole.
- The 64 + 49 hole-masked tiles are exactly the partly cut tiles. Each mask
  equals the package cutout, sample for sample.
- On every tile, the grid-to-world transform maps the +0x18 origin to the bounds
  minimum and the heights to the bounds' z range.

The surface slot is stored per sample and does not follow the render
composition:

- Where one render layer dominates (effective weight above 0.9), the collision
  slot is that layer: 100% of samples in sector 1, 94% in sector 0.
- In blends, collision often keeps the base layer where the render rule
  promotes the first painted layer. The render rule agrees on only 42% / 48% of
  samples.
- Sequential-lerp effective weights, with the base layer's weight scaled by
  0.35–0.5 before the argmax, reproduce 97.8% of sector 1 and 87% of sector 0.
  Sector 0's remaining mismatches are spread over the whole map in a
  fine-grained pattern, so some per-sample input may be involved, such as the
  blend-height textures.

The exact rule is unknown. Read the stored slots rather than deriving them.

### What the package preserves

The package preserves:

- Sector-local material ordering, image bindings and original identities.
- Independent BC4 layer weights, R16 heights, cutout bits and tile masks.
- UV matrices and uninterpreted material constants.
- Source files with SHA-256 comparisons.
- A `materials/superterrain_materials.json` intake recipe.

The recipe is not a GDT. Full material names remain distinct from basename
aliases used by a consumer. Height/reveal is not automatically roughness, and
unknown semantic bindings remain unknown.

BO4's independently overlapping weights must not be replaced with a fabricated
discrete index plane or silently normalized. A consumer needs a BO4-specific
intake path. Radiant patch reconstruction and its control budgets are external to Greyhound.
Greyhound now exports BO4 source, original-material CAST and baked CAST packages;
see [export versions](bo4-terrain-export.md). It does not turn BO4 masks into OMPV
or ship a configured TerrainReconstructor workspace.

[verify_bo4_gdt_intake.cjs](../tools/black_ops_4/capture/verify_bo4_gdt_intake.cjs)
requires a separately supplied GDT project and materials directory. It checks
that consumer's source parser in memory, not a distributed desktop binary or
a compiled BO3 map.

## Find the relevant capture

Use [BO4 capture modes](bo4.md#capture-modes) to collect only the branch needed.

| Area | Native entry point | Offline tools |
| --- | --- | --- |
| World pools | `src/WraithXCOD/WraithXCOD/games/black_ops_4/capture/BO4WorldPoolProbe.h` | `audit_bo4_world_probe.py`, `decode_bo4_collision.py` |
| Static placements | `src/WraithXCOD/WraithXCOD/games/black_ops_4/placements/BO4ModelPlacementCapture.h` | `audit_bo4_placements.py` |
| Model triangle collision | `src/WraithXCOD/WraithXCOD/games/black_ops_4/brushes/BO4ModelCollisionProbe.h` | `decode_bo4_model_collision.py` |
| Model physics | Mode 3 capture | `decode_bo4_model_physics.py` |
| Primitive investigation | Saved model-physics evidence | `analyze_bo4_physics_primitives.py` |

Native headers are under `src/WraithXCOD/WraithXCOD/`; offline decoders are
under [BO4 brushes](../tools/black_ops_4/brushes/) unless listed in
[placements](../tools/black_ops_4/placements/). Read each script's `--help`
and source before choosing inputs.

The measured world pools include:

| Pool | Reference name | Header bytes |
| --- | --- | ---: |
| 11 | clipmap / col_map | 728 |
| 12 | comworld | 96 |
| 13 | gameworld | 96 |
| 14 | gfxworld | 6,832 |
| 147 | streamerworld | 256 |
| 118 | entity_list | 32 |

An initial one-hop probe can hit its target limit without capturing a complete
graph. Check occupancy, free-list agreement and the capture's actual read
coverage before treating a field as a fully recovered array.

## World brush layout and ownership

The supported BO4 world decoder uses these measured fields:

| Location | Interpretation |
| --- | --- |
| clipmap +0x2B0 / +0x2B8 | Brush count / pointer |
| Brush +0x00 / +0x08 | 20-byte side records / float3 vertices |
| Brush +0x10 / +0x20 | Minimum / maximum XYZ |
| Brush +0x1C | Raw contents |
| Brush +0x2C | Six axial filter indices, uint16 |
| Brush +0x38 / +0x3A | Vertex / side counts, uint16 |
| clipmap +0x278 | 32-byte leafbrush nodes, not brush records |
| clipmap +0x68 | 56-byte collision leaves |
| clipmap +0x58 | 24-byte BSP nodes |

Brush records are 64 bytes. Validate all vertex/side spans and ownership.
Positive leafbrush-node counts reference indices through +16. Branches use
node-relative children at +24/+28; a -1 count also visits the following node.
BSP signed children encode leaves as `-(leaf + 1)`.

zm_towers also validates this layout: 11,521 brushes split exactly into 11,025
world and 496 inline brushes. Its last leaf (209) has no brushes: root node 0,
zero brush contents and bounds, and it is unreachable from the BSP. It is
the triangle-only leaf of clip model 2 (see
[World triangle collision](#world-triangle-collision)). 16 of 221 clip models
have root node 0 (no brush collision). The decoder accepts only those shapes
and lists them.

Collision leaves are 56 bytes: surface tree index +0 (-1 for none), brush
contents +4, triangle contents +8, bounds +12, and leafbrush root +40. The
bounds are the brush extent ±0.125. Each 88-byte clip model holds bounds +0,
radius +24, and an embedded copy of that leaf at +32, like CoD's `cmodel_t`.
All 205 brush-bearing clip models have embedded contents equal to the OR of
their brushes and embedded bounds equal to the brush extent ±0.125. Clip model
0 is the world: its embedded leaf is zero, and the world uses BSP leaves
instead.

The geometry of both trees is verified too, and the decoder now enforces it:

- **Leafbrush nodes** follow CoD's `cLeafBrushNode`: axis +0, count +4
  (positive for a leaf, 0 or -1 for a branch), contents +8, split distance
  +16, range +20, child offsets +24/+28.
  - On zm_towers, across all 3,158 branches, child-0 brushes start at or
    above the split and child-1 brushes end at or below it.
  - A -1 branch's following node holds exactly the 7,853 brushes that
    straddle the split.
  - Node contents equal the OR of the subtree's brushes.
- **World BSP nodes** hold an inline plane (normal +0, distance +12) and
  signed children at +16. zm_towers has only three nodes (x = 8192,
  y = -8192, z = 3584), so the leafbrush tree carries the real spatial
  subdivision. No leaf brush lies on the wrong side of its path.
- **Brush solids:** rebuilding each brush from its bounds and side planes
  gives the same solid as its stored vertices within 0.1 units for all
  11,519 non-degenerate brushes (11,377 within 0.01). Stored bounds of
  many-sided brushes can be up to 1.1 units looser than the vertices.

The header count at +0x280 can describe the sum of leaf references rather than
one unique physical allocation. Shared pointer ranges and unreachable nodes
must not extend the trusted decode into adjacent memory.

World ownership follows BSP roots. Inline ownership follows clipmodel roots
and is checked against gfx-model bounds. Unused inline-library shapes stay
unplaced; they must not be emitted at an invented world origin.

The exact hull backend is shared with CW for mathematical operations only.
It does not imply shared binary layouts or contents meanings. A record with
too few points to form a volume remains rejected. Bounds/plane discrepancies
are retained rather than hidden by clamping or snapping coordinates.

## Entity transforms

Measured runtime entity records are 48 bytes: model index +16, unknown word
+20, origin +24 and angles +36. Earlier external 20/32 offset candidates did
not establish this runtime layout.

Keep authored transforms, runtime record transforms and gfx bounds separately.
A disagreement can have several causes. On zm_towers, record +16 indexes the
clip/gfx brush models. 28 of 29 script_brushmodel disagreements are zombies
blockers (`*_backup_clip`, `mdl_turn_back`) whose gfxworld bounds sit exactly
2048 units lower in Z than the entity origin. The entity origin matches the
authored `origin` property, so the gfx bounds reflect script motion at runtime.
Use the entity origin for authored placement.

## World triangle collision

`decode_bo4_triangle_collision.py` reads 36-byte surface records at
clipmap +0x98:

| Offset | Field |
| --- | --- |
| +0 | Six bounds floats |
| +24 | Triangle start, uint32 |
| +28 | Vertex-reference start, uint32 |
| +32 / +33 | Triangle / vertex-reference counts, uint8 |
| +34 | Global filter (material) index, uint16 |

The vertex-reference array comes from clipmap +0x2A8. It is not a sequential
slice of the vertex pool. Check topology, range accounting and bounds while
preserving original triangles. Do not thicken surfaces into guessed brush solids.

### Ownership: surface trees

Clipmap +0xA0 / +0xA8 is a count and a pointer to 16-byte `{blob pointer,
byte size}` entries. Each blob is a BVH of u32 words:

| Node | Words |
| --- | --- |
| Branch | child count n (2–8); n child offsets, in words from this node; minX[n], minY[n], minZ[n], maxX[n], maxY[n], maxZ[n] |
| Leaf | `0x100 \| count`, then that many surface indices |

A collision leaf, or a clip model's embedded leaf, names its tree at +0 and
stores the OR of its triangle contents at +8. On zm_towers (73,610 surfaces):

| Tree | Owner | Surfaces | Nodes | Triangle contents |
| --- | --- | --- | --- | --- |
| 0 | World (BSP leaf 3) | 0–73,572 | 3,924 branches, 17,239 leaves | 0x085B36E1 |
| 1 | Clip model 2 (copied in leaf 209) | 73,573–73,609 | 2 branches, 7 leaves | 0x00103081 |

The trees partition every surface exactly once. Every box contains its
children and its surfaces. Each owner's triangle contents equal the OR of its
surfaces' filter contents. World-tree surfaces are in world space. Clip-model
surfaces are model-local and are placed by the entities that use that clip
model (entity 1885 for clip model 2).

### Materials: the global filter table

Brush side materials (20-byte sides), brush axial indices (+0x2C) and surface
+34 all index one table in the executable, not in the map. The table holds
8-byte `{surfaceFlags, contents}` entries. The probe finds it by scanning for
the brush contents and saves it as `global_filter_candidate.bin`. For all
11,521 brushes, every face's filter contents equal the brush contents.

Names come from BO4's own declarations, which the probe captures as
`named_flag_candidates`. Each declaration is a `{name, surfaceFlags mask,
contents mask}` record:

- **Surface type:** bits 0x01F00000 of surfaceFlags, a 5-bit index
  (rock = 0x11, concrete = 0x05, water = 0x14, …). Type 0 has no declaration.
- **Flags:** bits named by the other declarations, such as noDraw, nonSolid,
  playerClip, bulletClip and detail.

zm_towers uses 54 materials:

- 32 are fully named.
- 21 leave only contents 0x1 unnamed. CoD's `CONTENTS_SOLID` convention fits,
  but BO4 does not declare it.
- One (the caulk material) leaves surfaceFlags 0x8 unnamed.

`decode_bo4_triangle_collision.py` writes per-surface `material_index` and
`surface_tree` fields. It also writes a `materials` table (raw flags, type,
names, unnamed bits) and a `surface_trees` list with owners. Captures made
before the tree blobs were saved still resolve materials but report ownership
as not captured.

The global table is a registry built at runtime. On zm_towers, entries 0–153
are filled and the rest are zero, and no pair appears twice.

The per-map table at clipmap +0x2C0 / +0x2C8 holds 152 entries of 8 bytes,
ending with a 0xFFFFFFFF entry. It is the map's own list of pairs in the same
`{surfaceFlags, contents}` form:

- 131 of its 151 pairs are registered in the global table, but not in table
  order. The in-memory brush and surface ids already point into the global
  table, so decoding never needs this table.
- 24 global entries come from elsewhere: 0x20000000-contents pairs, and a
  0xFFFFFFFF entry at index 38.
- The 21 pairs that are not registered are mostly bare surface-type pairs
  (contents 0x1). Model collision uses only 14 of them, so they are not the
  model filter list either. What uses them is unknown.

## Model-attached collision

Each measured 96-byte instance contains model pointer +0, flags +8, position
+12, a 3x3 basis at +24 and world bounds at +60.

The stored basis maps world-relative coordinates into local coordinates.
Its lengths are inverse scales. The decoder retains
`world_to_local_linear` and emits a column-vector `matrix_world` using
the inverse linear transform. Apply that transform once; do not use the stored
basis as a forward matrix. Transform each surface box before combining bounds.

Model +0x50 and count +0x140 identify 56-byte surface records: triangle pointer
+0, count +16, bounds +20, bone index +44, contents +48 and surfaceFlags +52.
The pair is stored inline, not as a global filter index. Given BO4's flag
declarations (`--flags` with a mode 1 or mode 7 probe),
`decode_bo4_model_collision.py` names them the same way as world materials. On
zm_towers all 45 model materials are named except contents bit 0x1; for
example, rock with contents 0x1 covers 512 surfaces.
Each pointer must be captured independently; separate surfaces need not be
contiguous allocations.

Triangles are reconstructed from three float4 equations:

```text
n.xyz dot p = n.w
s.xyz dot p = s.w + u
t.xyz dot p = t.w + v
```

Solve at barycentrics (0,0), (1,0) and (0,1), then select winding against the
captured normal. Validate singularity, finite values and equation residuals.
These coordinates are recovered from stored float32 equations; they are not
claimed bit-identical to original authored vertices.

Bone references, mismatching bounds and zero-surface models remain diagnostics.
Do not substitute a render mesh or resize geometry to match culling bounds.

## Model physics and unknown primitives

The model +0x60 path leads to brush/primitive geometry. The measured list header
is 24 bytes with count, contents and a pointer to 16-byte entries. Entries hold
separate brush and primitive pointers.

Mode 3 creates a self-contained physics capture with its own headers,
instance transforms and geometry bytes. The decoder validates every count,
pointer and instance relationship before building supported brush hulls.

Primitive type 3 remains unresolved. A cylinder interpretation has geometric
support, but another game's enum is only a lead. Trace BO4's type dispatch
before claiming a shape and preserve unknown primitive bytes until then.
Unsupported primitive instances stay out of the published brush geometry.

## Useful next contributions

- Validate supported layouts after reloads and on other BO4 maps/builds.
- Save the terrain collision heightfields (clipmap +0x1D8), instanced models
  (gfxworld +0x470) and dynamic entities (clipmap +0x150) in the probes. Then
  emit the last two from the placements command.
- Trace bone-dependent collision and the per-map +0x2C0 pair table.
- Confirm trigger associations through runtime dispatch.
- Identify primitive types from BO4 consumers.
- Extend mask/slice regression coverage to more sector sizes and shared arrays,
  preserving independent weights and explicit exclusions. Validate draw-selected
  LOD and sampler state separately from offline shader agreement.
- Test assembled brush outputs in Radiant and gameplay.

Keep source accounting and rejected records in every report. Describe what a
check proves: file hashes, equation residuals, matching bounds, compilation
and gameplay are different evidence. Start with the
[contribution walkthrough](contributing.md), and add small synthetic fixtures
instead of personal captures.
