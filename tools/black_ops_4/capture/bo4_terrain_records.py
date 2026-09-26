"""The terrain layer record (t14) of every layer material, captured or rebuilt from the material.

A capture holds the 112-byte runtime records only for the sectors streamed
near the player. Every other layer is rebuilt from its material:

- Flags. Materials that share a technique set share every flag bit the terrain
  pixel shader tests (0x1, 0x2, 0x4, 0x10, 0x80, 0x100, 0x200, 0x400) except
  0x8, the gloss mask, which is clear exactly when the gloss map is
  $white_gloss (25 of 25 captured materials). The technique set comes from
  read_bo4_terrain_techsets. A technique set no capture reached takes 0x1 and
  0x2, 0x4 from a real reveal map, 0x80 from a detail map, and soft light and
  far tiling (0x100, 0x200, 0x400) from a captured material with the same
  colour map, if there is one.
- Values. The material's constant buffer holds them in HLSL packing order
  (a field never straddles a float4), fields present by the bound textures:

      0 unused, 1-3 tint, 4 normal strength, 5 gloss lo, 6 gloss hi,
      [reveal map:  contrast, exponent, reveal uv scale (2)]
      [height map:  displacement (3); the amount is the third, x3]
      [detail map:  detail uv scale (2), detail strength]

  Materials that bind the coal texture (semantic 0xBA68F89F) use their own
  order (COAL_LAYOUT). The record stores them quantized: tint as floats
  truncated to 4 mantissa bits; strengths, contrast and exponent as u8/255
  truncated; gloss, uv scales and displacement as halves truncated.

Both rules reproduce 23 of the 25 captured Blackout records exactly (check()).
The other two share one technique set (flags 0xCB) whose constant buffer is
empty apart from two 128s: its values live elsewhere, so its uncaptured
members take a captured member's values.
"""

# Support direct execution and the isolated packaged Python runtime.
import sys as _tool_sys
from pathlib import Path as _ToolPath
TOOLS_ROOT = next(p for p in _ToolPath(__file__).resolve().parents if (p / "tool_bootstrap.py").is_file())
_tool_sys.path.insert(0, str(TOOLS_ROOT))
import tool_bootstrap as _tool_bootstrap
_tool_bootstrap.activate(__file__)
import argparse
import json
import math
from pathlib import Path

SHADER_FLAGS = 0x1 | 0x2 | 0x4 | 0x8 | 0x10 | 0x80 | 0x100 | 0x200 | 0x400
COAL_SEMANTIC = "unk_semantic_0xBA68F89F"
COAL_LAYOUT = {"tint": 1, "normal_strength": 4, "gloss_lo": 10, "gloss_hi": 11, "contrast": 12, "exponent": 13,
               "reveal_uv_scale": 14, "displacement": 17}
FIELDS = ("tint_rgb", "normal_strength", "gloss_range", "blend_contrast", "blend_exponent", "reveal_uv_scale",
          "detail_uv_scale", "detail_strength", "displacement_amount")


def trunc_mantissa(v, bits):
    if v <= 0:
        return 0.0
    step = 2.0 ** (math.floor(math.log2(v)) - bits)
    return math.floor(v / step + 1e-9) * step


def q_tint(v):
    return trunc_mantissa(v, 4)


def q_half(v):
    return trunc_mantissa(v, 10)


def q_u8(v):
    return math.floor(min(max(v, 0.0), 1.0) * 255 + 1e-6) / 255


def features(bindings):
    real = lambda s: bindings.get(s) is not None and not bindings[s].startswith("$")
    return {"reveal": real("revealMap"), "height": real("heightMap"), "detail": "detailMap" in bindings,
            "coal": COAL_SEMANTIC in bindings}


def layout(feat):
    """Constant index of each value, HLSL-packed in declaration order."""
    if feat["coal"]:
        return dict(COAL_LAYOUT)
    at, out = 0, {}

    def put(name, size):
        nonlocal at
        if at // 4 != (at + size - 1) // 4:
            at = (at + 3) // 4 * 4
        out[name] = at
        at += size

    for name, size in (("unused", 1), ("tint", 3), ("normal_strength", 1), ("gloss_lo", 1), ("gloss_hi", 1)):
        put(name, size)
    if feat["reveal"]:
        put("contrast", 1), put("exponent", 1), put("reveal_uv_scale", 2)
    if feat["height"]:
        put("displacement", 3)
    if feat["detail"]:
        put("detail_uv_scale", 2), put("detail_strength", 1)
    return out


def values(consts, feat):
    """The record's shader-read values from a material's constants."""
    at = layout(feat)
    c = lambda name, k=0: consts[at[name] + k]
    has = lambda name: name in at
    return {"tint_rgb": [q_tint(c("tint", k)) for k in range(3)],
            "normal_strength": q_u8(c("normal_strength")),
            "gloss_range": [q_half(c("gloss_lo")), q_half(c("gloss_hi"))],
            "blend_contrast": q_u8(c("contrast")) if has("contrast") else 0.0,
            "blend_exponent": q_u8(c("exponent")) if has("exponent") else 0.0,
            "reveal_uv_scale": [q_half(c("reveal_uv_scale", k)) for k in range(2)] if has("reveal_uv_scale") else [0.0, 0.0],
            "detail_uv_scale": [q_half(c("detail_uv_scale", k)) for k in range(2)] if has("detail_uv_scale") else [1.0, 1.0],
            "detail_strength": q_u8(c("detail_strength")) if has("detail_strength") else 0.0,
            "displacement_amount": q_half(3 * c("displacement", 2)) if has("displacement") else 0.0}


