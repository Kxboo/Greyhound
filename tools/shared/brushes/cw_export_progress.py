"""Best-effort atomic progress updates; telemetry must not abort geometry export."""

# Support direct execution and the isolated packaged Python runtime.
import sys as _tool_sys
from pathlib import Path as _ToolPath
TOOLS_ROOT = next(p for p in _ToolPath(__file__).resolve().parents if (p / "tool_bootstrap.py").is_file())
_tool_sys.path.insert(0, str(TOOLS_ROOT))
import tool_bootstrap as _tool_bootstrap
_tool_bootstrap.activate(__file__)
REPO_ROOT = TOOLS_ROOT.parent
import json
import os
import time


def write_progress(path, data, attempts=6):
    temporary=path.with_suffix('.tmp')
    for attempt in range(attempts):
        try:
            temporary.write_text(json.dumps(data),encoding='utf-8')
            os.replace(temporary,path)
            return True
        except PermissionError:
            # Windows readers/scanners may briefly deny delete-sharing. Keep
            # the last complete JSON available, then try the next progress tick.
            if attempt+1<attempts:time.sleep(0.02*(attempt+1))
    return False
