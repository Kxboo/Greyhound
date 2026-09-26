"""Build a CAST model of a BO4 terrain sector from a source package.

Geometry is the height grid at full resolution. A cell is dropped where its
cutout bit is 0, the same test the terrain pixel shader discards on: bit (i, j)
decides the cell from sample (i, j) to (i + 1, j + 1).

The albedo is baked with the terrain pixel shader's own layer loop:
- Layers run in ascending slot order: color = lerp(color, layer_color, w').
- w comes from the layer's BC4 weight slice, bilinear on the sample grid; record
  slice 4094 means always 1 and 4095 always 0.
- The first layer with w > 0 is drawn at w' = 1.
- Height-blend layers (flag 0x4) use the reveal map h:
  x = sat(0.998 w + 0.001), lo = sat((1-x) - c x^e), hi = sat((1-x) + c (1-x)^e),
  w' = max(sat((h - lo) / (hi - lo)), sat(100 (w - 0.99))).
- layer_color = albedo.rgb * lerp(1, tint, a), with a = 1 for height-blend
  layers and albedo.a otherwise.
- Flag 0x300 swaps the multiply for a Pegtop soft light,
  soft(base, top) = (1 - 2 top) base^2 + 2 top base, with base = albedo and
  top = tint (flag 0x200 swaps the two), and
  layer_color = lerp(albedo.rgb, soft, a). A tint of 0.5 leaves the albedo as
  it is.
- The tint is the record's 10-bit truncated half, which is what the shader
  reads, not the material constant it was packed from.
Blending is done on linear colour, as the GPU does after an sRGB fetch.

Far tiling (flag 0x400) is baked as a close camera sees it: within 16 texture
repeats of the camera every far-tiling factor is exactly 1, the same as with
the flag clear (bo4_terrain_gbuffer's far_tiling="near").

This needs the probe v46 runtime layer records in the package. A layer whose
flags select a path not implemented here (metal, untextured) stops the bake
instead of approximating it. bo4_terrain_gbuffer.py runs the game's own
shader instead and covers every path.

Positions are written in centimetres (game inches x 2.54), like Greyhound's
own CAST model exports, so the terrain lines up with exported props.

--emulate builds the model from the game's own shaders instead, run by
bo4_dxbc_emulator:

- Mesh: the height grid split `--subdivide` times per cell. Each vertex sits
  where the terrain domain shader puts it, on the bilinear height array raised
  by the layer displacement (TerrainScene.displaced_height). A sub-cell is
  dropped with its grid cell's cutout bit.
- Vertex normals: the pixel shader's own height normal, a central difference
  of the undisplaced height array one height texel (span / width) either side.
  The game shades with that normal, never with the displaced surface.
- Maps: the terrain pixel shader over every texel, then every volume decal
  drawn over the G-buffer with its own shader and blend state
  (bo4_decal_composite). The CAST material gets albedo (alpha 0 in holes),
  normal (tangent space around the vertex normal, OpenGL +Y), roughness and
  specular; gloss is written beside them.
- Far tiling (layer flag 0x400) is baked as the game draws it within 16
  texture repeats of the camera, where it is exactly off (TerrainScene
  far_tiling="near").
"""

# Support direct execution and the isolated packaged Python runtime.
import sys as _tool_sys
from pathlib import Path as _ToolPath
TOOLS_ROOT = next(p for p in _ToolPath(__file__).resolve().parents if (p / "tool_bootstrap.py").is_file())
_tool_sys.path.insert(0, str(TOOLS_ROOT))
import tool_bootstrap as _tool_bootstrap
_tool_bootstrap.activate(__file__)
import argparse
import json
import struct
from pathlib import Path

import numpy as np
from PIL import Image

from verify_bo4_terrain_package import cutout_bits, decode_bc4, world_aligned

CM_PER_INCH = 2.54
ALWAYS_ONE, ALWAYS_ZERO = 4094, 4095
EMPTY_COLOR = 0.05


