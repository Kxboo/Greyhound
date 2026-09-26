"""Verify a BO4 terrain source package against its own data and the map's props.

Checks, per sector:
- Height padding: the grid is 32n+4 wide but only 32n+1 samples are used; on
  maps with relief at the far edge, rows/columns 32n+1..32n+3 repeat 32n, which
  places sample (0, 0) at the sector origin.
- Layer weights: BC4 slice k is nonzero in exactly the tiles whose layer mask
  has bit k+1 (the slice-to-layer mapping the package declares).
- Cutout: the declared bit addressing (sample (i, j) -> word (i >> 3, j >> 2),
  bit (i & 7) + 8 (j & 3)) must be more spatially coherent than bit-reversed or
  y-major packings. Polarity (set = solid) and addressing come from the
  terrain pixel shader, which discards where the bit is 0; the data check only
  guards the packing.
- Optional, with a placements `static_models.json`: small surface props must
  rest on the decoded height. Only props within 40 units of the surface count
  (maps have underground sections), and the declared mapping (rows = +Y,
  columns = +X, height scale 1) must beat every flipped/transposed/rescaled
  alternative. A rotated sector is tested after `world_aligned`, so the
  flipped and transposed readings include its other right-angle rotations.

Measured: zm_white (2 sectors) and zm_towers (1 sector) pass.
"""

# Support direct execution and the isolated packaged Python runtime.
import sys as _tool_sys
from pathlib import Path as _ToolPath
TOOLS_ROOT = next(p for p in _ToolPath(__file__).resolve().parents if (p / "tool_bootstrap.py").is_file())
_tool_sys.path.insert(0, str(TOOLS_ROOT))
import tool_bootstrap as _tool_bootstrap
_tool_bootstrap.activate(__file__)
REPO_ROOT = TOOLS_ROOT.parent
import argparse
import json
from pathlib import Path

import numpy as np

MASK_AGREEMENT = 0.99      # a tile or two can decode to all-zero weights
SURFACE_WINDOW, ON_SURFACE = 40.0, 1.5
MAX_PROP_WIDTH = 48.0      # one height under the prop


