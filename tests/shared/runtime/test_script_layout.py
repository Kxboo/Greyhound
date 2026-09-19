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
])
def test_isolated_entry_point_from_unrelated_directory(relative, tmp_path):
    result = subprocess.run([sys.executable, '-I', str(TOOLS / relative), '--help'],
                            cwd=tmp_path, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert 'usage:' in result.stdout.lower()
