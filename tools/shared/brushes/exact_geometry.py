"""Exact geometry shared by game converters; preserve captured coordinates and topology."""

# Support direct execution and the isolated packaged Python runtime.
import sys as _tool_sys
from pathlib import Path as _ToolPath
TOOLS_ROOT = next(p for p in _ToolPath(__file__).resolve().parents if (p / "tool_bootstrap.py").is_file())
_tool_sys.path.insert(0, str(TOOLS_ROOT))
import tool_bootstrap as _tool_bootstrap
_tool_bootstrap.activate(__file__)
REPO_ROOT = TOOLS_ROOT.parent
from collections import Counter
from fractions import Fraction as F
from itertools import combinations
import math
import numpy as np


def sub(a, b):
    return tuple(x-y for x, y in zip(a, b))

def cross(a, b):
    return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])

def dot(a, b):
    return sum(x*y for x, y in zip(a, b))

def exact_hull(points):
    if not points or any(len(p) != 3 or not all(math.isfinite(x) for x in p) for p in points):
        raise ValueError('Invalid source points')
    ratios = [[float(x).as_integer_ratio() for x in p] for p in points]
    denominator = max(d for p in ratios for _, d in p)
    raw = [tuple(n*(denominator//d) for n, d in p) for p in ratios]
    # Coincident input positions share one topological representative; all
    # original vertices remain available in the exported source buffer.
    representatives = {}
    for i, p in enumerate(raw):
        representatives.setdefault(p, i)
    ids = list(representatives.values())
    if len(ids) < 4:
        raise ValueError('Fewer than four distinct points')
    origin = raw[ids[0]]
    p = [sub(v, origin) for v in raw]
    a = ids[0]
    b = max(ids[1:], key=lambda i: dot(p[i], p[i]))
    c = max(ids, key=lambda i: dot(cross(p[b], p[i]), cross(p[b], p[i])))
    n = cross(p[b], p[c])
    d = max(ids, key=lambda i: abs(dot(n, p[i])))
    if not dot(n, p[d]):
        raise ValueError('Coplanar or collinear source points; no volume')
    tetra = (a, b, c, d)
    inside4 = tuple(sum(p[i][axis] for i in tetra) for axis in range(3))

    def normal(t):
        return cross(sub(p[t[1]], p[t[0]]), sub(p[t[2]], p[t[0]]))

    def outward(t):
        n = normal(t)
        if not any(n):
            raise ValueError('Exact hull created a collinear triangle')
        sign = dot(n, sub(inside4, tuple(4*x for x in p[t[0]])))
        if not sign:
            raise ValueError('Hull face contains the strictly interior seed')
        return (t[0], t[2], t[1]) if sign > 0 else t

    faces = [outward(t) for t in ((a,b,c), (a,b,d), (a,c,d), (b,c,d))]
    for i in ids:
        if i in tetra:
            continue
        visible = [t for t in faces if dot(normal(t), sub(p[i], p[t[0]])) > 0]
        if not visible:
            continue
        edges = Counter((t[j], t[(j+1)%3]) for t in visible for j in range(3))
        horizon = [(u,v) for u,v in edges if (v,u) not in edges]
        removed = set(visible)
        faces = [t for t in faces if t not in removed]
        faces += [outward((u,v,i)) for u,v in horizon]
    directed = Counter((t[j],t[(j+1)%3]) for t in faces for j in range(3))
    if any(n != 1 or directed[v,u] != 1 for (u,v),n in directed.items()):
        raise ValueError('Exact hull failed directed edge closure')
    if any(dot(normal(t), sub(v,p[t[0]])) > 0 for t in faces for v in p):
        raise ValueError('Exact hull failed source containment')
    volume6 = sum(dot(p[t[0]], cross(p[t[1]], p[t[2]])) for t in faces)
    if volume6 <= 0:
        raise ValueError('Exact hull has nonpositive signed volume')
    return faces, dict(method='Incremental hull with exact integer predicates on captured coordinates',
        exact_source_containment=True, exact_directed_edge_closure=True,
        volume_numerator=str(volume6), volume_denominator=str(6*denominator**3),
        duplicate_source_positions=len(raw)-len(ids))


def checked_hull(points, containment_tolerance=0.0001):
    points = np.asarray(points, dtype=float)
    if points.ndim != 2 or points.shape[1] != 3 or len(points) < 4 or not np.isfinite(points).all():
        raise ValueError('Hull requires at least four finite float3 points')
    center = points.mean(axis=0)
    local = points-center
    faces, exact = exact_hull(points.tolist())
    triangles = np.asarray(faces, dtype=int)
    if not len(triangles):
        raise ValueError('Empty vertex hull')
    tris = local[triangles]
    normals = np.cross(tris[:, 1]-tris[:, 0], tris[:, 2]-tris[:, 0])
    lengths = np.linalg.norm(normals, axis=1)
    if np.any(lengths <= 0):
        raise ValueError('Degenerate hull triangle')
    # Winding is established by exact predicates; do not override it using a
    # rounded center/normal test on tiny facets.
    normals /= lengths[:, None]
    edges = Counter((int(t[i]), int(t[(i+1)%3])) for t in triangles for i in range(3))
    if any(n != 1 or edges[b, a] != 1 for (a, b), n in edges.items()):
        raise ValueError('Hull edges are not closed and consistently oriented')
    if len({tuple(sorted(t)) for t in triangles}) != len(triangles):
        raise ValueError('Duplicate hull face')
    tris = local[triangles]
    volume = float(np.einsum('ij,ij->i', tris[:, 0], np.cross(tris[:, 1], tris[:, 2])).sum()/6)
    violation = float(max(0, (local@normals.T-np.einsum('ij,ij->i', tris[:, 0], normals)).max()))
    if volume <= 0 or violation > containment_tolerance:
        raise ValueError(f'Invalid hull: volume={volume}, containment violation={violation}')
    return triangles, normals, dict(closed=True, consistently_oriented=True,
        volume=volume, minimum_triangle_area=float(lengths.min()/2),
        max_source_point_outside_hull=violation, containment_tolerance=containment_tolerance,
        source_vertices=len(points), used_vertices=len(set(triangles.ravel().tolist())),
        triangles=len(triangles), exact=exact, method='Exact-predicate convex hull; original vertex indices and coordinates')


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
