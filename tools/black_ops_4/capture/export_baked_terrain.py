"""Build BO4 terrain CAST sections with volume decals composited into their maps.

This is the small-map alternative to the separate BO3 decal asset export. It
requires a full BO4 terraingfx probe and keeps the source and packaged evidence
beside the models. Large maps fail preflight before any shader bake begins.
"""
from __future__ import annotations

# The bundled Python runtime is isolated and does not add the script directory.
import sys as _tool_sys
from pathlib import Path as _ToolPath
TOOLS_ROOT = next(p for p in _ToolPath(__file__).resolve().parents if (p / "tool_bootstrap.py").is_file())
_tool_sys.path.insert(0, str(TOOLS_ROOT))
import tool_bootstrap as _tool_bootstrap
_tool_bootstrap.activate(__file__)

import argparse
import json
import math
import re
from pathlib import Path

from bo4_decal_composite import DecalScene
from bo4_terrain_gbuffer import TerrainScene
from build_bo4_terrain_cast import build_emulated, load_grid
from package_bo4_terrain import package
from bo4_terrain_validation import require_runtime_layers


def write_placement_map(path: Path, models):
    """Place baked meshes, which already contain world coordinates, at origin."""
    names = [model['name'] for model in models]
    if (not names or len(set(names)) != len(names) or
            any(not re.fullmatch(r'[A-Za-z0-9_-]+', name) for name in names)):
        raise ValueError('Terrain placements require unique model asset names')
    lines = ['iwmap 4', '"000_Global" flags active', '// entity 0', '{',
             '"classname" "worldspawn"', '}']
    for index, name in enumerate(names, 1):
        lines.extend([f'// entity {index}', '{', '"classname" "misc_model"',
                      f'"model" "{name}"', '"origin" "0 0 0"',
                      '"angles" "0 0 0"', '"modelscale" "1"', '}'])
    Path(path).write_text('\n'.join(lines) + '\n', encoding='utf8')


def map_identity(source):
    """Use the captured name hash so different maps cannot share model assets.

    Keep the identifier decimal and stable even when the name database changes.
    """
    for word in source.get("header_words", []):
        if int(str(word["header_offset"]), 0) == 0:
            value = int(str(word["u64"]), 0) & 0x0FFFFFFFFFFFFFFF
            if value:
                return str(value)
    match = re.fullmatch(r"terraingfx_([0-9a-fA-F]+)", source.get("asset", {}).get("name", ""))
    if match:
        value = int(match[1], 16) & 0x0FFFFFFFFFFFFFFF
        if value:
            return str(value)
    raise ValueError("BO4 terrain capture is missing its map identity; capture the terrain again")


def plan(package_root: Path, chunk_cells: int, texels_per_inch: float, max_models: int,
         map_id: str | None = None):
    sectors = sorted((json.loads(p.read_text(encoding="utf8")) for p in
                      (package_root / "capture" / "sectors").glob("*/sector.json")),
                     key=lambda row: row["sector"])
    if not sectors:
        raise ValueError("The BO4 probe contains no packaged terrain sectors")
    audit_file = package_root / "package_audit.json"
    if audit_file.is_file():
        excluded = json.loads(audit_file.read_text(encoding="utf8")).get("excluded_sectors", [])
        if excluded:
            raise ValueError(f"The BO4 package excludes {len(excluded)} terrain sectors; export the raw source for review")
    prefix = f"bo4_terrain_{map_id}" if map_id is not None else "bo4_terrain"
    jobs = []
    for sector in sectors:
        index = sector["sector"]
        if sector.get("local_to_world"):
            raise ValueError(f"BO4 sector {index} is rotated; the decal shader bake cannot yet place it correctly")
        n = int(sector["grid_samples"]) - 1
        ups = float(sector["units_per_sample"])
        if n <= 0 or not math.isfinite(ups) or ups <= 0:
            raise ValueError(f"BO4 sector {index} has invalid grid dimensions")
        cells = min(chunk_cells, max(1, int(1024 / (ups * texels_per_inch))))
        if cells < 2:
            raise ValueError(f"BO4 sector {index} exceeds the 1024 texel model texture limit")
        ox, oy = sector["world_xy_origin"]
        for j in range(0, n, cells):
            for i in range(0, n, cells):
                i1, j1 = min(i + cells, n), min(j + cells, n)
                jobs.append({"sector": index, "grid": [i, j, i1, j1],
                             "box": [ox + i * ups, oy + j * ups,
                                     ox + i1 * ups, oy + j1 * ups],
                             "name": f"{prefix}_s{index:02d}_x{i:04d}_y{j:04d}"})
    if len(jobs) > max_models:
        raise ValueError(f"This BO4 map needs {len(jobs)} terrain sections at the safe texture size "
                         f"(limit {max_models}). Use Terrain source capture for a large-map workflow")
    return jobs


