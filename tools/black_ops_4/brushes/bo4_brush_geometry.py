"""Certified convex partitions and read-back validation for BO4 tool brushes."""
import hashlib
from pathlib import Path
import numpy as np
from bo3_map_planes import CanonicalPlaneWriter, read_map_planes
from certified_brush_partition import compact_pieces


def partition(points, faces):
    return compact_pieces(points, faces, 64)


def serialize_piece(points, equations, matrix, material, contents, layer, ordinal):
    matrix = np.asarray(matrix, dtype=float)
    linear, translation = matrix[:3, :3], matrix[:3, 3]
    normals = equations[:, :3] @ np.linalg.inv(linear)
    lengths = np.linalg.norm(normals, axis=1)
    expected = np.column_stack((normals / lengths[:, None],
        (equations[:, 3] + normals @ translation) / lengths))
    transformed = points @ linear.T + translation
    if not 4 <= len(expected) <= 64:
        raise ValueError('Unsupported serialized brush face count')
    lines = CanonicalPlaneWriter().lines(expected, transformed.mean(0), material)
    parsed = np.asarray(read_map_planes('\n'.join(lines)))
    error = float(np.max(np.abs(parsed - expected)))
    outside = float(max(0, np.max(transformed @ parsed[:, :3].T - parsed[:, 3])))
    if not np.isfinite(parsed).all() or error > 1e-6 or outside > 1e-6:
        raise ValueError('Serialized partition moved outside its certified geometry')
    flags = 'contents ' + ' '.join(contents) + ';\n' if contents else ''
    text = f'// brush {ordinal}\n{{\nlayer "{layer}"\n' + flags + '\n'.join(lines) + '\n}\n'
    return text, dict(face_count=len(lines), serialized_plane_error=error,
        source_vertex_outside=outside, expected_planes=expected.tolist())


def publish_groups(output, map_name, prefix, rows, bodies, group_key):
    output.mkdir(parents=True, exist_ok=True)
    files = {}
    for group in sorted({r[group_key] for r in rows}):
        selected = [(r, b) for r, b in zip(rows, bodies) if r[group_key] == group]
        layers = {'000_Global'} | {r['layer'] for r, _ in selected}
        header = 'iwmap 4\n' + ''.join(f'"{l}" flags\n' for l in sorted(layers))
        path = output / (map_name + '_' + prefix + group + '.map')
        path.write_bytes((header + '// entity 0\n{\n"classname" "worldspawn"\n' +
            ''.join(b for _, b in selected) + '}\n').replace('\n', '\r\n').encode())
        actual = np.asarray(read_map_planes(path.read_text()))
        expected = np.vstack([r['expected_planes'] for r, _ in selected])
        if actual.shape != expected.shape or np.max(np.abs(actual - expected)) > 1e-6:
            raise ValueError('Published prefab planes differ from certified partitions')
        files[path.name] = dict(brushes=len(selected), sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        for row, _ in selected:
            row['prefab_file'] = path.name
    return files
