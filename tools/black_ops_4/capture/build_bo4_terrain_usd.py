"""Write a BO4 terrain region as OpenUSD with a live MaterialX material: no baking.

The stage keeps the terrain in its source form and rebuilds the look at render
time, the way the game does:

- Mesh: the height grid at its native spacing, in game inches
  (metersPerUnit 0.0254, Z up), holes dropped by the cutout bits. The points
  are the game-space positions, untransformed; everything the material needs
  (layer uvs, the weight-grid uv, decal box coordinates) is an affine function
  of the object-space position (ND_position_vector3), so the constants live in
  the material, not per vertex.
- Layer weights: each used BC4 slice decoded once to a 16-bit PNG for the whole
  sector (`<sector>/weights/`), sampled bilinearly with clamped edges, as the
  pixel shader samples t20.
- Material textures and decal images are referenced from the source package;
  nothing is copied.
- Material: a MaterialX network (standard ND_ nodes) replaying the terrain
  G-buffer pixel shader's layer loop and the volume-decal pass, as read from
  the game's shaders (see docs/bo4-terrain-research.md):
  - per layer, in slot order: weight w, the height-blend w' (flag 0x4), the
    tinted or soft-light albedo, the layer normal in the frame of its uv rows
    Gram-Schmidt'd against the height normal (flag 0x2, with the detail normal
    for 0x80), and gloss -log2(2^(-17 g) + var) / 17; all lerp by w';
  - then every decal in draw order (priority descending, material pointer
    ascending), its own pixel shader translated instruction by instruction
    (bo4_dxbc_graph): box test, angle test against the G-buffer normal,
    edge fade, reveal atlas, and its writes, blended by its blend state onto
    the G-buffer in its stored form (RT1 tetrahedron-encoded).
  Far tiling (0x400) is drawn as a near camera sees it, like the bakes. Metal
  (0x10) layers stop the export.
- Surface: standard_surface with base colour = albedo, roughness =
  sqrt(sqrt(2 / (2^(17 gloss) + 2))) and the world normal.

Texture coordinates follow USD/MaterialX (v up): game v becomes 1 - v.
"""

# Support direct execution and the isolated packaged Python runtime.
import sys as _tool_sys
from pathlib import Path as _ToolPath
TOOLS_ROOT = next(p for p in _ToolPath(__file__).resolve().parents if (p / "tool_bootstrap.py").is_file())
_tool_sys.path.insert(0, str(TOOLS_ROOT))
import tool_bootstrap as _tool_bootstrap
_tool_bootstrap.activate(__file__)
import argparse
import sys
import json
import math
import os
from pathlib import Path

import numpy as np
from PIL import Image

from build_bo4_terrain_cast import ALWAYS_ONE, ALWAYS_ZERO, grid_box, load_grid, load_weights
from bo4_decal_composite import DecalScene, draw_key, footprint
from bo4_volume_decals import world_to_local
from bo4_dxbc_graph import DecalTranslator, GBufferState
from bo4_terrain_records import layer_runtime, records

LN2 = math.log(2.0)


# ------------------------------------------------------------------ graph
class Ref:
    def __init__(self, name, kind):
        self.name, self.kind = name, kind


def usd_value(kind, value):
    if kind in ("float", "int"):
        return repr(float(value)) if kind == "float" else str(int(value))
    if kind in ("string", "token"):
        return json.dumps(value)
    if kind == "asset":
        return "@%s@" % value
    return "(" + ", ".join(repr(float(v)) for v in value) + ")"


