"""Run disassembled D3D11 shader model 5 pixel shaders on numpy arrays.

The BO4 terrain and volume-decal pixel shaders are captured from the running
game and disassembled with D3DCompiler_47. This module executes that text
directly, so the replication runs the game's own maths instead of a hand port.

Every lane is one pixel. Lanes run together and branches are handled with
execution masks: both sides of an `if` run, and each side writes only the
lanes where its condition holds. `discard` only drops a lane's outputs: the
lane keeps running as a helper to the end, as on the GPU, so the derivatives
of the pixels sharing its 2x2 quad stay valid. Registers are stored as raw 32-bit words; float
instructions view them as float32, so bit tricks such as `xor` on sign bits and
`f16tof32` behave as they do on the GPU.

Lanes can be laid out as an image (`grid=(H, W)`). Derivatives then use 2x2
quads as a GPU does, which gives the implicit mip level for `sample`.

Supported: the ALU, comparison, bitfield and conversion instructions these
shaders use, plus `if`/`else`/`loop`/`break`/`continue`/`discard`/`ret`,
`ld_structured`, `ld`, `sample`, `sample_l`, `lod` and `resinfo`. An unknown
opcode raises NotImplementedError instead of being skipped. Domain shaders run
with one lane per evaluated point: pass `vDomain` and each control-point input
`vicp[p][r]` as "vicp{p}_{r}".

Textures keep their texels in the dtype they were given: uint8 texels are
UNORM (or go through a lookup table, e.g. an sRGB decode), integer texels of
a uint resource are returned bit-exact by `ld`, and floats pass through.
`VirtualArray` models the engine's material texture arrays, where each slice
is a separate image and a smaller image starts at a lower mip of the array.

A texture carries a default address mode. Pass `samplers` to `Shader.run` to
use the sampler bound to each `sample` instead: its address mode, whether it
filters between mips at all, and point or linear texel filtering.
"""

import re
import struct

import numpy as np

FLOAT_OPS = set()
SWZ = {"x": 0, "y": 1, "z": 2, "w": 3, "r": 0, "g": 1, "b": 2, "a": 3}


def _f(u):
    return u.view(np.float32)


def _u(f):
    return np.ascontiguousarray(f, dtype=np.float32).view(np.uint32)


def _i(u):
    return u.view(np.int32)


UNORM8 = np.arange(256, dtype=np.float32) / 255


def srgb_decode_table():
    """uint8 sRGB -> linear float, as an _SRGB format fetch does before filtering."""
    c = np.arange(256, dtype=np.float64) / 255
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4).astype(np.float32)


def srgb_encode(linear):
    c = np.clip(linear, 0, 1)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * c ** (1 / 2.4) - 0.055)


