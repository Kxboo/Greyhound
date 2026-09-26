"""Package a Greyhound BO4 probe without discarding overlapping layer weights.

Producer-side only: does not modify TerrainReconstructor, generate GDTs, or
invent a CW index image.

Per-sector sources are found from the probe itself, not from fixed names. Each
sector's image table lists one triple of texture arrays per sector size: R16
height (`terrain_height_maps_<i>`, 32n+4 square), R32 cutout
((4n+1) x (8n+1)) and BC4 layer weights (hash-named, 32n+4 square). A sector
takes the slice at its rank among sectors of its size; its layers' weight
slices come from side array +0x138. Measured on zm_white (2 sectors, n = 128
and 32), zm_towers (1 sector, n = 32) and Blackout (27 sectors in arrays of
4, 5, 14 and 4 slices; shared arrays are cut into per-sector files).
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

from bo4_volume_decals import decode_blend_word, decode_d3d11_packed, parse_decals


SCHEMA = "superterrain-bo4-source-package-v1"
MASK60 = (1 << 60) - 1
RUNTIME_LAYER_BYTES = 112
LAYER_RECORD_STRIDE = RUNTIME_LAYER_BYTES
FORMAT_R16, FORMAT_R32, FORMAT_BC4 = 56, 42, 80
ALWAYS_ONE, ALWAYS_ZERO = 4094, 4095     # layer weight slice sentinels
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
# The engine's own name for each semantic hash: atian-cod-tools' material hash
# h = (33 h) ^ (c | 0x20) over the name.  SEMANTICS keeps the spellings the GDT
# intake already reads; 0xFBFD3A43 is really heightMap (the tessellation
# displacement map, record +80), which zm_towers points at the reveal image.
ENGINE_SEMANTICS = {
    0xA0AB1041: "colorMap", 0x59D30D0F: "normalMap", 0x6D0A6C98: "glossMap", 0x07176BF2: "aoMap",
    0x34D849D5: "revealMap", 0xFBFD3A43: "heightMap", 0xEB529B4D: "detailMap",
    0xEC443804: "specColorMap", 0x199A03D3: "tintMask", 0x389DD40F: "thermalHeatmap",
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


def runtime_record(raw, slot):
    """Decode one 112-byte terrain pixel shader layer record (structured buffer t14).

    Every field the terrain G-buffer pixel shader (457b8be2b884842c) and domain
    shader (8b5368bcb0ce612f) read; see docs/bo4-terrain-research.md.
    """
    rec = raw[slot * RUNTIME_LAYER_BYTES:(slot + 1) * RUNTIME_LAYER_BYTES]
    u32 = struct.unpack("<28I", rec)
    half = lambda bits: struct.unpack("<e", struct.pack("<H", bits & 0xFFFF))[0]
    # 10-bit truncated halfs: the top 10 bits of a word, shifted back up by 6.
    top10 = lambda word: half((word >> 22) << 6)
    flags, blend = u32[13], u32[18]
    return {"raw_hex": rec.hex(), "weight_slice": u32[8], "flags": f"0x{flags:X}",
            "textured": bool(flags & 0x1), "normal_map": bool(flags & 0x2),
            "height_blend": bool(flags & 0x4), "gloss_mask": bool(flags & 0x8),
            "metal": bool(flags & 0x10), "detail_normal": bool(flags & 0x80),
            "soft_light_tint": bool(flags & 0x300), "soft_light_swap": bool(flags & 0x200),
            "far_tiling": bool(flags & 0x400), "ground_cover": bool(flags & 0x2000),
            "blend_contrast": (blend & 0xFF) / 255, "blend_exponent": ((blend >> 8) & 0xFF) / 255,
            "detail_strength": ((blend >> 16) & 0xFF) / 255, "normal_strength": (u32[17] >> 24) / 255,
            "tint_rgb": [half((u32[19] >> 16) << 6), top10(u32[20]), top10(u32[21])],
            "metal_rgb": [top10(u32[22]), top10(u32[23]), top10(u32[24])],
            "detail_uv_scale": [half(u32[10]), half(u32[10] >> 16)],
            "gloss_range": [half(u32[11]), half(u32[11] >> 16)],
            "reveal_uv_scale": [half(u32[12]), half(u32[12] >> 16)],
            "displacement_amount": half(flags >> 16),
            "slices": {"albedo": u32[21] & 0xFFFF, "albedo_array": (u32[21] >> 20) & 0x3,
                       "albedo_min_mip": (u32[21] >> 16) & 0xF, "displacement": u32[20] & 0xFFFF,
                       "normal": u32[23] & 0xFFFF, "normal_min_mip": (u32[23] >> 16) & 0x3F,
                       "detail_normal": u32[24] & 0xFFFF, "reveal": u32[25] & 0xFFFF,
                       "gloss_mask": u32[26] & 0xFFFF},
            "uv_rows": list(struct.unpack("<8f", rec[:32]))}


STAGES = {0: "pixel", 1: "vertex", 2: "geometry", 3: "hull", 4: "domain", 5: "compute"}


def dxbc_summary(data):
    """A DXBC container's stage and the declarations that tell terrain shaders apart.

    Read straight from the SHEX/SHDR tokens: structured buffers {register:
    stride}, constant buffers {register: rows}, texture2darray (uint) count,
    whether any instruction discards, and the declared outputs.
    """
    if data[:4] != b"DXBC":
        raise ValueError("not a DXBC container")
    chunks = struct.unpack_from("<I", data, 28)[0]
    for c in range(chunks):
        at = struct.unpack_from("<I", data, 32 + 4 * c)[0]
        tag, size = struct.unpack_from("<4sI", data, at)
        if tag in (b"SHEX", b"SHDR"):
            tokens = struct.unpack_from(f"<{size // 4}I", data, at + 8)
            break
    else:
        raise ValueError("DXBC container has no shader chunk")
    structured, cbuffers, outputs = {}, {}, []
    uint_arrays, discard, q = 0, False, 2
    while q < len(tokens):
        token = tokens[q]
        opcode = token & 0x7FF
        length = tokens[q + 1] if opcode == 53 else (token >> 24) & 0x7F   # 53: custom data
        if length == 0:
            break
        if opcode == 162:                                     # dcl_resource_structured
            structured[tokens[q + 2]] = tokens[q + length - 1]
        elif opcode == 88:                                    # dcl_resource
            if (token >> 11) & 0x1F == 8 and tokens[q + length - 1] & 0xF == 4:
                uint_arrays += 1                              # texture2darray (uint)
        elif opcode == 89:                                    # dcl_constantbuffer
            cbuffers[tokens[q + 2]] = tokens[q + 3]
        elif opcode == 13:                                    # discard
            discard = True
        elif opcode in (101, 103):                            # dcl_output, dcl_output_siv
            outputs.append({"register": tokens[q + 2],
                            **({"system_value": tokens[q + 3]} if opcode == 103 else {})})
        q += length
    return {"stage": STAGES.get(tokens[0] >> 16, str(tokens[0] >> 16)), "structured": structured,
            "cbuffers": cbuffers, "uint_texture_arrays": uint_arrays, "discard": discard, "outputs": outputs}


def terrain_shader_role(summary):
    """The replay role of a terrain shader, or None.

    The pixel and domain shaders come in pairs that differ only in how they
    bind the layer records: a 112-byte structured t14, which the replay feeds,
    or rows of CB1. The pixel variants that discard (the cutout) also declare
    the four texture2darray (uint) cutout arrays. A domain shader that writes
    only its position (system value 1) serves the depth pass; the G-buffer one
    also passes the tile id and world point on.
    """
    if summary["structured"].get(9) != 124 or summary["structured"].get(14) != LAYER_RECORD_STRIDE:
        return None
    if summary["stage"] == "pixel" and len(summary["outputs"]) == 3:
        return "gbuffer_cutout" if summary["discard"] and summary["uint_texture_arrays"] == 4 else (
            "gbuffer" if not summary["discard"] else None)
    if summary["stage"] == "domain":
        position_only = [o.get("system_value") for o in summary["outputs"]] == [1]
        return "domain" if position_only else "domain_gbuffer"
    return None


def load_wni(path):
    """Greyhound's LZ4 name index: key u64 (top nibble masked) then a NUL-terminated name."""
    import lz4.block
    raw = Path(path).read_bytes()
    _magic, _version, count, packed, unpacked = struct.unpack_from("<IHIII", raw, 0)
    body = lz4.block.decompress(raw[18:18 + packed], uncompressed_size=unpacked)
    names, off = {}, 0
    for _ in range(count):
        key = struct.unpack_from("<Q", body, off)[0] & MASK60
        off += 8
        end = body.index(b"\0", off)
        names[key] = body[off:end].decode("utf-8", "replace")
        off = end + 1
    return names


