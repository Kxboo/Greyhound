"""Incremental convex hull using exact integer predicates for dyadic inputs.

Returns original point indices. No coordinate rounding, jitter, welding, or
distance epsilon participates in visibility or orientation decisions.
"""
from collections import Counter
import math


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
