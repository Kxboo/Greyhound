"""Greyhound runtime launcher for the source-capture organizer."""

import pathlib
import runpy
import sys

root = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(root))
import tool_bootstrap

target = root / "capture" / "organize_export.py"
tool_bootstrap.activate(target)
runpy.run_path(str(target), run_name="__main__")
