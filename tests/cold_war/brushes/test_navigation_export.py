
import sys as _tool_sys
from pathlib import Path as _ToolPath
REPO_ROOT = next(p for p in _ToolPath(__file__).resolve().parents if (p / "build-greyhound.ps1").is_file())
TOOLS_ROOT = REPO_ROOT / "tools"
_tool_sys.path.insert(0, str(TOOLS_ROOT))
import tool_bootstrap as _tool_bootstrap
_tool_bootstrap.activate(TOOLS_ROOT / "tool_bootstrap.py")
import copy
import sys
from pathlib import Path
import tempfile
import unittest

from export_cw_bo3_navigation import BEGIN, END, plan, export


class NavigationTests(unittest.TestCase):
    def fixture(self):
        common = dict(PROCEDURAL=dict(type='bool', spawnflag='1024'), targetname=dict(type='string'))
        catalogue=[dict(animscript=family+'_'+str(distance),family=family,nominal_distance=distance,rows=[])
                   for family in ('jump_up','jump_down','jump_across') for distance in (36,72,128,256)]
        reference = dict(navigation_reference=dict(stock_traversals=catalogue),entity_reference=dict(classes={
            BEGIN: dict(common, target=dict(type='string'), movementtype_ignore=dict(type='string', flags='vehicle,zombie')),
            END: dict(common)}))
        rows = [dict(index=10, classname=BEGIN, conversion_keyvalues=dict(
                    classname=BEGIN, origin='1.25 -2.125 16', angles='0 45.12345 0',
                    target='end', targetname='start', movementtype_ignore='vehicle', spawnflags='67108864',
                    animscript='cw_missing_script')),
                dict(index=11, classname=END, conversion_keyvalues=dict(
                    classname=END, origin='10.25 -2.125 52', angles='0 225.12345 0', targetname='end', target='start'))]
        document = dict(schema='greyhound-cw-entitylist-lossless-v1', map='test', source=dict(name_hash='0x123'), entities=rows)
        return document, reference

    def test_both_endpoint_flags_and_properties_survive_serialization(self):
        document, reference = self.fixture()
        with tempfile.TemporaryDirectory() as tmp:
            report = export(document, reference, tmp, 'test')
            pair = report['pairs'][0]
            for side in ('begin', 'end'):
                self.assertEqual(pair[side + '_properties']['spawnflags'], '0')
                self.assertEqual(pair[side + '_properties']['PROCEDURAL'], '0')
            self.assertEqual(pair['begin_properties']['animscript'], 'jump_up_36')
            self.assertEqual(pair['end_properties']['animscript'], 'jump_down_36')
            self.assertEqual(pair['begin_properties']['origin'], '1.25 -2.125 16')
            self.assertEqual(pair['begin_properties']['movementtype_ignore'], 'vehicle')
            self.assertEqual(pair['reverse_source_target'], 'start')
            self.assertFalse(pair['reverse_behavior_verified'])
            self.assertTrue(report['output']['entity_property_roundtrip_verified'])

    def test_unknown_restriction_does_not_broaden_actor_access(self):
        document, reference = self.fixture()
        document['entities'][0]['conversion_keyvalues']['movementtype_ignore'] = 'vehicle,unknown_actor'
        result = plan(document, reference)
        self.assertEqual(result['summary']['emitted_nodes'], 0)
        self.assertIn('unknown_actor', result['unresolved_pairs'][0]['reason'])

    def test_placement_reference_keeps_source_animation_without_assigning_it(self):
        document, reference = self.fixture()
        with tempfile.TemporaryDirectory() as tmp:
            result = export(document, reference, tmp, 'test', placement_only=True)
        pair = result['pairs'][0]
        self.assertEqual(pair['source_begin']['animscript'], 'cw_missing_script')
        self.assertEqual(pair['begin_properties']['animscript'], '')
        self.assertEqual(pair['end_properties']['animscript'], '')
        self.assertEqual(pair['begin_properties']['origin'], '1.25 -2.125 16')

    def test_ambiguous_target_is_not_silently_selected(self):
        document, reference = self.fixture()
        duplicate = copy.deepcopy(document['entities'][1])
        duplicate['index'] = 12
        document['entities'].append(duplicate)
        result = plan(document, reference)
        self.assertEqual(result['summary']['emitted_nodes'], 0)
        self.assertEqual(result['summary']['deferred_entities'], 3)

    def test_volumes_and_restrictions_are_retained(self):
        document, reference = self.fixture()
        document['entities'].append(dict(index=12, classname='node_negotiation_volume',
                                        conversion_keyvalues=dict(classname='node_negotiation_volume', movementtype_ignore='zombie')))
        result = plan(document, reference)
        self.assertEqual(result['summary']['deferred_with_movement_restrictions'], 1)
        self.assertEqual(result['deferred'][0]['source_properties']['movementtype_ignore'], 'zombie')


if __name__ == '__main__':
    unittest.main()
