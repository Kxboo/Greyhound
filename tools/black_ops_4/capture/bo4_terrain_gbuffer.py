"""Run the BO4 terrain G-buffer pixel shader over a top-down grid of a sector.

One pixel shader decides how BO4 terrain looks (457b8be2b884842c on
zm_towers). It:

- tests the cutout;
- builds the surface normal from four height-array samples;
- composites every layer in the tile's layer mask (albedo, normal and detail
  maps, gloss and variance, height blending, tint, metal);
- writes three G-buffer targets.

This module runs that shader, as captured from the game and disassembled,
with bo4_dxbc_emulator on every texel of a top-down bake. It returns the
render targets and the values they pack:

- albedo: linear RGB. RT0 is an sRGB target.
- normal: world-space unit normal. RT1 xy and w carry it, encoded on a
  tetrahedron.
- gloss: 0..1. RT1 z = gloss * 0.497556 + 0.001466.
- specular: linear F0. RT2 carries Y and a checkerboarded Co/Cg.
- geo_normal: the normal of the height array before any layer normal map.
- alive: false where the cutout discarded the pixel.

The resources are rebuilt from a source package the way the shader addresses
them:

- t9 holds one 124-byte node record per 256-unit tile. The game draws
  quadtree quadrants, and a quadrant's layer mask is the OR of its tiles'
  masks. All 124 live records on zm_towers match that rule. The finest
  quadrant is one tile, which is what a close camera draws. The uv rows are
  (1/(ups*n), 0, (ups/2 - origin)/(ups*n)), matching the live records with
  the camera at 0: the uv puts sample i at texel centre i.
- t14 holds the captured 112-byte layer records.
- t0/t11/t20 are the height (R16), cutout (R32_UINT) and BC4 weight arrays.
- cb2[30 + class] = (width, height, n / width, 0). The live value is
  (1028, 1028, 1025/1028, 0).
- t24/t25/t30, t26 and t29 are the material arrays, 2048 at mip 0. A smaller
  image fills only the lower mips of its slice. Each layer record gives the
  slice and first mip of its albedo, normal, detail, reveal and gloss image,
  and every image's width shifted by that mip is checked against the array
  size.

The terrain is tessellated, and its domain shader (8b5368bcb0ce612f on
zm_towers) moves every vertex up along +Z. `displaced_height` runs that shader
on any set of points. Per vertex it:

- samples the height array;
- walks the node's displacement layer mask (t9 +8; equal to the layer mask
  +4 on every live zm_towers node);
- keeps acc = max(w * h * amount, (1 - w) * acc) in layer order, where w is the
  raw weight, h the layer's heightMap (record +80 slice and first mip) and
  amount the half in record +52 bits 16-31. A layer outside the displacement
  mask only scales acc by (1 - w);
- fades acc out between the camera distances in cb2[41]. Here the fade is held
  at 1, as for a close camera.

The pixel shader never sees the displacement: its normal comes from the height
array alone.

The pixel shader also computes the camera distance (32 `dp3 v1, v1` terms), but
only far tiling (layer flag 0x400) uses it. With every term forced to 0, the
zm_towers bake is bit-identical; no zm_towers layer sets 0x400.

Far tiling scales a layer's uv by 1 / (16 floor(r / 4) + 1), where
r = sqrt(d |uv row|) and d is the camera distance, so r is measured in texture
repeats. The first fifth of each band blends from the band before, and the
domain shader divides the displaced height by the root of the same scale.
Within 16 repeats of the camera every factor is exactly 1, the same as with
the flag clear. A bake has no camera (v1 is the world point, which would put
it at the origin), so `far_tiling="near"` clears the flag and bakes the
close-up look. On zm_white, where most layers set 0x400, that is bit-identical
in RT0-RT2 and displacement to keeping the flag with both shaders' distance
patched to 0.
"""

# Support direct execution and the isolated packaged Python runtime.
import sys as _tool_sys
from pathlib import Path as _ToolPath
TOOLS_ROOT = next(p for p in _ToolPath(__file__).resolve().parents if (p / "tool_bootstrap.py").is_file())
_tool_sys.path.insert(0, str(TOOLS_ROOT))
import tool_bootstrap as _tool_bootstrap
_tool_bootstrap.activate(__file__)
import argparse
import ctypes
import json
import struct
import time
from pathlib import Path

import numpy as np
from PIL import Image

from bo4_dxbc_emulator import Shader, Texture, VirtualArray, srgb_encode
from verify_bo4_terrain_package import decode_bc4

