
import sys as _tool_sys
from pathlib import Path as _ToolPath
REPO_ROOT = next(p for p in _ToolPath(__file__).resolve().parents if (p / "build-greyhound.ps1").is_file())
TOOLS_ROOT = REPO_ROOT / "tools"
_tool_sys.path.insert(0, str(TOOLS_ROOT))
import tool_bootstrap as _tool_bootstrap
_tool_bootstrap.activate(TOOLS_ROOT / "tool_bootstrap.py")
from pathlib import Path
import sys

import pytest

from bo3_material_definitions import materials


def test_cross_file_forward_inheritance_preserves_overrides_and_provenance(tmp_path):
    child = tmp_path / 'child.gdt'
    base = tmp_path / 'base.gdt'
    child.write_text('{\n"catwalk" ["player"] {"surfaceType" "metalcatwalk"}\n'
                     '"player" ["metal"] {"aiClip" "0"}\n}')
    base.write_text('{"metal" ("material.gdf") {"surfaceType" "metal" "playerClip" "1" "aiClip" "1"}}')
    rows = {r['name']: r for r in materials([child, base], tmp_path)}
    assert rows['catwalk']['properties'] == {'surfaceType': 'metalcatwalk', 'playerClip': '1', 'aiClip': '0'}
    assert rows['metal']['properties']['aiClip'] == '1'
    assert rows['catwalk']['inheritance_chain'] == ['metal', 'player']
    assert rows['catwalk']['source'] == 'child.gdt'
    assert rows['catwalk']['line'] == 2


@pytest.mark.parametrize('text,reason', [
    ('"a" ["b"] {} "b" ["a"] {}', 'cycle'),
    ('"a" ["absent"] {}', 'Missing parent'),
    ('"a" ("material.gdf") {} "a" ("material.gdf") {}', 'Duplicate'),
])
def test_invalid_material_graph_is_rejected(tmp_path, text, reason):
    path = tmp_path / 'bad.gdt'
    path.write_text('{' + text + '}')
    with pytest.raises(ValueError, match=reason):
        materials([path])


def test_commented_out_definitions_are_not_candidates(tmp_path):
    path = tmp_path / 'commented.gdt'
    path.write_text('// "fake" ("material.gdf") {}\n'
                    '/* "fake2" ("material.gdf") {} */\n'
                    '"real" ("material.gdf") {"colorMap" "tools//image"}')
    rows = materials([path])
    assert len(rows) == 1
    assert rows[0]['name'] == 'real'
    assert rows[0]['line'] == 3
    assert rows[0]['properties']['colorMap'] == 'tools//image'