def layers(sector):
    candidates = [a["layers"] for a in sector["side_arrays"] if "layers" in a]
    if len(candidates) != 1:
        raise ValueError("Ambiguous/missing layer table")
    return candidates[0]


def array_slices(image, texel_bytes):
    """Texture-array depth of a grid image: its resident top-mip bytes over one slice."""
    per = image["width"] * image["height"] * texel_bytes
    total = image.get("loaded_mip_bytes") or per
    if total % per:
        raise ValueError(f"Grid image {image.get('name') or image['image']} is not a whole number of slices")
    return total // per


def right_angle_rotation(sector):
    """A rotated sector's local-to-world rows [[r00, r01], [r10, r11]] as exact 0/+-1, or None.

    world_from_local and local_from_world (probe v49) are each a translation t
    then 3x3 rows R, with world = local . R + t for row vectors. Only that
    reading makes the two invert each other (R' = R^T, t' = -t . R^T), which
    is checked. Only a turn about Z by a multiple of 90 degrees is accepted: it
    maps the sample lattice onto itself, so the grids can be re-indexed exactly.
    """
    wfl, lfw = sector.get("world_from_local"), sector.get("local_from_world")
    if not wfl or not lfw or len(wfl) != 12 or len(lfw) != 12:
        return None
    t, R = wfl[:3], [wfl[3 + 3 * i:6 + 3 * i] for i in range(3)]
    ti, Ri = lfw[:3], [lfw[3 + 3 * i:6 + 3 * i] for i in range(3)]
    exact = [[round(v) for v in row] for row in R]
    if any(abs(R[i][j] - exact[i][j]) > 1e-4 for i in range(3) for j in range(3)):
        return None
    if exact[2] != [0, 0, 1] or exact[0][2] or exact[1][2]:
        return None
    if any(abs(Ri[i][j] - R[j][i]) > 1e-4 for i in range(3) for j in range(3)):
        return None
    if any(abs(ti[j] + sum(t[i] * R[j][i] for i in range(3))) > 0.05 for j in range(3)):
        return None
    return [exact[0][:2], exact[1][:2]]


