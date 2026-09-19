"""Review stock BO3 matches before proposing APE property recipes.

This checks captured CW declarations against BO3 authoring fields. It does not
prove compiler equivalence, install materials, or change exported geometry.
"""

# Support direct execution and the isolated packaged Python runtime.
import sys as _tool_sys
from pathlib import Path as _ToolPath
TOOLS_ROOT = next(p for p in _ToolPath(__file__).resolve().parents if (p / "tool_bootstrap.py").is_file())
_tool_sys.path.insert(0, str(TOOLS_ROOT))
import tool_bootstrap as _tool_bootstrap
_tool_bootstrap.activate(__file__)
REPO_ROOT = TOOLS_ROOT.parent
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path


def audit(assignments, reference):
    flags = assignments['named_flag_evidence']
    surfaces = assignments['surface_enum_evidence']
    climbs = assignments['traversal_enum_evidence']
    controls = {r['name'] for r in reference['material_property_reference']['fields']}
    surface_values = {int(r['field_12'], 16): r['name'] for r in surfaces}
    climb_values = {int(r['field_12'], 16): r['name'] for r in climbs}
    filters = assignments['filter_entries']
    content_mask = 0x03ffffff

    def encode(properties):
        sw = co = 0
        for flag in flags:
            if properties.get(flag['name']) == '1':
                sw |= int(flag['field_12'], 16)
                co |= int(flag['field_16'], 16) & content_mask
        for table, field in ((surfaces, 'surfaceType'), (climbs, 'surfaceClimbType')):
            for row in table:
                if properties.get(field) == row['name']:
                    sw |= int(row['field_12'], 16)
                    co |= int(row['field_16'], 16) & content_mask
        return sw, co

    stock = [(m, encode(m['properties'])) for m in reference['materials']]
    groups = {}
    for key, brush in assignments['brushes'].items():
        paired = brush['filter_association'] == 'pointer_backed_union_verified'
        values = sorted({(int(filters[i]['surface_raw'], 16), int(filters[i]['contents_raw'], 16))
                         for i in brush['side_filter_indices']}) if paired else []
        signature = json.dumps([paired, values, brush['contents_raw'], brush['unknown_contents']])
        if signature in groups:
            groups[signature]['brushes'].append(key)
            continue
        blockers = []
        row = dict(brushes=[key], source_filters=values,
                   current_assignment=brush['decision']['material'], stock_matches=[],
                   blockers=blockers, recipe=None)
        groups[signature] = row
        if not paired:
            blockers.append('Filter ownership unresolved; raw indices do not prove surface names')
        elif len(values) != 1:
            blockers.append('Mixed side profiles require side-to-polygon mapping')
        if int(brush['unknown_contents'], 16):
            blockers.append('Unknown/base-solid contents require decoding before custom authoring')
        if blockers:
            row['status'] = 'needs_source_decode'
            continue
        sw, co = values[0]
        for material, encoded in stock:
            if encoded == (sw, co):
                row['stock_matches'].append({k: material.get(k) for k in ('name', 'source', 'line', 'parent')})
        if row['stock_matches']:
            row['status'] = 'stock_named_profile_available'
            continue
        decision = brush['decision']
        if (decision['status'] in ('CLOSEST_BO3_APPLIED','APPROXIMATE_BO3_TOOL')
                and not decision['omitted_contents'] and len(decision['added_contents']) <= 1
                and len(decision['omitted_surface_flags']) + len(decision['added_surface_flags']) <= 1
                and decision.get('bo3_climb_type','<none>') == (brush['traversal']['name'] or '<none>')):
            row['status'] = 'similar_stock_preferred'
            row['stock_approximation'] = {k:decision.get(k) for k in
                ('material','source','source_line','added_contents','omitted_contents',
                 'added_surface_flags','omitted_surface_flags','bo3_surface_type','surface_type_match')}
            row['preference'] = 'Use a similar installed BO3 type before creating a custom material; recorded differences still need gameplay testing'
            continue
        surface = surface_values.get(sw & 0x03f00000)
        climb = climb_values.get(sw & 0x38000000)
        if surface is None:
            blockers.append('Default/unknown CW surface is not proven equivalent to BO3 <none>')
        if sw & 0x38000000 and climb is None:
            blockers.append('Unknown traversal enum')
        if surface and surface not in reference['material_property_reference']['surfaceType']:
            blockers.append('BO3 has no matching surfaceType enum')
        if climb and climb not in reference['material_property_reference']['surfaceClimbType']:
            blockers.append('BO3 has no matching surfaceClimbType enum')
        props = dict(surfaceType=surface or '<none>', surfaceClimbType=climb or '<none>')
        # Enums contribute contents too. Do not turn mantle-derived mount
        # contents into the separate mount surface checkbox.
        for flag in flags:
            sm = int(flag['field_12'], 16)
            cm = int(flag['field_16'], 16) & content_mask
            if not (sm or cm):
                continue
            enabled = (sw & sm == sm) if sm else (co & cm == cm)
            if flag['name'] in controls:
                props[flag['name']] = '1' if enabled else '0'
            elif enabled:
                blockers.append('No BO3 APE checkbox: ' + flag['name'])
        if props.get('nonColliding') == '1':
            blockers.append('BO3 nonColliding discards BSP collision; needs compiler/behavior review')
        if props.get('noDraw') != '1':
            blockers.append('Source is not an invisible tool profile; render/collision ownership needs review')
        if encode(props) != (sw, co):
            blockers.append('APE property recipe does not reproduce the captured named fields')
        if blockers:
            row['status'] = 'needs_source_or_engine_review'
        else:
            row['status'] = 'ape_recipe_requires_compiler_validation'
            row['recipe'] = dict(name='cw_review_' + hashlib.sha256(signature.encode()).hexdigest()[:12],
                                 base_material=brush['decision']['material'], properties=props,
                                 stock_definitions_examined=len(stock), installed=False,
                                 reason='No exact named profile among supplied installed BO3 materials; use existing APE controls only')
    profiles = list(groups.values())
    return dict(schema='greyhound-stock-first-review-v1', map=assignments['map'],
                stock_materials_examined=len(stock), profiles=profiles,
                summary=dict(unique_brushes=sum(len(r['brushes']) for r in profiles),
                             profiles=len(profiles), profile_statuses=dict(Counter(r['status'] for r in profiles)),
                             brush_statuses=dict(Counter({s:sum(len(r['brushes']) for r in profiles if r['status']==s)
                                                          for s in {r['status'] for r in profiles}}))),
                missing_ape_flag_names=[r['name'] for r in flags if r['name'] not in controls],
                scope='Captured CW named fields compared with installed BO3 authoring properties; raw bits are never copied to BO3. Stock profile matches and recipes still require BO3 compiler/gameplay validation.')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--assignments', required=True, type=Path)
    p.add_argument('--reference', required=True, type=Path)
    p.add_argument('--output', required=True, type=Path)
    a = p.parse_args()
    report = audit(json.loads(a.assignments.read_text()), json.loads(a.reference.read_text()))
    report['sources'] = [dict(file=str(path.resolve()), sha256=hashlib.sha256(path.read_bytes()).hexdigest())
                         for path in (a.assignments, a.reference)]
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report['summary']))


if __name__ == '__main__':
    main()
