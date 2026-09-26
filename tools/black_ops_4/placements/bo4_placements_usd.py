"""BO4 model placements as a USD PointInstancer layer (no model exports).

Two steps, so the large JSON files never need pxr and pxr never needs them:

  extract  (any Python)        stream the placement JSON files into one .npz
  write    (a Python with pxr, e.g. Blender's)   .npz -> placements.usdc

Every instance keeps the game's transform as given: position, rotation
quaternion (XYZW in the JSON, real-first in USD) and ModelScale, which is
non-uniform on stretched spline rows. `primvars:bo4_source` says where each
row came from (0 static gfxworld, 1 spline rigid approximation, 2 instanced
model, 3 dynamic entity), `primvars:bo4_row` its row in that file.

Prototypes are one empty Xform per model, carrying the model name and hash.
--models-dir adds a payload to <dir>/<model>.usd on each, for when models are
exported; without it nothing is referenced that does not exist.
"""

import argparse
import json
import re
from pathlib import Path

import numpy as np

SOURCES = {"live": 0, "spline_rigid_approximation": 1, "clipmap_instanced_model": 2, "clipmap_dynamic_entity": 3}


def records(path, block=1 << 26):
    """The objects of a top-level JSON array, decoded one at a time."""
    decoder = json.JSONDecoder()
    with open(path, encoding="utf-8") as f:
        buf, pos, eof = f.read(block), 0, False
        pos = buf.index("[") + 1
        while True:
            while pos < len(buf) and buf[pos] in " \t\r\n,":
                pos += 1
            if pos < len(buf) and buf[pos] == "]":
                return
            try:
                obj, end = decoder.raw_decode(buf, pos)
            except json.JSONDecodeError:
                if eof:
                    raise
                more = f.read(block)
                eof = not more
                buf, pos = buf[pos:] + more, 0
                continue
            yield obj
            pos = end
            if pos > block and not eof:
                more = f.read(block)
                eof = not more
                buf, pos = buf[pos:] + more, 0


def extract(files, out):
    names, hashes, resolved = {}, [], []
    proto, pos, quat, scale, source, row = [], [], [], [], [], []
    for path, default_source in files:
        for k, r in enumerate(records(path)):
            key = r["Name"]
            if key not in names:
                names[key] = len(names)
                hashes.append(r.get("ModelHash") or "")
                resolved.append(bool(r.get("NameResolved")))
            proto.append(names[key])
            p, q, s = r["Position"], r["RotationQuaternion"], r["ModelScale"]
            pos.append((p["X"], p["Y"], p["Z"]))
            quat.append((q["X"], q["Y"], q["Z"], q["W"]))
            scale.append((s["X"], s["Y"], s["Z"]))
            source.append(SOURCES.get(r.get("PlacementSource"), default_source))
            row.append(k)
        print(path, "->", len(proto), "instances so far", flush=True)
    np.savez(out, names=np.array(list(names), dtype=str), hashes=np.array(hashes, dtype=str),
             resolved=np.array(resolved), proto=np.array(proto, np.int32), pos=np.array(pos, np.float64),
             quat=np.array(quat, np.float32), scale=np.array(scale, np.float32), source=np.array(source, np.uint8),
             row=np.array(row, np.int32))
    return len(proto), len(names)


def prim_name(name, used):
    base = re.sub(r"[^A-Za-z0-9_]", "_", name)
    if not base or base[0].isdigit():
        base = "m_" + base
    out, k = base, 1
    while out in used:
        k += 1
        out = "%s_%d" % (base, k)
    used.add(out)
    return out


def write(npz, out, models_dir=None):
    from pxr import Gf, Sdf, Usd, UsdGeom, Vt
    d = np.load(npz)
    stage = Usd.Stage.CreateNew(str(out))
    stage.SetMetadata("metersPerUnit", 0.0254)
    stage.SetMetadata("upAxis", "Z")
    root = UsdGeom.Xform.Define(stage, "/Placements")
    stage.SetDefaultPrim(root.GetPrim())
    inst = UsdGeom.PointInstancer.Define(stage, "/Placements/Instances")
    UsdGeom.Scope.Define(stage, "/Placements/Instances/Prototypes")
    used, targets = set(), []
    for name, h, ok in zip(d["names"], d["hashes"], d["resolved"]):
        path = "/Placements/Instances/Prototypes/" + prim_name(str(name), used)
        prim = UsdGeom.Xform.Define(stage, path).GetPrim()
        prim.CreateAttribute("bo4:model", Sdf.ValueTypeNames.String).Set(str(name))
        prim.CreateAttribute("bo4:model_hash", Sdf.ValueTypeNames.String).Set(str(h))
        prim.CreateAttribute("bo4:name_resolved", Sdf.ValueTypeNames.Bool).Set(bool(ok))
        if models_dir:
            prim.GetPayloads().AddPayload("%s/%s.usd" % (models_dir.rstrip("/"), name))
        targets.append(path)
    inst.CreatePrototypesRel().SetTargets(targets)
    inst.CreateProtoIndicesAttr(Vt.IntArray.FromNumpy(d["proto"]))
    inst.CreatePositionsAttr(Vt.Vec3fArray.FromNumpy(d["pos"].astype(np.float32)))
    # orientationsf: full float quaternions (half precision is ~0.03 degrees, half an inch at the end of a
    # 1000-inch road spline). GfQuatf is laid out imaginary first, XYZW, as the JSON.
    inst.CreateOrientationsfAttr(Vt.QuatfArray.FromNumpy(np.ascontiguousarray(d["quat"])))
    inst.CreateScalesAttr(Vt.Vec3fArray.FromNumpy(d["scale"]))
    pv = UsdGeom.PrimvarsAPI(inst.GetPrim())
    pv.CreatePrimvar("bo4_source", Sdf.ValueTypeNames.IntArray, UsdGeom.Tokens.vertex).Set(
        Vt.IntArray.FromNumpy(d["source"].astype(np.int32)))
    pv.CreatePrimvar("bo4_row", Sdf.ValueTypeNames.IntArray, UsdGeom.Tokens.vertex).Set(Vt.IntArray.FromNumpy(d["row"]))
    lo, hi = d["pos"].min(0), d["pos"].max(0)
    inst.CreateExtentAttr(Vt.Vec3fArray([Gf.Vec3f(*map(float, lo)), Gf.Vec3f(*map(float, hi))]))
    stage.GetRootLayer().Save()
    return len(d["proto"]), len(targets)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("extract")
    e.add_argument("out", type=Path, help=".npz to write")
    e.add_argument("--static", type=Path, help="static_models_resolved.json (splines resolved)")
    e.add_argument("--instanced", type=Path, help="instanced_models.json")
    e.add_argument("--dynamic", type=Path, help="dynamic_entities.json")
    w = sub.add_parser("write")
    w.add_argument("npz", type=Path)
    w.add_argument("out", type=Path, help="placements.usdc")
    w.add_argument("--models-dir", help="add a payload to <dir>/<model>.usd on every prototype")
    args = parser.parse_args()
    if args.cmd == "extract":
        files = [(p, s) for p, s in ((args.static, 0), (args.instanced, 2), (args.dynamic, 3)) if p]
        print("instances %d, models %d" % extract(files, args.out))
    else:
        print("instances %d, prototypes %d" % write(args.npz, args.out, args.models_dir))


if __name__ == "__main__":
    main()
