"""Assemble a whole BO4 map as one USD scene: every terrain sector with live materials, and model placements.

Layout under OUTPUT:

  <name>.usda                      root stage (small): /World/Terrain and /World/Placements, all payloads
  terrain/sector_NN/chunk_JJ_II.usda   one chunk of a sector: the native height grid over CHUNK x CHUNK
                                   quads (holes dropped) and its own MaterialX material
                                   (build_bo4_terrain_usd.build_material), holding only
                                   - the layers whose weights reach the chunk, and
                                   - the decals whose boxes reach it, translated from their shaders.
  terrain/sector_NN/weights/       the sector's layer weights, 16-bit PNG, shared by its chunks
  placements/placements.npz        instance arrays for write_bo4_placements_usd.py (run it with a
                                   Python that has pxr) to write placements/placements.usdc

--no-decals writes terrain-layer-only chunks beside the full ones
(chunk_JJ_II_terrain.usda, reports in reports_terrain/) and a root of their
own (--name). The decals are 4.3M of the whole map's 4.9M material nodes: more
than Blender holds on 16 GB, and they overflow Cycles' GPU (SVM) stack. Their
chunks share one material per sector, Terrain_sNN, holding all its layers (a
layer that is zero over a chunk changes nothing there), so a viewer builds 27
materials for the whole map rather than 388.

Every chunk is a payload, so a viewer opens the root instantly and loads the
chunks it needs. How sectors combine needs nothing extra: where a fine local
sector is solid, the quadrant sector under it is cut out (its cutout bits),
and the two surfaces meet within about 0.1 inch; both are simply loaded.
Sectors the package left out (rotated ones) are listed in the report.

Chunks are written as .usda; usd_crate.py converts them to binary .usdc and
repoints the root.
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
import time
from pathlib import Path

import numpy as np

from build_bo4_terrain_cast import ALWAYS_ONE, ALWAYS_ZERO, load_grid, load_weights
from build_bo4_terrain_usd import build_material, select_decals, terrain_mesh, write_usda
from bo4_decal_composite import DecalScene
from bo4_terrain_records import layer_runtime, records


def sector_rows(package):
    return sorted((json.loads(p.read_text()) for p in (package / "capture" / "sectors").glob("*/sector.json")),
                  key=lambda s: s["sector"])


def weight_reach(package, s, layers, chunk):
    """{slot: bool array [chunk row, chunk col]}: where each layer's weight is above zero.

    A chunk's quads read weight texels i0-1 .. i1+1 (bilinear), so each
    chunk's window is grown by one texel. A layer that is zero over a chunk
    changes nothing there (its active term is 0), so leaving it out is exact.
    """
    lw = s["layer_weights"]
    base = lw.get("array_slice_base", 0)
    n = s["grid_samples"] - 1
    count = -(-n // chunk)
    out = {}
    for L in layers:
        ws = L["runtime"]["weight_slice"]
        if ws in (ALWAYS_ONE, ALWAYS_ZERO):
            out[L["slot"]] = np.full((count, count), ws == ALWAYS_ONE)
            continue
        k = ws - base
        if not 0 <= k < lw["slices"]:
            raise ValueError(f"sector {s['sector']} slot {L['slot']}: weight slice {ws} outside the file")
        w = load_weights(package, s, k)
        reach = np.zeros((count, count), bool)
        for cj in range(count):
            for ci in range(count):
                j0, i0 = cj * chunk, ci * chunk
                reach[cj, ci] = w[max(j0 - 1, 0):j0 + chunk + 2, max(i0 - 1, 0):i0 + chunk + 2].max() > 0
        out[L["slot"]] = reach
    return out


def build_sector(package, output, s, table, decal_scene, chunk, log, suffix=""):
    """Write one sector's chunks; returns their report rows. Without a decal_scene the chunks
    have no decals and share one material, Terrain_sNN, with every layer of the sector."""
    ox, oy = s["world_xy_origin"]
    ups, n = s["units_per_sample"], s["grid_samples"] - 1
    layers = [dict(L, runtime=layer_runtime(L, table[L["material"]])) for L in sorted(s["layers"], key=lambda r: r["slot"])]
    heights, solid = load_grid(package, s)
    shared = decal_scene is None
    reach = None if shared else weight_reach(package, s, layers, chunk)
    folder = output / "terrain" / ("sector_%02d" % s["sector"])
    (folder / "weights").mkdir(parents=True, exist_ok=True)
    if shared:
        sector_material = build_material(package, folder, s, layers, [], None, ".")
    rows = []
    count = -(-n // chunk)
    for cj in range(count):
        for ci in range(count):
            i0, j0 = ci * chunk, cj * chunk
            i1, j1 = min(i0 + chunk, n), min(j0 + chunk, n)
            box = (ox + i0 * ups, oy + j0 * ups, ox + i1 * ups, oy + j1 * ups)
            if not solid[j0:j1, i0:i1].any():
                continue
            started = time.time()
            geometry = terrain_mesh(s, heights, solid, box)
            z = geometry["positions"][:, 2]
            name = "chunk_%02d_%02d" % (cj, ci)
            if shared:
                active, decals = layers, []
                g, outputs, report, decal_report = sector_material
                material = "Terrain_s%02d" % s["sector"]
            else:
                active = [L for L in layers if reach[L["slot"]][cj, ci]]
                decals = select_decals(decal_scene, box, float(z.min()), float(z.max()), geometry)
                g, outputs, report, decal_report = build_material(package, folder, s, active, decals, decal_scene, ".")
                material = "Terrain_s%02d_%s" % (s["sector"], name)
            path = folder / (name + suffix + ".usda")
            write_usda(path, material, geometry, g, outputs)
            lo, hi = geometry["positions"].min(0), geometry["positions"].max(0)
            row = {"sector": s["sector"], "chunk": name, "file": path.relative_to(output).as_posix(),
                   "box": list(box), "extent": [lo.tolist(), hi.tolist()], "vertices": int(len(geometry["positions"])),
                   "triangles": int(len(geometry["faces"])), "layers": len(active), "decals": len(decals),
                   "untranslated_decals": [d["index"] for d in decal_report if "untranslated" in d],
                   "material_nodes": len(g.reachable(list(outputs.values()))), "seconds": round(time.time() - started, 1)}
            rows.append(row)
            log(row)
    return rows


def write_root(output, name, chunks, placements, excluded):
    """The root stage: one payload per chunk and one for the placements."""
    lines = ['#usda 1.0', '(', '    defaultPrim = "World"', '    metersPerUnit = 0.0254', '    upAxis = "Z"',
             '    doc = "BO4 map: terrain chunks with live MaterialX materials and model placements '
             '(build_bo4_map_usd.py)"', ')', '', 'def Xform "World" (', '    kind = "assembly"', ')', '{',
             '    def Scope "Terrain"', '    {']
    by_sector = {}
    for c in chunks:
        by_sector.setdefault(c["sector"], []).append(c)
    for sector, rows in sorted(by_sector.items()):
        lines += ['        def Xform "Sector_%02d" (' % sector, '            kind = "group"', '        )', '        {']
        for c in rows:
            lo, hi = c["extent"]
            lines += ['            def Xform "%s" (' % c["chunk"].capitalize(),
                      '                kind = "component"',
                      '                prepend payload = @./%s@</World>' % c["file"], '            )', '            {',
                      '                float3[] extentsHint = [(%r, %r, %r), (%r, %r, %r)]' % (*lo, *hi),
                      '            }']
        lines += ['        }']
    lines += ['    }']
    if placements:
        lines += ['', '    def Xform "Placements" (', '        kind = "group"',
                  '        prepend payload = @./%s@</Placements>' % placements, '    )', '    {', '    }']
    lines += ['}', '']
    if excluded:
        lines.insert(6, '    customLayerData = {')
        lines.insert(7, '        string bo4_excluded_sectors = "%s"' % ", ".join(str(e) for e in excluded))
        lines.insert(8, '    }')
    (output / (name + ".usda")).write_text("\n".join(lines), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("package", type=Path, help="package_bo4_terrain.py output (probe v46 or newer)")
    parser.add_argument("output", type=Path)
    parser.add_argument("--sectors", type=int, nargs="*", help="only these sectors (default: all packaged)")
    parser.add_argument("--chunk", type=int, default=256, help="chunk size in grid quads (default 256)")
    parser.add_argument("--name", default="map")
    parser.add_argument("--root-only", action="store_true",
                        help="only rewrite the root from the chunk reports already written")
    parser.add_argument("--placements", help="placements file relative to OUTPUT for the root "
                                             "(default placements/placements.usdc when it exists)")
    parser.add_argument("--no-decals", action="store_true",
                        help="terrain layers only, as chunk_JJ_II_terrain.usda beside the full chunks")
    args = parser.parse_args()
    package, output = args.package, args.output
    output.mkdir(parents=True, exist_ok=True)
    suffix = "_terrain" if args.no_decals else ""
    reports = output / ("reports" + suffix)
    reports.mkdir(exist_ok=True)
    sectors = sector_rows(package)
    if not args.root_only:
        table = records(package)
        decal_scene = None if args.no_decals else DecalScene(package)
        for s in sectors:
            if args.sectors and s["sector"] not in args.sectors:
                continue
            path = reports / ("sector_%02d.jsonl" % s["sector"])
            with path.open("w") as f:
                def log(row):
                    f.write(json.dumps(row) + "\n")
                    f.flush()
                    print(f"sector {row['sector']} {row['chunk']}: {row['vertices']} vertices, {row['layers']} layers, "
                          f"{row['decals']} decals, {row['material_nodes']} nodes, {row['seconds']} s", flush=True)
                build_sector(package, output, s, table, decal_scene, args.chunk, log, suffix)
    chunks = [json.loads(line) for p in sorted(reports.glob("sector_*.jsonl")) for line in p.read_text().splitlines()]
    for c in chunks:
        crate = Path(c["file"]).with_suffix(".usdc")
        if (output / crate).is_file():
            c["file"] = crate.as_posix()
    audit = package / "package_audit.json"
    excluded = []
    if audit.is_file():
        excluded = [e.get("sector") for e in json.loads(audit.read_text()).get("excluded_sectors", [])]
    placements = args.placements or ("placements/placements.usdc"
                                     if (output / "placements" / "placements.usdc").is_file() else None)
    write_root(output, args.name, chunks, placements, excluded)
    print(json.dumps({"chunks": len(chunks), "vertices": sum(c["vertices"] for c in chunks),
                      "material_nodes": sum(c["material_nodes"] for c in chunks), "excluded_sectors": excluded,
                      "placements": placements}, indent=1))


if __name__ == "__main__":
    main()