class Graph:
    """A MaterialX node graph with constant folding for float arithmetic."""

    def __init__(self):
        self.nodes = []           # (name, id, out_kind, {input: (kind, value or Ref, metadata)})
        self._seen = {}           # identical nodes are made once

    def node(self, ident, out_kind, **inputs):
        key = (ident, out_kind) + tuple(sorted(
            (k, spec[0], spec[1].name if isinstance(spec[1], Ref) else repr(spec[1])) + tuple(spec[2:])
            for k, spec in inputs.items()))
        if key in self._seen:
            return self._seen[key]
        name = "n%d" % len(self.nodes)
        self.nodes.append((name, ident, out_kind, inputs))
        self._seen[key] = ref = Ref(name, out_kind)
        return ref

    def reachable(self, outputs):
        """The nodes the outputs depend on, in creation order."""
        index = {n[0]: n for n in self.nodes}
        keep, todo = set(), [v.name for v in outputs if isinstance(v, Ref)]
        while todo:
            name = todo.pop()
            if name in keep:
                continue
            keep.add(name)
            todo += [spec[1].name for spec in index[name][3].values() if isinstance(spec[1], Ref)]
        return [n for n in self.nodes if n[0] in keep]

    # float arithmetic, folded when both sides are constants
    def _bin(self, op, fold, a, b):
        if not isinstance(a, Ref) and not isinstance(b, Ref):
            return fold(float(a), float(b))
        return self.node("ND_%s_float" % op, "float", in1=("float", a), in2=("float", b))

    def add(self, a, b):
        if not isinstance(a, Ref) and float(a) == 0:
            return b
        if not isinstance(b, Ref) and float(b) == 0:
            return a
        return self._bin("add", lambda x, y: x + y, a, b)

    def sub(self, a, b):
        if not isinstance(b, Ref) and float(b) == 0:
            return a
        return self._bin("subtract", lambda x, y: x - y, a, b)

    def mul(self, a, b):
        for x, y in ((a, b), (b, a)):
            if not isinstance(x, Ref):
                if float(x) == 1:
                    return y
                if float(x) == 0:
                    return 0.0
        return self._bin("multiply", lambda x, y: x * y, a, b)

    def div(self, a, b):
        return self._bin("divide", lambda x, y: x / y if y else 0.0, a, b)

    def max(self, a, b):
        return self._bin("max", max, a, b)

    def min(self, a, b):
        return self._bin("min", min, a, b)

    def pow(self, a, b):
        if not isinstance(b, Ref) and float(b) == 0:
            return 1.0
        return self._bin("power", lambda x, y: x ** y, a, b)

    def clamp(self, x, lo=0.0, hi=1.0):
        if not isinstance(x, Ref):
            return float(np.clip(x, lo, hi))
        return self.node("ND_clamp_float", "float", **{"in": ("float", x)}, low=("float", lo), high=("float", hi))

    def sat(self, x):
        return self.clamp(x, 0.0, 1.0)

    def unary(self, op, x, fold):
        if not isinstance(x, Ref):
            return fold(float(x))
        return self.node("ND_%s_float" % op, "float", **{"in": ("float", x)})

    def sqrt(self, x):
        return self.unary("sqrt", x, math.sqrt)

    def abs(self, x):
        return self.unary("absval", x, abs)

    def exp2(self, x):
        return self.unary("exp", self.mul(x, LN2), math.exp)

    def log2(self, x):
        return self.mul(self.unary("ln", x, math.log), 1 / LN2)

    def ifgt(self, v1, v2, a, b):
        """v1 > v2 ? a : b"""
        if not isinstance(v1, Ref) and not isinstance(v2, Ref):
            return a if float(v1) > float(v2) else b
        return self.node("ND_ifgreater_float", "float", value1=("float", v1), value2=("float", v2),
                         in1=("float", a), in2=("float", b))

    def ifge(self, v1, v2, a, b):
        """v1 >= v2 ? a : b"""
        if not isinstance(v1, Ref) and not isinstance(v2, Ref):
            return a if float(v1) >= float(v2) else b
        return self.node("ND_ifgreatereq_float", "float", value1=("float", v1), value2=("float", v2),
                         in1=("float", a), in2=("float", b))

    def lerp(self, a, b, t):
        if not isinstance(t, Ref) and float(t) == 1:
            return b
        return self.add(a, self.mul(self.sub(b, a), t))

    # vectors and colours
    def vec(self, kind, xyz):
        """A float3 / color3 from three floats or refs."""
        if not any(isinstance(v, Ref) for v in xyz):
            return tuple(float(v) for v in xyz)
        suffix = "vector3" if kind == "float3" else "color3"
        return self.node("ND_combine3_" + suffix, kind, in1=("float", xyz[0]), in2=("float", xyz[1]),
                         in3=("float", xyz[2]))

    def comp(self, v, i):
        if not isinstance(v, Ref):
            return float(v[i])
        suffix = {"float3": "vector3", "color3f": "color3", "color4f": "color4", "float2": "vector2"}[v.kind]
        return self.node("ND_extract_" + suffix, "float", **{"in": (v.kind, v)}, index=("int", i))

    def vop(self, op, kind, a, b):
        suffix = "vector3" if kind == "float3" else "color3"
        return self.node("ND_%s_%s" % (op, suffix), kind, in1=(kind, a), in2=(kind, b))

    def vmix(self, kind, bg, fg, t):
        if not isinstance(t, Ref) and float(t) == 1:
            return fg
        suffix = "vector3" if kind == "float3" else "color3"
        return self.node("ND_mix_" + suffix, kind, fg=(kind, fg), bg=(kind, bg), mix=("float", t))

    def scale(self, kind, v, s):
        suffix = "vector3FA" if kind == "float3" else "color3FA"
        return self.node("ND_multiply_" + suffix, kind, in1=(kind, v), in2=("float", s))

    def dot(self, a, b):
        return self.node("ND_dotproduct_vector3", "float", in1=("float3", a), in2=("float3", b))

    def normalize(self, v):
        return self.node("ND_normalize_vector3", "float3", **{"in": ("float3", v)})

    def uv(self, u, v):
        return self.node("ND_combine2_vector2", "float2", in1=("float", u), in2=("float", v))

    def image(self, path, texcoord, kind="color4f", srgb=False, clamp=False):
        ident = {"color4f": "ND_image_color4", "float": "ND_image_float"}[kind]
        address = clamp if isinstance(clamp, str) else "clamp" if clamp else "periodic"
        return self.node(ident, kind, file=("asset", path, "srgb_texture" if srgb else "raw"),
                         texcoord=("float2", texcoord), uaddressmode=("string", address),
                         vaddressmode=("string", address), filtertype=("string", "linear"))

    def rgb(self, c4):
        return self.node("ND_convert_color4_color3", "color3f", **{"in": ("color4f", c4)})


