"""A v9 saved export must seal both its prefabs and reconstruction evidence."""
import hashlib
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT/'tools'))
import tool_bootstrap
tool_bootstrap.activate(ROOT/'tools/tool_bootstrap.py')
from verify_saved_export import verify


@pytest.mark.parametrize('version', ['v9', 'v10', 'v11'])
def test_reconstruction_metadata_is_required_and_hash_checked(tmp_path, version):
    metadata = tmp_path/'metadata'; metadata.mkdir()
    names = ['bo3_stock_reference.json','material_assignments.json','stock_material_audit.json',
        'STOCK_MATERIALS.md','CAPTURED_BRUSH_MATERIALS.md','BO3_RENDER_MATERIALS.md',
        'brush_faces.jsonl','brush_face_audit.json','collision_metadata.json']
    embedded = {}
    if version=='v11':names.append('render_transfer.json')
    for name in names:
        p = metadata/name; p.write_text('{}\n')
        embedded[name] = dict(file='metadata/'+name,sha256=hashlib.sha256(p.read_bytes()).hexdigest())
    prefab = tmp_path/'fixture.map'; prefab.write_text('iwmap 4\n{\n"classname" "worldspawn"\n}\n')
    report = dict(schema='greyhound-cw-radiant-'+version,status='exported',embedded_data=embedded,
        prefabs=dict(brushes_clips=dict(file=prefab.name,sha256=hashlib.sha256(prefab.read_bytes()).hexdigest())))
    if version=='v11':report['texture_transfer']=dict(status='render_material_uv_associations_unavailable')
    path = metadata/'export_report.json'; path.write_text(json.dumps(report))
    assert verify(path)['status'] == 'passed'
    (metadata/'brush_faces.jsonl').write_text('changed corners\n')
    result = verify(path)
    assert result['status'] == 'failed'
    assert any(c['file'] == 'metadata/brush_faces.jsonl' and not c['passed'] for c in result['checks'])
    del report['embedded_data']['brush_faces.jsonl']; path.write_text(json.dumps(report))
    with pytest.raises(ValueError, match='omits required'): verify(path)
