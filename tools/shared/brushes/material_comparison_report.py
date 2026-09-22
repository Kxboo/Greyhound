"""Readable inventories accompanying the exhaustive captured-property comparison."""

from collections import Counter


QUERY_FLAGS = ('playerClip','aiClip','vehicleClip','playerVehicleClip','itemClip',
               'missileClip','bulletClip','aiSightClip','canShootClip','utilityClip')


def cell(value):
    if isinstance(value, (list, tuple, set)):
        value = ', '.join(str(v) for v in value)
    return str(value if value is not None else 'unknown').replace('|', '\\|').replace('<', '&lt;').replace('>', '&gt;') or 'none'


def reports(reference, assignments, audit):
    materials = [*reference['materials'], *reference.get('supplemental_materials', [])]
    primary = {m['name'] for m in reference['materials']}
    brushes = assignments.get('brushes', {})
    profiles = assignments.get('candidate_profiles', {})
    chosen = Counter(b.get('decision', {}).get('material') for b in brushes.values())
    lines = ['# All stock material options for this capture', '',
        f"{len(brushes):,} unique captured brushes; {len(profiles)} comparison profiles; "
        f"{len(materials)} tool/invisible definitions ({len(primary)} primary, {len(materials)-len(primary)} supplemental).", '',
        'Every profile compares every listed tool, including caulk, slick, traversal, volumes, invisible, engine and render tools. '
        'The full ranked comparisons, property differences, automatic-selection reasons and brush keys are in '
        '`material_assignments.json` → `candidate_profiles`. The five-item `closest_candidates` field is only a preview. '
        'Not automatically applied means that role/property evidence is missing; it does not remove the source brush or hide the candidate.', '',
        'Captured collision hashes and flags do not establish original authored texture names. '
        'Unknown contents, unjoined filters and mixed surfaces remain explicit. Matching named fields does not establish compiler/gameplay equivalence.', '',
        '## Caulk and emitted prefab materials', '',
        'Caulk belongs in the other-brushes prefab because the role split puts clip-named tools in the collision prefab. '
        'Import both categories to include both. Counts below are unique captured brushes, not repeated placed pieces.', '',
        '| Caulk material | Selected unique brushes | Shader type | nonSolid | nonColliding | noCastShadow | onlyCastSunShadow | outdoorOccluder |',
        '|---|---:|---|---|---|---|---|---|']
    for m in sorted(materials, key=lambda m:m['name']):
        if 'caulk' in m['name']:
            p=m['properties']
            lines.append('| '+' | '.join(cell(v) for v in [m['name'],chosen[m['name']],
                *[p.get(k) for k in ('materialType','nonSolid','nonColliding','noCastShadow','onlyCastSunShadow','outdoorOccluder')]])+' |')
    lines += ['', '| Emitted prefab | Material | Faces |', '|---|---|---:|']
    for row in audit['maps']:
        for name,count in sorted(row['face_material_counts'].items()):
            lines.append(f"| {cell(row['file'])} | {cell(name)} | {count} |")
    lines += ['', '## Every captured named flag', '',
              '| Flag | Captured surface word | Captured contents word |', '|---|---|---|']
    for row in assignments.get('named_flag_evidence', []):
        lines.append('| '+' | '.join(cell(row.get(k)) for k in ('name','field_12','field_16'))+' |')
    lines += ['', '## Every captured traversal type', '',
        '| Traversal enum | Captured surface word | Captured contents word | Stock tools |','|---|---|---|---|']
    for row in assignments.get('traversal_enum_evidence', []):
        matches=sorted(m['name'] for m in materials if m['properties'].get('surfaceClimbType')==row['name'])
        lines.append('| '+' | '.join(cell(v) for v in [row['name'],row['field_12'],row['field_16'],matches])+' |')
    lines += ['', '## Every captured surface type and its stock tools', '',
        'A listed enum exists in the captured type table; the brush count shows whether it occurred in a verified brush association. '
        'A missing exact stock tool stays visible. Related or generic alternatives and their changes appear in the profile comparison.', '',
        '| Surface enum | Unique brushes with this verified surface | Stock tools with this exact surface |', '|---|---:|---|']
    surfaces=Counter(n for b in brushes.values() for n in b.get('surface_types',{}).get('counts',{}))
    for row in assignments.get('surface_enum_evidence', []):
        name=row['name']
        matches=sorted(m['name'] for m in materials if m['properties'].get('surfaceType')==name)
        lines.append(f"| {cell(name)} | {surfaces[name]} | {cell(matches) if matches else 'No stock tool with this exact enum'} |")
    lines += ['', '## Every source profile', '',
        'Each profile below has the complete tool list in the JSON, including all candidates needing additional evidence. '
        'The table names the current selections and all candidates eligible under the automatic policy. '
        'Ranking retains queries and limits added non-item queries and slick/nonSolid changes first; '
        'then exact or documented related surfaces precede generic tools, with extra itemClip recorded. '
        'For unresolved contents the selected fallback can differ from the first comparison result.', '',
        '| Profile ID | Unique brushes | Contents | Common surface flags | Surface enums | Unknown contents / surface | Selected | Automatically eligible options |',
        '|---|---:|---|---|---|---|---|---|']
    for profile_id,profile in sorted(profiles.items()):
        s=profile['source']
        values=[profile_id,len(profile['brush_keys']),s['named_contents'],s['common_surface_flags'],s['surface_types'],
            f"{s['unknown_contents']} / {s['unknown_surface_bits']}",
            ', '.join(f'{k} ({v})' for k,v in sorted(profile['chosen_material_counts'].items())),
            [c['material'] for c in profile['candidates'] if c['automatic_selection_eligible']]]
        lines.append('| '+' | '.join(cell(v) for v in values)+' |')
    lines += ['', '## Complete tool/invisible catalogue', '',
        'No entries are removed for lack of a match. Supplemental engine, shader, debug and FX tools remain in every comparison; '
        'their presence in the installation does not establish their suitability for a captured collision brush.', '',
        '| Material | Catalogue | Surface | Climb | Query flags | noDraw / nonSolid / nonColliding | Source GDT and line |',
        '|---|---|---|---|---|---|---|']
    for m in sorted(materials,key=lambda m:m['name']):
        p=m['properties']
        values=[m['name'],'primary' if m['name'] in primary else 'supplemental',p.get('surfaceType'),p.get('surfaceClimbType'),
            [k for k in QUERY_FLAGS if p.get(k)=='1'],' / '.join(p.get(k,'unknown') for k in ('noDraw','nonSolid','nonColliding')),
            f"{m.get('source','unknown')}:{m.get('line','unknown')}"]
        lines.append('| '+' | '.join(cell(v) for v in values)+' |')
    lines += ['', 'Full definitions, inherited properties, source hashes, tool image aliases and all remaining render-material names '
              'are in `bo3_stock_reference.json`. `BO3_RENDER_MATERIALS.md` lists the render inventory; '
              '`CAPTURED_BRUSH_MATERIALS.md` lists every captured brush identity and selected material.', '']
    captured=['# Every captured brush material', '',
        'One row per unique source brush. Repeated placed pieces refer to these keys in `collision_metadata.json`. '
        'The collision hash identifies the captured asset; it is not an authored texture name. '
        'Every profile ID resolves to the complete candidate comparison in `material_assignments.json`.', '',
        '| Brush key | Collision asset hash | Contents word | Filter association | Selected material | Profile ID |', '|---|---|---|---|---|---|']
    for key,b in sorted(brushes.items(),key=lambda item:tuple(int(i) for i in item[0].split(':'))):
        d=b.get('decision',{})
        captured.append('| '+' | '.join(cell(v) for v in [key,b.get('collision_hash'),b.get('contents_raw'),
            b.get('filter_association'),d.get('material'),d.get('candidate_profile')])+' |')
    render=['# Remaining installed render materials', '',
        'These installed materials are retained in the inventory, beyond the tool/invisible definitions in `STOCK_MATERIALS.md`. '
        'Collision flags do not reveal which visible texture was originally authored. '
        'This is an availability inventory, not a claim that each texture is a suitable invisible collision replacement.', '',
        '| Material | Surface | Shader type | Usage | Source GDT and line |','|---|---|---|---|---|']
    for m in sorted(reference.get('other_material_inventory',[]),key=lambda m:m['name']):
        render.append('| '+' | '.join(cell(v) for v in [m['name'],m['surfaceType'],m['materialType'],m['usage'],f"{m['source']}:{m['line']}"])+' |')
    return {'STOCK_MATERIALS.md':'\n'.join(lines),'CAPTURED_BRUSH_MATERIALS.md':'\n'.join(captured)+'\n',
            'BO3_RENDER_MATERIALS.md':'\n'.join(render)+'\n'}
