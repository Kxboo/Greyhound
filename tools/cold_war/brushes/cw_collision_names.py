"""Shared verified naming convention for offline Greyhound collision exports."""

# Support direct execution and the isolated packaged Python runtime.
import sys as _tool_sys
from pathlib import Path as _ToolPath
TOOLS_ROOT = next(p for p in _ToolPath(__file__).resolve().parents if (p / "tool_bootstrap.py").is_file())
_tool_sys.path.insert(0, str(TOOLS_ROOT))
import tool_bootstrap as _tool_bootstrap
_tool_bootstrap.activate(__file__)
REPO_ROOT = TOOLS_ROOT.parent
import re

def hash63(name):
    value=0xcbf29ce484222325
    for byte in name.encode('utf-8'):
        value=((value^byte)*0x100000001b3)&0xffffffffffffffff
    return value&0x7fffffffffffffff

def collision_instance_name(name, collision_hash, district, reference_index):
    label=name if name and hash63(name)==collision_hash else f'xmodel_{collision_hash:x}'
    label=re.sub(r'[^A-Za-z0-9_.-]','_',label)
    return f'{label}_collision_d{district}_i{reference_index}'
