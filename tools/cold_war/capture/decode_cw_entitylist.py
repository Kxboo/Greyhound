"""Decode saved CW ENTITYLIST bytes without dropping properties or float32 precision.

This is a saved-capture decoder, not a BO3 entity/script converter. Ordered property
records are authoritative; dictionaries are conveniences and omit duplicate keys.
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
import struct


def require(condition, message):
    if not condition:
        raise ValueError(message)


def hx(value):
    return f"0x{value:016X}"


class Capture:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.cache = {}
        self.logical_files = {}
        self.evidence = self.json('evidence.json')

    def physical(self, name):
        path = (self.root / name).resolve()
        require(path.is_relative_to(self.root), f'Path outside capture: {name}')
        if name not in self.cache:
            self.cache[name] = path.read_bytes()
        return self.cache[name]

    def json(self, name):
        return json.loads(self.physical(name).decode('utf-8-sig'))

    def read(self, name, size=None):
        entry = self.evidence.get('storage', {}).get(name)
        if entry is None:
            data = self.physical(name)
        else:
            backing = self.physical(entry['file'])
            start, length = entry['offset'], entry['bytes']
            require(start >= 0 and length >= 0 and start + length <= len(backing),
                    f'Truncated packed span: {name}')
            data = backing[start:start + length]
        require(size is None or len(data) == size, f'Wrong byte count: {name}')
        self.logical_files[name] = {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
        return data

    def string(self, address, candidate):
        require(int(candidate['address'], 16) == address, 'String pointer disagrees with candidate')
        data = self.read(f'typed/strings/0x{address:X}.bin')
        end = data.find(b'\0')
        require((end >= 0) == candidate['terminated'], 'String termination disagrees')
        payload = data[:end] if end >= 0 else data
        try:
            value = payload.decode('utf-8', errors='strict')
        except UnicodeDecodeError:
            value = None
        if 'text' in candidate:
            require(value == candidate['text'], 'String text disagrees with captured bytes')
        return dict(value=value, terminated=end >= 0, raw_hex=payload.hex(), address=hx(address))


def floats(raw):
    values = struct.unpack('<' + 'f' * (len(raw) // 4), raw)
    # Strict JSON has no NaN/Infinity. Raw bytes always retain their exact payload.
    return [v if math.isfinite(v) else None for v in values]


def number_text(value):
    return None if value is None else format(value, '.9g')


def decode_property(capture, raw, candidate, legacy_value=None):
    key = capture.string(struct.unpack_from('<Q', raw)[0], candidate['key'])
    tag, = struct.unpack_from('<H', raw, 24)
    full_tag, = struct.unpack_from('<I', raw, 24)
    require(tag == candidate['type_tag'] and full_tag == candidate['raw_tag_u32'], 'Property tag differs')
    require(raw[8:24].hex() == candidate['raw_value_hex'].lower(), 'Property value bytes differ')
    row = dict(key=key['value'], key_string=key, type_tag=tag, raw_tag_u32=full_tag,
               raw_record_hex=raw.hex(), raw_value_hex=raw[8:24].hex(),
               unknown_tail_hex=raw[28:32].hex(), status='decoded_storage_type')
    text_value = None
    if tag == 2:
        row['type'] = 'string'
        row['string'] = capture.string(struct.unpack_from('<Q', raw, 8)[0], candidate['string_candidate'])
        row['value'] = row['string']['value']
        if row['string']['terminated']:
            text_value = row['value']
    elif tag in (3, 5):
        values = floats(raw[8:20] if tag == 3 else raw[8:12])
        native = candidate['vector_candidate'] if tag == 3 else [candidate['float_candidate']]
        require(len(native) == len(values), 'Float component counts differ')
        for offset, (value, other) in enumerate(zip(values, native)):
            if value is not None:
                require(struct.pack('<f', other) == raw[8 + offset * 4:12 + offset * 4], 'Float bytes differ')
        row.update(type='vector3_float32' if tag == 3 else 'float32',
                   value=values if tag == 3 else values[0])
        if all(v is not None for v in values):
            text_value = ' '.join(number_text(v) for v in values)
        else:
            row['status'] = 'nonfinite_float_raw_bits_preserved'
    elif tag == 4:
        value, = struct.unpack_from('<Q', raw, 8)
        require(value == int(candidate['asset_hash_candidate'], 16), 'Hash differs')
        row.update(type='asset_hash64', value=hx(value), raw_hash=hx(value))
        # Legacy resolution came from Greyhound name caches; do not assert that
        # a cache result is verified against this hash or that BO3 has the asset.
        unresolved = legacy_value in (None, f'{value:X}', hx(value))
        row['name_status'] = 'unresolved' if unresolved else 'native_name_cache_candidate'
        if not unresolved:
            row['name_candidate'] = legacy_value
        text_value = legacy_value if legacy_value is not None else f'{value:X}'
    elif tag == 6:
        unsigned, = struct.unpack_from('<I', raw, 8)
        signed, = struct.unpack_from('<i', raw, 8)
        require(unsigned == candidate['uint32_candidate'] and signed == candidate['int32_candidate'], 'Integer differs')
        row.update(type='integer32', value=unsigned, unsigned_value=unsigned, signed_value=signed,
                   interpretation='signedness is property-dependent; value preserves legacy unsigned interpretation')
        text_value = str(unsigned)
    else:
        row.update(type='unknown', value=None, status='unknown_type_raw_bytes_preserved')
    row['keyvalue'] = text_value
    return row


def decode(root, bo3_def=None, map_name=None):
    capture = Capture(root)
    native = capture.json('decoded_candidates.json')
    legacy = capture.json('entities.json')['Entities']
    require(native['source_pool'] == 0x8E, 'Expected ENTITYLIST pool 0x8E')
    require(native['capture_reads_complete'] and native['readback_unchanged'], 'Capture is incomplete or changed during readback')
    arrays = {a['file']: a for a in native['arrays']}
    descriptor = arrays['typed/entity_records.bin']
    count = descriptor['count']
    require(descriptor['candidate_stride'] == 48, 'Unexpected entity stride')
    require(count == len(native['entities']) == len(legacy), 'Entity counts disagree')
    records = capture.read('typed/entity_records.bin', count * 48)
    headers = capture.read('headers.bin')
    matching = [i for i in range(0, len(headers) - 23, 24)
                if struct.unpack_from('<Q', headers, i)[0] == int(native['source_name_hash'], 16)
                and struct.unpack_from('<I', headers, i + 8)[0] == count
                and struct.unpack_from('<Q', headers, i + 16)[0] == int(descriptor['address'], 16)]
    require(len(matching) == 1, 'No unique header matches the entity array')
    classes, class_source = set(), None
    if bo3_def:
        path = Path(bo3_def).resolve()
        data = path.read_bytes()
        classes = {v['classname'] for v in json.loads(data) if 'classname' in v}
        class_source = dict(file=str(path), sha256=hashlib.sha256(data).hexdigest())
    entities, precision_changes = [], []
    types, class_counts = Counter(), Counter()
    for i, candidate in enumerate(native['entities']):
        raw = records[i * 48:(i + 1) * 48]
        nprops, = struct.unpack_from('<I', raw)
        require(candidate['index'] == i and nprops == candidate['property_count'] == len(candidate['properties']), 'Property counts disagree')
        require(int(candidate['record_address'], 16) == int(descriptor['address'], 16) + i * 48, 'Record address differs')
        name = f'typed/properties_{i}.bin'
        if nprops:
            desc = arrays[name]
            require(desc['count'] == nprops and desc['candidate_stride'] == 32, 'Property descriptor differs')
            require(int(desc['address'], 16) == struct.unpack_from('<Q', raw, 8)[0], 'Property pointer differs')
            props = capture.read(name, nprops * 32)
        else:
            props = b''
        reference, identity = struct.unpack_from('<II', raw, 16)
        require(reference == candidate['raw_reference_u32'] and identity == candidate['raw_id_u32'], 'Raw record IDs differ')
        vectors = [floats(raw[24:36]), floats(raw[36:48])]
        for offset, vector in enumerate(candidate['record_vector_candidates']):
            for axis, value in enumerate(vector):
                if vectors[offset][axis] is not None:
                    require(struct.pack('<f', value) == raw[24 + offset * 12 + axis * 4:28 + offset * 12 + axis * 4], 'Record vector differs')
        ordered = []
        for j, prop in enumerate(candidate['properties']):
            key = prop['key'].get('text')
            row = decode_property(capture, props[j * 32:(j + 1) * 32], prop, legacy[i].get(key))
            row['index'] = j
            ordered.append(row)
            types[str(row['type_tag'])] += 1
        key_counts = Counter(p['key'] for p in ordered)
        duplicates = [k for k, n in key_counts.items() if n > 1]
        unique = [p for p in ordered if p['key'] is not None and key_counts[p['key']] == 1]
        values = {p['key']: p['value'] for p in unique}
        keyvalues = {p['key']: p['keyvalue'] for p in unique if p['keyvalue'] is not None}
        require(set(legacy[i]) <= set(key_counts), 'Legacy export contains an unexplained key')
        for p in unique:
            old = legacy[i].get(p['key'])
            if old is not None and p['type_tag'] not in (3, 5):
                require(old == p['keyvalue'], f'Legacy non-float value differs at entity {i}: {p["key"]}')
            if old is not None and p['type_tag'] in (3, 5) and old != p['keyvalue']:
                precision_changes.append(dict(entity_index=i, key=p['key'], previous=old, exact_float32_text=p['keyvalue']))
        classname = values.get('classname')
        class_counts[str(classname)] += 1
        # In the Silver capture every named transform component is an integer,
        # within half a unit of these record floats. Retain both representations
        # and use the corroborated higher-precision record values for conversion.
        transform = {}
        conversion_keyvalues = dict(keyvalues)
        for j, key in enumerate(('origin', 'angles')):
            named = values.get(key)
            record = vectors[j]
            corroborated = (isinstance(named, list) and len(named) == 3
                            and all(v is not None for v in named + record)
                            and all(abs(a-b) <= 0.50001 for a, b in zip(named, record)))
            transform[key] = record if corroborated else named
            transform[key + '_source'] = 'entity_record' if corroborated else 'named_property'
            transform[key + '_status'] = ('record_agrees_with_named_property_within_half_unit'
                                         if corroborated else 'record_relation_not_confirmed')
            if corroborated:
                conversion_keyvalues[key] = ' '.join(number_text(v) for v in record)
        entities.append(dict(index=i, classname=classname, properties=values, keyvalues=keyvalues,
                             property_list=ordered, duplicate_keys=duplicates,
                             origin=transform['origin'], angles=transform['angles'], transform=transform,
                             conversion_keyvalues=conversion_keyvalues,
                             record=dict(address=candidate['record_address'], raw_hex=raw.hex(),
                                         raw_reference_u32=reference, raw_id_u32=identity,
                                         unknown_offset_4_hex=raw[4:8].hex(), vector_candidates=vectors,
                                         vectors_match_named_properties=[vectors[j] == values.get(k) for j, k in enumerate(('origin', 'angles'))]),
                             bo3=dict(classname_status=('present_in_installed_definitions' if classname in classes else
                                                        'absent_from_installed_definitions') if bo3_def else 'not_checked',
                                      converted=False)))
    targets = defaultdict(list)
    for entity in entities:
        name = entity['keyvalues'].get('targetname')
        if name:
            targets[name].append(entity['index'])
    links = []
    for entity in entities:
        name = entity['keyvalues'].get('target')
        if name:
            links.append(dict(entity_index=entity['index'], key='target', value=name,
                              matching_targetname_entity_indices=targets.get(name, []),
                              status='exact_string_match' if name in targets else 'not_in_this_entitylist'))
    allprops = [p for e in entities for p in e['property_list']]
    summary = dict(entity_count=count, property_count=len(allprops), type_counts=dict(types),
                   class_counts=dict(sorted(class_counts.items())), duplicate_key_entities=sum(bool(e['duplicate_keys']) for e in entities),
                   unknown_type_properties=sum(p['type']=='unknown' for p in allprops),
                   unrepresentable_keyvalues=sum(p['key'] is None or p['keyvalue'] is None for p in allprops),
                   asset_hash_properties=sum(p['type_tag']==4 for p in allprops),
                   unresolved_asset_hash_properties=sum(p.get('name_status')=='unresolved' for p in allprops),
                   revised_float_strings=len(precision_changes), target_links=len(links),
                   targets_absent_from_entitylist=sum(not r['matching_targetname_entity_indices'] for r in links),
                   bo3_class_status_counts=dict(Counter(e['bo3']['classname_status'] for e in entities)),
                   record_vector_property_mismatches=sum(not all(e['record']['vectors_match_named_properties']) for e in entities),
                   record_transforms_corroborated=sum(all(e['transform'][k + '_source']=='entity_record' for k in ('origin', 'angles')) for e in entities))
    return dict(schema='greyhound-cw-entitylist-lossless-v1', map=map_name,
                source=dict(capture_directory=str(capture.root), pool=142, name_hash=native['source_name_hash'],
                            header_offset=matching[0], capture_finished_utc=capture.evidence.get('finished_utc'),
                            capture_readback_unchanged=native['readback_unchanged'], atomic_snapshot=False,
                            physical_files={name:dict(bytes=len(data), sha256=hashlib.sha256(data).hexdigest()) for name, data in capture.cache.items()},
                            logical_files=capture.logical_files),
                scope='All counted ENTITYLIST records and property bytes in this saved capture. Not all runtime/spawned entities, brush geometry, script behavior, or a completed BO3 conversion.',
                conventions=dict(coordinates='Original CW coordinate values and axis order; no transform applied.',
                                 floats='JSON numbers retain exact finite float32 values; keyvalues use 9 significant digits to round-trip float32.',
                                 hashes='Hex strings preserve all 64 bits; names from the previous Greyhound export are cache candidates.',
                                 properties='Typed dictionary; duplicate keys omitted here and in keyvalues, preserved in property_list.',
                                 transforms='origin/angles and conversion_keyvalues prefer record float3 values at +24/+36 when each component agrees with named properties within 0.50001. Original named values remain in properties/keyvalues; this is a measured layout interpretation, not a traced engine consumer.',
                                 links='Only literal target to targetname matches within this list; absence may mean a dynamic or external target.',
                                 bo3='Class presence is an authoring hint, not proof of equivalent keys, scripts, assets, or gameplay.'),
                bo3_definitions=class_source, summary=summary, entities=entities,
                target_links=links, float_text_changes=precision_changes)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capture', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--bo3-def', type=Path)
    parser.add_argument('--map-name')
    args = parser.parse_args()
    require(not args.output.resolve().is_relative_to(args.capture.resolve()), 'Write the decode outside the evidence capture')
    result = decode(args.capture, args.bo3_def, args.map_name)
    args.output.mkdir(parents=True, exist_ok=True)
    def write(name, value):
        (args.output / name).write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + '\n', encoding='utf-8')
    write('entities.decoded.json', result)
    # Keep the established Entities shape for existing map conversion scripts.
    write('entities.json', dict(schema='greyhound-cw-entity-keyvalues-v2', source_name_hash=result['source']['name_hash'],
                               entity_count=len(result['entities']),
                               omitted_property_entries=result['summary']['unrepresentable_keyvalues'] + sum(
                                   sum(p['key'] in e['duplicate_keys'] for p in e['property_list']) for e in result['entities']),
                               source='entities.decoded.json',
                               transform_policy=result['conventions']['transforms'],
                               converted_to_bo3=False,
                               Entities=[e['conversion_keyvalues'] for e in result['entities']]))
    write('summary.json', result['summary'])
    print(json.dumps(result['summary']))


if __name__ == '__main__':
    main()
