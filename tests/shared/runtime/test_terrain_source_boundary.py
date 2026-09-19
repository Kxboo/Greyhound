"""Regression guard: terrain reconstruction stays outside Greyhound.

Brush conversion and map diagnostics have their own packaged tools.
"""

import sys as _tool_sys
from pathlib import Path as _ToolPath
REPO_ROOT = next(p for p in _ToolPath(__file__).resolve().parents if (p / "build-greyhound.ps1").is_file())
TOOLS_ROOT = REPO_ROOT / "tools"
_tool_sys.path.insert(0, str(TOOLS_ROOT))
import tool_bootstrap as _tool_bootstrap
_tool_bootstrap.activate(TOOLS_ROOT / "tool_bootstrap.py")

from pathlib import Path
import re


ROOT = REPO_ROOT
NATIVE = ROOT / "src" / "WraithXCOD" / "WraithXCOD"


def test_native_python_calls_are_capture_finalization_only():
    code = (NATIVE / "CoDAssets.cpp").read_text(encoding="utf-8")
    calls = set(re.findall(r'RunTerrainPython\("([^"]+)"', code))
    assert calls == {"shared/capture/organize_export.py", "shared/capture/finalize_research_capture.py"}
    assert "const bool SourceOnly = true;" in code
    assert '"reconstruction_started", false' in code
    assert "if (!SourceOnly" not in code
    assert "geometry_exported" not in code
    assert "terrain_reconstructed_detail" not in code


def test_reconstruction_presets_and_controls_are_absent():
    assert not (NATIVE / "TerrainPresets.cpp").exists()
    assert not (NATIVE / "TerrainPresets.h").exists()
    project = (NATIVE / "WraithXCOD.vcxproj").read_text(encoding="utf-8")
    ui = (NATIVE / "WraithXCOD.rc").read_text(encoding="utf-8")
    assert "TerrainPresets" not in project
    assert "IDC_TERRAINEXPORTPRESET" not in ui
    assert "Run splat reconstruction" not in ui
    assert "Bake OMPV pages" not in ui
    assert "Export Black Ops III .map" not in ui

    native_source = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in NATIVE.glob("*.cpp")
    )
    assert "terrainrunpipeline" not in native_source
    assert "terrainrunompv" not in native_source
    assert "terrainexportbo3map" not in native_source
    assert "terraingeometryquality" not in native_source


def test_terrain_helpers_do_not_ship_reconstruction_modules():
    scripts = {
        path.relative_to(ROOT / "tools").as_posix()
        for path in (ROOT / "tools").rglob("*.py")
    }
    assert {
        "shared/capture/finalize_research_capture.py",
        "shared/capture/organize_export.py",
        "shared/core/layout.py",
        "tool_bootstrap.py",
    } <= scripts
    assert not any(Path(name).name in {
        "rebuild_terrain.py", "ompv_composite.py", "build_tile_mesh.py",
        "export_presets.py", "ompv_splat.py"
    } for name in scripts)
    build = (ROOT / "build-greyhound.ps1").read_text(encoding="utf-8")
    assert "export_presets.json" not in build
    assert "rebuild_terrain.py" not in build
    assert "ompv_composite.py" not in build