NODE_RECORD_BYTES = 124
LAYER_RECORD_BYTES = 112
CB2_ROWS = 34
# Domain shader: patch records (t4) name the node (+28 >> 16) and the sector
# transform (+16) in t5, whose rows 0-2 are a 3x4 local-to-world matrix.
PATCH_RECORD_BYTES = 32
TRANSFORM_RECORD_BYTES = 64
DS_CB2_ROWS = 42
# Record +84 bits 20-21 pick the albedo array: 0 -> t24, 1 -> t25, anything else t30.
ALBEDO_REGISTER = {0: 24, 1: 25}
GLOSS_SCALE, GLOSS_BIAS = 0.497556, 0.001466


def disassemble(dxbc):
    """D3DCompiler_47's disassembly of a DXBC container."""
    d3d = ctypes.WinDLL("D3DCompiler_47.dll")
    blob = ctypes.c_void_p()
    if d3d.D3DDisassemble(ctypes.c_char_p(dxbc), ctypes.c_size_t(len(dxbc)), 0, None, ctypes.byref(blob)):
        raise ValueError("D3DDisassemble rejected the container")
    table = ctypes.cast(ctypes.cast(blob, ctypes.POINTER(ctypes.c_void_p))[0], ctypes.POINTER(ctypes.c_void_p))
    method = lambda slot, restype: ctypes.WINFUNCTYPE(restype, ctypes.c_void_p)(table[slot])
    text = ctypes.string_at(method(3, ctypes.c_void_p)(blob), method(4, ctypes.c_size_t)(blob)).decode("latin1")
    method(2, ctypes.c_ulong)(blob)
    return text


def load_shader(path):
    path = Path(path)
    if path.suffix.lower() == ".dxbc":
        return Shader(disassemble(path.read_bytes()))
    return Shader(path.read_text(encoding="latin1").replace("\x00", ""))


def half(bits):
    return struct.unpack("<e", struct.pack("<H", bits & 0xFFFF))[0]


def rgba(path):
    return np.asarray(Image.open(path).convert("RGBA"))


def decode_tetra_normal(rt1):
    """RT1 (x, y, _, w) back to a world normal: the inverse the decal shaders use."""
    x = (rt1[..., 0] - 0.5) / 0.588235
    y = (rt1[..., 1] - 0.5) / 0.588235
    face = np.rint(rt1[..., 3] * 3).astype(np.int64)
    d = x * x + y * y
    s = np.sqrt(np.maximum(2 - d, 0))
    a = (1 - d) * 0.57735
    n = np.stack([a + s * x * 0.408248 - s * y * 0.707107,
                  a - s * x * 0.816497,
                  a + s * x * 0.408248 + s * y * 0.707107], -1)
    # The encoder folds the normal into the face whose axis (1, 1, 1) * signs is closest.
    signs = np.array([[1, 1, 1], [1, -1, -1], [-1, 1, -1], [-1, -1, 1]], np.float64)
    return n * signs[face]