def grid_images(doc):
    """Map sector index -> {height, cutout, weights, slice, array_slices} image records.

    Each triple is one texture array per sector size (tiles across); the
    terrain vertex shader picks the array from sector record +116 >> 30 and the
    slice from +112 >> 20. Measured on Blackout (27 sectors in 4 arrays of 4, 5,
    14 and 4 slices): the static sector record's +0xE0 is the array, the one
    whose triple has the sector's tiles across, and +0xE4 is the slice, the
    sector's rank among sectors of that size in sector order. zm_white and
    zm_towers have one sector per size, so every array there has one slice.
    """
    records, seen = [], set()
    for sector in doc["sectors"]:
        for array in sector.get("side_arrays", []):
            for image in array.get("images", []):
                if isinstance(image, dict) and image.get("grid_shape") and image["image"] not in seen:
                    seen.add(image["image"]); records.append(image)
    if len(records) % 3:
        raise ValueError("Sector grid images do not form height/cutout/weight triples")
    by_size = {}
    for height, cutout, weights in zip(records[0::3], records[1::3], records[2::3]):
        if (height["format"], cutout["format"], weights["format"]) != (FORMAT_R16, FORMAT_R32, FORMAT_BC4):
            raise ValueError("Unexpected sector grid image order")
        match = re.fullmatch(r"terrain_height_maps_(\d+)", height.get("name", ""))
        if not match or cutout.get("name", f"terrain_cutout_maps_{match[1]}") != f"terrain_cutout_maps_{match[1]}":
            raise ValueError("Sector grid images are not named per array")
        n = height["tiles_across"]
        if not (cutout["tiles_across"] == weights["tiles_across"] == n
                and height["width"] == height["height"] == weights["width"] == weights["height"] == 32*n + 4
                and (cutout["width"], cutout["height"]) == (4*n + 1, 8*n + 1)):
            raise ValueError("Sector grid image dimensions disagree")
        if n in by_size:
            raise ValueError("Two grid arrays share a sector size")
        depth = array_slices(height, 2)
        if array_slices(cutout, 4) != depth:
            raise ValueError("Height and cutout arrays disagree in depth")
        by_size[n] = {"height": height, "cutout": cutout, "weights": weights, "array": int(match[1]),
                      "array_slices": depth, "weight_slices": array_slices(weights, 0.5)}
    result, used = {}, {}
    for sector in sorted(doc["sectors"], key=lambda s: s["sector"]):
        grid = by_size.get(sector["finest_width"])
        if grid is None:
            raise ValueError(f"No grid array for sector {sector['sector']}")
        k = used.get(sector["finest_width"], 0)
        used[sector["finest_width"]] = k + 1
        result[sector["sector"]] = {**grid, "slice": k}
        # v49 stores the record's own array and slice.
        if "grid_array" in sector and (sector["grid_array"], sector["grid_array_slice"]) != (grid["array"], k):
            raise ValueError(f"Sector {sector['sector']} record names array {sector['grid_array']} slice "
                             f"{sector['grid_array_slice']}, not {grid['array']} slice {k}")
    if any(used.get(n, 0) != g["array_slices"] for n, g in by_size.items()):
        raise ValueError("Sectors do not fill their grid arrays exactly")
    return result


