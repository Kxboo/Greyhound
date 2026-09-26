"""Export scoped CW collision mesh candidates; strip topology/winding remain provisional."""

# Support direct execution and the isolated packaged Python runtime.
import sys as _tool_sys
from pathlib import Path as _ToolPath
TOOLS_ROOT = next(p for p in _ToolPath(__file__).resolve().parents if (p / "tool_bootstrap.py").is_file())
_tool_sys.path.insert(0, str(TOOLS_ROOT))
import tool_bootstrap as _tool_bootstrap
_tool_bootstrap.activate(__file__)
REPO_ROOT = TOOLS_ROOT.parent
import argparse
import collections
import json
from pathlib import Path
from audit_cw_clip_payloads import read_logical
from cw_quantized_geometry import decode_payload


def decode(data, model, *, apply_axis_offsets=True):
    address = model.get('payload', {}).get('address')
    if isinstance(address, str): address = int(address, 16)
    payload = decode_payload(data, address, apply_axis_offsets=apply_axis_offsets)
    vertices=[]; triangles=[]; groups=[]; shapes=[]
    complete=True; overlaps=0
    for shape in payload.shapes:
        coverage={1:collections.Counter(),2:collections.Counter()}
        first_vertex=len(vertices);first_triangle=len(triangles)
        for group in shape.groups:
            coverage[group.width].update(range(group.start,group.start+group.count))
            offset=len(vertices)
            vertices.extend(group.vertices)
            local=([(j,j+1,j+2) if j%2==0 else (j+1,j,j+2) for j in range(group.count-2)]
                   if group.strip else [(j,j+1,j+2) for j in range(0,group.count,3)])
            triangles.extend(tuple(offset+k for k in t) for t in local)
            groups.append({'shape_index':shape.index,'word':hex(group.word),
                'mode_candidate':'strip' if group.strip else 'triangle_batch',
                'start':group.start,'count':group.count,'width':group.width,
                'axis_blocks':list(group.axis_blocks),
                'axis_offsets':[256*b*s if apply_axis_offsets else 0 for b,s in zip(group.axis_blocks,shape.scales)],
                'packed_bits_14_25':(group.word>>14)&4095})
        complete &= all(len(coverage[w])==n for w,n in ((1,shape.n8),(2,shape.n16)))
        overlaps += sum(sum(v>1 for v in c.values()) for c in coverage.values())
        shapes.append(dict(shape_index=shape.index,header_offset=shape.header_offset,
            transform_selector=shape.transform_selector,transform_applied=False,
            bounds=[*shape.minimum,*shape.maximum],coordinate_scales=list(shape.scales),
            contents=hex(shape.contents),surface_word=hex(shape.surface_word),
            vertex_start=first_vertex,vertex_count=len(vertices)-first_vertex,
            triangle_start=first_triangle,triangle_count=len(triangles)-first_triangle,
            stream_start=shape.stream_start,stream_end=shape.stream_end,
            tree_offset=shape.tree_offset,tree_bytes=shape.tree_bytes,
            checked_pointers=shape.checked_pointers))
    if not vertices: raise ValueError('empty model')
    lo=[min(v[a] for v in vertices) for a in range(3)]
    hi=[max(v[a] for v in vertices) for a in range(3)]
    axis_errors=[max(abs(lo[a]-model['mins'][a]),abs(hi[a]-model['maxs'][a])) for a in range(3)]
    quanta=[max(shape.scales[a] for shape in payload.shapes) for a in range(3)]
    error=max(axis_errors)
    degenerate=0
    for t in triangles:
        a,b,c=[vertices[i] for i in t]
        u=[b[i]-a[i] for i in range(3)]; v=[c[i]-a[i] for i in range(3)]
        cross=[u[1]*v[2]-u[2]*v[1],u[2]*v[0]-u[0]*v[2],u[0]*v[1]-u[1]*v[0]]
        degenerate+=sum(x*x for x in cross)==0
    report={'coordinate_axis_offsets_applied':apply_axis_offsets,'name':model['name'],'bounds_error':error,
            'bounds_within_one_quantum':all(e<=q for e,q in zip(axis_errors,quanta)),
            'bounds_error_per_axis':axis_errors,'coordinate_quanta_per_axis':quanta,
            'bounds_comparison_scope':'Quantized model-local vertices versus asset bounds; excludes extra branches and unapplied transforms',
            'vertex_records':len(vertices),'triangle_candidates':len(triangles),'degenerate_triangle_candidates':degenerate,
            'complete_vertex_coverage':complete,'overlapping_vertex_slots':overlaps,
            'unresolved_tail_bytes':sum(s.tree_bytes for s in payload.shapes),'groups':groups,
            'coordinate_decode':'float32(max(float32(max-min),8191)*float32(1/65535)); nibble precedes multiplication',
            'topology_status':'triangle-list/strip candidates; winding not verified',
            'shape_count':len(shapes),'shapes':shapes,
            'selector_bytes':payload.selectors.hex(),'extra_sections_not_decoded':payload.extra_count,
            'extra_section_offset':payload.extra_offset,
            'complete_model_collision':False}
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
                for v in vertices: stream.write('v '+' '.join(format(x,'.17g') for x in v)+'\n')
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
