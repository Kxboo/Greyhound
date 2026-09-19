"""Build a separate Silver zone/door test prefab using BO3's stock systems."""

# Support direct execution and the isolated packaged Python runtime.
import sys as _tool_sys
from pathlib import Path as _ToolPath
TOOLS_ROOT = next(p for p in _ToolPath(__file__).resolve().parents if (p / "tool_bootstrap.py").is_file())
_tool_sys.path.insert(0, str(TOOLS_ROOT))
import tool_bootstrap as _tool_bootstrap
_tool_bootstrap.activate(__file__)
REPO_ROOT = TOOLS_ROOT.parent
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re
import sys

import numpy as np

from cw_canonical_map_planes import CanonicalPlaneWriter
from export_cw_bo3_player_volumes import quoted
from audit_cw_bo3_brush_types import entities as parse_map

STEM = 'cw_silver_zone_progression_v1'

# BO3 room volumes must activate with the accessible parent area. These are
# authoring overrides for this port, not additional Cold War quest behavior.
ROOM_ZONE_LINKS = {
    ('zone_proto_interior_lower', 'zone_wonder_weapon_room', 'open_wonder_weapon_room'): (
        'connect_start_to_proto_interior', 'connect_cave_to_proto_interior',
        'connect_interior_to_proto_upstairs_2'),
    ('zone_trans_north', 'zone_trans_north_pap_room', 'connect_zone_trans_north_pap_room_to_zone_trans_north'): (
        'connect_power_trans_north_to_trans_north_room', 'connect_trans_to_particle_accelerator'),
    ('zone_trans_south', 'zone_trans_south_pap_room', 'connect_zone_trans_south_pap_room_to_zone_trans_south'): (
        'connect_power_trans_south_to_trans_south_room', 'connect_trans_to_particle_accelerator'),
}


def activate_room_zones_with_parent(connections):
    result = []
    for row in connections:
        flags = ROOM_ZONE_LINKS.get((row['a'], row['b'], row['flag']))
        if flags is None:
            result.append(row)
        else:
            result.extend(dict(row, flag=flag, source_flag=row['flag'],
                               bo3_override='room_zone_shares_parent_door_flags') for flag in flags)
    return result


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def parse_connections(text):
    connections, aliases = [], []
    for line_number, line in enumerate(text.splitlines(), 1):
        match = re.fullmatch(r'\s*zm_zonemgr::add_adjacent_zone\(\s*"([^"]+)"\s*,\s*"([^"]+)"\s*,\s*"([^"]+)"\s*,\s*([01])\s*\);\s*', line)
        if match:
            a, b, flag, one_way = match.groups()
            connections.append(dict(a=a, b=b, flag=flag, one_way=int(one_way), source_line=line_number))
        match = re.fullmatch(r'\s*zm_zonemgr::add_zone_flags\(\s*"([^"]+)"\s*,\s*"([^"]+)"\s*\);\s*', line)
        if match:
            aliases.append(dict(wait_flag=match[1], set_flag=match[2], source_line=line_number))
    if not connections:
        raise ValueError('No literal zone connections found')
    return connections, aliases


def box_planes(center, half):
    center, half = np.array(center, dtype=float), np.array(half, dtype=float)
    if not np.all(np.isfinite(center)) or not np.all(half > 0):
        raise ValueError('Invalid reference box')
    return np.array([[*n, float(n @ center + half[axis])]
                     for axis in range(3) for n in (-np.eye(3)[axis], np.eye(3)[axis])])