def srgb_to_linear(c):
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def linear_to_srgb(c):
    c = np.clip(c, 0, 1)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * c ** (1 / 2.4) - 0.055)


def pyramid(image):
    """Box-filtered mip chain of a float image (H, W, C)."""
    levels = [image]
    while min(levels[-1].shape[:2]) > 1:
        a = levels[-1]
        h, w = a.shape[0] // 2 * 2, a.shape[1] // 2 * 2
        a = a[:h, :w]
        levels.append((a[0::2, 0::2] + a[1::2, 0::2] + a[0::2, 1::2] + a[1::2, 1::2]) / 4)
    return levels


def bilinear_wrap(image, u, v):
    """Sample (H, W, C) at texture uv with wrap addressing, D3D texel centres."""
    h, w = image.shape[:2]
    x, y = u * w - 0.5, v * h - 0.5
    x0, y0 = np.floor(x).astype(np.int64), np.floor(y).astype(np.int64)
    fx, fy = (x - x0)[..., None], (y - y0)[..., None]
    x0, y0 = x0 % w, y0 % h
    x1, y1 = (x0 + 1) % w, (y0 + 1) % h
    return ((image[y0, x0] * (1 - fx) + image[y0, x1] * fx) * (1 - fy)
            + (image[y1, x0] * (1 - fx) + image[y1, x1] * fx) * fy)


def bilinear_clamp(grid, s, t):
    """Sample a (rows, cols) grid at fractional (col, row), clamped."""
    rows, cols = grid.shape
    s, t = np.clip(s, 0, cols - 1), np.clip(t, 0, rows - 1)
    i, j = np.minimum(np.floor(s).astype(np.int64), cols - 2), np.minimum(np.floor(t).astype(np.int64), rows - 2)
    fs, ft = s - i, t - j
    return ((grid[j, i] * (1 - fs) + grid[j, i + 1] * fs) * (1 - ft)
            + (grid[j + 1, i] * (1 - fs) + grid[j + 1, i + 1] * fs) * ft)


class Layer:
    def __init__(self, package, row):
        self.slot, self.runtime = row["slot"], row.get("runtime")
        if self.runtime is None:
            raise ValueError("Package has no runtime layer records; capture with probe v46 or newer")
        r = self.runtime
        # Flag 0x10 is the metal path (probe v46 packages called it "cavity").
        if r.get("metal", r.get("cavity")) or not r["textured"]:
            raise NotImplementedError(f"Layer {self.slot}: flags {r['flags']} select an albedo path not implemented")
        self.soft_light, self.soft_light_swap = r["soft_light_tint"], r["soft_light_swap"]
        images = image_table(package, row["material"])
        albedo = np.asarray(Image.open(images["colorMap"]).convert("RGBA"), np.float32) / 255
        albedo[..., :3] = srgb_to_linear(albedo[..., :3])
        self.albedo = pyramid(albedo)
        self.reveal = None
        if r["height_blend"]:
            reveal = np.asarray(Image.open(images["revealMap"]).convert("RGBA"), np.float32)[..., :1] / 255
            self.reveal = pyramid(reveal)
        rows = r["uv_rows"]
        self.u_row, self.v_row = rows[0:4], rows[4:8]
        self.tint = np.array(r["tint_rgb"], np.float32)

    def uv(self, x, y):
        (a, b, _, c), (d, e, _, f) = self.u_row, self.v_row
        return a * x + b * y + c, d * x + e * y + f

    def tinted(self, rgb, a):
        """The shader's tint: a multiply, or a soft light with flag 0x300 (0x200 swaps its operands)."""
        if not self.soft_light:
            return rgb * (1 + (self.tint - 1) * a)
        top, base = (rgb, self.tint) if self.soft_light_swap else (self.tint, rgb)
        soft = (1 - 2 * top) * base * base + 2 * top * base
        return rgb + (soft - rgb) * a

    def level(self, levels, texels_per_unit, scale=1.0):
        """Mip whose texel best matches one bake texel."""
        per_unit = levels[0].shape[1] * abs(self.u_row[0] or self.u_row[1]) * scale
        ratio = per_unit / texels_per_unit
        return levels[int(np.clip(np.round(np.log2(max(ratio, 1))), 0, len(levels) - 1))]


