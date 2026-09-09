"""Optional outer-hull cleanup, measured against the preserved source hull."""
import numpy as np
from scipy.spatial import HalfspaceIntersection, ConvexHull
from scipy.optimize import linprog
from export_cw_full_brush_map import hull_planes
def surface_distances(points,triangles):
    """Closest Euclidean distance to triangles, including edges and vertices."""
    a,b,c=triangles[:,0],triangles[:,1],triangles[:,2]
    ab=b-a;ac=c-a
    normal=np.cross(ab,ac);lengths=np.linalg.norm(normal,axis=1)
    if np.any(lengths<=0):
        raise ValueError('Degenerate comparison triangle')
    normal/=lengths[:,None]
    results=[]
    for point in points:
        ap=point-a
        signed=np.einsum('ij,ij->i',ap,normal)
        projected=point-signed[:,None]*normal
        tests=[]
        for x,y in ((a,b),(b,c),(c,a)):
            tests.append(np.einsum('ij,ij->i',np.cross(y-x,projected-x),normal))
        # Do not give tiny facets a large implicit area tolerance. Boundary
        # roundoff can fall through to the exact edge-distance calculation.
        inside=np.min(tests,axis=0)>=0
        distance=np.where(inside,abs(signed),np.inf)
        for x,y in ((a,b),(b,c),(c,a)):
            edge=y-x
            t=np.einsum('ij,ij->i',point-x,edge)/np.einsum('ij,ij->i',edge,edge)
            closest=x+np.clip(t,0,1)[:,None]*edge
            distance=np.minimum(distance,np.linalg.norm(point-closest,axis=1))
        results.append(float(distance.min()))
    return results




def cleanup(vertices, faces, tolerance, method='cluster'):
    points = np.asarray(vertices, dtype=float)
    original = hull_planes(dict(vertices=vertices, faces=faces))
    center = points.mean(axis=0)
    local = points-center
    equations = original.copy()
    equations[:,3] -= equations[:,:3]@center
    # Keep one existing support plane for each narrowly agreeing group. This
    # only removes constraints; it never pulls a source point inward.
    active = []
    for i, plane in enumerate(equations):
        if any(np.dot(plane[:3],equations[j,:3]) > .9999 and
               np.max(np.abs(local@(plane[:3]-equations[j,:3])-(plane[3]-equations[j,3]))) <= tolerance/4
               for j in active):
            continue
        active.append(i)
    if method=='linear_program' and len(equations)>12:
        active=list(range(len(equations)))
        for i in list(active):
            other=[j for j in active if j!=i]
            candidate=equations[other]
            result=linprog(-equations[i,:3],A_ub=candidate[:,:3],b_ub=candidate[:,3],bounds=[(None,None)]*3,method='highs')
            if result.success and -result.fun-equations[i,3]<=tolerance/2:
                active.remove(i)
    if len(active)==len(original):
        return points,original,dict(changed=False,original_planes=len(original),output_planes=len(original),max_outward_distance=0.)
    eq = equations[active]
    try:
        result=HalfspaceIntersection(np.column_stack((eq[:,:3],-eq[:,3])), np.zeros(3)).intersections
        if not np.isfinite(result).all():raise ValueError('Nonfinite intersection')
        hull=ConvexHull(result)
        result=result[hull.vertices]
        # Distance to a convex set is convex, so its maximum over the outer
        # polytope is bounded by the maximum at its extreme vertices. Interior
        # vertices contribute zero; outside vertices use point-triangle distance.
        residual=result@equations[:,:3].T-equations[:,3]
        outside=result[np.max(residual,axis=1)>1e-9]
        distance=max(surface_distances(outside,local[np.asarray(faces)]),default=0.)
        violation=float(np.max(local@eq[:,:3].T-eq[:,3]))
        if distance>tolerance or violation>1e-8:raise ValueError('Cleanup exceeds declared bound')
        return result+center,original[active],dict(changed=True,original_planes=len(original),output_planes=len(active),max_outward_distance=distance,source_containment_residual=violation,local_tolerance=tolerance)
    except (ValueError,RuntimeError) as error:
        return points,original,dict(changed=False,original_planes=len(original),output_planes=len(original),max_outward_distance=0.,rejected=str(error))
