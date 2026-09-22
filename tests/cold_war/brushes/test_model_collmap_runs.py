"""Repeated model exports retain each run's geometry and ownership manifest."""

import sys
from pathlib import Path

REPO_ROOT = next(p for p in Path(__file__).resolve().parents if (p / 'build-greyhound.ps1').is_file())
sys.path.insert(0, str(REPO_ROOT / 'tools'))
import tool_bootstrap
tool_bootstrap.activate(REPO_ROOT / 'tools/tool_bootstrap.py')

from concurrent.futures import ThreadPoolExecutor
import hashlib
import itertools
import json
import pytest

import export_cw_model_collmaps as collmaps
from cw_export_layout import reserve_export_directory


@pytest.mark.parametrize('mixed', [False, True])
def test_changed_model_material_creates_new_complete_run(tmp_path, monkeypatch, mixed):
    native = tmp_path / 'capture'
    normalized = native / 'radiant_work/normalized'
    normalized.mkdir(parents=True)
    (normalized / 'capture.json').write_text(json.dumps({'map': 'test_map'}))
    owner = dict(name='test_model', name_hash='0x123', collision_pointer='0x1000')
    (native / 'model_collision_owners.json').write_text(json.dumps(dict(
        status='captured', readback_unchanged=True, models=[owner])))
    payload = b'synthetic cube'
    count = 2 if mixed else 1
    model = dict(index=0, record_address='0x1000', status='decoded', brush_count=count,
                 payload=dict(file='cube.bin', sha256=hashlib.sha256(payload).hexdigest()),
                 component_source=dict(compact_triangle_surfaces_not_exported=0))

    def prepare(_native, local_root):
        local_root.mkdir(exist_ok=True)
        (local_root / 'cube.bin').write_bytes(payload)
        return dict(models=[model]), {}

    material = {'name': 'clip_physics'}
    monkeypatch.setattr(collmaps, 'prepare', prepare)
    monkeypatch.setattr(collmaps, 'decode_brushes', lambda *_: dict(brushes=[dict(
        brush_index=i, vertices=list(itertools.product((-1., 1.), repeat=3))) for i in range(count)]))
    monkeypatch.setattr(collmaps, 'build_assignments', lambda *_: dict(brushes={
        f'0:{i}': dict(decision=dict(material=material['name'] if i==0 else 'clip')) for i in range(count)}))
    # The second run must keep physics-only shapes out of model collision.
    reference = dict(sources=[], materials=[
        dict(name='clip_physics', properties={}),
        dict(name='clip', properties=dict(playerClip='1', noDraw='1')),
        dict(name='nodraw_notsolid', properties=dict(nonSolid='1', noDraw='1')),
        dict(name='lightmap_gray', properties={})])
    destination = tmp_path / 'collmaps/black_ops_cw/test_map'
    # Stub only the material policy for the old run. Hull construction, plane
    # serialization, filenames and all publication below use the real exporter.
    policy = collmaps.model_clip_policy
    monkeypatch.setattr(collmaps, 'model_clip_policy', lambda assignment, _: dict(
        material=assignment['decision']['material']))
    first = collmaps.export(normalized, native, None, None, destination, reference)
    original = {p.name: p.read_bytes() for p in destination.iterdir()}
    monkeypatch.setattr(collmaps, 'model_clip_policy', policy)
    second = collmaps.export(normalized, native, None, None, destination, reference)

    assert Path(first['folder']) == destination
    assert Path(second['folder']) == destination.with_name('test_map_2')
    assert {p.name: p.read_bytes() for p in destination.iterdir()} == original
    new_root = Path(second['folder'])
    assert b' clip_physics ' in original['test_model.map']
    assert (new_root / 'test_model.map').exists() == mixed
    if mixed:
        assert b' clip ' in (new_root / 'test_model.map').read_bytes()
        assert b' clip_physics ' not in (new_root / 'test_model.map').read_bytes()
    assert b' nodraw_notsolid ' in (new_root / 'references/test_model.map').read_bytes()
    assert second['collision_brushes'] == int(mixed) and second['reference_brushes'] == 1
    assert second['models'] == 1 and second['brushes'] == count
    manifest = json.loads((new_root / 'manifest.json').read_text())
    row = next(r for r in manifest['files'] if r['prefab_role']=='reference_brushes')
    assert manifest['map'] == 'test_map'
    assert row['sha256'] == hashlib.sha256((new_root / row['file']).read_bytes()).hexdigest()
    assert row['model_collision_assignments'][0]['physics_fallback']
    assert row['model_collision_assignments'][0]['collision_candidate_material'] == 'clip'
    assert row['prefab_role'] == 'reference_brushes'
    assert row['compile_excluded']
    stock = json.loads((new_root/'stock_material_audit.json').read_text())
    assert stock['maps'][0]['file'] == 'references/test_model.map'
    from verify_cw_local_collmaps import verify
    assert verify(new_root)['brush_pieces'] == count


def test_reservation_skips_existing_files_and_empty_directories(tmp_path):
    destination = tmp_path / 'test_map'
    destination.write_text('existing file')
    destination.with_name('test_map_2').mkdir()
    assert reserve_export_directory(destination) == tmp_path / 'test_map_3'
    assert destination.read_text() == 'existing file'


def test_concurrent_exports_reserve_different_folders(tmp_path):
    destination = tmp_path / 'test_map'
    with ThreadPoolExecutor(max_workers=4) as pool:
        runs = list(pool.map(reserve_export_directory, [destination] * 8))
    assert len(set(runs)) == 8
    assert all(p.is_dir() for p in runs)
    assert {p.name for p in runs} == {'test_map', *(f'test_map_{i}' for i in range(2, 9))}
