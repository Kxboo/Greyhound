"""Serialize validated BO4 brush hulls with Greyhound's existing BO3 writer.

Grey inspection surfaces only. Raw BO4 contents are retained per brush, not
mapped to Cold War flags or assumed BO3 gameplay behavior. Does not export terrain.
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


def export(root, output, map_name="bo4_map", assignments=None):
    meta_path, hull_path = root/'collision_data.json', root/'brush_hulls.json'
    meta, source = json.loads(meta_path.read_text()), json.loads(hull_path.read_text())
    if hashlib.sha256(meta_path.read_bytes()).hexdigest() != source['source_metadata_sha256']:
        raise ValueError('Hull ownership metadata changed')
    if output.exists(): raise ValueError('Output must be new')
    meshes = {h['brush_index']: h for h in source['hulls']}
    models = {m['index']: m for m in meta['models']}
    instances = [(j, None) for j in models[0]['brush_indices'] if j in meshes]
    entities = [e for e in meta['entities'] if e['model_index'] >= 0]
    for entity in entities:
        if any(entity['angles']):
            raise ValueError('Nonzero BO4 entity angles require a validated rotation convention')
        instances.extend((j, entity) for j in models[entity['model_index']]['brush_indices'] if j in meshes)
    material = 't7_concrete_poured_bunker_paint_01_grey_lt'
    choices = {r['brush_index']: r for r in assignments['rows']} if assignments else {}
    writer, cache, rows, body, layers = CanonicalPlaneWriter(), {}, [], [], {'000_Global'}
    for j, entity in instances:
        hull = meshes[j]
        decision = choices.get(j, {})
        material = decision.get("material", "t7_concrete_poured_bunker_paint_01_grey_lt")
        points = np.array(hull['points'])
        if j not in cache:
            cache[j] = hull_planes({'vertices': hull['points'], 'faces': hull['faces']})
        equations = cache[j].copy()
        if len(equations) > 64:
            raise ValueError(f'Brush {j} requires face-limit partitioning')
        origin = np.array(entity['origin']) if entity else np.zeros(3)
        points = points + origin
        equations[:, 3] += equations[:, :3] @ origin
        state = 'WORLD' if entity is None else ('INLINE_AGREES' if entity['placement_crosscheck'] == 'agrees' else 'INLINE_AUTHORED_REVIEW')
        type_layer=f'000_Global/{state}/{material}'
        layer = f"{type_layer}/contents_{int(hull['contents_raw'],16):08x}"
        layers.update((f'000_Global/{state}',type_layer,layer))
        components = decision.get('collision_components') or [dict(material=material, brush_contents=decision.get('brush_contents', []))]
        if len(components) != 1:
            raise ValueError('One source brush must produce exactly one output brush')
        for component_index, component in enumerate(components):
            material = component['material']
            group = ('inline_models_' if entity else 'world_') + brush_role(decision)
            lines = writer.lines(equations, points.mean(0), material)
            parsed = np.asarray(read_map_planes('\n'.join(lines)))
            error = float(abs(parsed-equations).max())
            outside = float(max(0., (points@parsed[:, :3].T-parsed[:, 3]).max()))
            if error > 1e-6 or outside > 1e-6 or not np.isfinite(parsed).all():
                raise ValueError(f'Serialized hull drift: {j}, {error}, {outside}')
            contents_line = ('contents '+' '.join(component.get('brush_contents', []))+';\n') if component.get('brush_contents') else ''
            ordinal = len(rows)
            body.append(f'// brush {ordinal}\n{{\nlayer "{layer}"\n'+contents_line+'\n'.join(lines)+'\n}\n')
            rows.append({'map_brush_index': ordinal, 'source_brush_index': j,
                'collision_component_index': component_index, 'collision_component': component,
                'entity_index': entity['index'] if entity else None,
                'model_index': entity['model_index'] if entity else 0,
                'origin_applied_once': origin.tolist(), 'placement_status': state,
                'contents_raw': hull['contents_raw'], 'face_count': len(lines),
                'serialized_plane_error': error, 'source_vertex_outside': outside,
                'layer': layer, 'material': material, 'prefab_group': group, 'type_assignment': decision})
    output.mkdir(parents=True)
    target = output/(map_name+'_brush_inspection.map')
    header = 'iwmap 4\n'+''.join(f'"{layer}" flags'+(' active' if layer=='000_Global' else '')+'\n' for layer in sorted(layers))
    text = header+'// entity 0\n{\n"classname" "worldspawn"\n'+''.join(body)+'}\n'
    files = {}
    if assignments:
        for group in sorted({r['prefab_group'] for r in rows}):
            selected = [(r,b) for r,b in zip(rows,body) if r['prefab_group']==group]
            path = output/(map_name+'_'+group+'.map')
            content = header+'// entity 0\n{\n"classname" "worldspawn"\n'+''.join(b for _,b in selected)+'}\n'
            path.write_bytes(content.replace('\n','\r\n').encode())
            check = path.read_text()
            if check.count('// brush ') != len(selected) or len(read_map_planes(check)) != sum(r['face_count'] for r,_ in selected):
                raise ValueError('Split prefab coverage differs')
            files[path.name] = {'brushes':len(selected),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
            for r,_ in selected: r['prefab_file']=path.name
    else:
        target.write_bytes(text.replace('\n','\r\n').encode())
    # Reopen the final file, independently of the per-brush writer buffers.
    reopened = "\n".join((output/f).read_text() for f in files) if assignments else target.read_text()
    if reopened.count('// brush ') != len(rows) or len(read_map_planes(reopened)) != sum(r['face_count'] for r in rows):
        raise ValueError('Final file brush/plane count differs')
    summary = {'brushes': len(rows), 'source_brush_instances': len(instances),
        'additional_collision_components': len(rows)-len(instances),
        'placements': dict(Counter(r['placement_status'] for r in rows)),
        'authored_inline_entities': len(entities), 'maximum_faces': max(r['face_count'] for r in rows),
        'max_serialized_plane_error': max(r['serialized_plane_error'] for r in rows),
        'max_source_vertex_outside': max(r['source_vertex_outside'] for r in rows)}
    report = {'schema': 'greyhound-bo4-radiant-brush-inspection-v1', 'summary': summary,
        'prefab_layout_version': 2,
        'map_files': files, 'map_file': None if assignments else target.name,
        'source_hulls_sha256': hashlib.sha256(hull_path.read_bytes()).hexdigest(),
        'source_metadata_sha256': source['source_metadata_sha256'],
        'unplaced_inline_model_indices': sorted(set(models)-{0}-{e['model_index'] for e in entities}),
        'source_rejections': source['rejected'], 'rows': rows,
        'geometry_policy': 'Source vertex hulls, support-plane merging only, translation applied once; no terrain or triangle collision',
        'material_policy': 'Named BO4 properties matched to shipped BO3 tools; differences in type_assignment. No GDT. Gameplay equivalence not asserted.' if assignments else 'Grey inspection placeholder',
        'placement_policy': 'Authored entity origins. Mismatched or missing runtime bounds are on REVIEW layers; unplaced models remain in source hulls.',
        'radiant_opened': False, 'compiled': False}
    (output/'collision_metadata.json').write_text(json.dumps(report, separators=(',', ':'))+'\n')
    print(json.dumps(summary, indent=2))
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('capture', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    export(args.capture, args.output)
