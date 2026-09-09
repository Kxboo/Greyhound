"""Export inspectable CW clip_map mesh and separated brush candidates.

The mesh decoder is the current evidence-backed coordinate/strip candidate.
Brushes use checked hulls of unchanged captured vertices. Float triangles keep
captured indices; quantized strips remain candidates. Run this exporter with
Python: SCRIPT CAPTURE --output-dir DIR.
"""
import argparse
import json
import math
import re
import struct
import sys
import time
import hashlib
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from export_cw_clip_mesh_candidates import decode as decode_mesh

try:
    import numpy as np
except Exception:
    np = None


BRUSH_BOX_TOLERANCE = 0.1


def payload_bytes(root, model):
    path = root / model["payload"]["file"]
    return path.read_bytes()


def u32(data, offset):
    return struct.unpack_from("<I", data, offset)[0]


def u64(data, offset):
    return struct.unpack_from("<Q", data, offset)[0]


def f32s(data, offset, count):
    return struct.unpack_from("<" + "f" * count, data, offset)


def finite_box(values):
    return all(math.isfinite(x) for x in values)


def relative_pointer(data, offset, address):
    if offset + 8 > len(data):
        return None
    value = u64(data, offset)
    if address <= value < address + len(data):
        return value - address
    return None


def verify_brush_arrays(data, vs, bb, ab, nv, nb, pointer_backed=False):
    if vs < 0 or bb < 0 or ab < 0:
        return None
    if vs + 12 * nv > len(data) or bb + 4 * nb > len(data):
        return None
    if ab + 28 * nb > len(data):
        return None
    vertices = [list(f32s(data, vs + 12 * i, 3)) for i in range(nv)]
    boxes = [list(f32s(data, ab + 28 * i, 6)) for i in range(nb)]
    if not all(finite_box(v) for v in vertices + boxes):
        return None
    starts = [(u32(data, bb + 4 * i) & 0xFFFFFF, i) for i in range(nb)]
    starts.sort()
    if not starts or starts[0][0] != 0:
        return None
    if any(starts[i][0] == starts[i - 1][0] for i in range(1, len(starts))):
        return None
    result = []
    for i, (start, brush_index) in enumerate(starts):
        # Game readers 6B13030/B8A2D50 use the high byte as an explicit count.
        count = u32(data, bb + 4 * brush_index) >> 24
        end = start + count
        next_start = starts[i + 1][0] if i + 1 < len(starts) else nv
        if not count or end != next_start:
            return None
        run = vertices[start:end]
        actual = [min(v[a] for v in run) for a in range(3)]
        actual += [max(v[a] for v in run) for a in range(3)]
        box = boxes[brush_index]
        if any(box[a] > box[a + 3] for a in range(3)):
            return None
        bounds_error = max(abs(actual[a] - box[a]) for a in range(6))
        outside = max([0.0] + [box[a] - actual[a] for a in range(3)] +
                      [actual[a + 3] - box[a + 3] for a in range(3)])
        # Direct runtime pointers establish array identity independently of box
        # tightness. Runtime AABBs may conservatively enclose the vertex hull.
        # Scanned candidates still require a tight match to locate the table.
        if outside > BRUSH_BOX_TOLERANCE or (not pointer_backed and bounds_error > BRUSH_BOX_TOLERANCE):
            return None
        result.append({
            "brush_index": brush_index,
            "vertex_start": start,
            "vertex_count": count,
            "stored_bounds_max_difference": bounds_error,
            "vertex_outside_stored_bounds": outside,
            "vertices": run,
            "mins": boxes[brush_index][:3],
            "maxs": boxes[brush_index][3:],
            # Keep the legacy raw field for existing audit consumers.
            "contents": u32(data, ab + 28 * brush_index + 24),
            "packed_flags_and_plane_count": u32(data, ab + 28 * brush_index + 24),
            "nonaxial_plane_count": u32(data, ab + 28 * brush_index + 24) >> 26,
            "collision_flags_raw": u32(data, ab + 28 * brush_index + 24) & 0x3FFFFFF,
            "field_a": None,
        })
    if sum(len(item["vertices"]) for item in result) != nv:
        return None
    return result


