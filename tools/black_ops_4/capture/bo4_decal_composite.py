"""Draw BO4 volume decals onto a baked terrain G-buffer with the game's decal pixel shaders.

BO4 draws its volume decals after the opaque G-buffer pass. Each decal is a
box. Its material's pixel shader (18 of them on zm_towers):

- reads the scene depth (t0) and the G-buffer normal target (t6);
- rebuilds the world position of every pixel it covers;
- drops pixels outside the box, or facing away from the box's projection axis;
- writes albedo, gloss, specular and sometimes a normal through the blend
  state of its material.

bo4_volume_decals holds the records. This module replays that pass over a
top-down bake from bo4_terrain_gbuffer.

Camera
    The shaders rebuild the world position from depth and the pixel position
    through the camera rows of cb2 (12, 13, 16, 17, 18, 24, 61 and 92). A bake
    has no camera, so every draw gets one looking straight down. Each lane's
    pixel position and depth are then solved so the shader's own
    reconstruction lands on the texel's world point (x, y, terrain z). The
    pixel position is only used there and to address the G-buffer loads,
    which here return the lane's own texel, so solving it per lane changes
    nothing else.

Render targets
    They keep their formats between draws: RT0 is sRGB 8-bit and blends in
    linear, and RT1 and RT2 are 10:10:10:2 UNORM. These formats are inferred
    from the shaders' encodings, not read from the device. Each draw's outputs are
    clamped, blended with the material's blend state and write mask, and
    quantized again, as the output merger does.

Bindings
    Textures and samplers bind by the material's pass arguments (slot =
    register). The one declared texture that no argument names is the shared
    reveal atlas. Sampler states are decoded from the material's words (see
    bo4_dxbc_emulator.Sampler).

Draw order
    Read from a live zm_towers frame. The engine writes its visible decals'
    records as a series of lists, and a decal can appear in several of them.
    Each list is sorted by priority (+0xC8) descending, then by material
    pointer ascending. The instance buffer is 0, 1, 2, ..., so within a draw
    call records draw in list order. The order the per-material draw calls
    are issued in was not captured; they are taken to follow the list too,
    which puts priority 1 last, on top. The art agrees: murals, overlays and
    moss have priorities 15-21, while blood, soot, footprints and puddles
    have 1-2. draw_key does the same sort. Ties have no fixed order in the
    engine, so they keep asset order here.

Fixed by the shaders or seen live
    - v1 = 1: the one decal vertex shader (4a6c71bc) writes o1 = (1, 1, 1, 1).
    - Record +128.w = 0 on all 311 live records, so the angle test uses the
      G-buffer normal (the --depth-normal switch sets 1).
    - cb2[89].w is time. Only dba9e9d1, the puddle and waterfall shader, reads
      it: it scrolls two normal-map UV sets by cb0[4] * time. Bakes freeze at
      time 0.
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
import time
from collections import OrderedDict
from pathlib import Path

import numpy as np
from PIL import Image

from bo4_dxbc_emulator import LaneTexture, Sampler, Texture, srgb_decode_table, srgb_encode
from bo4_terrain_gbuffer import GLOSS_BIAS, GLOSS_SCALE, TerrainScene, decode_tetra_normal, load_shader, tangent_space
from bo4_volume_decals import footprint, gpu_record, world_to_local

CB2_ROWS = 114
# Depth below 0.984375 decodes as 1/w = depth * 1.015873 in every decal shader.
DEPTH_SCALE = 1.015873
# The synthetic camera sits this far above the highest texel of a draw.
CAMERA_CLEARANCE = 64.0

# How a decal image's DXGI format reads in a shader.
SRGB_FORMATS = {29, 72, 75, 78, 91, 99}
RGBA_FORMATS = {28, 71, 74, 77, 87, 98}
R_FORMATS = {61, 80}
RG_FORMATS = {83}

# Render targets: bits per channel; RT0 stores sRGB colour.
TARGET_BITS = {0: (8, 8, 8, 8), 1: (10, 10, 10, 2), 2: (10, 10, 10, 2)}
SRGB_TARGETS = {0}
_SRGB8 = srgb_decode_table()


def encode_target(rt, values):
    """Linear values -> the integers render target rt stores."""
    v = np.clip(np.nan_to_num(np.asarray(values, np.float32)), 0, 1)
    if rt in SRGB_TARGETS:
        v = v.copy()
        v[..., :3] = srgb_encode(v[..., :3])
    scale = np.array([(1 << b) - 1 for b in TARGET_BITS[rt]], np.float32)
    return np.rint(v * scale).astype(np.uint16)


def decode_target(rt, stored):
    """Stored integers -> the linear values a load or the blender reads."""
    scale = np.array([(1 << b) - 1 for b in TARGET_BITS[rt]], np.float32)
    v = stored.astype(np.float32) / scale
    if rt in SRGB_TARGETS:
        v[..., :3] = _SRGB8[stored[..., :3]]
    return v


def _factor(name, src, dst, alpha):
    """One D3D11 blend factor, (n, 4) or (n, 1)."""
    ones = np.ones_like(src[:, :1])
    if name == "ZERO":
        return 0 * ones
    if name == "ONE":
        return ones
    if name == "SRC_ALPHA":
        return src[:, 3:4]
    if name == "INV_SRC_ALPHA":
        return 1 - src[:, 3:4]
    if name == "DEST_ALPHA":
        return dst[:, 3:4]
    if name == "INV_DEST_ALPHA":
        return 1 - dst[:, 3:4]
    if name in ("SRC_COLOR", "INV_SRC_COLOR", "DEST_COLOR", "INV_DEST_COLOR"):
        c = src if name.endswith("SRC_COLOR") else dst
        c = c[:, 3:4] if alpha else c[:, :3]
        return 1 - c if name.startswith("INV") else c
    if name == "SRC_ALPHA_SAT":
        return ones if alpha else np.minimum(src[:, 3:4], 1 - dst[:, 3:4])
    raise ValueError(f"blend factor {name} is not modelled")


def _combine(op, a, b):
    if op == "ADD":
        return a + b
    if op == "SUBTRACT":
        return a - b
    if op == "REV_SUBTRACT":
        return b - a
    raise ValueError(f"blend op {op} is not modelled")


def blend(state, src, dst):
    """The output merger for one target: src (shader output) and dst are (n, 4) linear values."""
    if not state["enable"]:
        return src
    out = np.empty_like(dst)
    for channels, alpha, s_name, d_name, op in (
            (slice(0, 3), False, state["src"], state["dst"], state["op"]),
            (slice(3, 4), True, state["src_alpha"], state["dst_alpha"], state["op_alpha"])):
        s, d = src[:, channels], dst[:, channels]
        if op in ("MIN", "MAX"):
            out[:, channels] = (np.minimum if op == "MIN" else np.maximum)(s, d)
        else:
            out[:, channels] = _combine(op, s * _factor(s_name, src, dst, alpha),
                                        d * _factor(d_name, src, dst, alpha))
    return out


class GBuffer:
    """RT0-RT2 over a top-down grid, held as the integers their formats store.

    Row 0 is the +Y edge of `box`; column 0 its -X edge.
    """

    def __init__(self, box, texels_per_unit, height, alive, targets):
        self.box = tuple(float(b) for b in box)
        self.tpu = float(texels_per_unit)
        self.z = np.asarray(height, np.float32)
        self.alive = np.asarray(alive, bool)
        self.stored = {rt: encode_target(rt, targets[rt]) for rt in TARGET_BITS}

    @classmethod
    def from_terrain(cls, result, box, texels_per_unit):
        return cls(box, texels_per_unit, result["height"], result["alive"],
                   {rt: result[f"rt{rt}"] for rt in TARGET_BITS})

    @property
    def shape(self):
        return self.z.shape

    def world(self, rows, cols):
        """World x, y of the texel centres in a rows x cols window (slices)."""
        x0, _, _, y1 = self.box
        c = np.arange(cols.start, cols.stop)
        r = np.arange(rows.start, rows.stop)
        return np.meshgrid(x0 + (c + 0.5) / self.tpu, y1 - (r + 0.5) / self.tpu)

    def window(self, lo, hi):
        """The texel window covering world bounds lo..hi, grown to whole 2x2 quads."""
        x0, _, _, y1 = self.box
        h, w = self.shape
        c0 = max(0, int(np.floor((lo[0] - x0) * self.tpu)) // 2 * 2)
        c1 = min(w, (int(np.ceil((hi[0] - x0) * self.tpu)) + 1) // 2 * 2)
        r0 = max(0, int(np.floor((y1 - hi[1]) * self.tpu)) // 2 * 2)
        r1 = min(h, (int(np.ceil((y1 - lo[1]) * self.tpu)) + 1) // 2 * 2)
        if c1 <= c0 or r1 <= r0:
            return None
        return slice(r0, r1), slice(c0, c1)

    def read(self, rt, rows=slice(None), cols=slice(None)):
        return decode_target(rt, self.stored[rt][rows, cols])

    def write(self, rt, rows, cols, values, mask, write_mask):
        """Store linear values where mask holds, in the channels write_mask enables."""
        new = encode_target(rt, values)
        view = self.stored[rt][rows, cols]
        for c in range(4):
            if write_mask >> c & 1:
                view[..., c][mask] = new[..., c][mask]

    def surface(self):
        """What the lighting pass reads back: albedo, world normal, gloss, specular F0."""
        rt0, rt1, rt2 = (self.read(rt) for rt in TARGET_BITS)
        normal = decode_tetra_normal(rt1.astype(np.float64))
        normal /= np.maximum(np.linalg.norm(normal, axis=-1, keepdims=True), 1e-20)
        flag = rt1[..., 2] >= 0.5
        gloss = (rt1[..., 2] - np.where(flag, 0.5, GLOSS_BIAS)) / GLOSS_SCALE
        return {"albedo": rt0[..., :3], "normal": normal.astype(np.float32),
                "gloss": np.clip(gloss, 0, 1).astype(np.float32),
                "specular": checkerboard_specular(rt2), "alive": self.alive, "rt0_alpha": rt0[..., 3],
                "gloss_flag": flag}


def checkerboard_specular(rt2):
    """RT2 (Y, chroma) -> RGB F0. Texels with x and y of equal parity carry Co = R - B, the
    others Cg = G - (R + B) / 2; the missing one is the mean of the four neighbours."""
    y = rt2[..., 0]
    chroma = rt2[..., 1] * 2 - 1
    h, w = y.shape
    rows, cols = np.mgrid[0:h, 0:w]
    co_here = (rows & 1) == (cols & 1)
    padded = np.pad(chroma, 1, mode="edge")
    count = np.zeros_like(chroma)
    total = np.zeros_like(chroma)
    for dr, dc in ((0, 1), (2, 1), (1, 0), (1, 2)):
        n = padded[dr:dr + h, dc:dc + w]
        # A replicated edge copies this texel's own kind of chroma: skip it.
        valid = np.ones_like(chroma, bool)
        if dr == 0:
            valid[0] = False
        if dr == 2:
            valid[-1] = False
        if dc == 0:
            valid[:, 0] = False
        if dc == 2:
            valid[:, -1] = False
        total += np.where(valid, n, 0)
        count += valid
    other = total / np.maximum(count, 1)
    co = np.where(co_here, chroma, other)
    cg = np.where(co_here, other, chroma)
    rgb = np.stack([y - cg / 2 + co / 2, y + cg / 2, y - cg / 2 - co / 2], -1)
    return np.clip(rgb, 0, 1).astype(np.float32)


def draw_key(decal):
    """The engine's decal sort: priority descending, then material pointer ascending.

    Packages written before the field was named keep it as unknown_c8.
    """
    priority = decal["priority"] if "priority" in decal else decal["unknown_c8"]
    return -priority, int(decal["material"], 16)


class DecalMaterial:
    """What one decal material binds for its G-buffer draw."""

    def __init__(self, shader, resources, samplers, cb0, blend_states, atlas_register):
        self.shader, self.resources, self.samplers = shader, resources, samplers
        self.cb0, self.blend, self.atlas_register = cb0, blend_states, atlas_register


class DecalScene:
    """A package's volume decals, their materials and the shaders that draw them."""

    def __init__(self, package, cache=6):
        self.package = Path(package)
        doc = json.loads((self.package / "capture" / "decals" / "decals.json").read_text())
        self.decals = doc["decals"]
        self.materials = {m["pointer"]: m for m in doc["materials"]}
        self.atlas_row = doc.get("atlas")
        self._atlas = None
        self._shaders = {}
        self._bound = OrderedDict()
        self._images = OrderedDict()
        self.cache = cache

    # ------------------------------------------------------------ bindings
    def image(self, row):
        """A decal image as a Texture, read the way its DXGI format reads in a shader."""
        key = row["png_file"]
        if key in self._images:
            self._images.move_to_end(key)
            return self._images[key]
        fmt = row["dxgi_format"]
        with Image.open(self.package / key) as im:
            texels = np.asarray(im.convert("RGBA"))
        if fmt in SRGB_FORMATS:
            texture = Texture.from_image(texels, srgb=True)
        elif fmt in RGBA_FORMATS:
            texture = Texture.from_image(texels)
        elif fmt in R_FORMATS:
            texture = Texture.from_image(np.ascontiguousarray(texels[:, :, :1]))
        elif fmt in RG_FORMATS:
            texture = Texture.from_image(np.ascontiguousarray(texels[:, :, :2]))
        else:
            raise ValueError(f"{row['name']}: DXGI format {fmt} is not mapped to a shader read")
        self._images[key] = texture
        while len(self._images) > 4 * self.cache:
            self._images.popitem(last=False)
        return texture

    def atlas(self):
        if self._atlas is None:
            if not self.atlas_row or not self.atlas_row.get("png_file"):
                raise FileNotFoundError("the package has no volume decal reveal atlas")
            self._atlas = self.image(self.atlas_row)
        return self._atlas

    def shader(self, material):
        digest = material["pixel_shader"]["sha1_16"]
        if digest not in self._shaders:
            self._shaders[digest] = load_shader(self.package / material["pixel_shader"]["file"])
        return self._shaders[digest]

    def material(self, pointer):
        if pointer in self._bound:
            self._bound.move_to_end(pointer)
            return self._bound[pointer]
        m = self.materials[pointer]
        shader = self.shader(m)
        images = {im["raw_semantic"]: im for im in m["images"]}
        states = {s["hash"]: s["state"] for s in m["samplers"]}
        resources, samplers = {}, {}
        for arg in m["pass_arguments"]:
            if arg.get("count", 1) != 1:
                raise ValueError(f"{m['name']}: pass argument {arg['hash']} binds {arg['count']} items")
            if arg["kind"] == "texture":
                if arg["hash"] not in images:
                    raise KeyError(f"{m['name']}: no image for texture argument {arg['hash']}")
                resources[arg["slot"]] = self.image(images[arg["hash"]])
            elif arg["kind"] == "sampler":
                samplers[arg["slot"]] = Sampler.from_state(states[arg["hash"]])
        free = [t for t in sorted(shader.decl["textures"]) if t not in resources and t not in (0, 6)]
        if len(free) > 1:
            # The coal and burned-wood variants declare an engine texture as
            # well (a lookup read with sample_l or ld); the atlas is the one
            # free texture they filter with a plain sample.
            free = [t for t in free if any(ins.op == "sample" and ins.args[2].index == t for ins in shader.prog)]
        if len(free) > 1:
            raise ValueError(f"{m['name']}: textures {free} are declared but not bound")
        if free:
            resources[free[0]] = self.atlas()
        cb0 = np.zeros(((len(m.get("cbuffer_floats", [])) + 3) // 4 * 4 or 4,), np.float32)
        cb0[:len(m.get("cbuffer_floats", []))] = m.get("cbuffer_floats", [])
        bound = DecalMaterial(shader, resources, samplers, cb0.reshape(-1, 4), m["blend"],
                              free[0] if free else None)
        self._bound[pointer] = bound
        while len(self._bound) > self.cache:
            self._bound.popitem(last=False)
        return bound

    # ---------------------------------------------------------------- draw
    def draws(self, gbuffer):
        """Decals whose boxes reach the bake, in draw order (draw_key)."""
        x0, y0, x1, y1 = gbuffer.box
        out = []
        for decal in self.decals:
            lo, hi = footprint(decal)
            if decal["hidden"] or hi[0] < x0 or lo[0] > x1 or hi[1] < y0 or lo[1] > y1:
                continue
            if self.materials.get(decal["material"], {}).get("pixel_shader") is None:
                continue
            out.append(decal)
        return sorted(out, key=draw_key)

    def draw(self, gbuffer, decal, depth_normal=False):
        """Run one decal's pixel shader over the texels its box reaches and blend it in.

        Returns the number of texels whose stored G-buffer values it changed.
        """
        window = gbuffer.window(*footprint(decal))
        if window is None:
            return 0
        rows, cols = window
        x, y = gbuffer.world(rows, cols)
        z = gbuffer.z[rows, cols].astype(np.float64)
        local = world_to_local(decal, np.stack([x, y, z], -1).reshape(-1, 3)).reshape(x.shape + (3,))
        inside = (np.abs(local) <= 1).all(-1) & gbuffer.alive[rows, cols]
        if not inside.any():
            return 0
        # Shrink to the texels inside, still on whole quads.
        rr, cc = np.nonzero(inside)
        rows = slice(rows.start + rr.min() // 2 * 2, min(rows.start + (rr.max() // 2 + 1) * 2, rows.stop))
        cols = slice(cols.start + cc.min() // 2 * 2, min(cols.start + (cc.max() // 2 + 1) * 2, cols.stop))
        x, y = gbuffer.world(rows, cols)
        z = gbuffer.z[rows, cols].astype(np.float64)
        h, w = x.shape
        n = h * w

        material = self.material(decal["material"])
        v2, depth, cb2 = self.camera(gbuffer, rows, cols, x, y, z, material)
        resources = dict(material.resources)
        resources[0] = LaneTexture(np.concatenate([depth[:, None], np.zeros((n, 3), np.float32)], 1))
        resources[6] = LaneTexture(gbuffer.read(1, rows, cols).reshape(n, 4))
        outs, alive = material.shader.run(
            n, inputs={"v0": np.zeros((n, 4), np.uint32), "v1": np.ones(4, np.float32), "v2": v2},
            cbuffers={0: material.cb0, 2: cb2}, resources=resources,
            structured={21: gpu_record(decal, depth_normal)}, grid=(h, w), samplers=material.samplers)
        mask = alive.reshape(h, w) & gbuffer.alive[rows, cols]
        if not mask.any():
            return 0
        changed = np.zeros((h, w), bool)
        for rt in TARGET_BITS:
            state = material.blend[rt]
            if rt not in outs or not state["write_mask"]:
                continue
            src = np.clip(np.nan_to_num(outs[rt]), 0, 1)
            before = gbuffer.stored[rt][rows, cols].copy()
            dst = decode_target(rt, before).reshape(n, 4)
            gbuffer.write(rt, rows, cols, blend(state, src, dst).reshape(h, w, 4), mask, state["write_mask"])
            changed |= (gbuffer.stored[rt][rows, cols] != before).any(-1)
        return int(changed.sum())

    def camera(self, gbuffer, rows, cols, x, y, z, material):
        """cb2, per-lane pixel positions and depths that rebuild exactly (x, y, z).

        The shaders compute ndc = (v2 - cb2[92].xy) * cb2[61].zw * (2, -2) + (-1, 1),
        view = (ndc.x * cb2[12].x, ndc.y * cb2[13].y, 1) * w with 1/w = depth * 1.015873,
        and world = view.x * cb2[16] + view.y * cb2[17] + view.z * cb2[18] + cb2[24].
        """
        h, w = x.shape
        x0, _, _, y1 = gbuffer.box
        tpu = gbuffer.tpu
        top = float(z.max()) + CAMERA_CLEARANCE
        dist = top - z
        ref = float(np.median(dist))
        cx = x0 + (cols.start + w / 2) / tpu
        cy = y1 - (rows.start + h / 2) / tpu
        kx, ky = w / (2 * tpu * ref), h / (2 * tpu * ref)
        cb2 = np.zeros((CB2_ROWS, 4), np.float32)
        cb2[12, 0], cb2[13, 1] = kx, ky
        cb2[16, :3], cb2[17, :3], cb2[18, :3] = (1, 0, 0), (0, 1, 0), (0, 0, -1)
        cb2[24, :3] = (cx, cy, top)
        cb2[61, 2:] = (1 / w, 1 / h)
        if material.atlas_register is not None:
            width, height, _ = material.resources[material.atlas_register].size(0)
            cb2[113, 2:] = (0.5 / width, 0.5 / height)
        ndc_x = (x - cx) / (kx * dist)
        ndc_y = (y - cy) / (ky * dist)
        v2 = np.stack([(ndc_x + 1) * 0.5 * w, (1 - ndc_y) * 0.5 * h], -1).reshape(-1, 2)
        depth = (1 / dist / DEPTH_SCALE).reshape(-1)
        return v2.astype(np.float32), depth.astype(np.float32), cb2

    def composite(self, gbuffer, decals=None, progress=None, depth_normal=False):
        """Draw every decal that reaches the bake, in order; returns one row per draw."""
        log = []
        started = time.time()
        todo = self.draws(gbuffer) if decals is None else decals
        for done, decal in enumerate(todo, 1):
            texels = self.draw(gbuffer, decal, depth_normal)
            m = self.materials[decal["material"]]
            log.append({"index": decal["index"], "material": m["name"],
                        "shader": m["pixel_shader"]["sha1_16"], "texels": texels})
            if progress:
                progress(done, len(todo), time.time() - started)
        return log


def surface_maps(surface, geo_normal):
    """8-bit maps for a material from a decoded G-buffer.

    albedo: sRGB, alpha 0 where the cutout removed the surface. normal: tangent
    space around the height-array normal, OpenGL style (+Y up the image).
    gloss: the G-buffer's 0..1 gloss. roughness: sqrt(sqrt(2 / (2^(17 g) + 2))),
    the GGX roughness whose lobe matches the Blinn-Phong power 2^(17 g).
    specular: F0, sRGB.
    """
    to8 = lambda a: np.round(np.clip(a, 0, 1) * 255).astype(np.uint8)
    alive = surface["alive"][..., None].astype(np.float32)
    ts = tangent_space(surface["normal"].astype(np.float64), geo_normal.astype(np.float64))
    gloss = surface["gloss"]
    return {"albedo": to8(np.concatenate([srgb_encode(surface["albedo"]), alive], -1)),
            "normal": to8(ts * 0.5 + 0.5),
            "gloss": to8(gloss),
            "roughness": to8(np.sqrt(np.sqrt(2 / (np.exp2(17 * gloss) + 2)))),
            "specular": to8(srgb_encode(surface["specular"]))}


def save_surface(surface, geo_normal, folder, name):
    """Write surface_maps as {name}_{map}.png; returns the file names by map."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    maps = surface_maps(surface, geo_normal)
    for key, image in maps.items():
        Image.fromarray(image).save(folder / f"{name}_{key}.png")
    return {key: f"{name}_{key}.png" for key in maps}


def bake_surface(terrain, decals, box, texels_per_unit, tile=1024, block=128, progress=None,
                 depth_normal=False):
    """The terrain pixel shader and then the decal pass over a world box, one tile at a time.

    Tiles overlap by two texels so the specular checkerboard has neighbours at
    tile edges. Tile origins stay even, so the 2x2 quads and checkerboard parity
    are those of one whole bake. decals may be None (terrain only). Returns
    (surface_maps arrays for the box, {decal index: texels changed}; texels in
    tile margins count once per tile).
    """
    x0, y0, x1, y1 = box
    tpu = float(texels_per_unit)
    width = int(round((x1 - x0) * tpu)) // 2 * 2
    height = int(round((y1 - y0) * tpu)) // 2 * 2
    tile, margin = max(2, tile // 2 * 2), 2
    maps, changed = None, {}
    tiles = [(r, c) for r in range(0, height, tile) for c in range(0, width, tile)]
    started = time.time()
    for done, (r, c) in enumerate(tiles, 1):
        r0, c0 = max(0, r - margin), max(0, c - margin)
        r1, c1 = min(height, r + tile + margin), min(width, c + tile + margin)
        window = (x0 + c0 / tpu, y1 - r1 / tpu, x0 + c1 / tpu, y1 - r0 / tpu)
        result = terrain.bake(window, tpu, block)
        gbuffer = GBuffer.from_terrain(result, window, tpu)
        if decals is not None:
            for row in decals.composite(gbuffer, depth_normal=depth_normal):
                if row["texels"]:
                    changed[row["index"]] = changed.get(row["index"], 0) + row["texels"]
        part = surface_maps(gbuffer.surface(), result["geo_normal"])
        del result, gbuffer
        if maps is None:
            maps = {k: np.zeros((height, width) + v.shape[2:], np.uint8) for k, v in part.items()}
        h, w = min(tile, height - r), min(tile, width - c)
        for key, image in part.items():
            maps[key][r:r + h, c:c + w] = image[r - r0:r - r0 + h, c - c0:c - c0 + w]
        if progress:
            progress(done, len(tiles), time.time() - started)
    return maps, changed


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("package", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--sector", type=int, default=0)
    parser.add_argument("--shader", type=Path, help="terrain G-buffer PS (.dxbc or .asm); default: the package's")
    parser.add_argument("--box", type=float, nargs=4, metavar=("X0", "Y0", "X1", "Y1"), required=True)
    parser.add_argument("--texels-per-inch", type=float, default=1.0)
    parser.add_argument("--block", type=int, default=128)
    parser.add_argument("--name", default="terrain")
    parser.add_argument("--depth-normal", action="store_true",
                        help="angle-test decals against depth-derived normals (record +128.w = 1)")
    args = parser.parse_args()
    terrain = TerrainScene(args.package, args.sector, args.shader)
    report = lambda d, n, t: print(f"terrain block {d}/{n} {t:.0f}s", flush=True)
    result = terrain.bake(args.box, args.texels_per_inch, args.block, report)
    gbuffer = GBuffer.from_terrain(result, args.box, args.texels_per_inch)
    args.output.mkdir(parents=True, exist_ok=True)
    before = save_surface(gbuffer.surface(), result["geo_normal"], args.output, args.name + "_nodecals")
    scene = DecalScene(args.package)
    log = scene.composite(gbuffer, progress=lambda d, n, t: print(f"decal {d}/{n} {t:.0f}s", flush=True),
                          depth_normal=args.depth_normal)
    after = save_surface(gbuffer.surface(), result["geo_normal"], args.output, args.name)
    np.savez_compressed(args.output / f"{args.name}_gbuffer.npz", alive=gbuffer.alive, height=gbuffer.z,
                        geo_normal=result["geo_normal"], **{f"rt{k}": v for k, v in gbuffer.stored.items()})
    (args.output / f"{args.name}_decals.json").write_text(json.dumps(
        {"box": args.box, "texels_per_inch": args.texels_per_inch, "without_decals": before, "maps": after,
         "draws": log}, indent=1))
    print(json.dumps({"drawn": sum(1 for r in log if r["texels"]), "considered": len(log), "maps": after}, indent=1))
