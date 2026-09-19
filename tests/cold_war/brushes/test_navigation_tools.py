
import sys as _tool_sys
from pathlib import Path as _ToolPath
REPO_ROOT = next(p for p in _ToolPath(__file__).resolve().parents if (p / "build-greyhound.ps1").is_file())
TOOLS_ROOT = REPO_ROOT / "tools"
_tool_sys.path.insert(0, str(TOOLS_ROOT))
import tool_bootstrap as _tool_bootstrap
_tool_bootstrap.activate(TOOLS_ROOT / "tool_bootstrap.py")
from pathlib import Path
import sys
import tempfile
import unittest

from export_cw_navigation_tools import export


class NavigationToolTests(unittest.TestCase):
    def fixture(self):
        graph=dict(schema='cw-navigation-graph-evidence-v1',map='test',map_hash='0x123',volume_pairs=[],nodes=[
            dict(index=0,source_entity_index=99,classname='node_negotiation_volume',
                 position=[10,20,30],angles=[2,0,-19],compiled_yaw=0,
                 geometry_validation=dict(source_local_half_dimensions=[2,5,5]),
                 edge_points=[[12,16,26],[12,24,34]],
                 source_properties=dict(movementtype_ignore='zombie'))])
        reference=dict(materials=[dict(name=n,properties=dict(surfaceClimbType=t,noDraw='1',nonSolid='1'))
                                  for n,t in (('traverse','<none>'),('mantle_on','mantleOn'),('mantle_over','mantleOver'))])
        return graph,reference

    def test_centered_bounds_use_compiled_yaw_and_keep_restrictions(self):
        graph,reference=self.fixture()
        with tempfile.TemporaryDirectory() as tmp:
            result=export(graph,reference,tmp,'test')
            record=result['records'][0]
            self.assertEqual(record['center'],[10,20,30])
            self.assertLessEqual(record['max_serialized_point_outside'],.001)
            self.assertEqual(record['bounds_orientation']['source_entity_angles'],[2,0,-19])
            self.assertEqual(record['source_properties']['movementtype_ignore'],'zombie')
            self.assertFalse(record['movement_restrictions_implemented_by_brush'])
            self.assertEqual(result['summary']['verified_edge_points'],2)

    def test_reject_points_outside_bound(self):
        graph,reference=self.fixture()
        graph['nodes'][0]['edge_points'][0][2]=0
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError,'escape'):
                export(graph,reference,tmp,'test')


if __name__=='__main__':unittest.main()