def decode_bc4(raw, width, height):
    """BC4_UNORM blocks -> float32 [0, 1] image."""
    blocks = np.frombuffer(raw, np.uint8).reshape(height // 4, width // 4, 8)
    r0, r1 = blocks[..., 0].astype(np.float32), blocks[..., 1].astype(np.float32)
    bits = np.zeros(blocks.shape[:2], np.uint64)
    for i in range(6):
        bits |= blocks[..., 2 + i].astype(np.uint64) << np.uint64(8 * i)
    index = np.stack([((bits >> np.uint64(3 * k)) & np.uint64(7)).astype(np.intp) for k in range(16)], -1)
    six = r0 > r1
    palette = np.empty(blocks.shape[:2] + (8,), np.float32)
    palette[..., 0], palette[..., 1] = r0, r1
    for k in range(2, 8):
        eight = ((8 - k) * r0 + (k - 1) * r1) / 7
        four = ((6 - k) * r0 + (k - 1) * r1) / 5 if k < 6 else np.full_like(r0, 0 if k == 6 else 255)
        palette[..., k] = np.where(six, eight, four)
    values = np.take_along_axis(palette, index, -1)
    return values.reshape(height // 4, width // 4, 4, 4).transpose(0, 2, 1, 3).reshape(height, width) / 255


def world_aligned(s, a, cells=False):
    """A grid indexed [local row, local col] -> the same grid indexed [world row (+Y), world col (+X)].

    A rotated sector (`local_to_world` in its sector.json: world = local . R + t
    with row vectors, R a right angle about Z) keeps its height, cutout and
    weight files as captured, in its own frame; the shader reaches them through
    a rotated sector uv. Anything that places them in the world goes through
    here. `a` is the used grid, square (32n+1 samples). Samples map to samples;
    with cells=True, cell (i, j), which spans samples i..i+1 and j..j+1, maps by
    its centre (the last row and column are not cells and stay padding).
    Unrotated sectors are returned as they are.
    """
    rot = s.get("local_to_world")
    if not rot:
        return a
    R = np.array(rot["rotation_rows"], np.int64)
    n = a.shape[0] - 1
    half = 0.5 if cells else 0.0
    wr, wc = np.meshgrid(np.arange(n + 1), np.arange(n + 1), indexing="ij")
    dx, dy = wc + half - n / 2, wr + half - n / 2
    # local = (world - t) . R^T
    col = np.rint(dx * R[0, 0] + dy * R[0, 1] + n / 2 - half).astype(np.int64)
    row = np.rint(dx * R[1, 0] + dy * R[1, 1] + n / 2 - half).astype(np.int64)
    return a[np.clip(row, 0, n), np.clip(col, 0, n)]


def load_sector(package, path):
    s = json.loads(path.read_text())
    width = s["height"]["width"]
    raw = np.fromfile(package / s["height"]["file"], "<u2").reshape(width, width).astype(float)
    return s, raw


def padding_check(s, samples):
    used = s["grid_samples"]
    edge = samples[used - 1]
    if np.all(samples == samples.flat[0]):
        return {"status": "uninformative_flat"}
    repeats = all(np.array_equal(samples[i], edge) and np.array_equal(samples[:, i], samples[:, used - 1])
                  for i in range(used, samples.shape[0]))
    varied = len(np.unique(edge)) > 1 or len(np.unique(samples[:, used - 1])) > 1
    return {"status": ("pass" if repeats else "fail") if varied else "uninformative_flat_edge",
            "padding_rows_repeat_last_used": repeats}


def weight_check(package, s):
    n, width = s["tiles_across"], s["layer_weights"]["width"]
    per = s["layer_weights"]["bytes_per_slice"]
    raw = (package / s["layer_weights"]["file"]).read_bytes()
    mask = np.fromfile(package / s["tile_layer_mask"]["file"], "<" + s["tile_layer_mask"].get("dtype", "u2")).reshape(n, n)
    rows, ok = [], True
    for k, slot in enumerate(s["layer_weights"]["slice_to_layer_slot"]):
        w = decode_bc4(raw[k * per:(k + 1) * per], width, width)
        # A tile spans 33x33 samples, sharing its far edge with the next tile.
        tiles = np.array([[w[ty * 32:ty * 32 + 33, tx * 32:tx * 32 + 33].max() > 0
                           for tx in range(n)] for ty in range(n)])
        agree = {b: float(np.mean(tiles == (((mask >> b) & 1) > 0))) for b in range(1, 16)}
        best = max(agree.values())
        passed = agree[slot] >= MASK_AGREEMENT and agree[slot] == best
        ok &= passed
        rows.append({"slice": k, "layer_slot": slot, "agreement": agree[slot], "best_other": max(
            v for b, v in agree.items() if b != slot), "weighted_tiles": int(tiles.sum()),
            "mask_tiles": int(((mask >> slot) & 1).sum()), "pass": passed})
    return {"status": "pass" if ok else "fail", "slices": rows}


def cutout_bits(words, order="x8_y4"):
    """(4n+1) x (8n+1) u32 words -> per-sample bits; the terrain pixel shader reads bit (i & 7) + 8 (j & 3)."""
    h, w = words.shape
    bits = ((words[:, :, None] >> np.arange(32, dtype=np.uint32)) & 1).astype(np.uint8)
    if order == "msb_first":
        bits = bits[:, :, ::-1]
    if order == "y4_x8":   # bit (j & 3) + 4 (i & 7)
        return bits.reshape(h, w, 8, 4).transpose(0, 3, 1, 2).reshape(h * 4, w * 8)
    return bits.reshape(h, w, 4, 8).transpose(0, 2, 1, 3).reshape(h * 4, w * 8)


def cutout_check(package, s, samples):
    """Declared bit addressing must be the most spatially coherent one; set = solid."""
    used, c = s["grid_samples"], s["cutout"]
    words = np.fromfile(package / c["file"], "<u4").reshape(c["height"], c["width"])

    def coherence(bits):
        return float((np.mean(bits[:, 1:] == bits[:, :-1]) + np.mean(bits[1:] == bits[:-1])) / 2)
    declared = cutout_bits(words)[:used, :used]
    alternatives = {o: coherence(cutout_bits(words, o)[:used, :used]) for o in ("msb_first", "y4_x8")}
    solid = declared.astype(bool)
    z = s["world_height_bias"] + samples[:used, :used] * s["height"]["scale"]
    report = {"solid_fraction": float(solid.mean()), "coherence": coherence(declared),
              "alternative_coherence": alternatives, "hole_samples": int((~solid).sum())}
    if solid.all():
        return {"status": "uninformative_no_holes", **report}
    report["median_height_hole"], report["median_height_solid"] = float(np.median(z[~solid])), float(np.median(z[solid]))
    ok = report["coherence"] > max(alternatives.values()) and report["solid_fraction"] > 0.5
    return {"status": "pass" if ok else "fail", **report}


def solid_samples(package, s):
    """Per-sample cutout bits under the declared addressing (True = drawn)."""
    c = s["cutout"]
    words = np.fromfile(package / c["file"], "<u4").reshape(c["height"], c["width"])
    return cutout_bits(words)[:s["grid_samples"], :s["grid_samples"]].astype(bool)


def surface_check(s, samples, rows, solid=None):
    """Props rest on the declared surface more often than on any flipped or rescaled one.

    A prop over a hole stands on whatever the hole makes room for, not on this
    sector: zm_white's sector 0 is a backdrop whose only holes are sector 1's
    footprint. So props over hole cells are left out, under each mapping's own
    reading of the cutout.
    """
    used, ups = s["grid_samples"], s["units_per_sample"]
    x0, y0 = s["world_xy_origin"]
    bias, scale = s["world_height_bias"], s["height"]["scale"]
    props = []
    for r in rows:
        if r.get("SplineInstanceIndex") is not None:
            continue
        lo = [r["BoundsMin"][c] for c in "XYZ"]; hi = [r["BoundsMax"][c] for c in "XYZ"]
        if hi[0] - lo[0] <= MAX_PROP_WIDTH and hi[1] - lo[1] <= MAX_PROP_WIDTH:
            props.append(((lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, lo[2]))
    props = np.array(props).reshape(-1, 3)

    def score(transpose=False, flip_x=False, flip_y=False, z_scale=1.0):
        u, v = (props[:, 0] - x0) / ups, (props[:, 1] - y0) / ups
        if flip_x: u = (used - 1) - u
        if flip_y: v = (used - 1) - v
        inside = (u >= 0) & (v >= 0) & (u <= used - 1) & (v <= used - 1)
        grid = samples.T if transpose else samples
        u, v = u[inside], v[inside]
        iu, iv = np.clip(np.floor(u).astype(int), 0, used - 2), np.clip(np.floor(v).astype(int), 0, used - 2)
        au, av = u - iu, v - iv
        h = (grid[iv, iu] * (1 - au) * (1 - av) + grid[iv, iu + 1] * au * (1 - av)
             + grid[iv + 1, iu] * (1 - au) * av + grid[iv + 1, iu + 1] * au * av)
        d = props[inside, 2] - (bias + h * scale * z_scale)
        if solid is not None:
            d = d[(solid.T if transpose else solid)[iv, iu]]
        near = d[np.abs(d) < SURFACE_WINDOW]
        return len(near), float(np.mean(np.abs(near) < ON_SURFACE)) if len(near) else 0.0

    declared_near, declared = score()
    alternatives = {f"transpose={t} flip_x={fx} flip_y={fy}": score(t, fx, fy)[1]
                    for t in (False, True) for fx in (False, True) for fy in (False, True) if (t, fx, fy) != (False, False, False)}
    alternatives.update({f"z_scale={z}": score(z_scale=z)[1] for z in (0.9, 1.1)})
    if declared_near < 100:
        return {"status": "uninformative_few_surface_props", "surface_props": declared_near}
    best_other = max(alternatives.values())
    return {"status": "pass" if declared > best_other else "fail", "surface_props": declared_near,
            "declared_on_surface_fraction": declared, "best_alternative_fraction": best_other,
            "alternatives": alternatives}


def verify(package, placements=None):
    package = Path(package)
    rows = json.loads(Path(placements).read_text()) if placements else None
    report = {"schema": "superterrain-bo4-terrain-verification-v1", "sectors": []}
    for path in sorted(package.glob("capture/sectors/sector_*/sector.json")):
        s, samples = load_sector(package, path)
        entry = {"sector": s["sector"], "height_padding": padding_check(s, samples),
                 "layer_weights": weight_check(package, s), "cutout": cutout_check(package, s, samples)}
        if rows is not None:
            used = s["grid_samples"]
            entry["surface_props"] = surface_check(s, world_aligned(s, samples[:used, :used]), rows,
                                                   world_aligned(s, solid_samples(package, s), cells=True))
        report["sectors"].append(entry)
    statuses = [c["status"] for e in report["sectors"] for k, c in e.items() if isinstance(c, dict)]
    report["status"] = "fail" if "fail" in statuses else "pass"
    (package / "terrain_verification.json").write_text(json.dumps(report, indent=1) + "\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("package", type=Path, help="package_bo4_terrain.py output folder")
    parser.add_argument("--placements", type=Path, help="Greyhound BO4 placements static_models.json for the same map")
    args = parser.parse_args()
    result = verify(args.package, args.placements)
    for e in result["sectors"]:
        print(f"sector {e['sector']}: " + ", ".join(f"{k} {v['status']}" for k, v in e.items() if isinstance(v, dict)))
    print("overall", result["status"])
    raise SystemExit(result["status"] != "pass")