class Texture:
    """A 2D texture or texture array: levels[m] is (slices, H, W, 4).

    uint8 levels are UNORM, or decoded through `lut` (256 floats, e.g. an sRGB
    table) per fetched texel; other integer levels stay integers for `ld` on a
    uint resource; float levels are used as they are.
    """

    def __init__(self, levels, address="wrap", lut=None):
        self.levels = [np.asarray(l) for l in levels]
        if self.levels[0].ndim == 3:
            self.levels = [l[None] for l in self.levels]
        self.address = address
        self.lut = lut if lut is not None else (UNORM8 if self.levels[0].dtype == np.uint8 else None)

    @classmethod
    def from_image(cls, image, address="wrap", mips=True, srgb=False):
        """image: (H, W, C) float array, or uint8 texels (UNORM, or sRGB with srgb=True).

        Builds a box-filtered mip chain.  uint8 chains are filtered in linear
        space and stored back as uint8, like the 8-bit mips the game ships.
        """
        image = np.asarray(image)
        if image.ndim == 2:
            image = image[:, :, None]
        if image.dtype != np.uint8:
            image = image.astype(np.float32)
            levels = [image] + (_box_mips(image) if mips else [])
            return cls(levels, address)
        lut = srgb_decode_table() if srgb else UNORM8
        levels = [image]
        if mips:
            linear = lut[image]
            for level in _box_mips(linear):
                out = level
                if srgb:
                    out = np.concatenate([srgb_encode(level[..., :3]), level[..., 3:]], axis=2)
                levels.append(np.round(np.clip(out, 0, 1) * 255).astype(np.uint8))
        return cls(levels, address, lut=lut)

    def mip_count(self):
        return len(self.levels)

    def size(self, level=0):
        l = self.levels[min(level, len(self.levels) - 1)]
        return l.shape[2], l.shape[1], l.shape[0]

    def _raw(self, level, s, x, y, address=None):
        l = self.levels[level]
        h, w = l.shape[1], l.shape[2]
        if (address or self.address) == "wrap":
            x, y = np.mod(x, w), np.mod(y, h)
        else:
            x, y = np.clip(x, 0, w - 1), np.clip(y, 0, h - 1)
        return l[np.clip(s, 0, l.shape[0] - 1), y, x]

    def _fetch(self, level, s, x, y, address=None):
        raw = self._raw(level, s, x, y, address)
        if self.lut is not None:
            return _pad4(self.lut[raw])
        return _pad4(raw.astype(np.float32, copy=False))

    def bilinear(self, u, v, s, level, address=None, point=False):
        level = int(np.clip(level, 0, len(self.levels) - 1))
        l = self.levels[level]
        h, w = l.shape[1], l.shape[2]
        if point:
            x, y = np.floor(u * w).astype(np.int64), np.floor(v * h).astype(np.int64)
            return self._fetch(level, s, x, y, address)
        x, y = u * w - 0.5, v * h - 0.5
        x0, y0 = np.floor(x), np.floor(y)
        fx, fy = (x - x0)[:, None], (y - y0)[:, None]
        x0, y0 = x0.astype(np.int64), y0.astype(np.int64)
        a = self._fetch(level, s, x0, y0, address)
        b = self._fetch(level, s, x0 + 1, y0, address)
        c = self._fetch(level, s, x0, y0 + 1, address)
        d = self._fetch(level, s, x0 + 1, y0 + 1, address)
        return (a * (1 - fx) + b * fx) * (1 - fy) + (c * (1 - fx) + d * fx) * fy

    def sample(self, u, v, s, lod, sampler=None):
        """Trilinear sample; lod is a per-lane float array.

        A Sampler replaces the texture's address mode and can turn off mip
        filtering (mip 0 only) or round to the nearest mip.
        """
        address = sampler.address if sampler else None
        point = bool(sampler and sampler.filter == "point")
        u, v = np.nan_to_num(u), np.nan_to_num(v)
        lod = np.clip(np.nan_to_num(lod, nan=0.0), 0, len(self.levels) - 1)
        if sampler and sampler.mip == "none":
            lod = np.zeros_like(lod)
        elif sampler and sampler.mip == "point":
            lod = np.minimum(np.floor(lod + 0.5), len(self.levels) - 1)
        out = np.zeros((u.shape[0], 4), np.float32)
        base = np.floor(lod).astype(np.int64)
        frac = (lod - base)[:, None]
        for m in np.unique(base):
            k = base == m
            lo = self.bilinear(u[k], v[k], s[k], m, address, point)
            if m + 1 < len(self.levels):
                hi = self.bilinear(u[k], v[k], s[k], m + 1, address, point)
                lo = lo + (hi - lo) * frac[k]
            out[k] = lo
        return out

    def load(self, x, y, s, level, raw=False):
        """`ld`: out-of-range texels read 0.  raw=True returns the stored integers."""
        l = self.levels[int(level)]
        inside = (x >= 0) & (y >= 0) & (x < l.shape[2]) & (y < l.shape[1])
        out = self._fetch(int(level), s, x, y) if not raw else _pad4(self._raw(int(level), s, x, y))
        out = out.copy()
        out[~inside] = 0
        return out


def _pad4(texels):
    """Missing channels read as D3D fills them: green and blue 0, alpha 1."""
    if texels.shape[-1] >= 4:
        return texels
    pad = np.zeros(texels.shape[:-1] + (4 - texels.shape[-1],), texels.dtype)
    pad[..., -1] = 1
    return np.concatenate([texels, pad], -1)


class Sampler:
    """A sampler state: address mode, mip filtering and texel filtering.

    `from_state` decodes the engine's material sampler word: the filter in bits
    0-2 (1 point, 2 linear, 3 and up anisotropic), the mip filter in bits 3-4
    (0 none, 1 point, 2 linear) and 2-bit U, V and W address modes from bit 5
    (0 wrap, 1 clamp).  Anisotropic filters are sampled trilinearly.
    """

    ADDRESS = {0: "wrap", 1: "clamp"}
    MIP = {0: "none", 1: "point", 2: "linear"}

    def __init__(self, address="wrap", mip="linear", filter="linear"):
        self.address, self.mip, self.filter = address, mip, filter

    @classmethod
    def from_state(cls, word):
        word = int(word, 16) if isinstance(word, str) else int(word)
        u, v = (word >> 5) & 3, (word >> 7) & 3
        mip = (word >> 3) & 3
        if u != v or u not in cls.ADDRESS or mip not in cls.MIP or not word & 7:
            raise ValueError(f"sampler state 0x{word:X} is outside the decoded modes")
        return cls(cls.ADDRESS[u], cls.MIP[mip], "point" if word & 7 == 1 else "linear")

    def __repr__(self):
        return f"Sampler({self.address}, mip={self.mip}, filter={self.filter})"


