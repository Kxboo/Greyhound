"""Translate BO4 volume-decal pixel shaders into MaterialX node graphs, instruction by instruction.

The USD terrain keeps decals live: each decal's own pixel shader (35 on
Blackout, all from one template) becomes nodes in the terrain material, so any
decal material draws exactly as its shader says, with no per-shader decoding.

Every register component carries two things:

- its value on a set of probe lanes, computed in float64 (bits for integer
  ops) the way bo4_dxbc_emulator computes them, from probe points around the
  decal; and
- a symbol: a MaterialX node (or a Python float) for the same value at any
  terrain point.

Each component also knows what it depends on: known constants (literals,
constant buffers, the decal record in t21, the face), the position only (the
pixel position and depth), or data (textures, the G-buffer). Known constants
fold, and so do the branches and selects on them. A position-only component
that is exactly affine in the world position on the probes becomes a clean
affine node. That is what removes the camera: the shader rebuilds the world
position from depth and the pixel position (inputs with probe values but no
symbol), and the rebuilt position comes out affine, so it is replaced by
the surface position. Nothing folds because probes happen to agree.

The one non-float input is the G-buffer normal's tetrahedron face (RT1.w).
The shader is translated once per face with the face held constant, which
folds all of its integer work (the decode for the angle test and the encode
of its own normal onto that face), and the four results are selected by the
face the terrain wrote. RT1 is kept in its stored form, (x, y) on the face
and the gloss channel, so decals blend on it exactly as the output merger
does; the terrain material decodes it once at the end. Values are not
quantized to the render targets' 8 and 10 bits.

A derivative (deriv_rtx/rty) is taken of affine values only: the screen steps
are the surface's own, (1, 0, -nx/nz) and (0, -1, ny/nz) from the geometric
normal, which fixes the cotangent frames the shaders build. Sampling ignores
the level of detail: the renderer filters.
"""

# Support direct execution and the isolated packaged Python runtime.
import sys as _tool_sys
from pathlib import Path as _ToolPath
TOOLS_ROOT = next(p for p in _ToolPath(__file__).resolve().parents if (p / "tool_bootstrap.py").is_file())
_tool_sys.path.insert(0, str(TOOLS_ROOT))
import tool_bootstrap as _tool_bootstrap
_tool_bootstrap.activate(__file__)
import numpy as np

from bo4_decal_composite import (CB2_ROWS, DEPTH_SCALE, R_FORMATS, RG_FORMATS, SRGB_FORMATS, DecalScene,
                                 footprint)
from bo4_volume_decals import gpu_record

PROBES = 64
FACE_SIGNS = np.array([[1, 1, 1], [1, -1, -1], [-1, 1, -1], [-1, -1, 1]], np.float64)
GLOSS_SCALE, GLOSS_BIAS = 0.497556, 0.001466
TETRA = 0.588235
QUAD = ((0, 0), (0, 1), (0, 2), (1, 1), (1, 2), (2, 2))
HUGE = 1e30          # stands in for an infinite constant (fits float32; see fsym)
ADDRESS = {"wrap": "periodic", "clamp": "clamp"}


class Poison(ValueError):
    pass


def _bits(x):
    return np.asarray(x, np.float64).astype(np.float32).view(np.uint32)


def _float(b):
    return np.asarray(b, np.uint32).view(np.float32).astype(np.float64)


class V:
    """One 32-bit register component: probe values and a symbol.

    num: float64 values (f True) or uint32 bits (f False). sym: ("f", float or
    Ref), ("b", Ref) for a comparison mask (1 = all bits set), or None.
    aff: affine coefficients over (x, y, z, 1) when the value is affine.
    quad: its gradient as three affine rows when it is quadratic instead
    (bilinear corner uvs), for derivatives.
    d: 0 known constant, 1 position only, 2 data.
    rough: made through a non-analytic op (min, max, abs, saturate, a select,
    integer work) of a varying value, so only piecewise polynomial: never fitted.
    cam: a function of the depth alone. The camera is synthetic and sits well
    above every probe, so a compare, min or max on such values (the depth
    encoding switch, the clamp before 1/depth) has one outcome by
    construction: it is resolved on the probes and checked to be uniform.
    """
    __slots__ = ("num", "f", "sym", "aff", "d", "quad", "rough", "cam")

    def __init__(self, num, f, sym=None, aff=None, d=2, quad=None, rough=False, cam=False):
        self.num, self.f, self.sym, self.aff, self.d, self.quad, self.rough, self.cam =             num, f, sym, aff, d, quad, rough, cam

    def copy(self, **kw):
        v = V(self.num.copy(), self.f, self.sym, self.aff, self.d, self.quad, self.rough, self.cam)
        for k, x in kw.items():
            setattr(v, k, x)
        return v

    def bits(self):
        return _bits(self.num) if self.f else self.num

    def flt(self):
        return self.num if self.f else _float(self.num)


def encode_face(g, n, k):
    """The decal shaders' tetrahedron encode of normal n (three floats or refs) onto face k: (x, y)."""
    a = FACE_SIGNS[k] * 0.57735
    ex = g.add(g.add(g.mul(n[0], a[0] * 0.707107), g.mul(n[1], a[1] * -1.414214)), g.mul(n[2], a[2] * 0.707107))
    ey = g.add(g.mul(n[0], a[0] * -1.224745), g.mul(n[2], a[2] * 1.224745))
    d = g.add(g.add(g.mul(n[0], a[0]), g.mul(n[1], a[1])), g.mul(n[2], a[2]))
    s = g.div(TETRA, g.sqrt(g.add(g.abs(d), 1.0)))
    return g.add(g.mul(ex, s), 0.5), g.add(g.mul(ey, s), 0.5)