# ------------------------------------------------------------------ shading
class Scene:
    def __init__(self, g, world, normal):
        self.g, self.P, self.N = g, world, normal
        self.px, self.py, self.pz = (g.comp(world, i) for i in range(3))

    def affine(self, row):
        """row . (x, y, z, 1) on the game-space position."""
        g = self.g
        return g.add(g.add(g.add(g.mul(self.px, row[0]), g.mul(self.py, row[1])), g.mul(self.pz, row[2])), row[3])

    def height_blend(self, w, h, c, e, with_top=True):
        """The shader's height-blend weight (with_top adds max(., sat(100 (w - 0.99))))."""
        g = self.g
        x = g.sat(g.add(g.mul(w, 0.998), 0.001))
        ix = g.sub(1.0, x)
        lo = g.sat(g.sub(ix, g.mul(c, g.pow(x, e))))
        hi = g.sat(g.add(ix, g.mul(c, g.pow(ix, e))))
        shaped = g.sat(g.div(g.sub(h, lo), g.sub(hi, lo)))
        if with_top:
            shaped = g.max(shaped, g.sat(g.mul(g.sub(w, 0.99), 100.0)))
        return shaped

    def tangent_normal(self, tex, strength):
        """Normal-map xy and the variance term from a sampled texture."""
        g = self.g
        t = [g.comp(tex, i) for i in range(3)]
        xy = [g.sub(g.mul(g.add(0.5, g.mul(g.sub(t[i], 0.5), strength)), 1.992188), 1.0) for i in range(2)]
        z = g.mul(t[2], strength)
        var = g.min(g.mul(g.mul(z, z), 1 / 3), 1.0)
        return xy, var

    def gloss(self, value, var):
        g = self.g
        gl = g.max(g.sat(g.mul(value, 1 / 17)), 0.01)
        return g.sat(g.mul(g.log2(g.add(g.exp2(g.mul(gl, -17.0)), var)), -1 / 17))