def image_table(package, material):
    txt = package / "materials" / "materials" / (material.split("/")[-1] + "_images.txt")
    table = {}
    for line in txt.read_text().splitlines()[1:]:
        semantic, name = line.split(",", 1)
        table[semantic] = package / "materials" / "images" / (name + ".png")
    return table


def load_grid(package, s):
    """World heights and cutout bits of a sector, both indexed [row (+Y), col (+X)] in the world."""
    used, width = s["grid_samples"], s["height"]["width"]
    raw = np.fromfile(package / s["height"]["file"], "<u2").reshape(width, width)
    heights = s["world_height_bias"] + raw[:used, :used].astype(np.float64) * s["height"]["scale"]
    c = s["cutout"]
    words = np.fromfile(package / c["file"], "<u4").reshape(c["height"], c["width"])
    solid = cutout_bits(words)[:used, :used].astype(bool)
    return world_aligned(s, heights), world_aligned(s, solid, cells=True)


def load_weights(package, s, k):
    """Weight slice k of a sector as the full texture (32n+4 texels, texel i at sample i), world-aligned."""
    lw, used = s["layer_weights"], s["grid_samples"]
    per = lw["bytes_per_slice"]
    with (package / lw["file"]).open("rb") as f:
        f.seek(k * per)
        texels = decode_bc4(f.read(per), lw["width"], lw["height"])
    if s.get("local_to_world"):
        # Rotate the used samples; the padding repeats the new last row and column, as in the file.
        grid = world_aligned(s, texels[:used, :used])
        texels = np.pad(grid, ((0, lw["height"] - used), (0, lw["width"] - used)), mode="edge")
    return texels


def load_sector(package, sector_json):
    s = json.loads(sector_json.read_text())
    used = s["grid_samples"]
    heights, solid = load_grid(package, s)
    weights = [load_weights(package, s, k)[:used, :used] for k in range(s["layer_weights"]["slices"])]
    layers = [Layer(package, row) for row in sorted(s["layers"], key=lambda r: r["slot"])]
    return s, heights, solid, weights, layers


def blend(layers, weights, s, x, y, texels_per_unit):
    """The terrain pixel shader's layer loop over world points (x, y) -> linear rgb."""
    ox, oy = s["world_xy_origin"]
    ups = s["units_per_sample"]
    gs, gt = (x - ox) / ups, (y - oy) / ups
    color = np.full(x.shape + (3,), EMPTY_COLOR, np.float32)
    drawn = np.zeros(x.shape, bool)
    for layer in layers:
        r = layer.runtime
        if r["weight_slice"] == ALWAYS_ONE:
            w = np.ones(x.shape, np.float32)
        elif r["weight_slice"] == ALWAYS_ZERO:
            continue
        else:
            # The record's slice indexes the shared array; the package holds this sector's run.
            k = r["weight_slice"] - s["layer_weights"].get("array_slice_base", 0)
            w = bilinear_clamp(weights[k], gs, gt).astype(np.float32)
        active = w > 0
        if not active.any():
            continue
        u, v = layer.uv(x, y)
        if layer.reveal is not None:
            c, e = r["blend_contrast"], r["blend_exponent"]
            su, sv = r["reveal_uv_scale"]
            h = bilinear_wrap(layer.level(layer.reveal, texels_per_unit, su), u * su, v * sv)[..., 0]
            k = np.clip(0.998 * w + 0.001, 0, 1)
            lo = np.clip((1 - k) - c * k ** e, 0, 1)
            hi = np.clip((1 - k) + c * (1 - k) ** e, 0, 1)
            with np.errstate(divide="ignore", invalid="ignore"):
                shaped = np.clip((h - lo) / (hi - lo), 0, 1)
            shaped = np.nan_to_num(shaped, nan=0.0)
            w = np.where(active, np.maximum(shaped, np.clip(100 * (w - 0.99), 0, 1)), 0)
        w = np.where(active & ~drawn, 1.0, w)
        albedo = bilinear_wrap(layer.level(layer.albedo, texels_per_unit), u, v)
        alpha = 1.0 if layer.reveal is not None else albedo[..., 3:4]
        layer_color = layer.tinted(albedo[..., :3], alpha)
        color += (layer_color - color) * w[..., None]
        drawn |= active
    return color


