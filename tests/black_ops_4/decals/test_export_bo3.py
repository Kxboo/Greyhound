"""Synthetic native BO3 decal packaging regressions; no game installation needed."""
import hashlib
import json
import math
import re
import struct
import sys
from pathlib import Path

import pytest
from PIL import Image


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'tools/black_ops_4/decals'))
import export_bo3 as bo3


def record(index, pointer=0x1234, priority=15, yaw=0, feather=(1, 1, 1)):
    raw = bytearray(bo3.RECORD_BYTES)
    axes = bo3.basis([0, yaw, 0])
    origin = [10.0+index*300, 20.0, 30.0]
    matrix = [[axes[j][i] for j in range(3)] for i in range(3)]
    translation = [-sum(origin[i]*matrix[i][j] for i in range(3)) for j in range(3)]
    struct.pack_into('<12f', raw, 0x0C, *(axes[0]+axes[1]+axes[2]+origin))
    struct.pack_into('<12f', raw, 0x3C, *(matrix[0]+matrix[1]+matrix[2]+translation))
    struct.pack_into('<3f', raw, 0x6C, 1, 98, 112)
    struct.pack_into('<3f', raw, 0x78, *feather)
    struct.pack_into('<4f', raw, 0x84, 0, 0, .5, .5)
    struct.pack_into('<4f', raw, 0x94, 0, 0, 1, 1)
    struct.pack_into('<4f', raw, 0xA4, 0, 1, 0, 1)
    struct.pack_into('<Q', raw, 0xB8, pointer)
    struct.pack_into('<I', raw, 0xC8, priority)
    struct.pack_into('<f', raw, 0xD0, .5)
    return bytes(raw)


@pytest.fixture
def capture(tmp_path, monkeypatch):
    source = tmp_path / 'capture'
    source.mkdir()
    bo3_root = tmp_path / 'BO3_is_not_installed'
    shader = b'DXBC synthetic verified family for a focused test'
    (source / 'shader.dxbc').write_bytes(shader)
    monkeypatch.setattr(bo3, 'SHADER_ID', hashlib.sha1(shader).hexdigest()[:16])
    constants = [0.0]*80
    constants[1:4] = [.074213676]*3
    constants[10:14] = [1.0]*4
    (source / 'cbuffer.bin').write_bytes(struct.pack('<80f', *constants))
    definition = bytearray(32)
    struct.pack_into('<2f', definition, 12, 1, 1)
    images = []
    for semantic, filename, color in [('0xA0AB1041','color.png',(100,50,20,200)),
                                      ('0x34D849D5','reveal.png',(60,60,60,255)),
                                      ('0x199A03D3','white.png',(255,255,255,255))]:
        Image.new('RGBA', (8, 8), color).save(source / filename)
        images.append({'semantic': semantic, 'file': filename, 'width': 8, 'height': 8,
                       'texture_def': definition.hex()})
    atlas = Image.new('RGBA', (16, 16))
    atlas.putdata([(i % 256, 0, 0, 255) for i in range(256)])
    atlas.save(source / 'atlas.png')
    (source / 'volume_decals.bin').write_bytes(record(0)+record(1, yaw=40))
    material = {'material': '0x1234', 'hash': '0x4694BEDE07186AD', 'name': 'sample_stain',
                'decals': 2, 'pixel_shader': 'shader.dxbc', 'cbuffer': 'cbuffer.bin',
                'images': images, 'blend_words': [f'0x{word:08X}' for word in bo3.EXPECTED_BLEND],
                'pass_arguments': ([{'kind':'texture','hash':f'0x{key:08X}','slot':slot,'count':count}
                                    for key, slot, count in sorted(bo3.TEXTURE_BINDINGS)] +
                                   [{'kind':'sampler','hash':f'0x{key:08X}','slot':slot,'count':count}
                                    for key, slot, count, _ in sorted(bo3.SAMPLER_BINDINGS)]),
                'samplers': [{'hash':f'0x{key:08X}','state':f'0x{state:X}'}
                             for key, _, _, state in sorted(bo3.SAMPLER_BINDINGS)]}
    data = {'schema': bo3.SCHEMA, 'material_pointer': '0x1234', 'include_placements': True,
            'volume_decals': {'status':'captured','selected_material':'0x1234',
                              'count':2,'record_bytes':bo3.RECORD_BYTES,'records_scope':'full_world',
                              'selected_source_indices':[0,1], 'file':'volume_decals.bin',
                              'atlas':{'file':'atlas.png','width':16,'height':16},
                              'materials':[material]}}
    path = source / 'decal_capture.json'
    path.write_text(json.dumps(data))
    return path, bo3_root, data


