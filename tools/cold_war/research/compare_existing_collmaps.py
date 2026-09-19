"""Read-only geometric comparison of named BO3/CW collmaps; no registration."""

# Support direct execution and the isolated packaged Python runtime.
import sys as _tool_sys
from pathlib import Path as _ToolPath
TOOLS_ROOT = next(p for p in _ToolPath(__file__).resolve().parents if (p / "tool_bootstrap.py").is_file())
_tool_sys.path.insert(0, str(TOOLS_ROOT))
import tool_bootstrap as _tool_bootstrap
_tool_bootstrap.activate(__file__)
REPO_ROOT = TOOLS_ROOT.parent
import itertools,json,re,hashlib
from pathlib import Path
import numpy as np
from scipy.optimize import linear_sum_assignment
from scipy.spatial import ConvexHull
from scipy.stats import qmc

REPO=Path(__file__).resolve().parents[3]
STOCK=Path('C:/Program Files (x86)/Steam/steamapps/common/Call of Duty Black Ops III/share/raw/collmaps')
EXPORTED=REPO/'src/WraithXCOD/x64/Release/exported_files/collmaps/black_ops_cw/zm_tungsten'

def parse(path):
    text=path.read_text(encoding='utf-8-sig')
    brushes=[];primitives=[]
    for block in re.split(r'// brush \d+',text)[1:]:
        primitive=re.findall(r'\bphysics_\w+\b',block)
        if primitive: primitives.extend(primitive);continue
        planes=[];materials=[]
        for line in block.splitlines():
            if not line.strip().startswith('('):continue
            groups=re.findall(r'\(\s*([^()]*)\)',line)
            assert len(groups)==3,(path,line)
            a,b,c=[np.array([float(x) for x in g.split()]) for g in groups]
            n=-np.cross(b-a,c-a);n/=np.linalg.norm(n)
            planes.append([*n,n@a]);materials.append(line.rsplit(')',1)[1].split()[0])
        if not planes:continue
        p=np.array(planes);verts=[]
        for ids in itertools.combinations(range(len(p)),3):
            h=p[list(ids)]
            if abs(np.linalg.det(h[:,:3]))<1e-10:continue
            v=np.linalg.solve(h[:,:3],h[:,3])
            if np.max(p[:,:3]@v-p[:,3])<=1e-6:verts.append(v)
        v=np.unique(np.round(verts,9),axis=0)
        assert len(v)>=4,(path,len(v))
        hull=ConvexHull(v)
        brushes.append(dict(p=p,v=v,volume=float(hull.volume),materials=sorted(set(materials))))
    return brushes,primitives

def describe(bs,primitives):
    v=np.concatenate([b['v'] for b in bs])
    return dict(brushes=len(bs),planes=sum(len(b['p']) for b in bs),primitives=primitives,
                bounds=[v.min(0).tolist(),v.max(0).tolist()],
                summed_brush_volume=sum(b['volume'] for b in bs),
                materials=sorted({m for b in bs for m in b['materials']}))

def occupied(bs,points):
    hit=np.zeros(len(points),bool)
    for b in bs:
        v=b['v'];sel=np.where((~hit)&np.all(points>=v.min(0)-1e-7,axis=1)&np.all(points<=v.max(0)+1e-7,axis=1))[0]
        hit[sel]=np.all(points[sel]@b['p'][:,:3].T<=b['p'][:,3]+1e-7,axis=1)
    return hit