def decode_face(g, x, y, k):
    """decode_tetra_normal for face k: three floats or refs."""
    x, y = g.div(g.sub(x, 0.5), TETRA), g.div(g.sub(y, 0.5), TETRA)
    d = g.add(g.mul(x, x), g.mul(y, y))
    s = g.sqrt(g.max(g.sub(2.0, d), 0.0))
    a = g.mul(g.sub(1.0, d), 0.57735)
    sx, sy = g.mul(s, x), g.mul(s, y)
    n = [g.sub(g.add(a, g.mul(sx, 0.408248)), g.mul(sy, 0.707107)),
         g.sub(a, g.mul(sx, 0.816497)),
         g.add(g.add(a, g.mul(sx, 0.408248)), g.mul(sy, 0.707107))]
    return [g.mul(c, float(FACE_SIGNS[k][i])) for i, c in enumerate(n)]


def face_indicators(g, n):
    """1 on the face the encoder picks (the axis closest to n, first on ties), else 0."""
    d = [g.add(g.add(g.mul(n[0], s[0]), g.mul(n[1], s[1])), g.mul(n[2], s[2])) for s in FACE_SIGNS]
    out = []
    for k in range(4):
        ind = 1.0
        for j in range(4):
            if j != k:
                ind = g.mul(ind, g.ifgt(d[k], d[j], 1.0, 0.0) if j < k else g.ifge(d[k], d[j], 1.0, 0.0))
        out.append(ind)
    return out


def select(g, indicators, values):
    """sum_k indicator_k * value_k, collapsing when every value is the same."""
    names = {v.name if hasattr(v, "name") else repr(v) for v in values}
    if len(names) == 1:
        return values[0]
    out = 0.0
    for ind, v in zip(indicators, values):
        out = g.add(out, g.mul(ind, v))
    return out


class GBufferState:
    """RT0 (linear rgb, a) and RT1 (x, y, gloss channel) as symbols, and the face indicators."""

    def __init__(self, g, albedo, normal, gloss):
        self.g = g
        self.face = face_indicators(g, normal)
        enc = [encode_face(g, normal, k) for k in range(4)]
        self.rt = {0: [albedo[0], albedo[1], albedo[2], 1.0],
                   1: [select(g, self.face, [e[0] for e in enc]), select(g, self.face, [e[1] for e in enc]),
                       g.add(g.mul(gloss, GLOSS_SCALE), GLOSS_BIAS), None]}

    def surface(self):
        g = self.g
        x, y, z = self.rt[1][:3]
        n = [select(g, self.face, [decode_face(g, x, y, k)[i] for k in range(4)]) for i in range(3)]
        # Stored gloss at 0.5 and above carries a flag bit (bo4_decal_composite GBuffer.surface).
        gloss = g.sat(g.div(g.sub(z, g.ifge(z, 0.5, 0.5, GLOSS_BIAS)), GLOSS_SCALE))
        return self.rt[0][:3], n, gloss


def _factor(g, name, src, dst, alpha, c):
    if name == "ZERO":
        return 0.0
    if name == "ONE":
        return 1.0
    if name in ("SRC_ALPHA", "INV_SRC_ALPHA") and src[3] is None:
        raise NotImplementedError("a blend factor reads a source alpha the shader leaves unmodelled")
    if name == "SRC_ALPHA":
        return src[3]
    if name == "INV_SRC_ALPHA":
        return g.sub(1.0, src[3])
    if name in ("SRC_COLOR", "INV_SRC_COLOR"):
        v = src[3] if alpha else src[c]
        return g.sub(1.0, v) if name.startswith("INV") else v
    raise NotImplementedError(f"blend factor {name}")


def blend(g, state, src, dst):
    """The output merger for one target on symbols; dst channels a write mask leaves alone stay."""
    out = list(dst)
    for c in range(4):
        if not state["write_mask"] >> c & 1:
            continue
        if dst[c] is None:
            raise NotImplementedError("a decal writes a channel the terrain does not model")
        if not state["enable"]:
            out[c] = src[c]
            continue
        alpha = c == 3
        s_name, d_name, op = ((state["src_alpha"], state["dst_alpha"], state["op_alpha"]) if alpha else
                              (state["src"], state["dst"], state["op"]))
        s = g.mul(src[c], _factor(g, s_name, src, dst, alpha, c))
        d = g.mul(dst[c], _factor(g, d_name, src, dst, alpha, c))
        if op == "ADD":
            out[c] = g.add(s, d)
        elif op == "SUBTRACT":
            out[c] = g.sub(s, d)
        elif op == "REV_SUBTRACT":
            out[c] = g.sub(d, s)
        else:
            raise NotImplementedError(f"blend op {op}")
    return out


