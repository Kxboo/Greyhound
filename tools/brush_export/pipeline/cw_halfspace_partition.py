"""Spatial subdivision retaining supplied exterior planes, without rehulling."""
import numpy as np
from scipy.spatial import HalfspaceIntersection, ConvexHull
from scipy.optimize import linprog
from cw_exact_vertex_hull import exact_hull

def volume(points):
    # Independent exact predicates avoid Qhull's wide-facet merge failures on
    # nearly coincident intersection vertices. No QJ jitter or allow-wide flag.
    _,cert=exact_hull(points.tolist())
    return int(cert['volume_numerator'])/int(cert['volume_denominator'])


def polytope(eq):
    # Work near the local origin, supplied by the caller.
    r=linprog([0.,0.,0.,-1.],A_ub=np.column_stack((eq[:,:3],np.ones(len(eq)))),b_ub=eq[:,3],bounds=[(None,None)]*3+[(0,None)],method='highs')
    if not r.success or r.x[3]<=1e-9:raise ValueError('No positive interior for partition')
    h=HalfspaceIntersection(np.column_stack((eq[:,:3],-eq[:,3])),r.x[:3])
    v=h.intersections
    if not np.isfinite(v).all() or np.max(v@eq[:,:3].T-eq[:,3])>1e-6:raise ValueError('Invalid partition vertices')
    return v,eq[np.unique([i for facet in h.dual_facets for i in facet])]


def partition(points,equations,limit=12):
    center=points.mean(axis=0);eq=equations.copy();eq[:,3]-=eq[:,:3]@center
    vertices,eq=polytope(eq);todo=[(vertices,eq,0)];done=[];splits=[];fallbacks=[]
    while todo:
        v,e,depth=todo.pop()
        if len(e)<=limit:
            world=e.copy();world[:,3]+=world[:,:3]@center;done.append((v+center,world));continue
        if depth>=24 or len(done)+len(todo)>4096:raise ValueError('Partition guard reached')
        choices=[]
        directions=list(np.eye(3))
        if depth>0:directions += [np.array(x)/np.linalg.norm(x) for x in [(1,1,0),(1,-1,0),(1,0,1),(0,1,1),(1,1,1)]]
        for n in directions:
            projection=v@n
            for d in np.unique([np.median(projection),(projection.min()+projection.max())/2]):
                if d<=projection.min()+1e-7 or d>=projection.max()-1e-7:continue
                cut=np.r_[n,d]
                try:
                    a=polytope(np.vstack((e,cut)));b=polytope(np.vstack((e,-cut)))
                except (ValueError,RuntimeError):continue
                score=(max(len(a[1]),len(b[1])),len(a[1])+len(b[1]))
                choices.append((score,a,b,cut))
        if not choices:raise ValueError('No bounded spatial cut')
        score,a,b,cut=min(choices,key=lambda x:x[0])
        if score[0]>=len(e):
            residual=np.abs(v@e[:,:3].T-e[:,3]);peak=v[np.argmax(np.sum(residual<1e-6,axis=1))]
            # A cut through the high-valence corner splits its fan instead of
            # keeping every incident side on one child.
            extra=[]
            normals=directions+[np.array(x)/np.linalg.norm(x) for x in [(1,0,-1),(0,1,-1),(1,1,-1),(1,-1,1),(-1,1,1)]]
            edges=v-peak;edge=edges[np.argmax(np.linalg.norm(edges,axis=1))]
            cross_lengths=np.linalg.norm(np.cross(edges,edge),axis=1)
            if cross_lengths.max()>1e-8:
                other=edges[np.argmax(cross_lengths)];aa=edge@edge;ab=edge@other;bb=other@other;normal=(bb+ab)*edge-(aa+ab)*other
                if np.linalg.norm(normal)>0:normals.append(normal/np.linalg.norm(normal))
            for n in normals:
                projection=v@n
                for d in np.unique([peak@n,*projection]):
                    if d<=projection.min()+1e-7 or d>=projection.max()-1e-7:continue
                    cut=np.r_[n,d]
                    try:a=polytope(np.vstack((e,cut)));b=polytope(np.vstack((e,-cut)))
                    except (ValueError,RuntimeError):continue
                    score2=(max(len(a[1]),len(b[1])),len(a[1])+len(b[1]))
                    extra.append((score2,a,b,cut))
            if extra:
                improved=min(extra,key=lambda x:x[0])
                if improved[0]<score:score,a,b,cut=improved
        if score[0]>=len(e):
            # A conical fan can retain all sides under every tested spatial cut.
            # Partition only this small leaf, rather than tetrahedralizing the
            # entire source brush. The helper checks exact volume and closure.
            from export_cw_radiant_brushes import pieces
            faces,_=exact_hull(v.tolist())
            tets,certificate=pieces(v.tolist(),faces,4)
            fallbacks.append(dict(parent_faces=len(e),**certificate))
            for points,planes in tets:
                shifted=planes.copy();shifted[:,3]+=shifted[:,:3]@center
                done.append((points+center,shifted))
            continue
        parent_volume=volume(v)
        child_volume=volume(a[0])+volume(b[0])
        volume_error=abs(child_volume-parent_volume)/parent_volume
        if volume_error>1e-7:raise ValueError('Partition volume changed')
        splits.append(dict(parent_faces=len(e),child_faces=[len(a[1]),len(b[1])],plane=cut.tolist(),relative_volume_error=volume_error))
        todo.extend([(a[0],a[1],depth+1),(b[0],b[1],depth+1)])
    return done,dict(partitioned=bool(splits or fallbacks),pieces=len(done),source_support_planes=len(equations),cuts=splits,tetrahedral_fallback_regions=fallbacks,partition_center=center.tolist(),method='Complementary halfspace cuts with local certified tetrahedra when cuts stall; floating-point intersection and redundancy checks')

