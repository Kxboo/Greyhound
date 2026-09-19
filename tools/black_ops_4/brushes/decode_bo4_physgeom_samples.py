"""Validate model-attached brush/primitive lists in bounded Greyhound samples.

Only reads references inside a captured sample. Missing ranges remain missing.
Primitive type numbers and the remaining root fields are not guessed.
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
import struct
import numpy as np
from cw_brush_hull import checked_hull


def decode(root):
    probe = json.loads((root/'model_collision_probe.json').read_text())
    placed = json.loads((root/'model_collision_data.json').read_text())
    models = []
    for model in probe['models']:
        for target in model['targets']:
            if int(target['field_offset'],16) != 0x60: continue
            raw = (root/target['file']).read_bytes(); base = int(target['pointer'],16)
            def span(pointer, size):
                offset = pointer-base
                if offset<0 or offset+size>len(raw): raise ValueError('Reference outside captured sample')
                return raw[offset:offset+size]
            header = span(base,32)
            list_ptr = struct.unpack_from('<Q',header)[0]
            listing = span(list_ptr,24)
            count, contents, entries = struct.unpack_from('<IIQ',listing)
            if count>4096: raise ValueError('Geometry count outside measured limit')
            row = {'model_pointer':model['pointer'],'name':model.get('name'),'hash':model['hash'],
                   'source_file':target['file'],'source_sha256':hashlib.sha256(raw).hexdigest(),
                   'root_bytes_hex':header.hex(),'list_bytes_hex':listing.hex(),
                   'list_contents_raw':hex(contents),'entries':[]}
            for i in range(count):
                item = {'index':i}
                try:
                    brush, primitive = struct.unpack('<2Q',span(entries+i*16,16))
                    item.update(brush_pointer=hex(brush),primitive_pointer=hex(primitive))
                    if bool(brush)==bool(primitive): raise ValueError('Unknown geometry-entry pointer combination')
                    if brush:
                        bh = span(brush,64); sides,vertices=struct.unpack_from('<2Q',bh)
                        nv,ns=struct.unpack_from('<HH',bh,56)
                        points=np.frombuffer(span(vertices,nv*12),dtype='<f4').reshape(-1,3).astype(float)
                        bounds=np.r_[struct.unpack_from('<3f',bh,16),struct.unpack_from('<3f',bh,32)]
                        if not np.array_equal(bounds,np.r_[points.min(0),points.max(0)]):
                            raise ValueError('Brush bounds disagree with vertices')
                        planes=[]
                        if ns:
                            data=span(sides,ns*20)
                            planes=[{'plane':struct.unpack_from('<4f',data,j*20),
                                     'material_raw':struct.unpack_from('<I',data,j*20+16)[0]} for j in range(ns)]
                        faces,_,check=checked_hull(points)
                        item.update(kind='brush',status='decoded_checked_hull',points=points.tolist(),
                                    faces=faces.tolist(),bounds=bounds.tolist(),sides=planes,
                                    contents_raw=hex(struct.unpack_from('<I',bh,28)[0]),
                                    vertex_count=nv,side_count=ns,hull_checks=check)
                    else:
                        data=span(primitive,64)
                        item.update(kind='primitive',status='raw_type_unresolved',
                                    type_raw=struct.unpack_from('<I',data)[0],bytes_hex=data.hex(),
                                    floats_uninterpreted=struct.unpack_from('<15f',data,4))
                except ValueError as error:
                    item.update(status='unresolved',reason=str(error))
                row['entries'].append(item)
            brushes=[e for e in row['entries'] if e['status']=='decoded_checked_hull']
            row['placements']=[]
            if len(brushes)==count:
                for instance in placed['instances']:
                    if instance['model_pointer']!=model['pointer']:continue
                    matrix=np.array(instance['matrix_world']);all_points=[]
                    for brush in brushes:
                        all_points.append(np.array(brush['points'])@matrix[:3,:3].T+matrix[:3,3])
                    points=np.concatenate(all_points);bounds=np.array(instance['captured_world_bounds'])
                    outside=float(max(0.,(bounds[:3]-points).max(),(points-bounds[3:]).max()))
                    row['placements'].append({'instance_index':instance['index'],
                        'matrix_world':instance['matrix_world'],'source_flags_raw':instance['flags_raw'],
                        'max_vertex_outside_instance_bounds':outside,
                        'contents_match_except_low_two_bits':(int(instance['flags_raw'],16)&~3)==contents,
                        'note':'Containment check; instance bounds need not tightly enclose each physics brush'})
            models.append(row)
    entries=[e for m in models for e in m['entries']]
    summary={'sampled_models':len(models),'checked_brushes':sum(e['status']=='decoded_checked_hull' for e in entries),
             'raw_primitives':sum(e['status']=='raw_type_unresolved' for e in entries),
             'unresolved_entries':sum(e['status']=='unresolved' for e in entries)}
    result={'schema':'greyhound-bo4-physgeom-sample-decode-v1','summary':summary,'models':models,
            'scope':'Bounded +0x60 samples only; not a complete model physics capture',
            'limitations':['Primitive type numbers unresolved','Root fields beyond first geometry-list pointer unresolved',
                           'No global contents mapping inferred from one model/instance match']}
    (root/'physgeom_samples.json').write_text(json.dumps(result,separators=(',',':'))+'\n')
    print(json.dumps(summary,indent=2))
    for model in models: print(model['name'],json.dumps(model['placements']))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('capture',type=Path)
    decode(parser.parse_args().capture)
