"""Write certified BO4 collision tool hulls; original visuals use explicit-UV patches."""
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
from exact_geometry import hull_planes
from bo4_prefab_layout import brush_role
from bo4_brush_geometry import partition, serialize_piece, publish_groups


def export(root, output, map_name="bo4_map", assignments=None, visuals=None):
    meta_path, hull_path = root/'collision_data.json', root/'brush_hulls.json'
    meta, source = json.loads(meta_path.read_text()), json.loads(hull_path.read_text())
    if hashlib.sha256(meta_path.read_bytes()).hexdigest() != source['source_metadata_sha256']:
        raise ValueError('Hull ownership metadata changed')
    if output.exists(): raise ValueError('Output must be new')
    meshes = {h['brush_index']: h for h in source['hulls']}
    models = {m['index']: m for m in meta['models']}
    entities = [e for e in meta['entities'] if e['model_index'] >= 0]
    instances = [(j, None) for j in models[0]['brush_indices'] if j in meshes]
    for entity in entities:
        instances.extend((j, entity) for j in models[entity['model_index']]['brush_indices'] if j in meshes)
    choices = {r['brush_index']: r for r in assignments['rows']} if assignments else {}
    rows, bodies, omissions, cache, certificates = [], [], [], {}, {}
    for j, entity in instances:
        hull, decision = meshes[j], choices.get(j, {})
        identity = dict(source_brush_index=j, entity_index=entity['index'] if entity else None,
            model_index=entity['model_index'] if entity else 0)
        if entity and any(abs(a)%360 > 1e-5 for a in entity['angles']):
            omissions.append(dict(identity, reason='Nonzero inline angles lack a verified rotation convention', source_entity=entity))
            continue
        if not decision.get('material') or decision.get('visual_required'):
            evidence = dict(status='not_inferred',
                reason='Original visual output uses authoritative render triangles; no collision brush-face material identity is inferred')
            omissions.append(dict(identity, reason='Original visual surface is exported separately when proven; no generic brush material fallback',
                type_assignment=decision, visual_evidence=evidence))
            continue
        if j not in cache:
            cache[j], certificates[str(j)] = partition(hull['points'], hull['faces'])
        parts = cache[j]
        origin = np.asarray(entity['origin']) if entity else np.zeros(3)
        matrix = np.eye(4); matrix[:3, 3] = origin
        state = 'WORLD' if not entity else ('INLINE_AGREES' if entity['placement_crosscheck']=='agrees' else 'INLINE_AUTHORED_REVIEW')
        role = 'tool_fallback_review' if decision.get('fallback') else brush_role(decision)
        group = ('inline_models_' if entity else 'world_') + role
        components = decision['collision_components']
        for piece_index, (points, equations) in enumerate(parts):
            for component_index, component in enumerate(components):
                material = component['material']
                layer = f'000_Global/{state}/{material}/contents_{int(hull["contents_raw"],16):08x}'
                body, check = serialize_piece(points, equations, matrix, material,
                    component.get('brush_contents', []), layer, len(rows))
                bodies.append(body)
                rows.append(dict(identity, **check, map_brush_index=len(rows), partition_index=piece_index,
                    partition_count=len(parts), collision_component_index=component_index,
                    collision_component=component, origin_applied_once=origin.tolist(), placement_status=state,
                    contents_raw=hull['contents_raw'], layer=layer, material=material, prefab_group=group,
                    type_assignment=decision))
    files = publish_groups(output, map_name, '', rows, bodies, 'prefab_group')
    exported_instances = len({(r['source_brush_index'],r['entity_index']) for r in rows})
    summary = dict(brushes=len(rows), source_brush_instances=exported_instances,
        available_source_brush_instances=len(instances), omitted_source_instances=len(omissions),
        partitioned_source_hulls=sum(c['partitioned'] for c in certificates.values()),
        additional_partition_or_category_components=len(rows)-exported_instances,
        placements=dict(Counter(r['placement_status'] for r in rows)), authored_inline_entities=len(entities),
        maximum_faces=max((r['face_count'] for r in rows), default=0),
        max_serialized_plane_error=max((r['serialized_plane_error'] for r in rows), default=0),
        max_source_vertex_outside=max((r['source_vertex_outside'] for r in rows), default=0))
    report = dict(schema='greyhound-bo4-radiant-brush-inspection-v3', prefab_layout_version=3,
        summary=summary, rows=rows, map_files=files, map_file=None, omissions=omissions,
        partition_certificates=certificates, source_hulls_sha256=hashlib.sha256(hull_path.read_bytes()).hexdigest(),
        source_metadata_sha256=source['source_metadata_sha256'],
        source_model_bounds_checks=[dict(model_index=m['index'], **m['brush_bounds_check'])
            for m in models.values() if m.get('brush_bounds_check', {}).get('status') == 'contained_collision_subset'],
        unplaced_inline_model_indices=sorted(set(models)-{0}-{e['model_index'] for e in entities}),
        source_rejections=source['rejected'],
        geometry_policy='Certified convex partition union preserves the source exterior and exact volume; original transform applied once.',
        material_policy='Named stock tool categories only. Category differences are isolated in review. Original visuals use separately verified explicit-UV patches.',
        radiant_opened=False, compiled=False)
    (output/'collision_metadata.json').write_text(json.dumps(report,separators=(',',':'))+'\n')
    print(json.dumps(summary, indent=2))
    return report


if __name__ == '__main__':
    import argparse
    from pathlib import Path
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('capture',type=Path)
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--map-name',default='bo4_map')
    parser.add_argument('--assignments',type=Path,help='Source-derived stock tool assignments; no generic fallback')
    args=parser.parse_args()
    assignment_path=args.assignments or args.capture/'material_assignments.json'
    choices=json.loads(assignment_path.read_text()) if assignment_path.is_file() else None
    export(args.capture,args.output,args.map_name,choices)
