"""Regression checks for trigger conversion policy and independent hull placement."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'pipeline'))
import export_cw_bo3_trigger_entities as exporter


class TriggerExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.reference = json.loads((ROOT / 'bo3_reference.json').read_text())

    def row(self, classname='trigger_multiple', index=0):
        return dict(classname=classname, entity_index=index, source_id=index,
                    origin=[100., 200., 300.], angles=[0., 0., 0.],
                    properties={'classname': classname, 'targetname': 'shared_name'},
                    hulls=[dict(hull_index=index, local_center=[2., 3., 4.],
                                local_halfsize=[1., 2., 3.], slabs=[])])

    def export_rows(self, rows):
        source = dict(models=[r for r in rows if 'hulls' in r],
                      entities_without_precompiled_model=[r for r in rows if 'hulls' not in r])
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'evidence.json').write_text('{}')
            with patch.object(exporter, 'map_identity', return_value={'name_hash': '0x123'}), \
                    patch.object(exporter, 'ownership', return_value=source):
                report=exporter.export(root, 'zm_fixture', root / 'out', self.reference)
                report['_parsed_prefabs']={k:exporter.entities(root/'out'/v['file']) for k,v in report['map_files'].items()}
                report['_map_filenames']=sorted(p.name for p in (root/'out').glob('*.map'))
                return report

    def test_prefabs_partition_by_entity_class_without_duplication(self):
        volume=self.row('info_volume',0)
        trigger=self.row('trigger_multiple',1)
        box=self.row('trigger_box',2);del box['hulls']
        box['properties'].update(width='10',length='20',height='30')
        report=self.export_rows([volume,trigger,box])
        self.assertEqual(report['_map_filenames'],['zm_fixture_triggers.map','zm_fixture_volumes.map'])
        self.assertEqual(report['map_files']['volumes']['entities'],1)
        self.assertEqual(report['map_files']['triggers']['entities'],2)
        for category,rows in report['_parsed_prefabs'].items():
            self.assertEqual(rows[0]['properties']['classname'],'worldspawn')
            self.assertEqual(rows[0]['brush_blocks'],0)
            for row in rows[1:]:
                self.assertEqual(row['properties']['classname']=='info_volume',category=='volumes')
        by_source={r['source_entity_index']:r for r in report['entities']}
        self.assertEqual(len(by_source),3)
        self.assertEqual([by_source[i]['map_entity_index'] for i in range(3)],[1,1,2])
        self.assertEqual(by_source[2]['emitted_properties']['origin'],'100 200 300')

    def test_empty_categories_still_have_valid_empty_prefabs(self):
        report=self.export_rows([])
        self.assertEqual(len(report['map_files']),2)
        self.assertTrue(all(len(rows)==1 for rows in report['_parsed_prefabs'].values()))

    def test_world_hulls_translate_once_and_preserve_duplicate_names(self):
        first = self.row()
        first['properties'].update(target='linked_trigger', script_noteworthy='zombie_zone')
        second = self.row(index=1)
        report = self.export_rows([first, second])
        entities = report['entities']
        self.assertEqual(len(entities), 2)
        self.assertNotEqual(entities[0]['layer'], entities[1]['layer'])
        for row in entities:
            props = row['emitted_properties']
            self.assertEqual(props['targetname'], 'shared_name')
            self.assertNotIn('origin', props)
            self.assertNotIn('angles', props)
            vertices = row['hulls'][0]['vertices_world']
            for axis, expected in enumerate([(101, 103), (201, 205), (301, 307)]):
                self.assertAlmostEqual(min(v[axis] for v in vertices), expected[0])
                self.assertAlmostEqual(max(v[axis] for v in vertices), expected[1])
        self.assertEqual(entities[0]['emitted_properties']['target'], 'linked_trigger')

    def test_unsupported_geometry_is_reported_and_source_is_retained(self):
        unknown = self.row('trigger_unknown')
        rotated = self.row(index=1)
        rotated['angles'] = [0., 90., 0.]
        invalid = self.row('trigger_box', 2)
        del invalid['hulls']
        invalid['properties'].update(width='nan', length='10', height='20')
        report = self.export_rows([unknown, rotated, invalid])
        self.assertEqual(report['summary']['skipped_entities'], 3)
        self.assertEqual(report['summary']['exported_entities'], 0)
        self.assertEqual(len(report['raw_trigger_data']['models']), 2)
        self.assertEqual({r['source_entity_index'] for r in report['not_converted']}, {0, 1, 2})

    def test_parameter_box_retains_transform_dimensions_and_limit(self):
        row = self.row('trigger_box')
        del row['hulls']
        row['angles'] = [0., 90., 0.]
        row['properties'].update(width='10', length='20', height='30')
        result = self.export_rows([row])['entities'][0]
        for key, value in dict(width='10', length='20', height='30', origin='100 200 300', angles='0 90 0').items():
            self.assertEqual(result['emitted_properties'][key], value)
        self.assertFalse(result['parameter_bounds_validated'])

    def test_flags_use_bo3_names_not_raw_cw_bit_positions(self):
        row = self.row('trigger_multiple')
        row['properties'].update(spawnflags='65535', AI_AXIS='1', TRIGGER_ONCE='1', TEAM_AXIS='1')
        original = copy.deepcopy(row)
        props, omitted, flags = exporter.properties(row, self.reference['entity_reference']['classes']['trigger_multiple'], False)
        self.assertEqual(props['spawnflags'], '1025')
        self.assertIn('TEAM_AXIS', omitted)
        self.assertIn('spawnflags', omitted)
        self.assertEqual(flags['AI_AXIS'], 1)
        self.assertEqual(row, original)

    def test_unknown_bo3_enum_is_retained_only_as_source(self):
        row = self.row('trigger_use')
        row['properties']['cursorhint'] = 'CW_UNKNOWN_HINT'
        props, omitted, _ = exporter.properties(row, self.reference['entity_reference']['classes']['trigger_use'], False)
        self.assertNotIn('cursorhint', props)
        self.assertIn('cursorhint', omitted)
        self.assertEqual(row['properties']['cursorhint'], 'CW_UNKNOWN_HINT')

    def test_named_volume_purpose_is_preserved_without_guessing_from_targetname(self):
        materials={m['name']:m for m in self.reference['materials']}
        row=self.row('info_volume')
        row['properties'].update(targetname='kill_somewhere',script_noteworthy='district_toggle_volumes',variantName='info_volume_zm_districts_toggle')
        identity=exporter.volume_identity(row,materials)
        self.assertEqual(identity['material'],'volume')
        self.assertEqual(identity['source_identifiers']['variantName'],'info_volume_zm_districts_toggle')
        self.assertFalse(identity['gameplay_ported'])
        for purpose,material in [('unlock_volume','unlock'),('vol_death_zone','kill'),('fog','fog')]:
            row['properties']['script_noteworthy']=purpose
            result=self.export_rows([row])['entities'][0]
            self.assertEqual(result['material'],material)
            self.assertEqual(result['emitted_properties']['script_noteworthy'],purpose)
            self.assertIn('/'+purpose+'/',result['layer'])


if __name__ == '__main__':
    unittest.main()