class Prefab:
    def __init__(self):
        self.rows = []
        self.writer = CanonicalPlaneWriter()

    def add(self, props, layer, brushes=(), comment=''):
        self.rows.append(dict(properties=props, layer=layer, brushes=list(brushes), comment=comment))
        return len(self.rows)

    def brush(self, equations, center, material):
        return self.writer.lines(np.array(equations), np.array(center), material)

    def source_hulls(self, row, material):
        if any(row['source_angles']):
            raise ValueError('Unexpected nonzero trigger rotation')
        result = []
        for hull in row['hulls']:
            equations = np.array(hull['source_equations_local'], dtype=float)[hull['active_source_planes']]
            equations[:, 3] += equations[:, :3] @ np.array(row['source_origin'])
            vertices = np.array(hull['vertices_world'])
            if np.max(vertices @ equations[:, :3].T - equations[:, 3]) > .001:
                raise ValueError('Saved hull planes disagree with saved vertices')
            result.append(self.brush(equations, vertices.mean(axis=0), material))
        if not result:
            raise ValueError('Expected captured hull geometry')
        return result

    def save(self, path):
        layers = sorted({r['layer'] for r in self.rows})
        lines = ['iwmap 4', '"000_Global" flags active']
        lines += [quoted(layer) + ' flags' for layer in layers]
        lines += ['// entity 0', '{', '"classname" "worldspawn"', '}']
        for index, row in enumerate(self.rows, 1):
            lines += [f'// entity {index}: {row["comment"]}', '{', 'layer ' + quoted(row['layer'])]
            lines += [quoted(k) + ' ' + quoted(v) for k, v in row['properties'].items()]
            for brush_index, brush in enumerate(row['brushes']):
                lines += [f'// brush {brush_index}', '{', 'layer ' + quoted(row['layer']), *brush, '}']
            lines.append('}')
        path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
        parsed = parse_map(path)
        if len(parsed) != len(self.rows) + 1:
            raise ValueError('Prefab entity count changed')
        for actual, expected in zip(parsed[1:], self.rows):
            if actual['properties'] != expected['properties'] or actual['brush_blocks'] != len(expected['brushes']):
                raise ValueError('Prefab serialization differs')


