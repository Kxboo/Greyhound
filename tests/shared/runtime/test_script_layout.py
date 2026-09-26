"""Guard script relocation, direct entry points and maintained reference paths."""
import ast
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[3]
TOOLS = ROOT / 'tools'


def test_scripts_have_game_or_shared_ownership_and_unique_module_names():
    modules = {}
    for script in TOOLS.rglob('*.py'):
        relative = script.relative_to(TOOLS)
        assert relative.as_posix() == 'tool_bootstrap.py' or relative.parts[0] in {
            'cold_war', 'black_ops_4', 'black_ops_3', 'shared'}
        assert script.stem not in modules, (script, modules.get(script.stem))
        modules[script.stem] = script
        ast.parse(script.read_text(encoding='utf-8'))


@pytest.mark.parametrize('relative', [
    'cold_war/capture/organize_cw_placements.py',
    'black_ops_4/capture/package_bo4_terrain.py',
    'black_ops_3/reference/build_reference.py',
    'shared/runtime/export_brushes.py',
    'shared/capture/organize_export.py',
    'black_ops_4/brushes/build_bo4_brush_hulls.py',
    'black_ops_4/brushes/decode_bo4_model_physics.py',
    'black_ops_4/brushes/decode_bo4_physgeom_samples.py',
    'black_ops_4/brushes/export_bo4_model_physics_map.py',
    'black_ops_4/brushes/export_bo4_radiant_brushes.py',
    'cold_war/brushes/export_cw_full_brush_map.py',
    'cold_war/brushes/build_cw_bo3_brush_prototype.py',
])
def test_isolated_entry_point_from_unrelated_directory(relative, tmp_path):
    result = subprocess.run([sys.executable, '-I', str(TOOLS / relative), '--help'],
                            cwd=tmp_path, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert 'usage:' in result.stdout.lower()


@pytest.mark.parametrize('old_path,new_module,names', [
    ('cold_war/brushes/cw_exact_vertex_hull.py', 'exact_geometry', ('sub', 'cross', 'dot', 'exact_hull')),
    ('cold_war/brushes/cw_brush_hull.py', 'exact_geometry', ('checked_hull',)),
    ('cold_war/brushes/exact_cw_brush_halfspaces.py', 'exact_geometry', ('reconstruct_exact',)),
    ('cold_war/brushes/cw_canonical_map_planes.py', 'bo3_map_planes', ('CanonicalPlaneWriter',)),
    ('cold_war/brushes/export_cw_full_brush_map.py', 'exact_geometry', ('hull_planes',)),
    ('cold_war/brushes/export_cw_full_brush_map.py', 'bo3_map_planes', ('face_text',)),
    ('cold_war/brushes/build_cw_bo3_brush_prototype.py', 'bo3_map_planes', ('read_map_planes',)),
    ('shared/brushes/cw_export_layout.py', 'cw_export_layout_impl', ('map_name', 'publish', 'reserve_export_directory')),
    ('shared/brushes/material_comparison_report.py', 'cw_material_comparison_report', ('QUERY_FLAGS', 'cell', 'reports')),
])
def test_old_tool_paths_forward_to_canonical_modules_from_other_directory(old_path, new_module, names, tmp_path):
    program = (
        'import importlib, pathlib, runpy; '
        f'old = runpy.run_path({str(TOOLS / old_path)!r}); '
        f'canonical = importlib.import_module({new_module!r}); '
        f'assert all(old[name] is getattr(canonical, name) for name in {names!r}); '
        'new = runpy.run_path(canonical.__file__); '
        f'assert all(name in new for name in {names!r})'
    )
    result = subprocess.run([sys.executable, '-I', '-c', program], cwd=tmp_path,
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
