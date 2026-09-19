
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

from export_cw_volume_connections import build, export, edge_center


class ConnectionTests(unittest.TestCase):
    def fixture(self):
        common=['bot','civilian','human','hero','advanced','mannequin','robot','riotshield','dog','gorilla','vehicle','zombie','zombie_no_legs','zombie_keeper','zombie_dog','zombie_boss']
        source=common+['ghost']
        target=common+['monkey','zombie_quad']
        nodes=[dict(index=i,source_entity_index=i+100,classname='node_negotiation_volume',position=[i*128,0,10],
                    compiled_yaw=0,cost_modifier=1,edge_points=[[i*128,-20,0],[i*128,20,0]],
                    movement_ignore_names=source if i==0 else ['vehicle'],movement_ignore_mask='0x1ffff' if i==0 else '0x400') for i in range(2)]
        graph=dict(schema='cw-navigation-graph-evidence-v1',map='test',map_hash='0x12345678',nodes=nodes,
                   volume_pairs=[dict(index=0,volume_nodes=[0,1],mantle_node=None,directions=[dict(start_node=i,end_node=1-i,movement_ignore_names=nodes[i]['movement_ignore_names']) for i in range(2)])])
        reference=dict(entity_reference=dict(classes=dict(node_negotiation_begin=dict(movementtype_ignore=dict(flags=','.join(target))))),
            navigation_reference=dict(one_way_empty_end_animscript_reference='one_way.map',stock_traversals=[
                dict(animscript=f'{family}_{n}',family=family,nominal_distance=n,rows=[])
                for family in ('jump_up','jump_down','jump_across') for n in (36,72,128)]))
        return graph,reference

    def test_one_way_and_actor_scope_survive_map(self):
        graph,reference=self.fixture()
        with tempfile.TemporaryDirectory() as tmp:
            report=export(graph,reference,tmp,'test')
            self.assertEqual(report['summary']['directional_connections'],1)
            self.assertEqual(report['summary']['directions_with_no_mapped_actor'],1)
            row=report['emitted'][0]
            self.assertEqual(row['source_start_node'],1)
            self.assertEqual(row['end_properties']['animscript'],'')
            self.assertEqual(set(row['begin_properties']['movementtype_ignore'].split(',')),{'vehicle','monkey','zombie_quad'})
            self.assertEqual(report['actor_mapping']['unmapped_source_types'],['ghost'])
            self.assertEqual(row['begin_properties']['width'],'40')
            self.assertEqual(row['begin_properties']['origin'],'128 0 16')

    def test_no_vocabulary_inference_from_sparse_exclusions(self):
        graph,reference=self.fixture()
        graph['nodes'][0]['movement_ignore_names']=['vehicle']
        graph['nodes'][0]['movement_ignore_mask']='0x400'
        with self.assertRaisesRegex(ValueError,'source vocabulary'):build(graph,reference)

    def test_manual_animation_preserves_direction_and_placement(self):
        graph,reference=self.fixture()
        with tempfile.TemporaryDirectory() as tmp:
            report=export(graph,reference,tmp,'test',placement_only=True)
        row=report['emitted'][0]
        self.assertEqual(row['begin_properties']['animscript'],'')
        self.assertEqual(row['end_properties']['animscript'],'')
        self.assertEqual(row['source_edge_centers'][0],[128,0,0])
        self.assertEqual(row['begin_properties']['origin'],'128 0 16')
        self.assertEqual(row['source_start_node'],1)

    def test_edge_height_interpolates_samples(self):
        center,width,proof=edge_center(dict(edge_points=[[0,-5,10],[0,3,14],[0,5,16]]))
        self.assertEqual(center,[0,0,12.5])
        self.assertEqual(width,10)
        self.assertEqual(proof['segment'],[0,1])

    def test_reject_nonmonotonic_sampling(self):
        with self.assertRaisesRegex(ValueError,'Nonmonotonic'):
            edge_center(dict(edge_points=[[0,-5,10],[0,3,14],[0,2,16],[0,5,16]]))


if __name__=='__main__':unittest.main()
