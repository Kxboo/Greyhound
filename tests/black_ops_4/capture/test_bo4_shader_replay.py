"""Synthetic regressions for the BO4 shader replay: emulator semantics, decal output merger and CAST build."""

import sys as _tool_sys
from pathlib import Path as _ToolPath
REPO_ROOT = next(p for p in _ToolPath(__file__).resolve().parents if (p / "build-greyhound.ps1").is_file())
TOOLS_ROOT = REPO_ROOT / "tools"
_tool_sys.path.insert(0, str(TOOLS_ROOT))
import tool_bootstrap as _tool_bootstrap
_tool_bootstrap.activate(TOOLS_ROOT / "tool_bootstrap.py")
import struct
import tempfile
import unittest
from pathlib import Path

import numpy as np

import bo4_decal_composite as composite
import build_bo4_terrain_cast as terrain_cast
from bake_cw_splines import read_cast
from bo4_dxbc_emulator import Sampler, Shader, Texture
from bo4_terrain_gbuffer import TerrainScene, decode_tetra_normal, half


class SamplerStateTests(unittest.TestCase):
    def test_decodes_filter_mip_and_address_bits(self):
        atlas = Sampler.from_state("0x2A2")        # the decal reveal atlas: linear, no mips, clamp
        self.assertEqual((atlas.address, atlas.mip, atlas.filter), ("clamp", "none", "linear"))
        for word in (0x12, 0x13, 0x14):             # linear or anisotropic, linear mips, wrap
            s = Sampler.from_state(word)
            self.assertEqual((s.address, s.mip, s.filter), ("wrap", "linear", "linear"))
        point = Sampler.from_state(0x09)
        self.assertEqual((point.mip, point.filter), ("point", "point"))

    def test_rejects_modes_outside_the_decoded_set(self):
        for word in (0x12 | 1 << 5, 0x12 | 2 << 5 | 2 << 7, 0x10):   # U != V, border/mirror, no filter
            with self.assertRaises(ValueError):
                Sampler.from_state(word)

    def test_no_mip_sampler_reads_the_top_level(self):
        top = np.zeros((4, 4, 1), np.float32)
        tex = Texture([top[None], np.ones((1, 2, 2, 1), np.float32)], address="wrap")
        u = v = np.array([0.5], np.float32)
        s = np.zeros(1, np.int64)
        lod = np.array([1.0], np.float32)
        self.assertEqual(float(tex.sample(u, v, s, lod)[0, 0]), 1.0)
        self.assertEqual(float(tex.sample(u, v, s, lod, Sampler("wrap", "none"))[0, 0]), 0.0)


class EmulatorTests(unittest.TestCase):
    def test_discarded_lanes_keep_running_as_derivative_helpers(self):
        # Lanes in column 0 discard after r1.x was left stale. A GPU keeps them
        # running, so the coarse x derivative of column 1 sees their new value.
        shader = Shader("""ps_5_0
dcl_input_ps linear v1.xy
dcl_output o0.xyzw
dcl_temps 2
mov r1.x, l(100.000000)
lt r0.x, v1.x, l(0.500000)
discard_nz r0.x
mul r1.x, v1.x, l(3.000000)
deriv_rtx_coarse r1.y, r1.x
mov o0.xyzw, r1.yyyy
ret
""")
        column = np.array([[0, 0], [1, 0], [0, 1], [1, 1]], np.float32)   # (x, y) of a 2x2 quad
        outs, alive = shader.run(4, inputs={"v1": column}, grid=(2, 2))
        self.assertEqual(alive.tolist(), [False, True, False, True])
        np.testing.assert_allclose(outs[0][alive, 0], [3.0, 3.0])

    def test_domain_shader_inputs(self):
        shader = Shader("""ds_5_0
dcl_input vDomain.xyz
dcl_input vicp[3][0].xy
dcl_output_siv o0.xyzw, position
dcl_temps 1
mul r0.xy, vDomain.xxxx, vicp[0][0].xyxx
mad r0.xy, vDomain.yyyy, vicp[1][0].xyxx, r0.xyxx
mad r0.xy, vDomain.zzzz, vicp[2][0].xyxx, r0.xyxx
mov o0.xy, r0.xyxx
mov o0.zw, l(0, 0, 0, 1.000000)
ret
""")
        corners = {f"vicp{p}_0": np.array([[p, 10 * p]], np.float32) for p in range(3)}
        outs, _ = shader.run(1, inputs={"vDomain": np.array([0.2, 0.3, 0.5, 0], np.float32), **corners})
        np.testing.assert_allclose(outs[0][0, :2], [0.3 + 1.0, 3 + 10.0], rtol=1e-6)


