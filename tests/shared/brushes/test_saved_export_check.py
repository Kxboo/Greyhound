
import sys as _tool_sys
from pathlib import Path as _ToolPath
REPO_ROOT = next(p for p in _ToolPath(__file__).resolve().parents if (p / "build-greyhound.ps1").is_file())
TOOLS_ROOT = REPO_ROOT / "tools"
_tool_sys.path.insert(0, str(TOOLS_ROOT))
import tool_bootstrap as _tool_bootstrap
_tool_bootstrap.activate(TOOLS_ROOT / "tool_bootstrap.py")
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import pytest

from verify_saved_export import verify


@pytest.mark.parametrize('game', ['cw', 'bo4'])
def test_saved_prefab_detects_modified_missing_and_escaping_files(tmp_path, game):
    prefab = tmp_path / 'test.map'
    prefab.write_text('iwmap 4\n{\n"classname" "worldspawn"\n}\n')
    entry = dict(sha256=hashlib.sha256(prefab.read_bytes()).hexdigest())
    if game == 'cw':
        entry['file'] = prefab.name
    report = dict(schema='greyhound-cw-radiant-v6' if game == 'cw' else 'greyhound-bo4-brush-export-v1',
                  status='exported' if game == 'cw' else 'exported_with_review',
                  prefabs={prefab.name: entry})
    metadata = tmp_path / 'metadata'
    metadata.mkdir()
    source = metadata / 'export_report.json'
    source.write_text(json.dumps(report))
    assert verify(source)['status'] == 'passed'
    del entry['sha256']
    source.write_text(json.dumps(report))
    assert 'no valid SHA-256' in verify(source)['checks'][0]['error']
    entry['sha256'] = hashlib.sha256(prefab.read_bytes()).hexdigest()
    source.write_text(json.dumps(report))
    prefab.write_text('changed')
    assert verify(source)['status'] == 'failed'
    prefab.unlink()
    assert verify(source)['status'] == 'failed'
    report['prefabs'] = {'outside': dict(file='../outside.map', sha256='0' * 64)}
    source.write_text(json.dumps(report))
    assert 'escapes' in verify(source)['checks'][0]['error']


def test_terrain_verification_uses_sealed_inventory_and_preserves_source(tmp_path):
    helper = TOOLS_ROOT / 'shared/capture/finalize_research_capture.py'
    spec = importlib.util.spec_from_file_location('terrain_seal_fixture', helper)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    root = tmp_path / 'exported_files/test/_source'
    (root / 'capture/research').mkdir(parents=True)
    (root / 'capture/research/evidence.json').write_text(json.dumps({'reads': []}))
    (root / 'capture/terraingfx.json').write_text(json.dumps({'source_only': True}))
    module.finalize(root)
    source = root / 'research_capture.report.json'
    before = {path.name: path.read_bytes() for path in root.rglob('*') if path.is_file()}
    assert verify(source)['status'] == 'passed'
    assert before == {path.name: path.read_bytes() for path in root.rglob('*') if path.is_file()}
    (root / 'capture/terraingfx.json').write_text('{}')
    assert verify(source)['status'] == 'failed'


def test_unrecognized_report_cannot_claim_success(tmp_path):
    source = tmp_path / 'export_report.json'
    source.write_text('{"schema":"unknown","status":"exported"}')
    with pytest.raises(ValueError, match='Choose metadata'):
        verify(source)
