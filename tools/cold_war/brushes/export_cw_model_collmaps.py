"""One BO3 local-space collision prefab per pointer-verified CW render model."""

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
import re
from pathlib import Path
import numpy as np
from cw_canonical_map_planes import CanonicalPlaneWriter
from build_cw_bo3_brush_prototype import read_map_planes
from decode_cw_local_physics import prepare
from assign_cw_bo3_types import build_assignments
from export_cross_map_cw_geometry import decode_brushes
from cw_exact_vertex_hull import exact_hull
from cw_model_collision_policy import apply as model_clip_policy, POLICY
from export_cw_radiant_brushes import pieces
from cw_export_layout import reserve_export_directory
from stock_material_metadata import write_stock_metadata
from cw_collision_role_policy import REFERENCE_LAYER


def export(normalized, native, geometry, assignments, destination,reference):
    normalized=normalized.resolve();native=native.resolve();destination=destination.resolve()
    capture=json.loads((normalized/'capture.json').read_text())
    owners=json.loads((native/'model_collision_owners.json').read_text())
    if owners['status']!='captured' or not owners.get('readback_unchanged'):
        raise ValueError('Model collision ownership changed during capture')
    local_root=normalized.parent/'model_local'
    local,components=prepare(native,local_root)
    local['map']=capture['map'];(local_root/'capture.json').write_text(json.dumps(local,indent=2))
    assignments=build_assignments(local_root,native,reference)
    (local_root/'material_assignments.json').write_text(json.dumps(assignments,indent=2))
    research=normalized.parent/'physics_research';research.mkdir(exist_ok=True)
    (research/'source_material_assignments.json').write_text(json.dumps(dict(
        policy=POLICY,physics_conversion_verified=False,
        note='Source physics/type evidence only; never import this folder as model collision. No rigid-body or compact-triangle reconstruction is published.',
        assignments=assignments),indent=2))
    by_pointer={int(m['record_address'],16):m for m in local['models']}
    geometry=local_root/'geometry';(geometry/'hull-cache').mkdir(parents=True,exist_ok=True)
    for model in local['models']:
        raw=(local_root/model['payload']['file']).read_bytes();decoded=decode_brushes(raw,model)
        for brush in decoded['brushes']:
            faces,checks=exact_hull(brush['vertices'])
            parts,certificate=pieces(brush['vertices'],faces,64)
            (geometry/'hull-cache'/f"{model['index']}_{brush['brush_index']}.json").write_text(json.dumps(dict(
                payload_sha256=model['payload']['sha256'],parts=[(v.tolist(),eq.tolist()) for v,eq in parts],certificate=certificate)))
    results=[];unresolved=[];planned=[];filenames={};writer=CanonicalPlaneWriter()
    unrelated_loaded_models=0
    for owner in owners['models']:
        model=by_pointer.get(int(owner['collision_pointer'],16))
        if model is None:
            component=components.get(owner['collision_pointer'])
            if component is None:unrelated_loaded_models+=1;continue
            unresolved.append(dict(**owner,reason=component));continue
        if model['status']!='decoded':
            unresolved.append(dict(**owner,reason=model['status']));continue
        # A name may contain an asset directory. Flatten it deterministically;
        # append the identity hash only if flattening/case creates a collision.
        name=re.sub(r'[^A-Za-z0-9_.-]+','_',owner['name']).strip('. ')
        if not name or name.split('.')[0].upper() in {'CON','PRN','AUX','NUL',*[f'COM{i}' for i in range(10)],*[f'LPT{i}' for i in range(10)]}:
            name='xmodel_'+owner['name_hash'].removeprefix('0x')
        identity=(owner['name_hash'],owner['collision_pointer'])
        if name.casefold() in filenames:
            if filenames[name.casefold()]==identity:continue
            name+='_'+owner['name_hash'].removeprefix('0x')
        if name.casefold() in filenames and filenames[name.casefold()]!=identity:raise ValueError('Model filename identity conflict')
        filenames[name.casefold()]=identity
        planned.append((owner,model,name+'.map'))
    # Model collmaps share a map-named root across brush captures. Reserve a
    # separate run so older materials/geometry cannot abort this brush export,
    # and earlier files and their ownership manifest always stay together.
    destination=reserve_export_directory(destination)
    # All geometry comes from the verified LOCAL hull cache. Instance transforms
    # never enter this exporter; the cache records its bounded cleanup policy.
    for owner,model,filename in planned:
        buckets={}
        for bi in range(model['brush_count']):
            cached=json.loads((geometry/'hull-cache'/f"{model['index']}_{bi}.json").read_text())
            if cached['payload_sha256']!=model['payload']['sha256']:raise ValueError('Local geometry cache identity mismatch')
            source_assignment=assignments['brushes'][f"{model['index']}:{bi}"]
            decision=model_clip_policy(source_assignment,reference)
            role=decision.get('prefab_role','model_collision')
            bucket=buckets.setdefault(role,dict(layers={'000_Global'},body=[],bounds=[],certificates=[],assignments=[],plane_error=0.,outside=0.))
            bucket['assignments'].append(dict(source_brush=bi,**decision))
            material=decision['material']
            layer=REFERENCE_LAYER if role=='reference_brushes' else '000_Global/'+material
            bucket['layers'].add(layer)
            bucket['certificates'].append(cached['certificate'])
            for vertices,equations in cached['parts']:
                pts=np.asarray(vertices);eq=np.asarray(equations)
                lines=writer.lines(eq,pts.mean(axis=0),material)
                parsed=np.array(read_map_planes('\n'.join(lines)))
                err=float(np.abs(parsed-eq).max());out=float((pts@parsed[:,:3].T-parsed[:,3]).max())
                if not np.isfinite(parsed).all() or err>1e-6 or out>1e-6:raise ValueError('Local collision serialization drift')
                bucket['plane_error']=max(bucket['plane_error'],err);bucket['outside']=max(bucket['outside'],out)
                bucket['bounds'].extend((pts.min(axis=0),pts.max(axis=0)))
                bucket['body'].append(f'// brush {len(bucket["body"])}\n{{\nlayer "{layer}"\n'+'\n'.join(lines)+'\n}')
        for role,bucket in buckets.items():
            text='iwmap 4\n'+''.join(f'"{l}" flags'+(' active' if l=='000_Global' else ' ignore' if l==REFERENCE_LAYER else '')+'\n' for l in sorted(bucket['layers']))+'// entity 0\n{\n"classname" "worldspawn"\n'+'\n'.join(bucket['body'])+'\n}\n'
            relative=filename if role=='model_collision' else 'references/'+filename
            data=text.replace('\n','\r\n').encode();target=destination/relative
            target.parent.mkdir(parents=True,exist_ok=True)
            with target.open('xb') as output:output.write(data)
            results.append(dict(**owner,file=relative,prefab_role=role,collision_asset_index=model['index'],
                compile_excluded=role=='reference_brushes',
                source_brushes=len(bucket['assignments']),total_model_source_brushes=model['brush_count'],
                output_brushes=len(bucket['body']),sha256=hashlib.sha256(data).hexdigest(),local_mins=np.min(bucket['bounds'],axis=0).tolist(),
                local_maxs=np.max(bucket['bounds'],axis=0).tolist(),max_plane_error=bucket['plane_error'],max_vertex_outside=bucket['outside'],
                bounded_cleanup=bucket['certificates'],model_collision_assignments=bucket['assignments'],
                compact_triangle_surfaces_not_exported=model['component_source']['compact_triangle_surfaces_not_exported'],
                component_source=model['component_source']))
    report=dict(schema='greyhound-cw-local-model-collmaps-v2',map=capture['map'],game='black_ops_cw',
        model_collision_policy=POLICY,physics_conversion_verified=False,physics_research=str(research),
        coordinates='model_local',instance_transforms_applied=False,ownership='loaded XModel.XCollisionPtr exact address join',
        model_count=len(planned),file_count=len(results),files=results,unresolved=unresolved,compiled=False,
        complete_model_collision=False,unrelated_loaded_models=unrelated_loaded_models,
        limitation='Convex brush components only. Compact triangle components are not yet verified and are omitted, including alongside exported brushes. No bounding-box substitute.',
        source_capture=str(native),local_capture=str(local_root),ownership_sha256=hashlib.sha256((native/'model_collision_owners.json').read_bytes()).hexdigest())
    if results:
        report['embedded_data']=write_stock_metadata(destination,reference,assignments)
        report['stock_materials_only']=True
        for record in results:
            record['sha256']=hashlib.sha256((destination/record['file']).read_bytes()).hexdigest()
    (destination/'manifest.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    (destination/'README.txt').write_text(
        'Cold War local model collision: '+capture['map']+'\n\n'
        'One model-named .map per supported convex brush component.\n'
        'Coordinates stay relative to the source model origin; no instance transform or recentering.\n'
        'Use each file with its matching model. Do not insert every file at world origin.\n\n'
        'Coverage is incomplete: compact triangle components are omitted, including alongside exported brushes.\n'
        'Root .map files contain model collision. references/ contains optional nonblocking shapes.\n'
        'Reference shapes use the visible CW_Reference layer, excluded from compilation (ignore flag).\n'
        'Source non-colliding shapes and unsupported player-clip fallbacks never enter model collision.\n'
        'Physics-only shapes remain in references/; proposed clips are recorded but not applied.\n'
        'See manifest.json for ownership, geometry checks, missing components, and unresolved models.\n'
        'No BO3 compilation or gameplay validation has been performed.\n',encoding='utf-8')
    return dict(folder=str(destination),models=len(planned),brushes=sum(r['output_brushes'] for r in results),
        collision_brushes=sum(r['output_brushes'] for r in results if r['prefab_role']=='model_collision'),
        reference_brushes=sum(r['output_brushes'] for r in results if r['prefab_role']=='reference_brushes'),
        unresolved=len(unresolved),coordinates='model_local',complete_model_collision=False,
        limitation=report['limitation'])