def bake(layers, weights, s, box, texels_per_unit, block=256):
    x0, y0, x1, y1 = box
    width, height = int(round((x1 - x0) * texels_per_unit)), int(round((y1 - y0) * texels_per_unit))
    out = np.zeros((height, width, 3), np.uint8)
    xs = x0 + (np.arange(width) + 0.5) / texels_per_unit
    for top in range(0, height, block):
        rows = np.arange(top, min(top + block, height))
        ys = y1 - (rows + 0.5) / texels_per_unit          # image row 0 is the +Y edge
        gx, gy = np.meshgrid(xs, ys)
        rgb = blend(layers, weights, s, gx, gy, texels_per_unit)
        out[rows] = np.round(linear_to_srgb(rgb) * 255).astype(np.uint8)
    return out


def mesh(s, heights, solid, box):
    ox, oy = s["world_xy_origin"]
    ups = s["units_per_sample"]
    i0, j0, i1, j1 = grid_box(s, box)
    cols, rows = i1 - i0 + 1, j1 - j0 + 1
    ii, jj = np.meshgrid(np.arange(i0, i1 + 1), np.arange(j0, j1 + 1))
    x, y, z = ox + ii * ups, oy + jj * ups, heights[jj, ii]
    dzdx = np.gradient(heights, ups, axis=1)[jj, ii]
    dzdy = np.gradient(heights, ups, axis=0)[jj, ii]
    normals = np.stack([-dzdx, -dzdy, np.ones_like(z)], -1)
    normals /= np.linalg.norm(normals, axis=-1, keepdims=True)

    cell = solid[j0:j1, i0:i1]
    cj, ci = np.nonzero(cell)
    a = cj * cols + ci
    b, c, d = a + 1, a + cols + 1, a + cols           # (i+1, j), (i+1, j+1), (i, j+1)
    faces = np.stack([np.stack([a, b, c], -1), np.stack([a, c, d], -1)], 1).reshape(-1, 3)
    keep = np.zeros(rows * cols, bool)
    keep[faces.ravel()] = True
    remap = np.cumsum(keep) - 1
    faces = remap[faces]
    positions = np.stack([x, y, z], -1).reshape(-1, 3)[keep]
    x0, y0, x1, y1 = box
    uv = np.stack([(positions[:, 0] - x0) / (x1 - x0), 1 - (positions[:, 1] - y0) / (y1 - y0)], -1)
    return {"positions": positions, "normals": normals.reshape(-1, 3)[keep], "uv": uv, "faces": faces,
            "cells": int(cell.size), "hole_cells": int((~cell).sum())}


def grid_box(s, box):
    """The sample-grid box (i0, j0, i1, j1) covering a world box, clipped to the sector."""
    ox, oy = s["world_xy_origin"]
    ups, used = s["units_per_sample"], s["grid_samples"]
    i0 = int(np.clip(np.floor((box[0] - ox) / ups), 0, used - 1))
    j0 = int(np.clip(np.floor((box[1] - oy) / ups), 0, used - 1))
    i1 = int(np.clip(np.ceil((box[2] - ox) / ups), 0, used - 1))
    j1 = int(np.clip(np.ceil((box[3] - oy) / ups), 0, used - 1))
    return i0, j0, i1, j1


