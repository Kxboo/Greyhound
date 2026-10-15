"""Engine-byte oracle regressions for expanded terrain material reconstruction."""
import json
from pathlib import Path
import struct
import sys
import unittest

REPO = next(p for p in Path(__file__).resolve().parents if (p / 'build-greyhound.ps1').is_file())
sys.path.insert(0, str(REPO / 'tools/black_ops_4/capture'))
import bo4_terrain_layer_source as source

FIXTURES = Path(__file__).parent / 'fixtures/terrain_expanded_native_oracle.json'


class NativeLayerSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = json.loads(FIXTURES.read_text())

    def test_full_mansion_preparation_and_packing_matches_engine(self):
        registry = {int(k):v for k,v in self.fixture['registry'].items()}
        for case in self.fixture['layers']:
            with self.subTest(sector=case['sector'], slot=case['slot']):
                parameters = source.prepare_parameters(bytes.fromhex(case['source_hex']), case['weight_slice'],
                    {int(k):v for k,v in case['bindings'].items()}, registry)
                self.assertEqual(parameters.hex(), case['prepared_hex'])
                self.assertEqual(source.pack_parameters(parameters).hex(), case['packed_hex'])

    def test_packing_boundaries_match_offline_native_code_oracle(self):
        for index, case in enumerate(self.fixture['packing_edge_cases']):
            with self.subTest(case=index):
                self.assertEqual(source.pack_parameters(bytes.fromhex(case['parameters_hex'])).hex(), case['packed_hex'])

    def test_reused_material_keeps_each_layers_far_tiling_flag(self):
        cases = {(c['sector'],c['slot']):c for c in self.fixture['layers']}
        for donor, target, expected in [((1,0),(3,1),0x4f),((2,4),(3,2),0x7),
                                        ((1,3),(4,0),0x507),((1,0),(4,1),0x4f)]:
            with self.subTest(target=target):
                before = struct.unpack_from('<I',bytes.fromhex(cases[donor]['packed_hex']),52)[0]
                after = struct.unpack_from('<I',bytes.fromhex(cases[target]['packed_hex']),52)[0]
                self.assertEqual(before ^ after, 0x400)
                self.assertEqual(after & 0xffff,expected)

    def test_ground_cover_requires_its_uncaptured_runtime_override(self):
        raw=bytearray(bytes.fromhex(self.fixture['layers'][0]['source_hex']))
        raw[0x3d]=1
        with self.assertRaises(source.SourceUnavailable):
            source.prepare_parameters(bytes(raw),4094,{}, {})

    def test_usd_consumer_prefers_the_layer_record_over_a_material_donor(self):
        from bo4_terrain_records import layer_runtime
        layer={'runtime':{'flags':'0x7'}, 'uv_matrix_2x4':[0.0]*8, 'weight_source_slice':6}
        result=layer_runtime(layer,{'runtime':{'flags':'0x407'}})
        self.assertEqual(result['flags'],'0x7')
        self.assertEqual(result['weight_slice'],6)
        self.assertNotIn('weight_slice',layer['runtime'])

    def test_truncated_layer_is_rejected(self):
        with self.assertRaises(ValueError):
            source.prepare_parameters(bytes(263),4094,{}, {})


if __name__ == '__main__':
    unittest.main()
