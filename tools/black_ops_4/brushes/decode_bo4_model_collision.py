"""Recover BO4 model collision triangles and retain their model attachments.

Triangle vertices are reconstructed from captured plane/barycentric equations,
not copied from a render mesh. Bone references and unverified placements stay
explicit. No convex hull replacement of potentially concave model collision.
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
from collections import Counter
import hashlib
import json
from pathlib import Path
import struct
import numpy as np


def decode(root):
    probe_path = root/'model_collision_probe.json'
    doc = json.loads(probe_path.read_text())
    if doc['schema'] != 'greyhound-bo4-model-collision-probe-v2' or not doc['readback_unchanged']:
        raise ValueError('Requires complete model collision probe v2')
    if doc['unresolved_references']: raise ValueError('Unresolved source model references')
    headers = (root/'collision_surface_headers.bin').read_bytes()
    raw_triangles = (root/'model_collision_triangles.bin').read_bytes()
    model_rows, surface_rows = [], []
    triangle_cursor = 0
    triangle_path = root/'decoded_model_collision_triangles.f64'
    with triangle_path.open('wb') as output:
        for model in doc['models']:
            col = model['collision']
            out = {'pointer': model['pointer'], 'hash': model['hash'],
                   'name': model.get('name'), 'surface_indices': [], 'source_status': col['status']}
            if col['status'] == 'empty':
                model_rows.append(out); continue
            if col['status'] != 'captured_stable': raise ValueError('Missing model surfaces')
            surface_start = col['byte_offset']
            for tri_record in col['surfaces']:
                if tri_record['status'] != 'captured_stable': raise ValueError('Missing model triangles')
                sh = headers[surface_start+tri_record['surface']*56:surface_start+(tri_record['surface']+1)*56]
                count = tri_record['count']; offset = tri_record['byte_offset']
                if len(sh) != 56 or struct.unpack_from('<I',sh,16)[0] != count:
                    raise ValueError('Surface header/triangle count differs')
                raw = raw_triangles[offset:offset+count*48]
                if len(raw) != count*48: raise ValueError('Truncated source triangles')
                equations = np.frombuffer(raw,dtype='<f4').reshape(-1,3,4).astype(float)
                if not np.isfinite(equations).all(): raise ValueError('Nonfinite triangle equations')
                matrix = equations[:,:,:3]
                if np.any(np.linalg.det(matrix)==0): raise ValueError('Singular triangle equations')
                # n.p=d, s.p=sw+u, t.p=tw+v at barycentrics (0,0),(1,0),(0,1).
                rhs = np.repeat(equations[:,:,3:4],3,axis=2)
                rhs[:,1,1] += 1; rhs[:,2,2] += 1
                points = np.transpose(np.linalg.solve(matrix,rhs),(0,2,1))
                residual = float(np.max(abs(matrix@np.transpose(points,(0,2,1))-rhs)))
                if not np.isfinite(points).all() or residual > 1e-5:
                    raise ValueError('Triangle equation inversion failed')
                bounds = np.array(struct.unpack_from('<6f',sh,20))
                reconstructed = np.r_[points.min((0,1)),points.max((0,1))]
                margin_error = float(np.max(abs(bounds-reconstructed-[-.001,-.001,-.001,.001,.001,.001])))
                outside = float(max(0.,np.max(bounds[:3]-points),np.max(points-bounds[3:])))
                face_normals = np.cross(points[:,1]-points[:,0],points[:,2]-points[:,0])
                direction = np.einsum('ij,ij->i',face_normals,equations[:,0,:3])
                # Preserve the captured outward plane convention.
                flip = direction < 0
                points[flip] = points[flip][:,[0,2,1]]
                sid = len(surface_rows); out['surface_indices'].append(sid)
                surface_rows.append({'index': sid, 'model_pointer': model['pointer'],
                    'surface_in_model': tri_record['surface'], 'triangle_start': triangle_cursor,
                    'triangle_count': count, 'source_triangles_byte_offset': offset,
                    'bone_index_raw': struct.unpack_from('<i',sh,44)[0],
                    'contents_raw': hex(struct.unpack_from('<I',sh,48)[0]),
                    'flags_raw': hex(struct.unpack_from('<I',sh,52)[0]),
                    'bounds': bounds.tolist(), 'reconstructed_bounds': reconstructed.tolist(),
                    'bounds_margin_error': margin_error, 'vertex_outside_bounds': outside,
                    'equation_residual': residual, 'winding_flips': int(flip.sum())})
                output.write(points.astype('<f8').tobytes()); triangle_cursor += count
            model_rows.append(out)
    instances_raw = (root/doc['instance_file']).read_bytes()
    u = np.frombuffer(instances_raw,dtype='<u4').reshape(-1,24)
    f = u.view('<f4').astype(float)
    ptrs = u[:,:2].copy().view('<u8').ravel()
    byptr = {int(m['pointer'],16):m for m in model_rows}
    instances = []
    for i,row in enumerate(f):
        model = byptr[int(ptrs[i])]; inverse_basis = row[6:15].reshape(3,3); origin = row[3:6]
        gram = inverse_basis@inverse_basis.T; scale_sq = float(np.trace(gram)/3)
        if scale_sq <= 0 or not np.isfinite(inverse_basis).all(): raise ValueError('Invalid model basis')
        similarity_error = float(np.max(abs(gram/scale_sq-np.eye(3))))
        forward = np.linalg.inv(inverse_basis)
        if np.linalg.det(forward) <= 0: raise ValueError('Mirrored or singular model transform')
        world_matrix = np.eye(4); world_matrix[:3,:3] = forward; world_matrix[:3,3] = origin
        item = {'index': i,'model_pointer': model['pointer'], 'position': origin.tolist(),
            'world_to_local_linear': inverse_basis.tolist(),
            'matrix_world': world_matrix.tolist(), 'flags_raw': hex(int(u[i,2])),
            'captured_world_bounds': row[15:21].tolist(),
            'uniform_scale': float(1/np.sqrt(scale_sq)),
            'similarity_transform_error': similarity_error,
            'transform_convention': 'world_column = matrix_world @ local_homogeneous; stored basis maps world delta to local; bone transform separate'}
        surfaces = [surface_rows[s] for s in model['surface_indices']]
        if surfaces:
            bb = np.array([s['bounds'] for s in surfaces])
            # Transform each surface AABB before union. Transforming the union
            # box invents corners between disconnected surfaces and overbounds.
            center = ((bb[:,:3]+bb[:,3:])/2)@forward.T+origin
            extent = ((bb[:,3:]-bb[:,:3])/2)@abs(forward.T)
            predicted = np.r_[(center-extent).min(0),(center+extent).max(0)]
            error = float(np.max(abs(predicted-row[15:21])))
            item['unposed_collision_bounds_error'] = error
            item['unposed_predicted_world_bounds'] = predicted.tolist()
            item['one_unit_world_expansion_residual'] = float(np.max(abs(
                row[15:21]-predicted-[-1,-1,-1,1,1,1])))
            item['placement_status'] = 'unposed_bounds_agree' if error<.01 else 'requires_pose_or_bounds_investigation'
        else: item['placement_status'] = 'no_collision_surfaces_in_model_header'
        instances.append(item)
    summary = {'referenced_models': len(model_rows), 'named_models': sum(bool(m['name']) for m in model_rows),
        'models_with_surfaces': sum(bool(m['surface_indices']) for m in model_rows),
        'surfaces': len(surface_rows),'reconstructed_triangles': triangle_cursor,'instances': len(instances),
        'max_equation_residual': max(s['equation_residual'] for s in surface_rows),
        'max_bounds_margin_error': max(s['bounds_margin_error'] for s in surface_rows),
        'max_vertex_outside_surface_bounds': max(s['vertex_outside_bounds'] for s in surface_rows),
        'surfaces_with_nonzero_bone': sum(s['bone_index_raw']!=0 for s in surface_rows),
        'placement_status': dict(Counter(i['placement_status'] for i in instances)),
        'max_similarity_transform_error': max(i['similarity_transform_error'] for i in instances)}
    files = [probe_path,root/'model_headers.bin',root/'collision_surface_headers.bin',
             root/'model_collision_triangles.bin',root/doc['instance_file'],triangle_path]
    result = {'schema':'greyhound-bo4-model-collision-data-v2','summary':summary,
        'files':{p.name:{'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in files},
        'triangle_file':triangle_path.name,'triangle_format':'little-endian float64 [triangle][3 vertices][xyz]',
        'models':model_rows,'surfaces':surface_rows,'instances':instances,
        'limitations':['Triangle vertices are recovered from float32 equations, not original authored coordinates',
                       'Bone references retained; pose transforms not yet traced. Inverse basis corrected and surface bounds transformed individually.',
                       'Unmatched instance bounds are not corrected or exported as verified clips',
                       'Contents and flags preserved raw; no CW interpretation']}
    (root/'model_collision_data.json').write_text(json.dumps(result,separators=(',',':'))+'\n')
    print(json.dumps(summary,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument('capture',type=Path)
    decode(parser.parse_args().capture)
