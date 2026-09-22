
import sys as _tool_sys
from pathlib import Path as _ToolPath
REPO_ROOT = next(p for p in _ToolPath(__file__).resolve().parents if (p / "build-greyhound.ps1").is_file())
TOOLS_ROOT = REPO_ROOT / "tools"
_tool_sys.path.insert(0, str(TOOLS_ROOT))
import tool_bootstrap as _tool_bootstrap
_tool_bootstrap.activate(TOOLS_ROOT / "tool_bootstrap.py")
import json
from pathlib import Path
import sys
import unittest

from split_cw_brush_roles import classify, split, sha


class BrushRoles(unittest.TestCase):
    reference = json.loads((TOOLS_ROOT / 'black_ops_3/reference/bo3_reference.json').read_text())

    def role(self, name, contents, status='EXACT_NAMED_PROPERTIES', **evidence):
        return classify(dict(assigned_material=name, assignment_status=status,
                             material_assignment_key='1:0'), self.reference,
                        {'brushes': {'1:0': dict(named_contents=contents, **evidence)}})[0]

    def test_clip_families_stay_together_regardless_of_actor_mask(self):
        for name in ('clip', 'clip_player', 'clip_full', 'clip_nosight', 'clip_slick', 'clip_player_vehicle', 'clip_missile', 'clip_ai', 'clip_physics', 'clip_ai_wallrun', 'nosight_noclip'):
            self.assertEqual(self.role(name, ['playerClip']), 'brushes_clips')
            self.assertEqual(self.role(name, ['solid']), 'brushes_clips')

    def test_traversal_is_separate_even_when_it_clips_players(self):
        for name in ('ladder', 'mantle_on', 'mantle_over', 'mount', 'wall_climb'):
            self.assertEqual(self.role(name, ['playerClip']), 'other_brushes')

    def test_non_clip_tools_separate_but_clip_fallbacks_remain(self):
        for name in ('skip', 'caulk_shadow'):
            self.assertEqual(self.role(name, []), 'other_brushes')
        self.assertEqual(self.role('clip', ['solid'], 'REVIEW_EXISTING_FALLBACK'), 'brushes_clips')
        self.assertEqual(self.role('unavailable_clip', ['playerClip']), 'other_brushes')

    def test_known_non_colliding_and_zero_query_fallbacks_are_references(self):
        for name in ('clip', 'concrete_clip', 'nodraw_notsolid', 'mantle_on', 'unavailable_clip'):
            self.assertEqual(self.role(name, [], contents_raw='0x0', unknown_contents='0x0',
                common_surface_flags=['nonSolid', 'noDraw']), 'reference_brushes')
        self.assertEqual(self.role('clip', [], 'REVIEW_EXISTING_FALLBACK', contents_raw='0x0',
            unknown_contents='0x0', common_surface_flags=None), 'reference_brushes')
        self.assertEqual(self.role('clip', ['nonColliding'], contents_raw='0x400000',
            unknown_contents='0x0'), 'reference_brushes')

    def test_non_solid_player_clips_and_unknown_base_solid_are_not_removed(self):
        self.assertEqual(self.role('clip', ['playerClip'], contents_raw='0x10000',
            unknown_contents='0x0', common_surface_flags=['nonSolid', 'noDraw']), 'brushes_clips')
        self.assertEqual(self.role('clip', [], 'REVIEW_EXISTING_FALLBACK', contents_raw='0x1',
            unknown_contents='0x1', common_surface_flags=None), 'brushes_clips')
        self.assertEqual(self.role('caulk_shadow', [], contents_raw='0x0', unknown_contents='0x0',
            common_surface_flags=['caulk', 'noDraw']), 'other_brushes')

    def test_query_only_source_cannot_gain_player_collision_from_material_match(self):
        evidence=dict(contents_raw='0x3080', unknown_contents='0x0', common_surface_flags=['nonSolid'])
        self.assertEqual(self.role('metal_clip_full', ['missileClip', 'bulletClip', 'aiSightClip'],
            **evidence), 'reference_brushes')
        self.assertEqual(self.role('clip_missile', ['missileClip'], **evidence), 'brushes_clips')
        self.assertEqual(self.role('nosight_noclip', ['aiSightClip'], **evidence), 'brushes_clips')

    def test_source_roles_apply_with_automatic_material_assignment_disabled(self):
        row = dict(assigned_material='clip', collision_asset_index=12, brush_index=3)
        assignments = {'brushes': {'12:3': dict(contents_raw='0x0', unknown_contents='0x0',
                                               named_contents=[], common_surface_flags=None)}}
        self.assertEqual(classify(row, self.reference, assignments)[0], 'reference_brushes')


def test_split_preserves_each_placement_and_projection_and_records_original_candidate(tmp_path):
    reference = BrushRoles.reference
    face = '( 0 0 0 ) ( 1 0 0 ) ( 0 1 0 ) clip 64 64 0.125 0 0 0 lightmap_gray 16384 16384 0 0 0 0\n'
    blocks = [f'// brush {i}\n{{\nlayer "000_Global"\n' + face * 6 + '}\n' for i in range(3)]
    path = tmp_path/'test_brush_collision.map'
    prefix = 'iwmap 4\n// entity 0\n{\n"classname" "worldspawn"\n'
    path.write_text(prefix + ''.join(blocks) + '}\n')
    rows = [dict(map_brush_index=i, assigned_material='clip', face_count=6, material_assignment_key=f'0:{i}',
                 position=[i, 2, 3], quaternion_xyzw=[0, 0, 0, 1], uniform_scale=1) for i in range(3)]
    (tmp_path/'collision_metadata.json').write_text(json.dumps(dict(map='test', map_sha256=sha(path), rows=rows)))
    assignments = {'brushes': {
        '0:0': dict(contents_raw='0x0', unknown_contents='0x0', named_contents=[], common_surface_flags=None),
        '0:1': dict(contents_raw='0x10000', unknown_contents='0x0', named_contents=['playerClip'], common_surface_flags=['nonSolid']),
        '0:2': dict(contents_raw='0x1', unknown_contents='0x1', named_contents=[], common_surface_flags=None)}}
    (tmp_path/'material_assignments.json').write_text(json.dumps(assignments))
    prefabs = split(tmp_path, reference)
    assert prefabs['brushes_clips']['brushes'] == 2
    assert prefabs['reference_brushes']['brushes'] == 1
    reference_text = (tmp_path/prefabs['reference_brushes']['file']).read_text()
    assert reference_text == prefix.replace('iwmap 4\n', 'iwmap 4\n"000_Global/CW_Reference" flags ignore\n') + blocks[0].replace(' clip ', ' nodraw_notsolid ').replace('layer "000_Global"', 'layer "000_Global/CW_Reference"') + '}\n'
    assert prefabs['reference_brushes']['compile_excluded']
    assert path.read_text() == prefix + ''.join(blocks[1:]) + '}\n'
    output = json.loads((tmp_path/'collision_metadata.json').read_text())
    assert output['rows'][0]['collision_candidate_material'] == 'clip'
    assert output['rows'][0]['assigned_material'] == 'nodraw_notsolid'
    for before, after in zip(rows, output['rows']):
        assert all(before[k] == after[k] for k in ('position','quaternion_xyzw','uniform_scale','map_brush_index'))


if __name__ == '__main__':
    unittest.main()
