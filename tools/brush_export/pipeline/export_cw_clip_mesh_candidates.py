"""Export scoped CW collision mesh candidates; strip topology/winding remain provisional."""
import argparse
import collections
import json
import struct
from pathlib import Path
from audit_cw_clip_payloads import read_logical


def decode(data, model, *, apply_axis_offsets=True):
    if data[356:380] != struct.pack('<6f', *model['mins'], *model['maxs']):
        raise ValueError('unsupported bounds layout')
    ng,n8,n16=struct.unpack_from('<3H',data,350)
    base16=(392+3*n8+1)&~1
    table=(392+3*n8+6*n16+3)&~3
    tail=struct.unpack_from('<I',data,344)[0]
    if table+4*ng+((tail+3)&~3)!=len(data):
        raise ValueError('unsupported section extent')
    vertices=[]; triangles=[]; groups=[]; coverage={1:collections.Counter(),2:collections.Counter()}
    for i in range(ng):
        w=struct.unpack_from('<I',data,table+4*i)[0]
        width=1 if w>>31 else 2
        strip=bool(w & (1<<30)); field=(w>>26)&15
        count=field+3 if strip else 3*(field+1)
        start=w&0x3fff
        if start+count>(n8 if width==1 else n16): raise ValueError('group out of range')
        coverage[width].update(range(start,start+count))
        at=(392 if width==1 else base16)+3*width*start
        raw=struct.unpack_from('<'+str(3*count)+('B' if width==1 else 'H'),data,at)
        axis_offsets=[32*((w>>(14+4*axis))&15) if width==1 and apply_axis_offsets else 0 for axis in range(3)]
        offset=len(vertices)
        for j in range(count):
            point=[]
            for axis in range(3):
                k=axis*count+j if strip else (j%3)*3*(field+1)+axis*(field+1)+j//3
                point.append(model['mins'][axis]+raw[k]/8+axis_offsets[axis])
            vertices.append(point)
        local=([(j,j+1,j+2) if j%2==0 else (j+1,j,j+2) for j in range(count-2)]
               if strip else [(j,j+1,j+2) for j in range(0,count,3)])
        triangles.extend(tuple(offset+k for k in t) for t in local)
        groups.append({'word':hex(w),'mode_candidate':'strip' if strip else 'triangle_batch',
                       'start':start,'count':count,'width':width,'axis_offsets':axis_offsets,'unknown_bits_14_25':(w>>14)&4095})
    if not vertices: raise ValueError('empty model')
    lo=[min(v[a] for v in vertices) for a in range(3)]
    hi=[max(v[a] for v in vertices) for a in range(3)]
    error=max(abs(bound[a]-model[key][a]) for bound,key in ((lo,'mins'),(hi,'maxs')) for a in range(3))
    degenerate=0
    for t in triangles:
        a,b,c=[vertices[i] for i in t]
        u=[b[i]-a[i] for i in range(3)]; v=[c[i]-a[i] for i in range(3)]
        cross=[u[1]*v[2]-u[2]*v[1],u[2]*v[0]-u[0]*v[2],u[0]*v[1]-u[1]*v[0]]
        degenerate+=sum(x*x for x in cross)==0
    report={'coordinate_axis_offsets_applied':apply_axis_offsets,'name':model['name'],'bounds_error':error,'bounds_within_one_quantum':error<=0.125,
            'vertex_records':len(vertices),'triangle_candidates':len(triangles),'degenerate_triangle_candidates':degenerate,
            'complete_vertex_coverage':all(len(coverage[w])==n for w,n in ((1,n8),(2,n16))),
            'overlapping_vertex_slots':sum(sum(v>1 for v in c.values()) for c in coverage.values()),
            'unresolved_tail_bytes':tail,'groups':groups}
    return vertices,triangles,report


def run(root,destination):
    destination.mkdir(parents=True,exist_ok=True)
    evidence=json.loads((root/'evidence.json').read_text())
    models=json.loads((root/'clip_map_models.json').read_text())['models']
    reports=[]; unsupported=[]
    for m in models:
        data=read_logical(root,evidence,m['payload']['file'])
        try: vertices,triangles,report=decode(data,m)
        except ValueError as exc:
            unsupported.append({'name':m['name'],'reason':str(exc)}); continue
        name=m['name']
        selected=name in [f'tet_railing_balcony_01_{n}' for n in (32,64,128)] or name in [f'p9_zm_gnt_pipe_metal_hp_4_straight_{n}_yellow' for n in (4,8,16,32,64)]
        if selected:
            path=destination/(name+'.candidate.obj')
            with path.open('w') as stream:
                stream.write('# Candidate topology; winding and unknown flags unresolved; model-local coordinates.\n')
                for v in vertices: stream.write('v '+' '.join(format(x,'.9g') for x in v)+'\n')
                for t in triangles: stream.write('f '+' '.join(str(i+1) for i in t)+'\n')
            report['obj']=str(path.resolve())
        reports.append(report)
    document={'source':str(root.resolve()),'status':'Coordinate evidence and provisional triangle-list/strip interpretation; no original-brush or final-winding claim.',
              'tested':len(reports),'bounds_matches':sum(r['bounds_within_one_quantum'] for r in reports),
              'complete_coverage':sum(r['complete_vertex_coverage'] for r in reports),'models':reports,'unsupported':unsupported}
    (destination/'mesh-candidate-report.json').write_text(json.dumps(document,indent=2)+'\n')
    print({k:v for k,v in document.items() if k not in ('models','unsupported')})
    print('selected',[(r['name'],r['bounds_error'],r['triangle_candidates']) for r in reports if 'obj' in r])


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('capture',type=Path); p.add_argument('--output-dir',type=Path,required=True)
    args=p.parse_args(); run(args.capture,args.output_dir)
