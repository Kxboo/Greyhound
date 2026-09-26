"""Load a build_bo4_terrain_usd.py stage into Blender (5.x) and optionally render it.

  blender -b -P blender_bo4_terrain_usd.py -- STAGE.usda [--render OUT.png --view top|oblique|albedo]
                                              [--samples N] [--save OUT.blend] [--osl]
                                              [--load-box X0 Y0 X1 Y1] [--chunks NAME ...]
                                              [--no-materials] [--decimate N]

A whole-map root (build_bo4_map_usd.py) is all payloads, which are loaded one
at a time; --load-box takes only the chunks whose extentsHint reaches the
world box (game inches), --chunks those named (Sector_08_Chunk_00_01, or
Sector_08_* for a sector). Each sector gets its own collection.

--no-materials skips the shader networks and loads terrain geometry only,
coloured by how heavy each chunk's material is (LIGHT, UNTESTED, HEAVY). The
whole map loads that way (6 GB), but drawing all 45.7M triangles took more
than 10 GB; --decimate 4 keeps every fourth grid line for an overview that
draws easily.

The mesh comes in as in Greyhound's CAST exports (centimetres, game axes); the
material reads the game-space position back as Position / 2.54. The material's MaterialX network is
translated node for node into Cycles/Eevee shader nodes; nothing is baked.
Only the ND_ nodes build_bo4_terrain_usd.py writes are supported, and any
other node stops the load.

Views: top and oblique frame the mesh like render_cast2.py; albedo renders
base colour only (emission, Standard view transform) top-down over the stage's
extent, one pixel per two game inches, for comparison with a baked albedo.

--save writes the file after the render setup (engine, --osl, sky, sun,
camera), with its 3D views aimed at the terrain in Solid shading, so it opens
ready to explore and render.
"""
import argparse
import fnmatch
import math
import os
import sys
import time

import bpy
import mathutils
import numpy as np
from pxr import Sdf, Usd, UsdGeom, UsdShade

CM_PER_INCH = 2.54
# --no-materials object colours: the chunk's material renders on Cycles' GPU (SVM), was not
# tried there, or comes out black there and needs --osl on the CPU.
LIGHT, UNTESTED, HEAVY = (0.45, 0.75, 0.45, 1.0), (0.95, 0.75, 0.3, 1.0), (0.85, 0.35, 0.3, 1.0)
MATH = {"add": "ADD", "subtract": "SUBTRACT", "multiply": "MULTIPLY", "divide": "DIVIDE", "max": "MAXIMUM",
        "min": "MINIMUM", "power": "POWER"}
VMATH = {"add": "ADD", "subtract": "SUBTRACT", "multiply": "MULTIPLY"}


def sock(sockets, identifier):
    return next(s for s in sockets if s.identifier == identifier)


