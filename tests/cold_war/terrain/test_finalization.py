"""Cold War baked package scope and finalization, using synthetic files."""
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'tools/cold_war/terrain'))
import finalize


def test_finalized_package_keeps_surface_scope_and_removes_owned_work(tmp_path):
    root = tmp_path / 'run'
    root.mkdir()
    work = root / '_work'
    work.mkdir()
    (work / 'source.bin').write_bytes(b'synthetic source')

    package = root / 'terrain'
    (package / '_mat_info').mkdir(parents=True)
    (package / '_mat_info' / 'mat.txt').write_text('material')
    images = package / '_images' / 'mat'
    images.mkdir(parents=True)
    for suffix in 'cngo':
        (images / f'mat_{suffix}.png').write_bytes(b'synthetic image data' * 2)
    (package / 'terrain.cast').write_bytes(b'synthetic model')
    (package / 'export_report.json').write_text(json.dumps({
        'tiles': [[0, 0]],
        'terrain_material_layers_included': True,
        'volume_decals_included': False,
    }))
    (root / 'terrain_export.json').write_text(json.dumps({
        'packages': [{'name': 'terrain'}],
        'terrain_material_layers_included': True,
        'volume_decals_included': False,
    }))

    finalize.finalize(root)

    manifest = json.loads((root / 'terrain_export.json').read_text())
    report = json.loads((package / 'export_report.json').read_text())
    assert manifest['status'] == report['status'] == 'complete'
    assert manifest['terrain_material_layers_included'] is True
    assert report['terrain_material_layers_included'] is True
    assert manifest['volume_decals_included'] is False
    assert report['volume_decals_included'] is False
    assert 'Independent volume decals are omitted.' in (root / 'README.txt').read_text()
    assert not work.exists()
