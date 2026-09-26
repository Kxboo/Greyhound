"""Place BO4 spline-deformed static models from a Greyhound placement run.

BO4 `splm/` static models carry an identity transform at the world origin; the
game positions them from the spline arrays captured beside the placement run
(gfxworld +0x460 instances, +0x468 segments). This tool decodes those arrays
into `splined_models.json` and writes `static_models_resolved.json`, where each
spline row receives a rigid placement at its model origin on the curve.

modelXExtent is the model's native length along the splining axis times
modelScale, and the game stretches it over instanceLength of curve. A rigid
placement therefore scales the splining axis by instanceLength / modelXExtent,
turns the lateral frame by the segment's bank angle, and loses only the bending
and any twist. Rows keep the exact spline fields. Measured on zm_towers and
zm_white.
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
import copy
import json
import warnings
from pathlib import Path

import numpy as np
from scipy.spatial.transform import Rotation

# spliningAxisType -> signed model axis that follows the curve. Measured from
# exported meshes: modelSplineOrigin.x is the model minimum along this axis.
AXES = [np.array(v, float) for v in ([1, 0, 0], [-1, 0, 0], [0, 1, 0], [0, -1, 0], [0, 0, 1], [0, 0, -1])]
# Model axis that faces the frame's up before banking: the model is turned about
# Z (X and Y splining axes) or about Y (Z splining axes) until its splining axis
# leads. On straight spans the placed render box reproduces the game's bounds for
# all six types (zm_white 202 of 204, zm_towers 1,075 of 1,155; the rest are
# twisted spans, within 0.53 units).
UP_AXES = [np.array(v, float) for v in ([0, 0, 1], [0, 0, 1], [0, 0, 1], [0, 0, 1], [-1, 0, 0], [1, 0, 0])]
SAMPLES = 64
XMODEL_BOUNDS = 0x10C          # XModel header: render bounds minimum, then maximum at +0x118


def load_arrays(diagnostics):
    capture = json.loads((diagnostics / "model_placement_capture.json").read_text())
    splines = capture.get("splines")
    if not splines:
        raise ValueError("Placement capture has no spline arrays; recapture with a current Greyhound build")
    inst = np.fromfile(diagnostics / splines["instances"]["file"], np.uint8)
    seg = np.fromfile(diagnostics / splines["segments"]["file"], np.uint8)
    if len(inst) != splines["instances"]["count"] * 48 or len(seg) != splines["segments"]["count"] * 192:
        raise ValueError("Spline file sizes differ from the capture report")
    return inst.reshape(-1, 48), seg.reshape(-1, 192)


class Splines:
    def __init__(self, inst, seg):
        self.f = inst.copy().view("<f4").astype(float)
        self.u = inst.copy().view("<u4")
        s = seg.copy().view("<f4").astype(float)
        self.dist, self.length = s[:, 0], s[:, 1]
        self.coef = s[:, 2:14].reshape(-1, 4, 3)          # a + b t + c t^2 + d t^3, segment-local
        self.to_world = s[:, 23:32].reshape(-1, 3, 3)     # world = origin + M @ p
        self.origin = s[:, 41:44]
        self.seg_raw = s
        t = np.linspace(0, 1, SAMPLES + 1)
        self.t = t
        powers = np.stack([np.ones_like(t), t, t * t, t ** 3], 1)
        local = np.einsum("tk,skc->stc", powers, self.coef)
        self.points = self.origin[:, None, :] + np.einsum("sij,stj->sti", self.to_world, local)
        steps = np.linalg.norm(np.diff(self.points, axis=1), axis=2)
        self.arc = np.concatenate([np.zeros((len(seg), 1)), np.cumsum(steps, 1)], 1)

    def segment(self, k, s):
        begin, end = int(self.u[k, 9]), int(self.u[k, 10])
        for g in range(begin, end):
            if s <= self.dist[g] + self.length[g] + 1e-3:
                return g
        return end - 1

    def evaluate(self, k, s):
        """World point, tangent, segment and curve parameter at spline distance s."""
        g = self.segment(k, s)
        local = np.clip(s - self.dist[g], 0, self.arc[g, -1])
        t = float(np.interp(local, self.arc[g], self.t))
        b = self.coef[g]
        point = self.origin[g] + self.to_world[g] @ (b[0] + b[1] * t + b[2] * t * t + b[3] * t ** 3)
        tangent = self.to_world[g] @ (b[1] + 2 * b[2] * t + 3 * b[3] * t * t)
        return point, tangent / np.linalg.norm(tangent), g, t

    def bank(self, k, s):
        """Bank angle in radians. bankAngleBezierEval is a power-form cubic in t, like
        the curve; read that way it is continuous across every segment join."""
        _, _, g, t = self.evaluate(k, s)
        return float(self.seg_raw[g, 44:48] @ np.array([1.0, t, t * t, t ** 3]))

    def frame(self, k, s):
        point, tangent, g, _ = self.evaluate(k, s)
        up = np.array([0, 0, 1.0])
        degenerate = abs(tangent @ up) > 0.999
        if degenerate:                                   # vertical curve: use the spline's own frame
            up = self.to_world[g] @ np.array([0, 0, 1.0])
        side = np.cross(up, tangent); side /= np.linalg.norm(side)
        up = np.cross(tangent, side)
        a = self.bank(k, s)                              # turns up toward side about the tangent
        up, side = np.cos(a) * up + np.sin(a) * side, np.cos(a) * side - np.sin(a) * up
        return point, tangent, side, up, degenerate


def instance_json(sp, k):
    f, u = sp.f[k], sp.u[k]
    return {"SplineInstanceIndex": k, "modelXExtent": f[0], "instanceLength": f[1],
            "modelSplineOrigin": f[2:5].tolist(), "distFromStartNode": f[5], "modelScale": f[6],
            "upDownOffset": f[7], "leftRightOffset": f[8], "segmentBegin": int(u[9]),
            "segmentEnd": int(u[10]), "spliningAxisType": int(u[11])}


def segment_json(sp, g):
    s = sp.seg_raw[g]
    return {"SegmentIndex": g, "distFromStartNode": s[0], "length": s[1], "curvePowerCoefficients": s[2:14].tolist(),
            "entBezierDerEval": s[14:23].tolist(), "entToAlignedRowMajor": s[23:32].tolist(),
            "modelToWldRowMajor": s[32:41].tolist(), "modelToWld_origin": s[41:44].tolist(),
            "bankAngleBezierEval": s[44:48].tolist()}


def rigid(sp, k):
    """Rigid placement of instance k: position, rotation matrix, model-space scale."""
    f = sp.f[k]
    axis = int(sp.u[k, 11])
    along = AXES[axis]
    up_model = UP_AXES[axis]
    side_model = np.cross(up_model, along)
    stretch = f[1] / f[0] if f[0] > 0 else 1.0           # instanceLength / modelXExtent
    s0 = f[5] - f[2] * stretch                           # model origin on the curve
    start = sp.dist[int(sp.u[k, 9])]
    end = sp.dist[int(sp.u[k, 10]) - 1] + sp.length[int(sp.u[k, 10]) - 1]
    clamped = not (start - 1e-3 <= s0 <= end + 1e-3)
    # An origin past either end of the curve continues along the end tangent: on
    # Blackout this reproduces the render box for 22 of 24 straight rows, clamping 0.
    s_end = float(np.clip(s0, start, end))
    point, tangent, side, up, degenerate = sp.frame(k, s_end)
    point = point + tangent * (s0 - s_end)
    # Offsets use the banked frame. Neither measured map has a banked instance with
    # offsets, so that choice is unverified.
    position = point + up * f[7] + side * f[8]
    world = np.stack([tangent, up, side], 1)
    model = np.stack([along, up_model, side_model], 1)
    matrix = world @ model.T
    scale = np.full(3, f[6]); scale[axis // 2] *= stretch
    twist = np.ptp([sp.bank(k, s) for s in np.linspace(f[5], f[5] + f[1], 9)])
    return {"position": position, "matrix": matrix, "scale": scale, "stretch": float(stretch),
            "bank": sp.bank(k, s_end), "twist": float(twist), "clamped": clamped, "degenerate": degenerate}


def render_box_check(run, sp, rows):
    """Straight, axis-aligned spans: the placed render box's AABB equals the game's
    bounds, because the deformed mesh is then the stretched rigid mesh."""
    capture = json.loads((run / "diagnostics" / "model_placement_capture.json").read_text())
    headers = (run / "diagnostics" / "model_headers.bin").read_bytes()
    boxes = {int(m["hash"], 16): np.frombuffer(headers, "<f4", 6, m["header_offset"] + XMODEL_BOUNDS).astype(float)
             for m in capture.get("models", [])}
    errors = []
    for row in rows:
        k = row["SplineInstanceIndex"]
        box = boxes.get(int(row["ModelHash"], 16))
        f = sp.f[k]
        tangents = np.array([sp.evaluate(k, s)[1] for s in np.linspace(f[5], f[5] + f[1], 9)])
        if box is None or np.abs(tangents @ tangents[0]).min() < np.cos(np.radians(0.5)) \
                or np.abs(tangents[0]).max() < np.cos(np.radians(0.5)):
            continue
        p = rigid(sp, k)
        corners = np.array([[x, y, z] for x in box[0::3] for y in box[1::3] for z in box[2::3]]) * p["scale"]
        world = corners @ p["matrix"].T + p["position"]
        game = [row["BoundsMin"][c] for c in "XYZ"] + [row["BoundsMax"][c] for c in "XYZ"]
        errors.append(float(np.abs(np.r_[world.min(0), world.max(0)] - game).max()))
    errors = np.array(errors) if errors else np.zeros(0)
    return {"straight_spans": len(errors), "within_0_05": int((errors < 0.05).sum()),
            "maximum_error": float(errors.max()) if len(errors) else None}


def span_in_bounds(sp, k, row):
    f = sp.f[k]
    lo = np.array([row["BoundsMin"][c] for c in "XYZ"]); hi = np.array([row["BoundsMax"][c] for c in "XYZ"])
    pts = []
    for s in np.linspace(f[5], f[5] + f[1], 16):
        point, tangent, side, up, _ = sp.frame(k, s)
        pts.append(point + up * f[7] + side * f[8])
    pts = np.array(pts)
    return float(max(np.maximum(lo - pts, 0).max(), np.maximum(pts - hi, 0).max()))


def resolve(run):
    run = Path(run)
    inst, seg = load_arrays(run / "diagnostics")
    sp = Splines(inst, seg)
    # Structural checks: ranges and curve continuity between consecutive segments.
    begins, ends = sp.u[1:, 9], sp.u[1:, 10]
    if not np.all((begins >= 1) & (begins < ends) & (ends <= len(seg))) or np.any(sp.u[1:, 11] > 5):
        raise ValueError("Invalid spline instance ranges or axis types")
    joins = [float(np.linalg.norm(sp.points[g, -1] - sp.points[g + 1, 0])) for g in range(1, len(seg) - 1)
             if abs(sp.dist[g] + sp.length[g] - sp.dist[g + 1]) < 1e-2]
    arc_error = np.abs(sp.arc[1:, -1] - sp.length[1:]) / np.maximum(sp.length[1:], 1e-3)

    rows = json.loads((run / "static_models.json").read_text())
    spline_rows = [row for row in rows if row.get("SplineInstanceIndex") is not None]
    resolved, overshoot = [], []
    counts = {"spline_rows": 0, "origin_outside_spline_range": 0, "vertical_tangent_frames": 0,
              "stretched": 0, "banked": 0, "twisted": 0}
    stretches = []
    for row in rows:
        k = row.get("SplineInstanceIndex")
        if k is None:
            resolved.append(row); continue
        counts["spline_rows"] += 1
        p = rigid(sp, k)
        counts["origin_outside_spline_range"] += int(p["clamped"])
        counts["vertical_tangent_frames"] += int(p["degenerate"])
        counts["stretched"] += int(abs(p["stretch"] - 1) > 1e-4)
        counts["banked"] += int(abs(p["bank"]) > 1e-4)
        counts["twisted"] += int(p["twist"] > 1e-3)
        stretches.append(p["stretch"])
        overshoot.append(span_in_bounds(sp, k, row))
        rot = Rotation.from_matrix(p["matrix"])
        with warnings.catch_warnings():   # gimbal lock still yields angles that reproduce the matrix
            warnings.simplefilter("ignore")
            euler = rot.as_euler("xyz", degrees=True)
        q = rot.as_quat()
        out = copy.deepcopy(row)
        out.update({"Position": dict(zip("XYZ", p["position"].tolist())),
                    "RotationQuaternion": dict(zip("XYZW", q.tolist())),
                    "RotationDegrees": dict(zip("XYZ", euler.tolist())),
                    "ModelScale": dict(zip("XYZ", p["scale"].tolist())),
                    "PlacementSource": "spline_rigid_approximation",
                    "SplineBendingIgnored": True,
                    "SplineStretch": p["stretch"],
                    "SplineBankRadians": p["bank"],
                    "SplineTwistIgnored": p["twist"] > 1e-3,
                    "SplineLateralOrientationVerified": True,
                    "SplineOriginClampedToCurve": bool(p["clamped"])})
        resolved.append(out)

    overshoot = np.array(overshoot) if overshoot else np.zeros(1)
    report = {"schema": "greyhound-bo4-spline-resolution-v2", "instances": len(inst) - 1, "segments": len(seg) - 1,
              "consecutive_segment_joins": len(joins), "maximum_join_error": max(joins) if joins else None,
              "arc_length_relative_error_median": float(np.median(arc_error)),
              "curve_span_inside_render_bounds_within_0_5": float(np.mean(overshoot < 0.5)),
              "curve_span_bounds_overshoot_p95": float(np.quantile(overshoot, 0.95)), **counts,
              "stretch_range": [min(stretches), max(stretches)] if stretches else None,
              "straight_span_render_box_check": render_box_check(run, sp, spline_rows)
              if (run / "diagnostics" / "model_headers.bin").is_file() else "model headers not captured",
              "notes": ["Render bounds are the game's bounds of the deformed mesh. The curve-span check tests position only; "
                        "the straight-span check places each model's render box and so tests rotation, stretch and bank.",
                        "ModelScale is non-uniform where SplineStretch is not 1: the splining axis carries "
                        "modelScale x instanceLength / modelXExtent. A consumer that reads only ModelScale.X loses the stretch.",
                        "Curve bending, and a bank that varies along an instance (SplineTwistIgnored), are not representable."]}
    doc = {"schema": "greyhound-bo4-splined-models-v1", "segment_end_exclusive": True,
           "instance_zero_reserved": True, "curve": "world = modelToWld_origin + entToAligned @ (a + b t + c t^2 + d t^3)",
           "Instances": [instance_json(sp, k) for k in range(1, len(inst))],
           "Segments": [segment_json(sp, g) for g in range(1, len(seg))]}
    (run / "splined_models.json").write_text(json.dumps(doc, indent=1))
    (run / "static_models_resolved.json").write_text(json.dumps(resolved, indent=2))
    (run / "spline_resolution_report.json").write_text(json.dumps(report, indent=2))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("run", type=Path, help="Greyhound BO4 placements run folder")
    print(json.dumps(resolve(parser.parse_args().run), indent=2))
