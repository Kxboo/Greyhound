"""Model clip export policy; physics behavior remains an unverified research input."""

# Support direct execution and the isolated packaged Python runtime.
import sys as _tool_sys
from pathlib import Path as _ToolPath
TOOLS_ROOT = next(p for p in _ToolPath(__file__).resolve().parents if (p / "tool_bootstrap.py").is_file())
_tool_sys.path.insert(0, str(TOOLS_ROOT))
import tool_bootstrap as _tool_bootstrap
_tool_bootstrap.activate(__file__)
REPO_ROOT = TOOLS_ROOT.parent
POLICY = 'ordinary_model_clips_physics_unverified_v1'

def apply(assignment, reference):
    source = assignment['decision']
    materials = {m['name']: m['properties'] for m in reference['materials']}
    old = materials[source['material']]
    physics = source['material'] == 'clip_physics' or old.get('physicsGeom') == '1'
    if not physics:
        return dict(material=source['material'],status='existing_model_clip_assignment',
                    physics_fallback=False,policy=POLICY)
    surface = source.get('preferred_source_surface')
    candidate = str(surface) + '_clip'
    props = materials.get(candidate, {})
    if not (surface and props.get('surfaceType') == surface and
            props.get('playerClip') == '1' and props.get('noDraw') == '1'):
        candidate = 'clip';props = materials[candidate]
    assert props.get('playerClip') == '1' and props.get('noDraw') == '1'
    return dict(material=candidate,source_material=source['material'],
                source_surface=surface,bo3_surface_type=props.get('surfaceType'),
                physics_fallback=True,physics_conversion_verified=False,
                status='ordinary_player_clip_fallback',policy=POLICY,
                reason='User-selected static model collision fallback. Source physics behavior is not reconstructed; player blocking is intentionally added.')