def material_images(package):
    """{material: {engine semantic: png}} as the G-buffer replay binds them: raw PNGs for normal and detail maps."""
    doc = json.loads((package / "capture" / "terraingfx.json").read_text())
    table = {}
    for m in doc["materials"]:
        row = table.setdefault(m["name"], {})
        for b in m.get("bindings") or []:
            semantic = b.get("engine_semantic")
            if not b.get("png_file") or semantic in row:
                continue
            raw = semantic in ("normalMap", "detailMap")
            if raw and not b.get("raw_png_file") and b.get("export", {}).get("patch"):
                raise ValueError(f"{m['name']} {semantic}: only a patched export exists; recapture with probe v47")
            row[semantic] = package / b["raw_png_file" if raw and b.get("raw_png_file") else "png_file"]
    return table


def rel(path, base):
    return Path(os.path.relpath(path, base)).as_posix()


def build_material(package, out_dir, s, layers, decals, decal_scene, sector_dir):
    g = Graph()
    world = g.node("ND_position_vector3", "float3", space=("string", "object"))
    normal = g.node("ND_normal_vector3", "float3", space=("string", "world"))
    sc = Scene(g, world, normal)
    ox, oy = s["world_xy_origin"]
    ups = s["units_per_sample"]
    lw = s["layer_weights"]
    width, height = lw["width"], lw["height"]
    grid_uv = g.uv(g.div(g.add(g.div(g.sub(sc.px, ox), ups), 0.5), width),
                   g.sub(1.0, g.div(g.add(g.div(g.sub(sc.py, oy), ups), 0.5), height)))
    base = lw.get("array_slice_base", 0)
    (out_dir / sector_dir / "weights").mkdir(parents=True, exist_ok=True)

    material_table = material_images(package)
    color = normal_acc = gloss_acc = None
    drawn = 0.0
    report = []
    for L in layers:
        r = L["runtime"]
        flags = int(r["flags"], 16)
        if flags & 0x10:
            raise NotImplementedError(f"layer {L['slot']}: metal (0x10) is not in the USD material yet")
        ws = r["weight_slice"]
        if ws == ALWAYS_ZERO:
            continue
        if ws == ALWAYS_ONE:
            w = 1.0
        else:
            k = ws - base
            path = out_dir / sector_dir / "weights" / ("slot_%02d.png" % L["slot"])
            if not path.is_file():                     # one file per sector, shared by its chunks
                texels = load_weights(package, s, k)
                Image.fromarray(np.round(texels * 65535).astype(np.uint16)).save(path)
            w = g.image(rel(path, out_dir), grid_uv, "float", clamp=True)
        images = material_table[L["material"]]
        rows = r["uv_rows"]
        u, v = sc.affine(rows[0:4]), sc.affine(rows[4:8])

        def layer_uv(su=1.0, sv=1.0):
            return g.uv(g.mul(u, su), g.sub(1.0, g.mul(v, sv)))

        uv = layer_uv()
        active = 1.0 if not isinstance(w, Ref) else g.ifgt(w, 0.0, 1.0, 0.0)
        first = drawn == 0.0
        if first and not isinstance(active, Ref):
            wp = 1.0                                   # the first drawn layer is drawn at 1
        else:
            wp = w
            if flags & 0x4:
                su, sv = r["reveal_uv_scale"]
                h = g.comp(g.image(rel(images["revealMap"], out_dir), layer_uv(su, sv)), 0)
                wp = g.mul(sc.height_blend(w, h, r["blend_contrast"], r["blend_exponent"]), active)
            if isinstance(drawn, Ref) or drawn == 0.0:
                wp = g.max(wp, g.mul(active, g.sub(1.0, drawn)))
        drawn = g.max(drawn, active) if isinstance(active, Ref) or isinstance(drawn, Ref) else max(drawn, active)

        tint = tuple(r["tint_rgb"])
        if flags & 0x1:
            albedo = g.image(rel(images["colorMap"], out_dir), uv, srgb=True)
            rgb = g.rgb(albedo)
            a = 1.0 if flags & 0x4 else g.comp(albedo, 3)
            if flags & 0x300:
                top, bottom = (rgb, tint) if flags & 0x200 else (tint, rgb)
                one = (1.0, 1.0, 1.0)
                if isinstance(top, Ref):
                    two_top = g.scale("color3f", top, 2.0)
                    inv = g.vop("subtract", "color3f", one, two_top)
                else:
                    two_top = tuple(2 * t for t in top)
                    inv = tuple(1 - 2 * t for t in top)
                soft = g.vop("add", "color3f", g.vop("multiply", "color3f", inv, g.vop("multiply", "color3f", bottom, bottom)),
                             g.vop("multiply", "color3f", two_top, bottom))
                layer_color = g.vmix("color3f", rgb, soft, a)
            else:
                factor = g.vec("color3f", [g.add(1.0, g.mul(tc - 1.0, a)) for tc in tint])
                layer_color = g.vop("multiply", "color3f", rgb, factor)
            color = layer_color if color is None else g.vmix("color3f", color, layer_color, wp)
        else:
            if color is None:
                color = tuple(0.05 * t for t in tint)
            else:
                color = g.vmix("color3f", color, g.vop("multiply", "color3f", color, tint), wp)

        if flags & 0x2:
            nstr = r["normal_strength"]
            tex = g.image(rel(images["normalMap"], out_dir), uv)
            (nx, ny), var = sc.tangent_normal(tex, nstr)
            if flags & 0x80:
                du, dv = r["detail_uv_scale"]
                dtex = g.image(rel(images["detailMap"], out_dir), layer_uv(du, dv))
                (dx, dy), dvar = sc.tangent_normal(dtex, nstr)
                dstr = r["detail_strength"]
                nx, ny = g.add(g.mul(dx, dstr), nx), g.add(g.mul(dy, dstr), ny)
                nz = g.sub(1.0, g.mul(g.add(g.mul(nx, nx), g.mul(ny, ny)), 0.6))
                var = g.add(g.mul(dvar, dstr), var)
                n = g.normalize(g.vec("float3", [nx, ny, nz]))
                nx, ny, nz = (g.comp(n, i) for i in range(3))
            else:
                nz = g.sqrt(g.max(g.sub(1.0, g.add(g.mul(nx, nx), g.mul(ny, ny))), 0.0))
            frame = []
            for row in (rows[0:3], rows[4:7]):
                t = g.vop("subtract", "float3", tuple(row), g.scale("float3", normal, g.dot(tuple(row), normal)))
                frame.append(g.normalize(t))
            n = g.vop("add", "float3", g.vop("add", "float3", g.scale("float3", frame[0], nx), g.scale("float3", frame[1], ny)),
                      g.scale("float3", normal, nz))
            n = g.normalize(n)
            lo, hi = r["gloss_range"]
            gmask = g.comp(g.image(rel(images["glossMap"], out_dir), uv), 0) if flags & 0x8 else 1.0
            gl = sc.gloss(g.add(lo, g.mul(gmask, hi - lo)), var)
            normal_acc = n if normal_acc is None else g.vmix("float3", normal_acc, n, wp)
            gloss_acc = gl if gloss_acc is None else g.lerp(gloss_acc, gl, wp)
        elif normal_acc is None:
            normal_acc, gloss_acc = normal, 1.0
        report.append({"slot": L["slot"], "material": L["material"], "flags": r["flags"],
                       "weight": "constant 1" if w == 1.0 else "sector_weights"})

    # ---------------------------------------------------------------- decals
    # Each decal's own pixel shader, translated instruction by instruction onto
    # the G-buffer as the terrain wrote it (bo4_dxbc_graph).
    gb = GBufferState(g, [g.comp(color, i) for i in range(3)],
                      [g.comp(g.normalize(normal_acc), i) for i in range(3)], gloss_acc)
    translator = DecalTranslator(g, sc, decal_scene, lambda png: rel(package / png, out_dir))
    decal_report = []
    for d in decals:
        m = decal_scene.materials[d["material"]]
        row = {"index": d["index"], "material": d["material_name"], "shader": m["pixel_shader"]["sha1_16"],
               "priority": d["priority"]}
        try:
            # A failed draw leaves gb as it was; its partial nodes are unreachable.
            alive = translator.draw(d, gb)
            row["alive"] = alive.name if isinstance(alive, Ref) else alive
        except (NotImplementedError, ValueError) as e:
            row["untranslated"] = str(e)
            print(f"decal {d['index']} ({d['material_name']}) not drawn: {e}", file=sys.stderr)
        decal_report.append(row)
    albedo, n, gloss = gb.surface()
    color = g.vec("color3f", albedo)
    final_normal = g.normalize(g.vec("float3", n))
    rough = g.sqrt(g.sqrt(g.div(2.0, g.add(g.exp2(g.mul(gloss, 17.0)), 2.0))))
    return g, {"base_color": color, "specular_roughness": rough, "normal": final_normal}, report, decal_report


