"""CW-style category prefabs, arranged under the user's three BO4 categories."""

# Support direct execution and the isolated packaged Python runtime.
import sys as _tool_sys
from pathlib import Path as _ToolPath
TOOLS_ROOT = next(p for p in _ToolPath(__file__).resolve().parents if (p / "tool_bootstrap.py").is_file())
_tool_sys.path.insert(0, str(TOOLS_ROOT))
import tool_bootstrap as _tool_bootstrap
_tool_bootstrap.activate(__file__)
REPO_ROOT = TOOLS_ROOT.parent
from pathlib import Path
import re


def brush_role(decision):
    role=decision.get('role','brushes')
    if role in ('traversal','non_colliding'):
        return role
    material=decision.get('material','')
    if role=='clips' or 'clip' in material.split('_') or material=='nosight_noclip':
        return 'clips'
    return 'brushes'


def prefab_relative_path(name):
    if Path(name).name!=name:
        raise ValueError('Expected a prefab basename')
    model=re.search(r'_model_physics_(brushes|clips|traversal|non_colliding)\.map$',name)
    if model:
        return Path('model clips')/model[1]/name
    source=re.search(r'_(world|inline_models)_(brushes|clips|traversal|non_colliding)\.map$',name)
    if source:
        kind,role=source.groups()
        top='clips' if role=='clips' else 'brushes'
        folder=kind if role in ('brushes','clips') else role
        return Path(top)/folder/name
    review=re.search(r'_(triggers|volumes)_review\.map$',name)
    if review:
        return Path('brushes')/review[1]/name
    raise ValueError('Unclassified BO4 prefab: '+name)


def remap_references(value, paths):
    if isinstance(value,dict):
        return {paths.get(k,k):remap_references(v,paths) for k,v in value.items()}
    if isinstance(value,list):
        return [remap_references(v,paths) for v in value]
    return paths.get(value,value) if isinstance(value,str) else value
