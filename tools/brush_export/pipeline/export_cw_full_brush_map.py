"""Export all brushes of the verified Silver scene as an inspection-only BO3 map.

World transforms are baked exactly once. Unmatched materials stay in REVIEW layers.
This exports vertex hulls, not inferred original Radiant authoring planes.
"""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import re
import time
import numpy as np
from cw_exact_vertex_hull import sub,cross,dot
from build_cw_bo3_brush_prototype import materials,read_map_planes


def digest(p): return hashlib.sha256(p.read_bytes()).hexdigest()


def hull_planes(mesh):
    ratios=[[float(v).as_integer_ratio() for v in p] for p in mesh['vertices']]
    den=max(d for row in ratios for _,d in row)
    points=[tuple(n*(den//d) for n,d in row) for row in ratios]
    unique={};edges=Counter();volume=0
    for face in mesh['faces']:
        if len(face)!=3: raise ValueError('Expected checked triangles')
        a,b,c=(points[i] for i in face)
        n=cross(sub(b,a),sub(c,a));d=dot(n,a)
        if not any(n) or any(dot(n,p)>d for p in points):
            raise ValueError('Not an exact outward support plane')
        gcd=math.gcd(*n,d)
        key=tuple(v//gcd for v in (*n,d))
        unique[key]=[*(v for v in key[:3]),key[3]/den]
        volume+=dot(sub(a,points[0]),cross(sub(b,points[0]),sub(c,points[0])))
        edges.update((face[j],face[(j+1)%3]) for j in range(3))
    if volume<=0 or any(v!=1 or edges[(b,a)]!=1 for (a,b),v in edges.items()):
        raise ValueError('Unclosed or reversed source hull')
    eq=np.array(list(unique.values()),dtype=float)
    eq/=np.linalg.norm(eq[:,:3],axis=1)[:,None]
    return eq


def face_text(equations,center,material):
    lines=[]
    for plane in equations:
        n=plane[:3];d=plane[3]
        base=center+n*(d-n@center)
        axis=np.eye(3)[np.argmin(abs(n))]
        u=np.cross(n,axis);u*=128/np.linalg.norm(u)
        v=np.cross(u,n);v*=128/np.linalg.norm(v)
        text=' '.join('( '+' '.join(format(float(x),'.17g') for x in p)+' )'
                      for p in [base,base+u,base+v])
        lines.append(text+f' {material} 64 64 0 0 0 0 lightmap_gray 16384 16384 0 0 0 0')
    return lines


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--scene',type=Path,required=True);p.add_argument('--flags',type=Path,required=True)
    p.add_argument('--gdt',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--allow-oversized-intermediate',action='store_true',
        help='Research intermediate for repair_cw_map_face_limit.py only; never open oversized output in Radiant')
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=True)
    scene=json.loads(a.scene.read_text());flags=json.loads(a.flags.read_text())['items']
    lookup={(int(r['name_hash'],16),r['brush_index']):r for r in flags}
    mats=materials(a.gdt)
    # Explicitly reviewed choices. Do not automatically select slick or fuller materials.
    choices={0x80:'clip_missile',0x400:'clip_physics',0x1040:'nosight_noclip',
             0x10000:'clip_player',0x20000:'clip_ai',0x130200:'clip',
             0x131640:'clip_nosight',0x1336c0:'clip_full'}
    assert all(n in mats for n in [*choices.values(),'clip'])
    cache={};rows=[];layers=set();counts=Counter();last=time.monotonic()
    body=a.output/'brush-body.tmp'
    maxerr=0.;maxoutside=0.;max32=0.;maxsides=0
    with body.open('w') as out:
        for index,inst in enumerate(scene['instances']):
            prop=inst['properties'];key=(int(prop['collision_hash'],16),prop['brush_index'])
            info=lookup[key];mask=int(info['contents']['raw_contents'],16)
            matched=mask in choices;material=choices.get(mask,'clip')
            names='_'.join(info['contents']['named_properties']) or 'unnamed'
            category='PROPERTY_MATCH' if matched else 'REVIEW_PLACEHOLDER'
            layer=f'000_Global/{category}/{mask:08x}_{names}'
            layers.update(['000_Global',f'000_Global/{category}',layer])
            counts[category]+=1;counts['material_'+material]+=1
            mesh=scene['meshes'][inst['mesh']]
            if inst['mesh'] not in cache:cache[inst['mesh']]=hull_planes(mesh)
            if len(cache[inst['mesh']])>64 and not a.allow_oversized_intermediate:
                raise ValueError('Radiant permits at most64 faces per brush; partition this hull before publishing a map')
            local=cache[inst['mesh']];m=np.array(inst['matrix_world']);linear=m[:3,:3];pos=m[:3,3]
            assert np.linalg.det(linear)>0
            points=np.array(mesh['vertices'])@linear.T+pos
            n=local[:,:3]@np.linalg.inv(linear)
            equations=np.column_stack((n,local[:,3]+n@pos))
            equations/=np.linalg.norm(equations[:,:3],axis=1)[:,None]
            lines=face_text(equations,points.mean(axis=0),material)
            parsed=np.array(read_map_planes('\n'.join(lines)))
            error=float(abs(parsed-equations).max());maxerr=max(maxerr,error)
            outside=max(0.,float((points@parsed[:,:3].T-parsed[:,3]).max()))
            maxoutside=max(maxoutside,outside)
            if error>1e-6 or outside>1e-6:raise ValueError(('Serialization lost precision',inst['name'],error,outside))
            # Diagnostic of possible compiler float32 point parsing, not a compiler test.
            qplanes=[]
            for line in lines:
                x,y,z=[np.array([float(x) for x in s.split()],dtype=np.float32).astype(float)
                       for s in re.findall(r'\(\s*([^()]*)\)',line)]
                qn=-np.cross(y-x,z-x);qn/=np.linalg.norm(qn)
                qplanes.append([*qn,qn@x])
            qplanes=np.array(qplanes)
            fp32=max(0.,float((points@qplanes[:,:3].T-qplanes[:,3]).max()));max32=max(max32,fp32)
            maxsides=max(maxsides,len(lines))
            out.write(f'// brush {index}\n{{\nlayer "{layer}"\n')
            out.write('\n'.join(lines)+'\n}\n')
            rows.append(dict(map_brush_index=index,source_object=inst['name'],source_mesh=inst['mesh'],
                name_hash=prop['collision_hash'],brush_index=prop['brush_index'],source_properties=prop,
                source_matrix_world=inst['matrix_world'],world_mins=points.min(axis=0).tolist(),
                world_maxs=points.max(axis=0).tolist(),contents=info['contents'],layer=layer,
                assigned_material=material,assignment_status=category,
                source_plane_count=len(mesh['faces']),exported_support_planes=len(lines),
                representation='captured vertex hull, exact coplanar planes merged within this brush only',
                serialized_plane_error=error,source_point_outside=outside,
                float32_point_parse_outside_diagnostic=fp32,
                known_source_plane_disagreement=prop['collision_model_index']==791 and prop['brush_index']==1209))
            if time.monotonic()-last>10:
                print(f'Converted {index+1}/{len(scene["instances"])} brushes',flush=True);last=time.monotonic()
    target=a.output/'zm_silver_brush_collision_inspection.map'
    with target.open('w') as out:
        out.write('iwmap 4\n')
        for layer in sorted(layers):out.write(f'"{layer}" flags '+(' active' if layer=='000_Global' else '')+'\n')
        out.write('// entity 0\n{\n"classname" "worldspawn"\n')
        with body.open() as inp:
            for line in inp:out.write(line)
        out.write('}\n')
    body.unlink()
    report=dict(schema='cw_bo3_full_brush_map_v1',map='zm_silver',brush_instances=len(rows),
        unique_source_meshes=len(cache),counts=dict(counts),maximum_support_planes=maxsides,
        max_serialized_plane_error=maxerr,max_source_point_outside=maxoutside,
        max_float32_point_parse_outside_diagnostic=max32,source_scene=str(a.scene),
        source_scene_sha256=digest(a.scene),map_sha256=digest(target),gdt_sha256=digest(a.gdt),
        source_flags_sha256=digest(a.flags),generator_sha256=digest(Path(__file__)),
        scope='All brush objects from verified scene collections 00 and 03; no renderer models, terrain, or triangle collision',
        units='game inches, Z up; source scene world coordinates; no recenter or scale fitting',
        material_policy='PROPERTY_MATCH compares known contents only; all extra BO3 behavior unverified. REVIEW_PLACEHOLDER uses clip solely for inspection, not a faithful gameplay conversion.',
        geometry_policy='Captured vertex hulls; original counted planes retained in source capture and may differ. No coincident-brush deduplication.',
        radiant_opened=False,compiled=False,rows=rows)
    (a.output/'collision_metadata.json').write_text(json.dumps(report,indent=2))
    print(json.dumps({k:v for k,v in report.items() if k not in ['rows']}),flush=True)


if __name__=='__main__':main()
