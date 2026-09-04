"""Regression guard: Greyhound produces source data and never reconstructs it."""

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / "src" / "WraithXCOD" / "WraithXCOD"


def test_native_python_calls_are_capture_finalization_only():
    code = (NATIVE / "CoDAssets.cpp").read_text(encoding="utf-8")
    calls = set(re.findall(r'RunTerrainPython\("([^"]+)"', code))
    assert calls == {"organize_export.py", "capture/finalize_research_capture.py"}
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


def test_only_capture_helpers_ship_with_greyhound():
    scripts = {
        path.relative_to(ROOT / "tools").as_posix()
        for path in (ROOT / "tools").rglob("*.py")
    }
    assert scripts == {
        "capture/finalize_research_capture.py",
        "capture/organize_export.py",
        "core/layout.py",
        "organize_export.py",
        "tool_bootstrap.py",
    }
    build = (ROOT / "build-greyhound.ps1").read_text(encoding="utf-8")
    assert "export_presets.json" not in build
    assert "rebuild_terrain.py" not in build
    assert "ompv_composite.py" not in build
