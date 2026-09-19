"""Package a Greyhound BO4 probe without discarding overlapping layer weights.

Producer-side only: does not modify TerrainReconstructor, generate GDTs, or
invent a CW index image. The present control-map associations were measured on
zm_white; another asset must be explicitly decoded before using this packager.
"""
from __future__ import annotations

# Support direct execution and the isolated packaged Python runtime.
import sys as _tool_sys
from pathlib import Path as _ToolPath
TOOLS_ROOT = next(p for p in _ToolPath(__file__).resolve().parents if (p / "tool_bootstrap.py").is_file())
_tool_sys.path.insert(0, str(TOOLS_ROOT))
import tool_bootstrap as _tool_bootstrap
_tool_bootstrap.activate(__file__)
REPO_ROOT = TOOLS_ROOT.parent

import argparse
import csv
import hashlib
import json
import re
import shutil
import struct
from pathlib import Path


SCHEMA = "superterrain-bo4-source-package-v1"
ZM_WHITE = "1173ca83f06a352"
WEIGHT_FILES = {
    0: "terrain_map_B8AE8EB18D0C15E.bin",
    1: "terrain_map_B8AE9EB18D0C311.bin",
}
# Retain the raw semantic alongside the consumer spelling. Height/reveal is
# intentionally not called roughness, despite that obsolete label in v45.
SEMANTICS = {
    0xA0AB1041: ("color", "colorMap", "_c"),
    0x59D30D0F: ("normal", "normalMap", "_n"),
    0x6D0A6C98: ("gloss", "glossMap", "_g"),
    0x07176BF2: ("occlusion", "aoMap", "_o"),
    0x34D849D5: ("height_reveal", "revealMap", "_r"),
    0xFBFD3A43: ("height_reveal", "revealMap", "_r"),
}


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf8")


def safe_name(value):
    if not re.fullmatch(r"[A-Za-z0-9_$/.-]+", value) or any(
            p in ("", ".", "..") for p in value.split("/")):
        raise ValueError("Unsafe asset name: " + value)
    return value


def contained(root, relative):
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise ValueError("Source path escapes capture: " + relative)
    return path


def layers(sector):
    candidates = [a["layers"] for a in sector["side_arrays"] if "layers" in a]
    if len(candidates) != 1:
        raise ValueError("Ambiguous/missing layer table")
    return candidates[0]


def image_file(image, exports):
    row = exports.get(image["image"], {})
    if row.get("status") == "converted" and row.get("file"):
        return row["file"]
    return None


