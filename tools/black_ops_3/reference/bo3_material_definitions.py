"""Resolve direct and inherited BO3 GDT materials, retaining source provenance.

Based on the research resolver in tools/analysis/audit_cw_bo3_surface_mapping.py.
Only the flat material property blocks used by the shipped clip/tool GDTs are
accepted. Inheritance may refer forward or cross the supplied GDT files.
"""

# Support direct execution and the isolated packaged Python runtime.
import sys as _tool_sys
from pathlib import Path as _ToolPath
TOOLS_ROOT = next(p for p in _ToolPath(__file__).resolve().parents if (p / "tool_bootstrap.py").is_file())
_tool_sys.path.insert(0, str(TOOLS_ROOT))
import tool_bootstrap as _tool_bootstrap
_tool_bootstrap.activate(__file__)
REPO_ROOT = TOOLS_ROOT.parent
import re
from pathlib import Path


def materials(paths, relative_to=None):
    records = {}
    pattern = r'"([^"\n]+)"\s*(?:\(\s*"material.gdf"\s*\)|\[\s*"([^"\n]+)"\s*\])\s*\{([^{}]*)\}'
    for path in map(Path, paths):
        text = path.read_text(encoding='utf-8-sig')
        # Remove comments without changing source line numbers or quoted strings.
        text = re.sub(r'"(?:\\.|[^"\\])*"|//[^\n]*|/\*.*?\*/',
                      lambda m: m[0] if m[0].startswith('"') else re.sub(r'[^\n]', ' ', m[0]),
                      text, flags=re.S)
        source = path.relative_to(relative_to).as_posix() if relative_to else str(path)
        for match in re.finditer(pattern, text):
            name = match[1]
            if name in records:
                raise ValueError('Duplicate material definition: ' + name)
            records[name] = dict(name=name, parent=match[2], source=source,
                                 line=text.count('\n', 0, match.start()) + 1,
                                 own_properties=dict(re.findall(r'"([^"\n]*)"\s*"([^"\n]*)"', match[3])))
    resolved = {}

    def resolve(name, trail=()):
        if name in trail:
            raise ValueError('Material inheritance cycle: ' + ' -> '.join((*trail, name)))
        if name not in records:
            raise ValueError('Missing parent material: ' + name)
        if name in resolved:
            return resolved[name]
        row = records[name]
        properties, chain = {}, []
        if row['parent']:
            parent = resolve(row['parent'], (*trail, name))
            properties.update(parent['properties'])
            chain = [*parent['inheritance_chain'], row['parent']]
        properties.update(row['own_properties'])
        resolved[name] = dict(**row, properties=properties, inheritance_chain=chain)
        return resolved[name]

    return [resolve(name) for name in records]
