"""Export source-labelled CW player volumes as a BO3 Radiant prefab.

Reads the original TRIGGERLIST capture, verifies the requested map hash, and
keeps full source properties in JSON. Only zero-angle precompiled info_volume
records labelled player_volume are converted. This does not classify CLIP_MAP.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import struct

import numpy as np
from audit_cw_bo3_brush_types import entities
from build_cw_bo3_brush_prototype import read_map_planes
from cw_canonical_map_planes import CanonicalPlaneWriter
from exact_cw_brush_halfspaces import reconstruct_exact
from map_cw_trigger_ownership import run as ownership, read_counted


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def map_identity(capture, name, expected_hash=None):
    if not re.fullmatch(r'[a-z0-9_]+', name):
        raise ValueError('Expected a simple map name')
    asset = f'maps/{name.split("_")[0]}/{name}.d3dbsp'
    value = 0xcbf29ce484222325
    for byte in asset.encode():
        value = ((value ^ byte) * 0x100000001b3) & 0xffffffffffffffff
    value &= 0x7fffffffffffffff
    if expected_hash is not None:
        if name.startswith("cw_map_"):
            value=int(expected_hash); asset=None
        elif value!=int(expected_hash):
            raise ValueError("Resolved map name disagrees with collision capture")
    header = (capture / 'headers.bin').read_bytes()
    evidence = json.loads((capture / 'evidence.json').read_text())
    pool = evidence['pool']
    stride, capacity = pool['asset_size'], pool['capacity']
    if evidence.get('pool_index') != 0x80 or stride != 72 or not 0 < capacity <= 200000 or \
            len(header) != stride * capacity or pool['loaded'] != 1:
        raise ValueError('Expected one occupied TRIGGERLIST asset with a complete header pool')
    if not all(evidence.get(k) for k in ('descriptor_unchanged', 'headers_readback_unchanged')) or \
            not all(evidence.get('typed_candidates', {}).get(k) for k in ('complete', 'saved', 'readback_unchanged')):
        raise ValueError('Trigger capture is incomplete or changed during readback')
    # Match Greyhound's pool occupancy rule; free slots contain links, not hashes.
    base, head = int(pool['address'], 16), int(pool['free_head'], 16)
    free = set()
    while head:
        offset = head - base
        if offset < 0 or offset >= len(header) or offset % stride or offset // stride in free:
            raise ValueError('Invalid pool free list')
        free.add(offset // stride)
        head = struct.unpack_from('<Q', header, offset)[0]
    occupied = set(range(capacity)) - free
    if len(occupied) != 1:
        raise ValueError('Pool occupancy disagrees with the loaded count')
    slot = occupied.pop()
    active = header[slot * stride:(slot + 1) * stride]
    if struct.unpack_from('<Q', active)[0] != value:
        raise ValueError('TRIGGERLIST header does not match the requested map')
    candidates = json.loads((capture / evidence['typed_candidates']['file']).read_text())
    if int(candidates['source_name_hash'], 16) != value:
        raise ValueError('Typed arrays belong to a different map')
    for offset, width, filename in [(8, 8, 'trigger_models'), (24, 32, 'trigger_hulls'),
                                    (40, 20, 'trigger_slabs'), (56, 48, 'entity_records')]:
        count = struct.unpack_from('<I', active, offset)[0]
        read_counted(capture, evidence, 'typed/' + filename + '.bin', width, count)
    return dict(map=name, asset_name=asset, name_hash=f'0x{value:016x}',
                pool_capacity=capacity, occupied_slot=slot,
                header_sha256=sha(capture / 'headers.bin'))


def hull_planes(hull):
    center = np.array(hull['local_center'])
    half = np.array(hull['local_halfsize'])
    result = []
    for axis in range(3):
        n = np.eye(3)[axis]
        result.extend([[*(-n), half[axis] - center[axis]],
                       [*n, half[axis] + center[axis]]])
    for slab in hull['slabs']:
        n = np.array(slab['direction'])
        result.extend([[*n, slab['midpoint'] + slab['halfsize']],
                       [*(-n), slab['halfsize'] - slab['midpoint']]])
    return np.array(result)


def quoted(value):
    value = str(value)
    if any(c in value for c in '\r\n"\\'):
        raise ValueError('Unsupported map property escaping')
    return '"' + value + '"'


def export(capture, name, bo3, output, reference=None, expected_hash=None):
    identity = map_identity(capture, name, expected_hash)
    source = ownership(capture)
    if reference is None:
        raise ValueError('Bundled BO3 reference is required')
    volume_ref=reference['volume_reference']
    if volume_ref['entity_class']!='info_volume' or volume_ref['material']!='volume':
        raise ValueError('Invalid bundled player-volume reference')
    volume=next(r for r in reference['materials'] if r['name']=='volume')
    selected = [r for r in source['models'] if r['classname'] == 'info_volume'
                and r['properties'].get('script_noteworthy') == 'player_volume']
    selected_total=len(selected)
    selected=[r for r in selected if not any(r['angles'])]
    layers = {'000_Global', '000_Global/CW_Player_Volumes'}
    body, converted = [], []
    writer = CanonicalPlaneWriter()
    for ordinal, row in enumerate(selected, 1):
        if any(row['angles']):
            raise ValueError('Nonzero-angle volume is outside the validated transform policy')
        props = {k: v for k, v in row['properties'].items()
                 if k in ('classname', 'script_noteworthy', 'targetname', 'target')}
        label = re.sub(r'[^a-zA-Z0-9_]', '_', props.get('targetname', 'unnamed'))
        layer = '000_Global/CW_Player_Volumes/' + label
        layers.add(layer)
        body.extend([f'// entity {ordinal}: CW source {row["source_id"]}', '{',
                     'layer ' + quoted(layer)])
        body.extend(quoted(k) + ' ' + quoted(v) for k, v in props.items())
        hull_rows = []
        for brush_index, hull in enumerate(row['hulls']):
            equations = hull_planes(hull)
            mesh = reconstruct_exact(equations)
            if mesh['bad_directed_edges'] or mesh['volume'] <= 0:
                raise ValueError('Trigger hull is not a closed positive-volume intersection')
            # Remove only constraints that produce no polygon or duplicate faces.
            active = [face['side_candidates'][0] for face in mesh['faces']]
            if len(active) > 64 or max(len(f['vertices']) for f in mesh['faces']) > 64:
                raise ValueError('Volume exceeds Radiant face/winding limits')
            local = np.array(mesh['vertices'])
            world = local + row['origin']
            eq = equations[active].copy()
            eq[:, 3] += eq[:, :3] @ np.array(row['origin'])
            eq /= np.linalg.norm(eq[:, :3], axis=1)[:, None]
            lines = writer.lines(eq, world.mean(axis=0), 'volume')
            parsed = np.array(read_map_planes('\n'.join(lines)))
            drift = float(np.max(np.abs(parsed - eq)))
            outside = float(np.max(world @ parsed[:, :3].T - parsed[:, 3]))
            if drift > 1e-6 or outside > 1e-6:
                raise ValueError('Serialized planes moved the source volume')
            body.extend([f'// brush {brush_index}', '{', 'layer ' + quoted(layer),
                         *lines, '}'])
            hull_rows.append(dict(hull_index=hull['hull_index'], brush_index=brush_index,
                source_equations_local=equations.tolist(), active_source_planes=active,
                vertices_world=world.tolist(), faces=[f['vertices'] for f in mesh['faces']],
                volume=mesh['volume'], face_count=len(active),
                max_winding_points=max(len(f['vertices']) for f in mesh['faces']),
                serialized_plane_error=drift, max_vertex_outside=outside))
        body.append('}')
        converted.append(dict(source_entity_index=row['entity_index'], source_id=row['source_id'],
            map_entity_index=ordinal, layer=layer, emitted_properties=props,
            source_properties=row['properties'], source_origin=row['origin'],
            source_angles=row['angles'], contents_raw=row['contents_raw'], hulls=hull_rows))
        if ordinal % 24 == 0:
            print(f'Player volumes: {ordinal}/{len(selected)}', flush=True)
    text = '\n'.join(['iwmap 4', *['"' + l + '" flags' +
        (' active' if l == '000_Global' else '') for l in sorted(layers)],
        '// entity 0', '{', '"classname" "worldspawn"', '}', *body, ''])
    output.mkdir(parents=True, exist_ok=True)
    target = output / (name + '_player_volumes.map')
    target.write_text(text, encoding='utf-8')
    parsed_entities = entities(target)
    if len(parsed_entities) != len(selected) + 1:
        raise ValueError('Serialized entity count mismatch')
    for parsed, emitted in zip(parsed_entities[1:], converted):
        if parsed['properties'] != emitted['emitted_properties'] or \
                parsed['brush_blocks'] != len(emitted['hulls']) or \
                set(parsed['face_material_counts']) != {'volume'}:
            raise ValueError('Serialized entity ownership, material or properties changed')
    converted_ids = {r['source_entity_index'] for r in converted}
    unconverted = [dict(entity_index=r['entity_index'], classname=r['classname'],
        reason='Nonzero-angle player volume is unsupported' if r.get('properties',{}).get('script_noteworthy')=='player_volume' and any(r['angles']) else 'Not an explicitly labelled precompiled player volume')
        for r in [*source['models'], *source['entities_without_precompiled_model']]
        if r['entity_index'] not in converted_ids]
    hulls = [h for r in converted for h in r['hulls']]
    summary = dict(player_volume_entities=len(converted), hull_brushes=len(hulls),
        zone_targetnames=len({r['emitted_properties'].get('targetname') for r in converted}),
        other_source_entities_preserved=len(unconverted),
        max_faces=max((h['face_count'] for h in hulls),default=0),
        max_winding_points=max((h['max_winding_points'] for h in hulls),default=0),
        max_serialized_plane_error=max((h['serialized_plane_error'] for h in hulls),default=0),
        skipped_rotated_player_volumes=selected_total-len(selected),
        compiler_validated=False, gameplay_validated=False)
    report = dict(schema='cw_bo3_player_volumes_v1', **identity,
        source_capture=str(capture.resolve()), source_files={p.name: sha(p) for p in
        [capture/'headers.bin', capture/'evidence.json', capture/'triggers.json', capture/'small_records.bin'] if p.is_file()},
        implementation_sha256=sha(Path(__file__)),
        bo3_reference=dict(volume_reference=volume_ref, material=volume),
        units='game inches', coordinates='world; source origin baked once; no emitted origin/angles',
        geometry_policy='Local AABB intersected with abs(dot(direction, point)-midpoint)<=halfsize slabs',
        summary=summary, map_file=target.name, map_sha256=sha(target), entities=converted,
        not_converted=unconverted, raw_trigger_data=source,
        limitations=['Slab halfspace reconstruction is a candidate; serialization checks do not prove the CW point-query consumer.',
            'Zone names and geometry are preserved; CW gameplay scripts and BO3 zombie-zone setup are not ported.',
            'No CLIP_MAP brush-to-trigger join is assumed. Other trigger classes are preserved in JSON only.',
            'This map identity is verified, but trigger index association and zero-angle transforms require validation on new maps.'])
    (output/'player_volumes.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(dict(**identity, **summary), indent=2))
    return report


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('capture', type=Path)
    p.add_argument('--map', required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    reference=json.loads((Path(__file__).resolve().parent.parent/'bo3_reference.json').read_text())
    export(args.capture, args.map, None, args.output, reference=reference)