def _box_mips(image):
    levels, a = [], image
    while min(a.shape[:2]) > 1:
        h, w = a.shape[0] // 2 * 2 or 1, a.shape[1] // 2 * 2 or 1
        a = a[:h, :w]
        if a.shape[0] > 1:
            a = 0.5 * (a[0::2] + a[1::2])
        if a.shape[1] > 1:
            a = 0.5 * (a[:, 0::2] + a[:, 1::2])
        levels.append(a)
    return levels


class VirtualArray:
    """A texture2darray whose slices are separate images.

    The engine packs every layer material's maps into shared arrays of one base
    size; a smaller image occupies only the lower mips of its slice, and the
    shader clamps its lod to the slice's first valid mip (the record's "min mip").
    `slices` maps a slice index to a single-slice Texture; `base` is the
    array's (width, height) at mip 0.  Reading a slice that was not supplied
    raises, so a mis-routed index cannot silently sample something else.
    """

    def __init__(self, slices, base, count=None):
        self.slices = dict(slices)
        self.base = tuple(int(b) for b in base)
        self.count = count if count is not None else (max(self.slices) + 1 if self.slices else 0)
        self.offsets = {}
        for index, texture in self.slices.items():
            width = texture.size(0)[0]
            shift = int(round(np.log2(self.base[0] / width)))
            if width << shift != self.base[0]:
                raise ValueError(f"slice {index}: width {width} does not divide the array's {self.base[0]}")
            self.offsets[index] = shift

    def mip_count(self):
        return int(np.log2(max(self.base))) + 1

    def size(self, level=0):
        return max(1, self.base[0] >> level), max(1, self.base[1] >> level), self.count

    def _slice(self, index):
        if index not in self.slices:
            raise KeyError(f"texture array slice {index} was read but not supplied")
        return self.slices[index]

    def sample(self, u, v, s, lod, sampler=None):
        out = np.zeros((u.shape[0], 4), np.float32)
        for index in np.unique(s):
            k = s == index
            texture = self._slice(int(index))
            out[k] = texture.sample(u[k], v[k], np.zeros(int(k.sum()), np.int64),
                                    np.asarray(lod)[k] - self.offsets[int(index)], sampler)
        return out

    def load(self, x, y, s, level, raw=False):
        out = None
        for index in np.unique(s):
            k = s == index
            texture = self._slice(int(index))
            part = texture.load(x[k], y[k], np.zeros(int(k.sum()), np.int64),
                                max(0, int(level) - self.offsets[int(index)]), raw)
            if out is None:
                out = np.zeros((len(x),) + part.shape[1:], part.dtype)
            out[k] = part
        return out


class LaneTexture:
    """A resource whose `ld` returns one given texel per lane (G-buffer inputs)."""

    def __init__(self, values):
        self.values = np.asarray(values, np.float32)   # (N, 4)
        self.lanes = None

    def load(self, x, y, s, level, raw=False):
        return self.values[self.lanes]

    def mip_count(self):
        return 1

    def size(self, level=0):
        return 1, 1, 1


class Instruction:
    __slots__ = ("op", "sat", "args", "line", "extra")

    def __init__(self, op, sat, args, line, extra):
        self.op, self.sat, self.args, self.line, self.extra = op, sat, args, line, extra


_OPERAND = re.compile(r"\s*(-?)(\|?)([^|]+?)(\|?)\s*$")


def _split_args(text):
    out, depth, cur = [], 0, ""
    for ch in text:
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        if ch == "," and depth == 0:
            out.append(cur.strip())
            cur = ""
        else:
            cur += ch
    if cur.strip():
        out.append(cur.strip())
    return out


def _literal(text):
    vals = []
    for tok in text.split(","):
        tok = tok.strip()
        if tok.lower().startswith("0x") or tok.lower().startswith("-0x"):
            vals.append(int(tok, 16) & 0xFFFFFFFF)
        elif re.fullmatch(r"-?\d+", tok):
            vals.append(int(tok) & 0xFFFFFFFF)
        else:
            tok = tok.replace("1.#INF00", "inf").replace("1.#QNAN0", "nan")
            vals.append(struct.unpack("<I", struct.pack("<f", float(tok)))[0])
    while len(vals) < 4:
        vals.append(vals[-1])
    return np.array(vals, np.uint32)


