"""Model clip export policy; physics behavior remains an unverified research input."""

# Support direct execution and the isolated packaged Python runtime.
import sys as _tool_sys
from pathlib import Path as _ToolPath
TOOLS_ROOT = next(p for p in _ToolPath(__file__).resolve().parents if (p / "tool_bootstrap.py").is_file())
_tool_sys.path.insert(0, str(TOOLS_ROOT))
import tool_bootstrap as _tool_bootstrap
_tool_bootstrap.activate(__file__)
REPO_ROOT = TOOLS_ROOT.parent
from cw_collision_role_policy import REFERENCE_MATERIAL, reference_reason, reference_properties

POLICY = 'source_gated_model_collision_v3'

def apply(assignment, reference):
    source = assignment['decision']
    materials = {m['name']: m['properties'] for m in reference['materials']}
    old = materials[source['material']]
    physics = source['material'] == 'clip_physics' or old.get('physicsGeom') == '1'
    clip = source['material'] == 'nosight_noclip' or 'clip' in source['material'].split('_')
    reason = reference_reason(assignment, old if clip else {})
    if reason:
        reference_properties(reference)
        return dict(material=REFERENCE_MATERIAL, source_material=source['material'],
                    status='nonblocking_source_reference', prefab_role='reference_brushes',
                    physics_fallback=False, policy=POLICY, reason=reason)
    if not physics:
        return dict(material=source['material'],status='existing_model_clip_assignment',
                    prefab_role='model_collision', physics_fallback=False,policy=POLICY)
    surface = source.get('preferred_source_surface')
    candidate = str(surface) + '_clip'
    props = materials.get(candidate, {})
    if not (surface and props.get('surfaceType') == surface and
            props.get('playerClip') == '1' and props.get('noDraw') == '1'):
        candidate = 'clip';props = materials[candidate]
    assert props.get('playerClip') == '1' and props.get('noDraw') == '1'
    reference_properties(reference)
    return dict(material=REFERENCE_MATERIAL,source_material=source['material'],
                collision_candidate_material=candidate, prefab_role='reference_brushes',
                source_surface=surface,collision_candidate_surface_type=props.get('surfaceType'),
                physics_fallback=True,physics_conversion_verified=False,
                status='unverified_physics_nonblocking_reference',policy=POLICY,
                reason='Physics behavior is not reconstructed. The proposed player clip is recorded but excluded from model collision.')
