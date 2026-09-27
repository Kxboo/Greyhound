"""Optional saved-data audit of the verified BO4 stain and installed BO3 GDT."""
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'tools/black_ops_4/decals'))
import export_bo3 as bo3


SAVED32_ASSET_SHA256 = {
    'texture_assets/black_ops_4/decals/i_bo4_decal_0adc21290fb94ae_c.png':
        '9b0b82bf84b5c50a381378cc8171632e25bd05e48bb1bef1781abbf5f6be373e',
    'texture_assets/black_ops_4/decals/i_bo4_decal_0adc21290fb94ae_r.png':
        'bcbfe786e27cb9a0b323af356a704e0673a79e6769a1f96e605f49e9e5df97ce',
    'source_data/black_ops_4/decals/bo4_decal_0adc21290fb94ae.gdt':
        'ff40e1e54f18b23df05d0a7625afa30e51957bd72670e9862d1e3e7f19123d88',
    'map_source/_prefabs/black_ops_4/decals/bo4_decal_0adc21290fb94ae.map':
        'c9bab44b796d213286fff7ac3aeaa9c0482edc893091e5e5caabd8b8aef61490',
}


def test_saved_single_decal_material_against_stock_bo3(tmp_path):
    package_name = os.environ.get('GREYHOUND_BO4_PILOT_PACKAGE')
    if not package_name:
        pytest.skip('Set saved BO4 pilot package for this optional audit')
    package = Path(package_name).resolve()
    source = json.loads((package / 'capture/decals/decals.json').read_text())
    original = next(m for m in source['materials'] if m['name'] == 'xmaterial_4694bede07186ad')
    selected = [d['index'] for d in source['decals'] if d['material'] == original['pointer']]
    assert len(selected) == original['decals'] == 795
    capture_root = tmp_path / 'source'
    capture_root.mkdir()

    def saved_file(relative, target):
        source_file = (package / relative).resolve()
        assert source_file.is_relative_to(package) and source_file.is_file()
        shutil.copyfile(source_file, capture_root / target)
        return target

    shader = saved_file(original['pixel_shader']['file'], 'shader.dxbc')
    constants = saved_file(original['cbuffer_file'], 'cbuffer.bin')
    images = []
    for i, image in enumerate(original['images']):
        name = saved_file(image['png_file'], f'image_{i}.png')
        definition = bytearray(32)
        struct.pack_into('<2f', definition, 12, *image['uv_scale'])
        images.append({'semantic': image['raw_semantic'], 'file': name,
                       'width': image['width'], 'height': image['height'],
                       'texture_def': definition.hex()})
    material = {'material': original['pointer'], 'hash': original['hash'],
                'name': original['name'], 'decals': len(selected),
                'pixel_shader': shader, 'cbuffer': constants, 'images': images,
                'blend_words': [b['word'] for b in original['blend']],
                'pass_arguments': original['pass_arguments'],
                'samplers': original['samplers']}
    envelope = {'schema': bo3.SCHEMA, 'material_pointer': original['pointer'],
                'include_placements': False,
                'volume_decals': {'status':'captured', 'selected_material':original['pointer'],
                                  'count':source['count'], 'record_bytes':bo3.RECORD_BYTES,
                                  'records_scope':'omitted','selected_source_indices':selected,
                                  'materials':[material]}}
    capture = capture_root / 'decal_capture.json'
    capture.write_text(json.dumps(envelope))
    prepared = bo3.prepare(capture)
    result = bo3.package(prepared, tmp_path/'bo3_overlay')
    assert result['status'] == 'assets_only' and result['complete']
    assert result['selected_count'] == 795 and result['placement_exported'] == 0
    assert prepared['shader_id'] == bo3.SHADER_ID
    report = json.loads(Path(result['report']).read_text())
    assert len(report['images']) == 2
    assert all((Path(result['package_root']) / image['file']).is_file() for image in report['images'])
    assert not report['bo3_in_game_verified']
    gdt = Path(result['gdt']).read_text()
    assert '"colorTint" "0.301' in gdt and '"alphaRevealRamp" "1"' in gdt
    assert '"baseImage" "texture_assets\\\\black_ops_4' in gdt


