"""Decode Greyhound's standalone BO4 model physics export, offline.

Uses only files in this capture. Brush topology comes from captured vertices;
primitive records retain their bytes until their type/layout is established.
Instance bounds are diagnostic, never a reason to alter the captured shape.
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
from cw_brush_hull import checked_hull


def decode(root):
    report_file = root / 'model_physics_probe.json'
    doc = json.loads(report_file.read_text())
    if doc['schema'] != 'greyhound-bo4-model-physics-probe-v1':
        raise ValueError('Requires standalone model physics probe v1')
    if not doc['readback_unchanged'] or doc['unresolved_references']:
        raise ValueError('Incomplete source references')
    blob = (root / 'model_physics.bin').read_bytes()
    headers = (root / doc['header_file']).read_bytes()

    def span(ref, pointer, size):
        if int(ref['pointer'], 16) != pointer or ref['bytes'] != size:
            raise ValueError('Captured reference disagrees with source pointer/count')
        if size == 0 and ref['status'] == 'empty':
            return b''
        if ref['status'] != 'captured_stable' or ref['file'] != 'model_physics.bin':
            raise ValueError('Missing stable geometry span')
        start = ref['byte_offset']
        if start < 0 or start + size > len(blob):
            raise ValueError('Geometry span outside captured binary')
        return blob[start:start+size]

    models = []
    for model in doc['models']:
        p = model['physics']
        row = {k: model[k] for k in ('pointer', 'hash', 'slot')}
        row.update(name=model.get('name'), source_status=p['status'], entries=[])
        start, size = model['header_offset'], model['header_bytes']
        header = headers[start:start+size]
        if len(header) != 336 or size != 336:
            raise ValueError('Incomplete model header')
        root_ptr = struct.unpack_from('<Q', header, 0x60)[0]
        if root_ptr != int(p['pointer'], 16):
            raise ValueError('Model header/root pointer mismatch')
        if p['status'] == 'not_present':
            if root_ptr: raise ValueError('Nonzero root declared absent')
            models.append(row)
            continue
        if p['status'] != 'captured':
            row['decode_status'] = 'incomplete_source'
            models.append(row)
            continue
        rh = span(p['root'], root_ptr, 32)
        list_ptr = struct.unpack_from('<Q', rh)[0]
        listing = span(p['list'], list_ptr, 24)
        count, contents, entries_ptr = struct.unpack_from('<IIQ', listing)
        if count != p['entry_count'] or count != len(p['entries']):
            raise ValueError('Geometry list count mismatch')
        table = span(p['entry_table'], entries_ptr, count*16)
        row.update(root_bytes_hex=rh.hex(), list_bytes_hex=listing.hex(),
                   contents_raw=hex(contents), decode_status='decoded')
        for i, entry in enumerate(p['entries']):
            brush_ptr, primitive_ptr = struct.unpack_from('<2Q', table, i*16)
            if (entry['index'] != i or brush_ptr != int(entry['brush_pointer'], 16)
                    or primitive_ptr != int(entry['primitive_pointer'], 16)):
                raise ValueError('Geometry entry pointer mismatch')
            item = dict(index=i, kind=entry['kind'])
            try:
                if brush_ptr and not primitive_ptr:
                    bh = span(entry['header'], brush_ptr, 64)
                    sp, vp = struct.unpack_from('<2Q', bh)
                    nv, ns = struct.unpack_from('<2H', bh, 56)
                    if nv != entry['vertex_count'] or ns != entry['side_count']:
                        raise ValueError('Brush count mismatch')
                    vr = span(entry['vertices'], vp, nv*12)
                    sr = span(entry['sides'], sp, ns*20)
                    points = np.frombuffer(vr, dtype='<f4').reshape(-1, 3).astype(float)
                    bounds = np.r_[struct.unpack_from('<3f', bh, 16), struct.unpack_from('<3f', bh, 32)]
                    if not nv or not np.isfinite(points).all() or not np.isfinite(bounds).all():
                        raise ValueError('Empty or nonfinite brush')
                    bound_error = float(abs(bounds - np.r_[points.min(0), points.max(0)]).max())
                    sides = [dict(plane=struct.unpack_from('<4f', sr, j*20),
                                  material_raw=struct.unpack_from('<I', sr, j*20+16)[0]) for j in range(ns)]
                    side_outside = 0.
                    if ns:
                        planes = np.array([s['plane'] for s in sides])
                        if not np.isfinite(planes).all(): raise ValueError('Nonfinite brush side')
                        side_outside = float(max(0., (points @ planes[:, :3].T - planes[:, 3]).max()))
                    item.update(pointer=hex(brush_ptr), source_header_hex=bh.hex(),
                                points=points.tolist(), sides=sides, bounds=bounds.tolist(),
                                vertex_count=nv, side_count=ns,
                                contents_raw=hex(struct.unpack_from('<I', bh, 28)[0]),
                                axial_materials_raw=struct.unpack_from('<6H', bh, 44),
                                source_bounds_error=bound_error,
                                max_source_vertex_outside_side=side_outside)
                    faces, _, checks = checked_hull(points)
                    item.update(status='decoded_checked_hull', faces=faces.tolist(), hull_checks=checks)
                elif primitive_ptr and not brush_ptr:
                    raw = span(entry['record'], primitive_ptr, 64)
                    item.update(pointer=hex(primitive_ptr), status='raw_type_unresolved',
                                type_raw=struct.unpack_from('<I', raw)[0], bytes_hex=raw.hex(),
                                floats_uninterpreted=struct.unpack_from('<15f', raw, 4))
                else:
                    raise ValueError('Unknown geometry entry pointer combination')
            except ValueError as error:
                item.update(status='unresolved', reason=str(error))
            row['entries'].append(item)
        models.append(row)

    raw_instances = (root / doc['instance_file']).read_bytes()
    if doc['instance_stride'] != 96 or len(raw_instances) != doc['instance_count']*96:
        raise ValueError('Incomplete instance table')
    u = np.frombuffer(raw_instances, dtype='<u4').reshape(-1, 24)
    f = u.view('<f4').astype(float)
    pointers = u[:, :2].copy().view('<u8').ravel()
    by_ptr = {int(m['pointer'], 16): m for m in models}
    instances = []
    for i, fields in enumerate(f):
        model = by_ptr[int(pointers[i])]
        if model['source_status'] == 'not_present': continue
        inv = fields[6:15].reshape(3, 3)
        position = fields[3:6]
        if not np.isfinite(fields[3:21]).all() or np.linalg.det(inv) <= 0:
            raise ValueError('Invalid model transform or bounds')
        forward = np.linalg.inv(inv)
        matrix = np.eye(4)
        matrix[:3, :3], matrix[:3, 3] = forward, position
        gram = inv @ inv.T
        scale2 = np.trace(gram)/3
        bounds = fields[15:21]
        row = dict(index=i, model_pointer=model['pointer'], matrix_world=matrix.tolist(),
                   world_to_local_linear=inv.tolist(), flags_raw=hex(int(u[i, 2])),
                   captured_world_bounds=bounds.tolist(), uniform_scale=float(1/np.sqrt(scale2)),
                   similarity_transform_error=float(abs(gram/scale2-np.eye(3)).max()),
                   transform_convention='world_column = matrix_world @ local_homogeneous')
        brushes = [e for e in model['entries'] if e['status'] == 'decoded_checked_hull']
        if brushes:
            points = np.concatenate([np.array(e['points']) for e in brushes]) @ forward.T + position
            outside = float(max(0., (bounds[:3]-points).max(), (points-bounds[3:]).max()))
            row.update(checked_brush_count=len(brushes), max_brush_vertex_outside_instance_bounds=outside,
                       placement_status='contained' if outside <= .01 else 'outside_bounds_review',
                       bounds_check_scope='Decoded brushes only; primitive records excluded')
        else:
            row['placement_status'] = 'no_decoded_brushes'
        instances.append(row)

    entries = [e for m in models for e in m['entries']]
    brushes = [e for e in entries if e['status'] == 'decoded_checked_hull']
    summary = dict(source_models=len(models), models_with_physics=sum(m['source_status'] != 'not_present' for m in models),
                   source_instances=doc['instance_count'], physics_instances=len(instances),
                   entry_status_counts=dict(Counter(e['status'] for e in entries)),
                   primitive_types_raw=dict(Counter(e['type_raw'] for e in entries if 'type_raw' in e)),
                   placement_status_counts=dict(Counter(i['placement_status'] for i in instances)),
                   checked_brush_instances=sum(i.get('checked_brush_count', 0) for i in instances),
                   max_brush_bounds_error=max((b['source_bounds_error'] for b in brushes), default=0),
                   max_vertex_outside_source_side=max((b['max_source_vertex_outside_side'] for b in brushes), default=0),
                   max_hull_containment_error=max((b['hull_checks']['max_source_point_outside_hull'] for b in brushes), default=0))
    names = ['model_physics_probe.json', 'model_physics.bin', doc['header_file'], doc['instance_file'], 'clipmap_header.bin']
    result = dict(schema='greyhound-bo4-model-physics-data-v1', summary=summary,
                  source_sha256={name: hashlib.sha256((root/name).read_bytes()).hexdigest() for name in names},
                  models=models, instances=instances,
                  scope='Standalone model-attached physics export; no terrain or triangle export dependency',
                  limitations=['Primitive types and remaining root/list fields unresolved',
                               'Raw contents/material numbers retained; BO3 gameplay conversion unverified',
                               'Instance bounds are diagnostic; no geometry clamping or inflation applied'])
    (root/'model_physics_data.json').write_text(json.dumps(result, separators=(',', ':'), allow_nan=False)+'\n')
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('capture', type=Path)
    decode(parser.parse_args().capture)
