"""Embed stock definitions and replace unavailable materials with stock choices."""

import sys as _tool_sys
from pathlib import Path as _ToolPath
TOOLS_ROOT = next(p for p in _ToolPath(__file__).resolve().parents if (p / 'tool_bootstrap.py').is_file())
_tool_sys.path.insert(0, str(TOOLS_ROOT))
import tool_bootstrap as _tool_bootstrap
_tool_bootstrap.activate(__file__)

from collections import Counter
import hashlib
import json
import re
from material_comparison_report import reports


FACE = re.compile(r'^\s*(?:\([^\r\n()]+\)\s*){3}(\S+)\s+.*?\s+(\S+)\s+(?:[-+\d.eE]+\s*){6}$')
QUERY_FLAGS = ('playerClip', 'aiClip', 'vehicleClip', 'playerVehicleClip', 'itemClip',
               'missileClip', 'bulletClip', 'aiSightClip', 'canShootClip', 'utilityClip')


def closest_stock_material(requested, reference, decision=None, properties=None, default='clip'):
    stock = {m['name']: m for m in reference['materials']}
    if requested in stock:
        return requested, 'existing_stock_material'
    if decision:
        options = [decision, *decision.get('closest_candidates', [])]
        for option in options:
            name = option.get('material')
            if name in stock and option.get('automatic_selection_eligible', True):
                return name, 'captured_property_stock_recommendation'
    aliases = {name for image in reference.get('tool_images', []) if image['name'] == requested
               for name in image['referenced_by_materials'] if name in stock}
    if len(aliases) == 1:
        return next(iter(aliases)), 'stock_image_alias_resolved_to_material'
    if properties is not None:
        from assign_cw_bo3_types import surface_distance, material_score
        wanted = {n for n in QUERY_FLAGS if properties.get(n) == '1'}
        surface = properties.get('surfaceType', '<none>')
        climb = properties.get('surfaceClimbType', '<none>')
        candidates = []
        for name, material in stock.items():
            props = material['properties']
            if props.get('noDraw') != '1' or props.get('nonColliding') == '1':
                continue
            if climb not in ('', '<none>'):
                eligible = props.get('surfaceClimbType') == climb
            elif properties.get('mount') == '1':
                eligible = name == 'mount'
            elif not wanted:
                eligible = name in ('caulk', 'nodraw_notsolid', 'skip')
            else:
                eligible = props.get('usage') == 'clip' or name == 'nosight_noclip'
            if not eligible or (props.get('slick') == '1' and properties.get('slick') != '1'):
                continue
            # A slightly closer query mask must not turn metal into glass or a
            # generic solid into ice. Keep the same/related surface or a generic
            # stock fallback, matching the captured-brush assignment policy.
            distance = surface_distance(None if surface == '<none>' else surface,
                                        props.get('surfaceType', '<none>'))
            if distance == 3:
                continue
            actual = {n for n in QUERY_FLAGS if props.get(n) == '1'}
            flags = ('noMarks', 'noImpact', 'noCastShadow', 'nonSolid', 'structural', 'caulk', 'slick')
            score = (*material_score(wanted-actual, actual-wanted,
                     {n for n in flags if properties.get(n)=='1'},
                     {n for n in flags if props.get(n)=='1'},distance),len(name),name)
            candidates.append((score, name))
        if candidates:
            return min(candidates)[1], 'closest_stock_authoring_properties'
    if default not in stock:
        raise ValueError('Stock catalogue is missing the required fallback: ' + default)
    return default, 'generic_stock_fallback_source_properties_unavailable'


