"""Placement rules verified against the pinned CW scene script consumer."""

# Support direct execution and the isolated packaged Python runtime.
import sys as _tool_sys
from pathlib import Path as _ToolPath
TOOLS_ROOT = next(p for p in _ToolPath(__file__).resolve().parents if (p / "tool_bootstrap.py").is_file())
_tool_sys.path.insert(0, str(TOOLS_ROOT))
import tool_bootstrap as _tool_bootstrap
_tool_bootstrap.activate(__file__)
REPO_ROOT = TOOLS_ROOT.parent
import math

OFFSET_KEYS = {
    'Position': ('hash_922b4fc5', 'hash_3e692842', 'hash_be60a82b'),
    'AnglesPitchYawRoll': ('hash_16999a5d', 'hash_29563fd6', 'hash_eb00c330'),
}

def canonical(name):
    """CW script identifier checksum; used to link known captured property keys."""
    h = 0x4b9ace2f
    for c in name.lower().replace('\\', '/').encode():
        a = (h + c) & 0xffffffff
        a = (a ^ (a << 10)) & 0xffffffff
        h = (a + (a >> 6)) & 0xffffffff
    h = (9 * h) & 0xffffffff
    return (0x8001 * (h ^ (h >> 11))) & 0xffffffff

def vector(value):
    return isinstance(value, list) and len(value) == 3 and all(
        isinstance(v, (int, float)) and math.isfinite(v) for v in value)

def root_transform(entity):
    props = entity['Properties']
    origin, angles = props.get('origin'), props.get('angles')
    record = entity.get('record_vector_candidates', [])
    valid = vector(origin) and vector(angles) and len(record) == 2 and all(vector(v) for v in record)
    if valid:
        valid = all(abs(a-b) <= .501 for a,b in zip(origin, record[0])) and all(
            abs(math.remainder(a-b, 360)) <= .501 for a,b in zip(angles, record[1]))
    return {
        'AuthoredPropertyPosition': origin, 'AuthoredPropertyAnglesPitchYawRoll': angles,
        'RecordPosition': record[0] if len(record) == 2 else None,
        'RecordAnglesPitchYawRoll': record[1] if len(record) == 2 else None,
        'RecordAgreesWithRoundedProperties': bool(valid),
        'ReferencePosition': record[0] if valid else None,
        'ReferenceAnglesPitchYawRoll': record[1] if valid else None,
        'ModelScale': props.get('modelscale', 1),
    }

def alignment_pose(root, scene, obj, shot):
    result = {}
    for label, keys in OFFSET_KEYS.items():
        candidates = [(name, [node.get(k, 0) for k in keys]) for name,node in
                      (('shot', shot), ('object', obj), ('scene', scene))]
        if not all(vector(v) for _,v in candidates):
            raise ValueError('Invalid scene offset vector')
        source, offset = next(((name,v) for name,v in candidates if any(v)), ('scene', candidates[-1][1]))
        base = root['Reference'+label]
        result[label] = [a+b for a,b in zip(base, offset)] if base is not None else None
        result[label+'Offset'] = offset
        result[label+'OffsetSource'] = source
    # Tags refer to a runtime bone pose, even without a separate target entity.
    target = any(node.get(k) is not None for node in (scene, obj, shot)
                 for k in ('aligntarget', 'aligntargettag'))
    if target:
        result['Position'] = None
        result['AnglesPitchYawRoll'] = None
    elif bool(obj.get('preserveangle', 0)):
        result['AnglesPitchYawRoll'] = None
    result['RequiresRuntimeAlignmentTargetOrTag'] = target
    result['RequiresCurrentObjectAngles'] = bool(obj.get('preserveangle', 0))
    result['IsObservedRuntimePose'] = False
    return result
