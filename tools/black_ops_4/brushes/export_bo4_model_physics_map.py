"""Certified captured BO4 model collision hulls; unknown primitives remain explicit omissions."""
# Support direct execution and the isolated packaged Python runtime.
import sys as _tool_sys
from pathlib import Path as _ToolPath
TOOLS_ROOT = next(p for p in _ToolPath(__file__).resolve().parents if (p / "tool_bootstrap.py").is_file())
_tool_sys.path.insert(0, str(TOOLS_ROOT))
import tool_bootstrap as _tool_bootstrap
_tool_bootstrap.activate(__file__)
REPO_ROOT = TOOLS_ROOT.parent

from collections import Counter
import hashlib
import json
import numpy as np
from bo4_prefab_layout import brush_role
from bo4_brush_geometry import partition, serialize_piece, publish_groups


def export(root, output, map_name="bo4_map", types=None, filters=None):
    data_path=root/'model_physics_data.json'; data=json.loads(data_path.read_text())
    if data['schema']!='greyhound-bo4-model-physics-data-v1': raise ValueError('Requires standalone BO4 physics decode')
    for name,digest in data['source_sha256'].items():
        if hashlib.sha256((root/name).read_bytes()).hexdigest()!=digest: raise ValueError('Source capture changed: '+name)
    if output.exists(): raise ValueError('Output must be new')
    models={m['pointer']:m for m in data['models']}
    cache,certificates,rows,omitted,bodies={},{},[],[],[]
    for instance in data['instances']:
        model=models[instance['model_pointer']]
        for entry in model['entries']:
            identity=dict(instance_index=instance['index'],model_pointer=model['pointer'],
                model_hash=model['hash'],model_name=model['name'],entry_index=entry['index'])
            if entry['status']!='decoded_checked_hull':
                omitted.append(dict(identity,status=entry['status'],type_raw=entry.get('type_raw')));continue
            surface_values=[]
            if filters is not None:
                ids=[*entry['axial_materials_raw'],*[s['material_raw'] for s in entry['sides']]]
                if not ids or max(ids)>=len(filters) or int(np.bitwise_or.reduce(filters[ids,1]))!=int(entry['contents_raw'],16):
                    raise ValueError('Model-physics side filters do not reproduce source contents')
                surface_values=list(map(int,filters[ids,0]))
            decision=types.choose(int(entry['contents_raw'],16),surface_values) if types else {}
            if not decision.get('material') or decision.get('visual_required'):
                omitted.append(dict(identity,status='requires_original_visual_material',type_assignment=decision));continue
            key=model['pointer']+':'+str(entry['index'])
            if key not in cache: cache[key],certificates[key]=partition(entry['points'],entry['faces'])
            parts=cache[key]
            role='tool_fallback_review' if decision.get('fallback') else brush_role(decision)
            state='MODEL_PHYSICS_CONTAINED' if instance['placement_status']=='contained' else 'MODEL_PHYSICS_BOUNDS_REVIEW'
            for piece_index,(points,equations) in enumerate(parts):
                for component_index,component in enumerate(decision['collision_components']):
                    material=component['material'];layer=f'000_Global/{state}/{material}/contents_{int(entry["contents_raw"],16):08x}'
                    body,check=serialize_piece(points,equations,np.array(instance['matrix_world']),material,
                        component.get('brush_contents',[]),layer,len(rows))
                    bodies.append(body)
                    rows.append(dict(identity,**check,map_brush_index=len(rows),layer=layer,
                        partition_index=piece_index,partition_count=len(parts),collision_component_index=component_index,
                        collision_component=component,source_contents_raw=entry['contents_raw'],instance_flags_raw=instance['flags_raw'],
                        placement_status=instance['placement_status'],faces=check['face_count'],material=material,
                        prefab_role=role,type_assignment=decision))
    files=publish_groups(output,map_name,'model_physics_',rows,bodies,'prefab_role')
    count=len({(r['instance_index'],r['entry_index']) for r in rows})
    summary=dict(brushes=len(rows),source_brush_instances=count,additional_partition_or_category_components=len(rows)-count,
        partitioned_source_hulls=sum(c['partitioned'] for c in certificates.values()),
        placements=dict(Counter(r['placement_status'] for r in rows)),
        omitted_instances_by_reason=dict(Counter(o['status'] for o in omitted)),
        maximum_faces=max((r['faces'] for r in rows),default=0),
        max_serialized_plane_error=max((r['serialized_plane_error'] for r in rows),default=0),
        max_source_vertex_outside=max((r['source_vertex_outside'] for r in rows),default=0))
    report=dict(schema='greyhound-bo4-model-physics-inspection-v3',summary=summary,rows=rows,omissions=omitted,
        source_data_sha256=hashlib.sha256(data_path.read_bytes()).hexdigest(),map_file=None,map_files=files,
        partition_certificates=certificates,
        geometry_policy='Certified exact-volume partition union; captured model transform applied once.',
        material_policy='Named stock tools; category differences isolated in review; no visual material fallback.',
        radiant_opened=False,compiled=False)
    (output/'model_physics_metadata.json').write_text(json.dumps(report,separators=(',',':'))+'\n')
    print(json.dumps(summary,indent=2))
    return report


if __name__ == '__main__':
    import argparse
    from pathlib import Path
    from assign_bo4_bo3_types import Types
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('capture',type=Path)
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--map-name',default='bo4_map')
    parser.add_argument('--world-capture',type=Path,help='Captured named declarations/filter table for stock tool mapping')
    args=parser.parse_args();types=filters=None
    if args.world_capture:
        probe=json.loads((args.world_capture/'world_pools_probe.json').read_text())
        reference=json.loads((TOOLS_ROOT/'black_ops_3/reference/bo3_reference.json').read_text())
        types=Types(probe,reference)
        filters=np.fromfile(args.world_capture/probe['global_filter_candidate']['file'],'<u4').reshape(-1,2)
    export(args.capture,args.output,args.map_name,types,filters)