class OutputMergerTests(unittest.TestCase):
    ALPHA_BLEND = {"enable": True, "src": "SRC_ALPHA", "dst": "INV_SRC_ALPHA", "op": "ADD",
                   "src_alpha": "ZERO", "dst_alpha": "ONE", "op_alpha": "ADD", "write_mask": 15}

    def test_alpha_blend_keeps_destination_alpha(self):
        src = np.array([[1.0, 0.5, 0.0, 0.25]], np.float32)
        dst = np.array([[0.0, 0.5, 1.0, 0.75]], np.float32)
        np.testing.assert_allclose(composite.blend(self.ALPHA_BLEND, src, dst), [[0.25, 0.5, 0.75, 0.75]])
        np.testing.assert_allclose(composite.blend({"enable": False}, src, dst), src)

    def test_targets_store_their_formats(self):
        # RT0 is sRGB 8-bit: a round trip lands on the nearest representable linear value.
        linear = np.array([0.0, 0.2, 0.5, 1.0], np.float32)
        rt0 = composite.decode_target(0, composite.encode_target(0, np.tile(linear, (1, 1))))
        np.testing.assert_allclose(rt0[0, :3], linear[:3], atol=0.01)
        self.assertEqual(float(rt0[0, 3]), 1.0)
        # RT1 is 10:10:10:2 UNORM.
        stored = composite.encode_target(1, np.array([[0.5, 1.0, 0.0, 0.34]], np.float32))
        self.assertEqual(stored.tolist(), [[512, 1023, 0, 1]])
        np.testing.assert_allclose(composite.decode_target(1, stored), [[512 / 1023, 1, 0, 1 / 3]], rtol=1e-6)

    def test_gbuffer_write_honours_mask_and_write_mask(self):
        zeros = {rt: np.zeros((2, 2, 4), np.float32) for rt in (0, 1, 2)}
        gb = composite.GBuffer((0, 0, 2, 2), 1.0, np.zeros((2, 2)), np.ones((2, 2), bool), zeros)
        mask = np.array([[True, False], [False, False]])
        gb.write(1, slice(0, 2), slice(0, 2), np.ones((2, 2, 4), np.float32), mask, 0b0101)
        self.assertEqual(gb.stored[1][0, 0].tolist(), [1023, 0, 1023, 0])
        self.assertEqual(int(gb.stored[1][1:].sum() + gb.stored[1][0, 1].sum()), 0)


class GBufferDecodeTests(unittest.TestCase):
    def test_checkerboard_specular_round_trip(self):
        rng = np.random.default_rng(3)
        rgb = np.tile(rng.uniform(0.1, 0.9, 3), (6, 8, 1))
        y = rgb[..., 0] / 4 + rgb[..., 1] / 2 + rgb[..., 2] / 4
        co, cg = rgb[..., 0] - rgb[..., 2], rgb[..., 1] - (rgb[..., 0] + rgb[..., 2]) / 2
        rows, cols = np.mgrid[0:6, 0:8]
        chroma = np.where((rows & 1) == (cols & 1), co, cg)
        rt2 = np.stack([y, chroma * 0.5 + 0.5, np.zeros_like(y), np.zeros_like(y)], -1)
        np.testing.assert_allclose(composite.checkerboard_specular(rt2), rgb, atol=1e-6)

    def test_tetrahedral_normal_decodes_to_unit_vectors(self):
        rng = np.random.default_rng(5)
        xy = rng.uniform(0.5 - 0.588235 * 0.99, 0.5 + 0.588235 * 0.99, (64, 2))
        xy = xy[((xy - 0.5) ** 2).sum(1) / 0.588235 ** 2 <= 2]
        for face in range(4):
            rt1 = np.column_stack([xy, np.zeros(len(xy)), np.full(len(xy), face / 3)])
            np.testing.assert_allclose(np.linalg.norm(decode_tetra_normal(rt1), axis=1), 1, atol=1e-5)
        centres = decode_tetra_normal(np.array([[0.5, 0.5, 0, k / 3] for k in range(4)]))
        signs = np.array([[1, 1, 1], [1, -1, -1], [-1, 1, -1], [-1, -1, 1]])
        np.testing.assert_allclose(centres, signs / np.sqrt(3), atol=1e-5)

    def test_gloss_flag_offset(self):
        rt1 = np.zeros((1, 2, 4), np.float32)
        rt1[0, :, :2] = 0.5
        rt1[0, 0, 2] = 0.25 * composite.GLOSS_SCALE + composite.GLOSS_BIAS
        rt1[0, 1, 2] = 0.25 * composite.GLOSS_SCALE + 0.5
        gb = composite.GBuffer((0, 0, 2, 1), 1.0, np.zeros((1, 2)), np.ones((1, 2), bool),
                               {0: np.zeros((1, 2, 4), np.float32), 1: rt1, 2: np.zeros((1, 2, 4), np.float32)})
        surface = gb.surface()
        np.testing.assert_allclose(surface["gloss"][0], [0.25, 0.25], atol=2e-3)
        self.assertEqual(surface["gloss_flag"][0].tolist(), [False, True])


