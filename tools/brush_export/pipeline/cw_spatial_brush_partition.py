"""Exact rational halfspace cuts of convex source hulls, with volume certificates."""
from fractions import Fraction as F
import math
import numpy as np
from cw_exact_vertex_hull import sub,cross,dot
from export_cw_full_brush_map import hull_planes

def volume(faces):
    return sum(dot(poly[0],cross(poly[i],poly[i+1])) for poly,_ in faces for i in range(1,len(poly)-1))/6

def plane(poly):
    n=cross(sub(poly[1],poly[0]),sub(poly[2],poly[0]));return (*n,dot(n,poly[0]))

def support_count(faces):return len({key for _,key in faces})

def clean(poly):
    out=[]
    for p in poly:
        if not out or p!=out[-1]:out.append(p)
    if len(out)>1 and out[0]==out[-1]:out.pop()
    while len(out)>=3:
        bad=next((i for i in range(len(out)) if not any(cross(sub(out[i],out[i-1]),sub(out[(i+1)%len(out)],out[i])))),None)
        if bad is None:break
        out.pop(bad)
    return out if len(out)>=3 else []

def cap_polygon(points,axis,sign):
    axes=[i for i in range(3) if i!=axis];pts=sorted(set(points),key=lambda p:(p[axes[0]],p[axes[1]]))
    def turn(a,b,c):return (b[axes[0]]-a[axes[0]])*(c[axes[1]]-a[axes[1]])-(b[axes[1]]-a[axes[1]])*(c[axes[0]]-a[axes[0]])
    lower=[];upper=[]
    for p in pts:
        while len(lower)>1 and turn(lower[-2],lower[-1],p)<=0:lower.pop()
        lower.append(p)
    for p in reversed(pts):
        while len(upper)>1 and turn(upper[-2],upper[-1],p)<=0:upper.pop()
        upper.append(p)
    out=lower[:-1]+upper[:-1]
    if len(out)<3:raise ValueError('Degenerate cut cap')
    if plane(out)[axis]*sign<0:out.reverse()
    return out

def cut(faces,axis,at,sign):
    result=[];caps=set()
    for poly,key in faces:
        out=[]
        for i,p in enumerate(poly):
            q=poly[(i+1)%len(poly)];dp=sign*(p[axis]-at);dq=sign*(q[axis]-at)
            if dp<=0:out.append(p)
            if (dp<0 and dq>0) or (dp>0 and dq<0):
                t=dp/(dp-dq);out.append(tuple(p[k]+t*(q[k]-p[k]) for k in range(3)))
        out=clean(out)
        if out:
            result.append((out,key));caps.update(p for p in out if p[axis]==at)
    cap=cap_polygon(caps,axis,sign);n=[F(0)]*3;n[axis]=F(sign);key=(*n,F(sign)*at)
    result.append((cap,key));return result,cap

def cut_general(faces,normal,at,sign):
    result=[];caps=set()
    for poly,key in faces:
        out=[]
        for i,p in enumerate(poly):
            q=poly[(i+1)%len(poly)];dp=sign*(dot(normal,p)-at);dq=sign*(dot(normal,q)-at)
            if dp<=0:out.append(p)
            if (dp<0 and dq>0) or (dp>0 and dq<0):
                t=dp/(dp-dq);out.append(tuple(p[k]+t*(q[k]-p[k]) for k in range(3)))
        out=clean(out)
        if out:result.append((out,key));caps.update(p for p in out if dot(normal,p)==at)
    axis=max(range(3),key=lambda k:abs(normal[k]));cap=cap_polygon(caps,axis,1 if normal[axis]*sign>0 else -1)
    key=tuple(sign*x for x in (*normal,at));pivot=next(abs(x) for x in key[:3] if x);key=tuple(x/pivot for x in key)
    result.append((cap,key));return result,cap

