"""Merge only exactly convex unions of adjacent interior-point tetrahedra.

Uses unchanged source points plus the same interior point as the tetra policy.
Every merge cancels a shared boundary and retains exact integer volume.
"""
from collections import Counter
import math
import numpy as np
from cw_exact_vertex_hull import sub,cross,dot
from export_cw_full_brush_map import hull_planes

def canon(t):return min(t,t[1:]+t[:1],t[2:]+t[:2])
def reverse(t):return canon((t[0],t[2],t[1]))

def compact_pieces(vertices,faces,limit):
    eq=hull_planes(dict(vertices=vertices,faces=faces))
    if len(eq)<=limit:return [(np.array(vertices),eq)],dict(partitioned=False,source_support_planes=len(eq))
    v=np.array(vertices);points=np.vstack((v,v.mean(axis=0)));ci=len(v)
    ratios=[[float(x).as_integer_ratio() for x in p] for p in points];den=max(d for p in ratios for _,d in p)
    raw=[tuple(n*(den//d) for n,d in p) for p in ratios];ints=[sub(p,raw[ci]) for p in raw]
    groups={};initial_volume=0
    for i,f in enumerate(faces):
        f=tuple(f);volume=dot(ints[f[0]],cross(ints[f[1]],ints[f[2]]))
        if volume<=0:raise ValueError('Nonpositive initial tetrahedron')
        fs={canon(t) for t in [(ci,f[1],f[0]),(ci,f[2],f[1]),(ci,f[0],f[2]),f]}
        groups[i]=(fs,volume);initial_volume+=volume
    failed=set();nextid=len(groups);merges=0
    while True:
        owners={};pairs=set()
        for gid,(fs,_) in groups.items():
            for f in fs:
                other=owners.get(reverse(f))
                if other is not None:pairs.add(tuple(sorted((gid,other))))
                owners[f]=gid
        changed=False
        for a,b in sorted(pairs,key=lambda ab:(len(groups[ab[0]][0])+len(groups[ab[1]][0]),ab)):
            if a not in groups or b not in groups or (a,b) in failed:continue
            fa,va=groups[a];fb,vb=groups[b];shared={f for f in fa if reverse(f) in fb}
            boundary=(fa-shared)|(fb-{reverse(f) for f in shared});ids={i for f in boundary for i in f};planes={}
            for f in boundary:
                n=cross(sub(ints[f[1]],ints[f[0]]),sub(ints[f[2]],ints[f[0]]));d=dot(n,ints[f[0]]);g=math.gcd(*n,d)
                key=tuple(x//g for x in (*n,d));planes[key]=None
                if len(planes)>limit:break
            if len(planes)>limit or any(dot(k[:3],ints[i])>k[3] for k in planes for i in ids):failed.add((a,b));continue
            volume=sum(dot(ints[f[0]],cross(ints[f[1]],ints[f[2]])) for f in boundary)
            if volume!=va+vb:raise ValueError('Exact merge volume changed')
            groups[nextid]=(boundary,volume);nextid+=1;del groups[a];del groups[b];merges+=1;changed=True
        if not changed:break
    result=[];allfaces=Counter();volume=0
    for fs,vol in groups.values():
        ids=sorted({i for f in fs for i in f});lookup={x:i for i,x in enumerate(ids)};p=points[ids]
        triangles=[tuple(lookup[x] for x in f) for f in sorted(fs)];eq=hull_planes(dict(vertices=p.tolist(),faces=triangles))
        if len(eq)>limit:raise ValueError('Partition face limit exceeded')
        result.append((p,eq));allfaces.update(fs);volume+=vol
    exterior=[]
    for f,n in allfaces.items():
        if ci in f:
            if n!=1 or allfaces[reverse(f)]!=1:raise ValueError('Unpaired internal partition face')
        else:
            if n!=1:raise ValueError('Duplicate exterior face')
            exterior.append(f)
    if sorted(exterior)!=sorted(canon(tuple(f)) for f in faces) or volume!=initial_volume:raise ValueError('Partition exterior or volume changed')
    return result,dict(partitioned=True,source_support_planes=len(hull_planes(dict(vertices=vertices,faces=faces))),pieces=len(result),initial_tetrahedra=len(faces),exact_convex_merges=merges,internal_faces_cancel=True,external_triangles_unchanged=True,positive_exact_volumes=True,volume_numerator=str(volume),volume_denominator=str(6*den**3))
