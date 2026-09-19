"""On-disk contract for a sealed Greyhound terrain source export."""

from __future__ import annotations

# Support direct execution and the isolated packaged Python runtime.
import sys as _tool_sys
from pathlib import Path as _ToolPath
TOOLS_ROOT = next(p for p in _ToolPath(__file__).resolve().parents if (p / "tool_bootstrap.py").is_file())
_tool_sys.path.insert(0, str(TOOLS_ROOT))
import tool_bootstrap as _tool_bootstrap
_tool_bootstrap.activate(__file__)
REPO_ROOT = TOOLS_ROOT.parent

import os


CAPTURE = "capture"
MANIFEST = "terraingfx.json"


def capture_dir(root):
    return os.path.join(os.path.abspath(root), CAPTURE)


def capture(root, *parts):
    cleaned = []
    for part in parts:
        cleaned.extend(str(part).replace("\\", "/").split("/"))
    return os.path.join(capture_dir(root), *[part for part in cleaned if part])


def manifest_path(root):
    return capture(root, MANIFEST)


def is_organized(root):
    return os.path.exists(manifest_path(root))