def decode_brushes(data, model):
    bounds = struct.pack("<6f", *(model["mins"] + model["maxs"]))
    if data[336:360] != bounds:
        return None
    if len(data) < 372:
        return {"status": "truncated_header"}
    plane_count = u32(data, 360)
    vertex_count = u32(data, 364)
    brush_count = u32(data, 368)
    result = {
        "plane_count": plane_count,
        "vertex_count": vertex_count,
        "brush_count": brush_count,
    }
    if not vertex_count or not brush_count:
        result["status"] = "empty"
        return result

    address = int(model["payload"]["address"], 16)
    pointers = {offset: relative_pointer(data, offset, address)
                for offset in (400, 408, 440, 448, 464)}
    attempts = []
    if all(pointers[offset] is not None for offset in (408, 448, 464)):
        attempts.append(("pointer", pointers[408], pointers[448], pointers[464]))

    # The pointer-free layout is the common compact form: planes, vertices,
    # packed brush runs, then an AABB/content record array.
    vs = 520 + 16 * plane_count
    bb = vs + 12 * vertex_count + 4 * brush_count

    # For compact records, locate the AABB table by searching for the exact
    # min/max tuple of the first one or two decoded vertex runs. This handles
    # brushes whose local bounds do not span the whole parent model box.
    if vs + 12 * vertex_count <= len(data) and bb + 4 * brush_count <= len(data):
        starts = sorted((u32(data, bb + 4 * i) & 0xFFFFFF, i)
                        for i in range(brush_count))
        if starts and starts[0][0] == 0 and all(
                starts[i][0] != starts[i - 1][0] for i in range(1, len(starts))):
            for i, (start, brush_index) in enumerate(starts[:4]):
                end = starts[i + 1][0] if i + 1 < len(starts) else vertex_count
                if end <= start or end > vertex_count:
                    continue
                run = [f32s(data, vs + 12 * q, 3) for q in range(start, end)]
                actual = [min(v[a] for v in run) for a in range(3)]
                actual += [max(v[a] for v in run) for a in range(3)]
                hit = data.find(struct.pack("<6f", *actual), bb)
                if hit >= 0:
                    candidate = hit - 28 * brush_index
                    if candidate >= bb and candidate + 28 * brush_count <= len(data):
                        attempts.append(("invariant_exact", vs, bb, candidate))

    scan_end = min(len(data) - 28 * brush_count, bb + 8192)
    if np is not None and scan_end >= bb + 24:
        # Find plausible AABB rows in one vectorized pass, then run the exact
        # vertex/AABB check only on those offsets. This keeps the fallback
        # locator quick for models without absolute pointers.
        raw = np.frombuffer(data, dtype="<f4", count=(scan_end - bb) // 4,
                            offset=bb)
        windows = np.lib.stride_tricks.sliding_window_view(raw, 6)
        model_mins = np.asarray(model["mins"], dtype=np.float32)
        model_maxs = np.asarray(model["maxs"], dtype=np.float32)
        plausible = (np.isfinite(windows).all(axis=1) &
                     (windows[:, 3:] >= windows[:, :3]).all(axis=1) &
                     (windows[:, :3] >= model_mins - 0.01).all(axis=1) &
                     (windows[:, :3] <= model_maxs + 0.01).all(axis=1) &
                     (windows[:, 3:] >= model_mins - 0.01).all(axis=1) &
                     (windows[:, 3:] <= model_maxs + 0.01).all(axis=1))
        attempts.extend(("invariant", vs, bb, bb + 4 * int(i))
                        for i in np.flatnonzero(plausible))
    else:
        attempts.extend(("invariant", vs, bb, ab)
                        for ab in range(bb, scan_end + 1, 4))

    for mode, candidate_vs, candidate_bb, candidate_ab in attempts:
        arrays = verify_brush_arrays(data, candidate_vs, candidate_bb,
                                     candidate_ab, vertex_count, brush_count,
                                     pointer_backed=mode == "pointer")
        if arrays is None:
            continue
        field_a = None
        if pointers.get(440) is not None and pointers[440] + 4 * brush_count <= len(data):
            field_a = [u32(data, pointers[440] + 4 * i) for i in range(brush_count)]
            for item in arrays:
                item["field_a"] = field_a[item["brush_index"]]
        result.update({
            "status": "decoded",
            "mode": mode,
            "vertex_offset": candidate_vs,
            "brush_run_offset": candidate_bb,
            "bounds_offset": candidate_ab,
            "brushes": arrays,
        })
        return result
    result["status"] = "unlocated"
    return result


