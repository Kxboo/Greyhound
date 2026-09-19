"""Decode captured BO4 spawn properties without accessing a live process."""

# Support direct execution and the isolated packaged Python runtime.
import sys as _tool_sys
from pathlib import Path as _ToolPath
TOOLS_ROOT = next(p for p in _ToolPath(__file__).resolve().parents if (p / "tool_bootstrap.py").is_file())
_tool_sys.path.insert(0, str(TOOLS_ROOT))
import tool_bootstrap as _tool_bootstrap
_tool_bootstrap.activate(__file__)
REPO_ROOT = TOOLS_ROOT.parent
import argparse
import hashlib
import json
import struct
from collections import Counter
from pathlib import Path


def decode(root):
    root = Path(root)
    report_path = root / 'world_pools_probe.json'
    doc = json.loads(report_path.read_text())
    result = {'schema': 'greyhound-bo4-entity-properties-v1', 'pools': {},
              'source_sha256': {report_path.name: hashlib.sha256(report_path.read_bytes()).hexdigest()}}
    for pool_id in (118, 107):
        pool = next(p for p in doc['pools'] if p['pool_index'] == pool_id)
        if not pool['active_count_matches_directory'] or len(pool['assets']) != 1:
            raise ValueError(f'Ambiguous entity pool {pool_id}')
        asset = pool['assets'][0]
        props = asset['properties']
        table = next(t for t in asset['tables'] if t['stride'] == 48)
        if table['status'] != 'captured_stable' or not table['readback_unchanged']:
            raise ValueError('Unstable entity records')
        blobs = {}
        for name in (props['file'], table['file']):
            blobs[name] = (root / name).read_bytes()
            result['source_sha256'][name] = hashlib.sha256(blobs[name]).hexdigest()
        records, raw_props = blobs[table['file']], blobs[props['file']]
        texts = {int(k, 16): v for k, v in props['strings'].items()}
        rows = []
        for row in props['entities']:
            if row['status'] not in ('empty', 'captured_stable'):
                raise ValueError(f"Incomplete properties: {pool_id}/{row['entity']}")
            index = row['entity']
            record = records[index*48:(index+1)*48]
            if len(record) != 48 or struct.unpack_from('<I', record)[0] != row['count']:
                raise ValueError('Property count differs from entity record')
            values, entries = {}, []
            for j in range(row['count']):
                offset = row['offset'] + j * 32
                b = raw_props[offset:offset+32]
                if len(b) != 32:
                    raise ValueError('Truncated property')
                key_ptr = struct.unpack_from('<Q', b)[0]
                key = texts.get(key_ptr, {}).get('text')
                if not key or key in values:
                    raise ValueError('Unreadable or duplicate property key')
                kind = struct.unpack_from('<H', b, 24)[0]
                if kind == 2:
                    ptr = struct.unpack_from('<Q', b, 8)[0]
                    value = texts.get(ptr, {}).get('text')
                    if value is None:
                        raise ValueError(f'Unreadable string {key}')
                elif kind == 3:
                    value = list(struct.unpack_from('<3f', b, 8))
                elif kind == 4:
                    value = {'hash': hex(struct.unpack_from('<Q', b, 8)[0] & 0xFFFFFFFFFFFFFFF)}
                elif kind == 5:
                    value = struct.unpack_from('<f', b, 8)[0]
                elif kind == 6:
                    value = struct.unpack_from('<i', b, 8)[0]
                else:
                    value = {'unknown_type': kind, 'raw': b[8:24].hex()}
                values[key] = value
                entries.append({'key': key, 'type': kind, 'value': value, 'source_offset': offset})
            origin = list(struct.unpack_from('<3f', record, 24))
            angles = list(struct.unpack_from('<3f', record, 36))
            # BO4 retains authored properties alongside runtime record transforms.
            # Their measured differences must not be "fixed" by replacing either.
            placement_match = {key: key not in values or values[key] == expected
                               for key, expected in (('origin', origin), ('angles', angles))}
            rows.append({'index': index, 'origin': origin, 'angles': angles,
                         'model_index_raw': struct.unpack_from('<i', record, 16)[0],
                         'field_20_raw': struct.unpack_from('<I', record, 20)[0],
                         'properties': values, 'entries': entries,
                         'authored_matches_runtime': placement_match})
        if len(rows) != table['count']:
            raise ValueError('Missing entities')
        result['pools'][str(pool_id)] = {'map_hash': asset['name_hash_candidate'], 'entities': rows,
            'classes': dict(Counter(r['properties'].get('classname', '') for r in rows))}
    if result['pools']['118']['map_hash'] != result['pools']['107']['map_hash']:
        raise ValueError('Entity and trigger captures belong to different maps')
    (root/'entity_properties.json').write_text(json.dumps(result, separators=(',', ':'))+'\n')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('capture', type=Path)
    result = decode(parser.parse_args().capture)
    print(json.dumps({k: v['classes'] for k, v in result['pools'].items()}, indent=2))