class DecalCameraTests(unittest.TestCase):
    def test_reconstruction_lands_on_each_texel(self):
        gb = composite.GBuffer((100, 200, 132, 216), 2.0, np.zeros((32, 64)), np.ones((32, 64), bool),
                               {rt: np.zeros((32, 64, 4), np.float32) for rt in (0, 1, 2)})
        rows, cols = slice(4, 20), slice(10, 42)
        x, y = gb.world(rows, cols)
        z = 50 + 10 * np.sin(x / 7) * np.cos(y / 5)
        material = type("M", (), {"atlas_register": None})()
        v2, depth, cb2 = composite.DecalScene.camera(None, gb, rows, cols, x, y, z, material)
        # The decal shaders' reconstruction (see DecalScene.camera).
        ndc = (v2 - cb2[92, :2]) * cb2[61, 2:] * (2, -2) + (-1, 1)
        w = 1 / (depth.astype(np.float64) * composite.DEPTH_SCALE)
        view = np.stack([ndc[:, 0] * cb2[12, 0] * w, ndc[:, 1] * cb2[13, 1] * w, w], 1)
        world = view @ cb2[16:19, :3].astype(np.float64) + cb2[24, :3]
        np.testing.assert_allclose(world, np.stack([x.ravel(), y.ravel(), z.ravel()], 1), atol=2e-3)


class DecalOrderTests(unittest.TestCase):
    def decal(self, index, priority, material, key="priority"):
        return {"index": index, key: priority, "material": material, "hidden": 0, "axes": np.eye(3).tolist(),
                "origin": [0.0, 0.0, 0.0], "half_extents": [8.0, 8.0, 8.0]}

    def test_priority_descending_then_material_then_asset_order(self):
        scene = object.__new__(composite.DecalScene)
        scene.decals = [self.decal(0, 1, "0x300"), self.decal(1, 6, "0x200"), self.decal(2, 1, "0x100"),
                        self.decal(3, 6, "0x100"), self.decal(4, 1, "0x100"), self.decal(5, 4, "0xF0", "unknown_c8")]
        scene.materials = {d["material"]: {"pixel_shader": {}} for d in scene.decals}
        gb = composite.GBuffer((-16, -16, 16, 16), 1.0, np.zeros((32, 32)), np.ones((32, 32), bool),
                               {rt: np.zeros((32, 32, 4), np.float32) for rt in (0, 1, 2)})
        self.assertEqual([d["index"] for d in scene.draws(gb)], [3, 1, 5, 2, 4, 0])


class NodeRecordTests(unittest.TestCase):
    def scene(self, masks, flags):
        scene = object.__new__(TerrainScene)
        scene.sector, scene.ups, scene.n, scene.tiles = {}, 8.0, 65, 2
        scene.tile_size = (scene.n - 1) * scene.ups / scene.tiles
        scene.origin = np.array([-100.0, 50.0])
        scene.height_bias, scene.height_range = -99.0, 8191.0
        scene.masks = np.array(masks, np.uint16)
        scene.records = [struct.pack("<13II14I", *([0] * 13), f, *([0] * 14)) for f in flags]
        scene.layers = [{"slot": k} for k in range(len(flags))]
        return scene

    def test_masks_displacement_and_uv_rows(self):
        amounts = (3.0, 6.0, 1.5)
        flags = [struct.unpack("<H", struct.pack("<e", a))[0] << 16 | 0x6F for a in amounts]
        scene = self.scene([[0b001, 0b011], [0b110, 0b100]], flags)
        data = scene.node_records()
        self.assertEqual(len(data), 4 * 124)
        for tile, mask in enumerate((0b001, 0b011, 0b110, 0b100)):
            r = data[tile * 124:(tile + 1) * 124]
            # +4 is the layer mask the pixel shader walks, +8 the domain shader's displacement mask.
            self.assertEqual(struct.unpack_from("<3I", r, 0), (8, mask, mask))
            strongest = max(a for k, a in enumerate(amounts) if mask >> k & 1)
            self.assertEqual(half(struct.unpack_from("<I", r, 108)[0] >> 16), strongest)
        # The uv rows put sample i at texel centre i: u * n - 0.5 == (x - origin) / ups.
        row0 = struct.unpack_from("<3f", data, 56)
        x = np.array([-100.0, -92.0, 0.0])
        np.testing.assert_allclose((row0[0] * x + row0[2]) * scene.n - 0.5, (x + 100) / 8, atol=1e-4)


