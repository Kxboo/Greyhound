"""Offline, provisional CW compact-surface decoding for seven reference models.

Section layout uses the pointer-checked compound reader. Packed coordinate
ordering and strip interpretation remain candidates, not renderer-verified.
No published collmap is changed.
"""

# Support direct execution and the isolated packaged Python runtime.
import sys as _tool_sys
from pathlib import Path as _ToolPath
TOOLS_ROOT = next(p for p in _ToolPath(__file__).resolve().parents if (p / "tool_bootstrap.py").is_file())
_tool_sys.path.insert(0, str(TOOLS_ROOT))
import tool_bootstrap as _tool_bootstrap
_tool_bootstrap.activate(__file__)
REPO_ROOT = TOOLS_ROOT.parent
import collections,hashlib,itertools,json,struct,sys
from pathlib import Path
import numpy as np
from scipy.spatial import ConvexHull
from audit_cw_clip_payloads import read_logical

REPO=Path(__file__).resolve().parents[3]
ROOT=REPO/'src/WraithXCOD/x64/Release/exported_files/black_ops_cw/brushes/zm_tungsten/diagnostics'

def decode_surfaces(raw,base):
    bindings,count=struct.unpack_from('<2H',raw,296)
    header=(304+bindings+7)&~7;pos=header+80*count
    assert bindings and header<=len(raw) and pos<=len(raw)
    for s in range(count):
        h=header+80*s
        ptrs=struct.unpack_from('<4Q',raw,h)
        tail=struct.unpack_from('<I',raw,h+32)[0]
        ng,n8,n16=struct.unpack_from('<3H',raw,h+38)
        box=np.array(struct.unpack_from('<6f',raw,h+44)).reshape(2,3)
        flags=struct.unpack_from('<2I',raw,h+68)
        b8=pos;b16=(b8+3*n8+1)&~1;groups=(b16+6*n16+3)&~3;tree=groups+4*ng;pos=tree+tail
        assert pos<=len(raw)
        checks=0
        for p,o,n in zip(ptrs,(b16,b8,groups,tree),(6*n16,3*n8,4*ng,tail)):
            if p:assert p==base+o and n;checks+=1
        vertices=[];triangles=[];modes=collections.Counter();cover={1:set(),2:set()}
        for i in range(ng):
            w=struct.unpack_from('<I',raw,groups+4*i)[0]
            width=1 if w>>31 else 2;strip=bool(w&(1<<30));field=(w>>26)&15
            n=field+3 if strip else 3*(field+1);start=w&0x3fff
            assert start+n<=(n8 if width==1 else n16)
            cover[width].update(range(start,start+n));modes[f'{width}-byte-'+('strip' if strip else 'batch')]+=1
            at=(b8 if width==1 else b16)+3*width*start
            vals=struct.unpack_from('<'+str(3*n)+('B' if width==1 else 'H'),raw,at)
            offsets=[32*((w>>(14+4*k))&15) if width==1 else 0 for k in range(3)]
            offset=len(vertices)
            for j in range(n):
                vertices.append([box[0,k]+offsets[k]+vals[k*n+j if strip else (j%3)*3*(field+1)+k*(field+1)+j//3]/8 for k in range(3)])
            tri=([(j,j+1,j+2) if j%2==0 else (j+1,j,j+2) for j in range(n-2)] if strip else [(j,j+1,j+2) for j in range(0,n,3)])
            triangles.extend(tuple(offset+j for j in t) for t in tri)
        assert vertices
        vertices,inv=np.unique(np.array(vertices),axis=0,return_inverse=True)
        triangles=inv[np.array(triangles)]
        a,b,c=vertices[triangles].transpose(1,0,2)
        nonzero=np.linalg.norm(np.cross(b-a,c-a),axis=1)>1e-9
        triangles=triangles[nonzero]
        edges=collections.Counter();directed=collections.Counter()
        for t in triangles:
            for i,j in zip(t,np.roll(t,-1)):
                edges[tuple(sorted((int(i),int(j))))]+=1;directed[int(i),int(j)]+=1
        closed=all(n==2 for n in edges.values())
        oriented=closed and all(directed[j,i]==n for (i,j),n in directed.items())
        hull=ConvexHull(vertices);eq=hull.equations
        eq=np.unique(np.round(eq,8),axis=0)
        on_support=[bool(np.any(np.all(np.abs(vertices[t]@eq[:,:3].T+eq[:,3])<1e-6,axis=0))) for t in triangles]
        a,b,c=vertices[triangles].transpose(1,0,2)
        area=float(np.linalg.norm(np.cross(b-a,c-a),axis=1).sum()/2)
        signed=float(np.einsum('ij,ij->i',a,np.cross(b,c)).sum()/6)
        report=dict(surface=s,bounds=box.tolist(),decoded_bounds=[vertices.min(0).tolist(),vertices.max(0).tolist()],
            bounds_error=float(np.max(np.abs(np.array([vertices.min(0),vertices.max(0)])-box))),
            verified_section_pointers=checks,vertices=len(vertices),triangles=len(triangles),
            degenerate_triangles=int((~nonzero).sum()),modes=dict(modes),
            complete_coordinate_coverage=len(cover[1])==n8 and len(cover[2])==n16,
            open_edges=sum(n==1 for n in edges.values()),nonmanifold_edges=sum(n>2 for n in edges.values()),
            closed=closed,consistent_edge_winding=oriented,signed_volume=signed,
            convex_hull_volume=float(hull.volume),convex_hull_area=float(hull.area),mesh_area=area,
            convex_support_planes=len(eq),triangles_on_convex_support=sum(on_support),
            convex_boundary_candidate=oriented and all(on_support) and abs(abs(signed)-hull.volume)<1e-6*max(1,hull.volume) and abs(area-hull.area)<1e-6*max(1,hull.area),
            raw_contents=hex(flags[0]),raw_surface=hex(flags[1]))
        yield vertices,triangles,eq,report

def main():
    refs=json.loads((REPO/'test-output/collmap-crossref/comparison.json').read_text())['models']
    wanted={r['name'] for r in refs}
    evidence=json.loads((ROOT/'evidence.json').read_text())
    models=json.loads((ROOT/'clip_map_models.json').read_text())['models']
    results=[]
    out=REPO/'test-output/compact-shape-example';out.mkdir(exist_ok=True,parents=True)
    for m in models:
        if m['name'] not in wanted:continue
        raw=read_logical(ROOT,evidence,m['payload']['file'])
        row=dict(name=m['name'],source_sha256=hashlib.sha256(raw).hexdigest(),surfaces=[])
        try:
            for vertices,triangles,eq,r in decode_surfaces(raw,int(m['payload']['address'],16)):
                row['surfaces'].append(r)
                print(m['name'],json.dumps(r),flush=True)
        except (ValueError,AssertionError,struct.error) as exc:row['error']=str(exc) or type(exc).__name__
        results.append(row)
    (out/'analysis.json').write_text(json.dumps(dict(status='Provisional triangle interpretation. Internal geometry checks are not independent confirmation of source topology.',models=results),indent=2))

if __name__=='__main__':main()
