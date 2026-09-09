"""Decode float3/byte-index collision groups from saved payloads.

Layout follows C88C390/C88CB50; filter indices remain raw until joined to a
table captured with the payload. No deduplication, normalization or placement.
"""
import argparse
import collections
import json
import math
import struct
from pathlib import Path


def compact_offsets(raw, model, nv, ni):
    """Scoped compact layout with no intervening brush acceleration block."""
    from export_cross_map_cw_geometry import decode_brushes
    if struct.unpack_from('<Q', raw, 424)[0]:
        raise ValueError('compact layout has a brush acceleration pointer')
    nb = struct.unpack_from('<I',raw,368)[0]
    if nb:
        if nb*28 > len(raw):
            raise ValueError('brush count exceeds payload extent')
        brush = decode_brushes(raw, model)
        if not brush or brush.get('status') != 'decoded':
            raise ValueError('compact preceding brush arrays unresolved')
        vo = brush['bounds_offset']+28*nb
    else:
        if any(struct.unpack_from('<2I',raw,360)):
            raise ValueError('nonempty brush arrays without brushes')
        vo = 520
    io = vo+12*nv
    return [vo,io,(io+ni+7)&~7]


def decode(raw, model):
    if raw[336:360] != struct.pack('<6f', *(model['mins']+model['maxs'])):
        raise ValueError('different shape layout')
    if len(raw) < 520:
        raise ValueError('truncated shape header')
    nv, ni, ng, mask = struct.unpack_from('<4I', raw, 376)
    if not ng:
        raise ValueError('empty triangle branch')
    base = int(model['payload']['address'], 16)
    pointers = [struct.unpack_from('<Q', raw, at)[0] for at in (472,480,504)]
    mode = 'pointer'
    if not any(pointers):
        offsets = compact_offsets(raw,model,nv,ni)
        mode = 'compact_after_brush_bounds'
    elif not all(pointers):
        raise ValueError('partial triangle pointers')
    else:
        offsets = [p-base for p in pointers]
    if not all(0 <= o and o+n <= len(raw) for o,n in zip(offsets,(12*nv,ni,32*ng))):
        raise ValueError('triangle arrays outside payload')
    vo, io, go = offsets
    vertices = list(struct.iter_unpack('<3f', raw[vo:vo+12*nv]))
    if not all(math.isfinite(v) for p in vertices for v in p):
        raise ValueError('nonfinite vertex')
    groups, triangles, covered = [], [], collections.Counter()
    max_violation = 0.
    for index in range(ng):
        bounds = struct.unpack_from('<6f', raw, go+32*index)
        if not all(math.isfinite(v) for v in bounds) or any(bounds[a]>bounds[a+3] for a in range(3)):
            raise ValueError('invalid group bounds')
        word = struct.unpack_from('<Q', raw, go+32*index+24)[0]
        start_vertex = word & 0x7fffff
        start_triangle = (word >> 23) & 0x3ffffff
        count = (word >> 49) & 31
        filter_index = word >> 54
        if 3*(start_triangle+count) > ni:
            raise ValueError('group index span out of range')
        local = raw[io+3*start_triangle:io+3*(start_triangle+count)]
        ids = [start_vertex+x for x in local]
        if any(v >= nv for v in ids):
            raise ValueError('vertex index out of range')
        covered.update(range(3*start_triangle,3*(start_triangle+count)))
        violation = max((max(bounds[a]-vertices[v][a],vertices[v][a]-bounds[a+3],0.)
                         for v in ids for a in range(3)), default=0.)
        max_violation = max(max_violation, violation)
        first = len(triangles)
        triangles.extend(tuple(ids[i:i+3]) for i in range(0,len(ids),3))
        groups.append(dict(index=index, packed_word=hex(word), vertex_base=start_vertex,
            index_triangle_start=start_triangle, triangle_count=count, first_export_triangle=first,
            filter_index=filter_index, mins=bounds[:3],maxs=bounds[3:],bounds_violation=violation))
    if len(covered) != ni or any(n != 1 for n in covered.values()):
        raise ValueError('triangle groups do not partition the index array')
    if mode != 'pointer' and max_violation > 0:
        raise ValueError('compact vertices violate group bounds')
    degenerates = 0
    for t in triangles:
        a,b,c = [vertices[i] for i in t]
        u = [b[i]-a[i] for i in range(3)]; v = [c[i]-a[i] for i in range(3)]
        cross = [u[1]*v[2]-u[2]*v[1],u[2]*v[0]-u[0]*v[2],u[0]*v[1]-u[1]*v[0]]
        degenerates += all(x == 0 for x in cross)
    report = dict(mode=mode,vertices=nv,index_bytes=ni,triangles=len(triangles),groups=groups,
        aggregate_triangle_contents=hex(mask),brush_count=struct.unpack_from('<I',raw,368)[0],
        offsets=dict(vertices=vo,indices=io,groups=go),
        exact_index_partition=True,max_group_bounds_violation=max_violation,
        degenerate_triangles=degenerates,filter_indices=sorted({g['filter_index'] for g in groups}))
    return vertices, triangles, report


def write_obj(path, vertices, triangles, report):
    with path.open('w',encoding='utf-8') as f:
        f.write('# Captured float collision triangles; source coordinates, no placement applied.\n')
        f.write('# Filter indices are capture-specific. No recovered render materials.\n')
        for v in vertices:
            f.write('v '+' '.join(format(x,'.9g') for x in v)+'\n')
        for group in report['groups']:
            mask_tag = '_contents_'+group['filter_contents'][2:] if 'filter_contents' in group else ''
            f.write(f"g group_{group['index']}_filter_{group['filter_index']}{mask_tag}\n")
            start = group['first_export_triangle']
            for triangle in triangles[start:start+group['triangle_count']]:
                f.write('f '+' '.join(str(i+1) for i in triangle)+'\n')


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    models=json.loads((args.root/'clip_map_models.json').read_text())['models']
    rows=[];unsupported=collections.Counter()
    for index, model in enumerate(models):
        raw=(args.root/model['payload']['file']).read_bytes()
        try:vertices,triangles,row=decode(raw,model)
        except ValueError as exc:unsupported[str(exc)]+=1;continue
        row.update(model_index=index,name_hash=model['name_hash'])
        if index in (56,80,90,248,255,1336):
            obj=args.output/f'model_{index:04d}_{model["name_hash"]}_float_collision.obj'
            write_obj(obj,vertices,triangles,row);row['obj']=str(obj.resolve())
        rows.append(row)
    summary=dict(models=len(rows),triangles=sum(r['triangles'] for r in rows),
        layout_modes=dict(collections.Counter(r['mode'] for r in rows)),
        mixed_brush_triangle_models=sum(r['brush_count']>0 for r in rows),
        triangle_only_models=sum(r['brush_count']==0 for r in rows),
        exact_partitions=sum(r['exact_index_partition'] for r in rows),
        max_group_bounds_violation=max((r['max_group_bounds_violation'] for r in rows),default=0),
        degenerate_triangles=sum(r['degenerate_triangles'] for r in rows),unsupported=dict(unsupported))
    (args.output/'report.json').write_text(json.dumps(dict(summary=summary,models=rows),indent=2),encoding='utf-8')
    print(json.dumps(summary,indent=2))