def cross(a, b):
    return [a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0]]


def sub(a, b):
    return [a[i] - b[i] for i in range(3)]


def dot(a, b):
    return sum(a[i] * b[i] for i in range(3))


def convex_hull_faces(points):
    from cw_brush_hull import checked_hull
    return checked_hull(points)[0].tolist()


def safe_name(value):
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value))[:100]


def model_label(model, index):
    return model.get("name") or model.get("name_hash") or f"model_{index:04d}"


def write_mesh_obj(root, models, destination):
    path = destination / "clip-mesh-candidates.obj"
    reports = []
    total_vertices = 0
    total_faces = 0
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write("# Black Ops Cold War clip_map candidate geometry\n")
        stream.write("# Coordinates are game inches; topology and winding are provisional.\n")
        vertex_base = 1
        for index, model in enumerate(models):
            data = payload_bytes(root, model)
            try:
                vertices, triangles, report = decode_mesh(data, model)
                if not report['complete_vertex_coverage'] or report['overlapping_vertex_slots']:
                    raise ValueError('Quantized groups do not partition source vertex records')
            except (ValueError, struct.error) as exc:
                reports.append({"index": index, "label": model_label(model, index),
                                "status": "unsupported", "reason": str(exc)})
                continue
            label = model_label(model, index)
            object_name = f"mesh_{index:04d}_{safe_name(label)}"
            stream.write(f"\no {object_name}\n")
            stream.write(f"g {object_name}\n")
            for vertex in vertices:
                stream.write("v " + " ".join(format(x, ".17g") for x in vertex) + "\n")
            for triangle in triangles:
                stream.write("f " + " ".join(str(vertex_base + q) for q in triangle) + "\n")
            report.update({"index": index, "label": label, "status": "decoded",
                           "object": object_name, "name_hash": model.get("name_hash"),
                           "payload_sha256": hashlib.sha256(data).hexdigest(),
                           "quality_status": "candidate_bounds_match" if report['bounds_within_one_quantum'] else "candidate_bounds_mismatch"})
            reports.append(report)
            vertex_base += len(vertices)
            total_vertices += len(vertices)
            total_faces += len(triangles)
    return path, reports, total_vertices, total_faces


def material_color(contents):
    # Stable, readable colors derived from the contents mask.
    r = ((contents * 37) & 255) / 255.0
    g = ((contents * 73 + 80) & 255) / 255.0
    b = ((contents * 109 + 160) & 255) / 255.0
    return max(0.2, r), max(0.2, g), max(0.2, b)


def write_float_mesh_obj(root, models, destination):
    from decode_cw_float_collision_triangles import decode
    path = destination / 'float-collision-triangles.obj'
    rows, unsupported = [], []
    vertex_base = 1
    with path.open('w', encoding='utf-8', newline='\n') as stream:
        stream.write('# Captured float vertices and triangle indices, including duplicates and degenerates.\n')
        stream.write('# Captured coordinates; no placement applied. Filter IDs are capture-specific, not material names.\n')
        for index, model in enumerate(models):
            raw = payload_bytes(root, model)
            try:
                vertices, triangles, report = decode(raw, model)
            except (ValueError, struct.error) as exc:
                unsupported.append(dict(model_index=index, reason=str(exc)))
                continue
            name = f"{safe_name(model_label(model, index))}_collision_m{index}_float"
            stream.write(f'\no {name}\n')
            for v in vertices:
                stream.write('v '+' '.join(format(x, '.9g') for x in v)+'\n')
            for group in report['groups']:
                stream.write(f"g {name}_group{group['index']}_filter{group['filter_index']}\n")
                first = group['first_export_triangle']
                for triangle in triangles[first:first+group['triangle_count']]:
                    stream.write('f '+' '.join(str(vertex_base+i) for i in triangle)+'\n')
            report.update(model_index=index, name_hash=model['name_hash'], object=name,
                payload_sha256=hashlib.sha256(raw).hexdigest(),
                representation='captured_float_triangles', geometry_modified=False)
            rows.append(report)
            vertex_base += len(vertices)
    document = dict(obj=str(path.resolve()), models=rows, unsupported=unsupported,
        models_decoded=len(rows), vertices=sum(r['vertices'] for r in rows),
        triangles=sum(r['triangles'] for r in rows),
        degenerate_triangles_preserved=sum(r['degenerate_triangles'] for r in rows),
        max_group_bounds_violation=max((r['max_group_bounds_violation'] for r in rows), default=0))
    (destination/'float-collision-index.json').write_text(json.dumps(document, indent=2)+'\n')
    return document


