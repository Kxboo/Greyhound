"""Exercise the real post-build staging without compiling or touching an installed runtime."""

import sys as _tool_sys
from pathlib import Path as _ToolPath
REPO_ROOT = next(p for p in _ToolPath(__file__).resolve().parents if (p / "build-greyhound.ps1").is_file())
TOOLS_ROOT = REPO_ROOT / "tools"
_tool_sys.path.insert(0, str(TOOLS_ROOT))
import tool_bootstrap as _tool_bootstrap
_tool_bootstrap.activate(TOOLS_ROOT / "tool_bootstrap.py")
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = REPO_ROOT


@pytest.mark.parametrize("build_only", [True, False])
def test_staged_runtime_finalizes_multiple_capture_sessions(tmp_path, build_only):
    shell = shutil.which("pwsh")
    if not shell:
        pytest.skip("PowerShell required for Windows runtime staging")
    repo = tmp_path / "repo"
    repo.mkdir()
    shutil.copytree(ROOT / "tools", repo / "tools")
    runtime = repo / "src/WraithXCOD/x64/Release"
    runtime.mkdir(parents=True)
    (runtime / "Greyhound.exe").write_bytes(b"test executable")
    legacy = runtime / "tools/capture"
    legacy.mkdir(parents=True)
    (legacy / "local-note.txt").write_text("preserve during layout migration")
    code = (ROOT / "build-greyhound.ps1").read_text()
    staging = code[code.index('$builtExe ='):]
    script = repo / "stage-test.ps1"
    script.write_text('$ErrorActionPreference = "Stop"\n$Configuration = "Release"\n'
                      '$Platform = "x64"\n$BuildOnly = $' + str(build_only).lower() + '\n' + staging)
    env = dict(os.environ, SUPERTERRAIN_PYTHON=sys.executable)
    subprocess.run([shell, "-NoProfile", "-File", str(script)], env=env, check=True,
                   capture_output=True, text=True)
    assert (runtime / "Greyhound.exe").read_bytes() == b"test executable"
    assert not legacy.exists()
    archives = list(runtime.glob("tools-legacy-layout-*"))
    assert len(archives) == 1
    assert (archives[0] / "capture/local-note.txt").read_text() == "preserve during layout migration"
    # Native switches and their bundled implementation must ship together.
    bundle = runtime / "tools"
    manifest = json.loads((bundle / "manifest.json").read_text())
    assert "shared/runtime/verify_runtime.py" in manifest["files"]
    check = runtime / "runtime_check.json"
    subprocess.run([str(bundle / "runtime/python.exe"), "-I", str(bundle / "shared/runtime/verify_runtime.py"),
                    "--output", str(check)], check=True, capture_output=True, text=True)
    assert json.loads(check.read_text())["status"] == "passed"
    assert (runtime / "terrain-python.txt").read_text().strip() == sys.executable
    assert (repo / "bin/Greyhound.exe").exists() == (not build_only)
    # Different map/session paths must use the same shipped helper entry points.
    for name in ("terrain_snow", "terrain_rural", "terrain_zoo"):
        source = runtime / "exported_files" / name / "session/_source"
        (source / "research").mkdir(parents=True)
        (source / "terraingfx.json").write_text(json.dumps({"source_only": True, "name": name}))
        (source / "research/evidence.json").write_text(json.dumps({"reads": []}))
        for helper, args in (("shared/capture/organize_export.py", []),
                             ("shared/capture/finalize_research_capture.py", []),
                             ("shared/capture/finalize_research_capture.py", ["--verify"])):
            subprocess.run([sys.executable, str(runtime / "tools" / helper), str(source), *args],
                           check=True, capture_output=True, text=True)
        assert json.loads((source / "research_capture.report.json").read_text())["verification_ready"]
