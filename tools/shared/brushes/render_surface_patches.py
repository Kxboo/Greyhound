"""UV patch writer ported from TerrainReconstructor tools/bo3/brush_geometry.py.

Explicit corner attributes are preserved; this module does not recover UVs.
"""
import re
import numpy as np


def render_surface_patches(surface):
    """Preserve a verified convex render polygon, its UVs and vertex colors.

    Triangles become three nondegenerate quads with linearly interpolated
    attributes. Quads remain one patch; larger convex faces use a triangle fan.
    Collision belongs to the separately reconstructed native solids.
    """
    xyz = np.asarray(surface['vertices'], dtype=float)
    uv = np.asarray(surface['uv'], dtype=float)
    size = np.asarray(surface['texture_size'], dtype=float)
    material = surface['material']
    if (xyz.ndim != 2 or xyz.shape[1] != 3 or len(xyz) < 3 or uv.shape != (len(xyz), 2)
            or size.shape != (2,) or np.any(size <= 0)
            or not np.isfinite(xyz).all() or not np.isfinite(uv).all() or not np.isfinite(size).all()
            or not re.fullmatch(r'[A-Za-z0-9_/-]+', material)):
        raise ValueError('Invalid render surface geometry/material/UVs')
    color = np.asarray(surface.get('colors', [[255, 255, 255, 255]] * len(xyz)), dtype=float)
    if color.shape != (len(xyz), 4) or not np.isfinite(color).all() or np.any((color < 0) | (color > 255)):
        raise ValueError('Invalid vertex colors')
    normal = np.cross(xyz[1] - xyz[0], xyz[2] - xyz[0]); length = np.linalg.norm(normal)
    if length < 1e-10:
        raise ValueError('Degenerate render surface')
    normal /= length
    if abs((xyz - xyz[0]) @ normal).max() > 1e-6:
        raise ValueError('Render polygon is not planar; supply source triangles')
    turns = [np.dot(np.cross(xyz[(i+1)%len(xyz)] - xyz[i], xyz[(i+2)%len(xyz)] - xyz[(i+1)%len(xyz)]), normal)
             for i in range(len(xyz))]
    if min(turns) < -1e-9:
        raise ValueError('Render polygon is not convex; supply source triangles')
    # CoD mesh cell triangle order: (next-row first, first-row second,
    # first-row first), then (next-row first, next-row second, first-row second).
    if len(xyz) == 4:
        pieces = [[0, 3, 1, 2]]
    else:
        positions, coords, colors = list(xyz), list(uv), list(color)
        pieces = []
        def interpolate(ids):
            index = len(positions)
            positions.append(xyz[ids].mean(0)); coords.append(uv[ids].mean(0)); colors.append(color[ids].mean(0))
            return index
        for i in range(1, len(xyz)-1):
            triangle = [0, i, i+1]
            center = interpolate(triangle)
            midpoints = [interpolate([triangle[j], triangle[(j+1)%3]]) for j in range(3)]
            for j in range(3):
                # Polygon [corner, following midpoint, center, preceding midpoint].
                pieces.append([triangle[j], midpoints[(j-1)%3], midpoints[j], center])
        xyz, uv, color = np.array(positions), np.array(coords), np.array(colors)
    axis_u = np.cross(normal, np.eye(3)[np.argmin(abs(normal))]); axis_u /= np.linalg.norm(axis_u)
    axis_v = np.cross(normal, axis_u)
    lightmap = (xyz - xyz[0]) @ np.array([axis_u, axis_v]).T / 16
    for indices in pieces:
        lines = ['{', 'mesh', '{', 'contents nonColliding;', 'toolFlags;', material,
                 'lightmap_gray', '2 2 16 8']
        for row in (indices[:2], indices[2:]):
            lines.append('(')
            for i in row:
                p = ' '.join(format(float(v), '.17g') for v in xyz[i])
                t = ' '.join(format(float(v), '.17g') for v in uv[i] * size)
                c = ' '.join(str(int(round(v))) for v in color[i])
                # New target lightmap projection; original baked lighting is not recovered.
                lm = ' '.join(format(float(v), '.17g') for v in lightmap[i])
                lines.append(f'v {p} c {c} t {t} {lm}')
            lines.append(')')
        yield '\n'.join(lines + ['}', '}']) + '\n'