# ------------------------------------------------------------------ usda
def fmt(values, per):
    flat = np.asarray(values, np.float64).reshape(-1, per)
    if per == 1:
        return "[" + ", ".join("%.7g" % v for v in flat[:, 0]) + "]"
    return "[" + ", ".join("(" + ", ".join("%.7g" % x for x in row) + ")" for row in flat) + "]"


def write_usda(path, name, geometry, g, outputs):
    mat = "/World/Looks/%s" % name
    graph = mat + "/graph"
    lines = ['#usda 1.0', '(', '    defaultPrim = "World"', '    metersPerUnit = 0.0254', '    upAxis = "Z"',
             '    doc = "BO4 terrain, source data with a live MaterialX material (build_bo4_terrain_usd.py)"', ')', '',
             'def Xform "World"', '{', '    def Scope "Looks"', '    {', '        def Material "%s"' % name, '        {',
             '            token outputs:mtlx:surface.connect = <%s/surface.outputs:out>' % mat, '',
             '            def Shader "surface"', '            {',
             '                uniform token info:id = "ND_standard_surface_surfaceshader"',
             '                float inputs:base = 1', '                float inputs:specular = 1',
             '                float inputs:specular_IOR = 1.5']
    kinds = {"base_color": "color3f", "specular_roughness": "float", "normal": "float3"}
    for key, value in outputs.items():
        kind = "vector3f" if kinds[key] == "float3" else kinds[key]
        if isinstance(value, Ref):
            lines.append('                %s inputs:%s.connect = <%s.outputs:%s>' % (kind, key, graph, key))
        else:
            lines.append('                %s inputs:%s = %s' % (kind, key, usd_value(kinds[key], value)))
    lines += ['                token outputs:out', '            }', '', '            def NodeGraph "graph"', '            {']
    for key, value in outputs.items():
        if isinstance(value, Ref):
            kind = "vector3f" if kinds[key] == "float3" else kinds[key]
            lines.append('                %s outputs:%s.connect = <%s/%s.outputs:out>' % (kind, key, graph, value.name))
    for node_name, ident, out_kind, inputs in g.reachable(list(outputs.values())):
        lines += ['', '                def Shader "%s"' % node_name, '                {',
                  '                    uniform token info:id = "%s"' % ident]
        for key, spec in inputs.items():
            kind, value = spec[0], spec[1]
            usd_kind = {"float3": "vector3f", "float2": "float2"}.get(kind, kind)
            if isinstance(value, Ref):
                src_kind = {"float3": "vector3f"}.get(value.kind, value.kind)
                lines.append('                    %s inputs:%s.connect = <%s/%s.outputs:out>' % (src_kind, key, graph, value.name))
            else:
                meta = ' (\n                        colorSpace = "%s"\n                    )' % spec[2] if len(spec) > 2 else ""
                lines.append('                    %s inputs:%s = %s%s' % (usd_kind, key, usd_value(kind, value), meta))
        lines += ['                    %s outputs:out' % {"float3": "vector3f"}.get(out_kind, out_kind), '                }']
    lines += ['            }', '        }', '    }', '']
    pos, faces = geometry["positions"], geometry["faces"]
    lines += ['    def Mesh "Terrain" (', '        prepend apiSchemas = ["MaterialBindingAPI"]', '    )', '    {',
              '        uniform token subdivisionScheme = "none"',
              '        rel material:binding = <%s>' % mat,
              '        int[] faceVertexCounts = [%s]' % ", ".join(["3"] * len(faces)),
              '        int[] faceVertexIndices = [%s]' % ", ".join(str(int(i)) for i in faces.ravel()),
              '        point3f[] points = %s' % fmt(pos, 3),
              '        normal3f[] normals = %s (' % fmt(geometry["normals"], 3), '            interpolation = "vertex"', '        )',
              '        float3[] extent = [%s, %s]' % (tuple(map(float, pos.min(0))), tuple(map(float, pos.max(0)))),
              '    }', '}', '']
    path.write_text("\n".join(lines), encoding="utf-8")