class Operand:
    __slots__ = ("neg", "abs", "kind", "index", "swz", "lit", "cb", "cb_reg", "cb_comp", "cb_off", "raw")

    def __init__(self, text):
        self.raw = text
        m = _OPERAND.match(text)
        self.neg, self.abs = m.group(1) == "-", m.group(2) == "|"
        body = m.group(3).strip()
        self.lit = self.cb = self.cb_reg = None
        self.cb_comp = self.cb_off = 0
        self.swz = [0, 1, 2, 3]
        if body.startswith("l("):
            self.kind, self.lit = "l", _literal(body[2:-1])
            return
        if body in ("null", "oDepth"):
            self.kind, self.index = body, 0
            return
        cbm = re.fullmatch(r"cb(\d+)\[(.+?)\](?:\.([xyzw]+))?", body)
        if cbm:
            self.kind, self.cb = "cb", int(cbm.group(1))
            idx = cbm.group(2).replace(" ", "")
            dyn = re.fullmatch(r"r(\d+)\.([xyzw])(?:\+(\d+))?", idx)
            if dyn:
                self.cb_reg, self.cb_comp, self.cb_off = int(dyn.group(1)), SWZ[dyn.group(2)], int(dyn.group(3) or 0)
            else:
                self.cb_off = int(idx)
            if cbm.group(3):
                self.swz = self._swz(cbm.group(3))
            return
        dm = re.fullmatch(r"(vDomain|vicp\[(\d+)\]\[(\d+)\])(?:\.([xyzw]+))?", body)
        if dm:
            self.kind = "v"
            self.index = "Domain" if dm.group(1) == "vDomain" else f"icp{dm.group(2)}_{dm.group(3)}"
            if dm.group(4):
                self.swz = self._swz(dm.group(4))
            return
        rm = re.fullmatch(r"([a-z]+)(\d+)(?:\.([xyzw]+))?", body)
        if not rm:
            raise NotImplementedError("operand " + text)
        self.kind, self.index = rm.group(1), int(rm.group(2))
        if rm.group(3):
            self.swz = self._swz(rm.group(3))

    @staticmethod
    def _swz(s):
        out = [SWZ[c] for c in s]
        while len(out) < 4:
            out.append(out[-1])
        return out

    def mask(self):
        m = _OPERAND.match(self.raw).group(3)
        comp = m.split(".")[1] if "." in m else "xyzw"
        return [SWZ[c] for c in comp]


def _opcode(line):
    """Split 'name(...)(...)_uint args' into (name, bracket suffix, args)."""
    m = re.match(r"[a-z0-9_]+", line)
    if m is None:
        return None, "", line
    i = m.end()
    extra = ""
    while i < len(line) and line[i] == "(":
        depth, j = 0, i
        while True:
            depth += {"(": 1, ")": -1}.get(line[j], 0)
            j += 1
            if depth == 0:
                break
        extra += line[i:j]
        i = j
    if line.startswith("_uint", i):
        extra += "_uint"
        i += 5
    return m.group(0), extra, line[i:].strip()


def parse(text):
    """Parse disassembly text into declarations and a list of instructions."""
    decl, prog = {"temps": 0, "structured": {}, "textures": {}, "outputs": [], "inputs": []}, []
    for raw in text.splitlines():
        line = raw.split("//")[0].replace("\x00", "").strip()
        if not line or line.startswith(("ps_", "vs_", "cs_", "ds_", "hs_", "gs_")):
            continue
        if line.startswith("dcl_"):
            if line.startswith("dcl_temps"):
                decl["temps"] = int(line.split()[1])
            elif line.startswith("dcl_resource_structured"):
                t, stride = line.split()[1].rstrip(","), int(line.split()[2])
                decl["structured"][int(t[1:])] = stride
            elif line.startswith("dcl_resource_texture"):
                # dcl_resource_texture2d (float,float,float,float) t7 -> {7: "texture2d"}
                kind, register = line.split()[0][len("dcl_resource_"):], line.split()[-1]
                decl["textures"][int(register[1:])] = kind
            elif line.startswith("dcl_output"):
                decl["outputs"].append(line.split()[1])
            elif line.startswith("dcl_input"):
                decl["inputs"].append(line)
            continue
        name, extra, rest = _opcode(line)
        if name is None:
            if line.startswith(("{", "}")):
                continue
            raise NotImplementedError("line " + line)
        sat = name.endswith("_sat")
        op = name[:-4] if sat else name
        op = op.replace("_indexable", "")
        prog.append(Instruction(op, sat, [Operand(a) for a in _split_args(rest)] if rest else [], raw, extra))
    return decl, prog


