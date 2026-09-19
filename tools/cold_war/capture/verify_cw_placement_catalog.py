"""Audit a CW placement run against its saved bytes; no game process required."""

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


def audit(root, baseline=None):
    root = Path(root).resolve()
    load = lambda name: json.loads((root / name).read_text(encoding="utf-8"))
    report = load("non_static_report.json")
    assert report["complete"], "Capture reported incomplete"
    sources = {}
    for directory in (root / "diagnostics/non_static").iterdir():
        evidence = json.loads((directory / "evidence.json").read_text())
        assert all(v["status"] in ("unchanged", "empty") for v in evidence.get("verifications", []))
        blocks = []
        for read in evidence["reads"]:
            if read["status"] != "captured":
                assert read["status"] == "reused_file", read
                continue
            name = read["file"]
            if name in evidence["storage"]:
                entry = evidence["storage"][name]
                with (directory / entry["file"]).open("rb") as stream:
                    stream.seek(entry["offset"])
                    data = stream.read(entry["bytes"])
            else:
                data = (directory / name).read_bytes()
            assert len(data) == read["requested_bytes"]
            blocks.append((int(read["address"], 16), data))
        sources[directory.name] = blocks

    def original(source, address, size):
        address = int(address, 16) if isinstance(address, str) else address
        for base, data in sources[source]:
            if base <= address and address + size <= base + len(data):
                return data[address-base:address-base+size]
        raise AssertionError(("missing source bytes", source, hex(address), size))

    entities = {}
    groups = list((root / "entities").glob("*/*.json"))
    for file in groups:
        for entity in json.loads(file.read_text()):
            assert entity["EntityId"] not in entities
            entities[entity["EntityId"]] = entity
            record = original(file.parent.name, entity["record_address"], 48)
            assert list(struct.unpack_from("<3f", record, 24)) == entity["record_vector_candidates"][0]
            assert list(struct.unpack_from("<3f", record, 36)) == entity["record_vector_candidates"][1]
    assert len(entities) == report["entity_count"]
    models = load("non_static_models.json")
    for row in models:
        entity = entities[row["SourceEntityId"]]
        assert (root / row["SourceEntityFile"]).is_file()
        assert list(row["Position"][k] for k in "XYZ") == entity["record_vector_candidates"][0]
        assert list(row["SourceAngles"][k] for k in "XYZ") == entity["record_vector_candidates"][1]
        pitch, yaw, roll = [math.radians(x)/2 for x in entity["record_vector_candidates"][1]]
        cp, sp, cy, sy, cr, sr = math.cos(pitch), math.sin(pitch), math.cos(yaw), math.sin(yaw), math.cos(roll), math.sin(roll)
        expected = (sr*cp*cy-cr*sp*sy, cr*sp*cy+sr*cp*sy, cr*cp*sy-sr*sp*cy, cr*cp*cy+sr*sp*sy)
        assert all(abs(row["RotationQuaternion"][key]-v) < 1e-12 for key, v in zip("XYZW", expected))
    by_class = [r for file in (root / "non_static_models").glob("*.json") for r in json.loads(file.read_text())]
    assert sorted(by_class, key=lambda x: x["SourceEntityId"]) == sorted(models, key=lambda x: x["SourceEntityId"])
    assert len(models) == report["model_placements"]

    fx = load("fx_placement_candidates.json")
    for row in fx:
        raw = original("level_fx", row["RecordAddress"], 80)
        assert bytes.fromhex(row["RawRecordHex"]) == raw
        assert row["CandidatePosition"] == list(struct.unpack_from("<3f", raw, 8))
        assert row["CandidateAngles"] == list(struct.unpack_from("<3f", raw, 20))
        assert row["StructuralValidation"]
    lights = load("light_placement_candidates.json")
    for row in lights:
        raw = original("lighting", row["RecordAddress"], 688)
        assert bytes.fromhex(row["RawRecordHex"]) == raw
        assert row["CandidatePosition"] == list(struct.unpack_from("<3f", raw, 0x68))
        assert row["StructuralValidation"]
    probes = load("reflection_probes.json")
    probe_by_id = {r["SourceId"]:r for r in probes}
    for row in probes:
        raw = original("lighting", row["RecordAddress"], 376)
        assert bytes.fromhex(row["RawRecordHex"]) == raw
        assert row["Guid"] == struct.unpack_from("<I", raw, 0x148)[0]
        if row["StructuralValidation"]:
            assert row["Position"] == list(struct.unpack_from("<3f", raw, 0x5c))
        else:
            assert row["Position"] is None
    bounds = load("reflection_probe_bounds.json") if (root/"reflection_probe_bounds.json").is_file() else []
    bounds_by_id = {r["SourceId"]:r for r in bounds}
    assert len(bounds_by_id) == len(bounds)
    for bound in bounds:
        raw = original("lighting", bound["RecordAddress"], 604)
        assert bytes.fromhex(bound["RawRecordHex"]) == raw
        assert bound["StructuralValidation"] and bound["OwnershipValidated"]
        parent = probe_by_id[bound["SourceProbeId"]]
        assert bound["SourceId"] in parent["InfluenceVolumeIds"]
        assert parent["SunVolumeIndex"] == bound["SunVolumeIndex"]
        assert parent["ProbeDescriptorSlot"] == bound["ProbeDescriptorSlot"]
        for name,offset in (("VolumeOrigin",0),("InnerExtentMin",48),("InnerExtentMax",60),("BlendMin",72),("BlendMax",84),("StoredOuterCenter",580)):
            assert bound[name] == list(struct.unpack_from("<3f",raw,offset))
        axes = [list(struct.unpack_from("<3f",raw,12+i*12)) for i in range(3)]
        assert axes == bound["Axes"]
        pitch,yaw,roll = map(math.radians,bound["AnglesPitchYawRoll"])
        cp,sp,cy,sy,cr,sr = math.cos(pitch),math.sin(pitch),math.cos(yaw),math.sin(yaw),math.cos(roll),math.sin(roll)
        reconstructed = [[cp*cy,cp*sy,-sp],[sr*sp*cy-cr*sy,sr*sp*sy+cr*cy,sr*cp],[cr*sp*cy+sr*sy,cr*sp*sy-sr*cy,cr*cp]]
        assert max(abs(a-b) for row1,row2 in zip(axes,reconstructed) for a,b in zip(row1,row2)) < 0.002
        transform = lambda v:[bound["VolumeOrigin"][j]+sum(v[k]*axes[k][j] for k in range(3)) for j in range(3)]
        outer_min = [a+b for a,b in zip(bound["InnerExtentMin"],bound["BlendMin"])]
        outer_max = [a+b for a,b in zip(bound["InnerExtentMax"],bound["BlendMax"])]
        assert outer_min == bound["OuterExtentMin"] and outer_max == bound["OuterExtentMax"]
        center = transform([(b-a)/2 for a,b in zip(outer_min,outer_max)])
        assert max(abs(a-b) for a,b in zip(center,bound["StoredOuterCenter"])) < 0.05
        for box,lo,hi in (("InnerBox",bound["InnerExtentMin"],bound["InnerExtentMax"]),("OuterBox",outer_min,outer_max)):
            corners = [transform([hi[k] if mask & (1<<k) else -lo[k] for k in range(3)]) for mask in range(8)]
            for actual,expected in zip(bound[box]["WorldCorners"],corners):
                assert max(abs(a-b) for a,b in zip(actual,expected)) < 1e-8
            assert max(abs(a-b) for a,b in zip(bound[box]["WorldAABBMin"],[min(v[k] for v in corners) for k in range(3)])) < 1e-8
            assert max(abs(a-b) for a,b in zip(bound[box]["WorldAABBMax"],[max(v[k] for v in corners) for k in range(3)])) < 1e-8
        assert bound["PlaneCount"] == struct.unpack_from("<I",raw,96)[0] <= 30
        assert bound["SubtractRaw"] == raw[600] <= 1
        for index,plane in enumerate(bound["InfluencePlanes"]):
            assert plane["LocalNormal"] == list(struct.unpack_from("<3f",raw,100+index*16))
            assert plane["LocalD"] == struct.unpack_from("<f",raw,112+index*16)[0]
            normal = [sum(plane["LocalNormal"][k]*axes[k][j] for k in range(3)) for j in range(3)]
            assert max(abs(a-b) for a,b in zip(plane["WorldNormal"],normal)) < 1e-8
            assert abs(plane["WorldD"] - (plane["LocalD"]-sum(a*b for a,b in zip(normal,bound["VolumeOrigin"])))) < 1e-8
    if bounds:
        assert len(bounds) == report["sources"]["lighting"]["probe_influence_volume_records"]
        partition = [r for file in (root/"reflection_probe_bounds").glob("*.json") for r in json.loads(file.read_text())]
        assert sorted(partition,key=lambda r:r["SourceId"]) == sorted(bounds,key=lambda r:r["SourceId"])
        claimed=[]
        for parent in probes:
            raw = bytes.fromhex(parent["RawRecordHex"])
            first,count = struct.unpack_from("<HH",raw,88)
            assert (first,count) == (parent["InfluenceVolumeStart"],parent["InfluenceVolumeCount"])
            rows = [bounds_by_id[source] for source in parent["InfluenceVolumeIds"]]
            assert [r["BoundIndex"] for r in rows] == list(range(first,first+count))
            assert all(r["SourceProbeId"]==parent["SourceId"] for r in rows)
            claimed.extend(parent["InfluenceVolumeIds"])
        assert sorted(claimed)==sorted(bounds_by_id), "Bounds must be owned exactly once per descriptor"
    # Independent join: the authored reflection probe must match at least one
    # compiled descriptor, including separate inner sizes and blend margins.
    probe_matches = 0
    for entity in entities.values():
        if entity["ClassName"] != "reflection_probe":
            continue
        props = entity["Properties"]
        if "guid" not in props:
            continue
        guid = int(props["guid"]) & 0xffffffff
        matches = [r for r in probes if r["Guid"] == guid and r["Position"] == entity["record_vector_candidates"][0]]
        if not matches:
            continue
        for sign, field in (("min", "CompiledOuterExtentMin"), ("max", "CompiledOuterExtentMax")):
            if "size_"+sign not in props or "blend_"+sign+"s" not in props:
                continue
            blend = props["blend_"+sign+"s"]
            blend = list(map(float, blend.split())) if isinstance(blend, str) else blend
            expected = [a+b for a,b in zip(props["size_"+sign], blend)]
            assert all(abs(a-b)<1e-4 for a,b in zip(matches[0][field], expected))
            if bounds:
                matched_bound = bounds_by_id[matches[0]["InfluenceVolumeIds"][0]]
                assert max(abs(a-b) for a,b in zip(matched_bound["InnerExtent"+sign.title()],props["size_"+sign])) < 1e-4
                assert max(abs(a-b) for a,b in zip(matched_bound["Blend"+sign.title()],blend)) < 1e-4
        probe_matches += 1

    static, splines = load("static_models.json"), load("spline_models.json")
    assert all(not r.get("RequiresSplineDeformation", False) for r in static)
    assert all(r.get("RequiresSplineDeformation", False) for r in splines)
    if baseline:
        before = json.loads((Path(baseline)/"static_models.json").read_text())
        clean = lambda rows: [{k:v for k,v in r.items() if k not in ("Name", "SourceName", "NameResolved")} for r in rows]
        assert clean(before) == clean(static), "Static transforms changed between captures"
    summary = {"status":"passed", "root":str(root), "static_models":len(static), "spline_models":len(splines),
        "entities":len(entities), "entity_class_files":len(groups), "entity_model_placements":len(models),
        "fx_records":len(fx), "light_records":len(lights), "probe_records":len(probes),
        "validated_probe_records":sum(r["StructuralValidation"] for r in probes),
        "probe_bound_records":len(bounds), "multiface_bound_records":sum(r["PlaneCount"]>0 for r in bounds),
        "multiple_volume_probe_rows":sum(r.get("InfluenceVolumeCount",0)>1 for r in probes),
        "authored_compiled_probe_matches":probe_matches,
        "checks":"source bytes, stable reads, entity joins, precise transforms/quaternions, class partitions, FX/light/probe records, probe bounds, static/spline separation"}
    summary["document_sha256"] = {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in root.glob("*.json") if p.name != "validation.json"}
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = audit(args.run, args.baseline)
    if args.output:
        args.output.write_text(json.dumps(result, indent=2)+"\n")
    print(json.dumps({k:v for k,v in result.items() if k != "document_sha256"}, indent=2))