def terrain_mesh(s, heights, solid, box):
    """The native height grid over box, holes dropped (as the CAST builder's mesh, in game inches)."""
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
    cj, ci = np.nonzero(solid[j0:j1, i0:i1])
    a = cj * cols + ci
    faces = np.stack([np.stack([a, a + 1, a + cols + 1], -1), np.stack([a, a + cols + 1, a + cols], -1)], 1).reshape(-1, 3)
    keep = np.zeros(rows * cols, bool)
    keep[faces.ravel()] = True
    faces = (np.cumsum(keep) - 1)[faces]
    return {"positions": np.stack([x, y, z], -1).reshape(-1, 3)[keep], "normals": normals.reshape(-1, 3)[keep],
            "faces": faces}


def touches(decal, geometry):
    """Whether any triangle of the mesh may enter the decal's box (|local| <= 1).

    Conservative: a triangle is kept when the box of its corners' local
    coordinates overlaps the unit box. A decal no triangle enters is discarded
    by its shader on every pixel of this mesh, so leaving it out is exact.
    """
    local = world_to_local(decal, geometry["positions"].astype(np.float64))
    tri = local[geometry["faces"]]
    return bool(((tri.min(1) <= 1) & (tri.max(1) >= -1)).all(-1).any())


def select_decals(decal_scene, box, z0, z1, geometry=None):
    """The visible decals whose boxes reach a world box and height range (and the mesh, if given), in draw order."""
    decals = []
    for d in decal_scene.decals:
        lo, hi = footprint(d)
        if d["hidden"] or hi[0] < box[0] or lo[0] > box[2] or hi[1] < box[1] or lo[1] > box[3]:
            continue
        if hi[2] < z0 or lo[2] > z1:
            continue
        if decal_scene.materials.get(d["material"], {}).get("pixel_shader") is None:
            continue
        if geometry is not None and not touches(d, geometry):
            continue
        decals.append(d)
    return sorted(decals, key=draw_key)