def spatial_pieces(vertices,triangles,limit):
    original=hull_planes(dict(vertices=vertices,faces=triangles))
    if len(original)<=limit:return [(np.array(vertices),original)],dict(partitioned=False,source_support_planes=len(original))
    points=[tuple(F(float(x)) for x in p) for p in vertices];faces=[]
    for tri in triangles:
        poly=[points[i] for i in tri];key=plane(poly);pivot=next(abs(x) for x in key[:3] if x)
        faces.append((poly,tuple(x/pivot for x in key)))
    sourcekeys={k for _,k in faces};initial=volume(faces)
    if initial<=0:raise ValueError('Nonpositive source volume')
    queue=[(faces,0)];leaves=[];certs=[];tetra_fallbacks=0
    while queue:
        fs,depth=queue.pop();count=support_count(fs)
        if count<=limit:leaves.append(fs);continue
        if depth>=24 or len(queue)+len(leaves)>4096:raise ValueError('Spatial partition bound exceeded')
        vs=set(p for poly,_ in fs for p in poly);options=[]
        for axis in range(3):
            values=sorted({p[axis] for p in vs})
            # A split must also be able to pass through a high-valence source
            # vertex. Cuts strictly between coordinates leave its entire fan
            # on one side, which can cause repeated ineffective cuts.
            if len(values)<2:continue
            mid=len(values)//2;at=(values[mid-1]+values[mid])/2
            incident={v:set() for v in vs}
            for poly,key in fs:
                for v in poly:incident[v].add(key)
            peak=max(sorted(vs),key=lambda v:len(incident[v]))
            positions={at,values[mid],values[mid-1],peak[axis]}
            for at in sorted(positions):
                if not values[0]<at<values[-1]:continue
                # Predict surviving planes using exact signs before constructing
                # intersections. Only the selected cut needs rational clipping.
                nl=1+len({key for poly,key in fs if any(p[axis]<at for p in poly)})
                nr=1+len({key for poly,key in fs if any(p[axis]>at for p in poly)})
                score=(max(nl,nr),nl+nr,axis)
                options.append((score,axis,at))
        score,axis,at=min(options,key=lambda x:x[0])
        left,lc=cut(fs,axis,at,1);right,rc=cut(fs,axis,at,-1)
        if score[:2]!=(max(support_count(left),support_count(right)),support_count(left)+support_count(right)):raise ValueError('Predicted cut plane count differs from actual clipping')
        cut_normal=None
        if max(support_count(left),support_count(right))>=count:
            # At a bounding-box corner no axial plane through the vertex cuts
            # its incident fan. Try diagonal planes, then a plane separating
            # two incident edges using an exact 2x2 Gram solve.
            normals=[tuple(F(x) for x in n) for n in [(1,1,0),(1,-1,0),(1,0,1),(1,0,-1),(0,1,1),(0,1,-1),(1,1,1),(1,1,-1),(1,-1,1),(-1,1,1)]]
            neighbors=set()
            for poly,_ in fs:
                if peak in poly:
                    i=poly.index(peak);neighbors.update((poly[i-1],poly[(i+1)%len(poly)]))
            edges=[sub(p,peak) for p in sorted(neighbors) if p!=peak]
            if edges:
                e1=max(edges,key=lambda e:dot(e,e));others=[e for e in edges if any(cross(e1,e))]
                if others:
                    e2=max(others,key=lambda e:dot(cross(e1,e),cross(e1,e))/dot(e,e));aa=dot(e1,e1);ab=dot(e1,e2);bb=dot(e2,e2);det=aa*bb-ab*ab
                    normals.append(tuple(((bb+ab)*e1[i]-(aa+ab)*e2[i])/det for i in range(3)))
            alternatives=[]
            for normal in normals:
                threshold=dot(normal,peak);dist={v:dot(normal,v)-threshold for v in vs}
                if min(dist.values())>=0 or max(dist.values())<=0:continue
                nl=1+len({key for poly,key in fs if any(dist[p]<0 for p in poly)});nr=1+len({key for poly,key in fs if any(dist[p]>0 for p in poly)})
                if max(nl,nr)<count:alternatives.append(((max(nl,nr),nl+nr),normal,threshold))
            if alternatives:
                predicted,cut_normal,at=min(alternatives,key=lambda x:x[0]);axis=None
                left,lc=cut_general(fs,cut_normal,at,1);right,rc=cut_general(fs,cut_normal,at,-1)
                if predicted!=(max(support_count(left),support_count(right)),support_count(left)+support_count(right)):raise ValueError('General cut count mismatch')
        if max(support_count(left),support_count(right))>=count:
            # Small beveled shapes can retain the same faces under every axial
            # split. Exact rational tetrahedra remain a bounded local fallback.
            center=tuple(sum(p[k] for p in vs)/len(vs) for k in range(3));tets=[]
            for poly,_ in fs:
                for i in range(1,len(poly)-1):
                    a,b,c=poly[0],poly[i],poly[i+1]
                    tetra_triangles=[[center,b,a],[center,c,b],[center,a,c],[a,b,c]]
                    tet=[]
                    for tri in tetra_triangles:
                        key=plane(tri);pivot=next(abs(x) for x in key[:3] if x)
                        tet.append((tri,tuple(x/pivot for x in key)))
                    if volume(tet)<=0:raise ValueError('Nonpositive fallback tetrahedron')
                    tets.append(tet)
            if sum(volume(t) for t in tets)!=volume(fs):raise ValueError('Fallback volume changed')
            leaves.extend(tets);tetra_fallbacks+=1;continue
        lv,rv=volume(left),volume(right)
        if lv<=0 or rv<=0 or lv+rv!=volume(fs) or set(lc)!=set(rc):raise ValueError('Cut changed exact volume or shared cap')
        certs.append(dict(axis=axis,normal=[str(x) for x in cut_normal] if cut_normal is not None else None,coordinate=str(at),left_faces=support_count(left),right_faces=support_count(right),volume_conserved=True,shared_cap_identical=True))
        queue.extend([(left,depth+1),(right,depth+1)])
    if sum(volume(fs) for fs in leaves)!=initial:raise ValueError('Total partition volume changed')
    # Clear denominators once: these are the identical exact inequalities,
    # avoiding a Fraction reduction for every point/plane multiplication.
    integer_source=[]
    for key in sourcekeys:
        denominator=math.lcm(*(x.denominator for x in key))
        integer_source.append(tuple(x.numerator*(denominator//x.denominator) for x in key))
    result=[];retained=set()
    for fs in leaves:
        vs=set(p for poly,_ in fs for p in poly);retained.update(vs)
        for p in vs:
            denominator=math.lcm(*(x.denominator for x in p))
            integer_point=tuple(x.numerator*(denominator//x.denominator) for x in p)
            if any(dot(k[:3],integer_point)>k[3]*denominator for k in integer_source):raise ValueError('New vertex outside original hull')
        keys=list(dict.fromkeys(key for _,key in fs));eq=np.array([[float(x) for x in k] for k in keys]);eq/=np.linalg.norm(eq[:,:3],axis=1)[:,None]
        result.append((np.array([[float(x) for x in p] for p in sorted(vs)]),eq))
    # All original hull vertices remain on one or more pieces; no source movement.
    hullvertices={points[i] for tri in triangles for i in tri}
    if not hullvertices<=retained:raise ValueError('Source hull vertex lost')
    return result,dict(partitioned=True,source_support_planes=len(original),pieces=len(result),tetrahedral_fallback_regions=tetra_fallbacks,method='Exact rational axial cuts with exact local tetrahedral fallback; unchanged exterior planes',exact_volume_conserved=True,external_planes_preserved=True,source_hull_vertices_retained=True,positive_exact_volumes=True,volume_numerator=str(initial.numerator),volume_denominator=str(initial.denominator),cuts=certs)