def package(probe_path, output):
    probe_path, output = probe_path.resolve(), output.resolve()
    root = probe_path.parent
    doc = json.loads(probe_path.read_text(encoding="utf8"))
    if ZM_WHITE not in str(root).lower() or not doc["schema"].endswith("v45"):
        raise ValueError("This measured adapter currently accepts zm_white v45 only")
    if output.exists():
        raise ValueError("Output must be new; refusing to mix capture runs")
    sectors = [s for s in doc["sectors"] if s.get("status") == "walked" or "side_arrays" in s]
    if sorted(s["sector"] for s in sectors) != [0, 1]:
        raise ValueError("Expected both measured zm_white sectors")

    exports, unique_materials = {}, {}
    for sector in sectors:
        for layer in layers(sector):
            unique_materials.setdefault(layer["material"], layer)
            for im in layer["images"]:
                if im.get("export"):
                    exports[im["image"]] = im["export"]

    # Validate required sources before producing a partial-looking package.
    sources = {probe_path}
    for sector in sectors:
        idx, n = sector["sector"], sector["finest_width"]
        width = n * 32 + 4
        required = {
            f"terrain_height_maps_{idx}.r16.bin": width * width * 2,
            f"terrain_cutout_maps_{idx}.bin": (n * 4 + 1) * (n * 8 + 1) * 4,
            WEIGHT_FILES[idx]: (width // 4)**2 * 8 * (len(layers(sector)) - 1),
        }
        for name, size in required.items():
            source = contained(root, name)
            if source.stat().st_size != size:
                raise ValueError(f"Unexpected size: {name}, expected {size}")
            sources.add(source)
        if sector["placement"][3] != 1 or sector["height_bias_world"] != sector["min_z"] + sector["placement"][2]:
            raise ValueError("Unsupported placement or inconsistent world Z")

    output.mkdir(parents=True)
    inventory, copied = [], {}

    def copy(source, relative):
        source = source.resolve()
        target = output / relative
        if relative in copied:
            if copied[relative] != source:
                raise ValueError("Output name collision: " + relative)
            return relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        digest = sha(source)
        if sha(target) != digest:
            raise ValueError("Copy verification failed: " + relative)
        copied[relative] = source
        inventory.append({"file": relative, "source": source.name,
                          "bytes": target.stat().st_size, "sha256": digest})
        return relative

    copy(probe_path, "capture/evidence/terraingfx_probe.json")
    material_records, recipe, report_materials = {}, [], []
    txt_aliases, warnings, missing = {}, [], []
    for pointer, layer in unique_materials.items():
        name = layer.get("material_name")
        if not name:
            name = "xmaterial_" + format(int(layer["material_hash"], 16), "x")
        name = safe_name(name)
        # The GDT flat importer keys TXT declarations by basename. Preserve the
        # full asset name in the recipe targets and record this adapter alias.
        alias = name.split("/")[-1].lower()
        if alias in txt_aliases and txt_aliases[alias] != name:
            raise ValueError("GDT TXT basename collision: " + alias)
        txt_aliases[alias] = name
        bindings, txt_rows, packaged_images = [], [], []
        for im in layer["images"]:
            raw = int(im["semantic"], 16)
            role, semantic, suffix = SEMANTICS.get(raw, (
                "unresolved", f"unk_semantic_0x{raw:X}", ""))
            source_file = image_file(im, exports)
            image_name = im.get("name") or (Path(source_file).stem if source_file else "ximage_" + im["hash"])
            safe_name(image_name)
            record = {"raw_semantic": im["semantic"], "semantic": semantic,
                      "role": role, "asset_name": image_name, "image_pointer": im["image"],
                      "source_dxgi_format": im["format"], "declared_width": im["width"],
                      "declared_height": im["height"], "engine_constant": image_name.startswith("$")}
            if source_file:
                source = contained(root, source_file)
                dest = "materials/images/" + safe_name(Path(source_file).name)
                copy(source, dest)
                from PIL import Image
                with Image.open(source) as png:
                    record["exported_size"] = list(png.size)
                record.update(png_file=dest, status="captured", export=exports[im["image"]])
                packaged_images.append({"file": dest, "image_name": image_name})
            else:
                record["status"] = "missing"
                missing.append({"material": name, "image": image_name})
            if role == "unresolved":
                warnings.append({"material": name, "semantic": im["semantic"],
                                 "image": image_name, "note": "Preserved; no shader assignment inferred"})
            # Multiple BO4 bindings may point at the same reveal image.
            if (semantic, image_name) not in txt_rows:
                txt_rows.append((semantic, image_name))
            bindings.append(record)
        txt = "materials/materials/" + alias + "_images.txt"
        (output / txt).parent.mkdir(parents=True, exist_ok=True)
        with (output / txt).open("w", encoding="utf8", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(["semantic", "image_name"])
            writer.writerows(txt_rows)
        material_records[pointer] = {"name": name, "pointer": pointer,
            "name_status": "captured" if layer.get("material_name") else "hash_placeholder",
            "hash": layer.get("material_hash"), "bindings": bindings,
            "txt_file": txt, "txt_alias": alias}
        recipe.append({"source_material": alias, "source_asset_name": name,
                       "opaque_material": name, "blend_material": name + "_blend"})
        report_materials.append({"source_txt": alias + "_images.txt",
            "package_txt": {"images": {"file": txt.removeprefix("materials/")}},
            "packaged_images": [{**im, "file": im["file"].removeprefix("materials/")}
                                for im in packaged_images]})

    sector_records = []
    for sector in sectors:
        idx, n = sector["sector"], sector["finest_width"]
        width, used = n*32+4, n*32+1
        prefix = f"capture/sectors/sector_{idx}/"
        def map_copy(name):
            return copy(contained(root, name), prefix + name)
        hfile = map_copy(f"terrain_height_maps_{idx}.r16.bin")
        wfile = map_copy(WEIGHT_FILES[idx])
        cfile = map_copy(f"terrain_cutout_maps_{idx}.bin")
        ls = layers(sector)
        layer_rows = []
        for layer in ls:
            material = material_records[layer["material"]]
            layer_rows.append({"slot": layer["layer"], "material": material["name"],
                "weight_slice": layer["layer"]-1 if layer["layer"] else None,
                "uv_matrix_2x4": layer["uv"],
                "constants_uninterpreted": layer.get("constants"),
                "source_binding": {k: v for k, v in layer.items()
                                   if k not in ("images", "material_dump", "techset", "constants")}})
        finest = next(t for t in sector["tile_masks"] if t["level"] == 0)
        masks = finest["masks"]
        if len(masks) != n*n:
            raise ValueError("Incomplete tile mask")
        mask_name = prefix + "tile_layer_mask.u16"
        (output / mask_name).write_bytes(struct.pack("<%dH" % len(masks), *masks))
        row = {"sector": idx, "tiles_across": n, "grid_samples": used,
               "units_per_sample": sector["units_per_sample"],
               "placement": sector["placement"], "local_height_bias": sector["min_z"],
               "world_height_bias": sector["height_bias_world"],
               "world_xy_origin": sector["bounds"][:2], "content_bounds": sector["bounds"],
               "height": {"file": hfile, "format": "R16_UNORM_LE", "width": width,
                          "height": width, "scale": sector["z_range"]/65535,
                          "formula": "world_height_bias + sample_u16 * scale"},
               "layer_weights": {"file": wfile, "format": "BC4_UNORM", "dxgi_format": 80,
                   "width": width, "height": width, "slices": len(ls)-1,
                   "storage": "slice_major", "bytes_per_slice": (width//4)**2*8,
                   "slice_to_layer_slot": list(range(1, len(ls))),
                   "base_layer": 0, "independent_fields": True,
                   "normalization_applied": False,
                   "composition": "Runtime blending not established by nonzero-support checks"},
               "cutout": {"file": cfile, "format": "R32_UINT_LE", "width": n*4+1,
                   "height": n*8+1, "packing": "x8_y4_lsb_first", "set_bit": "solid",
                   "cell_clipping_policy": "Not baked; source bits preserved"},
               "tile_layer_mask": {"file": mask_name, "width": n, "height": n},
               "layers": layer_rows}
        write_json(output / prefix / "sector.json", row)
        sector_records.append(row)

    write_json(output / "materials/superterrain_materials.json", {
        "schema": "superterrain-material-recipe-v1", "game": "black_ops_4",
        "materials": recipe, "note": "Intake recipe only; no GDT generated"})
    write_json(output / "materials/material_report.json", {"materials": report_materials})
    write_json(output / "capture/terraingfx.json", {
        "schema": SCHEMA, "game": "black_ops_4", "asset": doc["asset"],
        "path_base": "package root (parent of capture)", "sectors": sector_records,
        "materials": list(material_records.values()),
        "intake": {"gdt_creator": "Greyhound TXT + images + superterrain-material-recipe-v1",
                   "terrain_reconstructor": "Native BO4 intake: Black Ops III Prefabs + textures; requires the September 12 native-intake build or newer",
                   "fabricated_index_map": False}})
    write_json(output / "capture/evidence/asset_pools.json", {
        "source_probe": "terraingfx_probe.json", "status": "captured_directory_only",
        "pools": doc["occupied_pools"],
        "limits": "Pool directory evidence only. Brush/clip reconstruction belongs to the separate Greyhound collision pipeline, not this terrain package."})
    audit = {"schema": SCHEMA, "source_probe": str(probe_path),
             "source_probe_sha256": sha(probe_path), "sectors": len(sector_records),
             "layer_bindings": sum(len(s["layers"]) for s in sector_records),
             "materials": len(material_records), "images": sum(r["file"].endswith(".png") for r in inventory),
             "missing_images": missing, "unresolved_semantics": warnings,
             "copied_files": inventory,
             "unfinished": ["Weight-aware control fitting for faithful BO3 interpolation between samples",
                            "Actual terrain shader blend constants and rule",
                            "Brush/clip outputs are separate Greyhound pipeline artifacts"]}
    write_json(output / "package_audit.json", audit)
    return audit


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("probe", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    result = package(args.probe, args.output)
    print(json.dumps({k: v for k, v in result.items()
                      if k not in ("copied_files", "unresolved_semantics")}, indent=2))
