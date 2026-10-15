"""Analytical regressions for color-space handling of BO4 tint masks."""
import sys as _tool_sys
from pathlib import Path as _ToolPath
REPO_ROOT = next(p for p in _ToolPath(__file__).resolve().parents if (p / 'build-greyhound.ps1').is_file())
TOOLS_ROOT = REPO_ROOT / 'tools'
_tool_sys.path.insert(0, str(TOOLS_ROOT))
import tool_bootstrap as _tool_bootstrap
_tool_bootstrap.activate(TOOLS_ROOT / 'tool_bootstrap.py')

import unittest
import numpy as np
from bo4_dxbc_emulator import Texture, srgb_decode_table


class TextureColorTests(unittest.TestCase):
    def test_srgb_rgb_and_all_alpha_codes_have_different_transfer_rules(self):
        pixels = np.full((1, 256, 4), 128, dtype=np.uint8)
        pixels[0, :, 3] = np.arange(256, dtype=np.uint8)
        texture = Texture.from_image(pixels, srgb=True, mips=False)
        x = np.arange(256)
        values = texture.load(x, np.zeros(256, int), np.zeros(256, int), 0)
        np.testing.assert_allclose(values[:, :3], ((128 / 255 + .055) / 1.055) ** 2.4, atol=1e-7)
        np.testing.assert_allclose(values[:, 3], x / 255, atol=1e-7)

    def test_supplied_native_levels_keep_alpha_linear_during_filtering(self):
        pixels = np.array([[[0, 0, 0, 64], [255, 255, 255, 192]]], dtype=np.uint8)
        texture = Texture([pixels], lut=srgb_decode_table())
        values = texture.sample(np.array([.5]), np.array([.5]), np.array([0]), np.array([0.0]))
        np.testing.assert_allclose(values[0], [.5, .5, .5, 128 / 255], atol=1e-7)

    def test_generated_mips_filter_rgb_in_linear_space_and_alpha_as_a_mask(self):
        pixels = np.array([[[0, 0, 0, 0], [255, 255, 255, 64]],
                           [[0, 0, 0, 128], [255, 255, 255, 255]]], dtype=np.uint8)
        texture = Texture.from_image(pixels, srgb=True)
        np.testing.assert_array_equal(texture.levels[1][0, 0, 0], [188, 188, 188, 112])
        values = texture.sample(np.array([.5]), np.array([.5]), np.array([0]), np.array([1.0]))
        np.testing.assert_allclose(values[0, 3], 112 / 255, atol=1e-7)

    def test_unorm_normal_variance_and_alpha_are_both_linear(self):
        pixels = np.full((2, 2, 4), 128, dtype=np.uint8)
        texture = Texture.from_image(pixels, srgb=False)
        values = texture.sample(np.array([.5]), np.array([.5]), np.array([0]), np.array([.5]))
        np.testing.assert_allclose(values, 128 / 255, atol=1e-7)


if __name__ == '__main__':
    unittest.main()