def height_normal(terrain, x, y):
    """The terrain pixel shader's normal: central differences of the height array.

    The shader steps one height texel, row0.xy / (|row0.xy|^2 * width) with
    row0 = (1 / span, 0), either side along X and along Y.
    """
    span = terrain.ups * terrain.n
    sx, sy = span / terrain.cb2[30, 0], span / terrain.cb2[30, 1]
    h = terrain.surface_height
    dx = (h(x + sx, y) - h(x - sx, y)) / (2 * sx)
    dy = (h(x, y + sy) - h(x, y - sy)) / (2 * sy)
    n = np.stack([-dx, -dy, np.ones_like(dx)], -1)
    return n / np.linalg.norm(n, axis=-1, keepdims=True)


def displaced_mesh(terrain, solid, box, subdivide=1, uv_box=None):
    """The tessellated terrain over a world box, from the game's domain and pixel shaders.

    Vertices lie on the sample grid split `subdivide` times per cell, at the
    domain shader's displaced height, with the pixel shader's height normal.
    Sub-cells take their grid cell's cutout bit. uv_box is the world box the
    texture covers (default: box); v runs from its +Y edge.
    """
    s = terrain.sector
    ox, oy = s["world_xy_origin"]
    ups, sub = s["units_per_sample"], max(1, int(subdivide))
    i0, j0, i1, j1 = grid_box(s, box)
    cols, rows = (i1 - i0) * sub + 1, (j1 - j0) * sub + 1
    x = ox + (i0 + np.arange(cols) / sub) * ups
    y = oy + (j0 + np.arange(rows) / sub) * ups
    x, y = np.meshgrid(x, y)
    z = terrain.displaced_height(x, y).astype(np.float64)
    normals = height_normal(terrain, x, y)

    cell = solid[j0:j1, i0:i1].repeat(sub, 0).repeat(sub, 1)
    cj, ci = np.nonzero(cell)
    a = cj * cols + ci
    b, c, d = a + 1, a + cols + 1, a + cols           # (i+1, j), (i+1, j+1), (i, j+1)
    faces = np.stack([np.stack([a, b, c], -1), np.stack([a, c, d], -1)], 1).reshape(-1, 3)
    keep = np.zeros(rows * cols, bool)
    keep[faces.ravel()] = True
    remap = np.cumsum(keep) - 1
    faces = remap[faces]
    positions = np.stack([x, y, z], -1).reshape(-1, 3)[keep]
    u0, v0, u1, v1 = uv_box or box
    uv = np.stack([(positions[:, 0] - u0) / (u1 - u0), (v1 - positions[:, 1]) / (v1 - v0)], -1)
    undisplaced = terrain.surface_height(positions[:, 0], positions[:, 1])
    return {"positions": positions, "normals": normals.reshape(-1, 3)[keep], "uv": uv, "faces": faces,
            "cells": int(cell.size // (sub * sub)), "hole_cells": int((~solid[j0:j1, i0:i1]).sum()),
            "displacement": positions[:, 2] - undisplaced}


# ---------------------------------------------------------------- CAST writer
def cast_property(name, kind, values):
    encoded = name.encode()
    if kind == "s":
        raw, count = values.encode() + b"\0", 1
    else:
        arr = np.ascontiguousarray(values)
        raw, count = arr.tobytes(), (len(arr) if arr.ndim else 1)
    return struct.pack("<2sHI", kind.encode().ljust(2, b"\0"), len(encoded), count) + encoded + raw


def cast_node(ident, hash_value, props, children=()):
    body = b"".join(props) + b"".join(children)
    return struct.pack("<4sIQII", ident, len(body) + 24, hash_value, len(props), len(children)) + body


def write_cast(path, name, geometry, textures):
    """One mesh and one PBR material. textures maps CAST slots (albedo, normal,
    roughness, specular, ...) to image paths; a bare string is the albedo."""
    if isinstance(textures, str):
        textures = {"albedo": textures}
    material_hash, mesh_hash = 0x2000, 0x3000
    faces = geometry["faces"]
    face_kind, face_dtype = ("i", "<u4") if len(geometry["positions"]) > 0xFFFF else ("h", "<u2")
    mesh_node = cast_node(b"mesh", mesh_hash, [
        cast_property("n", "s", name),
        cast_property("vp", "3v", (geometry["positions"] * CM_PER_INCH).astype("<f4")),
        cast_property("vn", "3v", geometry["normals"].astype("<f4")),
        cast_property("u0", "2v", geometry["uv"].astype("<f4")),
        cast_property("ul", "b", np.array([1], "<u1")),
        cast_property("f", face_kind, faces.astype(face_dtype).ravel()),
        cast_property("m", "l", np.array([material_hash], "<u8")),
    ])
    files = {slot: 0x1000 + k for k, slot in enumerate(textures)}
    file_nodes = [cast_node(b"file", files[slot], [cast_property("p", "s", texture)])
                  for slot, texture in textures.items()]
    material_node = cast_node(b"matl", material_hash, [
        cast_property("n", "s", name), cast_property("t", "s", "pbr")]
        + [cast_property(slot, "l", np.array([files[slot]], "<u8")) for slot in textures], file_nodes)
    model = cast_node(b"modl", 0x100, [cast_property("n", "s", name)], [mesh_node, material_node])
    root = cast_node(b"root", 0x1, [], [model])
    path.write_bytes(struct.pack("<4sIII", b"cast", 1, 1, 0) + root)


def build(package, output, sector_index=0, box=None, texels_per_unit=0.5, name=None):
    package, output = Path(package), Path(output)
    sector_json = package / "capture" / "sectors" / f"sector_{sector_index}" / "sector.json"
    s, heights, solid, weights, layers = load_sector(package, sector_json)
    ox, oy = s["world_xy_origin"]
    span = (s["grid_samples"] - 1) * s["units_per_sample"]
    box = tuple(box) if box else (ox, oy, ox + span, oy + span)
    name = name or f"bo4_terrain_sector{sector_index}"
    output.mkdir(parents=True, exist_ok=True)
    geometry = mesh(s, heights, solid, box)
    texture = f"{name}_albedo.png"
    Image.fromarray(bake(layers, weights, s, box, texels_per_unit)).save(output / texture)
    write_cast(output / f"{name}.cast", name, geometry, texture)
    report = {"cast": f"{name}.cast", "albedo": texture, "units": "centimetres (game inches x 2.54)",
              "world_box_inches": box, "texels_per_inch": texels_per_unit,
              "vertices": len(geometry["positions"]), "triangles": len(geometry["faces"]),
              "cells": geometry["cells"], "hole_cells": geometry["hole_cells"],
              "layers": [{"slot": l.slot, "flags": l.runtime["flags"], "height_blend": l.reveal is not None}
                         for l in layers]}
    (output / f"{name}.json").write_text(json.dumps(report, indent=1) + "\n")
    return report


CAST_SLOTS = ("albedo", "normal", "roughness", "specular")


def build_emulated(package, output, sector_index=0, box=None, texels_per_unit=1.0, name=None, subdivide=2,
                   pixel_shader=None, domain_shader=None, decals=True, tile=1024, block=128, progress=None):
    """The CAST model from the game's own terrain, domain and decal shaders (see module notes)."""
    from bo4_decal_composite import DecalScene, bake_surface
    from bo4_terrain_gbuffer import TerrainScene

    package, output = Path(package), Path(output)
    terrain = TerrainScene(package, sector_index, pixel_shader, domain_shader)
    s = terrain.sector
    ox, oy = s["world_xy_origin"]
    ups = s["units_per_sample"]
    i0, j0, i1, j1 = grid_box(s, box or (-np.inf, -np.inf, np.inf, np.inf))
    box = (ox + i0 * ups, oy + j0 * ups, ox + i1 * ups, oy + j1 * ups)
    # The bake covers the mesh with an even texel count from its top-left corner.
    tpu = float(texels_per_unit)
    width = int(np.ceil((box[2] - box[0]) * tpu / 2 - 1e-9)) * 2
    height = int(np.ceil((box[3] - box[1]) * tpu / 2 - 1e-9)) * 2
    bake_box = (box[0], box[3] - height / tpu, box[0] + width / tpu, box[3])
    name = name or f"bo4_terrain_sector{sector_index}"
    output.mkdir(parents=True, exist_ok=True)

    _, solid = load_grid(package, s)
    geometry = displaced_mesh(terrain, solid, box, subdivide, bake_box)
    maps, changed = bake_surface(terrain, DecalScene(package) if decals else None, bake_box, tpu,
                                 tile, block, progress)
    files = {}
    for key, image in maps.items():
        files[key] = f"{name}_{key}.png"
        Image.fromarray(image).save(output / files[key])
    del maps
    write_cast(output / f"{name}.cast", name, geometry, {slot: files[slot] for slot in CAST_SLOTS})
    displacement = geometry["displacement"]
    report = {"cast": f"{name}.cast", "maps": files, "units": "centimetres (game inches x 2.54)",
              "world_box_inches": box, "texture_box_inches": bake_box, "texels_per_inch": tpu,
              "texture_size": [width, height], "subdivide": max(1, int(subdivide)),
              "vertices": len(geometry["positions"]), "triangles": len(geometry["faces"]),
              "cells": geometry["cells"], "hole_cells": geometry["hole_cells"],
              "displacement_inches": {"min": float(displacement.min()), "max": float(displacement.max()),
                                      "mean": float(displacement.mean())},
              "decals_drawn": len(changed), "decal_texels": {str(k): v for k, v in sorted(changed.items())},
              "far_tiling": {"layer_slots": terrain.far_tiling_slots,
                             "baked_as": "near camera: exact within 16 texture repeats of the eye"},
              "shaders": {"pixel": str(pixel_shader or terrain.default_shader()),
                          "domain": str(domain_shader or terrain.default_shader("domain"))}}
    (output / f"{name}.json").write_text(json.dumps(report, indent=1) + "\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("package", type=Path, help="package_bo4_terrain.py output (probe v46 or newer)")
    parser.add_argument("output", type=Path)
    parser.add_argument("--sector", type=int, default=0)
    parser.add_argument("--box", type=float, nargs=4, metavar=("X0", "Y0", "X1", "Y1"),
                        help="world rectangle in game inches (default: the whole sector)")
    parser.add_argument("--texels-per-inch", type=float, default=0.5)
    parser.add_argument("--name")
    parser.add_argument("--emulate", action="store_true",
                        help="build from the game's terrain, domain and decal shaders (see module notes)")
    parser.add_argument("--pixel-shader", type=Path, help="--emulate: terrain G-buffer PS; default: the package's")
    parser.add_argument("--domain-shader", type=Path, help="--emulate: terrain domain shader; default: the package's")
    parser.add_argument("--subdivide", type=int, default=2, help="--emulate: vertices per grid cell edge")
    parser.add_argument("--no-decals", action="store_true", help="--emulate: skip the volume decal pass")
    parser.add_argument("--tile", type=int, default=1024, help="--emulate: texels per bake tile edge")
    args = parser.parse_args()
    if args.emulate:
        report = lambda d, n, t: print(f"tile {d}/{n} {t:.0f}s", flush=True)
        print(json.dumps(build_emulated(args.package, args.output, args.sector, args.box, args.texels_per_inch,
                                        args.name, args.subdivide, args.pixel_shader, args.domain_shader,
                                        not args.no_decals, args.tile, progress=report), indent=1))
    else:
        print(json.dumps(build(args.package, args.output, args.sector, args.box, args.texels_per_inch, args.name),
                         indent=1))