def decimate_grid(points, tris, n):
    """Keep every n-th line of a chunk's terrain grid, and one quad per coarse cell whose fine
    cells are all solid, so holes only grow. A chunk's last line is kept too: when holes cut
    into one border, the lines still land on the other, which the neighbouring chunk shares.
    Returns the kept vertex indices and the new triangles over them, or None for a mesh that
    is not a regular grid or keeps no whole cell."""
    p0, p1, p2 = points[tris[0]]
    legs = sorted(((b - a)[:2] for a, b in ((p0, p1), (p0, p2), (p1, p2))), key=np.linalg.norm)
    step = np.linalg.norm(legs[0])
    ax = legs[0] / step
    ay = np.array([-ax[1], ax[0]])
    rel = points[:, :2] - p0[:2]
    exact = np.stack([rel @ ax, rel @ ay], 1) / step
    grid = np.round(exact).astype(np.int64)
    if np.abs(exact - grid).max() > 1e-3:
        return None
    grid -= grid.min(0)
    size = grid.max(0) + 1
    # A grid triangle's centroid floors to its cell for either diagonal.
    cells = grid[tris].sum(1) // 3
    solid = np.bincount(cells[:, 0] * size[1] + cells[:, 1], minlength=size[0] * size[1]) >= 2
    area = np.zeros(size + 1, np.int64)
    area[1:, 1:] = solid.reshape(size).cumsum(0).cumsum(1)
    lines = [np.union1d(np.arange(0, s, n), [s - 1]) for s in size]
    i0, j0 = np.meshgrid(lines[0][:-1], lines[1][:-1], indexing="ij")
    i1, j1 = np.meshgrid(lines[0][1:], lines[1][1:], indexing="ij")
    whole = area[i1, j1] - area[i0, j1] - area[i1, j0] + area[i0, j0] == (i1 - i0) * (j1 - j0)
    if not whole.any():
        return None
    vertex = np.full(size, -1, np.int64)
    vertex[grid[:, 0], grid[:, 1]] = np.arange(len(points))
    c00, c10, c11, c01 = (vertex[i[whole], j[whole]] for i, j in ((i0, j0), (i1, j0), (i1, j1), (i0, j1)))
    # (ax, ay) is right-handed, so c00 c10 c11 runs counter-clockwise seen from +Z; keep the source winding.
    e1, e2 = (p1 - p0)[:2], (p2 - p0)[:2]
    if e1[0] * e2[1] - e1[1] * e2[0] > 0:
        quads = np.stack([c00, c10, c11, c00, c11, c01], 1)
    else:
        quads = np.stack([c00, c11, c10, c00, c01, c11], 1)
    keep = np.unique(quads)
    return keep, np.searchsorted(keep, quads.ravel()).astype(np.int32)


