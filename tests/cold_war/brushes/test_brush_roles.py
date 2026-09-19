
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

from split_cw_brush_roles import classify


class BrushRoles(unittest.TestCase):
    reference = json.loads((TOOLS_ROOT / 'black_ops_3/reference/bo3_reference.json').read_text())

    def role(self, name, contents, status='EXACT_NAMED_PROPERTIES'):
        return classify(dict(assigned_material=name, assignment_status=status,
                             material_assignment_key='1:0'), self.reference,
                        {'brushes': {'1:0': {'named_contents': contents}}})[0]

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


if __name__ == '__main__':
    unittest.main()
