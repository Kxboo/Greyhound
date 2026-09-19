"""Cross-check BO4 map layout references against Greyhound's bounded capture.

No live process reads, and no CW decoder imports. This is an evidence report,
not a claim that referenced brush meshes or entity properties were all dumped.
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
import hashlib
import json
import math
import struct
from pathlib import Path

REF = "https://github.com/ate47/atian-cod-tools/blob/main/src/core/acts/tools/fastfile/handlers/bo4/"


def audit(root):
    doc = json.loads((root / "world_pools_probe.json").read_text())
    if doc["schema"] != "greyhound-bo4-world-pool-probe-v1" or not doc["write_success"]:
        raise ValueError("Unsupported or incomplete capture")
    pools = {r["pool_index"]: r for r in doc["pools"]}
    result = {"schema": "greyhound-bo4-world-mapping-audit-v1", "observations": [],
              "probe_sha256": hashlib.sha256((root / "world_pools_probe.json").read_bytes()).hexdigest()}
    for index, size in [(11, 728), (12, 96), (13, 96), (14, 6832), (118, 32)]:
        row = pools[index]
        if row["asset_size"] != size or not row.get("active_count_matches_directory"):
            raise ValueError("Reference size or allocation differs for pool " + str(index))
        result["observations"].append({"pool_index": index, "size": size,
            "loaded": row["loaded"], "name_candidates": [a["name_hash_candidate"] for a in row["assets"]]})
    def read_header(index):
        row = pools[index]
        if len(row["assets"]) != 1:
            raise ValueError("Ambiguous map asset")
        offset = row["assets"][0]["header_offset"]
        return (root / row["file"]).read_bytes()[offset:offset+row["asset_size"]]
    def target(index, offset):
        entries = pools[index]["assets"][0]["targets"]
        item = next((r for r in entries if int(r["field_offset"], 16) == offset), None)
        return (root/item["file"]).read_bytes() if item else None
    gfx = read_header(14)
    basename = target(14, 0x10)
    if not basename:
        raise ValueError("Missing basename sample")
    name = basename.split(b"\0", 1)[0].decode("ascii")
    bounds = struct.unpack_from("<6f", gfx, 0x190)
    if not all(math.isfinite(v) for v in bounds) or not all(bounds[i] <= bounds[i+3] for i in range(3)):
        raise ValueError("Invalid reference bounds")
    result["gfxworld_reference_check"] = {
        "reference": REF+"bo4_unlinker_map_gfx.cpp", "basename": name,
        "surface_count": struct.unpack_from("<I", gfx, 0x18)[0],
        "brush_model_count": struct.unpack_from("<I", gfx, 0x180)[0],
        "static_model_count": struct.unpack_from("<I", gfx, 0x1bc)[0],
        "volume_decal_count": struct.unpack_from("<I", gfx, 0x590)[0],
        "bounds": bounds, "scope": "Header values plus basename sample; counts are not decoded geometry"}
    entities = read_header(118)
    count = struct.unpack_from("<Q", entities, 0x10)[0]
    sample = target(118, 0x18)
    if not sample:
        raise ValueError("Missing entity array sample")
    rows = []
    for i in range(min(count, len(sample)//48)):
        off = i*48
        properties = struct.unpack_from("<I", sample, off)[0]
        model = struct.unpack_from("<i", sample, off+16)[0]
        origin = struct.unpack_from("<3f", sample, off+24)
        angles = struct.unpack_from("<3f", sample, off+36)
        if not all(math.isfinite(v) for v in (*origin, *angles)):
            raise ValueError("Nonfinite entity transform")
        rows.append({"index": i, "property_count": properties,
                     "model_index": model, "origin": origin, "angles": angles})
    result["entity_reference_check"] = {"reference": REF+"bo4_unlinker_map.hpp",
        "declared_count": count, "sampled_complete_records": len(rows), "stride": 48, "runtime_origin_offset": 24, "runtime_angles_offset": 36,
        "layout_note": "External offsets 20/32 superseded by full BO4 runtime cross-check",
        "sample_records": rows, "property_values_captured": False}
    result["unfinished"] = ["Full entity arrays and property strings",
                            "Clipmap model/brush/plane decoding and ownership",
                            "Complete model and decal arrays",
                            "Greyhound BO4-to-brush-pipeline normalization"]
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path)
    args = parser.parse_args()
    result = audit(args.capture)
    (args.capture / "world_mapping_audit.json").write_text(json.dumps(result, indent=2)+"\n")
    print(json.dumps(result["gfxworld_reference_check"], indent=2))
    print("Entity records checked:", result["entity_reference_check"]["sampled_complete_records"])
