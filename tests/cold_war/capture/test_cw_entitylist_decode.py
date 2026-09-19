
import sys as _tool_sys
from pathlib import Path as _ToolPath
REPO_ROOT = next(p for p in _ToolPath(__file__).resolve().parents if (p / "build-greyhound.ps1").is_file())
TOOLS_ROOT = REPO_ROOT / "tools"
_tool_sys.path.insert(0, str(TOOLS_ROOT))
import tool_bootstrap as _tool_bootstrap
_tool_bootstrap.activate(TOOLS_ROOT / "tool_bootstrap.py")
import importlib.util
import json
from pathlib import Path
import struct
import tempfile
import unittest


SPEC = importlib.util.spec_from_file_location('cw_entity_decode', REPO_ROOT / 'tools/cold_war/capture/decode_cw_entitylist.py')
decoder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(decoder)


class EntityDecodeTests(unittest.TestCase):
    def fixture(self, root, extra=()):
        storage, backing, candidates, legacy = {}, bytearray(), [], {}
        next_address = 0x100000

        def save(name, data):
            storage[name] = dict(file='small_records.bin', offset=len(backing), bytes=len(data))
            backing.extend(data)

        def string(value):
            nonlocal next_address
            address = next_address
            next_address += 0x100
            save(f'typed/strings/0x{address:X}.bin', value.encode() + b'\0')
            return dict(address=hex(address), text=value, terminated=True)

        properties = bytearray()
        items = [('classname', 2, 'script_struct'), ('origin', 3, (1., -2., 3.)),
                 ('angles', 3, (0., 45., 0.)), ('modelscale', 5, 1.1547900438308716),
                 ('hash', 4, 0xFEDCBA9876543210), ('signed', 6, 0xFFFFFFFF)] + list(extra)
        for key, tag, value in items:
            prop = dict(key=string(key), type_tag=tag, raw_tag_u32=tag)
            payload = bytearray(16)
            if tag == 2:
                prop['string_candidate'] = string(value)
                struct.pack_into('<Q', payload, 0, int(prop['string_candidate']['address'], 16))
                legacy[key] = value
            elif tag == 3:
                struct.pack_into('<3f', payload, 0, *value)
                prop['vector_candidate'] = list(value)
                legacy[key] = ' '.join(format(v, '.7g') for v in value)
            elif tag == 4:
                struct.pack_into('<Q', payload, 0, value)
                prop['asset_hash_candidate'] = hex(value)
                legacy[key] = f'{value:X}'
            elif tag == 5:
                struct.pack_into('<f', payload, 0, value)
                prop['float_candidate'] = value
                legacy[key] = format(value, '.7g')
            elif tag == 6:
                struct.pack_into('<I', payload, 0, value)
                prop['uint32_candidate'] = value
                prop['int32_candidate'] = struct.unpack('<i', payload[:4])[0]
                legacy[key] = str(value)
            prop['raw_value_hex'] = payload.hex()
            properties.extend(struct.pack('<Q', int(prop['key']['address'], 16)) + payload + struct.pack('<I', tag) + b'\xAB\xCD\xEF\x01')
            candidates.append(prop)
        save('typed/properties_0.bin', properties)
        record = struct.pack('<IIQII6f', len(items), 123, 0x3000, 0xFFFFFFFF, 42, 1.25, -2.25, 3.125, 0., 45.125, 0.)
        save('typed/entity_records.bin', record)
        save('headers.bin', struct.pack('<QIIQ', 0x5555, 1, 0, 0x2000))
        native = dict(source_pool=142, source_name_hash='0x5555', capture_reads_complete=True, readback_unchanged=True,
                      arrays=[dict(file='typed/entity_records.bin', count=1, candidate_stride=48, address='0x2000'),
                              dict(file='typed/properties_0.bin', count=len(items), candidate_stride=32, address='0x3000')],
                      entities=[dict(index=0, property_count=len(items), record_address='0x2000', raw_reference_u32=0xFFFFFFFF,
                                     raw_id_u32=42, record_vector_candidates=[[1.25, -2.25, 3.125], [0., 45.125, 0.]], properties=candidates)])
        for name, obj in [('evidence.json', dict(storage=storage)), ('decoded_candidates.json', native),
                          ('entities.json', dict(Entities=[legacy]))]:
            (root / name).write_text(json.dumps(obj))
        (root / 'small_records.bin').write_bytes(backing)

    def test_exact_values_transforms_hash_and_signedness(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.fixture(root)
            result = decoder.decode(root)
            e = result['entities'][0]
            self.assertEqual(e['origin'], [1.25, -2.25, 3.125])
            self.assertEqual(e['properties']['origin'], [1., -2., 3.])
            self.assertEqual(e['conversion_keyvalues']['origin'], '1.25 -2.25 3.125')
            self.assertEqual(e['properties']['hash'], '0xFEDCBA9876543210')
            integer = e['property_list'][-1]
            self.assertEqual((integer['signed_value'], integer['unsigned_value']), (-1, 4294967295))
            self.assertEqual(integer['unknown_tail_hex'], 'abcdef01')
            self.assertEqual(struct.pack('<f', float(e['keyvalues']['modelscale'])), struct.pack('<f', e['properties']['modelscale']))
            self.assertEqual(result['summary']['revised_float_strings'], 1)
            json.dumps(result, allow_nan=False)

    def test_duplicate_and_unknown_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.fixture(root, [('same', 2, 'a'), ('same', 2, 'b'), ('unknown', 99, None)])
            result = decoder.decode(root)
            e = result['entities'][0]
            self.assertEqual(e['duplicate_keys'], ['same'])
            self.assertNotIn('same', e['keyvalues'])
            self.assertEqual([p['value'] for p in e['property_list'] if p['key']=='same'], ['a', 'b'])
            self.assertEqual(result['summary']['unknown_type_properties'], 1)

    def test_reject_truncated_capture(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.fixture(root)
            path = root / 'small_records.bin'
            path.write_bytes(path.read_bytes()[:-1])
            with self.assertRaisesRegex(ValueError, 'Truncated'):
                decoder.decode(root)

    def test_reject_mismatched_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.fixture(root)
            path = root / 'decoded_candidates.json'
            native = json.loads(path.read_text())
            native['entities'][0]['raw_id_u32'] = 7
            path.write_text(json.dumps(native))
            with self.assertRaisesRegex(ValueError, 'IDs differ'):
                decoder.decode(root)


if __name__ == '__main__':
    unittest.main()
