"""Preserve a full-map export while partitioning only brushes above Radiant's 64-face limit.

Each oversized convex hull is partitioned into tetrahedra using one shared interior
point. Original exterior triangles, positions, properties and identities remain.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sys
import numpy as np
from cw_exact_vertex_hull import sub,cross,dot
from export_cw_full_brush_map import face_text
from build_cw_bo3_brush_prototype import read_map_planes


def planes_for_tetra(points):
    equations=[]
    for ids in [(0,1,2),(0,3,1),(0,2,3),(1,3,2)]:
        a,b,c=points[list(ids)]
        n=np.cross(b-a,c-a);n/=np.linalg.norm(n)
        other=next(i for i in range(4) if i not in ids)
        if n@(points[other]-a)>0:n=-n
        equations.append([*n,n@a])
    return np.array(equations)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('src',type=Path);parser.add_argument('dst',type=Path)
    parser.add_argument('--split-source-brush',type=int,action='append',default=[],
        help='Also partition this original brush index after a reproduced winding failure')
    args=parser.parse_args();src,dst=args.src,args.dst;dst.mkdir(parents=True,exist_ok=True)
    forced=set(args.split_source_brush)
    report=json.loads((src/'collision_metadata.json').read_text())
    scene=json.loads(Path(report['source_scene']).read_text())
    instances={r['name']:r for r in scene['instances']}
    raw=(src/'zm_silver_brush_collision_inspection.map').read_text()
    blocks=re.split(r'// brush \d+\n',raw)
    assert len(blocks)-1==len(report['rows'])
    # Last brace belongs to worldspawn, not the final brush.
    blocks[-1]=blocks[-1].rstrip()[:-1].rstrip()+'\n'
    result=[];certificates=[];maxerror=0.;untouched=0
    target=dst/'zm_silver_brush_collision_64face.map'
    with target.open('w') as out:
        out.write(blocks[0])
        for row,block in zip(report['rows'],blocks[1:]):
            count=len(read_map_planes(block))
            assert count==row['exported_support_planes']
            if count<=64 and row['map_brush_index'] not in forced:
                out.write(f'// brush {len(result)}\n'+block)
                result.append(dict(row,original_map_brush_index=row['map_brush_index'],
                                   map_brush_index=len(result),partitioned=False))
                untouched+=1;continue
            inst=instances[row['source_object']];mesh=scene['meshes'][inst['mesh']]
            m=np.array(inst['matrix_world']);v=np.array(mesh['vertices'])@m[:3,:3].T+m[:3,3]
            center=v.mean(axis=0);points=np.vstack((v,center));ci=len(v)
            source_eq=np.array(read_map_planes(block))
            if (source_eq[:,:3]@center-source_eq[:,3]).max()>=0:
                raise ValueError('Partition center is not strictly interior')
            ratios=[[float(x).as_integer_ratio() for x in p] for p in points]
            den=max(d for p in ratios for _,d in p)
            ints=[tuple(n*(den//d) for n,d in p) for p in ratios]
            signed_volume=0;boundary=Counter();start=len(result)
            for piece,face in enumerate(mesh['faces']):
                assert len(face)==3
                ids=[ci,*face];tet=points[ids]
                a,b,c=(sub(ints[i],ints[ci]) for i in face)
                volume=dot(a,cross(b,c))
                if volume<=0:raise ValueError('Nonpositive exact tetrahedron volume')
                signed_volume+=volume
                for f in [(ci,face[1],face[0]),(ci,face[2],face[1]),(ci,face[0],face[2]),tuple(face)]:
                    # Cyclic canonicalization retains orientation; reverse faces cancel.
                    key=min(f,f[1:]+f[:1],f[2:]+f[:2]);boundary[key]+=1
                equations=planes_for_tetra(tet)
                lines=face_text(equations,tet.mean(axis=0),row['assigned_material'])
                parsed=np.array(read_map_planes('\n'.join(lines)))
                error=float(abs(parsed-equations).max());outside=float((tet@parsed[:,:3].T-parsed[:,3]).max())
                if error>1e-6 or outside>1e-6:raise ValueError('Partition serialization drift')
                maxerror=max(maxerror,error,outside)
                out.write(f'// brush {len(result)}\n{{\nlayer "{row["layer"]}"\n'+'\n'.join(lines)+'\n}\n')
                result.append(dict(row,original_map_brush_index=row['map_brush_index'],map_brush_index=len(result),
                    partitioned=True,partition_piece=piece,piece_vertices_world=tet.tolist(),
                    source_brush_world_mins=row['world_mins'],source_brush_world_maxs=row['world_maxs'],
                    world_mins=tet.min(axis=0).tolist(),world_maxs=tet.max(axis=0).tolist(),
                    exported_support_planes=4,serialized_plane_error=error,source_point_outside=max(0.,outside),
                    representation='Tetrahedral partition of source vertex hull; original outer triangles preserved',
                    internal_faces='Generated shared partition boundaries; same parent material and raw metadata'))
            external=[]
            for f,n in boundary.items():
                reverse=(f[0],f[2],f[1]);reverse=min(reverse,reverse[1:]+reverse[:1],reverse[2:]+reverse[:2])
                if ci in f:assert n==boundary[reverse]==1
                else:
                    assert n==1;external.append(f)
            original=sorted(min(tuple(f),tuple(f[1:]+f[:1]),tuple(f[2:]+f[:2])) for f in mesh['faces'])
            assert sorted(external)==original
            certificates.append(dict(source_object=row['source_object'],original_faces=count,pieces=len(result)-start,
                exact_positive_piece_volumes=True,internal_faces_cancel=True,external_triangles_unchanged=True,
                volume_numerator=str(signed_volume),volume_denominator=str(6*den**3)))
        out.write('}\n')
    report.update(schema='cw_bo3_full_brush_map_v2',rows=result,brush_instances=len(result),
        source_brush_instances=untouched+len(certificates),unchanged_source_brushes=untouched,
        split_source_brushes=len(certificates),maximum_support_planes=max(r['exported_support_planes'] for r in result),
        max_partition_serialization_error=maxerror,map_sha256=hashlib.sha256(target.read_bytes()).hexdigest(),
        original_map_sha256=hashlib.sha256((src/'zm_silver_brush_collision_inspection.map').read_bytes()).hexdigest(),
        repair_generator_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        counts_scope='Original counts describe source instances; see output_counts for partitioned output',
        output_counts=dict(Counter(r['assignment_status'] for r in result)),
        forced_partition_source_indices=sorted(forced),
        face_limit=64,face_limit_evidence='radiant_modtools.exe VA 0x1401ec4e3 cmp rax,0x40 followed by jb; assertion brush.cpp line126',
        partition_certificates=certificates,radiant_opened=False,compiled=False)
    (dst/'collision_metadata.json').write_text(json.dumps(report,indent=2))
    print(json.dumps({k:report[k] for k in ['source_brush_instances','unchanged_source_brushes',
        'split_source_brushes','brush_instances','maximum_support_planes','max_partition_serialization_error']}))


if __name__=='__main__':main()