def build(package, output, sector_index, box, name):
    package, output = Path(package), Path(output)
    output.mkdir(parents=True, exist_ok=True)
    rows = [json.loads(p.read_text()) for p in sorted((package / "capture" / "sectors").glob("*/sector.json"))]
    s = next(r for r in rows if r["sector"] == sector_index)
    table = records(package)
    layers = [dict(L, runtime=layer_runtime(L, table[L["material"]]))
              for L in sorted(s["layers"], key=lambda r: r["slot"])]
    heights, solid = load_grid(package, s)
    geometry = terrain_mesh(s, heights, solid, box)
    z0, z1 = float(geometry["positions"][:, 2].min()), float(geometry["positions"][:, 2].max())

    decal_scene = DecalScene(package)
    decals = select_decals(decal_scene, box, z0, z1, geometry)
    sector_dir = "sector_%d" % sector_index
    g, outputs, report, decal_report = build_material(package, output, s, layers, decals, decal_scene, sector_dir)
    usda = output / (name + ".usda")
    write_usda(usda, "TerrainSector%d" % sector_index, geometry, g, outputs)
    summary = {"usda": usda.name, "sector": sector_index, "world_box_inches": list(box),
               "vertices": int(len(geometry["positions"])), "triangles": int(len(geometry["faces"])),
               "material_nodes": len(g.nodes), "layers": report, "decals": decal_report,
               "package": rel(package, output), "far_tiling": "near camera (as the bakes)"}
    (output / (name + ".json")).write_text(json.dumps(summary, indent=1))
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("package", type=Path, help="package_bo4_terrain.py output (probe v46 or newer)")
    parser.add_argument("output", type=Path)
    parser.add_argument("--sector", type=int, required=True)
    parser.add_argument("--box", type=float, nargs=4, metavar=("X0", "Y0", "X1", "Y1"), required=True,
                        help="world box in game inches")
    parser.add_argument("--name", default="terrain")
    args = parser.parse_args()
    print(json.dumps(build(args.package, args.output, args.sector, args.box, args.name), indent=1))


if __name__ == "__main__":
    main()