def test_saved_vertical_ground_projectors():
    package_name = os.environ.get('GREYHOUND_BO4_PILOT_PACKAGE')
    if not package_name:
        pytest.skip('Set saved BO4 pilot package for this optional placement audit')
    package = Path(package_name).resolve()
    source = json.loads((package / 'capture/decals/decals.json').read_text())
    raw = (package / source['records_file']).read_bytes()
    with Image.open(package / source['atlas']['png_file']) as atlas:
        for index in (733, 740):
            captured = bo3.decode_record(raw, index)
            assert captured['priority'] == 15 and captured['material'] == int('0x27C6D3991B8', 16)
            authored = bo3.placement(captured, atlas)
            assert authored['angles'].startswith('270 0 ')
            assert authored['revealDataSize'] == '16x16'


def test_saved_live_material_preserves_all_32_decal_placements(tmp_path):
    capture_name = os.environ.get('GREYHOUND_BO4_LIVE_DECAL_CAPTURE')
    if not capture_name:
        pytest.skip('Set live BO4 decal capture for this optional audit')
    capture = Path(capture_name).resolve()
    prepared = bo3.prepare(capture, include_placements=True)
    assert len(prepared['selected']) == len(prepared['authored']) == 32
    assert not prepared['omitted']
    result = bo3.package(prepared, tmp_path / 'bo3_overlay', include_placements=True)
    assert result['status'] == 'placements_packaged_unverified' and result['complete']
    assert result['placement_exported'] == 32 and result['placement_omitted'] == 0
    for relative, expected_sha256 in SAVED32_ASSET_SHA256.items():
        actual = hashlib.sha256((Path(result['package_root']) / relative).read_bytes()).hexdigest()
        assert actual == expected_sha256, relative
    report = json.loads(Path(result['report']).read_text())
    assert not report['bo3_in_game_verified']
    assert len(report['placement_mappings']) == 32
    assert [row['source_index'] for row in report['placement_mappings']] == prepared['selected']
    assert all(row['bo3_layer_enum'] == row['source_priority'] - 1
               for row in report['placement_mappings'])
    assert all(max(abs((1 - source) - editor) for source, editor in zip(
        row['bo4_runtime_feather'], row['bo3_editor_feather'])) < 1e-6
        for row in report['placement_mappings'])

    def entities(path):
        contents = path.read_text()
        return {int(index): dict(re.findall(r'"([^"\n]+)" "([^"\n]*)"', body))
                for index, body in re.findall(
                    r'// entity \d+: source decal index (\d+)\s*\n\{(.*?)\n\}', contents, re.S)}

    current = entities(Path(result['prefab']))
    original = entities(capture.parent.parent / 'bo3_root' / report['prefab'])
    assert len(current) == 32 and len(original) == 8
    assert all(current[index] == fields for index, fields in original.items())
    by_layer = {}
    for fields in current.values():
        key = (fields['decalLayerSort'], fields['decalLayerSortEnum'])
        by_layer[key] = by_layer.get(key, 0) + 1
    assert by_layer == {('Grunge', '14'): 15, ('Damage - New', '1'): 12, ('Paper', '2'): 5}
    assert sum(fields['edgeFeatherX'] == '0.5' for fields in current.values()) == 7
    assert all(fields['edgeFeatherY'] == fields['edgeFeatherZ'] == '0' for fields in current.values())


def test_saved_live_cli_without_bo3_installation(tmp_path):
    capture_name = os.environ.get('GREYHOUND_BO4_LIVE_DECAL_CAPTURE')
    if not capture_name:
        pytest.skip('Set live BO4 decal capture for this optional CLI audit')
    output = tmp_path / 'cli_bo3_overlay'
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
    command = [sys.executable, '-B', str(ROOT / 'tools/black_ops_4/decals/export_bo3.py'),
               '--capture', capture_name, '--output', str(output), '--placements']
    completed = subprocess.run(command, capture_output=True, text=True, env=env, check=False)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    result = json.loads(completed.stdout)
    assert result['status'] == 'placements_packaged_unverified'
    assert result['placement_exported'] == 32 and result['placement_omitted'] == 0
    assert (output / 'source_data/black_ops_4/decals/bo4_decal_0adc21290fb94ae.gdt').is_file()
