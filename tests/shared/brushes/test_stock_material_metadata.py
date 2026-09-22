"""Stock-only publication embeds evidence and substitutes unavailable names."""
import sys
from pathlib import Path
REPO_ROOT = next(p for p in Path(__file__).resolve().parents if (p / 'build-greyhound.ps1').is_file())
sys.path.insert(0, str(REPO_ROOT / 'tools'))
import tool_bootstrap
tool_bootstrap.activate(REPO_ROOT / 'tools/tool_bootstrap.py')
import hashlib
import json
import pytest
from stock_material_metadata import write_stock_metadata, closest_stock_material
from verify_saved_export import verify


def fixture(tmp_path, material='clip'):
    stage = tmp_path / 'stage'
    stage.mkdir()
    target = stage / 'test.map'
    target.write_text('iwmap 4\n// entity 0\n{\n"classname" "worldspawn"\n// brush 0\n{\n'
                      f'( 0 0 0 ) ( 1 0 0 ) ( 0 1 0 ) {material} 64 64 0 0 0 0 lightmap_gray 16384 16384 0 0 0 0\n'
                      '}\n}\n')
    ref = dict(sources=[dict(file='clip.gdt', sha256='1' * 64)], materials=[
        dict(name='clip', source='clip.gdt', line=1, properties=dict(noDraw='1', playerClip='1')),
        dict(name='lightmap_gray', source='tools.gdt', line=1, properties={})])
    assignments = dict(summary=dict(unique_brushes=1), brushes={'0:0': dict(unknown_contents='0x1')})
    return stage, ref, assignments


def test_stock_definition_and_source_uncertainty_are_embedded(tmp_path):
    stage, ref, assignments = fixture(tmp_path)
    inventory = write_stock_metadata(stage, ref, assignments)
    assert json.loads((stage / 'bo3_stock_reference.json').read_text()) == ref
    assert json.loads((stage / 'material_assignments.json').read_text()) == assignments
    audit = json.loads((stage / 'stock_material_audit.json').read_text())
    assert audit['stock_only'] and audit['custom_material_count'] == 0
    assert audit['face_material_counts'] == {'clip': 1}
    assert audit['lightmap_material_counts'] == {'lightmap_gray': 1}
    assert {'STOCK_MATERIALS.md','CAPTURED_BRUSH_MATERIALS.md','BO3_RENDER_MATERIALS.md'} <= inventory.keys()
    assert all(hashlib.sha256((stage / entry['file']).read_bytes()).hexdigest() == entry['sha256']
               for entry in inventory.values())


@pytest.mark.parametrize('name', ['cw_custom_clip', 'clipmissile'])
def test_custom_or_image_alias_names_fall_back_without_dropping_geometry(tmp_path, name):
    stage, ref, assignments = fixture(tmp_path, name)
    original = (stage / 'test.map').read_text()
    write_stock_metadata(stage, ref, assignments)
    assert (stage / 'test.map').read_text() == original.replace(name + ' 64 64', 'clip 64 64')
    audit = json.loads((stage / 'stock_material_audit.json').read_text())
    assert audit['substitutions'][0]['requested'] == name
    assert audit['face_material_counts'] == {'clip': 1}


def test_adjacent_captured_recommendation_precedes_generic_clip(tmp_path):
    _, ref, _ = fixture(tmp_path)
    ref['materials'].append(dict(name='concrete_clip', properties=dict(noDraw='1')))
    decision = dict(material='unavailable_exact', closest_candidates=[
        dict(material='concrete_clip', automatic_selection_eligible=True)])
    assert closest_stock_material('unavailable_exact', ref, decision)[0] == 'concrete_clip'


def test_stock_image_alias_uses_its_actual_material(tmp_path):
    _, ref, _ = fixture(tmp_path)
    ref['materials'].append(dict(name='nodraw_notsolid', properties=dict(noDraw='1')))
    ref['tool_images'] = [dict(name='nodraw_nonsolid', referenced_by_materials=['nodraw_notsolid'])]
    assert closest_stock_material('nodraw_nonsolid', ref)[0] == 'nodraw_notsolid'


def test_authoring_fallback_does_not_switch_to_an_unrelated_surface():
    ref = json.loads((REPO_ROOT/'tools/black_ops_3/reference/bo3_reference.json').read_text())
    props = dict(noDraw='1',nonSolid='1',surfaceType='metal',missileClip='1',bulletClip='1',aiSightClip='1')
    name, _ = closest_stock_material('cw_custom_metal',ref,properties=props)
    selected = next(m for m in ref['materials'] if m['name']==name)
    assert selected['properties']['surfaceType'] in ('metal','<none>')
    assert name != 'glass_clip_full'


def test_saved_export_checks_embedded_data_and_detects_tampering(tmp_path):
    stage, ref, assignments = fixture(tmp_path)
    inventory = write_stock_metadata(stage, ref, assignments)
    path = stage / 'export_report.json'
    report = dict(schema='greyhound-cw-radiant-v7', status='exported', embedded_data=inventory,
                  prefabs=dict(brushes=dict(file='test.map', sha256=hashlib.sha256((stage/'test.map').read_bytes()).hexdigest())))
    path.write_text(json.dumps(report))
    assert verify(path)['status'] == 'passed'
    (stage / 'material_assignments.json').write_text('{}')
    assert verify(path)['status'] == 'failed'
    del report['embedded_data']['bo3_stock_reference.json']
    path.write_text(json.dumps(report))
    with pytest.raises(ValueError, match='omits required'):
        verify(path)