class TerrainScene:
    """A sector's shader resources, rebuilt from a source package."""

    def __init__(self, package, sector_index=0, shader_path=None, domain_path=None, far_tiling="near"):
        self.package = package = Path(package)
        self.domain_path, self._domain = domain_path, None
        sector_dir = package / "capture" / "sectors" / f"sector_{sector_index}"
        self.sector = s = json.loads((sector_dir / "sector.json").read_text())
        if s.get("local_to_world"):
            # The node uv rows built below are the unrotated ones; a rotated sector needs its rotation in them.
            raise NotImplementedError(f"sector {sector_index} is rotated; the shader bake only builds unrotated nodes")
        doc = json.loads((package / "capture" / "terraingfx.json").read_text())
        self.materials = {m["name"]: m for m in doc["materials"]}
        self.shader = load_shader(shader_path or self.default_shader())

        self.n, self.ups = s["grid_samples"], s["units_per_sample"]
        self.origin = np.array(s["world_xy_origin"], np.float64)
        self.tiles = s["tiles_across"]
        self.tile_size = (self.n - 1) * self.ups / self.tiles
        width = s["height"]["width"]
        heights = np.fromfile(package / s["height"]["file"], "<u2").reshape(s["height"]["height"], width)
        self.height_bias = s["world_height_bias"]
        self.height_range = s["height"]["scale"] * 65535
        c, lw = s["cutout"], s["layer_weights"]
        words = np.fromfile(package / c["file"], "<u4").reshape(c["height"], c["width"])
        data = (package / lw["file"]).read_bytes()
        per = lw["bytes_per_slice"]
        weights = np.stack([decode_bc4(data[k * per:(k + 1) * per], lw["width"], lw["height"])
                            for k in range(lw["slices"])]).astype(np.float32)
        self.heights = heights.astype(np.float32) / 65535
        self.layers = sorted(s["layers"], key=lambda r: r["slot"])
        self.records = [bytes.fromhex(r["runtime"]["raw_hex"]) for r in self.layers]
        # +32 indexes the shared weight array; t20 here holds only this sector's run.
        base = lw.get("array_slice_base", 0)
        if base:
            self.records = [rec[:32] + struct.pack("<I", struct.unpack_from("<I", rec, 32)[0] - base) + rec[36:]
                            if struct.unpack_from("<I", rec, 32)[0] < 4094 else rec for rec in self.records]
        # Far tiling is the only path that reads the camera distance, and a bake
        # has no camera: v1 is the world point, so it would sit at the origin.
        # Within 16 texture repeats of the camera both shaders' far-tiling
        # factors are exactly 1, the same as with the flag clear, so "near"
        # bakes the close-up look by clearing it; "keep" leaves it to the caller.
        self.far_tiling_slots = [r["slot"] for r, rec in zip(self.layers, self.records)
                                 if struct.unpack_from("<I", rec, 52)[0] & 0x400]
        if self.far_tiling_slots and far_tiling == "refuse":
            raise NotImplementedError(f"layers {self.far_tiling_slots} use far tiling (flag 0x400), "
                                      "which depends on the camera distance")
        if far_tiling == "near":
            self.records = [rec[:52] + struct.pack("<I", struct.unpack_from("<I", rec, 52)[0] & ~0x400) + rec[56:]
                            for rec in self.records]
        elif far_tiling not in ("keep", "refuse"):
            raise ValueError(f"far_tiling must be near, keep or refuse, not {far_tiling!r}")
        self.masks = np.fromfile(package / s["tile_layer_mask"]["file"], "<" + s["tile_layer_mask"].get("dtype", "u2")
                                 ).reshape(self.tiles, self.tiles)

        grid = {"address": "clamp"}
        self.resources = {
            0: Texture([self.heights[None, :, :, None]], **grid),
            11: Texture([words[None, :, :, None]], **grid),
            20: Texture([weights[:, :, :, None]], **grid),
        }
        self.resources.update(self.material_arrays())
        self.structured = {9: self.node_records(), 14: b"".join(self.records)}
        cb2 = np.zeros((CB2_ROWS, 4), np.float32)
        for k in range(4):
            cb2[30 + k] = (width, s["height"]["height"], self.n / width, 0.0)
        self.cb2 = cb2
        # Taps: the height-array normal once it is built, and the unpacked
        # G-buffer values at the end (r4 = normal, gloss; r11 albedo; r14 F0).
        self.geo_pc = next(pc for pc, ins in enumerate(self.shader.prog)
                           if ins.op == "ubfe" and ins.args[0].raw.startswith("r2.y"))
        self.ret_pc = self.shader.find("ret")

    def default_shader(self, role="gbuffer_cutout"):
        shaders = self.package / "capture" / "shaders" / "terrain"
        index = shaders / "shaders.json"
        if index.is_file():
            table = json.loads(index.read_text())
            rows = [row for row in table["shaders"] if row.get("role") == role]
            if rows:
                return shaders / rows[0]["file"]
        raise FileNotFoundError(f"The package has no terrain {role} shader; pass its path")

    def domain_shader(self):
        if self._domain is None:
            self._domain = load_shader(self.domain_path or self.default_shader("domain"))
        return self._domain

    # ----------------------------------------------------------- resources
    def node_records(self):
        """One t9 record per tile, laid out like the live ones (see module notes)."""
        s, span = self.sector, self.ups * self.n
        count = len(self.layers)
        flags = [struct.unpack_from("<I", r, 52)[0] for r in self.records]
        out = bytearray()
        for j in range(self.tiles):
            for i in range(self.tiles):
                mask = int(self.masks[j, i])
                displacement = max((half(f >> 16) for k, f in enumerate(flags) if mask >> k & 1), default=0.0)
                r = bytearray(NODE_RECORD_BYTES)
                struct.pack_into("<3I", r, 0, 8, mask, mask)
                struct.pack_into("<4f", r, 20, self.tile_size, self.tile_size,
                                 -0.5 * (self.n - 1) * self.ups + i * self.tile_size,
                                 -0.5 * (self.n - 1) * self.ups + j * self.tile_size)
                struct.pack_into("<2f", r, 44, *self.origin)
                struct.pack_into("<I", r, 52, 1)
                struct.pack_into("<3f", r, 56, 1 / span, 0.0, (self.ups / 2 - self.origin[0]) / span)
                struct.pack_into("<3f", r, 72, 0.0, 1 / span, (self.ups / 2 - self.origin[1]) / span)
                struct.pack_into("<2f", r, 96, self.height_bias, self.height_range)
                struct.pack_into("<3I", r, 108,
                                 struct.unpack("<H", struct.pack("<e", displacement))[0] << 16,
                                 int((self.n - 1) * self.ups), count << 24)
                out += r
        return bytes(out)

    def binding(self, material, semantic, raw=False):
        for b in self.materials[material]["bindings"]:
            if b.get("engine_semantic") == semantic and b.get("png_file"):
                key = "raw_png_file" if raw and b.get("raw_png_file") else "png_file"
                if raw and not b.get("raw_png_file") and b.get("export", {}).get("patch"):
                    raise ValueError(f"{material} {semantic}: only a patched export exists; recapture with probe v47")
                return self.package / b[key], b
        return None, None

    def material_arrays(self):
        """t24/t25/t30 albedo, t26 gloss/reveal/height, t29 normal + detail."""
        slots = {24: {}, 25: {}, 30: {}, 26: {}, 29: {}}
        bases = {k: set() for k in slots}
        inert = set()

        def put(register, index, path, min_mip, kind):
            if path is None:
                return
            key = str(path)
            if index in slots[register]:
                if slots[register][index][0] != key:
                    raise ValueError(f"t{register} slice {index} is claimed by two images")
                return
            slots[register][index] = (key, kind)
            width = Image.open(path).size[0]
            bases[register].add(width << min_mip)

        for layer, rec in zip(self.layers, self.records):
            u = struct.unpack("<28I", rec)
            flags, material = u[13], layer["material"]
            if flags & 0x1:
                register = ALBEDO_REGISTER.get((u[21] >> 20) & 3, 30)
                put(register, u[21] & 0xFFFF, self.binding(material, "colorMap")[0], (u[21] >> 16) & 0xF, "srgb")
            put(29, u[23] & 0xFFFF, self.binding(material, "normalMap", raw=True)[0], (u[23] >> 16) & 0x3F, "rgba")
            if flags & 0x80:
                put(29, u[24] & 0xFFFF, self.binding(material, "detailMap", raw=True)[0], (u[24] >> 16) & 0x3F, "rgba")
            if flags & 0x4:
                put(26, u[25] & 0xFFFF, self.binding(material, "revealMap")[0], (u[25] >> 16) & 0x3F, "r")
            put(26, u[26] & 0xFFFF, self.binding(material, "glossMap")[0], (u[26] >> 16) & 0x3F, "r")
            # The domain shader's displacement map (its t20 is this array).
            height_map = self.binding(material, "heightMap")[0]
            put(26, u[20] & 0xFFFF, height_map, (u[20] >> 16) & 0x3F, "r")
            # The domain shader samples every flag-0x2 layer's slice before it
            # multiplies by the amount; with amount 0 (zm_white's grass and
            # asphalt, which carry no heightMap) any texel gives the same result.
            if flags & 0x2 and height_map is None and half(flags >> 16) == 0:
                inert.add(u[20] & 0xFFFF)

        arrays = {}
        for register, table in slots.items():
            if len(bases[register]) > 1:
                raise ValueError(f"t{register}: images disagree on the array size {sorted(bases[register])}")
            base = bases[register].pop() if bases[register] else 2048
            textures = {}
            for index, (path, kind) in table.items():
                texels = rgba(path)
                if kind == "r":
                    texels = np.ascontiguousarray(texels[:, :, :1])
                textures[index] = Texture.from_image(texels, srgb=kind == "srgb")
            if register == 26:
                for index in inert - set(table):
                    textures[index] = Texture([np.zeros((1, 1, 1), np.float32)])
            arrays[register] = VirtualArray(textures, (base, base))
        return arrays

    # ---------------------------------------------------------------- run
    def surface_height(self, x, y):
        """Bilinear height-array z at world (x, y): the undisplaced surface."""
        s = np.clip((x - self.origin[0]) / self.ups, 0, self.n - 1)
        t = np.clip((y - self.origin[1]) / self.ups, 0, self.n - 1)
        i, j = np.minimum(np.floor(s).astype(np.int64), self.n - 2), np.minimum(np.floor(t).astype(np.int64), self.n - 2)
        fs, ft = s - i, t - j
        h = self.heights
        z = ((h[j, i] * (1 - fs) + h[j, i + 1] * fs) * (1 - ft)
             + (h[j + 1, i] * (1 - fs) + h[j + 1, i + 1] * fs) * ft)
        return self.height_bias + z * self.height_range

    def tile_index(self, x, y):
        ti = np.clip(np.floor((x - self.origin[0]) / self.tile_size), 0, self.tiles - 1).astype(np.int64)
        tj = np.clip(np.floor((y - self.origin[1]) / self.tile_size), 0, self.tiles - 1).astype(np.int64)
        return tj * self.tiles + ti

    def displaced_height(self, x, y, chunk=1 << 18):
        """World z of the tessellated surface at (x, y), from the game's domain shader.

        Each point is a domain point of a patch whose three control points all
        sit at (x, y). The patch record names the point's tile node and an
        identity sector transform, so the shader's local frame is the world.
        cb2 rows 8-11 are an identity view-projection, so o0 is the world point.
        """
        shader = self.domain_shader()
        x = np.asarray(x, np.float64)
        y = np.asarray(y, np.float64)
        shape = x.shape
        x, y = x.ravel(), y.ravel()
        patches = bytearray(PATCH_RECORD_BYTES * self.tiles * self.tiles)
        for index in range(self.tiles * self.tiles):
            struct.pack_into("<I", patches, index * PATCH_RECORD_BYTES + 28, index << 16)
        transform = struct.pack("<16f", 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0)
        cb2 = np.zeros((DS_CB2_ROWS, 4), np.float32)
        cb2[8:12] = np.eye(4, dtype=np.float32)
        cb2[30:34] = self.cb2[30:34]
        cb2[41] = (1e30, 2e30, 0, 0)            # displacement fade distances: never reached
        resources = {0: self.resources[0], 11: self.resources[20], 20: self.resources[26]}
        structured = {4: bytes(patches), 5: transform, 9: self.structured[9], 14: self.structured[14]}
        out = np.empty(x.size, np.float32)
        for start in range(0, x.size, chunk):
            k = slice(start, min(start + chunk, x.size))
            n = k.stop - k.start
            xy = np.stack([x[k], y[k]], 1).astype(np.float32)
            node = np.zeros((n, 4), np.uint32)
            node[:, 0] = self.tile_index(x[k], y[k])
            inputs = {"vDomain": np.array([1, 0, 0, 0], np.float32), "vicp0_0": xy, "vicp1_0": xy,
                      "vicp2_0": xy, "vicp0_1": node, "vicp1_1": node, "vicp2_1": node}
            outs, _ = shader.run(n, inputs=inputs, cbuffers={2: cb2}, resources=resources, structured=structured)
            out[k] = outs[0][:, 2]
        return out.reshape(shape)

    def run_block(self, x, y, pixel_x, pixel_y):
        """Shade one (H, W) block of world points; H and W must be even (2x2 quads)."""
        h, w = x.shape
        n = h * w
        z = self.surface_height(x, y)
        v0 = np.zeros((n, 4), np.uint32)
        v0[:, 0] = self.tile_index(x, y).ravel()
        v1 = np.stack([x.ravel(), y.ravel(), z.ravel()], 1).astype(np.float32)
        v2 = np.stack([pixel_x.ravel() + 0.5, pixel_y.ravel() + 0.5], 1).astype(np.float32)
        taps = {self.geo_pc: ["r1"], self.ret_pc: ["r4", "r11", "r14"]}
        outs, alive = self.shader.run(n, inputs={"v0": v0, "v1": v1, "v2": v2}, cbuffers={2: self.cb2},
                                      resources=self.resources, structured=self.structured,
                                      grid=(h, w), taps=taps)
        t = self.shader.tapped
        normal = t[self.ret_pc]["r4"][:, :3]
        normal = normal / np.maximum(np.linalg.norm(normal, axis=1, keepdims=True), 1e-20)
        shape = (h, w)
        return {
            "alive": alive.reshape(shape),
            "rt0": outs[0].reshape(shape + (4,)), "rt1": outs[1].reshape(shape + (4,)),
            "rt2": outs[2].reshape(shape + (4,)),
            "albedo": t[self.ret_pc]["r11"][:, :3].reshape(shape + (3,)),
            "normal": normal.reshape(shape + (3,)),
            "gloss": t[self.ret_pc]["r4"][:, 3].reshape(shape),
            "specular": t[self.ret_pc]["r14"][:, :3].reshape(shape + (3,)),
            "geo_normal": t[self.geo_pc]["r1"][:, 1:4].reshape(shape + (3,)),
            "height": z.astype(np.float32),
        }

    def bake(self, box, texels_per_unit, block=128, progress=None):
        """Shade a world rectangle top-down; image row 0 is the +Y edge."""
        x0, y0, x1, y1 = box
        width = int(round((x1 - x0) * texels_per_unit)) // 2 * 2
        height = int(round((y1 - y0) * texels_per_unit)) // 2 * 2
        result = None
        started = time.time()
        blocks = [(r, c) for r in range(0, height, block) for c in range(0, width, block)]
        for done, (r, c) in enumerate(blocks, 1):
            rows, cols = np.arange(r, min(r + block, height)), np.arange(c, min(c + block, width))
            px, py = np.meshgrid(cols, rows)
            wx = x0 + (px + 0.5) / texels_per_unit
            wy = y1 - (py + 0.5) / texels_per_unit
            part = self.run_block(wx, wy, px, py)
            if result is None:
                result = {k: np.zeros((height, width) + v.shape[2:], v.dtype) for k, v in part.items()}
            for k, v in part.items():
                result[k][r:r + len(rows), c:c + len(cols)] = v
            if progress:
                progress(done, len(blocks), time.time() - started)
        return result