def weight_slice_table(root, sector):
    """Each layer slot's BC4 weight slice (side array +0x138, u16 per layer).

    4094 = always 1 (the base layer), 4095 = always 0. Other values index the
    sector size's shared weight array; a sector's slices form one contiguous
    run. Equal to every live runtime record's +32 on Blackout sector 2, and
    the runs partition all four Blackout arrays (94, 80, 180 and 44 slices).
    Without the table (older probes) slot k reads slice k - 1.
    """
    count = len(layers(sector))
    side = [a for a in sector["side_arrays"] if a.get("count_offset") == "0x138" and a.get("file")]
    if not side:
        return [ALWAYS_ONE] + list(range(count - 1)), False
    raw = contained(root, side[0]["file"]).read_bytes()
    return list(struct.unpack_from(f"<{count}H", raw)), True


def dumped_file(image, fallback):
    dump = image.get("dump")
    name = dump.get("file") if isinstance(dump, dict) else None
    return name or fallback


def image_file(image, exports):
    row = exports.get(image["image"], {})
    if row.get("status") == "converted" and row.get("file"):
        return row["file"]
    return None


def raw_image_file(image, exports):
    """v47: an unpatched copy of a normal map (its blue channel is the gloss variance term)."""
    return exports.get(image["image"], {}).get("raw_file")


