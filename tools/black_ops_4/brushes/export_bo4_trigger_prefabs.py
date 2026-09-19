"""BO4 trigger/volume hulls, with provisional spawn-order association explicit."""

# Support direct execution and the isolated packaged Python runtime.
import sys as _tool_sys
from pathlib import Path as _ToolPath
TOOLS_ROOT = next(p for p in _ToolPath(__file__).resolve().parents if (p / "tool_bootstrap.py").is_file())
_tool_sys.path.insert(0, str(TOOLS_ROOT))
import tool_bootstrap as _tool_bootstrap
_tool_bootstrap.activate(__file__)
REPO_ROOT = TOOLS_ROOT.parent
import hashlib
import json
import struct
from collections import Counter, defaultdict
from pathlib import Path
import numpy as np
from exact_cw_brush_halfspaces import reconstruct_exact
from cw_canonical_map_planes import CanonicalPlaneWriter
from build_cw_bo3_brush_prototype import read_map_planes


def export(root, output, name):
    root, output = Path(root), Path(output)
    probe = json.loads((root/'world_pools_probe.json').read_text())
    source = json.loads((root/'entity_properties.json').read_text())
    for file, digest in source['source_sha256'].items():
        if hashlib.sha256((root/file).read_bytes()).hexdigest() != digest:
            raise ValueError('Trigger source changed')
    pool = next(p for p in probe['pools'] if p['pool_index']==107)
    if len(pool['assets']) != 1: raise ValueError('Ambiguous trigger list')
    tables = {t['label']: t for t in pool['assets'][0]['tables']}
    def load(label, stride):
        t = tables[label]; raw = (root/t['file']).read_bytes()
        if t['status']!='captured_stable' or not t['readback_unchanged'] or t['stride']!=stride or len(raw)!=t['count']*stride:
            raise ValueError('Unstable/truncated trigger table')
        return raw, t['count']
    models, nm = load('trigger_models', 8)
    hulls, nh = load('trigger_hulls', 32)
    slabs, ns = load('trigger_slabs', 20)
    entities = source['pools']['107']['entities']
    geometric = [e for e in entities if e['properties'].get('classname') not in ('trigger_box_new','trigger_radius_new')]
    if len(geometric) != nm: raise ValueError('Spawn-order association count failed; no guessed placement exported')
    writer = CanonicalPlaneWriter(); groups = defaultdict(list); rows=[]; omissions=[]
    used_hulls=[]; used_slabs=[]
    for model_index, e in enumerate(geometric):
        contents, count, first = struct.unpack_from('<IHH', models, model_index*8)
        if first+count > nh or not count: raise ValueError('Invalid trigger hull range')
        used_hulls.extend(range(first,first+count))
        cls=e['properties']['classname']; group='volumes' if cls=='info_volume' else 'triggers'
        # Export inspection geometry rather than claiming BO4 scripts have been ported.
        material='volume' if group=='volumes' else 'trigger'
        if any(abs(a)%360 > 1e-5 for a in e['angles']):
            omissions.append(dict(entity=e['index'],reason='Rotated trigger frame unverified',source=e)); continue
        for hi in range(first, first+count):
            v=struct.unpack_from('<6fIHH',hulls,hi*32); center=np.array(v[:3]);half=np.array(v[3:6])
            hc,sc,sf=v[6:]
            if np.any(half<=0) or sf+sc>ns or hc & ~contents: raise ValueError('Invalid trigger hull bounds/contents')
            equations=[]
            for axis in range(3):
                n=np.eye(3)[axis];equations.extend([[*n,center[axis]+half[axis]],[*(-n),half[axis]-center[axis]]])
            for si in range(sf,sf+sc):
                d=np.array(struct.unpack_from('<5f',slabs,si*20));used_slabs.append(si)
                if not np.isfinite(d).all() or d[4]<0 or abs(np.linalg.norm(d[:3])-1)>1e-4: raise ValueError('Invalid trigger slab')
                equations.extend([[*d[:3],d[3]+d[4]],[*(-d[:3]),d[4]-d[3]]])
            equations=np.array(equations);equations/=np.linalg.norm(equations[:,:3],axis=1)[:,None];mesh=reconstruct_exact(equations)
            if mesh['bad_directed_edges'] or mesh['volume']<=0: raise ValueError('Open trigger hull')
            active=[f['side_candidates'][0] for f in mesh['faces']]
            if len(active)>64: raise ValueError('Trigger needs face-limit partition')
            points=np.array(mesh['vertices'])+e['origin'];eq=equations[active].copy();eq[:,3]+=eq[:,:3]@e['origin']
            lines=writer.lines(eq,points.mean(0),material);parsed=np.array(read_map_planes('\n'.join(lines)))
            error=float(abs(parsed-eq).max())
            if error>1e-6 or (points@parsed[:,:3].T-parsed[:,3]).max()>1e-6: raise ValueError('Trigger planes moved')
            layer=f'000_Global/BO4_{group.upper()}_ASSOCIATION_REVIEW/{cls}'
            groups[group].append((layer,'// brush '+str(len(rows))+'\n{\nlayer "'+layer+'"\n'+'\n'.join(lines)+'\n}\n'))
            rows.append(dict(entity_index=e['index'],model_index=model_index,hull_index=hi,
                classname=cls,source_properties=e['properties'],origin=e['origin'],angles=e['angles'],
                prefab_group=group,material=material,plane_error=error,
                placement_status='SPAWN_ORDER_ASSOCIATION_REQUIRES_RUNTIME_CONFIRMATION'))
    if sorted(used_hulls)!=list(range(nh)): raise ValueError('Trigger models do not partition hulls')
    files={};output.mkdir(parents=True,exist_ok=True)
    for group, bodies in groups.items():
        layers={'000_Global',f'000_Global/BO4_{group.upper()}_ASSOCIATION_REVIEW'}|{l for l,_ in bodies}
        text='iwmap 4\n'+''.join('"'+l+'" flags\n' for l in sorted(layers))+'// entity 0\n{\n"classname" "worldspawn"\n'+''.join(b for _,b in bodies)+'}\n'
        path=output/(name+'_'+group+'_review.map');path.write_bytes(text.replace('\n','\r\n').encode())
        if path.read_text().count('// brush ')!=len(bodies):raise ValueError('Trigger prefab count changed')
        files[path.name]=dict(brushes=len(bodies),sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    for e in entities:
        if e not in geometric: omissions.append(dict(entity=e['index'],reason='Parameter trigger retained in JSON; no fabricated box',source=e))
    report=dict(schema='greyhound-bo4-trigger-prefabs-v1',map_files=files,rows=rows,omissions=omissions,
        classes=source['pools']['107']['classes'],hulls_accounted=nh,slabs_referenced=len(set(used_slabs)),
        association='Equal ordered counts support but do not prove model-to-spawn association; prefabs are marked REVIEW.',
        gameplay_ported=False,compiled=False)
    (output/'triggers.json').write_text(json.dumps(report,separators=(',',':'))+'\n')
    return report