def main():
    stock={p.stem:p for p in STOCK.rglob('*.map') if p.stem!='p7_debris_trash_paper_plate_01'}
    exports={p.stem:p for p in EXPORTED.glob('*.map')}
    manifest=json.loads((EXPORTED/'manifest.json').read_text())
    records={Path(r['file']).stem:r for r in manifest['files']}
    rows=[]
    for name in sorted(stock.keys()&exports.keys()):
        a,pa=parse(stock[name]);b,pb=parse(exports[name])
        av=np.concatenate([r['v'] for r in a]);bv=np.concatenate([r['v'] for r in b])
        lo=np.minimum(av.min(0),bv.min(0));hi=np.maximum(av.max(0),bv.max(0))
        points=lo+qmc.Sobol(d=3,scramble=True,seed=17).random_base2(19)*(hi-lo)
        ah=occupied(a,points);bh=occupied(b,points)
        # Match individual convex parts independent of brush order. Vertex-set
        # distance is a strict exact-match diagnostic, not surface Hausdorff.
        costs=np.empty((len(a),len(b)))
        for i,x in enumerate(a):
            for j,y in enumerate(b):
                d=np.linalg.norm(x['v'][:,None]-y['v'][None,:],axis=2)
                costs[i,j]=max(d.min(0).max(),d.min(1).max())
        ii,jj=linear_sum_assignment(costs)
        pairs=[dict(stock_brush=int(i),export_brush=int(j),max_nearest_vertex_distance=float(costs[i,j])) for i,j in zip(ii,jj)]
        row=dict(name=name,stock_file=str(stock[name]),export_file=str(exports[name]),
            stock_sha256=hashlib.sha256(stock[name].read_bytes()).hexdigest(),
            export_sha256=hashlib.sha256(exports[name].read_bytes()).hexdigest(),
            stock=describe(a,pa),exported=describe(b,pb),matched_parts=pairs,
            max_matched_vertex_distance=max(p['max_nearest_vertex_distance'] for p in pairs),
            exact_convex_part_match=len(a)==len(b) and not pa and not pb and all(p['max_nearest_vertex_distance']<1e-6 for p in pairs),
            sampled_union_iou=float((ah&bh).sum()/max(1,(ah|bh).sum())),
            stock_inside_export_fraction=float((ah&bh).sum()/max(1,ah.sum())),
            export_inside_stock_fraction=float((ah&bh).sum()/max(1,bh.sum())),
            sample_count=len(points),
            compact_triangle_surfaces_not_exported=records[name]['compact_triangle_surfaces_not_exported'])
        row['unmatched_export_brushes']=[dict(index=j,bounds=[x['v'].min(0).tolist(),x['v'].max(0).tolist()],materials=x['materials']) for j,x in enumerate(b) if j not in jj]
        # These reference collmaps are boxes. Coordinate subdivision gives an
        # exact union-volume comparison and retains holes between separate legs.
        if all(len(x['v'])==8 and np.all(np.sum(np.abs(x['p'][:,:3])>1e-8,axis=1)==1) for x in a+b):
            axes=[np.unique(np.concatenate([x['v'][:,k] for x in a+b])) for k in range(3)]
            centres=[(v[1:]+v[:-1])/2 for v in axes]
            pts=np.stack(np.meshgrid(*centres,indexing='ij'),axis=-1).reshape(-1,3)
            volume=np.prod(np.stack(np.meshgrid(*[np.diff(v) for v in axes],indexing='ij'),axis=-1),axis=-1).ravel()
            inside=[]
            for group in (a,b):
                hit=np.zeros(len(pts),bool)
                for x in group:hit|=np.all(pts>x['v'].min(0),axis=1)&np.all(pts<x['v'].max(0),axis=1)
                inside.append(hit)
            s,e=inside;inter=float(volume[s&e].sum());union=float(volume[s|e].sum())
            row['box_union']=dict(stock_volume=float(volume[s].sum()),export_volume=float(volume[e].sum()),intersection_volume=inter,union_volume=union,iou=inter/union)
        rows.append(row)
        print(name,len(a),len(b),'IoU',round(row['sampled_union_iou'],6),'vertex delta',round(row['max_matched_vertex_distance'],6),'materials',row['stock']['materials'],row['exported']['materials'],flush=True)
    out=REPO/'test-output/collmap-crossref';out.mkdir(exist_ok=True,parents=True)
    (out/'comparison.json').write_text(json.dumps(dict(excluded=['p7_debris_trash_paper_plate_01'],
        method='Halfspace intersection in original model coordinates; no alignment, scaling or recentering. Sobol occupancy overlap is an estimate. Exact part test compares all hull vertices.',models=rows),indent=2))

if __name__=='__main__':main()
