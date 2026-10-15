"""The optional BO4 model route must stay bounded and keep section identities."""
import json
import sys
from pathlib import Path

import pytest

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "build-greyhound.ps1").is_file())
sys.path.insert(0, str(ROOT / "tools" / "black_ops_4" / "capture"))
from export_baked_terrain import map_identity, plan, write_placement_map
from build_bo4_terrain_cast import write_baked_material, write_cast
sys.path.insert(0, str(ROOT / "tools" / "cold_war" / "placements"))
from bake_cw_splines import read_cast
import numpy as np
from PIL import Image


def sector(root, index, samples=257, rotated=False):
    folder = root / "capture" / "sectors" / f"sector_{index}"
    folder.mkdir(parents=True)
    (folder / "sector.json").write_text(json.dumps({
        "sector": index, "grid_samples": samples, "units_per_sample": 8,
        "world_xy_origin": [index * 4096, 0],
        "local_to_world": [1] if rotated else None,
    }))


def test_plans_distinct_baked_models_and_bounded_textures(tmp_path):
    sector(tmp_path, 0)
    sector(tmp_path, 1)
    jobs = plan(tmp_path, chunk_cells=128, texels_per_inch=0.5, max_models=8)
    assert len(jobs) == 8
    assert len({j["name"] for j in jobs}) == 8
    assert jobs[0]["box"] == [0, 0, 1024, 1024]
    assert jobs[-1]["sector"] == 1


def test_large_map_stops_before_bake(tmp_path):
    sector(tmp_path, 0, samples=4097)
    with pytest.raises(ValueError, match="Use Terrain source capture"):
        plan(tmp_path, chunk_cells=128, texels_per_inch=0.5, max_models=64)


def test_map_identity_survives_name_resolution_and_avoids_cross_map_collisions(tmp_path):
    unresolved = {"asset": {"name": "terraingfx_66f9c06602fe491"}}
    resolved = {"asset": {"name": "maps/zm/zm_towers"},
                "header_words": [{"header_offset": "0x0", "u64": "0xF66F9C06602FE491"}]}
    assert map_identity(unresolved) == map_identity(resolved) == str(0x66F9C06602FE491)
    sector(tmp_path, 0)
    a = plan(tmp_path, 128, 0.5, 64, map_identity(resolved))
    b = plan(tmp_path, 128, 0.5, 64, map_identity({"asset": {"name": "terraingfx_1234"}}))
    assert not {j["name"] for j in a} & {j["name"] for j in b}
    assert all(len(j["name"]) < 64 for j in a + b)
    path = tmp_path / "terrain.map"
    write_placement_map(path, a)
    text = path.read_text()
    for job in a:
        assert f'"model" "{job["name"]}"' in text
    assert text.count('"origin" "0 0 0"') == len(a)
    assert text.count('"angles" "0 0 0"') == len(a)
    assert text.count('"modelscale" "1"') == len(a)


def test_bake_requires_a_captured_map_identity():
    with pytest.raises(ValueError, match="map identity"):
        map_identity({"asset": {"name": "unknown"}})


def test_rotated_sector_is_not_silently_baked(tmp_path):
    sector(tmp_path, 0, rotated=True)
    with pytest.raises(ValueError, match="rotated"):
        plan(tmp_path, 128, 0.5, 64)


def test_baked_maps_have_matching_greyhound_material_info(tmp_path):
    maps = {"albedo": np.full((2, 4, 4), 127, np.uint8),
            "normal": np.full((2, 4, 3), 128, np.uint8),
            "gloss": np.full((2, 4), 200, np.uint8),
            "roughness": np.full((2, 4), 55, np.uint8),
            "specular": np.full((2, 4, 3), 30, np.uint8)}
    files, info = write_baked_material(tmp_path, "terrain_01", maps)
    text = (tmp_path / info).read_text()
    for key, image in maps.items():
        assert files[key] == f"_images/terrain_01/terrain_01_{key}.png"
        with Image.open(tmp_path / files[key]) as actual:
            assert np.array_equal(np.asarray(actual), image)
    assert "colorMap,terrain_01_albedo" in text
    assert "normalMap,terrain_01_normal" in text
    assert "specularMap,terrain_01_specular" in text
    assert "Name: terrain_01" in text


def test_static_terrain_cast_has_converter_skeleton_and_rigid_weights(tmp_path):
    geometry = {
        "positions": np.array([[100, -20, 3], [108, -20, 3], [100, -12, 4]], float),
        "normals": np.array([[0, 0, 1]] * 3, float),
        "uv": np.array([[0, 1], [1, 1], [0, 0]], float),
        "faces": np.array([[0, 1, 2]]),
    }
    path = tmp_path / "terrain_01.cast"
    write_cast(path, "terrain_01", geometry, "_images/terrain_01/albedo.png")
    model = read_cast(path.read_bytes())[0].children[0]
    # Cast.NET's converter expects a skeleton first, like native Greyhound.
    assert [c.ident for c in model.children] == [b"skel", b"matl", b"mesh"]
    skeleton, material, mesh = model.children
    assert len(skeleton.children) == 1
    bone = skeleton.children[0]
    assert bone.ident == b"bone"
    assert bone.props["n"][2] == b"tag_origin\0"
    np.testing.assert_array_equal(bone.array("p"), [0xFFFFFFFF])
    for prop in ("lr", "wr"):
        np.testing.assert_array_equal(bone.array(prop), [[0, 0, 0, 1]])
    for prop in ("lp", "wp"):
        np.testing.assert_array_equal(bone.array(prop), [[0, 0, 0]])
    np.testing.assert_array_equal(bone.array("s"), [[1, 1, 1]])
    np.testing.assert_array_equal(mesh.array("mi"), [1])
    np.testing.assert_array_equal(mesh.array("wb"), [0, 0, 0])
    np.testing.assert_array_equal(mesh.array("wv"), [1, 1, 1])
    np.testing.assert_array_equal(mesh.array("vc"), [0xFFFFFFFF] * 3)
    np.testing.assert_array_equal(mesh.array("vp"), (geometry["positions"] * 2.54).astype("<f4"))
    np.testing.assert_array_equal(mesh.array("vn"), geometry["normals"].astype("<f4"))
    np.testing.assert_array_equal(mesh.array("u0"), geometry["uv"].astype("<f4"))
    np.testing.assert_array_equal(mesh.array("f"), geometry["faces"].ravel())
    assert mesh.array("m")[0] == material.hash
