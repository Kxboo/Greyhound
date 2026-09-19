"""Build a replacement for Silver's placed model prefab with BO3 door models.

Only exact model-name/position matches are removed from the original placement
copy. Explosive entities and unrelated models are preserved as original text.
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
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import shutil


def sha(data):
    return hashlib.sha256(data).hexdigest()


def parse(text):
    rows, depth, offset = [], 0, 0
    for line in text.splitlines(keepends=True):
        stripped = line.strip()
        if stripped == '{':
            if depth == 0:
                start, props = offset, {}
            depth += 1
        elif stripped == '}':
            depth -= 1
            if depth == 0:
                rows.append(dict(start=start, end=offset + len(line), props=props))
        elif depth == 1:
            match = re.fullmatch(r'"([^"]+)"\s+"([^"]*)"', stripped)
            if match:
                props[match[1]] = match[2]
        offset += len(line)
    assert depth == 0
    return rows


def vector(props, name):
    return [float(x) for x in props.get(name, '0 0 0').split()]


def read_text(path):
    return path.read_bytes().decode('utf-8')


def point_entity(props, comment):
    return '// ' + comment + '\n{\n' + '\n'.join(f'"{k}" "{v}"' for k, v in props.items()) + '\n}\n'


def build(bo3, research, output, install=False):
    output.mkdir(parents=True, exist_ok=True)
    map_path = bo3 / 'map_source/zm/zm_silver.map'
    map_bytes = map_path.read_bytes()
    map_text = map_bytes.decode('utf-8')
    old_rel = '_prefabs/zm/black_ops_5/zm_silver/zm_silver_missing_model.map'
    new_rel = '_prefabs/codex/cw_silver_models_doors_v2.map'
    gameplay_rel = '_prefabs/codex/cw_silver_doors_zones_v2.map'
    refs = [r for r in parse(map_text) if r['props'].get('model') == old_rel]
    assert len(refs) == 1, 'Expected the current original missing-model prefab exactly once'
    assert refs[0]['props']['origin'] == '-812 57 -36'
    assert vector(refs[0]['props'], 'angles') == [0, 0, 0]

    mapping = json.loads((research / 'zone-progression-v1/zone-progression-mapping.json').read_text())
    sources = {e['index']: e['properties'] for door in mapping['doors'] for e in door['source_target_entities']
               if e['properties'].get('classname') == 'script_model'
               and e['properties'].get('script_string') == 'slide_apart'
               and 'explosive' not in e['properties'].get('model', '')}
    assert len(sources) == 14

    # Search all reachable placed prefabs, including nested ones. This prevents
    # silently adding another copy of a door already present in a nested prefab.
    visited, placed, source_hashes = set(), [], {}
    def visit(relative, ancestry=()):
        assert relative not in ancestry, 'Prefab cycle'
        if relative in visited:
            return
        visited.add(relative)
        file = bo3 / 'map_source' / relative
        data = file.read_bytes()
        source_hashes[relative] = sha(data)
        for index, row in enumerate(parse(data.decode('utf-8'))):
            p = row['props']
            if p.get('classname') == 'misc_prefab':
                visit(p['model'], (*ancestry, relative))
            elif p.get('model') in {s['model'] for s in sources.values()}:
                placed.append(dict(file=relative, index=index, props=p))
    for row in parse(map_text):
        if row['props'].get('classname') == 'misc_prefab':
            visit(row['props']['model'])

    matches = {}
    report = []
    emitted = []
    for index, source in sorted(sources.items()):
        found = [p for p in placed if p['props']['model'] == source['model'] and
                 sum((a-b)**2 for a,b in zip(vector(p['props'], 'origin'), vector(source, 'origin'))) < .01]
        assert len(found) <= 1, (index, found)
        if found:
            assert found[0]['file'] == old_rel, 'Additional prefab requires an explicit replacement'
            assert found[0]['props']['classname'] == 'misc_model'
            matches[found[0]['index']] = index
        # Keep the user's current transform/scale for the six existing models.
        transform = found[0]['props'] if found else source
        props = dict(classname='script_model', model=source['model'],
                     origin=transform['origin'], angles=transform.get('angles', '0 0 0'),
                     modelscale=transform.get('modelscale', '1'),
                     targetname='cwzv1_' + source['targetname'], script_noteworthy='model_clip',
                     script_string='slide_apart', script_vector=source['script_vector'],
                     script_transition_time='1', script_int=str(index))
        for key in ('lightingstate1', 'lightingstate2', 'lightingstate3', 'lightingstate4', 'shadow_casting'):
            if key in transform:
                props[key] = transform[key]
        emitted.append(props)
        report.append(dict(source_entity_index=index, source_properties=source, existing_matches=found,
                           bo3_properties=props, action='replace_static_instance' if found else 'add_missing_instance'))
    assert len(matches) == 6

    original = bo3 / 'map_source' / old_rel
    original_bytes = original.read_bytes()
    original_text = original_bytes.decode('utf-8')
    original_rows = parse(original_text)
    replacement = original_text
    for index, row in reversed(list(enumerate(original_rows))):
        if index in matches:
            replacement = replacement[:row['start']] + replacement[row['end']:]
    # Keep all new stock door targets together in this child prefab.
    replacement += '\n' + point_entity(dict(classname='misc_prefab', model=gameplay_rel, origin='0 0 0'),
        'CW Silver: 14 script_model doors, 25 triggers/blockers and existing zone volumes; import once')
    retained = parse(replacement)[:-1]
    expected = [original_text[r['start']:r['end']] for i,r in enumerate(original_rows) if i not in matches]
    assert [replacement[r['start']:r['end']] for r in retained] == expected

    gameplay = read_text(research / 'zone-progression-v1/cw_silver_zone_progression_v1.map')
    power_doors = []
    for row in reversed(parse(gameplay)):
        p = row['props']
        if p.get('classname') == 'trigger_use' and p.get('script_noteworthy') == 'electric_door':
            block = gameplay[row['start']:row['end']]
            block, count = re.subn(r'^"zombie_cost" "[^"]*"\r?\n', '', block, flags=re.M)
            assert count == 1
            power_doors.append(p['script_int'])
            gameplay = gameplay[:row['start']] + block + gameplay[row['end']:]
    assert len(power_doors) == 4
    for row, props in zip(report, emitted):
        gameplay += '\n' + point_entity(props, f"CW ENTITYLIST {row['source_entity_index']}; BO3 stock moving door")
    gameplay_rows = parse(gameplay)
    classes = Counter(r['props'].get('classname') for r in gameplay_rows)
    assert classes == Counter(worldspawn=1, info_volume=105, trigger_use=25, script_brushmodel=25, script_model=14)
    trigger_targets = {r['props']['target'] for r in gameplay_rows if r['props'].get('targetname') == 'zombie_door'}
    assert all(p['targetname'] in trigger_targets for p in emitted)
    assert len(trigger_targets) == 17
    assert all(any(r['props'].get('targetname') == target and r['props'].get('classname') == 'script_brushmodel'
                   for r in gameplay_rows) for target in trigger_targets)
    new_map = map_text.replace('"model" "' + old_rel + '"', '"model" "' + new_rel + '"')
    assert new_map.replace('"model" "' + new_rel + '"', '"model" "' + old_rel + '"') == map_text

    files = {new_rel: replacement.encode('utf-8'), gameplay_rel: gameplay.encode('utf-8')}
    for relative, data in files.items():
        (output / Path(relative).name).write_bytes(data)
    (output / 'zm_silver.reference-swap.map').write_bytes(new_map.encode('utf-8'))
    result = dict(schema='cw-silver-bo3-door-model-prefab-v2', prefab=new_rel, gameplay_prefab=gameplay_rel,
        source_map=str(map_path), original_map_sha256=sha(map_bytes), updated_map_sha256=sha(new_map.encode('utf-8')),
        placement_offset=refs[0]['props']['origin'], model_doors=report, removed_static_instances=matches,
        summary=dict(script_models=14, existing_models_converted=6, missing_models_added=8, door_triggers=25,
                     proxy_blocker_brushes=25, groups=17, zone_volumes=105, zone_connections=41,
                     power_doors_without_cost=len(power_doors),
                     reachable_prefabs_checked=len(visited)),
        source_prefab_hashes=source_hashes,
        limitations=['The 25 gate brushes remain labelled trigger-derived test proxies, not decoded original door hulls.',
                    'Eight node-only zones remain 128-unit reference boxes that need their extents authored.',
                    'Explosive model entities and custom bomb wiring remain unchanged; no explosion behavior is ported.',
                    'Static world collision and other prefabs are preserved; overlapping fixed clips require in-game review.',
                    'Only prefab files and one model reference in zm_silver.map are changed; map GSC is not modified.'])
    if install:
        assert map_path.read_bytes() == map_bytes, 'Current map changed during build'
        assert original.read_bytes() == original_bytes
        for relative in files:
            assert not (bo3 / 'map_source' / relative).exists(), 'Replacement already exists; inspect before overwriting'
        backup = output / ('backup-' + datetime.now().strftime('%Y%m%d-%H%M%S'))
        backup.mkdir()
        shutil.copy2(map_path, backup / 'zm_silver.map')
        shutil.copy2(original, backup / original.name)
        for relative, data in files.items():
            target = bo3 / 'map_source' / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        map_path.write_bytes(new_map.encode('utf-8'))
        result['backup_directory'] = str(backup)
        result['installed_files'] = {str(bo3 / 'map_source' / relative): sha(data) for relative,data in files.items()}
    (output / 'door-model-mapping.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result['summary']))
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('bo3', 'research', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--install', action='store_true')
    args = parser.parse_args()
    build(args.bo3, args.research, args.output, args.install)
