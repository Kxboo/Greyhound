
import sys as _tool_sys
from pathlib import Path as _ToolPath
REPO_ROOT = next(p for p in _ToolPath(__file__).resolve().parents if (p / "build-greyhound.ps1").is_file())
TOOLS_ROOT = REPO_ROOT / "tools"
_tool_sys.path.insert(0, str(TOOLS_ROOT))
import tool_bootstrap as _tool_bootstrap
_tool_bootstrap.activate(TOOLS_ROOT / "tool_bootstrap.py")
import json
from pathlib import Path
import struct
import sys

import pytest

from export_cross_map_cw_geometry import write_float_mesh_obj


def triangle_capture(root, packed):
    # One real float3/byte-index group using pointers into a captured allocation.
    raw = bytearray(592)
    base = 0x20000
    bounds = [0., 0., 0., 1., 1., 0.]
    struct.pack_into('<6f', raw, 336, *bounds)
    struct.pack_into('<4I', raw, 376, 3, 3, 1, 1)
    for offset, target in ((472, 520), (480, 556), (504, 560)):
        struct.pack_into('<Q', raw, offset, base + target)
    struct.pack_into('<9f', raw, 520, 0, 0, 0, 1, 0, 0, 0, 1, 0)
    raw[556:559] = bytes((0, 1, 2))
    struct.pack_into('<6fQ', raw, 560, *bounds, (1 << 49) | (7 << 54))
    name = 'triangle.bin'
    if packed:
        (root / 'packed.bin').write_bytes(b'prefix' + raw + b'suffix')
        (root / 'evidence.json').write_text(json.dumps({'storage': {
            name: {'file': 'packed.bin', 'offset': 6, 'bytes': len(raw)}}}))
    else:
        (root / name).write_bytes(raw)
    return {'name_hash': '0x123', 'mins': bounds[:3], 'maxs': bounds[3:],
            'payload': {'file': name, 'address': hex(base), 'allocated_bytes': len(raw)}}


@pytest.mark.parametrize('packed', [False, True])
def test_triangle_export_preserves_vertices_faces_and_filter_group(tmp_path, packed):
    model = triangle_capture(tmp_path, packed)
    output = tmp_path / 'output'
    output.mkdir()
    report = write_float_mesh_obj(tmp_path, [model], output)
    lines = (output / 'float-collision-triangles.obj').read_text().splitlines()
    assert [line for line in lines if line.startswith('v ')] == ['v 0 0 0', 'v 1 0 0', 'v 0 1 0']
    assert [line for line in lines if line.startswith('f ')] == ['f 1 2 3']
    assert any(line.endswith('_group0_filter7') for line in lines if line.startswith('g '))
    assert report['models_decoded'] == 1 and report['triangles'] == 1
    assert report['unsupported'] == []


def test_truncated_packed_triangle_capture_fails(tmp_path):
    model = triangle_capture(tmp_path, True)
    (tmp_path / 'packed.bin').write_bytes(b'short')
    with pytest.raises(ValueError, match='truncated packed range'):
        write_float_mesh_obj(tmp_path, [model], tmp_path)
