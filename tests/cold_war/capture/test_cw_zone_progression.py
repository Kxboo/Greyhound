
import sys as _tool_sys
from pathlib import Path as _ToolPath
REPO_ROOT = next(p for p in _ToolPath(__file__).resolve().parents if (p / "build-greyhound.ps1").is_file())
TOOLS_ROOT = REPO_ROOT / "tools"
_tool_sys.path.insert(0, str(TOOLS_ROOT))
import tool_bootstrap as _tool_bootstrap
_tool_bootstrap.activate(TOOLS_ROOT / "tool_bootstrap.py")
import importlib.util
from pathlib import Path
import tempfile
import unittest

import numpy as np

SPEC = importlib.util.spec_from_file_location('cw_zones', REPO_ROOT / 'tools/cold_war/capture/build_cw_zone_progression.py')
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ZoneProgressionTests(unittest.TestCase):
    def test_direction_and_multiple_flags_are_preserved(self):
        rows, aliases = MODULE.parse_connections('''
zm_zonemgr::add_adjacent_zone( "start", "room", "buy_a", 0 );
zm_zonemgr::add_adjacent_zone( "start", "room", "buy_b", 0 );
zm_zonemgr::add_adjacent_zone( "room", "drop", "drop_flag", 1 );
zm_zonemgr::add_zone_flags( "buy_a", "interior" );
''')
        self.assertEqual([r['flag'] for r in rows], ['buy_a', 'buy_b', 'drop_flag'])
        self.assertEqual([r['one_way'] for r in rows], [0, 0, 1])
        self.assertEqual(aliases[0]['set_flag'], 'interior')

    def test_captured_hull_rejects_mismatched_placement(self):
        p = MODULE.Prefab()
        equations = MODULE.box_planes([0, 0, 0], [1, 2, 3])
        row = dict(source_angles=[0, 0, 0], source_origin=[10, 0, 0], hulls=[dict(
            source_equations_local=equations.tolist(), active_source_planes=list(range(6)),
            vertices_world=[[0, 0, 0]])])
        with self.assertRaisesRegex(ValueError, 'disagree'):
            p.source_hulls(row, 'volume')

    def test_dynamic_brush_and_door_link_roundtrip(self):
        p = MODULE.Prefab()
        props = dict(classname='script_brushmodel', targetname='cwzv1_gate', DYNAMICPATH='1',
                     spawnflags='1', script_noteworthy='clip')
        p.add(props, '000_Global/Test', [p.brush(MODULE.box_planes([0, 0, 0], [4, 64, 48]), [0, 0, 0], 'clip')])
        p.add(dict(classname='trigger_use', targetname='zombie_door', target='cwzv1_gate',
                   script_flag='door_flag', zombie_cost='750'), '000_Global/Test')
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'test.map'
            p.save(target)
            rows = MODULE.parse_map(target)
        self.assertEqual(rows[1]['properties']['spawnflags'], '1')
        self.assertEqual(rows[2]['properties']['target'], rows[1]['properties']['targetname'])


if __name__ == '__main__':
    unittest.main()