def load_mesh(stage, prim, decimate=1):
    # USD arrays go through numpy: converting them element by element in Python took
    # 1.3 of the 1.4 seconds a 66k-vertex chunk needed.
    mesh = UsdGeom.Mesh(prim)
    points = np.asarray(mesh.GetPointsAttr().Get(), np.float64)
    counts = np.asarray(mesh.GetFaceVertexCountsAttr().Get(), np.int32)
    indices = np.asarray(mesh.GetFaceVertexIndicesAttr().Get(), np.int32)
    if (counts != 3).any():
        raise ValueError("expected a triangle mesh")
    keep = slice(None)
    coarse = decimate_grid(points, indices.reshape(-1, 3), decimate) if decimate > 1 else None
    if coarse is not None:
        keep, indices = coarse
        points, counts = points[keep], np.full(len(indices) // 3, 3, np.int32)
    # A whole-map root nests each chunk's mesh as /World/Terrain/Sector_NN/Chunk_jj_ii/Terrain.
    parts = str(prim.GetPath()).split("/")
    name = "_".join(parts[3:-1]) or prim.GetName()
    me = bpy.data.meshes.new(name)
    me.vertices.add(len(points))
    me.vertices.foreach_set("co", (points * CM_PER_INCH).astype(np.float32).ravel())
    me.loops.add(len(indices))
    me.loops.foreach_set("vertex_index", indices)
    me.polygons.add(len(counts))
    me.polygons.foreach_set("loop_start", np.arange(0, len(indices), 3, dtype=np.int32))
    me.polygons.foreach_set("loop_total", counts)
    me.update()
    me.validate()
    me.shade_smooth()
    normals = mesh.GetNormalsAttr().Get()
    if normals:
        me.normals_split_custom_set_from_vertices(np.asarray(normals, np.float32)[keep])
    api = UsdGeom.PrimvarsAPI(prim)
    for pv in api.GetPrimvars():
        values = pv.Get()
        if pv.GetInterpolation() != "vertex" or values is None:
            continue
        values = np.asarray(values, np.float32)[keep]
        if len(values) != len(points):
            continue
        attr = me.attributes.new(pv.GetPrimvarName(), "FLOAT_VECTOR", "POINT")
        attr.data.foreach_set("vector", values.ravel())
    obj = bpy.data.objects.new(name, me)
    # One collection per sector, so a whole-map file can show and hide sectors in the outliner.
    scene = bpy.context.scene
    if len(parts) > 5:
        if parts[3] not in scene.collection.children:
            scene.collection.children.link(bpy.data.collections.new(parts[3]))
        scene.collection.children[parts[3]].objects.link(obj)
    else:
        scene.collection.objects.link(obj)
    return obj


GROUP_NODES = 250          # Blender's node editing slows down faster than quadratically with tree size
IMAGES = {}                # (file, colour space) -> bpy image, across all chunks
MATERIALS = {}             # USD material name -> bpy material
SOCKET_TYPES = {"VALUE": "NodeSocketFloat", "VECTOR": "NodeSocketVector", "RGBA": "NodeSocketColor"}


class Translator:
    """Builds the material's network as a chain of node groups of about GROUP_NODES nodes each.

    A value used outside the group that made it leaves through that group's
    outputs and enters the using group through its inputs, wired in the
    material's own tree.
    """

    def __init__(self, material, stage_dir):
        self.mat = bpy.data.materials.new(material.GetPrim().GetName())
        self.mat.use_nodes = True
        self.main = self.mat.node_tree
        self.main.nodes.clear()
        self.dir = stage_dir
        self.values = {}
        self.x = 0
        self.groups = {}          # group tree name -> (group node in main, group input node, group output node)
        self.exported = {}        # socket pointer -> interface name on its group
        self.imported = {}        # (tree name, socket pointer) -> socket inside that tree
        self.tree = self.main
        self.count = 0

    @property
    def nodes(self):
        return self.tree.nodes

    @property
    def links(self):
        return self.tree.links

    def start_group(self):
        tree = bpy.data.node_groups.new("%s_%03d" % (self.mat.name, len(self.groups)), "ShaderNodeTree")
        gin, gout = tree.nodes.new("NodeGroupInput"), tree.nodes.new("NodeGroupOutput")
        node = self.main.nodes.new("ShaderNodeGroup")
        node.node_tree = tree
        node.location = (len(self.groups) * 300, 600)
        self.groups[tree.name] = (node, gin, gout)
        self.tree, self.count = tree, 0

    def local(self, value):
        """value (a socket, an image dict or a constant) as seen from the current tree."""
        if isinstance(value, dict):
            return {k: self.local(v) for k, v in value.items()}
        if not isinstance(value, bpy.types.NodeSocket) or value.id_data == self.tree:
            return value
        key = (self.tree.name, value.as_pointer())
        if key in self.imported:
            return self.imported[key]
        src_node, _, src_out = self.groups[value.id_data.name]
        name = self.exported.get(value.as_pointer())
        if name is None:
            name = "v%d" % len(self.exported)
            value.id_data.interface.new_socket(name, in_out="OUTPUT", socket_type=SOCKET_TYPES[value.type])
            value.id_data.links.new(value, src_out.inputs[name])
            self.exported[value.as_pointer()] = name
        if self.tree == self.main:
            sock = src_node.outputs[name]
        else:
            node, gin, _ = self.groups[self.tree.name]
            self.tree.interface.new_socket(name, in_out="INPUT", socket_type=SOCKET_TYPES[value.type])
            self.main.links.new(src_node.outputs[name], node.inputs[name])
            sock = gin.outputs[name]
        self.imported[key] = sock
        return sock

    def new(self, kind, **props):
        node = self.nodes.new(kind)
        for k, v in props.items():
            setattr(node, k, v)
        node.location = (self.x % 60000, -(self.x // 60000) * 400)
        self.x += 220
        return node

    def feed(self, socket, value):
        value = self.local(value)
        if isinstance(value, bpy.types.NodeSocket):
            self.links.new(value, socket)
        elif isinstance(value, dict):
            self.links.new(value["color"], socket)
        elif isinstance(value, (tuple, list)):
            v = list(value) + [0.0] * (len(socket.default_value) - len(value))
            socket.default_value = v[:len(socket.default_value)]
        else:
            socket.default_value = float(value)

    def input(self, shader, name):
        inp = shader.GetInput(name)
        if inp is None:
            return None
        if inp.HasConnectedSource():
            src = inp.GetConnectedSources()[0][0]
            return self.local(self.values[src.source.GetPath()])
        v = inp.Get()
        if hasattr(v, "resolvedPath"):
            return v.resolvedPath or os.path.join(self.dir, v.path)
        if hasattr(v, "__len__") and not isinstance(v, str):
            return tuple(float(c) for c in v)
        return v

    def image(self, shader, ident):
        path = self.input(shader, "file")
        cs = shader.GetInput("file").GetAttr().GetColorSpace() or "raw"
        colorspace = "sRGB" if cs == "srgb_texture" else "Non-Color"
        # One datablock per file and colour space, shared by every chunk: a file read both
        # ways would otherwise take the colour space of whichever chunk loaded it last.
        img = IMAGES.get((path, colorspace))
        if img is None:
            img = IMAGES[path, colorspace] = bpy.data.images.load(path, check_existing=False)
            img.colorspace_settings.name = colorspace
            img.alpha_mode = "CHANNEL_PACKED"
        tex = self.new("ShaderNodeTexImage", image=img, interpolation="Linear",
                       extension={"clamp": "EXTEND", "mirror": "MIRROR"}.get(self.input(shader, "uaddressmode"), "REPEAT"))
        self.feed(tex.inputs["Vector"], self.input(shader, "texcoord"))
        if ident == "ND_image_float":
            sep = self.new("ShaderNodeSeparateColor")
            self.links.new(tex.outputs["Color"], sep.inputs[0])
            return sep.outputs[0]
        return {"color": tex.outputs["Color"], "alpha": tex.outputs["Alpha"]}

    def translate(self, prim):
        shader = UsdShade.Shader(prim)
        ident = shader.GetIdAttr().Get()
        I = lambda name: self.input(shader, name)
        parts = ident[3:].split("_")
        op, kind = parts[0], "_".join(parts[1:])
        if ident == "ND_geompropvalue_vector3":
            return self.new("ShaderNodeAttribute", attribute_type="GEOMETRY", attribute_name=I("geomprop")).outputs["Vector"]
        if ident == "ND_position_vector3":
            node = self.new("ShaderNodeVectorMath", operation="SCALE")
            self.links.new(self.new("ShaderNodeNewGeometry").outputs["Position"], node.inputs[0])
            node.inputs["Scale"].default_value = 1 / CM_PER_INCH
            return node.outputs["Vector"]
        if ident == "ND_normal_vector3":
            return self.new("ShaderNodeNewGeometry").outputs["Normal"]
        if ident in ("ND_image_color4", "ND_image_float"):
            return self.image(shader, ident)
        if ident == "ND_convert_color4_color3":
            return I("in")["color"]
        if ident == "ND_extract_color4":
            src, index = I("in"), int(I("index"))
            if index == 3:
                return src["alpha"]
            sep = self.new("ShaderNodeSeparateColor")
            self.feed(sep.inputs[0], src)
            return sep.outputs[index]
        if ident in ("ND_extract_vector3", "ND_extract_color3", "ND_extract_vector2"):
            sep = self.new("ShaderNodeSeparateXYZ")
            self.feed(sep.inputs[0], I("in"))
            return sep.outputs[int(I("index"))]
        if op in ("combine2", "combine3"):
            node = self.new("ShaderNodeCombineXYZ")
            for k in range(3 if op == "combine3" else 2):
                self.feed(node.inputs[k], I("in%d" % (k + 1)))
            return node.outputs[0]
        if kind == "float" and op in MATH:
            node = self.new("ShaderNodeMath", operation=MATH[op])
            self.feed(node.inputs[0], I("in1"))
            self.feed(node.inputs[1], I("in2"))
            return node.outputs[0]
        if ident == "ND_clamp_float":
            node = self.new("ShaderNodeClamp")
            self.feed(node.inputs["Value"], I("in"))
            self.feed(node.inputs["Min"], I("low"))
            self.feed(node.inputs["Max"], I("high"))
            return node.outputs[0]
        if kind == "float" and op in ("sqrt", "absval", "ln", "exp"):
            node = self.new("ShaderNodeMath", operation={"sqrt": "SQRT", "absval": "ABSOLUTE", "ln": "LOGARITHM",
                                                        "exp": "EXPONENT"}[op])
            self.feed(node.inputs[0], I("in"))
            if op == "ln":
                node.inputs[1].default_value = math.e
            return node.outputs[0]
        if ident in ("ND_ifgreater_float", "ND_ifgreatereq_float"):
            # v1 > v2 ? in1 : in2; v1 >= v2 is not (v1 < v2), so its inputs swap.
            ge = ident == "ND_ifgreatereq_float"
            gt = self.new("ShaderNodeMath", operation="LESS_THAN" if ge else "GREATER_THAN")
            self.feed(gt.inputs[0], I("value1"))
            self.feed(gt.inputs[1], I("value2"))
            mix = self.new("ShaderNodeMix", data_type="FLOAT", clamp_factor=False)
            self.links.new(gt.outputs[0], sock(mix.inputs, "Factor_Float"))
            self.feed(sock(mix.inputs, "A_Float"), I("in1" if ge else "in2"))
            self.feed(sock(mix.inputs, "B_Float"), I("in2" if ge else "in1"))
            return sock(mix.outputs, "Result_Float")
        if kind in ("vector3", "color3") and op in VMATH:
            node = self.new("ShaderNodeVectorMath", operation=VMATH[op])
            self.feed(node.inputs[0], I("in1"))
            self.feed(node.inputs[1], I("in2"))
            return node.outputs["Vector"]
        if ident in ("ND_multiply_vector3FA", "ND_multiply_color3FA"):
            node = self.new("ShaderNodeVectorMath", operation="SCALE")
            self.feed(node.inputs[0], I("in1"))
            self.feed(node.inputs["Scale"], I("in2"))
            return node.outputs["Vector"]
        if ident == "ND_dotproduct_vector3":
            node = self.new("ShaderNodeVectorMath", operation="DOT_PRODUCT")
            self.feed(node.inputs[0], I("in1"))
            self.feed(node.inputs[1], I("in2"))
            return node.outputs["Value"]
        if ident == "ND_normalize_vector3":
            node = self.new("ShaderNodeVectorMath", operation="NORMALIZE")
            self.feed(node.inputs[0], I("in"))
            return node.outputs["Vector"]
        if ident in ("ND_mix_vector3", "ND_mix_color3"):
            node = self.new("ShaderNodeMix", data_type="VECTOR", clamp_factor=False)
            self.feed(sock(node.inputs, "Factor_Float"), I("mix"))
            self.feed(sock(node.inputs, "A_Vector"), I("bg"))
            self.feed(sock(node.inputs, "B_Vector"), I("fg"))
            return sock(node.outputs, "Result_Vector")
        if ident == "ND_standard_surface_surfaceshader":
            node = self.new("ShaderNodePrincipledBSDF")
            for usd_name, socket in (("base_color", "Base Color"), ("specular_roughness", "Roughness"), ("normal", "Normal")):
                value = I(usd_name)
                if value is not None:
                    self.feed(node.inputs[socket], value)
            node["base_color_source"] = 1
            self.surface_inputs = {"base_color": I("base_color")}
            return node.outputs["BSDF"]
        raise NotImplementedError("MaterialX node %s is not translated" % ident)

    def build(self, material, albedo_only=False):
        graph_prims = []
        for prim in Usd.PrimRange(material.GetPrim()):
            if prim.IsA(UsdShade.Shader) and prim.GetName() != "surface":
                graph_prims.append(prim)
        # The exporter writes nodes in dependency order (n0, n1, ...).
        graph_prims.sort(key=lambda p: int(p.GetName()[1:]))
        for prim in graph_prims:
            if self.tree == self.main or self.count >= GROUP_NODES:
                self.start_group()
            self.values[prim.GetPath()] = self.translate(prim)
            self.count += 1
        self.tree = self.main
        # NodeGraph outputs resolve through to their node.
        for prim in Usd.PrimRange(material.GetPrim()):
            if prim.IsA(UsdShade.NodeGraph) and not prim.IsA(UsdShade.Material):
                for out in UsdShade.NodeGraph(prim).GetOutputs():
                    src = out.GetConnectedSources()[0][0]
                    self.values[out.GetAttr().GetPath()] = self.values[src.source.GetPath()]
        surface = UsdShade.Shader(material.GetPrim().GetChild("surface"))
        fixed = {}
        for inp in surface.GetInputs():
            if inp.HasConnectedSource():
                src = inp.GetConnectedSources()[0][0]
                fixed[inp.GetBaseName()] = self.values[src.source.GetPrim().GetPath().AppendProperty("outputs:" + src.sourceName)]
        out = self.new("ShaderNodeOutputMaterial")
        if albedo_only:
            em = self.new("ShaderNodeEmission")
            self.feed(em.inputs["Color"], fixed["base_color"])
            self.links.new(em.outputs[0], out.inputs["Surface"])
        else:
            bsdf = self.new("ShaderNodeBsdfPrincipled")
            for usd_name, socket in (("base_color", "Base Color"), ("specular_roughness", "Roughness"), ("normal", "Normal")):
                if usd_name in fixed:
                    self.feed(bsdf.inputs[socket], fixed[usd_name])
            bsdf.inputs["IOR"].default_value = 1.5
            self.links.new(bsdf.outputs[0], out.inputs["Surface"])
        return self.mat


def main():
    argv = sys.argv[sys.argv.index("--") + 1:]
    ap = argparse.ArgumentParser()
    ap.add_argument("stage")
    ap.add_argument("--render")
    ap.add_argument("--view", default="oblique", choices=("top", "oblique", "albedo", "close"))
    ap.add_argument("--target", type=float, nargs=3, metavar=("X", "Y", "DIST"),
                    help="close view: aim at world (X, Y) in game inches from DIST inches, pitched 35 degrees down")
    ap.add_argument("--yaw", type=float, default=0.0)
    ap.add_argument("--samples", type=int, default=64)
    ap.add_argument("--save")
    ap.add_argument("--osl", action="store_true",
                    help="render with Cycles' OSL shading on the CPU: materials with decals exceed the GPU "
                         "(SVM) stack of 255 floats")
    ap.add_argument("--load-box", type=float, nargs=4, metavar=("X0", "Y0", "X1", "Y1"),
                    help="load only the payloads whose extentsHint reaches this world box (game inches)")
    ap.add_argument("--no-materials", action="store_true",
                    help="terrain geometry only, without the shader networks: light enough to load the whole map")
    ap.add_argument("--decimate", type=int, default=1, metavar="N",
                    help="keep every Nth line of each chunk's terrain grid (2, 4, 8, ...): the whole map at "
                         "full resolution (45.7M triangles) is too much to draw on a 16 GB machine")
    ap.add_argument("--chunks", nargs="+", metavar="NAME",
                    help="load only these chunks, named as the objects are (Sector_08_Chunk_00_01); "
                         "wildcards work (Sector_08_*)")
    args = ap.parse_args(argv)

    bpy.ops.wm.read_factory_settings(use_empty=True)
    stage = Usd.Stage.Open(args.stage, Usd.Stage.LoadNone)
    # Traverse() skips unloaded prims, which with LoadNone is every payload; walk them all.
    payloads = [p for p in stage.TraverseAll() if p.HasAuthoredPayloads()]
    if args.chunks:
        payloads = [p for p in payloads
                    if any(fnmatch.fnmatch("_".join(str(p.GetPath()).split("/")[3:]), c) for c in args.chunks)]
    if args.load_box:
        x0, y0, x1, y1 = args.load_box
        hints = [p.GetAttribute("extentsHint").Get() for p in payloads]
        payloads = [p for p, hint in zip(payloads, hints)
                    if hint and hint[0][0] <= x1 and hint[1][0] >= x0 and hint[0][1] <= y1 and hint[1][1] >= y0]
    stage_dir = os.path.dirname(os.path.abspath(args.stage))
    # The whole-map root's 388 payloads hold 4.9M shader prims between them, so each is
    # loaded alone and unloaded once Blender has its mesh and material. A stage without
    # payloads is read as it is.
    for path in [p.GetPath() for p in payloads] or [Sdf.Path.absoluteRootPath]:
        if path != Sdf.Path.absoluteRootPath:
            stage.Load(path)
            print("LOAD", path, flush=True)
        for prim in Usd.PrimRange(stage.GetPrimAtPath(path)):
            if not prim.IsA(UsdGeom.Mesh):
                continue
            start = time.perf_counter()
            obj = load_mesh(stage, prim, args.decimate)
            binding = UsdShade.MaterialBindingAPI(prim).ComputeBoundMaterial()[0]
            nodes = 0
            if binding and args.no_materials:
                # Colour the chunk by the size of the network it would build. Cycles on the GPU
                # rendered chunks up to 5.5k nodes; from 6.7k they came out black and need --osl.
                shaders = sum(p.IsA(UsdShade.Shader) for p in Usd.PrimRange(binding.GetPrim()))
                obj["material_nodes"] = nodes = shaders
                obj.color = LIGHT if shaders <= 5500 else HEAVY if shaders >= 6700 else UNTESTED
            elif binding:
                # Chunks whose materials share a name share one Blender material:
                # build_bo4_map_usd.py --no-decals gives each sector one, Terrain_sNN.
                name = binding.GetPrim().GetName()
                if name not in MATERIALS:
                    translator = Translator(binding, stage_dir)
                    MATERIALS[name] = translator.build(binding, albedo_only=args.view == "albedo")
                    nodes = sum(len(node.node_tree.nodes) for node, _, _ in translator.groups.values())
                obj.data.materials.append(MATERIALS[name])
            print("LOADED", obj.name, len(obj.data.vertices), "vertices,", nodes, "shader nodes, %.1f s"
                  % (time.perf_counter() - start), flush=True)
        if path != Sdf.Path.absoluteRootPath:
            stage.Unload(path)
    corners = [o.matrix_world @ mathutils.Vector(c) for o in bpy.context.scene.objects if o.type == "MESH"
               for c in o.bound_box]
    if not corners:
        sys.exit("no terrain mesh in %s matching --chunks/--load-box" % args.stage)
    lo = mathutils.Vector([min(v[i] for v in corners) for i in range(3)])
    hi = mathutils.Vector([max(v[i] for v in corners) for i in range(3)])
    if args.render or args.save:
        setup_scene(args, lo, hi)
    if args.save:
        frame_viewports(lo, hi, "OBJECT" if args.no_materials else "MATERIAL")
        bpy.ops.wm.save_as_mainfile(filepath=args.save)
        print("SAVED", args.save, flush=True)
    if args.render:
        bpy.context.scene.render.filepath = args.render
        bpy.ops.render.render(write_still=True)
        print("RENDERED", args.render, flush=True)


def frame_viewports(lo, hi, color_type):
    """Aim the 3D views of a --save file at the terrain and keep them out of Material Preview.

    A unit here is a centimetre, so Blender's default view range (1000 units) would end
    10 m from the eye. Material Preview (the Shading workspace's default) compiles every
    material for Eevee, which a decal-heavy terrain material can keep busy for minutes.
    A --no-materials file shows the chunks in their object colours (see LIGHT).
    """
    center, size = (lo + hi) / 2, max(hi.x - lo.x, hi.y - lo.y)
    for screen in bpy.data.screens:
        for area in screen.areas:
            for space in area.spaces:
                if space.type != "VIEW_3D":
                    continue
                space.clip_start, space.clip_end = min(size / 2000, 50.0), size * 10
                space.shading.type = "SOLID"
                space.shading.color_type = color_type
                view = space.region_3d
                view.view_perspective = "PERSP"
                view.view_location = center
                view.view_distance = size
                view.view_rotation = mathutils.Euler((math.radians(55), 0, math.radians(-20))).to_quaternion()


def setup_scene(args, lo, hi):
    """Cycles settings, sky, sun and camera: what --render needs and what a --save file opens with."""
    scene = bpy.context.scene
    scene.unit_settings.scale_length = 0.01     # one unit is a centimetre, so lengths read in real metres
    scene.render.engine = "CYCLES"
    prefs = bpy.context.preferences.addons["cycles"].preferences
    scene.cycles.shading_system = args.osl
    for backend in () if args.osl else ("OPTIX", "CUDA", "HIP", "ONEAPI"):
        try:
            prefs.compute_device_type = backend
            prefs.get_devices()
            if any(d.type == backend for d in prefs.devices):
                for d in prefs.devices:
                    d.use = d.type == backend
                scene.cycles.device = "GPU"
                print("DEVICE", backend)
                break
        except TypeError:
            continue
    scene.cycles.samples = args.samples
    scene.cycles.use_denoising = False
    center, size = (lo + hi) / 2, max(hi.x - lo.x, hi.y - lo.y)
    scene.render.resolution_x, scene.render.resolution_y = 1600, 1000
    cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
    scene.collection.objects.link(cam)
    scene.camera = cam
    if args.view == "albedo":
        scene.view_settings.view_transform = "Standard"
        scene.cycles.max_bounces = 0
        scene.cycles.filter_width = 1.0
        cam.data.type = "ORTHO"
        cam.data.ortho_scale = size
        cam.location = (center.x, center.y, hi.z + size)
        scene.render.resolution_x = scene.render.resolution_y = int(round(size / CM_PER_INCH / 2))
        cam.data.clip_end = size * 10
    else:
        scene.world = bpy.data.worlds.new("w")
        scene.world.use_nodes = True
        bg = scene.world.node_tree.nodes["Background"]
        bg.inputs[0].default_value = (0.55, 0.62, 0.72, 1)
        bg.inputs[1].default_value = 0.6
        sun = bpy.data.objects.new("sun", bpy.data.lights.new("sun", "SUN"))
        sun.data.energy = 3.5
        sun.rotation_euler = (math.radians(50), 0, math.radians(35))
        scene.collection.objects.link(sun)
        if args.view == "top":
            cam.data.type = "ORTHO"
            cam.data.ortho_scale = size
            cam.location = (center.x, center.y, hi.z + size)
            scene.render.resolution_y = 1600
            cam.data.clip_end = size * 10
        elif args.view == "close":
            tx, ty, dist = (v * CM_PER_INCH for v in args.target)
            yaw = math.radians(args.yaw)
            depsgraph = bpy.context.evaluated_depsgraph_get()
            hit, loc, *_ = scene.ray_cast(depsgraph, mathutils.Vector((tx, ty, hi.z + 1000)), mathutils.Vector((0, 0, -1)))
            target = loc if hit else mathutils.Vector((tx, ty, center.z))
            pitch = math.radians(35)
            offset = mathutils.Vector((-math.sin(yaw) * math.cos(pitch), -math.cos(yaw) * math.cos(pitch), math.sin(pitch)))
            cam.location = target + offset * dist
            cam.rotation_euler = (target - cam.location).to_track_quat("-Z", "Y").to_euler()
            cam.data.lens = 35
            cam.data.clip_start, cam.data.clip_end = dist / 500, dist * 20
        else:
            cam.data.lens = 28
            cam.location = center + mathutils.Vector((-0.05 * size, -0.62 * size, 0.30 * size))
            d = (center + mathutils.Vector((0, 0.05 * size, 0))) - cam.location
            cam.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
            cam.data.clip_end = size * 10
            cam.data.clip_start = size / 2000


main()
