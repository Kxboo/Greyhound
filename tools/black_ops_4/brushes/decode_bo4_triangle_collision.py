"""Decode BO4 collision surfaces, preserving original vertices and triangles.

Each surface references a triangle range and a separate vertex-index range.
The ranges and bounds are checked against all source records. Ownership and
material meanings are kept unresolved rather than inferred from Cold War.
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
from pathlib import Path
import numpy as np


def decode(root):
    probe = json.loads((root/'world_pools_probe.json').read_text())
    pool = next(p for p in probe['pools'] if p['pool_index'] == 11)
    if not pool['active_count_matches_directory'] or len(pool['assets']) != 1:
        raise ValueError('Ambiguous collision asset')
    tables = {t['label']: t for t in pool['assets'][0]['tables']}
    sources = {}
    def read(label, dtype):
        t = tables[label]
        if t['status'] != 'captured_stable' or not t['readback_unchanged']:
            raise ValueError('Source table was not captured stably')
        raw = (root/t['file']).read_bytes()
        if len(raw) != t['count']*t['stride']: raise ValueError('Source byte count differs')
        sources[label] = {**t, 'sha256': hashlib.sha256(raw).hexdigest()}
        return np.frombuffer(raw, dtype=dtype)
    records = read('bounds_candidate', '<u4').reshape(-1, 9)
    vertices = read('vertices_candidate', '<f4').reshape(-1, 3)
    triangles = read('triangles_candidate', '<u4').reshape(-1, 3)
    vertex_ids = read('indices_candidate_2A0', '<u4')
    if not np.isfinite(vertices).all() or np.any(vertex_ids >= len(vertices)) or np.any(triangles >= len(vertices)):
        raise ValueError('Invalid global collision vertices or indices')
    rows, tri_cursor, vertex_cursor = [], 0, 0
    for i, record in enumerate(records):
        ti, vi = int(record[6]), int(record[7])
        nt, nv, material = int(record[8]&255), int((record[8]>>8)&255), int(record[8]>>16)
        if ti != tri_cursor or vi != vertex_cursor or nt == 0 or nv == 0:
            raise ValueError('Surface ranges do not partition the source arrays')
        tri_cursor += nt; vertex_cursor += nv
        if tri_cursor > len(triangles) or vertex_cursor > len(vertex_ids):
            raise ValueError('Surface range exceeds source table')
        ids = vertex_ids[vi:vi+nv]; tris = triangles[ti:ti+nt]
        if set(ids.tolist()) != set(tris.ravel().tolist()):
            raise ValueError('Surface triangle vertices disagree with vertex list')
        points = vertices[ids]
        bounds = np.r_[points.min(0), points.max(0)]
        if not np.array_equal(bounds, record.view('<f4')[:6]):
            raise ValueError('Surface bounds do not exactly match captured vertices')
        rows.append({'index': i, 'bounds': bounds.tolist(), 'triangle_start': ti,
                     'triangle_count': nt, 'vertex_reference_start': vi,
                     'vertex_reference_count': nv, 'material_index_raw': material})
    if tri_cursor != len(triangles) or vertex_cursor != len(vertex_ids):
        raise ValueError('Trailing unused array data')
    vectors = vertices[triangles].astype(float)
    areas = np.linalg.norm(np.cross(vectors[:,1]-vectors[:,0], vectors[:,2]-vectors[:,0]), axis=1)*.5
    summary = {'surfaces': len(rows), 'vertices': len(vertices), 'triangles': len(triangles),
        'vertex_references': len(vertex_ids), 'ranges_partition_exactly': True,
        'all_surface_vertex_lists_match_triangles': True, 'all_bounds_match_exactly': True,
        'zero_area_triangles': int(np.sum(areas == 0)),
        'raw_material_index_min': min(r['material_index_raw'] for r in rows),
        'raw_material_index_max': max(r['material_index_raw'] for r in rows)}
    result = {'schema': 'greyhound-bo4-triangle-collision-v1', 'summary': summary,
        'sources': sources, 'surfaces': rows,
        'coordinate_policy': 'Unmodified source coordinates; world/instance ownership not yet traced',
        'topology_policy': 'Original triangle order and indices; no retriangulation or invented thickness',
        'material_policy': 'Raw u16 index; lookup table not yet captured'}
    (root/'triangle_collision.json').write_text(json.dumps(result,separators=(',',':'))+'\n')
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('capture', type=Path)
    decode(parser.parse_args().capture)
