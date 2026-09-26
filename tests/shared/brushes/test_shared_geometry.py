"""Cross-game geometry retains captured topology and BO3 MAP representation."""
from pathlib import Path
import sys

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'tools'))
import tool_bootstrap
tool_bootstrap.activate(ROOT / 'tools/tool_bootstrap.py')
from exact_geometry import checked_hull, exact_hull, hull_planes, reconstruct_exact
from bo3_map_planes import CanonicalPlaneWriter, read_map_planes


def test_translated_dyadic_hull_retains_duplicate_source_indices_and_volume():
    points = [[4096 + x / 8, -8192 + y / 16, 16384 + z / 32]
              for x in (0, 1) for y in (0, 1) for z in (0, 1)]
    points += [points[0], points[-1], [4096 + 1 / 16, -8192 + 1 / 32, 16384 + 1 / 64]]
    faces, normals, certificate = checked_hull(points)
    assert len(faces) == 12
    assert set(faces.ravel()) == set(range(8))
    assert np.allclose(np.linalg.norm(normals, axis=1), 1)
    assert certificate['volume'] == 1 / 4096
    assert certificate['exact']['duplicate_source_positions'] == 2
    assert certificate['exact']['exact_source_containment']
    planes = hull_planes({'vertices': points, 'faces': faces})
    assert len(planes) == 6
    assert np.max(np.asarray(points) @ planes[:, :3].T - planes[:, 3]) == 0


def test_exact_halfspaces_preserve_repeated_plane_candidates():
    equations = [[1, 0, 0, 1], [-1, 0, 0, 0], [0, 1, 0, 1],
                 [0, -1, 0, 0], [0, 0, 1, 1], [0, 0, -1, 0], [2, 0, 0, 2]]
    mesh = reconstruct_exact(equations)
    assert len(mesh['vertices']) == 8 and len(mesh['faces']) == 6
    assert mesh['volume_rational'] == '1'
    assert mesh['bad_directed_edges'] == 0
    assert any(face['side_candidates'] == [0, 6] for face in mesh['faces'])
    with pytest.raises(ValueError, match='fewer than four vertices'):
        reconstruct_exact(equations + [[1, 0, 0, -1]])


def test_exact_hull_rejects_flat_capture_without_jitter():
    with pytest.raises(ValueError, match='Coplanar or collinear'):
        exact_hull([[0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0]])


def test_canonical_map_plane_text_and_opposite_winding_are_stable():
    writer = CanonicalPlaneWriter()
    planes = np.array([[1., 0., 0., 2.25], [-1., 0., 0., -2.25]])
    lines = writer.lines(planes, np.array([500., 600., 700.]), 'clip')
    suffix = ' clip 64 64 0 0 0 0 lightmap_gray 16384 16384 0 0 0 0'
    assert lines == [
        '( 2.25 0 0 ) ( 2.25 0 8192 ) ( 2.25 8192 0 )' + suffix,
        '( 2.25 0 0 ) ( 2.25 8192 0 ) ( 2.25 0 8192 )' + suffix,
    ]
    assert len(writer.cache) == 1
    assert np.array_equal(np.array(read_map_planes('\n'.join(lines))), planes)
    assert writer.lines(planes, np.zeros(3), 'clip') == lines


def test_export_provenance_tracks_shared_geometry_implementations():
    import hashlib
    from export_cw_radiant_brushes import implementation_hashes
    hashes = implementation_hashes(['cw_exact_vertex_hull.py'])
    for relative in ('shared/brushes/exact_geometry.py', 'shared/brushes/bo3_map_planes.py'):
        assert hashes[relative] == hashlib.sha256((ROOT / 'tools' / relative).read_bytes()).hexdigest()
    assert hashes['cw_exact_vertex_hull.py'] == hashlib.sha256(
        (ROOT / 'tools/cold_war/brushes/cw_exact_vertex_hull.py').read_bytes()).hexdigest()