def tangent_space(normal, geo):
    """World normals -> an OpenGL (+Y) tangent-space map on a +X/+Y parameterised heightfield."""
    t = np.zeros_like(geo)
    t[..., 0] = 1
    t = t - geo * geo[..., :1]
    t /= np.maximum(np.linalg.norm(t, axis=-1, keepdims=True), 1e-20)
    b = np.cross(geo, t)
    return np.stack([(normal * t).sum(-1), (normal * b).sum(-1), (normal * geo).sum(-1)], -1)


def save_maps(result, folder, name):
    """PNG maps for a CAST material: albedo (sRGB), tangent normal, gloss, roughness, specular."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    alive = result["alive"][..., None]
    to8 = lambda a: np.round(np.clip(a, 0, 1) * 255).astype(np.uint8)
    albedo = np.concatenate([srgb_encode(result["albedo"]), alive], -1)
    Image.fromarray(to8(albedo)).save(folder / f"{name}_albedo.png")
    ts = tangent_space(result["normal"].astype(np.float64), result["geo_normal"].astype(np.float64))
    Image.fromarray(to8(ts * 0.5 + 0.5)).save(folder / f"{name}_normal.png")
    gloss = np.clip(result["gloss"], 0, 1)
    Image.fromarray(to8(gloss)).save(folder / f"{name}_gloss.png")
    # gloss g is log2(specular power) / 17 (the shader adds variance as 2^(-17 g) + v).
    power = np.exp2(17 * gloss)
    roughness = np.sqrt(np.sqrt(2 / (power + 2)))
    Image.fromarray(to8(roughness)).save(folder / f"{name}_roughness.png")
    Image.fromarray(to8(srgb_encode(result["specular"]))).save(folder / f"{name}_specular.png")
    return {k: f"{name}_{k}.png" for k in ("albedo", "normal", "gloss", "roughness", "specular")}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("package", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--sector", type=int, default=0)
    parser.add_argument("--shader", type=Path, help="terrain G-buffer PS (.dxbc or .asm); default: the package's")
    parser.add_argument("--box", type=float, nargs=4, metavar=("X0", "Y0", "X1", "Y1"), required=True)
    parser.add_argument("--texels-per-inch", type=float, default=1.0)
    parser.add_argument("--block", type=int, default=128)
    parser.add_argument("--name", default="terrain_gbuffer")
    args = parser.parse_args()
    scene = TerrainScene(args.package, args.sector, args.shader)
    report = lambda d, n, t: print(f"block {d}/{n} {t:.0f}s", flush=True)
    result = scene.bake(args.box, args.texels_per_inch, args.block, report)
    args.output.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(args.output / f"{args.name}.npz", **result)
    print(json.dumps(save_maps(result, args.output, args.name), indent=1))
