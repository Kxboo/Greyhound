"""Audit zm_silver's zero-offset authored scene placements against saved evidence.

This intentionally does not reuse the scene transform implementation. Other maps
with nonzero offsets or runtime attachment rules need a separate semantic audit.
"""

# Support direct execution and the isolated packaged Python runtime.
import sys as _tool_sys
from pathlib import Path as _ToolPath
TOOLS_ROOT = next(p for p in _ToolPath(__file__).resolve().parents if (p / "tool_bootstrap.py").is_file())
_tool_sys.path.insert(0, str(TOOLS_ROOT))
import tool_bootstrap as _tool_bootstrap
_tool_bootstrap.activate(__file__)
REPO_ROOT = TOOLS_ROOT.parent
import argparse, collections, hashlib, json, math
from pathlib import Path


def verify(root):
    root = Path(root).resolve()
    load = lambda name: json.loads((root / name).read_text())
    bundle = load('animation/scene_bundle_data.json')
    raw_bundle = load('animation/scriptbundles_decoded/bundles.json')
    assert bundle['complete'] and raw_bundle['complete']
    evidence = []
    for read in bundle['reads']:
        data = (root / bundle['EvidenceBaseDirectory'] / read['file']).read_bytes()
        assert read['unchanged'] and len(data) == read['bytes']
        assert hashlib.sha256(data).hexdigest() == read['sha256']
        evidence.append((int(read['address'], 16), data))

    fields_checked = 0
    def check_node(enriched, raw):
        nonlocal fields_checked
        assert enriched['address'] == raw['address']
        assert len(enriched['fields']) == len(raw['fields'])
        for field, source in zip(enriched['fields'], raw['fields']):
            for key in ('address', 'key_hash', 'key_canonical', 'type', 'raw_hex'):
                assert field[key] == source[key]
            address = int(field['address'], 16)
            data = bytes.fromhex(field['raw_hex'])
            hits = [b[address-a:address-a+len(data)] for a,b in evidence
                    if a <= address and address+len(data) <= a+len(b)]
            assert hits and all(b == data for b in hits)
            fields_checked += 1
        assert len(enriched['subarrays']) == len(raw['subarrays'])
        for sub, source in zip(enriched['subarrays'], raw['subarrays']):
            assert sub['raw_hex'] == source['raw_hex']
            assert len(sub['items']) == len(source['items'])
            for child, original in zip(sub['items'], source['items']):
                check_node(child, original)

    assert len(bundle['records']) == len(raw_bundle['records']) == 53
    for record, source in zip(bundle['records'], raw_bundle['records']):
        assert record['hash'] == source['hash'] and record['loaded']
        assert record['source_entities'] == source['source_entities']
        check_node(record['objects'], source['objects'])
    validation = bundle['reference_validation']
    assert validation['matched_bundles'] == 40 and validation['unmatched_bundles'] == 13
    assert validation['matched_fields'] == 9387

    entities = {e['EntityId']: e for p in (root/'entities').glob('*/*.json')
                for e in json.loads(p.read_text())}
    named = collections.defaultdict(list)
    for e in entities.values():
        for key, value in e['Properties'].items():
            if key.lower() == 'targetname': named[value].append(e)
    rows = load('animation/scene_placements.json')
    objects = load('animation/object_placements.json')
    by_name = {b['name']: b for b in bundle['records'] if 'DumpReference' in b}
    def children(node, name):
        return next((s['items'] for s in node['subarrays'] if s['key'] == name), [])
    def values(node):
        return {f['ReferenceKey']: f.get('value', f.get('value_name') or f.get('value_hash'))
                for f in node['fields']}
    counts = collections.Counter()
    markers = set()
    for row in rows:
        source = entities[row['SourceEntityId']]
        scene = by_name[row['BundleName']]
        assert any(r['entity'] == source['EntityId'] for r in scene['source_entities'])
        obj = children(scene['objects'], 'objects')[row['ObjectIndex']]
        shot = children(obj, 'shots')[row['ShotIndex']]
        for key, node in [('SceneControls', scene['objects']), ('ObjectControls', obj), ('ShotControls', shot)]:
            assert row[key] == values(node)
        controls = [row[k] for k in ('ShotControls', 'ObjectControls', 'SceneControls')]
        for node in controls:
            assert not node.get('aligntargettag') and not node.get('preserveangle')
            for key in ('hash_922b4fc5','hash_3e692842','hash_be60a82b',
                        'hash_16999a5d','hash_29563fd6','hash_eb00c330'):
                assert node.get(key, 0) == 0, 'Nonzero offset needs a different dataset audit'
        name = next((n['aligntarget'] for n in controls if n.get('aligntarget') is not None), None)
        pose = row['ResolvedAuthoredAlignment']
        if name is None:
            expected = source
            assert pose['Status'] == 'authored_scene_root'
        else:
            assert len(named[name]) == 1
            expected = named[name][0]
            assert expected['ClassName'] == 'script_struct'
            assert pose['Status'] == 'unique_authored_alignment_marker'
            markers.add(expected['EntityId'])
        assert pose['AlignmentSourceEntityId'] == expected['EntityId']
        for key, i, property_key in [('Position', 0, 'origin'), ('AnglesPitchYawRoll', 1, 'angles')]:
            vector = expected['record_vector_candidates'][i]
            assert pose[key] == vector and all(math.isfinite(v) for v in vector)
            delta = [a-b for a,b in zip(vector, expected['Properties'][property_key])]
            assert all(abs(math.remainder(d,360) if i else d) <= .501 for d in delta)
        assert pose['BO3']['origin'] == pose['Position']
        assert pose['BO3']['angles'] == pose['AnglesPitchYawRoll']
        counts[pose['Status']] += 1

    indexed = []
    for obj in objects:
        assert (root / obj['SourceBundleFile']).is_file()
        for shot in obj['Shots']:
            i = shot['SourceScenePlacementIndex']; indexed.append(i)
            row = rows[i]
            assert (root / shot['SourceScenePlacementFile']).is_file()
            assert shot['Alignment'] == row['ResolvedAuthoredAlignment']
            assert shot['AnimationReferences'] == row['AnimationEntries']
            for key in ('SourceEntityId', 'BundleName', 'ObjectIndex'): assert obj[key] == row[key]
    assert sorted(indexed) == list(range(len(rows)))
    for name in {o['BundleName'] for o in objects}:
        assert load('animation/scene_objects/'+name+'.json') == [o for o in objects if o['BundleName'] == name]
    assert len(rows) == 231 and len(objects) == 99 and len(markers) == 14
    report = {'status': 'passed', 'evidence_reads': len(evidence), 'raw_fields_checked': fields_checked,
              'reference_matched_bundles': 40, 'reference_matched_fields': 9387, 'raw_only_bundles': 13,
              'scene_objects': len(objects), 'object_shot_references': len(rows),
              'alignment_markers': len(markers), 'alignment_statuses': dict(counts),
              'scope': 'zm_silver authored alignment only; zero offsets verified; no live skeletal pose or child-scale claim'}
    (root/'metadata/scene_placement_validation.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    verify(parser.parse_args().root)
