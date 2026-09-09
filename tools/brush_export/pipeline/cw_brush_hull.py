"""Checked hull topology; every face indexes the unchanged captured points.

Connectivity and containment use exact integer predicates. Metric diagnostics
use the original double precision coordinates, centered locally.
"""
from collections import Counter
import numpy as np


def checked_hull(points, containment_tolerance=0.0001):
    from cw_exact_vertex_hull import exact_hull
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
