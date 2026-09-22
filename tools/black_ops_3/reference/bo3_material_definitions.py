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
    other_asset_roots = set()
    pattern = r'"([^"\n]+)"\s*(?:\(\s*"([^"\n]+\.gdf)"\s*\)|\[\s*"([^"\n]+)"\s*\])\s*\{([^{}]*)\}'
    for path in map(Path, paths):
        text = path.read_text(encoding='utf-8-sig')
        # Remove comments without changing source line numbers or quoted strings.
        text = re.sub(r'"(?:\\.|[^"\\])*"|//[^\n]*|/\*.*?\*/',
                      lambda m: m[0] if m[0].startswith('"') else re.sub(r'[^\n]', ' ', m[0]),
                      text, flags=re.S)
        source = path.relative_to(relative_to).as_posix() if relative_to else str(path)
        for match in re.finditer(pattern, text):
            name = match[1]
            if match[2] and match[2] != 'material.gdf':
                other_asset_roots.add(name)
                continue
            if name in records:
                raise ValueError('Duplicate material definition: ' + name)
            records[name] = dict(name=name, parent=match[3], source=source,
                                 line=text.count('\n', 0, match.start()) + 1,
                                 own_properties=dict(re.findall(r'"([^"\n]*)"\s*"([^"\n]*)"', match[4])))
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

    def material_chain(name, trail=()):
        # Mixed stock GDTs also contain inherited models/images. Only a chain
        # ending at an explicitly non-material root is excluded; unresolved
        # parents and cycles still reach resolve() and fail with provenance.
        if name not in records:
            return name not in other_asset_roots
        if name in trail or not records[name]['parent']:
            return True
        return material_chain(records[name]['parent'], (*trail, name))

    return [resolve(name) for name in records if material_chain(name)]