class Shader:
    def __init__(self, text):
        self.decl, self.prog = parse(text)
        self._pc_of = {id(ins): pc for pc, ins in enumerate(self.prog)}
        self.taps, self.tapped = {}, {}
        self._match()

    def _match(self):
        stack, self.jump = [], {}
        for pc, ins in enumerate(self.prog):
            if ins.op in ("if_nz", "if_z", "loop"):
                stack.append(pc)
            elif ins.op == "else":
                self.jump[stack[-1]] = pc
            elif ins.op in ("endif", "endloop"):
                self.jump[("end", stack.pop())] = pc

    # ------------------------------------------------------------------ run
    def find(self, op, occurrence=-1):
        """Index of an instruction by opcode (the last one by default), for `taps`."""
        hits = [pc for pc, ins in enumerate(self.prog) if ins.op == op]
        return hits[occurrence]

    def run(self, n, inputs=None, cbuffers=None, resources=None, structured=None,
            grid=None, lod_bias=0.0, max_loop=64, taps=None, samplers=None):
        """Execute for n lanes.

        inputs: {"v0": (n, 4) array or 4-vector}; values are float unless uint32.
        cbuffers: {index: (rows, 4) uint32 or float32 array}.
        resources: {t: Texture, VirtualArray or LaneTexture}. structured: {t: bytes}.
        samplers: {s: Sampler}; a `sample` through an unlisted sampler uses the
        texture's own address mode with trilinear filtering.
        taps: {pc: ["r14", ...]} copies those registers (as float32 (n, 4)) when
        instruction pc runs, before it executes; read them from self.tapped[pc].
        Returns ({0: o0 as (n, 4) float32, ...}, alive): alive is False where a lane discarded.
        """
        self.taps = taps or {}
        self.tapped = {pc: {} for pc in self.taps}
        self.n = n
        self.grid = grid
        self.lod_bias = lod_bias
        self.r = np.zeros((max(self.decl["temps"], 1), 4, n), np.uint32)
        self.o = {}
        self.v = {}
        for k, val in (inputs or {}).items():
            a = np.asarray(val)
            if a.ndim == 1:
                a = np.tile(a, (n, 1))
            if a.dtype != np.uint32:
                a = _u(a.astype(np.float32))
            if a.shape[1] < 4:
                a = np.concatenate([a, np.zeros((n, 4 - a.shape[1]), np.uint32)], 1)
            key = k[1:]
            self.v[int(key) if key.isdigit() else key] = np.ascontiguousarray(a.T)
        self.cb = {}
        for k, val in (cbuffers or {}).items():
            a = np.asarray(val)
            self.cb[k] = a.view(np.uint32) if a.dtype == np.float32 else a.astype(np.uint32)
        self.res = resources or {}
        self.samplers = samplers or {}
        self.sb = {k: np.frombuffer(bytes(v), np.uint8) for k, v in (structured or {}).items()}
        self.alive = np.ones(n, bool)
        self.active = np.ones(n, bool)
        self.lanes = np.arange(n)
        for t in self.res.values():
            if isinstance(t, LaneTexture):
                t.lanes = self.lanes
        mask = np.ones(n, bool)
        self._block(0, len(self.prog), mask, max_loop)
        outs = {k: _f(v.T.copy()) for k, v in self.o.items()}
        return outs, self.alive

    def _block(self, pc, end, mask, max_loop, loop_state=None):
        while pc < end:
            ins = self.prog[pc]
            op = ins.op
            if op in ("if_nz", "if_z"):
                c = self._src(ins.args[0], mask_ok=True)[0] != 0
                if op == "if_z":
                    c = ~c
                els = self.jump.get(pc)
                fin = self.jump[("end", pc)]
                live = mask & self.active
                if loop_state is not None:
                    live &= ~loop_state["done"] & ~loop_state["cont"]
                taken = live & c
                if taken.any():
                    r = self._block(pc + 1, els if els is not None else fin, taken, max_loop, loop_state)
                if els is not None and (live & ~c).any():
                    self._block(els + 1, fin, live & ~c, max_loop, loop_state)
                pc = fin + 1
                continue
            if op == "loop":
                fin = self.jump[("end", pc)]
                state = {"done": ~mask.copy(), "cont": np.zeros(self.n, bool)}
                for _ in range(max_loop):
                    run = mask & self.active & ~state["done"]
                    if not run.any():
                        break
                    state["cont"][:] = False
                    self._block(pc + 1, fin, run, max_loop, state)
                else:
                    raise RuntimeError("loop exceeded max_loop")
                pc = fin + 1
                continue
            if op in ("break", "breakc_nz", "breakc_z", "continue", "continuec_nz", "continuec_z"):
                live = mask & self.active & ~loop_state["done"] & ~loop_state["cont"]
                if op in ("break", "continue"):
                    hit = live
                else:
                    c = self._src(ins.args[0])[0] != 0
                    hit = live & (c if op.endswith("_nz") else ~c)
                if op.startswith("break"):
                    loop_state["done"] |= hit
                else:
                    loop_state["cont"] |= hit
                pc += 1
                continue
            if op == "ret":
                if pc in self.taps:
                    self._tap(pc, mask & self.active)
                self.active &= ~mask
                pc += 1
                continue
            live = mask & self.active
            if loop_state is not None:
                live = live & ~loop_state["done"] & ~loop_state["cont"]
            if live.any():
                self._exec(ins, live)
            pc += 1

    def _tap(self, pc, live):
        for name in self.taps[pc]:
            bank = self.r if name[0] == "r" else self.o
            index = int(name[1:])
            src = bank[index] if name[0] == "r" else self.o.get(index, np.zeros((4, self.n), np.uint32))
            dst = self.tapped[pc].setdefault(name, np.zeros((self.n, 4), np.float32))
            dst[live] = _f(src.T.copy())[live]

    # ------------------------------------------------------------- operands
    def _raw(self, o):
        if o.kind == "r":
            return self.r[o.index]
        if o.kind == "v":
            return self.v[o.index]
        if o.kind == "o":
            return self.o.setdefault(o.index, np.zeros((4, self.n), np.uint32))
        if o.kind == "null":
            return np.zeros((4, self.n), np.uint32)
        if o.kind == "oDepth":
            return self.o.setdefault("depth", np.zeros((4, self.n), np.uint32))
        if o.kind == "l":
            return np.repeat(o.lit[:, None], self.n, 1)
        if o.kind == "cb":
            buf = self.cb[o.cb]
            if o.cb_reg is None:
                row = buf[o.cb_off] if o.cb_off < len(buf) else np.zeros(4, np.uint32)
                return np.repeat(row[:, None], self.n, 1)
            idx = self.r[o.cb_reg][o.cb_comp].astype(np.int64) + o.cb_off
            idx = np.clip(idx, 0, len(buf) - 1)
            return buf[idx].T.copy()
        raise NotImplementedError(o.raw)

    def _src(self, o, kind="f", mask_ok=False):
        raw = self._raw(o)[o.swz]
        if kind == "u":
            if o.neg:
                raw = (-_i(raw.copy())).view(np.uint32)
            return raw
        if kind == "i":
            v = _i(raw.copy())
            return -v if o.neg else v
        if not (o.neg or o.abs):
            return raw
        v = _f(raw.copy())
        if o.abs:
            v = np.abs(v)
        if o.neg:
            v = -v
        return _u(v)

    def _fs(self, o):
        return _f(np.ascontiguousarray(self._src(o)))

    def _write(self, o, value, live, sat=False, is_float=True):
        """value: (4, n) uint32 or float32 array."""
        if value.dtype != np.uint32:
            v = value.astype(np.float32)
            if sat:
                v = np.nan_to_num(np.clip(v, 0, 1), nan=0.0)
            value = _u(v)
        elif sat:
            v = np.nan_to_num(np.clip(_f(value.copy()), 0, 1), nan=0.0)
            value = _u(v)
        dst = self._raw(o)
        for c in o.mask():
            dst[c][live] = value[c][live]

    # ------------------------------------------------------------ execution
    def _exec(self, ins, live):
        if self.taps and self._pc_of.get(id(ins)) in self.taps:
            self._tap(self._pc_of[id(ins)], live)
        op, a = ins.op, ins.args
        F, U, I = self._fs, lambda x: self._src(x, "u"), lambda x: self._src(x, "i")
        w = lambda v, f=True: self._write(a[0], v, live, ins.sat)
        with np.errstate(all="ignore"):
            if op == "mov":
                w(self._src(a[1]))
            elif op == "add":
                w(F(a[1]) + F(a[2]))
            elif op == "mul":
                w(F(a[1]) * F(a[2]))
            elif op == "mad":
                w(F(a[1]) * F(a[2]) + F(a[3]))
            elif op == "div":
                w(F(a[1]) / F(a[2]))
            elif op in ("dp2", "dp3", "dp4"):
                k = int(op[2])
                d = (F(a[1])[:k] * F(a[2])[:k]).sum(0)
                w(np.repeat(d[None], 4, 0))
            elif op == "min":
                w(np.fmin(F(a[1]), F(a[2])))
            elif op == "max":
                w(np.fmax(F(a[1]), F(a[2])))
            elif op == "rcp":
                w(np.float32(1) / F(a[1]))
            elif op == "rsq":
                w(np.float32(1) / np.sqrt(F(a[1])))
            elif op == "sqrt":
                w(np.sqrt(F(a[1])))
            elif op == "log":
                w(np.log2(F(a[1])))
            elif op == "exp":
                w(np.exp2(F(a[1])))
            elif op == "frc":
                x = F(a[1])
                w(x - np.floor(x))
            elif op == "round_ni":
                w(np.floor(F(a[1])))
            elif op == "round_pi":
                w(np.ceil(F(a[1])))
            elif op == "round_z":
                w(np.trunc(F(a[1])))
            elif op == "round_ne":
                w(np.rint(F(a[1])))
            elif op in ("lt", "ge", "eq", "ne"):
                x, y = F(a[1]), F(a[2])
                r = {"lt": x < y, "ge": x >= y, "eq": x == y, "ne": x != y}[op]
                w(np.where(r, np.uint32(0xFFFFFFFF), np.uint32(0)))
            elif op in ("ilt", "ige", "ieq", "ine"):
                x, y = I(a[1]), I(a[2])
                r = {"ilt": x < y, "ige": x >= y, "ieq": x == y, "ine": x != y}[op]
                w(np.where(r, np.uint32(0xFFFFFFFF), np.uint32(0)))
            elif op in ("ult", "uge"):
                x, y = U(a[1]), U(a[2])
                w(np.where(x < y if op == "ult" else x >= y, np.uint32(0xFFFFFFFF), np.uint32(0)))
            elif op == "movc":
                c = self._src(a[1]) != 0
                w(np.where(c, self._src(a[2]), self._src(a[3])))
            elif op == "swapc":
                c = self._src(a[2]) != 0
                x, y = self._src(a[3]), self._src(a[4])
                self._write(a[0], np.where(c, y, x), live)
                self._write(a[1], np.where(c, x, y), live)
            elif op == "and":
                w(U(a[1]) & U(a[2]))
            elif op == "or":
                w(U(a[1]) | U(a[2]))
            elif op == "xor":
                w(U(a[1]) ^ U(a[2]))
            elif op == "not":
                w(~U(a[1]))
            elif op == "iadd":
                w((I(a[1]) + I(a[2])).view(np.uint32))
            elif op == "imul":
                w((I(a[2]) * I(a[3])).view(np.uint32) if len(a) == 4 else (I(a[1]) * I(a[2])).view(np.uint32))
            elif op == "umul":
                self._write(a[1], (U(a[2]) * U(a[3])), live)
            elif op == "ishl":
                w(U(a[1]) << (U(a[2]) & 31))
            elif op == "ushr":
                w(U(a[1]) >> (U(a[2]) & 31))
            elif op == "ishr":
                w((I(a[1]) >> (U(a[2]) & 31).astype(np.int32)).view(np.uint32))
            elif op in ("imin", "imax"):
                w((np.minimum if op == "imin" else np.maximum)(I(a[1]), I(a[2])).view(np.uint32))
            elif op in ("umin", "umax"):
                w((np.minimum if op == "umin" else np.maximum)(U(a[1]), U(a[2])))
            elif op == "ineg":
                w((-I(a[1])).view(np.uint32))
            elif op == "ubfe":
                width, off, x = U(a[1]) & 31, U(a[2]) & 31, U(a[3])
                m = np.where(width == 0, 0, (np.uint64(1) << width.astype(np.uint64)) - np.uint64(1)).astype(np.uint64)
                r = ((x.astype(np.uint64) >> off.astype(np.uint64)) & m).astype(np.uint32)
                w(np.where(width == 0, np.uint32(0), r))
            elif op == "bfi":
                width, off, x, y = U(a[1]) & 31, U(a[2]) & 31, U(a[3]), U(a[4])
                m = (((np.uint64(1) << width.astype(np.uint64)) - np.uint64(1)) << off.astype(np.uint64)).astype(np.uint32)
                w(((x << off) & m) | (y & ~m))
            elif op == "ftou":
                x = np.nan_to_num(F(a[1]), nan=0.0)
                w(np.clip(np.trunc(x), 0, 4294967295.0).astype(np.uint64).astype(np.uint32))
            elif op == "ftoi":
                x = np.nan_to_num(F(a[1]), nan=0.0)
                w(np.clip(np.trunc(x), -2147483648.0, 2147483647.0).astype(np.int64).astype(np.int32).view(np.uint32))
            elif op == "utof":
                w(U(a[1]).astype(np.float32))
            elif op == "itof":
                w(I(a[1]).astype(np.float32))
            elif op == "f16tof32":
                w((U(a[1]) & 0xFFFF).astype(np.uint16).view(np.float16).astype(np.float32))
            elif op == "f32tof16":
                w(F(a[1]).astype(np.float16).view(np.uint16).astype(np.uint32))
            elif op in ("firstbit_hi", "firstbit_lo"):
                x = U(a[1])
                out = np.full(x.shape, 0xFFFFFFFF, np.uint32)
                for b in (range(32) if op == "firstbit_lo" else range(31, -1, -1)):
                    hit = ((x >> b) & 1).astype(bool) & (out == 0xFFFFFFFF)
                    out[hit] = (31 - b) if op == "firstbit_hi" else b
                w(out)
            elif op == "countbits":
                x = U(a[1])
                w(np.array([[bin(int(v)).count("1") for v in row] for row in x], np.uint32))
            elif op in ("deriv_rtx_coarse", "deriv_rty_coarse", "deriv_rtx", "deriv_rty",
                        "deriv_rtx_fine", "deriv_rty_fine"):
                w(self._deriv(F(a[1]), "x" in op.split("_")[1]))
            elif op in ("discard_nz", "discard_z"):
                c = self._src(a[0])[0] != 0
                kill = live & (c if op == "discard_nz" else ~c)
                self.alive &= ~kill
            elif op == "ld_structured":
                idx, off = U(a[1])[0], U(a[2])[0]
                t = a[3]
                buf = self.sb[t.index]
                stride = self.decl["structured"][t.index]
                base = idx.astype(np.int64) * stride + off.astype(np.int64)
                words = np.zeros((4, self.n), np.uint32)
                for c in range(4):
                    p = np.clip(base + 4 * c, 0, len(buf) - 4)
                    words[c] = (buf[p].astype(np.uint32) | (buf[p + 1].astype(np.uint32) << 8) |
                                (buf[p + 2].astype(np.uint32) << 16) | (buf[p + 3].astype(np.uint32) << 24))
                w(words[t.swz])
            elif op in ("sample", "sample_l", "sample_b", "sample_d"):
                self._sample(ins, live)
            elif op == "lod":
                self._lod(ins, live)
            elif op == "ld":
                t = a[2]
                c = I(a[1])
                tex = self.res[t.index]
                arr = "texture2darray" in (ins.extra or "")
                level = c[3] if arr else c[2]
                level = int(level[live][0]) if live.any() else 0
                integer = "(uint" in (ins.extra or "") or "(sint" in (ins.extra or "")
                slices = c[2] if arr else np.zeros(self.n, np.int64)
                texel = np.zeros((self.n, 4), np.uint32 if integer else np.float32)
                if isinstance(tex, LaneTexture):
                    tex.lanes = self.lanes[live]
                got = tex.load(c[0][live], c[1][live], slices[live], level, raw=integer)
                if integer and got.dtype.kind == "f":
                    got = np.rint(got).astype(np.int64)
                texel[live] = got
                val = texel.T.astype(np.uint32) if integer else _u(texel.T.astype(np.float32))
                w(val[t.swz])
            elif op == "resinfo":
                t = a[2]
                tex = self.res[t.index]
                level = int(U(a[1])[0][0]) if self.n else 0
                wd, ht, sl = tex.size(level)
                vals = np.array([wd, ht, sl, tex.mip_count()], np.uint32)
                if "_uint" not in (ins.extra or ""):
                    vals = _u(vals.astype(np.float32))
                w(np.repeat(vals[t.swz][:, None], self.n, 1))
            elif op == "nop":
                pass
            else:
                raise NotImplementedError(f"opcode {op}: {ins.line.strip()}")

    def _deriv(self, x, horizontal):
        if self.grid is None:
            return np.zeros_like(x)
        h, wd = self.grid
        g = x.reshape(4, h, wd)
        out = np.zeros_like(g)
        if horizontal and wd > 1:
            d = g[:, :, 1::2] - g[:, :, 0:(wd // 2) * 2:2]
            d = d[:, 0:(h // 2) * 2:2]                          # coarse: top row of the quad
            d = np.repeat(np.repeat(d, 2, 1), 2, 2)
            out[:, :d.shape[1], :d.shape[2]] = d
        elif not horizontal and h > 1:
            d = g[:, 1::2] - g[:, 0:(h // 2) * 2:2]
            d = d[:, :, 0:(wd // 2) * 2:2]
            d = np.repeat(np.repeat(d, 2, 1), 2, 2)
            out[:, :d.shape[1], :d.shape[2]] = d
        return out.reshape(4, -1)

    def _implicit_lod(self, u, v, tex):
        wd, ht, _ = tex.size(0)
        dux, dvx = self._deriv(np.stack([u, u, u, u]), True)[0] * wd, self._deriv(np.stack([v, v, v, v]), True)[0] * ht
        duy, dvy = self._deriv(np.stack([u, u, u, u]), False)[0] * wd, self._deriv(np.stack([v, v, v, v]), False)[0] * ht
        rho = np.fmax(np.sqrt(dux * dux + dvx * dvx), np.sqrt(duy * duy + dvy * dvy))
        return np.log2(np.fmax(rho, 1e-8)) + self.lod_bias

    def _sample(self, ins, live):
        a = ins.args
        dst, coord, t = a[0], self._fs(a[1]), a[2]
        tex = self.res[t.index]
        arr = "texture2darray" in (ins.extra or "")
        u, v = coord[0], coord[1]
        s = np.rint(coord[2]).astype(np.int64) if arr else np.zeros(self.n, np.int64)
        if ins.op == "sample_l":
            lod = self._fs(a[4])[0]
        else:
            lod = self._implicit_lod(u, v, tex)
            if ins.op == "sample_b":
                lod = lod + self._fs(a[4])[0]
        sampler = self.samplers.get(a[3].index) if len(a) > 3 and a[3].kind == "s" else None
        texel = np.zeros((self.n, 4), np.float32)
        texel[live] = tex.sample(u[live], v[live], s[live], lod[live], sampler) if sampler else \
            tex.sample(u[live], v[live], s[live], lod[live])
        self._write(dst, texel.T[t.swz], live, ins.sat)

    def _lod(self, ins, live):
        a = ins.args
        coord, t = self._fs(a[1]), a[2]
        tex = self.res[t.index]
        raw = self._implicit_lod(coord[0], coord[1], tex)
        clamped = np.clip(raw, 0, tex.mip_count() - 1)
        vals = np.stack([clamped, raw, raw, raw]).astype(np.float32)
        self._write(a[0], vals[t.swz], live, ins.sat)
