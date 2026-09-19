"""Nonzero fixtures check reference conversion, not live engine behavior."""

import sys as _tool_sys
from pathlib import Path as _ToolPath
REPO_ROOT = next(p for p in _ToolPath(__file__).resolve().parents if (p / "build-greyhound.ps1").is_file())
TOOLS_ROOT = REPO_ROOT / "tools"
_tool_sys.path.insert(0, str(TOOLS_ROOT))
import tool_bootstrap as _tool_bootstrap
_tool_bootstrap.activate(TOOLS_ROOT / "tool_bootstrap.py")
import sys, unittest
from pathlib import Path
from cw_scene_controls import canonical, root_transform, alignment_pose

class SceneControls(unittest.TestCase):
    def setUp(self):
        self.root = root_transform({'Properties': {'origin':[10,20,30], 'angles':[0,90,0], 'modelscale':.9},
            'record_vector_candidates': [[10.25,20,30], [0,90,0]]})

    def test_known_property_links(self):
        self.assertEqual(canonical('n_explosion_delay'), 0xf912ea8d)
        self.assertEqual(canonical('bundle_not_hide'), 0x3e0f3ca4)

    def test_override_is_whole_vector_and_world_space(self):
        scene={'hash_922b4fc5':100, 'hash_3e692842':200, 'hash_16999a5d':10}
        obj={'hash_3e692842':4, 'hash_29563fd6':15}
        shot={'hash_be60a82b':8}
        p=alignment_pose(self.root,scene,obj,shot)
        self.assertEqual(p['Position'], [10.25,20,38])
        self.assertEqual(p['AnglesPitchYawRoll'], [0,105,0])
        self.assertEqual(p['PositionOffsetSource'], 'shot')
        self.assertEqual(p['AnglesPitchYawRollOffsetSource'], 'object')

    def test_preserve_angle_keeps_position(self):
        p=alignment_pose(self.root,{}, {'preserveangle':1}, {})
        self.assertEqual(p['Position'], [10.25,20,30])
        self.assertIsNone(p['AnglesPitchYawRoll'])

    def test_runtime_tag_cannot_be_baked(self):
        p=alignment_pose(self.root,{}, {}, {'aligntargettag':'tag_origin'})
        self.assertIsNone(p['Position'])
        self.assertIsNone(p['AnglesPitchYawRoll'])

    def test_bad_record_cannot_publish_pose(self):
        root=root_transform({'Properties':{'origin':[0,0,0], 'angles':[0,0,0]},
            'record_vector_candidates':[[100,0,0],[0,0,0]]})
        self.assertFalse(root['RecordAgreesWithRoundedProperties'])
        self.assertIsNone(alignment_pose(root,{}, {}, {})['Position'])

if __name__ == '__main__': unittest.main()
