"""Read-only verification of Greyhound's BO4 placement JSON against captured bytes.

Optional collision evidence is an independent BO4 rotation/direction check, not
the source of render placement data. Distinct collision scale is reported.
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
from scipy.spatial import cKDTree
from scipy.spatial.transform import Rotation


def audit(root, collision=None):
    root = Path(root)
    source = root / "diagnostics"
    capture = json.loads((source / "model_placement_capture.json").read_text())
    rows = json.loads((root / "static_models.json").read_text())
    refs = np.fromfile(source / capture["reference_file"], dtype="<u8").reshape(-1, 7)
    transforms = np.fromfile(source / capture["transform_file"], dtype="<f4").reshape(-1, 16)
    index = ((refs[:, 3] - int(capture["transform_pointer"], 16)) // 64).astype(int)
    assert len(rows) == len(refs) == capture["instance_count"]
    assert sorted(index) == list(range(len(refs)))
    t = transforms[index]
    back = t.copy().view("<u4")[:, 14] & 0x7fffffff
    np.testing.assert_array_equal(back, np.arange(len(rows)))
    models = {int(m["pointer"], 16): m for m in capture["models"]}
    for i, row in enumerate(rows):
        expected = models[int(refs[i, 0])]
        name = expected["name"] or f"xmodel_{int(expected['hash'],16):x}"
        assert row["SourceName"] == name
        assert row["ModelHash"] == expected["hash"]
        assert row["NameResolved"] == bool(expected["name"])
        assert row["RecordSlot"] == i and row["TransformSlot"] == index[i]
    vector = lambda key, components: np.array([[r[key][c] for c in components] for r in rows])
    np.testing.assert_array_equal(vector("Position", "XYZ"), t[:, 4:7])
    np.testing.assert_array_equal(vector("ModelScale", "XYZ"), np.repeat(t[:, 7:8], 3, axis=1))
    np.testing.assert_array_equal(vector("RotationQuaternion", "XYZW"), t[:, :4])
    np.testing.assert_array_equal(vector("BoundsMin", "XYZ"), t[:, 8:11])
    np.testing.assert_array_equal(vector("BoundsMax", "XYZ"), t[:, 11:14])
    matrices = Rotation.from_quat(t[:, :4]).as_matrix()
    euler_matrices = Rotation.from_euler("xyz", vector("RotationDegrees", "XYZ"), degrees=True).as_matrix()
    euler_error = float(np.max(np.abs(matrices - euler_matrices)))
    assert euler_error < 1e-6, euler_error
    result = {"instances": len(rows), "unique_models": len(models),
              "raw_fields_exact": True, "reference_permutation_verified": True,
              "euler_matrix_max_error": euler_error,
              "scale_range": [float(t[:, 7].min()), float(t[:, 7].max())],
              "unresolved_model_names": sum(not m["name"] for m in models.values())}
    if collision:
        collision = Path(collision)
        doc = json.loads((collision / "model_collision_probe.json").read_text())
        assert doc["map_hash"] == capture["map_hash"]
        for m in doc["models"]:
            ptr = int(m["pointer"], 16)
            if ptr in models:
                assert m["hash"] == models[ptr]["hash"], "Pointer identity changed between captures"
        c = np.fromfile(collision / "collision_instances.bin", dtype="<f4").reshape(-1, 24)
        pointers = c.view("<u8")[:, 0]
        forward = np.linalg.inv(c[:, 6:15].reshape(-1, 3, 3))
        scales = np.cbrt(np.linalg.det(forward))
        rotations = forward / scales[:, None, None]
        rotation_errors, scale_errors = [], []
        ambiguous = 0
        for ptr in np.unique(refs[:, 0]):
            a = np.where(refs[:, 0] == ptr)[0]
            b = np.where(pointers == ptr)[0]
            if not len(b):
                continue
            near = cKDTree(c[b, 3:6]).query_ball_point(t[a, 4:7], .001)
            for ri, matches in zip(a, near):
                if not matches:
                    continue
                ambiguous += len(matches) > 1
                candidates = b[matches]
                errors = np.max(np.abs(rotations[candidates] - matrices[ri]), axis=(1, 2))
                best = int(np.argmin(errors))
                rotation_errors.append(float(errors[best]))
                scale_errors.append(float(abs(scales[candidates[best]] - t[ri, 7])))
        assert rotation_errors and max(rotation_errors) < 1e-4
        result["independent_collision_check"] = {
            "matched_render_instances": len(rotation_errors),
            "rotation_matrix_max_error": max(rotation_errors),
            "multiple_collision_records_at_same_model_origin": ambiguous,
            "scale_disagreements_over_0_001": int(np.sum(np.array(scale_errors) > .001)),
            "note": "All candidates at duplicate origins considered; render scale retained unchanged."}
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("placements", type=Path)
    parser.add_argument("--collision", type=Path)
    args = parser.parse_args()
    print(json.dumps(audit(args.placements, args.collision), indent=2))
