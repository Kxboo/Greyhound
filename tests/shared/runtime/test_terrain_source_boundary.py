"""Guard the explicit separation of model export and archival Dev Tools capture."""
from pathlib import Path
import re
ROOT=Path(__file__).resolve().parents[3]
NATIVE=ROOT/'src/WraithXCOD/WraithXCOD'


def test_main_export_and_source_capture_have_separate_routes():
    code=(NATIVE/'assets/CoDAssets.cpp').read_text()
    assert 'case WraithAssetType::Terrain: {Result = TerrainSourceOnly' in code
    assert '? ExportTerrainAsset(' in code and ': ExportBakedTerrain(' in code
    assert 'Result == ExportGameResult::Success && TerrainSourceOnly' in code
    assert 'dev_tools/terrain_sources' in code
    assert 'cold_war/terrain/bake.py' in code
    assert 'cold_war/terrain/finalize.py' in code


def test_portable_terrain_bake_has_no_research_or_blender_dependency():
    source='\n'.join(p.read_text() for p in (ROOT/'tools/cold_war/terrain').glob('*.py'))
    assert 'C:/SuperTerrain' not in source and 'D:/_superterrain' not in source
    assert 'io_scene_cast' not in source and 'TerrainReconstructor' not in source
    assert 'Recovered distortion is required' in source


def test_archival_helpers_remain_packaged():
    for helper in ('shared/capture/finalize_research_capture.py','shared/capture/organize_export.py'):
        assert (ROOT/'tools'/helper).is_file()
    ui=(NATIVE/'WraithXCOD.rc').read_text()
    assert 'Capture raw terrain source' in ui
    assert 'Terrain model export' in ui
