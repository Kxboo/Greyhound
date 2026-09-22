"""Source evidence gates collision membership independently of stock matching."""

POLICY = 'source_gated_collision_roles_v2'
REFERENCE_MATERIAL = 'nodraw_notsolid'
REFERENCE_LAYER = '000_Global/CW_Reference'
QUERY_FLAGS = ('playerClip', 'aiClip', 'vehicleClip', 'utilityClip', 'itemClip',
               'bulletClip', 'missileClip', 'canShootClip', 'aiSightClip', 'physicsGeom')


def integer(value):
    return int(value, 0) if isinstance(value, str) else int(value)


def reference_reason(assignment, properties):
    """An absent/unknown source mask never proves that a shape is non-colliding.

    In particular, CW's unresolved base-solid bit and BO3's nonSolid flag are
    not interchangeable. Query-only mismatches remain references for review;
    that classification does not assert that the CW source was non-colliding.
    """
    if 'contents_raw' not in assignment or 'unknown_contents' not in assignment:
        return None
    if integer(assignment['unknown_contents']):
        return None
    contents = set(assignment.get('named_contents', ()))
    surface = assignment.get('common_surface_flags')
    if contents <= {'nonColliding'}:
        if 'nonColliding' in contents or 'nonSolid' in (surface or ()):
            return 'source_non_solid_without_collision_queries'
        if integer(assignment['contents_raw']) == 0 and surface is None:
            return 'zero_contents_unresolved_surface_reference'
    # Only ordinary clip candidates are passed here, after traversal routing.
    if (properties.get('playerClip') == '1'
            and not contents.intersection({'playerClip', 'solid'})
            and contents):
        return 'fallback_adds_player_collision_to_known_query_mask'
    return None


def reference_properties(reference):
    matches = [m['properties'] for m in reference['materials']
               if m['name'] == REFERENCE_MATERIAL]
    if (len(matches) != 1 or matches[0].get('nonSolid') != '1'
            or matches[0].get('noDraw') != '1'
            or any(matches[0].get(flag, '0') != '0' for flag in QUERY_FLAGS)):
        raise ValueError('Reference material must be stock nodraw/non-solid with no collision queries')
    return matches[0]
