"""Read back published local collmaps and compare every face with its local hull."""

# Support direct execution and the isolated packaged Python runtime.
import sys as _tool_sys
from pathlib import Path as _ToolPath
TOOLS_ROOT = next(p for p in _ToolPath(__file__).resolve().parents if (p / "tool_bootstrap.py").is_file())
_tool_sys.path.insert(0, str(TOOLS_ROOT))
import tool_bootstrap as _tool_bootstrap
_tool_bootstrap.activate(__file__)
REPO_ROOT = TOOLS_ROOT.parent
import argparse,hashlib,json,re,sys
from pathlib import Path
import numpy as np
from build_cw_bo3_brush_prototype import read_map_planes


def verify(folder):
    manifest=json.loads((folder/'manifest.json').read_text())
    source=Path(manifest['source_capture'])
    local=Path(manifest.get('local_capture',source/'radiant_work/model_local'))
    capture=json.loads((local/'capture.json').read_text())
    models={m['index']:m for m in capture['models']}
    seen=set();coverage={};total=0;max_error=0.;max_outside=0.
    for record in manifest['files']:
        name=record['file'];assert name.casefold() not in seen;seen.add(name.casefold())
        file=folder/name;raw=file.read_bytes();assert hashlib.sha256(raw).hexdigest()==record['sha256']
        text=raw.decode();assert 'misc_prefab' not in text and '"origin"' not in text and '"angles"' not in text
        blocks=re.findall(r'// brush \d+\s*\{(.*?)\n\}',text,re.S)
        model=models[record['collision_asset_index']];expected=[]
        identity=(record['name_hash'],record['collision_pointer'])
        indices=[r['source_brush'] for r in record['model_collision_assignments']]
        assert len(indices)==len(set(indices))==record['source_brushes']
        covered=coverage.setdefault(identity,set())
        assert not covered.intersection(indices);covered.update(indices)
        for bi in indices:
            cache=json.loads((local/'geometry/hull-cache'/f"{model['index']}_{bi}.json").read_text())
            assert cache['payload_sha256']==model['payload']['sha256']
            expected.extend(cache['parts'])
        assert len(blocks)==len(expected)==record['output_brushes']
        if record.get('prefab_role')=='reference_brushes':
            from cw_collision_role_policy import REFERENCE_MATERIAL, REFERENCE_LAYER
            assert all(set(re.findall(r'^\s*\(.*\)\s+(\S+)\s+', b, re.M))=={REFERENCE_MATERIAL} for b in blocks)
            if record.get('compile_excluded'):
                assert f'"{REFERENCE_LAYER}" flags ignore' in text
                assert all(f'layer "{REFERENCE_LAYER}"' in b for b in blocks)
        elif manifest['schema']=='greyhound-cw-local-model-collmaps-v2':
            assert all(not r.get('physics_fallback') and r.get('prefab_role')=='model_collision'
                       for r in record['model_collision_assignments'])
        for block,(vertices,equations) in zip(blocks,expected):
            actual=np.array(read_map_planes(block));eq=np.array(equations);points=np.array(vertices)
            assert actual.shape==eq.shape and 4<=len(actual)<=64 and np.isfinite(actual).all()
            error=float(np.abs(actual-eq).max());outside=float((points@actual[:,:3].T-actual[:,3]).max())
            assert error<=1e-6 and outside<=1e-6
            max_error=max(max_error,error);max_outside=max(max_outside,outside);total+=1
    assert len(seen)==len(list(folder.rglob('*.map')))
    assert len(coverage)==manifest['model_count']
    for record in manifest['files']:
        assert coverage[(record['name_hash'],record['collision_pointer'])]==set(range(models[record['collision_asset_index']]['brush_count']))
    return dict(models=len(coverage),files=len(seen),brush_pieces=total,max_plane_error=max_error,max_local_vertex_outside=max_outside,
        local_planes_preserved=True,no_instance_transforms=True,complete_model_collision=manifest['complete_model_collision'],
        bo3_compiled=False)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('folder',type=Path);a=p.parse_args()
    print(json.dumps(verify(a.folder.resolve()),indent=2))
