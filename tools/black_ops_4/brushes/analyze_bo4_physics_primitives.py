"""Record a cylinder interpretation of BO4 primitive records without promoting it to a decode.

The T6 enum is a reference lead, not proof for BO4. This report checks the BO4
record invariants and predicts analytic bounds for review; it writes no meshes.
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


REFERENCE = ('https://git.alterware.dev/zone/OpenAssetTools/compare/'
             'v0.21.2..af5e19b958d0c8b914eb0b75e3aea9a4d85dc81f')


def analyze(root):
    path = root/'model_physics_data.json'
    data = json.loads(path.read_text())
    if data['schema'] != 'greyhound-bo4-model-physics-data-v1':
        raise ValueError('Requires standalone physics decode v1')
    candidates = []
    for model in data['models']:
        for entry in model['entries']:
            if entry['status'] != 'raw_type_unresolved': continue
            f = np.array(entry['floats_uninterpreted'])
            if entry['type_raw'] != 3 or not np.isfinite(f).all():
                raise ValueError('Unexamined primitive record type or values')
            axes, center, dimensions = f[:9].reshape(3, 3), f[9:12], f[12:15]
            h, r1, r2 = dimensions
            residual = float(abs(axes @ axes.T-np.eye(3)).max())
            if min(dimensions) <= 0 or r1 != r2 or residual > 1e-5 or np.linalg.det(axes) <= 0:
                raise ValueError('Cylinder candidate invariants do not hold')
            # Candidate convention: row axes map canonical x/y/z into model
            # space. First dimension is axial half length; the others radii.
            # Retain the captured matrix, including its float32 rounding.
            extent = h*abs(axes[0]) + np.sqrt((r1*axes[1])**2 + (r2*axes[2])**2)
            candidates.append(dict(model_pointer=model['pointer'], model_hash=model['hash'],
                model_name=model['name'], entry_index=entry['index'], primitive_pointer=entry['pointer'],
                type_raw=3, interpretation_status='cylinder_candidate_runtime_dispatch_unverified',
                orientation_rows=axes.tolist(), center_model=center.tolist(),
                axial_half_length=float(h), radius=float(r1),
                local_bounds_candidate=np.r_[center-extent, center+extent].tolist(),
                orientation_orthogonality_error=residual,
                orientation_determinant=float(np.linalg.det(axes))))
    report = dict(schema='greyhound-bo4-physics-primitive-analysis-v1',
        source_data_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        reference_lead=dict(url=REFERENCE, scope='T6 type 3 is cylinder; not direct BO4 evidence'),
        summary=dict(records=len(candidates), exact_equal_radial_pairs=len(candidates),
                     maximum_orientation_error=max(c['orientation_orthogonality_error'] for c in candidates)),
        candidates=candidates,
        limitations=['BO4 type dispatch has not been traced',
                     'Equal radii and rigid axes support but do not uniquely prove cylinders',
                     'Triangle-collision or render bounds need not match physics geometry',
                     'Analytic bounds are predictions; no primitive meshes exported or omissions hidden'])
    (root/'model_physics_primitive_analysis.json').write_text(json.dumps(report, separators=(',', ':'))+'\n')
    print(json.dumps(report['summary'], indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('capture', type=Path)
    analyze(parser.parse_args().capture)
