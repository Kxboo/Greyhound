"""Behavior regressions for basic BO3 tools using stock definitions and CW flags."""

import sys as _tool_sys
from pathlib import Path as _ToolPath
REPO_ROOT = next(p for p in _ToolPath(__file__).resolve().parents if (p / "build-greyhound.ps1").is_file())
TOOLS_ROOT = REPO_ROOT / "tools"
_tool_sys.path.insert(0, str(TOOLS_ROOT))
import tool_bootstrap as _tool_bootstrap
_tool_bootstrap.activate(TOOLS_ROOT / "tool_bootstrap.py")
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=TOOLS_ROOT
import assign_cw_bo3_types as types
import separate_cw_tool_surface_projections as projections


class BasicToolsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.reference=json.loads((TOOLS_ROOT / 'black_ops_3/reference/bo3_reference.json').read_text())

    def decision(self, contents, surface, joined=True, traversal=False, surface_types=()):
        flags=[dict(name=n,field_12=hex(s),field_16=hex(c)) for n,s,c in
               [('mount',0x4000000,0x400000),('playerClip',0,0x10000),
                ('missileClip',0,0x80),('sky',4,0x800),('portal',0x80000000,0),
                ('nonSolid',0x4000,0),('nonColliding',0,4),('caulk',0x1000,0),
                ('onlyCastSunShadow',0x20000,0),('outdoorOccluder',0x10000,0),
                ('slick',2,0),('noDraw',0x80,0),('noImpact',0x10,0),('noMarks',0x20,0),
                ('bulletClip',0,0x2000),('aiClip',0,0x20000),('vehicleClip',0,0x200),
                ('itemClip',0,0x400),('canShootClip',0,0x40),('aiSightClip',0,0x1000),
                ('utilityClip',0,0x100000),('noCastShadow',0x40000,0)]]
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);payload=b'fixture';(root/'payload.bin').write_bytes(payload)
            model=dict(index=0,name_hash='0x42',status='decoded',payload=dict(file='payload.bin',sha256=hashlib.sha256(payload).hexdigest()))
            (root/'capture.json').write_text(json.dumps(dict(map='zm_fixture',map_hash='0x123',models=[model])))
            enums=[dict(name=n,field_12=hex((i+1)<<27),field_16=hex(0x400000 if n in ('mantleOn','mantleOver') else 0))
                   for i,n in enumerate(['ladder','mantleOn','mantleOver','climbWall','climbPipe'])] if traversal else []
            (root/'brush_type_capture.json').write_text(json.dumps(dict(readback_unchanged=True,map_hash='0x123',named_flags=flags,traversal_flags=enums,
                surface_types=list(surface_types),filter_entries=[dict(surface_raw=hex(surface),contents_raw=hex(contents))])))
            decoded=dict(pointer_layout_verified=joined,side_contents_union_mismatches=[],brushes=[dict(brush_index=0,contents=hex(contents),sides=[dict(filter_index=0)]*6)])
            with patch.object(types,'decode',return_value=decoded):
                return types.build_assignments(root,root,self.reference)['brushes']['0:0']['decision']

    def test_mount_contents_survive_missing_surface_join(self):
        result=self.decision(0x400000,0,False)
        self.assertEqual(result['material'],'mount')
        self.assertEqual(result['bo3_non_solid'],'1')
        self.assertFalse(result['exact_known_properties'])
        self.assertEqual(result['status'],'CONTENTS_MATCH_SURFACE_UNKNOWN')

    def test_enum_is_not_an_overlapping_bitset(self):
        for code,contents,name in [(1,0x10000,'ladder'),(2,0x400000,'mantle_on'),
            (3,0x400000,'mantle_over'),(4,0x10000,'wall_climb'),(5,0x10000,'pipe_climb')]:
            with self.subTest(code=code):
                result=self.decision(contents,(code<<27)|0x4080,traversal=True)
                self.assertEqual(result['material'],name)
                self.assertFalse(result['omitted_contents'])

    def test_combined_mount_requires_separate_surface_flag(self):
        self.assertEqual(self.decision(0x400000,0x10004080,traversal=True)['material'],'mantle_on')
        self.assertEqual(self.decision(0x400000,0x14004080,traversal=True)['material'],'mount_mantle_on')

    def test_stock_ladder_surface_variants_precede_generic_ladder(self):
        enums=[dict(name='metal',field_12='0xd00000',field_16='0'),
               dict(name='wood',field_12='0x1400000',field_16='0')]
        for code,name in [(0xd00000,'ladder_metal'),(0x1400000,'ladder_wood')]:
            result=self.decision(0x10000,(1<<27)|0x4080|code,traversal=True,surface_types=enums)
            self.assertEqual(result['material'],name)
            self.assertTrue(result['surface_type_retained'])
        result=self.decision(0x10000,(1<<27)|0x4080|0xd00000,joined=False,traversal=True,surface_types=enums)
        self.assertNotIn(result['material'],('ladder_metal','ladder_wood'))

    def test_metal_catwalk_uses_related_stock_when_query_preservation_prevents_exact_surface(self):
        enums=[dict(name='metal',field_12='0xd00000',field_16='0'),
               dict(name='metalcatwalk',field_12='0x2200000',field_16='0')]
        # Fresh Silver profile: stock catwalk lacks three query flags, whereas
        # full metal preserves them and adds bullet blocking. Keep the difference.
        result=self.decision(1251008,35930272,surface_types=enums)
        self.assertEqual(result['material'],'metal_clip_full')
        self.assertEqual(result['added_contents'],['bulletClip'])
        self.assertEqual(result['omitted_contents'],[])
        self.assertEqual(result['surface_type_match'],'related_stock_family')
        self.assertFalse(result['exact_known_properties'])
        # When source queries match the actual catwalk tool, keep that exact
        # surface instead of collapsing every metal subtype to generic metal.
        result=self.decision(0x130600,35930272,surface_types=enums)
        self.assertEqual(result['material'],'metal_clip_catwalk')
        self.assertTrue(result['surface_type_retained'])

    def test_missing_or_unjoined_enum_remains_basic_mount(self):
        self.assertEqual(self.decision(0x400000,0x18004080)['material'],'mount')
        self.assertEqual(self.decision(0x400000,0x18004080,False,True)['material'],'mount')

    def test_basic_tools_and_specialized_caulk_use_positive_properties(self):
        for contents,surface,name in [(0,0x80004080,'portal'),(0x800,4,'sky'),
            (0,0x5080,'caulk_shadow'),(4,0x25080,'caulk_sun_shadow'),
            (4,0x15080,'caulk_outdoor_occluder'),(0,0x4080,'skip')]:
            with self.subTest(name=name):self.assertEqual(self.decision(contents,surface)['material'],name)

    def test_non_solid_player_query_is_not_discarded_as_skip(self):
        result=self.decision(0x10000,0x4080)
        self.assertNotEqual(result['material'],'skip')
        self.assertNotIn('playerClip',result['omitted_contents'])

    def test_unjoined_surface_cannot_invent_tool_names(self):
        result=self.decision(0,0x80004080,False)
        self.assertEqual(result['status'],'REVIEW_EXISTING_FALLBACK')
        self.assertNotEqual(result['material'],'portal')

    def test_approximate_mount_retains_omitted_query_metadata(self):
        result=self.decision(0x410000,0x4080)
        self.assertEqual(result['material'],'mount')
        self.assertEqual(result['status'],'APPROXIMATE_BO3_TOOL')
        self.assertIn('playerClip',result['omitted_contents'])

    def test_visible_sky_projection_is_not_shifted(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);name='zm_fixture_brush_collision.map'
            face='( 0 0 0 ) ( 1 0 0 ) ( 0 1 0 ) {} 64 64 0 0 0 0 lightmap_gray 16384 16384 0 0 0 0'
            source='iwmap 4\n// entity 0\n{\n"classname" "worldspawn"\n// brush 0\n{\n'+face.format('mount')+'\n}\n// brush 1\n{\n'+face.format('sky')+'\n}\n}\n'
            (root/name).write_text(source)
            meta=dict(map='zm_fixture',map_sha256=types.sha(root/name),implementation_sha256={},rows=[
                dict(map_brush_index=i,assigned_material=n,face_count=1) for i,n in enumerate(['mount','sky'])])
            (root/'collision_metadata.json').write_text(json.dumps(meta))
            gdt=root/'tools.gdt';gdt.write_text('{\n"mount" ( "material.gdf" ) { "noDraw" "1" }\n"sky" ( "material.gdf" ) { "noDraw" "0" }\n}\n')
            with patch.object(sys,'argv',['test',str(root),'--output',str(root/'out'),'--gdt',str(gdt)]):projections.main()
            result=(root/'out'/name).read_text()
            self.assertIn(face.format('sky'),result)
            self.assertIn('mount 64 64 0.125 0 0 0',result)


if __name__=='__main__':unittest.main()
