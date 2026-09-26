"""Verify every BO4 static placement against the game's own world bounds.

Each 64-byte gfxworld transform stores world bounds that the game computed from
the model and that transform. Rebuilding those bounds from an exported mesh and
the row's rotation, position and scale is an independent per-instance check,
covering instances that have no collision copy.

Measured on zm_towers (33,495 non-spline instances):
- Static meshes: bounds are the AABB of the transformed vertices of the most
  detailed LOD (29,322 exact to 1e-4 relative).
- Flag 0x4 (animated/skinned: crowd, fxanim `_smod`): bounds are one pose box
  per model rotated into place, so the bind-pose mesh cannot match; instances
  sharing a pose box under different rotations still prove the rotation.
- Some meshes carry bounds extended on one side (chaos strands grow upward);
  matching the remaining faces exactly still pins the placement.

Export the models first in any format read here (CAST, SEModel, OBJ, SMD), e.g.
`Greyhound.exe assets export --type model --model-format cast --all-lods
--bo4-name-database echo000 --name ...`. CoDAssets::ExportWraithModel scales
CAST/SEModel/OBJ by 2.54 (centimetres) and leaves SMD in game inches; vertices
are converted back to inches here.
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
import collections
import json
import struct
from pathlib import Path

import numpy as np
from scipy.spatial import ConvexHull, QhullError
from scipy.spatial.transform import Rotation

ANIMATED_POSE_FLAG = 0x4
# Absolute tolerance in inches plus a float32-sized relative term.
ABS_TOL, REL_TOL = 0.01, 1e-4


def read_obj(path):
    with path.open() as handle:
        return np.array([line.split()[1:4] for line in handle if line.startswith("v ")], float)


def read_smd(path):
    """Vertex lines of the triangles block: parent x y z nx ny nz u v ..."""
    points, in_triangles = [], False
    with path.open() as handle:
        for line in handle:
            parts = line.split()
            if parts[:1] == ["triangles"]:
                in_triangles = True
            elif parts[:1] == ["end"]:
                in_triangles = False
            elif in_triangles and len(parts) >= 9:
                points.append(parts[1:4])
    return np.array(points, float)


def read_cast(path):
    """Positions (`vp`) of every CAST mesh node; property layout per the CAST v1 container."""
    data = path.read_bytes()
    magic, version, roots, _ = struct.unpack_from("<4sIII", data)
    if magic != b"cast" or version != 1:
        raise ValueError(f"{path}: not a CAST v1 file")
    sizes = {b"b": 1, b"h": 2, b"i": 4, b"l": 8, b"f": 4, b"d": 8, b"2v": 8, b"3v": 12, b"4v": 16}
    points = []

    def node(offset):
        ident, size, _, props, children = struct.unpack_from("<4sIQII", data, offset)
        end, offset = offset + size, offset + 24
        for _ in range(props):
            kind, name_size, count = struct.unpack_from("<2sHI", data, offset)
            kind = kind.rstrip(b"\0")
            name = data[offset + 8:offset + 8 + name_size]
            offset += 8 + name_size
            if kind == b"s":
                offset = data.index(b"\0", offset) + 1
                continue
            stop = offset + count * sizes[kind]
            if ident == b"mesh" and name == b"vp":
                points.append(np.frombuffer(data, "<f4", count * 3, offset).reshape(-1, 3))
            offset = stop
        for _ in range(children):
            offset = node(offset)
        if offset != end:
            raise ValueError(f"{path}: CAST node size mismatch")
        return end

    offset = 16
    for _ in range(roots):
        offset = node(offset)
    return np.concatenate(points).astype(float) if points else np.zeros((0, 3))


def read_semodel(path):
    """Vertex positions of each SEModel mesh, following WraithX SEModelExport.cpp."""
    data = path.read_bytes()
    if data[:7] != b"SEModel":
        raise ValueError(f"{path}: not an SEModel file")
    _, bone_flags, _, bones, meshes, _ = struct.unpack_from("<BBBIII", data, 11)
    offset = 29
    for _ in range(bones):                                   # null-terminated tag names
        offset = data.index(b"\0", offset) + 1
    offset += bones * (1 + 4 + 28 + 28 + (12 if bone_flags & 4 else 0))
    index_size = 1 if bones <= 0xFF else 2 if bones <= 0xFFFF else 4
    points = []
    for _ in range(meshes):
        _, layers, influences, vertices, faces = struct.unpack_from("<BBBII", data, offset)
        offset += 11
        points.append(np.frombuffer(data, "<f4", vertices * 3, offset).reshape(-1, 3))
        offset += vertices * (12 + layers * 8 + 12 + 4 + influences * (index_size + 4))
        face_index = 1 if vertices <= 0xFF else 2 if vertices <= 0xFFFF else 4
        offset += faces * 3 * face_index + layers * 4
    return np.concatenate(points).astype(float) if points else np.zeros((0, 3))


# Suffix -> (reader, file units per game inch).
FORMATS = {".cast": (read_cast, 2.54), ".semodel": (read_semodel, 2.54),
           ".obj": (read_obj, 2.54), ".smd": (read_smd, 1.0)}


def load_lods(models_root, name):
    """All exported LOD vertex sets for one model, reduced to hull vertices (AABB-preserving)."""
    folder = models_root / name
    for suffix, (reader, units) in FORMATS.items():
        files = sorted(folder.glob(f"{name}_LOD*{suffix}")) or sorted(folder.glob(f"{name}{suffix}"))
        if files:
            break
    else:
        return {}
    lods = {}
    for path in files:
        v = reader(path)
        if not len(v):
            continue
        v = v / units
        try:
            v = v[ConvexHull(v).vertices]
        except QhullError:       # planar meshes: keep every vertex
            pass
        lods[path.stem[len(name):].lstrip("_") or "default"] = v
    return lods


def row_vectors(row):
    q = np.array([row["RotationQuaternion"][c] for c in "XYZW"])
    p = np.array([row["Position"][c] for c in "XYZ"])
    b = np.array([[row["BoundsMin"][c] for c in "XYZ"], [row["BoundsMax"][c] for c in "XYZ"]])
    return q, p, float(row["ModelScale"]["X"]), b


def tolerance(bounds):
    return ABS_TOL + REL_TOL * float(np.abs(bounds).max())


def mesh_check(lods, row):
    """Best LOD by worst face error, plus how many of the six faces match exactly."""
    q, p, s, b = row_vectors(row)
    R = Rotation.from_quat(q).as_matrix() * s
    tol = tolerance(b)
    errors, faces = {}, 0
    for lod, v in lods.items():
        w = v @ R.T + p
        face = np.abs(np.r_[w.min(0), w.max(0)] - b.reshape(-1))
        errors[lod] = float(face.max())
        faces = max(faces, int((face <= tol).sum()))
    lod = min(errors, key=errors.get)
    return errors[lod], lod, faces


def pose_boxes(rows, indices):
    """Group flag-0x4 instances of one model by the local box their bounds imply."""
    implied = []
    for i in indices:
        q, p, s, b = row_vectors(rows[i])
        R = Rotation.from_quat(q).as_matrix() * s
        centre = np.linalg.lstsq(R, b.mean(0) - p, rcond=None)[0]
        half = np.linalg.lstsq(np.abs(R), (b[1] - b[0]) / 2, rcond=None)[0]
        implied.append((i, np.r_[centre, half], R, p, b))
    groups = collections.defaultdict(list)
    for item in implied:
        groups[tuple(np.round(item[1], 1))].append(item)
    result = {}
    for members in groups.values():
        box = np.mean([m[1] for m in members], 0)
        rotations = {tuple(np.round(m[2].reshape(-1), 3)) for m in members}
        for i, _, R, p, b in members:
            centre = p + R @ box[:3]
            half = np.abs(R) @ box[3:]
            error = float(np.abs(np.r_[centre - half, centre + half] - b.reshape(-1)).max())
            result[i] = (error, len(members), len(rotations), error <= tolerance(b))
    return result


def verify(run, models_root):
    run, models_root = Path(run), Path(models_root)
    rows = json.loads((run / "static_models.json").read_text())
    status = [None] * len(rows)
    cache, missing = {}, set()
    animated = collections.defaultdict(list)
    for i, row in enumerate(rows):
        if row.get("SplineInstanceIndex") is not None:
            status[i] = {"status": "spline_not_checked"}
            continue
        name = row["SourceName"]
        if name not in cache:
            cache[name] = load_lods(models_root, name)
        if not cache[name]:
            missing.add(name)
            status[i] = {"status": "unverified_no_mesh"}
            continue
        error, lod, faces = mesh_check(cache[name], row)
        if error <= tolerance(row_vectors(row)[3]):
            status[i] = {"status": "mesh_bounds_exact", "lod": lod, "error": error}
        elif int(row.get("StaticModelFlagsRaw") or 0) & ANIMATED_POSE_FLAG:
            animated[name].append(i)
            status[i] = {"status": "pending_pose", "mesh_error": error}
        elif faces >= 4:
            status[i] = {"status": "mesh_bounds_partial", "lod": lod, "exact_faces": faces, "error": error}
        else:
            status[i] = {"status": "unverified", "lod": lod, "exact_faces": faces, "error": error}
    for name, indices in animated.items():
        for i, (error, members, rotations, fits) in pose_boxes(rows, indices).items():
            proven = fits and members > 1 and rotations > 1
            status[i] = {"status": "pose_box_rotation_proven" if proven else
                         "pose_box_consistent" if fits else "unverified_animated",
                         "pose_group_size": members, "pose_group_rotations": rotations, "error": error}
    counts = collections.Counter(s["status"] for s in status)
    unverified = collections.Counter(rows[i]["SourceName"] for i, s in enumerate(status)
                                     if s["status"].startswith("unverified"))
    report = {"schema": "greyhound-bo4-placement-bounds-v1", "instances": len(rows),
              "status_counts": dict(counts), "models_without_mesh": sorted(missing),
              "unverified_by_model": dict(unverified.most_common()),
              "statuses": {
                  "mesh_bounds_exact": "stored bounds rebuilt exactly from the mesh and this transform",
                  "pose_box_rotation_proven": "animated model; one pose box explains instances with different rotations",
                  "pose_box_consistent": "animated model; pose box fits but no second rotation to prove it",
                  "mesh_bounds_partial": "at least four of six bound faces exact; bounds extended on the others",
                  "unverified": "bounds not reproduced; placement not independently confirmed",
                  "spline_not_checked": "spline-deformed; see resolve_bo4_splines.py"},
              "rows": [{"RecordSlot": rows[i]["RecordSlot"], "SourceName": rows[i]["SourceName"], **s}
                       for i, s in enumerate(status)]}
    (run / "placement_verification.json").write_text(json.dumps(report, indent=1))
    return {k: v for k, v in report.items() if k not in ("rows", "statuses")}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("run", type=Path, help="Greyhound BO4 placements run folder")
    parser.add_argument("models", type=Path, help="Greyhound xmodels export folder (<name>/<name>[_LODn].obj)")
    args = parser.parse_args()
    print(json.dumps(verify(args.run, args.models), indent=2))
