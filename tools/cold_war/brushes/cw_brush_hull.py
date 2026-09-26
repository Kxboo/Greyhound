"""Checked hull topology; every face indexes the unchanged captured points.

Connectivity and containment use exact integer predicates. Metric diagnostics
use the original double precision coordinates, centered locally.

Compatibility imports; implementations are shared by game converters.
"""

# Support direct execution and the isolated packaged Python runtime.
import sys as _tool_sys
from pathlib import Path as _ToolPath
TOOLS_ROOT = next(p for p in _ToolPath(__file__).resolve().parents if (p / "tool_bootstrap.py").is_file())
_tool_sys.path.insert(0, str(TOOLS_ROOT))
import tool_bootstrap as _tool_bootstrap
_tool_bootstrap.activate(__file__)
REPO_ROOT = TOOLS_ROOT.parent
from exact_geometry import checked_hull
