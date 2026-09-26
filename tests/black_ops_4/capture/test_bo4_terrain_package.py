"""Synthetic regressions for BO4 terrain packaging: sector image pairing and BC4 weights."""

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

import build_bo4_terrain_cast as terrain_cast
import package_bo4_terrain as package
from bake_cw_splines import read_cast
import verify_bo4_terrain_package as verify


def grid(index, n, pointer, weight_hash):
    side = 32 * n + 4
    return [
        {"image": f"0x{pointer:X}", "grid_shape": "sector_square", "format": 56, "width": side,
         "height": side, "tiles_across": n, "name": f"terrain_height_maps_{index}"},
        {"image": f"0x{pointer + 1:X}", "grid_shape": "sector_half_width", "format": 42,
         "width": 4 * n + 1, "height": 8 * n + 1, "tiles_across": n, "name": f"terrain_cutout_maps_{index}",
         "dump": {"file": f"terrain_cutout_maps_{index}.bin"}},
        {"image": f"0x{pointer + 2:X}", "grid_shape": "sector_square", "format": 80, "width": side,
         "height": side, "tiles_across": n, "hash": weight_hash,
         "dump": {"file": f"terrain_map_{weight_hash}.bin"}},
    ]


class SectorPairingTests(unittest.TestCase):
    def probe(self, *grids):
        images = [image for g in grids for image in g]
        # zm_white lists every sector's triple in one sector's side arrays, twice.
        return {"sectors": [{"sector": 0, "side_arrays": []},
                            {"sector": 1, "side_arrays": [{"images": images}, {"images": images}]}]}

    def test_pairs_each_sector_by_name_across_shared_arrays(self):
        result = package.grid_images(self.probe(grid(0, 128, 0x100, "A"), grid(1, 32, 0x200, "B")))
        self.assertEqual(sorted(result), [0, 1])
        self.assertEqual(result[0]["weights"]["dump"]["file"], "terrain_map_A.bin")
        self.assertEqual(result[1]["weights"]["dump"]["file"], "terrain_map_B.bin")

    def test_rejects_mismatched_dimensions(self):
        bad = grid(0, 32, 0x100, "A")
        bad[1]["width"] += 1
        with self.assertRaises(ValueError):
            package.grid_images(self.probe(bad))

    def test_rejects_cutout_named_for_another_sector(self):
        bad = grid(0, 32, 0x100, "A")
        bad[1]["name"] = "terrain_cutout_maps_1"
        with self.assertRaises(ValueError):
            package.grid_images(self.probe(bad))


class BC4Tests(unittest.TestCase):
    def block(self, r0, r1, indices):
        bits = sum(i << (3 * k) for k, i in enumerate(indices))
        return struct.pack("<BB", r0, r1) + bits.to_bytes(6, "little")

    def test_eight_value_palette_and_texel_order(self):
        indices = list(range(8)) * 2
        raw = self.block(255, 0, indices) + self.block(0, 0, [0] * 16)
        image = verify.decode_bc4(raw, 8, 4)
        expected = np.array([255, 0] + [((8 - k) * 255) / 7 for k in range(2, 8)]) / 255
        np.testing.assert_allclose(image[0, :4], expected[:4], atol=1e-6)
        np.testing.assert_allclose(image[1, :4], expected[4:], atol=1e-6)
        self.assertEqual(image[:, 4:].max(), 0)

    def test_six_value_palette_endpoints(self):
        raw = self.block(0, 200, [6, 7] + [0] * 14)
        image = verify.decode_bc4(raw, 4, 4)
        self.assertEqual((image[0, 0], image[0, 1]), (0.0, 1.0))


class CutoutTests(unittest.TestCase):
    def test_shader_bit_address(self):
        # The terrain pixel shader tests word (i >> 3, j >> 2), bit (i & 7) + 8 (j & 3).
        words = np.zeros((3, 2), np.uint32)
        for i, j in ((0, 0), (5, 2), (9, 4), (15, 11)):
            words[j >> 2, i >> 3] |= np.uint32(1 << ((i & 7) + 8 * (j & 3)))
        bits = verify.cutout_bits(words)
        self.assertEqual(bits.shape, (12, 16))
        self.assertEqual(sorted(zip(*np.nonzero(bits.T))), [(0, 0), (5, 2), (9, 4), (15, 11)])


class RuntimeRecordTests(unittest.TestCase):
    def test_decodes_flags_blend_bytes_and_tint(self):
        words = [0] * 28
        words[0], words[5] = struct.unpack("<I", struct.pack("<f", 0.015625))[0], struct.unpack("<I", struct.pack("<f", -0.015625))[0]
        words[8], words[12], words[13], words[18] = 2, 0x3C003C00, 0x4600006F, 0x0E007F7F
        # zm_towers slot 1's tint words: 0.9375, 0.90625, 0.84375
        words[19], words[20], words[21] = 0xEE000B, 0x3B410006, 0x3AE00000
        record = package.runtime_record(struct.pack("<28I", *words), 0)
        self.assertEqual(record["weight_slice"], 2)
        self.assertTrue(record["height_blend"] and record["textured"])
        self.assertFalse(record["metal"] or record["far_tiling"] or record["soft_light_tint"])
        self.assertAlmostEqual(record["blend_contrast"], 127 / 255)
        self.assertEqual(record["tint_rgb"], [0.9375, 0.90625, 0.84375])
        self.assertEqual(record["reveal_uv_scale"], [1.0, 1.0])


