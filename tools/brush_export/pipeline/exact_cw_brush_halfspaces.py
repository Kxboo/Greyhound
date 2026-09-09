"""Exact rational reference for small brush plane sets, not a fast map exporter."""
from fractions import Fraction as F
from collections import Counter
from itertools import combinations


def cross(a,b):
    return (a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0])


def dot(a,b):return sum(x*y for x,y in zip(a,b))
def sub(a,b):return tuple(x-y for x,y in zip(a,b))


def reconstruct_exact(equations):
    # Every source float32 is exactly representable as a rational. Do not
    # normalize before conversion: independent divisions would round coefficients.
    planes=[tuple(F(float(x)) for x in row) for row in equations]
    normals=[p[:3] for p in planes]
    points=[];seen=set()
    for i,j,k in combinations(range(len(planes)),3):
        a,b,c=normals[i],normals[j],normals[k]
        bc,ca,ab=cross(b,c),cross(c,a),cross(a,b)
        det=dot(a,bc)
        if not det:continue
        p=tuple((planes[i][3]*bc[q]+planes[j][3]*ca[q]+planes[k][3]*ab[q])/det for q in range(3))
        if p in seen or any(dot(n,p)>plane[3] for n,plane in zip(normals,planes)):
            continue
        seen.add(p);points.append(p)
    if len(points)<4:raise ValueError('Exact intersection has fewer than four vertices')
    faces=[];face_keys={}
    for si,(n,plane) in enumerate(zip(normals,planes)):
        ids=[i for i,p in enumerate(points) if dot(n,p)==plane[3]]
        if len(ids)<3:continue
        drop=max(range(3),key=lambda a:abs(n[a]));axes=[a for a in range(3) if a!=drop]
        order=sorted(ids,key=lambda i:(points[i][axes[0]],points[i][axes[1]]))
        def turn(i,j,k):
            a,b=axes
            return ((points[j][a]-points[i][a])*(points[k][b]-points[i][b])-
                    (points[j][b]-points[i][b])*(points[k][a]-points[i][a]))
        def half(seq):
            out=[]
            for i in seq:
                while len(out)>=2 and turn(out[-2],out[-1],i)<=0:out.pop()
                out.append(i)
            return out
        polygon=half(order)[:-1]+half(order[::-1])[:-1]
        if len(polygon)<3:continue
        orient=dot(n,cross(sub(points[polygon[1]],points[polygon[0]]),sub(points[polygon[2]],points[polygon[0]])))
        if not orient:raise ValueError('Exact polygon is degenerate')
        if orient<0:polygon.reverse()
        key=tuple(sorted(polygon))
        if key in face_keys:faces[face_keys[key]]['side_candidates'].append(si)
        else:
            face_keys[key]=len(faces)
            faces.append(dict(vertices=polygon,side_candidates=[si]))
    directed=Counter((f['vertices'][j],f['vertices'][(j+1)%len(f['vertices'])]) for f in faces for j in range(len(f['vertices'])))
    bad=sum(count!=1 or directed[(b,a)]!=1 for (a,b),count in directed.items())
    volume=F(0)
    triangles=[]
    for f in faces:
        for j in range(1,len(f['vertices'])-1):
            t=(f['vertices'][0],f['vertices'][j],f['vertices'][j+1]);triangles.append(t)
            volume+=dot(points[t[0]],cross(points[t[1]],points[t[2]]))/6
    return dict(vertices=[[float(x) for x in p] for p in points],
        vertex_rationals=[[str(x) for x in p] for p in points],triangles=triangles,faces=faces,
        bad_directed_edges=bad,volume=float(volume),volume_rational=str(volume),
        exact_halfspace_checks=True)