def test_two_native_placements_and_portable_gdt(capture, tmp_path):
    path, bo3_root, _ = capture
    assert not bo3_root.exists()
    prepared = bo3.prepare(path, bo3_root, True)
    assert len(prepared['authored']) == 2 and not prepared['omitted']
    result = bo3.package(prepared, tmp_path / 'overlay', bo3_root, True)
    assert result['complete'] and result['placement_exported'] == 2
    gdt = Path(result['gdt']).read_text()
    prefab = Path(result['prefab']).read_text()
    assert '"baseImage" "texture_assets\\\\black_ops_4\\\\decals\\\\' in gdt
    assert '"materialType" "lit_decal_diffuse_reveal"' in gdt
    assert '"normalMap" ""' in gdt
    assert 'C:' not in gdt and 'D:' not in gdt
    assert prefab.count('"classname" "misc_volume_decal"') == 2
    assert '// entity 1: source decal index 0' in prefab
    assert '// entity 2: source decal index 1' in prefab
    assert prefab.count('"decalLayerSort" "Grunge"') == 2
    assert prefab.count('"decalLayerSortEnum" "14"') == 2
    assert '"origin" "310 20 30"' in prefab
    assert '"revealDataSize" "8x8"' in prefab
    assert Path(result['package_root'], 'texture_assets/black_ops_4/decals/i_bo4_decal_4694bede07186ad_c.png').is_file()
    report = json.loads(Path(result['report']).read_text())
    assert report['placement_omitted'] == 0 and not report['bo3_in_game_verified']
    assert report['bundled_template']['canonical_sha256'] == bo3.TEMPLATE_SHA256


def test_bundled_template_identity_ignores_git_line_endings(capture, tmp_path, monkeypatch):
    path, _, _ = capture
    normalized = bo3.TEMPLATE_FILE.read_bytes().replace(b'\r\n', b'\n')
    for newline in (b'\n', b'\r\n'):
        template = tmp_path / 'bo3_stock_template_v1.json'
        template.write_bytes(normalized.replace(b'\n', newline))
        monkeypatch.setattr(bo3, 'TEMPLATE_FILE', template)
        assert bo3.prepare(path)['template']['schema'] == 'greyhound-bo3-stock-template-v1'


def test_cli_arguments_need_no_bo3_installation(capture, tmp_path, capsys):
    path, bo3_root, _ = capture
    assert not bo3_root.exists()
    output = tmp_path / 'cli_overlay'
    exit_code = bo3.main(['--capture', str(path), '--output', str(output), '--placements'])
    assert exit_code == 0
    result = json.loads(capsys.readouterr().out)
    assert result['placement_exported'] == 2 and result['complete']
    assert (output / 'source_data/black_ops_4/decals').is_dir()


@pytest.mark.parametrize('contents, message', [(None, 'Missing bundled'), (b'{"schema":"bad"}', 'Corrupt bundled')])
def test_missing_or_corrupt_bundled_template_fails_before_output(capture, tmp_path, monkeypatch, contents, message):
    path, _, _ = capture
    template = tmp_path / 'bo3_stock_template_v1.json'
    if contents is not None:
        template.write_bytes(contents)
    monkeypatch.setattr(bo3, 'TEMPLATE_FILE', template)
    with pytest.raises(ValueError, match=message):
        bo3.prepare(path)
    assert not (tmp_path / 'overlay').exists()


def test_asset_only_does_not_require_world_records(capture, tmp_path):
    path, bo3_root, data = capture
    data['include_placements'] = False
    volume = data['volume_decals']
    volume['records_scope'] = 'omitted'
    del volume['file'], volume['atlas']
    path.write_text(json.dumps(data))
    (path.parent / 'volume_decals.bin').unlink()
    prepared = bo3.prepare(path, bo3_root, False)
    result = bo3.package(prepared, tmp_path/'overlay', bo3_root, False)
    assert result['status'] == 'assets_only' and result['prefab'] is None
    assert result['selected_count'] == 2 and result['placement_exported'] == 0