def package(probe_path, output, names_dir=None):
    probe_path, output = probe_path.resolve(), output.resolve()
    root = probe_path.parent
    doc = json.loads(probe_path.read_text(encoding="utf8"))
    if not doc["schema"].endswith(("v45", "v46", "v47", "v48", "v49")):
        raise ValueError("This adapter reads BO4 terrain probe v45 to v49")
    names = {}
    if names_dir:
        for stem in ("fnv1a_xmaterials", "fnv1a_ximages"):
            if (Path(names_dir) / (stem + ".wni")).is_file():
                names.update(load_wni(Path(names_dir) / (stem + ".wni")))
    # v46: the terrain pixel shader's per-layer records, found by content in live memory.
    runtime = {r["sector"]: r for r in doc.get("runtime_layer_records", {}).get("sectors", [])
               if r.get("status") == "found"}
    if output.exists():
        raise ValueError("Output must be new; refusing to mix capture runs")
    sectors = [s for s in doc["sectors"] if s.get("status") == "walked" or "side_arrays" in s]
    grids = grid_images(doc)
    walked = sorted(s["sector"] for s in sectors)
    if not sectors or walked != sorted(grids) or walked != list(range(doc.get("sector_count", len(sectors)))):
        raise ValueError("Walked sectors and their grid images disagree")
    # The sector record holds two rigid transforms, a translation then a 3x3
    # rotation each: world to local at +0x58, local to world at +0x88. Probes up
    # to v48 keep only the first four floats, so placement[3] is R[0][0]. The
    # grid rules above assume no rotation; Blackout turns sectors 1 and 18 by
    # +/-90 degrees and sector 24 by 180. Probe v49 keeps both transforms whole
    # (right_angle_rotation), so such a sector is packaged with its files as
    # captured and its rotation in `local_to_world`; without them it is left
    # out and reported rather than packaged unrotated.
    rotations = {s["sector"]: right_angle_rotation(s) for s in sectors if abs(s["placement"][3] - 1) > 1e-5}
    excluded = [{"sector": k, "rotation_r00": next(s["placement"][3] for s in sectors if s["sector"] == k),
                 "reason": "rotated sector; the probe did not keep the full rotation, or it is not a right angle about Z"}
                for k, rows in rotations.items() if rows is None]
    walked_sectors = sectors
    sectors = [s for s in sectors if rotations.get(s["sector"], True) is not None]
    for s in sectors:
        s["_rotation"] = rotations.get(s["sector"])
    heights = {h["name"]: h for h in doc.get("height_maps", [])}
    for sector in sectors:
        grid = grids[sector["sector"]]
        if grid["height"]["tiles_across"] != sector["finest_width"]:
            raise ValueError("Sector grid size disagrees with its tile levels")
        sector["_grid"] = grid
        sector["_files"] = {
            "height": heights[grid["height"]["name"]]["file"],
            "cutout": dumped_file(grid["cutout"], grid["cutout"].get("name", "") + ".bin"),
            "weights": dumped_file(grid["weights"], None)}
        if not sector["_files"]["weights"]:
            raise ValueError("Layer weight image was not dumped")
        table, stored = weight_slice_table(root, sector)
        if table[0] != ALWAYS_ONE:
            raise ValueError("Layer slot 0 is not the constant base layer")
        body = [v for v in table[1:] if v not in (ALWAYS_ONE, ALWAYS_ZERO)]
        base = min(body) if body else 0
        if sorted(body) != list(range(base, base + len(body))) or base + len(body) > grid["weight_slices"]:
            raise ValueError("A sector's weight slices are not one contiguous run in its array")
        sector["_weights"] = {"table": table, "stored": stored, "base": base, "count": len(body)}
        # Shared arrays are cut per sector; one-slice arrays with slot k reading
        # slice k - 1 are copied as they are (zm_white, zm_towers).
        sector["_shared"] = grid["array_slices"] > 1 or grid["weight_slices"] != len(body) or \
            table[1:] != list(range(len(table) - 1))

    exports, unique_materials = {}, {}
    for sector in sectors:
        for layer in layers(sector):
            unique_materials.setdefault(layer["material"], layer)
    # The probe exports each image once, at its first sighting, which may be
    # in a sector left out above.
    for sector in walked_sectors:
        for layer in layers(sector):
            for im in layer["images"]:
                if im.get("export"):
                    exports[im["image"]] = im["export"]

    # Validate required sources before producing a partial-looking package.
    sources = {probe_path}
    for sector in sectors:
        idx, n = sector["sector"], sector["finest_width"]
        width = n * 32 + 4
        files, grid = sector["_files"], sector["_grid"]
        required = {
            files["height"]: width * width * 2 * grid["array_slices"],
            files["cutout"]: (n * 4 + 1) * (n * 8 + 1) * 4 * grid["array_slices"],
            files["weights"]: (width // 4)**2 * 8 * grid["weight_slices"],
        }
        for name, size in required.items():
            source = contained(root, name)
            if source.stat().st_size != size:
                raise ValueError(f"Unexpected size: {name}, expected {size}")
            sources.add(source)
        if sector["height_bias_world"] != sector["min_z"] + sector["placement"][2]:
            raise ValueError("Inconsistent world Z")

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
                      "engine_semantic": ENGINE_SEMANTICS.get(raw, semantic),
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
                raw_file = raw_image_file(im, exports)
                if raw_file:
                    record["raw_png_file"] = copy(contained(root, raw_file),
                                                  "materials/images/" + safe_name(Path(raw_file).name))
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
        grid, wt = sector["_grid"], sector["_weights"]
        per_slice = (width // 4)**2 * 8

        def map_copy(name, slice_bytes=None, first=0, count=1):
            if not sector["_shared"]:
                return copy(contained(root, name), prefix + name)
            # One sector's slices out of a shared texture array, written as their own file.
            source = contained(root, name)
            with source.open("rb") as stream:
                stream.seek(first * slice_bytes)
                data = stream.read(count * slice_bytes)
            if len(data) != count * slice_bytes:
                raise ValueError("Short read from grid array " + name)
            relative = prefix + f"{Path(name).stem}_slices_{first}_{count}{Path(name).suffix}"
            (output / relative).parent.mkdir(parents=True, exist_ok=True)
            (output / relative).write_bytes(data)
            inventory.append({"file": relative, "source": source.name, "bytes": len(data),
                              "source_byte_offset": first * slice_bytes,
                              "sha256": hashlib.sha256(data).hexdigest()})
            return relative
        hfile = map_copy(sector["_files"]["height"], width * width * 2, grid["slice"])
        wfile = map_copy(sector["_files"]["weights"], per_slice, wt["base"], wt["count"])
        cfile = map_copy(sector["_files"]["cutout"], (n*4 + 1) * (n*8 + 1) * 4, grid["slice"])
        ls = layers(sector)
        table = wt["table"]
        layer_rows = []
        records = runtime.get(idx)
        if records is not None and records["layers_expected"] != len(ls):
            raise ValueError("Runtime layer records do not cover the sector's layers")
        raw_records = (root / records["file"]).read_bytes() if records else None
        for layer in ls:
            material = material_records[layer["material"]]
            source_slice = table[layer["layer"]]
            extra = {"weight_source_slice": source_slice,
                     "weight_constant": {ALWAYS_ONE: 1, ALWAYS_ZERO: 0}.get(source_slice)} if sector["_shared"] else {}
            layer_rows.append({"slot": layer["layer"], "material": material["name"],
                "weight_slice": source_slice - wt["base"] if source_slice not in (ALWAYS_ONE, ALWAYS_ZERO) else None,
                **extra,
                "uv_matrix_2x4": layer["uv"],
                "constants_uninterpreted": layer.get("constants"),
                "runtime": runtime_record(raw_records, layer["layer"]) if raw_records else None,
                "source_binding": {k: v for k, v in layer.items()
                                   if k not in ("images", "material_dump", "techset", "constants")}})
        finest = next(t for t in sector["tile_masks"] if t["level"] == 0)
        masks = finest["masks"]
        if len(masks) != n*n:
            raise ValueError("Incomplete tile mask")
        # The tile mask is a u32 at tile +0xA8 (Blackout sector 2 uses bit 27); keep u16 files
        # when every mask fits so older packages stay byte-identical.
        wide = max(masks) > 0xFFFF
        mask_name = prefix + ("tile_layer_mask.u32" if wide else "tile_layer_mask.u16")
        (output / mask_name).write_bytes(struct.pack("<%d%s" % (len(masks), "I" if wide else "H"), *masks))
        row = {"sector": idx, "tiles_across": n, "grid_samples": used,
               "units_per_sample": sector["units_per_sample"],
               "placement": sector["placement"], "local_height_bias": sector["min_z"],
               "world_height_bias": sector["height_bias_world"],
               "world_xy_origin": sector["bounds"][:2], "content_bounds": sector["bounds"],
               **({"local_to_world": {
                   "rotation_rows": sector["_rotation"], "translation": sector["world_from_local"][:3],
                   "convention": "world = local . R + t with row vectors, about the sector centre",
                   "grids": "the height, cutout, weight and tile mask files keep the captured local layout "
                            "(rows +local Y, columns +local X); the grid rule holds after "
                            "verify_bo4_terrain_package.world_aligned, which re-indexes them into the world. "
                            "Layer uv rows act on world positions and need nothing."}}
                  if sector["_rotation"] else {}),
               "height": {"file": hfile, "format": "R16_UNORM_LE", "width": width,
                          "height": width, "scale": sector["z_range"]/65535,
                          "formula": "world_height_bias + sample_u16 * scale",
                          # Verified by verify_bo4_terrain_package.py (edge padding, surface props).
                          "grid": "sample[row][col] is at world_xy_origin + (col, row) * units_per_sample; "
                                  "rows +Y, columns +X; samples 32n+1..32n+3 repeat 32n (padding)"},
               "layer_weights": {"file": wfile, "format": "BC4_UNORM", "dxgi_format": 80,
                   "width": width, "height": width, "slices": wt["count"],
                   "storage": "slice_major", "bytes_per_slice": per_slice,
                   "slice_to_layer_slot": [table.index(wt["base"] + k) for k in range(wt["count"])],
                   **({"array_slice_base": wt["base"], "array_slices": grid["weight_slices"],
                       "slice_rule": "file slice k = shared array slice array_slice_base + k; a runtime record's "
                                     "+32 is the shared slice, so subtract array_slice_base; 4094 = weight 1, "
                                     "4095 = weight 0 (no slice)"} if sector["_shared"] else {}),
                   "base_layer": 0, "independent_fields": True,
                   "normalization_applied": False,
                   # Read from the terrain pixel shader; see docs/bo4-terrain-research.md.
                   "composition": {
                       "rule": "sequential lerp in ascending layer slot: color = lerp(color, layer_color, w'); "
                               "the first layer whose sampled w > 0 is drawn at w' = 1; base slot 0 has constant weight 1",
                       "w_prime_plain": "w (the BC4 sample)",
                       "w_prime_height_blend": "x = sat(0.998 w + 0.001); lo = sat((1-x) - c x^e); "
                                               "hi = sat((1-x) + c (1-x)^e); w' = max(sat((h - lo) / (hi - lo)), "
                                               "sat(100 (w - 0.99))); w = 0 stays 0",
                       "height_blend_inputs": "c, e = per-layer u8/255; h = the layer's blend-height texture "
                                              "(distance-faded toward h = 0.5 when the layer's far-tiling flag is set)",
                       "per_layer_parameters": "layers[].runtime (probe v46+): the 112-byte record the shader "
                                               "reads; h is the layer's revealMap red channel"}},
               "cutout": {"file": cfile, "format": "R32_UINT_LE", "width": n*4+1,
                   "height": n*8+1, "packing": "x8_y4_lsb_first", "set_bit": "solid",
                   "clear_bit": "hole (the terrain pixel shader discards)",
                   "bit_address": "sample (i, j) -> word (i >> 3, j >> 2), bit (i & 7) + 8 * (j & 3); "
                                  "same grid and orientation as the height samples",
                   "coverage": "bit (i, j) decides the cell from sample (i, j) to (i + 1, j + 1)",
                   "cell_clipping_policy": "Not baked; source bits preserved"},
               "tile_layer_mask": {"file": mask_name, "width": n, "height": n, **({"dtype": "u4"} if wide else {})},
               "layers": layer_rows,
               **({"grid_array": {"array": grid["array"], "slice": grid["slice"],
                                  "array_slices": grid["array_slices"],
                                  "weight_table_stored": wt["stored"],
                                  "note": "height and cutout are this sector's slice of shared texture arrays"}}
                  if sector["_shared"] else {})}
        write_json(output / prefix / "sector.json", row)
        sector_records.append(row)

    decals = package_decals(doc, root, output, copy, names) if doc.get("volume_decals", {}).get(
        "status") == "captured" else None
    shaders = package_terrain_shaders(doc, root, output, copy) if doc.get("shader_scan", {}).get(
        "terrain_shaders") else None

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
             **({"excluded_sectors": excluded} if excluded else {}),
             "volume_decals": decals,
             "terrain_shaders": shaders,
             "layer_bindings": sum(len(s["layers"]) for s in sector_records),
             "materials": len(material_records), "images": sum(r["file"].endswith(".png") for r in inventory),
             "missing_images": missing, "unresolved_semantics": warnings,
             "copied_files": inventory,
             "unfinished": ["Weight-aware control fitting for faithful BO3 interpolation between samples",
                            *([] if runtime else ["Per-layer runtime records (height-blend enable, contrast, exponent, tint): capture with probe v46+"]),
                            *([] if shaders else ["Terrain pixel and domain shaders for --emulate: capture with probe v48+"]),
                            "Brush/clip outputs are separate Greyhound pipeline artifacts"]}
    write_json(output / "package_audit.json", audit)
    return audit


def package_terrain_shaders(doc, root, output, copy):
    """v48: the terrain's graphics shaders, each tagged with the role the replay gives it."""
    prefix = "capture/shaders/terrain/"
    rows = []
    for hit in doc["shader_scan"]["terrain_shaders"]:
        if hit.get("status") != "dumped":
            continue
        source = contained(root, hit["file"])
        data = source.read_bytes()
        digest = hashlib.sha1(data).hexdigest()[:16]
        summary = dxbc_summary(data)
        rows.append({"file": copy(source, prefix + f"{digest}_{summary['stage']}.dxbc").removeprefix(prefix),
                     "sha1_16": digest, "stage": summary["stage"], "role": terrain_shader_role(summary),
                     "copies_in_memory": hit.get("copies"), "structured_strides": summary["structured"],
                     "constant_buffers": summary["cbuffers"], "discard": summary["discard"],
                     "uint_texture_arrays": summary["uint_texture_arrays"], "outputs": len(summary["outputs"])})
    rows.sort(key=lambda r: (r["role"] is None, r["stage"], r["sha1_16"]))
    roles = {}
    for row in rows:
        if row["role"]:
            roles.setdefault(row["role"], []).append(row["sha1_16"])
    ambiguous = {role: ids for role, ids in roles.items() if len(ids) > 1}
    if ambiguous:
        raise ValueError(f"More than one terrain shader fits a role: {ambiguous}")
    write_json(output / prefix / "shaders.json", {
        "schema": "superterrain-bo4-terrain-shaders-v1", "shaders": rows,
        "rule": "probe v48 keeps every non-compute shader declaring the 124-byte node record (t9); "
                "roles: package_bo4_terrain.terrain_shader_role"})
    return {"file": prefix + "shaders.json", "shaders": len(rows), "roles": {k: v[0] for k, v in roles.items()}}


def blend_agrees(words, packed):
    """The engine words decode to the same colour blend and write mask d3d11 built."""
    runtime = decode_d3d11_packed(packed)["rt"]
    for word, rt in zip(words, runtime):
        mine = decode_blend_word(int(word, 16))
        if mine["write_mask"] != rt["write_mask"] or mine["enable"] != rt["enable"]:
            return False
        if mine["enable"] and (mine["src"], mine["dst"], mine["op"]) != (rt["src"], rt["dst"], rt["op"]):
            return False
    return True


def package_decals(doc, root, output, copy, names):
    """v47: GfxWorld volume decals with everything their G-buffer pass reads."""
    capture = doc["volume_decals"]
    prefix = "capture/decals/"
    raw = contained(root, capture["file"]).read_bytes()
    copy(contained(root, capture["file"]), prefix + "volume_decals.bin")
    if capture.get("aux_file"):
        copy(contained(root, capture["aux_file"]), prefix + "volume_decal_aux.bin")

    def image_row(image):
        name = image.get("name")
        if name and name.startswith("ximage_0x"):
            name = names.get(int(name[len("ximage_0x"):], 16), name)
        row = {"name": name, "pointer": image["image"], "dxgi_format": image.get("format"),
               "width": image.get("width"), "height": image.get("height")}
        if image.get("file"):
            row["png_file"] = copy(contained(root, image["file"]),
                                   prefix + "images/" + safe_name(Path(image["file"]).name))
        else:
            row["status"] = image.get("status", "missing")
        if image.get("texture_def"):
            definition = bytes.fromhex(image["texture_def"])
            row["uv_scale"] = list(struct.unpack_from("<2f", definition, 0x0C))
        return row

    materials = {}
    for m in capture["materials"]:
        key = int(m["hash"], 16) if m.get("hash") else None
        row = {"pointer": m["material"], "hash": m.get("hash"), "decals": m["decals"],
               "name": m.get("name") or names.get(key) or ("xmaterial_" + format(key or 0, "x"))}
        if m.get("cbuffer"):
            row["cbuffer_file"] = copy(contained(root, m["cbuffer"]), prefix + "cbuffers/" + safe_name(m["cbuffer"]))
            data = contained(root, m["cbuffer"]).read_bytes()
            row["cbuffer_floats"] = list(struct.unpack("<%df" % (len(data) // 4), data[:len(data) // 4 * 4]))
        row["images"] = []
        for image in m.get("images", []):
            semantic = int(image["semantic"], 16)
            entry = image_row(image)
            entry.update(raw_semantic=image["semantic"],
                         engine_semantic=ENGINE_SEMANTICS.get(semantic, image["semantic"]))
            row["images"].append(entry)
        row["pass_arguments"] = m.get("pass_arguments", [])
        row["samplers"] = m.get("samplers", [])
        if m.get("blend_words"):
            row["blend"] = [decode_blend_word(int(w, 16)) for w in m["blend_words"]]
            if m.get("d3d11_blend_packed"):
                row["blend_matches_d3d11"] = blend_agrees(m["blend_words"], m["d3d11_blend_packed"])
        if m.get("pixel_shader"):
            source = contained(root, m["pixel_shader"])
            digest = hashlib.sha1(source.read_bytes()).hexdigest()[:16]
            row["pixel_shader"] = {"file": copy(source, prefix + "shaders/" + digest + ".dxbc"), "sha1_16": digest}
        materials[m["material"]] = row

    decals = parse_decals(raw)
    for decal in decals:
        decal["material_name"] = materials.get(decal["material"], {}).get("name")
    atlas = image_row(capture["atlas"]) if capture.get("atlas") else None
    record = {"schema": "superterrain-bo4-volume-decals-v1", "count": len(decals),
              "record_bytes": 216, "records_file": prefix + "volume_decals.bin", "atlas": atlas,
              "decals": decals, "materials": list(materials.values()),
              "draw_order": "priority (+0xC8) descending, then material pointer ascending, as each "
                            "live list is sorted; draw calls assumed to follow the list; ties have no "
                            "fixed order (bo4_decal_composite.draw_key)",
              "shader_inputs": {"t21": "220-byte records: bo4_volume_decals.gpu_record",
                                "t0": "scene depth", "t6": "terrain/G-buffer normal render target",
                                "atlas": "the one declared texture no pass argument binds (t12, t14, t18, t19 "
                                         "or t20 on zm_towers)"}}
    write_json(output / prefix / "decals.json", record)
    mismatched = [m["name"] for m in materials.values() if m.get("blend_matches_d3d11") is False]
    return {"file": prefix + "decals.json", "decals": len(decals), "materials": len(materials),
            "blend_words_disagree_with_d3d11": mismatched}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("probe", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--names", type=Path,
                        help="folder of Greyhound .wni name indexes (e.g. package_index/echo000_bo4) "
                             "to name decal materials the probe could not")
    args = parser.parse_args()
    result = package(args.probe, args.output, args.names)
    print(json.dumps({k: v for k, v in result.items()
                      if k not in ("copied_files", "unresolved_semantics")}, indent=2))
