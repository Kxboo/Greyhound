"""Write a separate grey BO3 inspection map of captured BO4 model physics brushes.

Preserves captured model placement. Bounds disagreements go on review layers;
unidentified primitives are recorded as omissions, never replaced with boxes.
"""

# Support direct execution and the isolated packaged Python runtime.
import sys as _tool_sys
from pathlib import Path as _ToolPath
TOOLS_ROOT = next(p for p in _ToolPath(__file__).resolve().parents if (p / "tool_bootstrap.py").is_file())
_tool_sys.path.insert(0, str(TOOLS_ROOT))
import tool_bootstrap as _tool_bootstrap
_tool_bootstrap.activate(__file__)
REPO_ROOT = TOOLS_ROOT.parent
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

import numpy as np
from export_cw_full_brush_map import hull_planes
from cw_canonical_map_planes import CanonicalPlaneWriter
from build_cw_bo3_brush_prototype import read_map_planes
from bo4_prefab_layout import brush_role


def export(root, output, map_name="bo4_map", types=None, filters=None):
    data_path = root/'model_physics_data.json'
    data = json.loads(data_path.read_text())
    if data['schema'] != 'greyhound-bo4-model-physics-data-v1':
        raise ValueError('Requires standalone BO4 physics decode')
    for name, digest in data['source_sha256'].items():
        if hashlib.sha256((root/name).read_bytes()).hexdigest() != digest:
            raise ValueError(f'Source capture changed: {name}')
    if output.exists(): raise ValueError('Output must be new')
    models = {m['pointer']: m for m in data['models']}
    writer = CanonicalPlaneWriter()
    material = 't7_concrete_poured_bunker_paint_01_grey_lt'
    plane_cache, rows, omitted, body = {}, [], [], []
    layers = {'000_Global'}
    for instance in data['instances']:
        model = models[instance['model_pointer']]
        matrix = np.array(instance['matrix_world'])
        linear, translation = matrix[:3, :3], matrix[:3, 3]
        for entry in model['entries']:
            identity = dict(instance_index=instance['index'], model_pointer=model['pointer'],
                            model_hash=model['hash'], model_name=model['name'], entry_index=entry['index'])
            if entry['status'] != 'decoded_checked_hull':
                omitted.append(dict(identity, status=entry['status'], type_raw=entry.get('type_raw')))
                continue
            surface_values=[]
            if filters is not None:
                ids=[*entry['axial_materials_raw'],*[s['material_raw'] for s in entry['sides']]]
                if not ids or max(ids)>=len(filters) or int(np.bitwise_or.reduce(filters[ids,1]))!=int(entry['contents_raw'],16):
                    raise ValueError('Model-physics side filters do not reproduce source contents')
                surface_values=list(map(int,filters[ids,0]))
            decision = types.choose(int(entry['contents_raw'],16), surface_values) if types else {}
            material = decision.get('material', 't7_concrete_poured_bunker_paint_01_grey_lt')
            key = (model['pointer'], entry['index'])
            if key not in plane_cache:
                plane_cache[key] = hull_planes({'vertices': entry['points'], 'faces': entry['faces']})
            local = plane_cache[key]
            if len(local) > 64:
                omitted.append(dict(identity, status='requires_face_limit_partition', faces=len(local)))
                continue
            # n_local . inv(A)(world-t) = d_local. Normalize the transformed
            # support equation; translation and uniform scale occur once.
            normals = local[:, :3] @ np.linalg.inv(linear)
            lengths = np.linalg.norm(normals, axis=1)
            distances = local[:, 3] + normals @ translation
            equations = np.column_stack((normals/lengths[:, None], distances/lengths))
            points = np.array(entry['points']) @ linear.T + translation
            components = decision.get('collision_components') or [dict(material=material, brush_contents=decision.get('brush_contents', []))]
            if len(components) != 1:
                raise ValueError('One source brush must produce exactly one output brush')
            for component_index, component in enumerate(components):
                material = component['material']
                lines = writer.lines(equations, points.mean(0), material)
                parsed = np.asarray(read_map_planes('\n'.join(lines)))
                error = float(abs(parsed-equations).max())
                outside = float(max(0., (points @ parsed[:, :3].T - parsed[:, 3]).max()))
                if error > 1e-6 or outside > 1e-6 or not np.isfinite(parsed).all():
                    raise ValueError(f'Serialized brush drift: {identity}, {error}, {outside}')
                state = 'MODEL_PHYSICS_CONTAINED' if instance['placement_status']=='contained' else 'MODEL_PHYSICS_BOUNDS_REVIEW'
                layer = f"000_Global/{state}/contents_{int(entry['contents_raw'],16):08x}"
                layers.update((f'000_Global/{state}', layer))
                contents_line = ('contents '+' '.join(component.get('brush_contents', []))+';\n') if component.get('brush_contents') else ''
                index = len(rows)
                body.append(f'// brush {index}\n{{\nlayer "{layer}"\n'+contents_line+'\n'.join(lines)+'\n}\n')
                rows.append(dict(identity, map_brush_index=index, layer=layer,
                                 collision_component_index=component_index, collision_component=component,
                                 source_contents_raw=entry['contents_raw'], instance_flags_raw=instance['flags_raw'],
                                 placement_status=instance['placement_status'], faces=len(lines),
                                 serialized_plane_error=error, source_vertex_outside=outside, material=material,
                                 prefab_role=brush_role(decision), type_assignment=decision))
    header = 'iwmap 4\n'+''.join(f'"{layer}" flags'+(' active' if layer=='000_Global' else '')+'\n' for layer in sorted(layers))
    output.mkdir(parents=True)
    files={}
    for role in sorted({r['prefab_role'] for r in rows}):
        selected=[(r,b) for r,b in zip(rows,body) if r['prefab_role']==role]
        target=output/(map_name+'_model_physics_'+role+'.map')
        text=header+'// entity 0\n{\n"classname" "worldspawn"\n'+''.join(b for _,b in selected)+'}\n'
        target.write_bytes(text.replace('\n','\r\n').encode())
        reopened=target.read_text()
        if reopened.count('// brush ')!=len(selected) or len(read_map_planes(reopened))!=sum(r['faces'] for r,_ in selected):
            raise ValueError('Final model-physics prefab count changed')
        files[target.name]=dict(brushes=len(selected),sha256=hashlib.sha256(target.read_bytes()).hexdigest())
        for r,_ in selected:r['prefab_file']=target.name
    source_instances=len({(r['instance_index'],r['entry_index']) for r in rows})
    summary = dict(brushes=len(rows), source_brush_instances=source_instances,
                   additional_collision_components=len(rows)-source_instances,
                   placements=dict(Counter(r['placement_status'] for r in rows)),
                   omitted_instances_by_reason=dict(Counter(o['status'] for o in omitted)),
                   maximum_faces=max((r['faces'] for r in rows), default=0),
                   max_serialized_plane_error=max((r['serialized_plane_error'] for r in rows), default=0),
                   max_source_vertex_outside=max((r['source_vertex_outside'] for r in rows), default=0))
    report = dict(schema='greyhound-bo4-model-physics-inspection-v1', summary=summary, rows=rows, omissions=omitted,
                  source_data_sha256=hashlib.sha256(data_path.read_bytes()).hexdigest(),
                  map_file=None, map_files=files,
                  geometry_policy='One output brush per captured source hull; its original model transform is applied once.',
                  scope='Model physics only. No world brush, model triangle, terrain or GDT export merged.',
                  material_policy='Named BO4 side filters mapped to BO3 tools with property differences recorded.' if types else 'Grey inspection placeholder.',
                  radiant_opened=False, compiled=False)
    (output/'model_physics_metadata.json').write_text(json.dumps(report, separators=(',', ':'))+'\n')
    (output/'README.txt').write_text(
        'Standalone BO4 model physics prefab.\n'
        'Separate model_physics prefabs contain clips, brushes, non-colliding hulls or traversal by decoded use.\n'
        'BOUNDS_REVIEW layers flag brushes extending outside captured instance bounds; shapes are unchanged.\n'
        'Unidentified primitives are omitted and listed in model_physics_metadata.json.\n'
        'Grey placeholder surfaces; no custom assets/GDT, no terrain, no gameplay-equivalence claim.\n'
        'The file was serialized and read back, but has not been opened in Radiant or compiled.\n')
    print(json.dumps(summary, indent=2))
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('capture', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    export(args.capture, args.output)