def build(research, cw_root, bo3, output):
    output.mkdir(parents=True, exist_ok=True)
    source = cw_root / 'scripts/zm/zm_silver_zones.gsc'
    connections, aliases = parse_connections(source.read_text())
    if len(connections) != 41:
        raise ValueError('This version expects the audited 41-connection Silver source')
    source_connections = connections
    connections = activate_room_zones_with_parent(connections)
    zones = sorted({r[k] for r in connections for k in ('a', 'b')})
    document = read(research / 'entitylist/entities.decoded.json')
    trigger_document = read(research / 'review-prefabs/metadata/triggers.json')
    if int(document['source']['name_hash'], 16) != int(trigger_document['name_hash'], 16):
        raise ValueError('Source map identities differ')
    entities = document['entities']
    triggers = trigger_document['entities']
    regions = defaultdict(list)
    for entity in entities:
        p = entity['conversion_keyvalues']
        if p['classname'] == 'node_exposed' and p.get('script_noteworthy') == 'player_region' and p.get('targetname') in zones:
            regions[p['targetname']].append(entity)
    prefab = Prefab()
    zone_rows = []
    for zone in zones:
        region = regions[zone]
        targets = {e['conversion_keyvalues']['target'] for e in region if e['conversion_keyvalues'].get('target')}
        if len(targets) != 1:
            raise ValueError('Expected one evidenced spawn group for ' + zone)
        target = next(iter(targets))
        volumes = [r for r in triggers if r['source_properties'].get('targetname') == zone and r['source_properties']['classname'] == 'info_volume']
        zone_row = dict(name=zone, spawn_target=target, source_region_entity_indices=[r['index'] for r in region],
                        source_trigger_indices=[], source_trigger_ids=[], prefab_entities=[], geometry_status='captured_hulls')
        props = dict(classname='info_volume', targetname=zone, target=target, script_noteworthy='player_volume')
        for row in volumes:
            idx = row['source_entity_index']
            props_with_id = dict(props, script_int=str(idx))
            number = prefab.add(props_with_id, f'000_Global/Zones_Captured/{zone}', prefab.source_hulls(row, 'volume'),
                                f'TRIGGER index {idx}, source ID {row["source_id"]}')
            zone_row['source_trigger_indices'].append(idx)
            zone_row['source_trigger_ids'].append(row['source_id'])
            zone_row['prefab_entities'].append(number)
        if not volumes:
            # CW allows node regions; BO3 asserts unless an info_volume exists.
            # This explicit editing placeholder does not claim decoded region extents.
            entity = region[0]
            center = entity['origin']
            half = [64., 64., 64.]
            number = prefab.add(dict(props, script_int=str(entity['index'])),
                f'000_Global/REVIEW_Zone_Extents/{zone}',
                [prefab.brush(box_planes(center, half), center, 'volume')],
                f'EDIT EXTENTS: 128-unit reference box at ENTITYLIST {entity["index"]}; not decoded CW bounds')
            zone_row.update(geometry_status='reference_box_at_captured_region_node_resize_required',
                placeholder_center=center, placeholder_half_dimensions=half, prefab_entities=[number])
        zone_rows.append(zone_row)

    door_rows = []
    doors = [r for r in triggers if r['source_properties'].get('targetname') == 'zombie_door']
    for row in doors:
        p = row['source_properties']
        idx = row['source_entity_index']
        target = 'cwzv1_' + p['target']
        # The Giant uses trigger_use + script_flag + zombie_cost + target.
        props = dict(classname='trigger_use', targetname='zombie_door', target=target,
            script_flag=p['script_flag'], zombie_cost=p['zombie_cost'], cursorhint='HINT_ACTIVATE', script_int=str(idx))
        if p.get('script_noteworthy'):
            props['script_noteworthy'] = p['script_noteworthy']
        num = prefab.add(props, f'000_Global/Doors_Captured/{p["script_flag"]}', prefab.source_hulls(row, 'trigger'),
                         f'TRIGGER {idx}, source ID {row["source_id"]}; source class {p["classname"]}')
        # A clearly labelled physical test gate, intentionally independent of
        # unported CW models and dynamite animations. Original geometry not known.
        vertices = np.array([v for h in row['hulls'] for v in h['vertices_world']])
        lo, hi = vertices.min(axis=0), vertices.max(axis=0)
        center, half = (lo + hi) / 2, (hi - lo) / 2
        thin = int(np.argmin(half[:2]))
        half[thin] = min(4., half[thin] / 2)
        half[1 - thin] *= .85
        half[2] *= .9
        gate_props = dict(classname='script_brushmodel', targetname=target, script_noteworthy='clip',
            script_string='clip', DYNAMICPATH='1', spawnflags='1', script_int=str(idx))
        gate = prefab.add(gate_props, f'000_Global/REVIEW_Door_Geometry/{p["script_flag"]}',
            [prefab.brush(box_planes(center, half), center, 'clip')],
            f'TEST GATE derived from trigger {idx}; replace with desired door brush/model')
        source_targets = [dict(index=e['index'], properties=e['conversion_keyvalues']) for e in entities
                          if e['conversion_keyvalues'].get('targetname') == p['target']]
        door_rows.append(dict(source_trigger_index=idx, source_trigger_id=row['source_id'], source_properties=p,
            prefab_trigger_entity=num, prefab_gate_entity=gate, bo3_properties=props, source_target_entities=source_targets,
            gate_geometry='test_proxy_derived_from_interaction_hull_not_original_door',
            gate_center=center.tolist(), gate_half_dimensions=half.tolist()))

    # Spawn locations are supplied as a separate optional prefab. Custom scene,
    # dog, special-enemy, and animated entry behavior is kept only in the JSON.
    spawns = Prefab()
    spawn_rows = []
    all_targets = {r['spawn_target'] for r in zone_rows}
    for entity in entities:
        p = entity['conversion_keyvalues']
        if p.get('targetname') not in all_targets:
            continue
        row = dict(source_entity_index=entity['index'], source_properties=p, emitted=False)
        if p['classname'] == 'script_struct' and p.get('script_noteworthy') in ('spawn_location', 'riser_location'):
            props = {k: p[k] for k in ('classname', 'origin', 'angles', 'targetname', 'script_noteworthy')}
            props['script_int'] = str(entity['index'])
            row.update(emitted=True, prefab_entity=spawns.add(props, '000_Global/Spawn_Locations/' + p['targetname'],
                       comment=f'ENTITYLIST {entity["index"]}; CW custom script_string/targets retained in JSON only'))
        spawn_rows.append(row)

    flags = sorted({r['flag'] for r in connections} | {r[k] for r in aliases for k in ('wait_flag', 'set_flag')})
    door_flags = {r['bo3_properties']['script_flag'] for r in door_rows}
    derived_flags = {r['set_flag'] for r in aliases}
    external_flags = sorted(set(flags) - door_flags - derived_flags - {'always_on'})
    template = (Path(__file__).parent / 'templates/cw_silver_zone_progression.gsc.in').read_text()
    init = []
    for flag in flags:
        init.append(f'    ensure_flag( "{flag}" );')
    init += ['    level flag::set( "always_on" );', '    zm_zonemgr::zone_init( "zone_proto_start" );']
    # Keep the literal source order (including its duplicate flag alias call).
    statements = [(r['source_line'], f'    zm_zonemgr::add_adjacent_zone( "{r["a"]}", "{r["b"]}", "{r["flag"]}", {r["one_way"]} );') for r in connections]
    statements += [(r['source_line'], f'    zm_zonemgr::add_zone_flags( "{r["wait_flag"]}", "{r["set_flag"]}" );') for r in aliases]
    init += [f'    // Based on CW zm_silver_zones.gsc:{line}; BO3 room links share parent door flags.\n{call}' for line, call in sorted(statements)]
    gsc = template.replace('@ZONE_INIT@', '\n'.join(init)).replace('@FLAGS@', '\n'.join(f'    level.cwzv1_flags["{f}"] = true;' for f in flags))
    prefab_path = output / (STEM + '.map')
    prefab.save(prefab_path)
    spawns.save(output / (STEM + '_spawn_locations.map'))
    (output / (STEM + '.gsc')).write_text(gsc, encoding='utf-8')
    report = dict(schema='cw-bo3-zone-progression-v1', map=document['map'],
        connections=connections, source_connections=source_connections, flag_aliases=aliases, zones=zone_rows, doors=door_rows, spawn_locations=spawn_rows,
        external_quest_flags=external_flags,
        summary=dict(connections=len(connections), zones=len(zones), flag_alias_calls=len(aliases),
            captured_zone_volumes=sum(len(z['source_trigger_indices']) for z in zone_rows),
            reference_zone_boxes=sum(not z['source_trigger_indices'] for z in zone_rows),
            door_triggers=len(doors), blocker_groups=len({r['bo3_properties']['target'] for r in door_rows}),
            proxy_gate_brushes=len(door_rows), optional_basic_spawn_locations=len(spawns.rows),
            main_prefab_entities=len(prefab.rows), initial_zones=['zone_proto_start']),
        bo3_authoring_sources=['map_source/zm/zm_giant.map', 'map_source/_prefabs/zm/zm_giant/geo/factory_doors.map',
            'share/raw/scripts/zm/zm_giant.gsc', 'share/raw/scripts/zm/_zm_zonemgr.gsc', 'share/raw/scripts/zm/_zm_blockers.gsc'],
        limitations=['Eight node-only CW zone extents are editing placeholders, not decoded volumes.',
            'Door trigger hulls, costs and flags are captured; gate brush geometry is a test proxy, not original CW door geometry.',
            'Stock BO3 electric_door behavior retained. Power and quest systems are supplied by the host map or optional debug commands.',
            'Custom spawn scenes, assets, AI actor spawners and animations are not ported by this prefab.',
            'Import once at identity transform and stamp prefab to prevent automatic name prefixes.'],
        sources=[])
    paths = [source, research / 'entitylist/entities.decoded.json', research / 'review-prefabs/metadata/triggers.json']
    paths += [bo3 / p for p in report['bo3_authoring_sources']]
    for p in paths:
        report['sources'].append(dict(file=str(p), sha256=hashlib.sha256(p.read_bytes()).hexdigest()))
    (output / 'zone-progression-mapping.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report['summary']))
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('research', 'cw-root', 'bo3', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    build(args.research, args.cw_root, args.bo3, args.output)