def export(probe: Path, output: Path, chunk_cells=128, texels_per_inch=0.5, max_models=64,
           progress: Path | None = None):
    probe, output = probe.resolve(), output.resolve()
    if chunk_cells < 2 or texels_per_inch <= 0 or max_models < 1:
        raise ValueError("Invalid BO4 terrain bake limits")
    if not probe.is_file():
        raise FileNotFoundError(f"Missing BO4 terrain probe: {probe}")
    source = json.loads(probe.read_text(encoding="utf8"))
    map_id = map_identity(source)
    decal_status = source.get("volume_decals", {}).get("status")
    if decal_status not in ("captured", "none"):
        raise ValueError(f"BO4 decal capture is {decal_status or 'missing'}; cannot certify a decal bake")
    package_root = output / "package"
    package(probe, package_root)
    sectors = [json.loads(p.read_text(encoding="utf8")) for p in
               sorted((package_root / "capture" / "sectors").glob("*/sector.json"))]
    # Validate every sector before starting a potentially long bake. Older
    # captures assumed per-sector weight slices started at zero; later sectors
    # could be missing or incorrectly reuse an earlier sector's runtime data.
    require_runtime_layers(sectors)
    jobs = plan(package_root, chunk_cells, texels_per_inch, max_models, map_id)
    if progress:
        progress.write_text("10", encoding="ascii")
    scene = DecalScene(package_root) if decal_status == "captured" else None
    models_root = output / "models"
    models_root.mkdir()
    results = []
    current_sector = None
    for done, job in enumerate(jobs, 1):
        if current_sector != job["sector"]:
            current_sector = job["sector"]
            terrain = TerrainScene(package_root, current_sector)
            solid = load_grid(package_root, terrain.sector)[1]
        i, j, i1, j1 = job["grid"]
        if not solid[j:j1, i:i1].any():
            continue
        folder = models_root / job["name"]
        report = build_emulated(package_root, folder, current_sector, job["box"],
                                texels_per_inch, job["name"], 1, decals=scene is not None,
                                terrain_scene=terrain, decal_scene=scene, solid_grid=solid)
        results.append({"name": job["name"], "sector": current_sector,
                        "grid": job["grid"], "model": (folder / report["cast"]).relative_to(output).as_posix(),
                        "report": (folder / f'{job["name"]}.json').relative_to(output).as_posix(),
                        "decals_drawn": report["decals_drawn"]})
        print(f"BO4 baked terrain {done}/{len(jobs)}: {job['name']} "
              f"({report['decals_drawn']} decals)", flush=True)
        if progress:
            progress.write_text(str(10 + int(85 * done / len(jobs))), encoding="ascii")
    if not results:
        raise ValueError("The BO4 terrain source contains no solid model sections")
    write_placement_map(output / 'terrain.map', results)
    try:
        source_probe = probe.relative_to(output).as_posix()
    except ValueError:
        source_probe = str(probe)
    manifest = {"schema": "greyhound-bo4-baked-terrain-v1", "status": "complete",
                "source_asset": source["asset"]["name"], "map_id": map_id,
                "decals_baked": True, "captured_decals": len(scene.decals) if scene else 0,
                "model_count": len(results),
                "texels_per_inch": texels_per_inch, "subdivide": 1, "models": results,
                "source_probe": source_probe,
                "source_package": "package", "placement_map": "terrain.map"}
    (output / "terrain_export.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf8")
    (output / "README.txt").write_text(
        f"BO4 terrain: {len(results)} CAST models with volume decals baked into their textures.\n"
        "Keep each model with its _images and _mat_info folders. terrain_export.json lists every model and source sector.\n"
        "terrain.map places every section at origin, angles 0 0 0, scale 1; the meshes already contain world coordinates.\n"
        "Convert/register BO3 model assets using the listed model names. Convert CAST centimeters to game inches once during model conversion.\n"
        "The source probe and package remain here for review. No BO3 decal transfer is needed.\n",
        encoding="utf8")
    if progress:
        progress.write_text("100", encoding="ascii")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("probe", type=Path, help="full BO4 terraingfx_probe.json")
    parser.add_argument("output", type=Path, help="reserved new terrain export directory")
    parser.add_argument("--chunk-cells", type=int, default=128)
    parser.add_argument("--texels-per-inch", type=float, default=0.5)
    parser.add_argument("--max-models", type=int, default=64)
    parser.add_argument("--progress", type=Path)
    args = parser.parse_args()
    print(json.dumps(export(args.probe, args.output, args.chunk_cells,
                            args.texels_per_inch, args.max_models, args.progress), indent=2))