def write_brush_obj(root, models, destination):
    decoded = []
    summary = Counter()
    materials = set()
    for index, model in enumerate(models):
        data = payload_bytes(root, model)
        result = decode_brushes(data, model)
        if result is None:
            continue
        result.update({"index": index, "label": model_label(model, index),
                       "name_hash": model.get("name_hash")})
        result["payload_sha256"] = hashlib.sha256(data).hexdigest()
        decoded.append(result)
        summary[result["status"]] += 1

    obj_path = destination / "brush-geometry-separated.obj"
    mtl_path = destination / "brush-geometry-separated.mtl"
    index_path = destination / "brush-index.json"
    brush_index = []
    total_brushes = 0
    hull_count = 0
    failed = []
    last_progress = time.monotonic()
    vertex_base = 1
    with obj_path.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write("# Black Ops Cold War clip_map brush candidates\n")
        stream.write("# One object per checked captured-vertex hull; topology reconstructed, outward winding checked.\n")
        stream.write("mtllib brush-geometry-separated.mtl\n")
        for result in decoded:
            if result["status"] != "decoded":
                continue
            model_tag = f"model_{result['index']:04d}_{safe_name(result['label'])}"
            for brush in result["brushes"]:
                points = brush["vertices"]
                from cw_brush_hull import checked_hull
                try:
                    face_array, _, quality = checked_hull(points)
                    faces = face_array.tolist()
                except (ValueError, RuntimeError) as exc:
                    failed.append(dict(model_index=result['index'], brush_index=brush['brush_index'],
                        reason=str(exc), vertices=points, status='hull_failed_source_points_preserved'))
                    continue
                representation = "captured_vertex_hull"
                hull_count += 1
                contents = brush["collision_flags_raw"]
                material = f"collision_flags_{contents:08x}"
                materials.add(contents)
                object_name = f"{model_tag}_brush_{brush['brush_index']:04d}"
                stream.write(f"\no {object_name}\n")
                stream.write(f"g {model_tag}\nusemtl {material}\n")
                for point in points:
                    stream.write("v " + " ".join(format(x, ".9g") for x in point) + "\n")
                for face in faces:
                    stream.write("f " + " ".join(str(vertex_base + q) for q in face) + "\n")
                mins = brush["mins"]
                maxs = brush["maxs"]
                brush_index.append({
                    "model_index": result["index"],
                    "model": result["label"],
                    "name_hash": result["name_hash"],
                    "brush_index": brush["brush_index"],
                    "object": object_name,
                    "contents": f"0x{brush['contents']:08x}",
                    "packed_flags_and_plane_count": f"0x{brush['packed_flags_and_plane_count']:08x}",
                    "collision_flags_raw": f"0x{contents:08x}",
                    "nonaxial_plane_count": brush["nonaxial_plane_count"],
                    "field_a": brush["field_a"],
                    "mins": mins,
                    "maxs": maxs,
                    "representation": representation,
                    "quality": quality,
                    "vertex_start": brush["vertex_start"],
                    "payload_sha256": result["payload_sha256"],
                    "vertex_count": len(points),
                })
                vertex_base += len(points)
                total_brushes += 1
                if time.monotonic()-last_progress > 10:
                    print(f'Brush hulls: {total_brushes} exported, {len(failed)} failed', flush=True)
                    last_progress = time.monotonic()

    with mtl_path.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write("# Contents masks used by brush-geometry-separated.obj\n")
        for contents in sorted(materials):
            r, g, b = material_color(contents)
            stream.write(f"newmtl collision_flags_{contents:08x}\nKd {r:.4f} {g:.4f} {b:.4f}\n\n")

    index_document = {
        "source": str(root.resolve()),
        "status": "Checked hulls of captured vertices; reconstructed topology, not original face indices or stored-plane intersections.",
        "coordinate_frame": "Captured coordinates; no placement inferred or applied.",
        "models_considered": len(models),
        "model_status": dict(summary),
        "decoded_models": sum(1 for x in decoded if x["status"] == "decoded"),
        "brushes": total_brushes,
        "convex_hull_brushes": hull_count,
        "aabb_fallback_brushes": 0,
        "failed_brushes": failed,
        "source_brushes": total_brushes + len(failed),
        "contents_masks": [f"0x{x:08x}" for x in sorted(materials)],
        "obj": str(obj_path.resolve()),
        "mtl": str(mtl_path.resolve()),
        "items": brush_index,
    }
    index_path.write_text(json.dumps(index_document, indent=2) + "\n", encoding="utf-8")
    return obj_path, mtl_path, index_path, index_document


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else None)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    models = json.loads((args.capture / "clip_map_models.json").read_text(encoding="utf-8"))["models"]

    mesh_path, mesh_reports, mesh_vertices, mesh_faces = write_mesh_obj(
        args.capture, models, args.output_dir)
    brush_obj, brush_mtl, brush_index_path, brush_document = write_brush_obj(
        args.capture, models, args.output_dir)
    float_document = write_float_mesh_obj(args.capture, models, args.output_dir)

    decoded_meshes = [x for x in mesh_reports if x["status"] == "decoded"]
    represented = ({r['index'] for r in decoded_meshes}
                   | {r['model_index'] for r in brush_document['items']}
                   | {r['model_index'] for r in float_document['models']})
    mesh_report = {
        "source": str(args.capture.resolve()),
        "status": "Source-coordinate geometry; no instance placement applied. See per-branch accuracy limits.",
        "float_triangles": {k: v for k, v in float_document.items() if k not in ('models', 'unsupported')},
        "coverage": {
            "source_models": len(models), "models_with_exported_geometry": len(represented),
            "models_without_supported_geometry": len(models)-len(represented),
            "unrepresented_models": [{"index": i, "name_hash": m['name_hash'], "name": model_label(m,i)}
                                     for i,m in enumerate(models) if i not in represented],
            "meaning": "Union across branches, not a claim of complete per-model decoding. Mixed brush/float models counted once."
        },
        "mesh": {
            "models_total": len(models),
            "models_decoded": len(decoded_meshes),
            "models_unsupported": len(models) - len(decoded_meshes),
            "bounds_matches": sum(x.get("bounds_within_one_quantum", False) for x in decoded_meshes),
            "complete_vertex_partitions": sum(x.get("complete_vertex_coverage", False) and
                                               x.get("overlapping_vertex_slots", 1) == 0
                                               for x in decoded_meshes),
            "vertices": mesh_vertices,
            "triangle_candidates": mesh_faces,
            "obj": str(mesh_path.resolve()),
            "models": mesh_reports,
        },
        "brush": {
            "index": str(brush_index_path.resolve()),
            "obj": str(brush_obj.resolve()),
            "mtl": str(brush_mtl.resolve()),
            "models_considered": brush_document["models_considered"],
            "model_status": brush_document["model_status"],
            "brushes": brush_document["brushes"],
            "convex_hull_brushes": brush_document["convex_hull_brushes"],
            "aabb_fallback_brushes": brush_document["aabb_fallback_brushes"],
            "failed_brushes": len(brush_document["failed_brushes"]),
        },
    }
    report_path = args.output_dir / "export-report.json"
    report_path.write_text(json.dumps(mesh_report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "output": str(args.output_dir.resolve()),
        "mesh_decoded": len(decoded_meshes),
        "mesh_bounds_matches": mesh_report["mesh"]["bounds_matches"],
        "mesh_partitions": mesh_report["mesh"]["complete_vertex_partitions"],
        "brush_models": brush_document["model_status"],
        "brushes": brush_document["brushes"],
        "hulls": brush_document["convex_hull_brushes"],
        "aabb_fallbacks": brush_document["aabb_fallback_brushes"],
        "failed_brushes": len(brush_document["failed_brushes"]),
        "float_models": float_document['models_decoded'],
        "float_triangles": float_document['triangles'],
    }, indent=2))
    if brush_document['failed_brushes']:
        raise RuntimeError('Incomplete brush hull export; see source points and reasons in brush-index.json')


if __name__ == "__main__":
    main()
