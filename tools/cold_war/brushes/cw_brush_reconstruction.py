"""Certified brush/face reconstruction, using n dot p <= d halfspaces.

Planes remain independent of render faces. A face's UVs belong to its corners;
collision materials do not imply a render material or a texture projection.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.spatial import ConvexHull, QhullError


@dataclass
class Solid:
    vertices: np.ndarray
    planes: np.ndarray

    @classmethod
    def from_arrays(cls, vertices, planes):
        v, e = np.asarray(vertices, dtype=float), np.asarray(planes, dtype=float)
        if (v.ndim != 2 or v.shape[1] != 3 or len(v) < 4 or
                e.ndim != 2 or e.shape[1] != 4 or len(e) < 4 or
                not np.isfinite(v).all() or not np.isfinite(e).all()):
            raise ValueError("Invalid solid arrays")
        if np.max(np.abs(np.linalg.norm(e[:, :3], axis=1) - 1)) > 1e-7:
            raise ValueError("Expected unit plane normals")
        if np.max(v @ e[:, :3].T - e[:, 3]) > 1e-6:
            raise ValueError("Vertices outside solid planes")
        return cls(v, e)

    def volume(self):
        return float(ConvexHull(self.vertices - self.vertices.mean(0)).volume)

    def transformed(self, rotation, scale, origin):
        r, o = np.asarray(rotation, dtype=float), np.asarray(origin, dtype=float)
        if (r.shape != (3, 3) or o.shape != (3,) or not np.isfinite(r).all()
                or not np.isfinite(o).all() or not np.isfinite(scale) or scale <= 0
                or not np.allclose(r @ r.T, np.eye(3), atol=1e-5, rtol=0)
                or np.linalg.det(r) < 0):
            raise ValueError("Invalid rigid transform / uniform scale")
        linear = r * scale
        n = self.planes[:, :3] @ np.linalg.inv(linear)
        equations = np.column_stack((n, self.planes[:, 3] + n @ o))
        equations /= np.linalg.norm(n, axis=1)[:, None]
        return Solid.from_arrays(self.vertices @ linear.T + o, equations)


def face_polygon(solid, plane, tolerance=1e-6):
    """Order the convex face boundary in an outward winding, near its origin."""
    n, d = plane[:3], plane[3]
    vertices = solid.vertices[np.abs(solid.vertices @ n - d) <= tolerance]
    if len(vertices) < 3:
        raise ValueError("Plane has fewer than three incident vertices")
    center = vertices.mean(0)
    u = np.cross(n, np.eye(3)[np.argmin(abs(n))]); u /= np.linalg.norm(u)
    w = np.cross(n, u)
    xy = (vertices - center) @ np.array([u, w]).T
    try:
        hull = ConvexHull(xy)
    except QhullError as error:
        raise ValueError("Plane has no nonzero-area polygon") from error
    polygon = vertices[hull.vertices]
    # Remove interpolation noise normal to the supplied support plane.
    polygon = polygon - (polygon @ n - d)[:, None] * n
    return polygon, float(hull.volume)


def recombine_partition(parts, max_faces=32):
    """Recombine an upstream-certified disjoint convex partition when possible.

    Only supplied support equations are retained. No new hull equations, cuts,
    simplification, cross-brush merging or rounding of plane keys is used.
    The caller must supply a previously validated partition of ONE source brush.
    """
    if not 4 <= max_faces <= 64:
        raise ValueError("Brush face budget must be between 4 and 64")
    if len(parts) == 1:
        return parts, dict(merged=False, reason="already_one_piece")
    vertices = np.unique(np.vstack([p.vertices for p in parts]), axis=0)
    planes = np.unique(np.vstack([p.planes for p in parts]), axis=0)
    supports = planes[np.max(vertices @ planes[:, :3].T - planes[:, 3], axis=0) <= 1e-7]
    if len(supports) > max_faces or len(supports) < 4:
        return parts, dict(merged=False, reason="support_plane_budget", support_planes=len(supports))
    merged = Solid.from_arrays(vertices, supports)
    try:
        area = 0.
        face_volume = 0.
        center = vertices.mean(0)
        for e in supports:
            _, a = face_polygon(merged, e, tolerance=1e-7)
            area += a
            face_volume += a * (e[3] - e[:3] @ center) / 3
        source_volume = sum(p.volume() for p in parts)
        hull_volume = merged.volume()
    except (ValueError, QhullError):
        return parts, dict(merged=False, reason="face_or_volume_validation")
    relative = max(abs(hull_volume - source_volume), abs(face_volume - source_volume)) / source_volume
    if relative > 1e-8:
        return parts, dict(merged=False, reason="union_volume_mismatch", relative_volume_error=relative)
    return [merged], dict(merged=True, original_pieces=len(parts), output_pieces=1,
                         source_volume=source_volume, volume=hull_volume,
                         relative_volume_error=relative, support_planes=len(supports),
                         area=area, method="reuse exterior planes of certified convex partition")


def compact_partition(parts, max_faces=32):
    """Also recombine convex adjacent subsets when a whole brush exceeds budget."""
    if any(len(p.planes) > max_faces for p in parts):
        raise ValueError('Face budget is below the existing partition; this pass does not introduce new cuts')
    whole, info = recombine_partition(parts, max_faces)
    if len(whole) == 1:
        return whole, info
    active = dict(enumerate(parts)); next_id = len(active)
    merges = []; tried = set()
    while True:
        owners = {}
        for key, solid in active.items():
            for e in solid.planes:
                owners.setdefault(tuple(e), []).append(key)
        pairs = set()
        for equation, ids in owners.items():
            for a in ids:
                for b in owners.get(tuple(-x for x in equation), []):
                    if a != b:
                        pairs.add(tuple(sorted((a, b))))
        changed = False
        for a, b in sorted(pairs, key=lambda p: (len(active[p[0]].planes) + len(active[p[1]].planes), p)):
            if (a, b) in tried or a not in active or b not in active:
                continue
            tried.add((a, b))
            combined, check = recombine_partition([active[a], active[b]], max_faces)
            if len(combined) == 1:
                del active[a], active[b]
                active[next_id] = combined[0]; next_id += 1
                merges.append(check); changed = True
        if not changed:
            break
    result = list(active.values())
    return result, dict(merged=bool(merges), original_pieces=len(parts), output_pieces=len(result),
                        whole_brush=info, merges=merges,
                        max_relative_volume_error=max((float(m['relative_volume_error']) for m in merges), default=0.))


def reconstruct_parts(parts, certificate, max_faces=32):
    """Only compact certified halfspace partitions, with a compiler-tested budget."""
    if not 4 <= max_faces <= 32:
        raise ValueError('Reconstruction face budget must be between 4 and 32')
    before = len(parts)
    if before > 1 and (not certificate.get('partitioned') or not certificate.get('cuts')
                       or certificate.get('tetrahedral_fallback_regions')):
        return parts, dict(merged=False, original_pieces=before, output_pieces=before,
                           reason='keep_partition_without_complementary_cut_certificate')
    solids, check = compact_partition([Solid.from_arrays(*p) for p in parts], max_faces)
    check.update(original_pieces=before, output_pieces=len(solids), max_faces=max_faces,
                 additional_simplification_tolerance=0., cross_source_brush_merges=False)
    return [(s.vertices, s.planes) for s in solids], check


def write_face_audit(geometry, staged):
    """Check final MAP readback against the cache and publish ordered corner data.

    This records collision face geometry for QA and future verified render joins.
    It cannot recover original render textures/UVs from collision material flags.
    """
    from collections import Counter
    import hashlib
    import json
    import re
    from build_cw_bo3_brush_prototype import read_map_planes
    from export_cw_district_placements import rotation

    def sha(path):
        with path.open('rb') as stream:
            digest = hashlib.sha256()
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(chunk)
            return digest.hexdigest()

    metadata = json.loads((staged / 'collision_metadata.json').read_text())
    capture_path = geometry.parent / 'normalized' / 'capture.json'
    policy = json.loads((geometry / 'hull-cache-policy.json').read_text())
    if sha(capture_path) != policy['capture_sha256'] or policy['capture_sha256'] != metadata['source_capture_sha256']:
        raise ValueError('Face audit capture/cache identity differs')
    capture = json.loads(capture_path.read_text())
    blocks = {}
    for name in {row['prefab_file'] for row in metadata['rows']}:
        path = (staged / name).resolve()
        if not path.is_relative_to(staged.resolve()):
            raise ValueError('Prefab path escapes staged export')
        blocks[name] = re.findall(r'^// brush (\d+)\n\{\n(.*?)^\}', path.read_text(), re.M | re.S)
    if sum(map(len, blocks.values())) != len(metadata['rows']):
        raise ValueError('Face audit MAP brush coverage differs')
    certificates = {(c['model_index'], c['brush_index']): c for c in metadata['partition_certificates']}
    local = {}; hashes = {}; counts = Counter(); maximum = Counter(); seen = set()
    faces_path = staged / 'brush_faces.jsonl'
    with faces_path.open('w', encoding='utf-8', newline='\n') as stream:
        for row in metadata['rows']:
            key = (row['collision_asset_index'], row['brush_index'])
            if key not in local:
                path = geometry / 'hull-cache' / f'{key[0]}_{key[1]}.json'
                data = json.loads(path.read_text())
                if (data['payload_sha256'] != capture['models'][key[0]]['payload']['sha256']
                        or data['certificate'] != certificates[key]):
                    raise ValueError('Face audit cache certificate/payload differs')
                solids = [Solid.from_arrays(*part) for part in data['parts']]
                vertices = np.vstack([s.vertices for s in solids]); polygons = []
                for solid in solids:
                    faces = []
                    for equation in solid.planes:
                        exterior = float((vertices @ equation[:3] - equation[3]).max()) <= 1e-7
                        try:
                            polygon, area = face_polygon(solid, equation)
                            faces.append(dict(vertices=polygon, area=area, exterior=exterior))
                        except ValueError as error:
                            # A failed polygon remains explicit; never remove its solid/plane.
                            faces.append(dict(vertices=None, area=0., exterior=exterior, error=str(error)))
                    polygons.append(faces)
                local[key] = (solids, polygons); hashes[path.name] = sha(path)
            solids, polygons = local[key]
            piece = row['partition_piece']
            solid = solids[piece].transformed(rotation(row['quaternion_xyzw']),
                                              row['uniform_scale'], row['position'])
            location = (row['prefab_file'], row['prefab_brush_index'])
            if location in seen:
                raise ValueError('Duplicate final prefab brush ordinal')
            seen.add(location)
            comment, block = blocks[location[0]][location[1]]
            materials = re.findall(r'^\s*\(.*\)\s+(\S+)\s+', block, re.M)
            parsed = np.asarray(read_map_planes(block))
            if (int(comment) != row['map_brush_index'] or len(materials) != row['face_count']
                    or set(materials) != {row['assigned_material']} or parsed.shape != solid.planes.shape):
                raise ValueError('Final MAP identity/material/plane count differs')
            drift = float(abs(parsed - solid.planes).max())
            outside = float((solid.vertices @ parsed[:, :3].T - parsed[:, 3]).max())
            if not np.isfinite(parsed).all() or drift > 1e-6 or outside > 1e-6:
                raise ValueError('Final MAP plane/placement readback failed')
            points32 = re.sub(r'\([^)]*\)', lambda m: '( ' + ' '.join(
                format(float(np.float32(float(x))), '.17g') for x in m[0][1:-1].split()) + ' )', block)
            parsed32 = np.asarray(read_map_planes(points32))
            error32 = float(abs(solid.vertices @ (parsed32[:, :3] - solid.planes[:, :3]).T
                                - (parsed32[:, 3] - solid.planes[:, 3])).max())
            if not np.isfinite(error32):
                raise ValueError('Nonfinite compiler float plane readback')
            for name, value in [('serialized_plane_error', drift), ('source_vertex_outside', outside),
                                ('float32_signed_distance_error', error32)]:
                maximum[name] = max(maximum[name], value)
            linear = rotation(row['quaternion_xyzw']) * row['uniform_scale']
            for index, (equation, face) in enumerate(zip(solid.planes, polygons[piece])):
                polygon = face['vertices']
                world = polygon @ linear.T + row['position'] if polygon is not None else None
                # Area from transformed corners preserves measured quaternion roundoff.
                area = float(np.linalg.norm(sum((np.cross(world[i]-world[0], world[i+1]-world[0])
                    for i in range(1, len(world)-1)), np.zeros(3))) / 2) if world is not None else 0.
                entry = dict(source_id=[row['collision_world'], row['instance_index'], *key],
                    partition_piece=piece, map=location[0], prefab_brush_index=location[1],
                    map_brush_index=row['map_brush_index'], face=index, plane=equation.tolist(),
                    material=row['assigned_material'], contents_raw=row['contents_low26'],
                    vertices=world.tolist() if world is not None else None, area=area,
                    exterior=face['exterior'], render_material=None, render_uv=None)
                if world is None:
                    entry['error'] = face['error']; counts['unresolved_polygons'] += 1
                else:
                    counts['ordered_polygons'] += 1
                counts['exterior_faces' if face['exterior'] else 'internal_partition_faces'] += 1
                counts['faces'] += 1
                stream.write(json.dumps(entry, allow_nan=False) + '\n')
            counts['brushes'] += 1
    report = dict(schema='cw-brush-face-audit-v1', status='passed', counts=dict(counts),
        maximum=dict(maximum), source_capture_sha256=policy['capture_sha256'],
        cache_sha256=hashes, all_final_map_brushes_checked=True,
        render_associations='Not captured: collision surface types do not identify render textures or UVs.',
        polygon_status='review_required' if counts['unresolved_polygons'] else 'all_ordered',
        compiler_validated=False, scope='Geometry/corner metadata and serialized plane/material readback; no BO3 compilation or gameplay validation.')
    report_path = staged / 'brush_face_audit.json'
    report_path.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    files = [faces_path, report_path, staged / 'collision_metadata.json']
    return report, {p.name: dict(file='metadata/' + p.name, sha256=sha(p)) for p in files}