class DecalTranslator:
    """Emits one decal's draw into a Graph, onto a GBufferState."""

    def __init__(self, g, scene, decals, image_path, seed=0):
        """g: Graph; scene: build_bo4_terrain_usd.Scene (world position and geometric normal);
        decals: bo4_decal_composite.DecalScene; image_path(png_file) -> the path a graph image uses."""
        self.g, self.scene, self.decals, self.image_path = g, scene, decals, image_path
        self.rng = np.random.default_rng(seed)
        gn = [g.comp(scene.N, i) for i in range(3)]
        self.slope = (g.div(g.mul(gn[0], -1.0), gn[2]), g.div(gn[1], gn[2]))   # dz along +x, dz along -y

    # ------------------------------------------------------------ bindings
    def bindings(self, material):
        """{t register: (png_file, dxgi format)} and {s register: address mode} for a decal material."""
        m = self.decals.materials[material]
        images = {im["raw_semantic"]: im for im in m["images"]}
        textures, samplers = {}, {}
        states = {s["hash"]: s["state"] for s in m["samplers"]}
        for arg in m["pass_arguments"]:
            if arg["kind"] == "texture":
                im = images[arg["hash"]]
                textures[arg["slot"]] = (im["png_file"], im["dxgi_format"])
            elif arg["kind"] == "sampler":
                word = int(states[arg["hash"]], 16)
                samplers[arg["slot"]] = ADDRESS.get({0: "wrap", 1: "clamp"}.get((word >> 5) & 3), "periodic")
        bound = self.decals.material(material)
        if bound.atlas_register is not None:
            atlas = self.decals.atlas_row
            textures[bound.atlas_register] = (atlas["png_file"], atlas["dxgi_format"])
        return textures, samplers

    # -------------------------------------------------------------- probes
    def probes(self, decal, face):
        """Probe points around the decal box, with shaded normals on `face` and geometric normals."""
        n, rng = PROBES, self.rng
        # Points in the decal's own frame, local coordinates in [-1.4, 1.4]^3:
        # about a third inside the box, the rest just outside it.
        M = np.array(decal["world_to_local"]["matrix"], np.float64)
        t = np.array(decal["world_to_local"]["translation"], np.float64)
        he = np.array(decal["half_extents"], np.float64)
        local = rng.uniform(-1.4, 1.4, (n, 3))
        p = (local * he - t) @ np.linalg.inv(M)
        axis0 = np.array(decal["axes"][0], np.float64)
        axis0 /= np.linalg.norm(axis0)

        def unit(k, near=None):
            v = rng.normal(size=(n * 32, 3))
            v /= np.linalg.norm(v, axis=1, keepdims=True)
            if near is not None:
                # Half of them near the projection axis, where the angle test passes.
                w = near + rng.normal(size=(n * 32, 3)) * 0.4
                w /= np.linalg.norm(w, axis=1, keepdims=True)
                v = np.where((np.arange(len(v)) % 2 == 0)[:, None], w, v)
            v = v[np.argmax(v @ FACE_SIGNS.T, 1) == k] if k is not None else v[v[:, 2] > 0.3]
            return v[:n]
        return p, unit(face, axis0), unit(None), rng.random(n) * 0.49

    # ----------------------------------------------------------- translate
    def draw(self, decal, gb, report=None):
        """Blend one decal into gb (a GBufferState). Returns the alive symbol."""
        g = self.g
        m = self.decals.material(decal["material"])
        shader = m.shader
        runs = [self.run(shader, decal, gb, k) for k in range(4)]
        alive = select(g, gb.face, [r[1] for r in runs])
        for rt in (0, 1):
            state = m.blend[rt]
            if not state["write_mask"] or rt not in runs[0][0]:
                continue
            for r in runs:
                for c in range(4):
                    if state["write_mask"] >> c & 1 and isinstance(r[0][rt][c], Poison):
                        raise r[0][rt][c]
            # The source alpha feeds blend factors even where the mask does not store it.
            src = [None if any(isinstance(r[0][rt][c], Poison) for r in runs) else
                   g.sat(select(g, gb.face, [r[0][rt][c] for r in runs])) for c in range(4)]
            new = blend(g, state, src, gb.rt[rt])
            gb.rt[rt] = [d if d is None or n is d else g.add(d, g.mul(g.sub(n, d), alive))
                         for n, d in zip(new, gb.rt[rt])]
        return alive

    def run(self, shader, decal, gb, face):
        """One pass of the shader with the destination face held at `face`: ({rt: [4 symbols]}, alive)."""
        g = self.g
        self.face = face
        m = self.decals.material(decal["material"])
        textures, samplers = self.bindings(decal["material"])
        self.textures, self.sampler_modes, self.resources = textures, samplers, m.resources
        self.samplers = m.samplers
        pts, shaded, geo, gloss = self.probes(decal, face)
        self.shaded = shaded
        self.basis = np.concatenate([pts, np.ones((len(pts), 1))], 1)
        self.centre, self.span = pts.mean(0), np.maximum(pts.std(0), 1.0)
        self.geo = geo
        n = len(pts)
        # The camera: straight down, as bo4_decal_composite.camera, solved per lane in float64.
        top = float(pts[:, 2].max()) + 64.0
        dist = top - pts[:, 2]
        cx, cy = pts[:, 0].mean(), pts[:, 1].mean()
        W = H = 64.0
        kx = ky = float(np.float32(1.0 / float(np.median(dist))))
        cb2 = np.zeros((CB2_ROWS, 4), np.float32)
        cb2[12, 0], cb2[13, 1] = kx, ky
        cb2[16, :3], cb2[17, :3], cb2[18, :3] = (1, 0, 0), (0, 1, 0), (0, 0, -1)
        cb2[24, :3] = (cx, cy, top)
        cb2[61, 2:] = (1 / W, 1 / H)
        if m.atlas_register is not None:
            width, height, _ = m.resources[m.atlas_register].size(0)
            cb2[113, 2:] = (0.5 / width, 0.5 / height)
        c24 = cb2[24, :3].astype(np.float64)
        ndc_x = (pts[:, 0] - c24[0]) / (np.float64(cb2[12, 0]) * dist)
        ndc_y = (pts[:, 1] - c24[1]) / (np.float64(cb2[13, 1]) * dist)
        v2 = np.stack([(ndc_x + 1) / (2 * np.float64(cb2[61, 2])), (1 - ndc_y) / (2 * np.float64(cb2[61, 3]))], 1)
        dist = top - pts[:, 2]
        depth = 1.0 / (dist * np.float64(np.float32(DEPTH_SCALE)))
        enc = np.zeros((n, 4))
        for i in range(n):
            gg = _NumGraph()
            ex, ey = encode_face(gg, list(shaded[i]), face)
            enc[i] = (ex, ey, gloss[i] * GLOSS_SCALE + GLOSS_BIAS, face / 3.0)
        self.t0 = V(depth, True, d=1, cam=True)
        self.t6 = [V(enc[:, c], True, ("f", gb.rt[1][c])) for c in range(3)] + [V(enc[:, 3], True, d=0)]
        self.cb = {0: np.asarray(m.cb0, np.float32).view(np.uint32), 2: cb2.view(np.uint32)}
        self.record = np.frombuffer(gpu_record(decal), np.uint8)
        self.v = {0: [V(np.zeros(n, np.uint32), False, d=0) for _ in range(4)],
                  1: [V(np.ones(n), True, d=0) for _ in range(4)],
                  2: [V(v2[:, 0], True, d=1), V(v2[:, 1], True, d=1), V(np.zeros(n), True, d=0),
                      V(np.ones(n), True, d=0)]}
        self.r = {}
        self.o = {}
        self.n = n
        self.alive_num = np.ones(n, bool)
        self.alive = 1.0
        self.shader = shader
        self._block(0, len(shader.prog), np.ones(n, bool), 1.0)
        outs = {}
        for rt, comps in self.o.items():
            outs[rt] = [self._out(c, f"o{rt}") for c in comps]
        return outs, self.alive

    # ------------------------------------------------------------ symbols
    @staticmethod
    def _cam(srcs):
        """True when the varying inputs are all depth-only."""
        vary = [x for x in srcs if x.d > 0]
        return bool(vary) and all(x.cam for x in vary)

    def _out(self, v, where):
        try:
            return self.fsym(v, self.alive_num, where)
        except Poison as e:
            return e

    def fsym(self, v, live, where):
        """A component's float symbol (a constant when its probe values agree)."""
        if v.d == 0:
            x = float(v.flt()[0])
            if np.isfinite(x):
                return x
            # rcp of a zero constant: the shaders use it as saturate(t * inf), a hard step. HUGE keeps that
            # step (0 below, 1 above, and 0 at t = 0 where D3D saturates the NaN to 0) without putting a
            # non-finite literal in the graph, which renderers may not parse and which turns t = 0 into NaN.
            if np.isnan(x):
                raise Poison(f"{where}: a NaN constant")
            return HUGE if x > 0 else -HUGE
        if v.sym is not None and v.sym[0] == "f":
            return v.sym[1]
        raise Poison(f"{where}: a varying value with no symbol (probe values {v.flt()[live][:4]})")

    def bsym(self, v, live, where):
        """A mask's symbol: 1.0 where all bits are set."""
        if v.d == 0:
            return 1.0 if v.bits()[0] else 0.0
        if v.sym is not None and v.sym[0] == "b":
            return v.sym[1]
        if v.sym is not None and v.sym[0] == "f":
            # A float used as a condition: nonzero.
            return self.g.ifgt(self.g.abs(v.sym[1]), 0.0, 1.0, 0.0)
        raise Poison(f"{where}: a varying condition with no symbol")

    def canon(self, v, live):
        """Replace the symbol by a constant, or by an affine node when a smooth position value fits one.

        A value built from analytic ops that is affine (or quadratic) on the
        probes is so everywhere; a rough one could fit one piece only.
        """
        if v.d == 0:
            if v.f:
                v.sym, v.aff = ("f", float(v.num[0])), np.array([0, 0, 0, v.num[0]])
            return v
        if not v.f or v.d != 1 or v.rough:
            return v
        vals = v.num[live]
        if live.sum() < 12 or not np.all(np.isfinite(vals)):
            return v
        A = self.basis[live]
        coef = np.linalg.lstsq(A, vals, rcond=None)[0]
        resid = np.abs(A @ coef - vals).max()
        scale = (np.abs(A) @ np.abs(coef)).max() + np.abs(vals).max()
        if resid <= 1e-9 * scale:
            v.aff = coef
            v.sym = ("f", self.scene.affine(tuple(float(c) for c in coef)))
            return v
        # Quadratic, in coordinates centred and scaled on the probes.
        q = (self.basis[live, :3] - self.centre) / self.span
        cols = [np.ones(len(q))] + [q[:, i] for i in range(3)] + [q[:, i] * q[:, j] for i, j in QUAD]
        A = np.stack(cols, 1)
        coef = np.linalg.lstsq(A, vals, rcond=None)[0]
        if np.abs(A @ coef - vals).max() <= 1e-7 * (np.abs(vals).max() + 1e-30):
            rows = []
            for k in range(3):
                # d/dq_k = c_k + sum over monomials q_i q_j of c_ij (d q_i q_j / d q_k), then / span.
                row = np.zeros(4)
                row[3] = coef[1 + k]
                for m, (i, j) in enumerate(QUAD):
                    c = coef[4 + m]
                    if i == k:
                        row[j] += c
                    if j == k:
                        row[i] += c
                # row is over q; q = (P - centre) / span.
                aff = np.zeros(4)
                aff[:3] = row[:3] / self.span
                aff[3] = row[3] - row[:3] @ (self.centre / self.span)
                rows.append(aff / self.span[k])
            v.quad = rows
        return v

    # ------------------------------------------------------------ operands
    def fetch(self, o, live, where):
        """Operand o as 4 components (swizzled, with neg/abs applied as floats)."""
        k = o.kind
        if k == "r":
            comps = self.r.setdefault(o.index, [V(np.zeros(self.n, np.uint32), False, d=0) for _ in range(4)])
        elif k == "v":
            comps = self.v[o.index]
        elif k == "l":
            comps = [V(np.full(self.n, o.lit[c], np.uint32), False, d=0) for c in range(4)]
        elif k == "cb":
            buf = self.cb[o.cb]
            if o.cb_reg is not None:
                raise NotImplementedError(f"{where}: dynamic constant buffer index")
            row = buf[o.cb_off] if o.cb_off < len(buf) else np.zeros(4, np.uint32)
            comps = [V(np.full(self.n, row[c], np.uint32), False, d=0) for c in range(4)]
        else:
            raise NotImplementedError(f"{where}: operand {o.raw}")
        out = [comps[s] for s in o.swz]
        if o.abs or o.neg:
            g = self.g
            fixed = []
            for c in out:
                rough = c.rough
                num = c.flt()
                sym = c.sym[1] if c.sym is not None and c.sym[0] == "f" else None
                aff = c.aff
                if o.abs:
                    num, sym, aff = np.abs(num), g.abs(sym) if sym is not None else None, None
                    rough = rough or c.d > 0
                if o.neg:
                    num = -num
                    sym = g.mul(sym, -1.0) if sym is not None else None
                    aff = -aff if aff is not None else None
                fixed.append(V(num, True, ("f", sym) if sym is not None and c.d else None, aff, c.d,
                               rough=rough and not (c.cam and np.array_equal(num, np.abs(c.flt()) * (-1 if o.neg else 1))),
                               cam=c.cam))
            out = fixed
        return out

    def write(self, o, values, live, sat=False):
        if o.kind == "null":
            return
        bank = self.o if o.kind == "o" else self.r
        comps = bank.setdefault(o.index, [V(np.zeros(self.n, np.uint32), False, d=0) for _ in range(4)])
        for c in o.mask():
            v = values[c]
            if sat:
                num = np.clip(np.nan_to_num(v.flt()), 0, 1)
                sym = self.g.sat(v.sym[1]) if v.d and v.sym is not None and v.sym[0] == "f" else None
                if v.cam and np.array_equal(num, v.flt()):
                    v = v.copy()
                else:
                    v = V(num, True, ("f", sym) if sym is not None else None, d=v.d, rough=v.rough or v.d > 0)
            # Inside a branch the lanes that did not take it keep garbage: the
            # merge at the end of the branch takes this value on its lanes only.
            comps[c] = self.canon(v.copy(), live)

    # ------------------------------------------------------------ control
    def _block(self, pc, end, live, pred):
        prog = self.shader.prog
        while pc < end:
            ins = prog[pc]
            where = f"{pc}: {ins.line.strip()}"
            if ins.op in ("if_nz", "if_z"):
                c = self.fetch(ins.args[0], live, where)[0]
                cond = (c.bits() != 0) if ins.op == "if_nz" else (c.bits() == 0)
                els, fin = self.shader.jump.get(pc), self.shader.jump[("end", pc)]
                taken, other = live & cond, live & ~cond
                if c.d == 0:
                    if cond[0]:
                        self._block(pc + 1, els if els is not None else fin, live, pred)
                    elif els is not None:
                        self._block(els + 1, fin, live, pred)
                    pc = fin + 1
                    continue
                b = self.bsym(c, live, where)
                if ins.op == "if_z":
                    b = self.g.sub(1.0, b)
                saved = self._snapshot()
                self._block(pc + 1, els if els is not None else fin, taken, self.g.mul(pred, b))
                then = self._snapshot()
                self._restore(saved)
                if els is not None:
                    self._block(els + 1, fin, other, self.g.mul(pred, self.g.sub(1.0, b)))
                self._merge(then, b, live, cond, where)
                pc = fin + 1
                continue
            if ins.op == "ret":
                if pred != 1.0:
                    raise NotImplementedError(f"{where}: return inside a branch")
                return
            if ins.op in ("loop", "break", "breakc_nz", "breakc_z", "continue"):
                raise NotImplementedError(f"{where}: loops")
            self.exec(ins, live, pred, where)
            pc += 1

    def _snapshot(self):
        return {("r", k): [c.copy() for c in v] for k, v in self.r.items()} | \
            {("o", k): [c.copy() for c in v] for k, v in self.o.items()}

    def _restore(self, snap):
        self.r = {k[1]: v for k, v in snap.items() if k[0] == "r"}
        self.o = {k[1]: v for k, v in snap.items() if k[0] == "o"}

    def _merge(self, then, b, live, cond, where):
        """Registers after an if/else: the then-branch where b, else the else-branch."""
        g = self.g
        now = self._snapshot()
        for key in set(then) | set(now):
            zero = [V(np.zeros(self.n, np.uint32), False, d=0) for _ in range(4)]
            a_list, e_list = then.get(key, zero), now.get(key, zero)
            merged = []
            for a, e in zip(a_list, e_list):
                if a.sym == e.sym and np.array_equal(a.bits(), e.bits()):
                    merged.append(a)
                    continue
                f = a.f and e.f
                num = np.where(cond, a.num, e.num) if f else np.where(cond, a.bits(), e.bits())
                try:
                    sa, se = self.fsym(a, live & cond, where), self.fsym(e, live & ~cond, where)
                    sym = ("f", g.add(se, g.mul(g.sub(sa, se), b)))
                except Poison:
                    sym = None
                merged.append(V(num, f, sym if f else None, None, 2))
            bank = self.r if key[0] == "r" else self.o
            bank[key[1]] = merged

    # ------------------------------------------------------------ execute
    def exec(self, ins, live, pred, where):
        g, op, a = self.g, ins.op, ins.args
        F = lambda o: self.fetch(o, live, where)
        fl = lambda xs: [(x.flt(), x.sym[1] if x.sym is not None and x.sym[0] == "f" else None) for x in xs]

        def sym_of(x, i):
            try:
                return self.fsym(x, live, where)
            except Poison:
                return None

        def fop(fn_num, fn_sym, *ops, smooth=True):
            srcs = [F(o) for o in ops]
            out = []
            for c in range(4):
                nums = [s[c].flt() for s in srcs]
                with np.errstate(all="ignore"):
                    num = fn_num(*nums)
                d = max(s[c].d for s in srcs)
                syms = [sym_of(s[c], c) for s in srcs] if d else []
                sym = None if d == 0 or any(s is None for s in syms) else fn_sym(*syms)
                cam = self._cam([s[c] for s in srcs])
                if cam and not smooth:
                    pick = [s[c] for s in srcs if np.array_equal(s[c].flt(), num)]
                    if not pick:
                        raise NotImplementedError(f"{where}: a depth-only min/max without one outcome")
                    out.append(pick[0].copy())
                    continue
                rough = any(s[c].rough for s in srcs) or (not smooth and d > 0)
                out.append(V(num, True, ("f", sym) if sym is not None else None, d=d, rough=rough, cam=cam))
            return out

        if op == "mov":
            src = F(a[1])
            self.write(a[0], [s.copy() for s in src], live, ins.sat)
        elif op == "add":
            self.write(a[0], fop(np.add, g.add, a[1], a[2]), live, ins.sat)
        elif op == "mul":
            self.write(a[0], fop(np.multiply, g.mul, a[1], a[2]), live, ins.sat)
        elif op == "mad":
            self.write(a[0], fop(lambda x, y, z: x * y + z, lambda x, y, z: g.add(g.mul(x, y), z), a[1], a[2], a[3]),
                       live, ins.sat)
        elif op == "div":
            self.write(a[0], fop(np.divide, g.div, a[1], a[2]), live, ins.sat)
        elif op == "min":
            self.write(a[0], fop(np.fmin, g.min, a[1], a[2], smooth=False), live, ins.sat)
        elif op == "max":
            self.write(a[0], fop(np.fmax, g.max, a[1], a[2], smooth=False), live, ins.sat)
        elif op == "rcp":
            self.write(a[0], fop(lambda x: 1 / x, lambda x: g.div(1.0, x), a[1]), live, ins.sat)
        elif op == "rsq":
            self.write(a[0], fop(lambda x: 1 / np.sqrt(x), lambda x: g.div(1.0, g.sqrt(x)), a[1]), live, ins.sat)
        elif op == "sqrt":
            self.write(a[0], fop(np.sqrt, g.sqrt, a[1]), live, ins.sat)
        elif op == "log":
            self.write(a[0], fop(np.log2, g.log2, a[1]), live, ins.sat)
        elif op == "exp":
            self.write(a[0], fop(np.exp2, g.exp2, a[1]), live, ins.sat)
        elif op in ("dp2", "dp3", "dp4"):
            k = int(op[2])
            x, y = F(a[1]), F(a[2])
            num = sum(x[c].flt() * y[c].flt() for c in range(k))
            d = max(max(x[c].d, y[c].d) for c in range(k))
            sym = 0.0
            try:
                for c in range(k):
                    sym = g.add(sym, g.mul(self.fsym(x[c], live, where), self.fsym(y[c], live, where)))
                sym = ("f", sym)
            except Poison:
                sym = None
            rough = any(x[c].rough or y[c].rough for c in range(k))
            cam = self._cam([x[c] for c in range(k)] + [y[c] for c in range(k)])
            self.write(a[0], [V(num, True, sym if d else None, d=d, rough=rough, cam=cam) for _ in range(4)], live,
                       ins.sat)
        elif op in ("lt", "ge", "eq", "ne"):
            x, y = F(a[1]), F(a[2])
            out = []
            for c in range(4):
                xn, yn = x[c].flt(), y[c].flt()
                r = {"lt": xn < yn, "ge": xn >= yn, "eq": xn == yn, "ne": xn != yn}[op]
                num = np.where(r, np.uint32(0xFFFFFFFF), np.uint32(0))
                sym = None
                d = max(x[c].d, y[c].d)
                if self._cam([x[c], y[c]]):
                    if not (np.all(num == num[0])):
                        raise NotImplementedError(f"{where}: a depth-only compare without one outcome")
                    out.append(V(num, False, d=0))
                    continue
                try:
                    if d == 0:
                        raise Poison("constant")
                    xs, ys = self.fsym(x[c], live, where), self.fsym(y[c], live, where)
                    if op == "lt":
                        sym = g.ifgt(ys, xs, 1.0, 0.0)
                    elif op == "ge":
                        sym = g.ifge(xs, ys, 1.0, 0.0)
                    else:
                        eq = g.mul(g.ifge(xs, ys, 1.0, 0.0), g.ifge(ys, xs, 1.0, 0.0))
                        sym = eq if op == "eq" else g.sub(1.0, eq)
                    sym = ("b", sym)
                except Poison:
                    pass
                out.append(V(num, False, sym, d=d, rough=d > 0))
            self.write(a[0], out, live)
        elif op == "movc":
            c, x, y = F(a[1]), F(a[2]), F(a[3])
            out = []
            for k in range(4):
                cond = c[k].bits() != 0
                f = x[k].f and y[k].f
                num = np.where(cond, x[k].num, y[k].num) if f else np.where(cond, x[k].bits(), y[k].bits())
                if c[k].d == 0:
                    out.append((x[k] if cond[0] else y[k]).copy())
                    continue
                d = max(c[k].d, x[k].d, y[k].d)
                sym = None
                try:
                    b = self.bsym(c[k], live, where)
                    xs, ys = self.fsym(x[k], live & cond, where), self.fsym(y[k], live & ~cond, where)
                    sym = ("f", g.add(ys, g.mul(g.sub(xs, ys), b)))
                    if not f:
                        num, f = np.where(cond, x[k].flt(), y[k].flt()), True
                except Poison:
                    pass
                out.append(V(num, f, sym, d=d, rough=True))
            self.write(a[0], out, live)
        elif op in ("and", "or", "xor"):
            x, y = F(a[1]), F(a[2])
            out = []
            for k in range(4):
                xb, yb = x[k].bits(), y[k].bits()
                num = {"and": xb & yb, "or": xb | yb, "xor": xb ^ yb}[op]
                d = max(x[k].d, y[k].d)
                sym = self.bitwise_sym(op, x[k], y[k], live, where) if d else None
                if sym is not None and sym[0] == "f":
                    out.append(V(_float(num), True, sym, d=d, rough=d > 0))
                else:
                    out.append(V(num, False, sym, d=d, rough=d > 0))
            self.write(a[0], out, live)
        elif op in ("ftoi", "ftou", "itof", "utof", "ishl", "ushr", "ishr", "iadd", "imul", "ieq", "ine", "ilt", "ige",
                    "not", "imin", "imax", "ineg"):
            self.write(a[0], self.int_op(ins, live, where), live)
        elif op in ("deriv_rtx_coarse", "deriv_rty_coarse", "deriv_rtx", "deriv_rty", "deriv_rtx_fine",
                    "deriv_rty_fine"):
            horizontal = "rtx" in op
            src = F(a[1])
            out = []
            for c in range(4):
                v = src[c]
                if v.d == 0:
                    out.append(V(np.zeros(self.n), True, d=0))
                    continue
                gx, gy, gz = self.geo[:, 0], self.geo[:, 1], self.geo[:, 2]
                if v.aff is None and v.quad is not None:
                    # The gradient is affine: its rows at the probes and as nodes.
                    grad = [self.basis @ row for row in v.quad]
                    gs = [self.scene.affine(tuple(float(c) for c in row)) for row in v.quad]
                    if horizontal:
                        num = grad[0] + grad[2] * (-gx / gz)
                        sym = g.add(gs[0], g.mul(gs[2], self.slope[0]))
                    else:
                        num = -grad[1] + grad[2] * (gy / gz)
                        sym = g.add(g.mul(gs[1], -1.0), g.mul(gs[2], self.slope[1]))
                    out.append(V(num, True, ("f", sym), d=2))
                    continue
                if v.aff is None:
                    raise NotImplementedError(f"{where}: derivative of a value that is not polynomial in position")
                ax, ay, az = v.aff[:3]
                if horizontal:
                    num = ax + az * (-gx / gz)
                    sym = g.add(ax, g.mul(az, self.slope[0])) if az else ax
                else:
                    num = -ay + az * (gy / gz)
                    sym = g.add(-ay, g.mul(az, self.slope[1])) if az else -ay
                out.append(V(num, True, ("f", sym), d=2) if az else V(np.full(self.n, float(sym)), True, d=0))
            self.write(a[0], out, live)
        elif op in ("discard_nz", "discard_z"):
            c = F(a[0])[0]
            cond = c.bits() != 0
            kill = live & (cond if op == "discard_nz" else ~cond)
            self.alive_num &= ~kill
            if kill.any() or c.d:
                b = self.bsym(c, live, where)
                if op == "discard_z":
                    b = g.sub(1.0, b)
                self.alive = g.mul(self.alive, g.sub(1.0, g.mul(pred, b)))
        elif op == "ld_structured":
            idx, off = F(a[1])[0].bits(), F(a[2])[0].bits()
            if not (np.all(idx == 0)):
                raise NotImplementedError(f"{where}: structured load at a varying index")
            t = a[3]
            if t.index != 21:
                raise NotImplementedError(f"{where}: structured buffer t{t.index}")
            base = int(off[0])
            words = [np.frombuffer(self.record[base + 4 * c:base + 4 * c + 4].tobytes(), np.uint32)[0]
                     if base + 4 * c + 4 <= len(self.record) else np.uint32(0) for c in range(4)]
            vals = [V(np.full(self.n, words[s], np.uint32), False, d=0) for s in t.swz]
            self.write(a[0], vals, live)
        elif op == "ld":
            t = a[2]
            if t.index == 0:
                comps = [self.t0] + [V(np.zeros(self.n), True, d=0) for _ in range(3)]
            elif t.index == 6:
                comps = self.t6
            else:
                raise NotImplementedError(f"{where}: texel load from t{t.index}")
            self.write(a[0], [comps[s].copy() for s in t.swz], live)
        elif op in ("sample", "sample_l"):
            self.write(a[0], self.sample(ins, live, where), live, ins.sat)
        else:
            raise NotImplementedError(f"{where}: opcode {op}")

    def bitwise_sym(self, op, x, y, live, where):
        g = self.g
        xc, yc = x.d == 0, y.d == 0
        kind = lambda v: v.sym[0] if v.sym is not None else None
        # Sign-bit tricks on a float with a known mask: negate, abs, -abs.
        for m, other, oc in ((x, y, yc), (y, x, xc)):
            if kind(m) == "f" and oc:
                bits = int(other.bits()[0])
                if bits == 0 and op in ("xor", "or"):
                    return m.sym
                if bits == 0x80000000 and op == "xor":
                    return ("f", g.mul(m.sym[1], -1.0))
                if bits == 0x7FFFFFFF and op == "and":
                    return ("f", g.abs(m.sym[1]))
                if bits == 0x80000000 and op == "or":
                    return ("f", g.mul(g.abs(m.sym[1]), -1.0))
        if op == "and":
            for m, other, oc in ((x, y, yc), (y, x, xc)):
                if kind(m) == "b":
                    if kind(other) == "b":
                        return ("b", g.mul(m.sym[1], other.sym[1]))
                    if oc:
                        bits = other.bits()[0]
                        if bits == 0xFFFFFFFF:
                            return m.sym
                        value = float(_float(np.array([bits]))[0])
                        if np.isfinite(value):
                            return ("f", g.mul(m.sym[1], value))
                    elif kind(other) == "f":
                        return ("f", g.mul(m.sym[1], other.sym[1]))
            return None
        if kind(x) == "b" and kind(y) == "b":
            if op == "or":
                return ("b", g.max(x.sym[1], y.sym[1]))
            return ("b", g.abs(g.sub(x.sym[1], y.sym[1])))
        return None

    def int_op(self, ins, live, where):
        op, a = ins.op, ins.args
        srcs = [self.fetch(o, live, where) for o in a[1:]]
        out = []
        for c in range(4):
            d = max(s[c].d for s in srcs)
            if op in ("ftoi", "ftou"):
                x = np.nan_to_num(srcs[0][c].flt())
                num = (np.clip(np.trunc(x), -2 ** 31, 2 ** 31 - 1).astype(np.int64).astype(np.int32).view(np.uint32)
                       if op == "ftoi" else np.clip(np.trunc(x), 0, 2 ** 32 - 1).astype(np.uint64).astype(np.uint32))
                out.append(V(num, False, d=d, rough=d > 0))
                continue
            if op in ("itof", "utof"):
                b = srcs[0][c].bits()
                num = b.view(np.int32).astype(np.float64) if op == "itof" else b.astype(np.float64)
                out.append(V(num, True, d=d, rough=d > 0))
                continue
            xb = srcs[0][c].bits()
            yb = srcs[1][c].bits() if len(srcs) > 1 else None
            xi = xb.view(np.int32).astype(np.int64)
            yi = yb.view(np.int32).astype(np.int64) if yb is not None else None
            if op == "ishl":
                num = (xb << (yb & 31)).astype(np.uint32)
            elif op == "ushr":
                num = xb >> (yb & 31)
            elif op == "ishr":
                num = (xb.view(np.int32) >> (yb & 31).astype(np.int32)).view(np.uint32)
            elif op == "iadd":
                num = (xi + yi).astype(np.int32).view(np.uint32)
            elif op == "imul":
                num = (xi * yi).astype(np.int32).view(np.uint32)
            elif op in ("imin", "imax"):
                num = (np.minimum if op == "imin" else np.maximum)(xi, yi).astype(np.int32).view(np.uint32)
            elif op == "ineg":
                num = (-xi).astype(np.int32).view(np.uint32)
            elif op == "not":
                num = ~xb
            else:
                r = {"ieq": xi == yi, "ine": xi != yi, "ilt": xi < yi, "ige": xi >= yi}[op]
                num = np.where(r, np.uint32(0xFFFFFFFF), np.uint32(0))
            out.append(V(num, False, d=d, rough=d > 0))
        return out

    def sample(self, ins, live, where):
        g, a = self.g, ins.args
        coord = self.fetch(a[1], live, where)
        t = a[2]
        if t.index not in self.textures:
            # An engine texture no pass argument binds (the coal variants'
            # specular lookup): only the specular target reads it.
            return [V(np.zeros(self.n), True) for _ in t.swz]
        png, fmt = self.textures[t.index]
        tex = self.resources[t.index]
        u, v = coord[0].flt(), coord[1].flt()
        s_index = a[3].index if len(a) > 3 and a[3].kind == "s" else None
        sampler = self.samplers.get(s_index)
        lod = np.zeros(self.n)
        texel = (tex.sample(u.astype(np.float32), v.astype(np.float32), np.zeros(self.n, np.int64), lod, sampler)
                 if sampler else tex.sample(u.astype(np.float32), v.astype(np.float32), np.zeros(self.n, np.int64), lod))
        texel = np.asarray(texel, np.float64)
        try:
            us, vs = self.fsym(coord[0], live, where), self.fsym(coord[1], live, where)
            img = g.image(self.image_path(png), g.uv(us, g.sub(1.0, vs)), srgb=fmt in SRGB_FORMATS,
                          clamp=self.sampler_modes.get(s_index, "periodic"))
            if fmt in R_FORMATS:
                chans = [g.comp(img, 0), 0.0, 0.0, 1.0]
            elif fmt in RG_FORMATS:
                chans = [g.comp(img, 0), g.comp(img, 1), 0.0, 1.0]
            else:
                chans = [g.comp(img, i) for i in range(4)]
        except Poison:
            chans = [None] * 4
        comps = [V(texel[:, c], True, ("f", chans[c]) if chans[c] is not None else None) for c in range(4)]
        return [comps[s] for s in t.swz]


class _NumGraph:
    """The Graph interface on plain floats, to run encode_face on probe values."""
    add = staticmethod(lambda a, b: a + b)
    sub = staticmethod(lambda a, b: a - b)
    mul = staticmethod(lambda a, b: a * b)
    div = staticmethod(lambda a, b: a / b)
    sqrt = staticmethod(lambda a: np.sqrt(a))
    abs = staticmethod(lambda a: abs(a))
    max = staticmethod(lambda a, b: max(a, b))
