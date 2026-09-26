"""BO4 volume decals: the GfxWorld records, the decal pass render state, and the
220-byte records the decal pixel shaders read.

GfxWorld +0x590 holds the count and +0x598 the array; each GfxVolumeDecal is 216
bytes (atian-cod-tools' T8 GfxWorld layout, confirmed field by field against the
decal pixel shaders on zm_towers):

  +0x00 u64 id                  +0x08 u8 hidden
  +0x0C localToWld: X, Y, Z axes and origin (4 x vec3, unit axes)
  +0x3C wldToLocal (4 x vec3): row k is world component k's contribution to the
        local coordinates, row 3 the translation; local = world @ M + t
  +0x6C halfExtents             +0x78 edgeFeather (per axis, 0..1)
  +0x84 reveal atlas rect: offset xy, size zw in the shared reveal texture
  +0x94 u corners, +0xA4 v corners (vec4 each; see decal_uv)
  +0xB8 material                +0xC0 forward material
  +0xC8 u32 draw priority, 1-21 on zm_towers. The engine sorts each
        per-frame draw list by it, descending, then by material pointer
        ascending. If draw calls follow the list, priority 1 draws last, on
        top. Ties have no fixed order.
                                +0xCC target name
  +0xD0 f32 cos(angle threshold)

The G-buffer pass's blend state is one engine word per render target, laid out
(matched against every ID3D11BlendState live on zm_towers):
src 1-4, op 5-7 (0 = blending off), dst 8-11, srcA 12-15, opA 16-18 (0 = keep
destination alpha), dstA 19-22, write mask 23-26; D3D11 enum values.
"""
import struct

import numpy as np

DECAL_BYTES = 216
GPU_RECORD_BYTES = 220

BLEND = {1: "ZERO", 2: "ONE", 3: "SRC_COLOR", 4: "INV_SRC_COLOR", 5: "SRC_ALPHA", 6: "INV_SRC_ALPHA",
         7: "DEST_ALPHA", 8: "INV_DEST_ALPHA", 9: "DEST_COLOR", 10: "INV_DEST_COLOR", 11: "SRC_ALPHA_SAT",
         14: "BLEND_FACTOR", 15: "INV_BLEND_FACTOR"}
BLEND_OP = {1: "ADD", 2: "SUBTRACT", 3: "REV_SUBTRACT", 4: "MIN", 5: "MAX"}