def write_stock_metadata(folder, reference, assignments, material_properties=None):
    """Write self-contained, hashed evidence beside staged or model-local maps."""
    stock = {m['name']: m for m in reference['materials']}
    if len(stock) != len(reference['materials']):
        raise ValueError('Ambiguous stock material catalogue')
    counts = Counter()
    lightmaps = Counter()
    maps = []
    substitutions = []
    metadata_path = folder / 'collision_metadata.json'
    metadata = json.loads(metadata_path.read_text()) if metadata_path.exists() else None
    rows = {r['map_brush_index']: r for r in metadata['rows']} if metadata else {}
    brush_files = {p['file'] for p in metadata.get('prefabs', {}).values()} if metadata else set()
    if metadata:
        brush_files.add(metadata['map'] + '_brush_collision.map')
    for path in sorted(folder.rglob('*.map')):
        relative = path.relative_to(folder).as_posix()
        materials = Counter()
        source = path.read_text(encoding='utf-8-sig')
        output = []
        brush = None
        changed = False
        for original in source.splitlines(keepends=True):
            line = original.rstrip('\r\n')
            comment = re.match(r'\s*// brush (\d+)', line)
            if comment:
                brush = int(comment[1])
            if not line.lstrip().startswith('('):
                output.append(original)
                continue
            match = FACE.fullmatch(line)
            if not match:
                raise ValueError('Unrecognized brush face in ' + str(path))
            material, lightmap = match.groups()
            row = rows.get(brush, {}) if relative in brush_files else {}
            decision = assignments.get('brushes', {}).get(row.get('material_assignment_key'), {}).get('decision')
            replacement, reason = closest_stock_material(material, reference, decision,
                (material_properties or {}).get(material))
            replacement_lightmap, _ = closest_stock_material(lightmap, reference, default='lightmap_gray')
            if replacement != material or replacement_lightmap != lightmap:
                substitutions.append(dict(file=relative, brush=brush, requested=material,
                    material=replacement, requested_lightmap=lightmap, lightmap=replacement_lightmap, reason=reason))
                # Replace only asset tokens; all plane/projection numbers stay intact.
                line = line[:match.start(2)] + replacement_lightmap + line[match.end(2):]
                line = line[:match.start(1)] + replacement + line[match.end(1):]
                original = line + original[len(original.rstrip('\r\n')):]
                changed = True
                if row:
                    row.update(assigned_material=replacement, unavailable_material=material,
                               stock_substitution_reason=reason)
            material, lightmap = replacement, replacement_lightmap
            output.append(original)
            materials[material] += 1
            lightmaps[lightmap] += 1
        if changed:
            path.write_text(''.join(output), encoding='utf-8')
        counts.update(materials)
        maps.append(dict(file=relative, sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                         face_material_counts=dict(materials)))
    if not maps:
        raise ValueError('No maps to audit for stock material references')
    used = set(counts) | set(lightmaps)
    audit = dict(schema='greyhound-stock-material-audit-v1', stock_only=True,
                 custom_material_count=0, catalogue_materials=len(stock),
                 face_material_counts=dict(counts), lightmap_material_counts=dict(lightmaps),
                 maps=maps, definitions=[stock[n] for n in sorted(used)],
                 captured_assignment_summary=assignments.get('summary', {}),
                 source_definitions=reference['sources'],
                 substitutions=substitutions,
                 scope='Every face and lightmap name resolves to the bundled BO3 stock catalogue. '
                       'Captured properties and suggested assignments are in material_assignments.json; '
                       'actual emitted materials are inventoried here. Property approximations, '
                       'unknown flags and model collision policy remain explicit. '
                       'Stock availability does not prove identical CW/BO3 gameplay.',
                 compiler_validated=False, gameplay_validated=False)
    if metadata and substitutions:
        inventory = {r['file']: r for r in maps}
        metadata['map_sha256'] = inventory[metadata['map'] + '_brush_collision.map']['sha256']
        for prefab in metadata.get('prefabs', {}).values():
            prefab['sha256'] = inventory[prefab['file']]['sha256']
            prefab['material_counts'] = dict(Counter(r['assigned_material'] for r in rows.values()
                                                    if r.get('prefab_file') == prefab['file']))
        metadata['stock_material_substitutions'] = substitutions
        metadata_path.write_text(json.dumps(metadata, indent=2), encoding='utf-8')
    documents = {'bo3_stock_reference.json': reference,
                 'material_assignments.json': assignments,
                 'stock_material_audit.json': audit}
    inventory = {}
    for name, document in documents.items():
        path = folder / name
        path.write_text(json.dumps(document, indent=2) + '\n', encoding='utf-8')
        inventory[name] = dict(file=name, sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    for name, content in reports(reference, assignments, audit).items():
        path = folder / name
        path.write_text(content, encoding='utf-8')
        inventory[name] = dict(file=name, sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    return inventory