@pytest.mark.parametrize('mutation, expected', [
    (lambda data: data['volume_decals']['materials'][0].update(pixel_shader='missing.dxbc'), 'Missing decal shader'),
    (lambda data: data['volume_decals']['materials'][0]['images'][0].update(file='../escape.png'), 'Unsafe color image path'),
    (lambda data: data['volume_decals']['materials'][0].update(blend_words=['0x0']*4), 'blend state'),
    (lambda data: data['volume_decals']['materials'][0]['pass_arguments'][0].update(slot=2), 'texture bindings'),
    (lambda data: data['volume_decals']['materials'][0]['samplers'][0].update(state='0x0'), 'sampler bindings'),
])
def test_preflight_rejects_bad_dependencies(capture, tmp_path, mutation, expected):
    path, bo3_root, data = capture
    mutation(data)
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match=expected):
        bo3.prepare(path, bo3_root, False)
    assert not (tmp_path / 'overlay').exists()


def test_wrong_shader_fails_even_when_dxbc(capture):
    path, bo3_root, _ = capture
    (path.parent / 'shader.dxbc').write_bytes(b'DXBC another shader')
    with pytest.raises(ValueError, match='Unsupported decal shader'):
        bo3.prepare(path, bo3_root, False)


def test_unrepresentable_placement_is_reported_partial(capture, tmp_path):
    path, bo3_root, _ = capture
    (path.parent / 'volume_decals.bin').write_bytes(record(0)+record(1, priority=23))
    prepared = bo3.prepare(path, bo3_root, True)
    result = bo3.package(prepared, tmp_path/'overlay', bo3_root, True)
    assert result['status'] == 'partial' and not result['complete']
    assert result['placement_exported'] == 1 and result['placement_omitted'] == 1
    report = json.loads(Path(result['report']).read_text())
    assert report['omitted_placements'][0]['source_index'] == 1
    assert 'priority' in report['omitted_placements'][0]['reason']
    assert 'PARTIAL:' in Path(result['package_root'], 'README.txt').read_text()


def test_native_decal_layers_preserve_source_priority(capture):
    path, bo3_root, data = capture
    data['volume_decals']['selected_source_indices'] = [0, 1]
    path.write_text(json.dumps(data))
    (path.parent / 'volume_decals.bin').write_bytes(record(0, priority=2)+record(1, priority=3))
    prepared = bo3.prepare(path, bo3_root, True)
    assert not prepared['omitted']
    assert [(p['decalLayerSort'], p['decalLayerSortEnum']) for _, p in prepared['authored']] == [
        ('Damage - New', '1'), ('Paper', '2')]


def test_runtime_feather_threshold_converts_to_bo3_editor_distance(capture):
    path, bo3_root, _ = capture
    (path.parent / 'volume_decals.bin').write_bytes(
        record(0, feather=(.5, 1, .25)) + record(1, feather=(1, 1, 1)))
    prepared = bo3.prepare(path, bo3_root, True)
    assert not prepared['omitted']
    first = prepared['authored'][0][1]
    assert [first['edgeFeather'+axis] for axis in 'XYZ'] == ['0.5', '0', '0.75']
    assert [prepared['authored'][1][1]['edgeFeather'+axis] for axis in 'XYZ'] == ['0', '0', '0']


def test_out_of_bounds_feather_is_still_omitted(capture):
    path, bo3_root, _ = capture
    (path.parent / 'volume_decals.bin').write_bytes(
        record(0, feather=(-.1, 1, 1)) + record(1))
    prepared = bo3.prepare(path, bo3_root, True)
    assert len(prepared['authored']) == 1
    assert prepared['omitted'][0]['source_index'] == 0
    assert 'outside native BO3 editor bounds' in prepared['omitted'][0]['reason']


def test_cod_angle_transform_roundtrip_and_output_containment(capture):
    for angles in ([0,0,0], [0,40,0], [20,310,15], [270,0,0],
                   [90,35,20], [270,45,20]):
        recovered = bo3.cod_angles(bo3.basis(angles))
        rebuilt = bo3.basis(recovered)
        assert max(abs(a-b) for row_a, row_b in zip(bo3.basis(angles), rebuilt)
                   for a, b in zip(row_a, row_b)) < 1e-8
    path, bo3_root, _ = capture
    with pytest.raises(ValueError, match='outside the BO3 installation'):
        bo3.package(bo3.prepare(path, bo3_root, False), bo3_root/'source_data/output', bo3_root, False)
