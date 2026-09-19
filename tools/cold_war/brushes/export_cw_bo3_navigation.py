"""Export paired CW traversal nodes through BO3's stock zombie animations.

This deliberately records the conversion choice and does not call it decoded
CW animation behavior. Negotiation volumes require a separate geometry/edge
conversion; all their source properties and restrictions remain in the report.
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
from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path
import sys

from export_cw_bo3_player_volumes import quoted
from audit_cw_bo3_brush_types import entities as parse_map


BEGIN = 'node_negotiation_begin'
END = 'node_negotiation_end'


def translate(properties, definition):
    output, omitted = {}, {}
    flags = 0
    for key, value in properties.items():
        field = definition.get(key)
        if key in ('classname', 'origin', 'angles'):
            output[key] = value
        elif key in ('animscript', 'previewanim1', 'previewmdl1'):
            omitted[key] = 'Stock zombie traversal replaces CW animation/preview dependencies'
        elif key == 'spawnflags':
            omitted[key] = 'Raw source bits are not BO3 flag values'
        elif not isinstance(field, dict):
            omitted[key] = 'Absent from the resolved BO3 class definition'
        elif field.get('noExport') in (True, 'true'):
            omitted[key] = 'BO3 editor-only property'
        elif 'spawnflag' in field:
            if field.get('type') == 'bool' and str(value).lower() in ('1', '0', 'true', 'false'):
                enabled = str(value).lower() in ('1', 'true')
                output[key] = '1' if enabled else '0'
                if enabled:
                    flags |= int(field['spawnflag'])
            else:
                omitted[key] = 'Unsupported named flag value'
        elif key in ('movementtype_ignore', 'movementtype_require'):
            allowed = {v.strip() for v in field['flags'].split(',')}
            tokens = [v.strip() for v in value.split(',') if v.strip()]
            unknown = [v for v in tokens if v not in allowed]
            # Removing a required type could admit an actor that was excluded.
            # Reject this node pair instead of silently broadening restrictions.
            if unknown:
                raise ValueError('Unmapped movement types: ' + ', '.join(unknown))
            output[key] = ','.join(tokens)
        else:
            output[key] = value
    # This export targets ordinary animation-based zombie traversal. The shipped
    # procedural branch is behavior-specific (Genesis), so do not enable it.
    flags &= ~int(definition['PROCEDURAL']['spawnflag'])
    output.update(PROCEDURAL='0', spawnflags=str(flags))
    for key in ('origin', 'angles'):
        vector = [float(v) for v in output[key].split()]
        if len(vector) != 3 or not all(math.isfinite(v) for v in vector):
            raise ValueError('Invalid node transform')
    for key, value in output.items():
        quoted(key)
        quoted(value)
    return output, omitted


def select_motion(start, end, catalogue):
    a, b = ([float(v) for v in props['origin'].split()] for props in (start, end))
    dz = b[2] - a[2]
    horizontal = math.hypot(b[0]-a[0], b[1]-a[1])
    # Similar-stock conversion policy, not a decoded CW traversal enum. The
    # level/across tolerance is reported for review; coordinates stay unchanged.
    family = 'jump_across' if abs(dz) <= 8 else 'jump_up' if dz > 0 else 'jump_down'
    distance = horizontal if family == 'jump_across' else abs(dz)
    candidates = [row for row in catalogue if row['family'] == family]
    if not candidates:
        raise ValueError('No resolved stock animation for ' + family)
    selected = min(candidates, key=lambda r: (abs(r['nominal_distance']-distance), r['nominal_distance']))
    return dict(animscript=selected['animscript'], source_displacement=[b[i]-a[i] for i in range(3)],
                horizontal_distance=horizontal, compared_distance=distance,
                stock_nominal_distance=selected['nominal_distance'], nominal_difference=selected['nominal_distance']-distance,
                across_height_tolerance=8, selection='closest_stock_nominal_distance_in_geometry_selected_family',
                animation_evidence=selected['rows'], exact_motion_equivalence=False)


def plan(document, reference):
    if document.get('schema') != 'greyhound-cw-entitylist-lossless-v1':
        raise ValueError('Use the precise saved-capture entity decoder output')
    rows = [e for e in document['entities'] if e['classname'].startswith('node_negotiation_')]
    named = defaultdict(list)
    for row in rows:
        name = row['conversion_keyvalues'].get('targetname')
        if name:
            named[name].append(row)
    definitions = reference['entity_reference']['classes']
    contract = reference.get('navigation_reference', {})
    if not contract.get('stock_traversals'):
        raise ValueError('Missing resolved stock zombie animation table evidence')
    for cls in (BEGIN, END):
        if cls not in definitions:
            raise ValueError('BO3 navigation class is missing from the reference: ' + cls)
    pairs, unresolved, consumed = [], [], set()
    for begin in (r for r in rows if r['classname'] == BEGIN):
        props = begin['conversion_keyvalues']
        ends = named.get(props.get('target'), [])
        reason = None
        if len(ends) != 1 or ends[0]['classname'] != END:
            reason = 'Begin does not target one unique negotiation end'
        elif len(named.get(props.get('targetname'), [])) > 1:
            reason = 'Ambiguous source begin targetname'
        elif ends[0]['index'] in consumed:
            reason = 'Shared end needs explicit association handling'
        else:
            end = ends[0]
            try:
                start_output, start_omitted = translate(props, definitions[BEGIN])
                end_output, end_omitted = translate(end['conversion_keyvalues'], definitions[END])
                forward_motion=select_motion(props,end['conversion_keyvalues'],contract['stock_traversals'])
                reverse_motion=select_motion(end['conversion_keyvalues'],props,contract['stock_traversals'])
                start_output['animscript']=forward_motion['animscript']
                # BO3's shipped jump_128 prefab places a reverse animscript on
                # its end node even though the class declaration omits this key.
                end_output['animscript']=reverse_motion['animscript']
            except (ValueError, KeyError) as error:
                reason = str(error)
        if reason:
            unresolved.append(dict(source_entity_index=begin['index'], reason=reason))
            continue
        consumed.update((begin['index'], end['index']))
        pairs.append(dict(begin_index=begin['index'], end_index=end['index'],
                          begin_properties=start_output, end_properties=end_output,
                          omitted_begin_properties=start_omitted, omitted_end_properties=end_omitted,
                          conversion='similar_stock_zombie_animation',
                          forward_motion=forward_motion,reverse_motion=reverse_motion,
                          reverse_source_target=end['conversion_keyvalues'].get('target'),
                          reverse_behavior_verified=False,
                          source_begin=props, source_end=end['conversion_keyvalues']))
    deferred = [dict(source_entity_index=r['index'], classname=r['classname'],
                     source_properties=r['conversion_keyvalues'],
                     reason='Requires volume/edge conversion; tool brushes alone do not encode movement restrictions'
                     if r['classname'] not in (BEGIN, END) else 'No validated unique endpoint pair')
                for r in rows if r['index'] not in consumed]
    return dict(schema='greyhound-cw-bo3-navigation-review-v1', map=document['map'],
                map_hash=document['source']['name_hash'], source_entity_count=len(rows),
                summary=dict(pairs=len(pairs), emitted_nodes=2*len(pairs), deferred_entities=len(deferred),
                             deferred_class_counts=dict(Counter(r['classname'] for r in deferred)),
                             deferred_with_movement_restrictions=sum(any(k in r['source_properties'] for k in
                                 ('movementtype_ignore', 'movementtype_require')) for r in deferred)),
                pairs=pairs, unresolved_pairs=unresolved, deferred=deferred,
                bo3_script_evidence=contract,
                compiled=False, gameplay_validated=False,
                limitations=['Stock animation selection is a geometric approximation, not the CW map-specific animation.',
                             'Uses zombie.ai_ast / zombie.ai_am traversal types; the map AI animation profile must include them.',
                             'Procedural flags are disabled: the default zombie behavior does not use the Genesis procedural branch.',
                             'The source end-to-begin target is retained in the report, but reverse behavior has not been verified.',
                             'The prefab supplies neither collision surfaces nor a compiled navigation mesh.'])


def export(document, reference, destination, stem, placement_only=False):
    report = plan(document, reference)
    if placement_only:
        for pair in report['pairs']:
            for side in ('begin', 'end'):
                pair[side + '_properties']['animscript'] = ''
            pair['conversion'] = 'placement_reference_animation_assigned_by_user'
        report['animation_setup'] = 'user_supplied; motion candidates are reference only'
        report['limitations'] = [
            'Animation fields are empty for user setup; forward/reverse motion suggestions in JSON are unassigned approximations.',
            'Precise source endpoint transforms and source properties are retained.',
            'The prefab supplies neither collision surfaces nor a compiled navigation mesh.']
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    path = destination / (stem + ('_traversal_placements.map' if placement_only else '_traversal_nodes_stock.map'))
    lines = ['iwmap 4', '"000_Global" flags active', '"000_Global/CW_Stock_Traversal" flags',
             '// entity 0', '{', '"classname" "worldspawn"', '}']
    expected = []
    for pair in report['pairs']:
        for side in ('begin', 'end'):
            props = pair[side + '_properties']
            expected.append(props)
            lines.extend([f'// entity {len(expected)}: CW source {pair[side + "_index"]}', '{',
                          'layer "000_Global/CW_Stock_Traversal"'])
            lines.extend(quoted(k) + ' ' + quoted(v) for k, v in props.items())
            lines.append('}')
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    parsed = parse_map(path)
    if len(parsed) != len(expected) + 1 or any(a['properties'] != b for a, b in zip(parsed[1:], expected)):
        raise ValueError('Serialized navigation entity properties differ')
    if any(row['brush_blocks'] for row in parsed):
        raise ValueError('Unexpected brush in point-node export')
    report['output'] = dict(file=path.name, sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                            entity_property_roundtrip_verified=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--entities', required=True, type=Path)
    parser.add_argument('--reference', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--name', required=True)
    parser.add_argument('--placement-only', action='store_true', help='Leave animation fields empty for manual setup')
    args = parser.parse_args()
    if Path(args.name).name != args.name or any(c in args.name for c in '/\\:'):
        parser.error('--name must be a filename stem')
    report = export(json.loads(args.entities.read_text()), json.loads(args.reference.read_text()), args.output, args.name, args.placement_only)
    report['sources'] = [dict(file=str(p.resolve()), sha256=hashlib.sha256(p.read_bytes()).hexdigest())
                         for p in (args.entities, args.reference)]
    (args.output / 'navigation-report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report['summary']))


if __name__ == '__main__':
    main()
