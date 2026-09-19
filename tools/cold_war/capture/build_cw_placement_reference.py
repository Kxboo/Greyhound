"""Package saved CW placements and evidence for manual BO3 authoring."""

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
import shutil
import sys

from export_cw_bo3_navigation import export as export_nodes
from export_cw_volume_connections import export as export_connections


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def write(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')


def build(root, reference, output):
    root, output = Path(root).resolve(), Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    document = read(root / 'entitylist/entities.decoded.json')
    graph = read(root / 'game-map-current/navigation-graph.json')
    catalogue = read(reference)
    if document['source']['name_hash'] != graph['map_hash']:
        raise ValueError('Entity and navigation map identities differ')
    name = graph['map']
    prefabs = output / 'prefabs'
    data = output / 'data'
    prefabs.mkdir(exist_ok=True)
    data.mkdir(exist_ok=True)
    explicit = export_nodes(document, catalogue, prefabs, name, placement_only=True)
    connections = export_connections(graph, catalogue, prefabs, name, placement_only=True)
    write(data / 'explicit-node-mapping.json', explicit)
    write(data / 'volume-connection-mapping.json', connections)
    sources = []

    def copy(relative, destination):
        source = root / relative
        shutil.copy2(source, destination)
        sources.append(dict(source=str(source), file=destination.relative_to(output).as_posix(),
                            sha256=hashlib.sha256(source.read_bytes()).hexdigest()))

    for filename in ('zm_silver_brush_collision.map', 'zm_silver_other_brushes.map',
                     'zm_silver_volumes.map', 'zm_silver_triggers.map'):
        copy('review-prefabs/' + filename, prefabs / filename)
    copy('navigation-stock/zm_silver_navigation_tools.map', prefabs / 'zm_silver_navigation_tools.map')
    for source, dest in (
        ('entitylist/entities.decoded.json', 'entities.decoded.json'),
        ('entitylist/entities.json', 'entities.json'),
        ('entitylist/unresolved-assets.json', 'unresolved-assets.json'),
        ('game-map-current/navigation-graph.json', 'navigation-graph.json'),
        ('navigation-stock/navigation-tools-report.json', 'navigation-tools-report.json'),
        ('review-prefabs/metadata/material_assignments.json', 'material_assignments.json'),
        ('review-prefabs/metadata/collision_metadata.json', 'collision_metadata.json'),
        ('review-prefabs/metadata/triggers.json', 'triggers.json'),
        ('review-prefabs/metadata/export_report.json', 'export_report.json'),
        ('silver-stock-first-audit.json', 'stock-first-audit.json')):
        copy(source, data / dest)
    shutil.copy2(reference, data / 'bo3_reference.json')
    tools = read(data / 'navigation-tools-report.json')
    by_entity = defaultdict(list)
    for i, row in enumerate(tools['records']):
        by_entity[row['source_entity_index']].append(dict(file='data/navigation-tools-report.json',
            pointer=f'/records/{i}', prefab='prefabs/zm_silver_navigation_tools.map', material=row['material']))
    for i, pair in enumerate(explicit['pairs']):
        for side in ('begin', 'end'):
            by_entity[pair[side + '_index']].append(dict(file='data/explicit-node-mapping.json',
                pointer=f'/pairs/{i}', prefab='prefabs/' + explicit['output']['file'], side=side))
    for i, row in enumerate(connections['emitted']):
        for side in ('start', 'end'):
            by_entity[row['source_' + side + '_entity']].append(dict(file='data/volume-connection-mapping.json',
                pointer=f'/emitted/{i}', prefab='prefabs/' + connections['file'], side=side))
    nodes = {n['source_entity_index']: n for n in graph['nodes']}
    entities = []
    for e in document['entities']:
        node = nodes.get(e['index'])
        entities.append(dict(source_entity_index=e['index'], source_record_id=e['record']['raw_id_u32'],
            classname=e['classname'], source_properties=e['conversion_keyvalues'],
            transform=e['transform'], bo3_class_check=e['bo3'], outputs=by_entity[e['index']],
            compiled_navigation_node=None if node is None else node['index'],
            compiled_navigation_position=None if node is None else node['position'],
            full_source_pointer=f"data/entities.decoded.json#/entities/{e['index']}",
            mapping_status='exported_reference' if by_entity[e['index']] else
                'same_name_class_exists_properties_require_review' if e['bo3']['classname_status']=='present_in_installed_definitions' else
                'source_preserved_no_automatic_mapping'))
    materials = read(data / 'material_assignments.json')
    collision = read(data / 'collision_metadata.json')
    # Assignment IDs are collision-asset:brush IDs, not ENTITYLIST indices.
    for row in collision['rows']:
        if row['material_assignment_key'] not in materials['brushes']:
            raise ValueError('Placed brush has no material mapping')
    index = dict(schema='cw-bo3-placement-reference-v1', map=name, map_hash=graph['map_hash'],
        scope='Every captured ENTITYLIST row and supported exported collision brush; not a claim that every CW pool or field is decoded.',
        animation_setup='User supplied. All traversal placement prefab animation fields are empty.',
        summary=dict(entities=len(entities), navigation_nodes=len(nodes), navigation_tool_brushes=len(tools['records']),
            explicit_endpoint_pairs=len(explicit['pairs']), volume_pairs=len(connections['pairs']),
            directional_connections=len(connections['emitted']), unique_collision_brushes=len(materials['brushes']),
            placed_collision_pieces=len(collision['rows']), entity_mapping_statuses=dict(Counter(e['mapping_status'] for e in entities))),
        entities=entities,
        lookup=dict(brush_materials='data/material_assignments.json#/brushes/<asset_index>:<brush_index>',
            brush_placements='data/collision_metadata.json#/rows (prefab_file and prefab_brush_index locate each output piece)',
            triggers='data/triggers.json#/entities (TRIGGER pool indices, a separate namespace from ENTITYLIST)',
            navigation='data/navigation-graph.json#/nodes', volume_pairs='data/volume-connection-mapping.json#/pairs'),
        limitations=['Class-name presence is not proof of property or behavior equivalence.',
            'Derived volume connection centers use sampled edge midpoints plus a documented 16-unit BO3 authoring lift; raw coordinates remain in JSON.',
            'Unresolved material flags, asset hashes and unsupported collision layouts are retained in the supporting reports.',
            'The geometry compiler check reported a leak and node projection failures; these are authoring references, not game-ready output.'])
    write(output / 'reference-index.json', index)
    write(output / 'source-manifest.json', sources)
    shutil.copy2(REPO_ROOT / 'docs/cw-effects-entities.md', output / 'README.md')
    manifest = {p.relative_to(output).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in output.rglob('*') if p.is_file() and p.name != 'manifest.json'}
    write(output / 'manifest.json', dict(schema='cw-reference-file-integrity-v1', files=manifest))
    return index['summary']


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--research', type=Path, required=True)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.research, args.reference, args.output)))