def load(package):
    package = Path(package)
    sectors = sorted((json.loads(p.read_text()) for p in (package / "capture" / "sectors").glob("*/sector.json")),
                     key=lambda s: s["sector"])
    doc = json.loads((package / "capture" / "terraingfx.json").read_text())
    bindings = {m["name"]: {b["engine_semantic"]: b["asset_name"] for b in m.get("bindings") or []}
                for m in doc["materials"]}
    ts_path = package / "capture" / "material_techsets.json"
    techsets = json.loads(ts_path.read_text())["materials"] if ts_path.is_file() else {}
    captured, consts = {}, {}
    for s in sectors:
        for L in s["layers"]:
            consts.setdefault(L["material"], L["constants_uninterpreted"]["values"])
            if L.get("runtime"):
                captured.setdefault(L["material"], L["runtime"])
    return sectors, bindings, techsets, captured, consts


def records(package):
    """{material: {"runtime": shader-read record fields, "provenance": str}} for every layer material."""
    sectors, bindings, techsets, captured, consts = load(package)
    by_techset, by_color = {}, {}
    for name, r in captured.items():
        if name in techsets:
            by_techset.setdefault(techsets[name]["techset"], []).append(r)
        by_color.setdefault(bindings[name].get("colorMap"), []).append(r)
    out = {}
    for name in consts:
        if name in captured:
            out[name] = {"runtime": captured[name], "provenance": "captured"}
            continue
        b = bindings[name]
        feat = features(b)
        rt = values(consts[name], feat)
        donors = by_techset.get(techsets.get(name, {}).get("techset"), [])
        if donors:
            flags = int(donors[0]["flags"], 16) & SHADER_FLAGS & ~0x8
            provenance = "rebuilt: technique set flags, constants"
            if not any(consts[name][1:7]):
                # The sand technique set keeps its values outside the constant
                # buffer the capture reads (its captured members do not rebuild
                # either); take a captured member's.
                rt = {f: donors[0][f] for f in FIELDS}
                provenance = "rebuilt: technique set flags and a captured member's values (empty constants)"
        else:
            if not techsets:
                raise FileNotFoundError("no capture/material_techsets.json: run read_bo4_terrain_techsets.py")
            flags = 0x1 | 0x2 | (0x4 if feat["reveal"] else 0) | (0x80 if feat["detail"] else 0)
            same = by_color.get(b.get("colorMap"), [])
            flags |= int(same[0]["flags"], 16) & 0x700 if same else 0
            provenance = "rebuilt: flags from bindings" + (" and the same colour map" if same else "") + ", constants"
        if b.get("glossMap") not in (None, "$white_gloss"):
            flags |= 0x8
        rt.update({"flags": "0x%X" % flags, "metal_rgb": [0.0, 0.0, 0.0]})
        out[name] = {"runtime": rt, "provenance": provenance}
    return out


def layer_runtime(layer, record):
    """A sector layer's record: the material's, with this sector's uv rows and weight slice."""
    rt = dict(record["runtime"])
    rt["uv_rows"] = layer["uv_matrix_2x4"]
    rt["weight_slice"] = layer["weight_source_slice"]
    return rt


def check(package):
    """Rebuild every captured record from its material; returns mismatching fields."""
    sectors, bindings, techsets, captured, consts = load(package)
    bad = []
    for name, r in captured.items():
        rebuilt = values(consts[name], features(bindings[name]))
        for f in FIELDS:
            a, b = rebuilt[f], r[f]
            a, b = (a, b) if isinstance(a, list) else ([a], [b])
            # Values the shader cannot read (no reveal map: contrast, exponent, reveal scale) are not compared.
            if f in ("blend_contrast", "blend_exponent", "reveal_uv_scale") and not int(r["flags"], 16) & 0x4:
                continue
            if f in ("detail_uv_scale", "detail_strength") and not int(r["flags"], 16) & 0x80:
                continue
            if any(abs(x - y) > 1e-6 for x, y in zip(a, b)):
                bad.append((name, f, a, b))
        gloss_off = bindings[name].get("glossMap") == "$white_gloss"
        if gloss_off == bool(int(r["flags"], 16) & 0x8):
            bad.append((name, "flags 0x8", bindings[name].get("glossMap"), r["flags"]))
    groups = {}
    for name, r in captured.items():
        if name in techsets:
            groups.setdefault(techsets[name]["techset"], set()).add(int(r["flags"], 16) & SHADER_FLAGS & ~0x8)
    bad += [("techset " + t, "flags", sorted(map(hex, f)), None) for t, f in groups.items() if len(f) > 1]
    return len(captured), bad


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("package", type=Path)
    args = parser.parse_args()
    n, bad = check(args.package)
    print(f"captured records rebuilt from their materials: {n - len({b[0] for b in bad})}/{n} exact")
    for row in bad:
        print("  mismatch", row)
    for name, r in sorted(records(args.package).items(), key=lambda kv: kv[1]["provenance"]):
        if r["provenance"] != "captured":
            print(f"  {name:45s} {r['runtime']['flags']:>6s} {r['provenance']}")


if __name__ == "__main__":
    main()
