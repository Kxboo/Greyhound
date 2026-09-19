"""Build BO4-owned brush hulls using Greyhound's existing exact hull backend.

Outputs original points and face indices, with rejected/degenerate records
explicitly retained in the report. Does not assign CW contents meanings.
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
from cw_brush_hull import checked_hull


def build(root):
    metadata_path = root / 'collision_data.json'
    doc = json.loads(metadata_path.read_text())
    if not doc['summary'].get('ownership', {}).get('all_brushes_owned'):
        raise ValueError('Requires validated BO4 ownership')
    vertex_path = root / doc['brush_vertices']['file']
    if hashlib.sha256(vertex_path.read_bytes()).hexdigest() != doc['sources'][vertex_path.name]['sha256']:
        raise ValueError('Captured vertices changed')
    vertices = np.fromfile(vertex_path, dtype='<f4').reshape(-1, 3)
    hulls, rejected = [], []
    for brush in doc['brushes']:
        first, count = brush['vertex_start'], brush['vertex_count']
        points = vertices[first:first+count].astype(float)
        try:
            faces, _, evidence = checked_hull(points)
        except (ValueError, RuntimeError) as error:
            rejected.append({'brush_index': brush['index'], 'model_indices': brush['model_indices'],
                             'vertex_start': first, 'vertex_count': count, 'reason': str(error)})
            continue
        hulls.append({'brush_index': brush['index'], 'model_indices': brush['model_indices'],
            'coordinate_space': brush['coordinate_space'], 'contents_raw': brush['contents_raw'],
            'points': points.tolist(), 'faces': faces.tolist(), 'checks': evidence})
    summary = {'source_brushes': len(doc['brushes']), 'closed_hulls': len(hulls),
        'rejected_brushes': len(rejected),
        'world_hulls': sum(h['coordinate_space'] == 'world' for h in hulls),
        'inline_local_hulls': sum(h['coordinate_space'] == 'inline_model_local' for h in hulls),
        'source_coordinates_unchanged': True,
        'maximum_containment_error': max(h['checks']['max_source_point_outside_hull'] for h in hulls)}
    result = {'schema': 'greyhound-bo4-brush-hulls-v1', 'summary': summary,
        'source_metadata_sha256': hashlib.sha256(metadata_path.read_bytes()).hexdigest(),
        'hulls': hulls, 'rejected': rejected,
        'limitations': ['Raw BO4 contents preserved; tool-material mapping unresolved',
                       'Inline hulls remain local; authored and runtime placements are separate',
                       'Collision triangles and static-model collision are separate sources']}
    (root / 'brush_hulls.json').write_text(json.dumps(result, separators=(',', ':'))+'\n')
    print(json.dumps(summary, indent=2))
    print('Rejections:', json.dumps(rejected[:12], indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('capture', type=Path)
    build(parser.parse_args().capture)