def parse_decals(raw):
    """Decode every 216-byte GfxVolumeDecal."""
    out = []
    for i in range(len(raw) // DECAL_BYTES):
        rec = raw[i * DECAL_BYTES:(i + 1) * DECAL_BYTES]
        f = lambda off, n: [float(x) for x in struct.unpack_from(f"<{n}f", rec, off)]
        l2w, w2l = f(0x0C, 12), f(0x3C, 12)
        out.append({
            "index": i, "id": f"0x{struct.unpack_from('<Q', rec, 0)[0]:016X}", "hidden": rec[8],
            "axes": [l2w[0:3], l2w[3:6], l2w[6:9]], "origin": l2w[9:12],
            "world_to_local": {"matrix": [w2l[0:3], w2l[3:6], w2l[6:9]], "translation": w2l[9:12]},
            "half_extents": f(0x6C, 3), "edge_feather": f(0x78, 3), "atlas_rect": f(0x84, 4),
            "u_corners": f(0x94, 4), "v_corners": f(0xA4, 4),
            "material": f"0x{struct.unpack_from('<Q', rec, 0xB8)[0]:X}",
            "forward_material": f"0x{struct.unpack_from('<Q', rec, 0xC0)[0]:X}",
            "priority": struct.unpack_from("<I", rec, 0xC8)[0],
            "target_name": struct.unpack_from("<I", rec, 0xCC)[0],
            "angle_threshold_cos": f(0xD0, 1)[0]})
    return out


def decode_blend_word(word):
    """One render target of the engine's pass state word."""
    field = lambda shift, bits: (word >> shift) & ((1 << bits) - 1)
    op, op_alpha = field(5, 3), field(16, 3)
    return {"word": f"0x{word:08X}", "enable": op != 0 and not word >> 31,
            "src": BLEND.get(field(1, 4), field(1, 4)), "dst": BLEND.get(field(8, 4), field(8, 4)),
            "op": BLEND_OP.get(op, "OFF"),
            "src_alpha": BLEND.get(field(12, 4), field(12, 4)) if op_alpha else "ZERO",
            "dst_alpha": BLEND.get(field(19, 4), field(19, 4)) if op_alpha else "ONE",
            "op_alpha": BLEND_OP.get(op_alpha, "ADD"), "write_mask": field(23, 4)}


def decode_d3d11_packed(hex_bytes):
    """d3d11.dll's packed D3D11_BLEND_DESC (the blend state object's +0xA8), to cross-check."""
    raw = bytes.fromhex(hex_bytes)
    head = struct.unpack_from("<I", raw, 0)[0]
    rts = []
    for i in range(8):
        w = struct.unpack_from("<I", raw, 4 + 8 * i)[0]
        rts.append({"enable": bool(w & 1), "src": BLEND.get((w >> 2) & 31), "dst": BLEND.get((w >> 7) & 31),
                    "op": BLEND_OP.get((w >> 12) & 7), "src_alpha": BLEND.get((w >> 15) & 31),
                    "dst_alpha": BLEND.get((w >> 20) & 31), "op_alpha": BLEND_OP.get((w >> 25) & 7),
                    "write_mask": w >> 28})
    return {"alpha_to_coverage": bool(head & 1), "independent": bool(head & 2), "rt": rts}


def gpu_record(decal, depth_normal=False):
    """The 220-byte record the decal pixel shaders load from t21.

    +0/+16/+32 axis * half extent, +48 origin (w 1); +64..+127 world-to-local
    as a column-major 4x4 scaled by 1/half extent; +128 feather xyz and w = 1
    to take the surface normal from depth derivatives instead of the G-buffer;
    +144 tint (1, 1, 1, 1); +160 atlas rect; +176 u corners; +192 v corners;
    +208 (1, 0); +216 cos(angle threshold).

    Checked against 311 records live on zm_towers: every byte matches, except
    that the engine inverts the matrix at +64 itself (float rounding apart),
    and +128.w was 0 on all of them.
    """
    he = np.array(decal["half_extents"], np.float32)
    axes = np.array(decal["axes"], np.float32)
    matrix = np.array(decal["world_to_local"]["matrix"], np.float32)
    t = np.array(decal["world_to_local"]["translation"], np.float32)
    out = bytearray(GPU_RECORD_BYTES)
    for k in range(3):
        struct.pack_into("<4f", out, 16 * k, *(axes[k] * he[k]), 0.0)
    struct.pack_into("<4f", out, 48, *decal["origin"], 1.0)
    # Column k (world component k) holds matrix[k][i] / he[i] for local axis i.
    for k in range(3):
        struct.pack_into("<4f", out, 64 + 16 * k, *(matrix[k] / he), 0.0)
    struct.pack_into("<4f", out, 112, *(t / he), 1.0)
    struct.pack_into("<4f", out, 128, *decal["edge_feather"], 1.0 if depth_normal else 0.0)
    struct.pack_into("<4f", out, 144, 1.0, 1.0, 1.0, 1.0)
    struct.pack_into("<4f", out, 160, *decal["atlas_rect"])
    struct.pack_into("<4f", out, 176, *decal["u_corners"])
    struct.pack_into("<4f", out, 192, *decal["v_corners"])
    struct.pack_into("<2f", out, 208, 1.0, 0.0)
    struct.pack_into("<f", out, 216, decal["angle_threshold_cos"])
    return bytes(out)


def world_to_local(decal, points):
    """Local decal coordinates in [-1, 1]^3 inside the volume, for (N, 3) world points."""
    matrix = np.array(decal["world_to_local"]["matrix"], np.float64)
    t = np.array(decal["world_to_local"]["translation"], np.float64)
    he = np.array(decal["half_extents"], np.float64)
    return (points @ matrix + t) / he


def footprint(decal):
    """World-space axis-aligned bounds of the decal volume."""
    axes = np.array(decal["axes"]) * np.array(decal["half_extents"])[:, None]
    reach = np.abs(axes).sum(0)
    origin = np.array(decal["origin"])
    return origin - reach, origin + reach