class TerrainCastTests(unittest.TestCase):
    class FakeLayer:
        def __init__(self, slice_id, color, reveal=None):
            self.runtime = {"weight_slice": slice_id, "blend_contrast": 127 / 255, "blend_exponent": 127 / 255,
                            "reveal_uv_scale": [1.0, 1.0]}
            self.albedo = [np.tile(np.array(color + [1.0], np.float32), (4, 4, 1))]
            self.reveal = None if reveal is None else [np.full((4, 4, 1), reveal, np.float32)]
            self.u_row, self.v_row, self.tint = [1, 0, 0, 0], [0, 1, 0, 0], np.ones(3, np.float32)
            self.soft_light = self.soft_light_swap = False

        tinted = terrain_cast.Layer.tinted

        def uv(self, x, y):
            return x, y

        def level(self, levels, texels_per_unit, scale=1.0):
            return levels[0]

    def sector(self):
        return {"world_xy_origin": [0.0, 0.0], "units_per_sample": 1.0, "grid_samples": 3}

    def blend(self, layers, weights):
        x = np.array([[0.5]]); return terrain_cast.blend(layers, weights, self.sector(), x, x, 1.0)[0, 0]

    def test_sequential_lerp_and_first_layer_forced(self):
        base, top = self.FakeLayer(terrain_cast.ALWAYS_ONE, [1.0, 0, 0]), self.FakeLayer(0, [0, 1.0, 0])
        np.testing.assert_allclose(self.blend([base, top], [np.full((3, 3), 0.25)]), [0.75, 0.25, 0], atol=1e-6)
        # With the base always-zero, the first painted layer is drawn at full weight.
        base.runtime["weight_slice"] = terrain_cast.ALWAYS_ZERO
        np.testing.assert_allclose(self.blend([base, top], [np.full((3, 3), 0.25)]), [0, 1.0, 0], atol=1e-6)

    def test_height_blend_is_half_at_half_weight_and_half_height(self):
        base, top = self.FakeLayer(terrain_cast.ALWAYS_ONE, [0, 0, 0]), self.FakeLayer(0, [1.0, 1.0, 1.0], reveal=0.5)
        self.assertAlmostEqual(float(self.blend([base, top], [np.full((3, 3), 0.5)])[0]), 0.5, places=3)
        top.reveal = [np.full((4, 4, 1), 0.9, np.float32)]
        self.assertGreater(float(self.blend([base, top], [np.full((3, 3), 0.5)])[0]), 0.9)

    def test_soft_light_tint(self):
        layer = self.FakeLayer(terrain_cast.ALWAYS_ONE, [0.2, 0.6, 0.8])
        albedo = np.array([0.2, 0.6, 0.8], np.float32)
        layer.soft_light = True
        layer.tint = np.full(3, 0.5, np.float32)                  # 0.5 is neutral
        np.testing.assert_allclose(layer.tinted(albedo, 1.0), albedo, atol=1e-6)
        layer.tint = np.array([0.25, 0.75, 1.0], np.float32)
        top, base = layer.tint, albedo                          # flag 0x100: albedo is the base
        np.testing.assert_allclose(layer.tinted(albedo, 1.0), (1 - 2 * top) * base ** 2 + 2 * top * base, atol=1e-6)
        np.testing.assert_allclose(layer.tinted(albedo, 0.5),
                                   albedo + ((1 - 2 * top) * base ** 2 + 2 * top * base - albedo) * 0.5, atol=1e-6)
        layer.soft_light_swap = True                            # flag 0x200: the tint is the base
        top, base = albedo, layer.tint
        np.testing.assert_allclose(layer.tinted(albedo, 1.0), (1 - 2 * top) * base ** 2 + 2 * top * base, atol=1e-6)

    def test_mesh_drops_hole_cells_and_writes_readable_cast(self):
        heights = np.arange(9, dtype=float).reshape(3, 3)
        solid = np.ones((3, 3), bool); solid[0, 1] = False          # cell (i=1, j=0)
        geometry = terrain_cast.mesh(self.sector(), heights, solid, (0, 0, 2, 2))
        self.assertEqual((geometry["cells"], geometry["hole_cells"], len(geometry["faces"])), (4, 1, 6))
        self.assertEqual(len(geometry["positions"]), 8)   # corner (2, 0) belonged only to the hole
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "t.cast"
            terrain_cast.write_cast(path, "t", geometry, "t.png")
            model = read_cast(path.read_bytes())[0].children[0]
            mesh = next(c for c in model.children if c.ident == b"mesh")
            np.testing.assert_allclose(mesh.array("vp"), geometry["positions"] * 2.54, rtol=1e-6)
            self.assertEqual(mesh.array("f").reshape(-1, 3).tolist(), geometry["faces"].tolist())


if __name__ == "__main__":
    unittest.main()
