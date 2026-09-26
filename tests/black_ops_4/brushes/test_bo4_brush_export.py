"""Regression tests for stock-category composition and certified BO4 publication."""
import sys
from pathlib import Path
TOOLS=Path(__file__).resolve().parents[3]/'tools'
sys.path.insert(0,str(TOOLS))
import tool_bootstrap
tool_bootstrap.activate(TOOLS/'tool_bootstrap.py')
import hashlib
import json
import tempfile
import unittest
import numpy as np
from exact_geometry import checked_hull
from certified_brush_partition import compact_pieces
from assign_bo4_bo3_types import Types,CLIP_NAMES
from bo4_brush_geometry import serialize_piece,publish_groups
from bo4_prefab_layout import prefab_relative_path,remap_references
from verify_bo4_brush_geometry import verify
from decode_bo4_collision import inline_bounds_check

REFERENCE=json.loads((TOOLS/'black_ops_3/reference/bo3_reference.json').read_text())

def types():
    values={'bulletClip':0x80,'missileClip':0x2000,'aiSightClip':0x1000}
    spare=iter([1,2,4,8,16,32,64])
    values.update({n:next(spare) for n in sorted(CLIP_NAMES-values.keys())})
    rows=[dict(name=n,field_8='0x0',field_12='0x0',field_16=hex(v),field_20='0x0') for n,v in values.items()]
    return Types(dict(named_flag_candidates=[dict(rows=rows)]),REFERENCE)

class CategoryTests(unittest.TestCase):
    def test_composes_exact_union_without_vehicle_addition(self):
        t=types();decision=t.choose(t.contents['playerClip']|t.contents['aiClip'],[0])
        self.assertEqual(decision['selected_stock_tools'],['clip_ai','clip_player'])
        self.assertFalse(decision['fallback']);self.assertEqual(decision['added_collision_properties'],[])
    def test_untyped_visual_never_receives_generic_material(self):
        row=types().choose(0,[0])
        self.assertTrue(row['visual_required']);self.assertIsNone(row['material']);self.assertEqual(row['collision_components'],[])
    def test_nonsolid_visual_requires_material_until_explicitly_nodraw(self):
        t=types();t.surface={'nonSolid':0x4000,'noDraw':0x80}
        self.assertTrue(t.choose(0,[0x4000])['visual_required'])
        self.assertEqual(t.choose(0,[0x4080])['material'],'skip')
    def test_review_folder_is_separate(self):
        self.assertEqual(prefab_relative_path('zm_world_tool_fallback_review.map').parts[:2],('review','tool fallbacks'))
        self.assertEqual(prefab_relative_path('zm_triggers_review.map').parts[0],'review')
    def test_unavailable_exact_category_is_named_as_review_fallback(self):
        t=types();row=t.choose(t.contents['bulletClip'],[0])
        self.assertTrue(row['fallback'])
        self.assertEqual(row['selected_stock_tools'],['clip_weapon'])
        self.assertEqual(row['source_collision_properties'],['bulletClip'])
        self.assertEqual(row['added_collision_properties'],['canShootClip'])
        self.assertEqual(row['omitted_collision_properties'],[])

class GeometryTests(unittest.TestCase):
    def test_collision_can_be_a_strict_subset_of_combined_model_bounds(self):
        brush=[-26.110124588,-17.25,-56,26.328445434,17.795742034,56]
        model=[-26.834575653,-17.25,-56,26.328445434,17.795742034,56]
        row=inline_bounds_check(brush,model)
        self.assertEqual(row['status'],'contained_collision_subset')
        self.assertEqual(row['brush_bounds'],brush)
        self.assertFalse(row['geometry_changed'])
        self.assertAlmostEqual(row['maximum_difference'],.724451065)
        self.assertEqual(inline_bounds_check(model,model)['status'],'equal_within_tolerance')
        with self.assertRaisesRegex(ValueError,'exceed'):
            inline_bounds_check(model,brush)
        with self.assertRaisesRegex(ValueError,'Invalid'):
            inline_bounds_check([float('nan')]*6,model)

    def test_partition_preserves_exact_exterior_and_volume(self):
        points=np.array([[np.cos(t),np.sin(t),z] for z in (-1,1) for t in np.arange(12)*2*np.pi/12])
        faces,_,_=checked_hull(points)
        pieces,certificate=compact_pieces(points.tolist(),faces.tolist(),8)
        self.assertTrue(certificate['partitioned']);self.assertTrue(certificate['internal_faces_cancel'])
        self.assertTrue(certificate['external_triangles_unchanged']);self.assertGreater(len(pieces),1)
        self.assertTrue(all(len(eq)<=8 for _,eq in pieces))
    def test_reopened_plane_and_material_tampering_is_rejected(self):
        points=np.array([[x,y,z] for x in (-1,1) for y in (-1,1) for z in (-1,1)],float)
        faces,_,_=checked_hull(points);parts,cert=compact_pieces(points.tolist(),faces.tolist(),64)
        t=types();decision=t.choose(t.contents['playerClip']|t.contents['aiClip'],[0])
        rows=[];bodies=[]
        for i,c in enumerate(decision['collision_components']):
            body,check=serialize_piece(*parts[0],np.eye(4),c['material'],c['brush_contents'],'000_Global',i)
            bodies.append(body);rows.append(dict(check,map_brush_index=i,source_brush_index=0,entity_index=None,
                layer='000_Global',material=c['material'],type_assignment=decision,collision_component=c,
                collision_component_index=i,partition_index=0,partition_count=1,prefab_group='world_clips'))
        with tempfile.TemporaryDirectory() as d:
            out=Path(d);publish_groups(out,'test','',rows,bodies,'prefab_group')
            report=dict(rows=rows,partition_certificates={'0':cert})
            self.assertTrue(verify(out,[report],REFERENCE)['geometry_verified'])
            path=out/rows[0]['prefab_file'];original=path.read_text();path.write_text(original.replace('clip_ai 64','clip_full 64',1))
            with self.assertRaisesRegex(ValueError,'material changed'):verify(out,[report],REFERENCE)
            path.write_text(original);rows.pop()
            with self.assertRaisesRegex(ValueError,'Cartesian coverage'):verify(out,[report],REFERENCE)

if __name__=='__main__':unittest.main()