class FakeTerrain:
    """Stands in for TerrainScene: a tilted plane, raised by a constant displacement."""

    def __init__(self):
        self.sector = {"world_xy_origin": [0.0, 0.0], "units_per_sample": 8.0, "grid_samples": 9}
        self.ups, self.n = 8.0, 9
        self.cb2 = np.zeros((34, 4), np.float32)
        self.cb2[30] = (12, 12, 9 / 12, 0)

    def surface_height(self, x, y):
        return 0.5 * np.asarray(x) - 0.25 * np.asarray(y)

    def displaced_height(self, x, y):
        return self.surface_height(x, y) + 2.0

    def bake(self, box, tpu, block=128, progress=None):
        """G-buffer values that encode each texel's world position, so tiles can be checked."""
        x0, y0, x1, y1 = box
        width, height = int(round((x1 - x0) * tpu)) // 2 * 2, int(round((y1 - y0) * tpu)) // 2 * 2
        x, y = np.meshgrid(x0 + (np.arange(width) + 0.5) / tpu, y1 - (np.arange(height) + 0.5) / tpu)
        rt = np.zeros((height, width, 4), np.float32)
        rt[..., 0], rt[..., 1] = (x % 64) / 64, (y % 64) / 64
        rt1 = np.zeros_like(rt)
        rt1[..., :2], rt1[..., 2], rt1[..., 3] = 0.5, (x % 32) / 64 + composite.GLOSS_BIAS, 0
        geo = np.zeros((height, width, 3), np.float32)
        geo[..., 2] = 1
        return {"rt0": rt, "rt1": rt1, "rt2": rt.copy(), "alive": np.ones((height, width), bool),
                "height": self.surface_height(x, y).astype(np.float32), "geo_normal": geo}


class TerrainCastTests(unittest.TestCase):
    def test_tiled_bake_matches_one_tile(self):
        terrain = FakeTerrain()
        whole, _ = composite.bake_surface(terrain, None, (0, 0, 20, 12), 2.0, tile=64)
        tiled, _ = composite.bake_surface(terrain, None, (0, 0, 20, 12), 2.0, tile=6)
        self.assertEqual(whole["albedo"].shape, (24, 40, 4))
        for key in whole:
            np.testing.assert_array_equal(tiled[key], whole[key], err_msg=key)

    def test_height_normal_is_the_plane_normal(self):
        terrain = FakeTerrain()
        normal = terrain_cast.height_normal(terrain, np.array([20.0, 33.0]), np.array([30.0, 17.0]))
        expected = np.array([-0.5, 0.25, 1]) / np.linalg.norm([-0.5, 0.25, 1])
        np.testing.assert_allclose(normal, [expected, expected], atol=1e-9)

    def test_displaced_mesh_subdivides_and_keeps_holes(self):
        terrain = FakeTerrain()
        solid = np.ones((9, 9), bool)
        solid[0, 1] = False                          # cell (i=1, j=0)
        geometry = terrain_cast.displaced_mesh(terrain, solid, (0, 0, 16, 16), 2)
        # 2 x 2 cells split twice: 16 sub-cells, 4 of them in the hole.
        self.assertEqual((geometry["cells"], geometry["hole_cells"], len(geometry["faces"])), (4, 1, 24))
        np.testing.assert_allclose(geometry["displacement"], 2.0)
        p = geometry["positions"]
        np.testing.assert_allclose(p[:, 2], terrain.surface_height(p[:, 0], p[:, 1]) + 2)
        self.assertEqual(sorted(set(p[:, 0].tolist())), [0, 4, 8, 12, 16])
        # u runs +X, v from the +Y edge.
        np.testing.assert_allclose(geometry["uv"][:, 0], p[:, 0] / 16)
        np.testing.assert_allclose(geometry["uv"][:, 1], (16 - p[:, 1]) / 16)

    def test_cast_material_binds_each_map(self):
        terrain = FakeTerrain()
        geometry = terrain_cast.displaced_mesh(terrain, np.ones((9, 9), bool), (0, 0, 8, 8), 1)
        maps = {slot: f"t_{slot}.png" for slot in terrain_cast.CAST_SLOTS}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "t.cast"
            terrain_cast.write_cast(path, "t", geometry, maps)
            model = read_cast(path.read_bytes())[0].children[0]
            material = next(c for c in model.children if c.ident == b"matl")
            files = {c.hash: c for c in material.children if c.ident == b"file"}
            for slot, name in maps.items():
                file_hash = int(material.array(slot)[0])
                self.assertEqual(files[file_hash].props["p"][2].rstrip(b"\0").decode(), name)


if __name__ == "__main__":
    unittest.main()
