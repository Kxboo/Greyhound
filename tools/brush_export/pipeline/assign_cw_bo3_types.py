"""Automatic BO3 clip naming from this capture and the bundled stock catalogue.

Every substitution records added/omitted properties and unknown source fields.
Geometry is unchanged. Similar names are never evidence for a surface flag.
"""
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
from decode_cw_brush_side_filters import decode


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def basic_tool_family(contents, surface, traversal=None):
    """Use named source behavior, never an arbitrary editor-volume alias."""
    names=contents | (surface or set())
    climb={'ladder':'ladder','mantleOn':'mantle_on','mantleOver':'mantle_over',
           'climbWall':'wall_climb','climbPipe':'pipe_climb'}.get(traversal)
    if climb:
        # Mantle's contents include mount already. Only the separate SURFACE
        # mount flag justifies BO3's combined mount_mantle variants.
        if traversal in ('mantleOn','mantleOver') and 'mount' in (surface or set()):climb='mount_'+climb
        return {climb}
    if 'mount' in names:return {'mount'}
    if 'portal' in names:return {'portal'}
    if 'sky' in names:return {'sky'}
    if 'caulk' in names:
        if 'onlyCastSunShadow' in names:return {'caulk_sun_shadow'}
        if 'outdoorOccluder' in names:return {'caulk_outdoor_occluder'}
        return {'caulk_shadow'}
    # Non-solid without collision-query contents is closer to skip than a solid
    # player clip. This does not identify the original volume's authored purpose.
    if 'nonSolid' in names and contents <= {'nonColliding'}:return {'skip'}
    return set()


def build_assignments(normalized, native, reference):
    capture=json.loads((normalized/'capture.json').read_text())
    types=json.loads((native/'brush_type_capture.json').read_text())
    if not types['readback_unchanged'] or int(types['map_hash'],16)!=int(capture['map_hash'],16):
        raise ValueError('Brush types do not belong to this verified map capture')
    cb={r['name']:int(r['field_16'],16) for r in types['named_flags'] if 0<int(r['field_16'],16)<=0x3ffffff}
    sb={r['name']:int(r['field_12'],16) for r in types['named_flags'] if int(r['field_12'],16) and not int(r['field_12'],16)&0x3bf00000}
    traversal_rows=types.get('traversal_flags',[]);traversal_values={}
    for row in traversal_rows:
        value=int(row['field_12'],16)
        if not value or value&~0x38000000 or value in traversal_values:raise ValueError('Invalid traversal enum table')
        traversal_values[value]=row['name']
    def unpack(value,bits):
        names={n for n,b in bits.items() if value&b==b};covered=0
        for n in names:covered|=bits[n]
        return names,value&~covered
    candidates=[]
    for material in reference['materials']:
        name=material['name'];props=material['properties']
        candidates.append((material,{n for n in cb if props.get(n)=='1'},{n for n in sb if props.get(n)=='1'}))
    if not candidates:raise ValueError('Bundled BO3 catalogue has no clip tools')
    filters=[(int(f['surface_raw'],16),int(f['contents_raw'],16)) for f in types['filter_entries']]
    choices={};join_counts=Counter();cache={};slick=[]
    def choose(contents,surface,unknown_c,unknown_s,uniform,traversal):
        key=(tuple(sorted(contents)),None if surface is None else tuple(sorted(surface)),unknown_c,unknown_s,uniform,traversal)
        if key in cache:return cache[key]
        ranked=[];family=basic_tool_family(contents,surface,traversal)
        for m,c,s in candidates:
            c=set(c)
            # BO3 uses a climb enum; CW's enum table also supplies contents
            # contributed by that climb type, separately from named booleans.
            for tr in traversal_rows:
                if tr['name']==m['properties'].get('surfaceClimbType'):
                    c.update(unpack(int(tr['field_16'],16),cb)[0])
            props=m['properties']
            eligible=m['name'] in family if family else (m['name'].startswith('clip') or m['name']=='nosight_noclip') and props.get('noDraw')=='1' and props.get('surfaceType')=='<none>'
            # Positive slick evidence on every side is needed to make a whole
            # output brush slippery. This also protects null-pointer shapes.
            if ('slick' in s) and (surface is None or 'slick' not in surface or not uniform):continue
            extra_c=c-contents;missing_c=contents-c
            extra_s=s-surface if surface is not None else set()
            missing_s=surface-s if surface is not None else set()
            score=12*len(extra_c)+10*len(missing_c)+len(extra_s)+len(missing_s)
            if surface is not None:
                score+=25*len((s^surface)&{'slick','nonSolid'})
            # Prefer generic shipped tools when named fields cannot distinguish
            # campaign-specific aliases. Keep all ties in the audit.
            tie=(0 if m['name'] in {'clip','clip_player','clip_ai','clip_full','clip_nosight','clip_slick','clip_slick_player','clip_physics','clip_missile','nosight_noclip'} else 1,len(m['name']),m['name'])
            exact=not(extra_c or missing_c or extra_s or missing_s or unknown_c or unknown_s) and surface is not None and uniform
            ranked.append((score,tie,dict(material=m['name'],source=m['source'],source_line=m['line'],
                added_contents=sorted(extra_c),omitted_contents=sorted(missing_c),
                added_surface_flags=sorted(extra_s),omitted_surface_flags=sorted(missing_s),
                exact_known_properties=exact,automatic_selection_eligible=eligible,
                bo3_surface_type=props.get('surfaceType'),bo3_climb_type=props.get('surfaceClimbType'),
                bo3_no_draw=props.get('noDraw'),bo3_non_solid=props.get('nonSolid'),
                comparison_scope='Named fields only; compiled contents, surface/climb enums and tool-specific behavior are not proven')))
        ranked.sort(key=lambda x:(x[0],x[1]))
        # Explicit named tool behavior takes precedence over generic clips.
        # Other editor-volume and traversal variants still require their own evidence.
        eligible=[r for r in ranked if r[2]['automatic_selection_eligible']]
        if not eligible:raise ValueError('Bundled BO3 catalogue has no supported automatic clip candidates')
        best=eligible[0][2]
        if not contents and not family:
            # Unknown solid/zero contents cannot justify a newly inferred type.
            best=next(r[2] for r in ranked if r[2]['material']=='clip')
            status='UNRESOLVED_CONTENTS_FALLBACK'
        elif best['exact_known_properties']:status='EXACT_NAMED_PROPERTIES'
        elif surface is None and not best['added_contents'] and not best['omitted_contents'] and not unknown_c:status='CONTENTS_MATCH_SURFACE_UNKNOWN'
        else:status='APPROXIMATE_BO3_TOOL' if family else 'CLOSEST_BO3_APPLIED'
        result=dict(**best,status=status,candidates_examined=len(ranked),automatic_candidates_examined=len(eligible),
            selection_policy='basic_named_tool' if family else 'closest_named_collision_properties',
            reason='Basic BO3 tool selected from named CW behavior; property differences remain in JSON.' if family else 'Closest supported BO3 collision properties are applied; approximation is recorded.',
            closest_candidates=[x[2] for x in ranked[:5]])
        cache[key]=result;return result
    for model in capture['models']:
        if model['status']!='decoded':continue
        raw=(normalized/model['payload']['file']).read_bytes()
        if sha(normalized/model['payload']['file'])!=model['payload']['sha256']:raise ValueError('Payload hash changed')
        sides=decode(raw,model)
        # Raw indices are retained even if the global table cannot be joined.
        in_range=all(s['filter_index']<len(filters) for b in sides['brushes'] for s in b['sides'])
        checked=decode(raw,model,filters) if in_range else None
        joined=bool(sides['pointer_layout_verified'] and checked is not None and not checked['side_contents_union_mismatches'])
        join='pointer_backed_union_verified' if joined else 'unresolved_global_filter_association'
        join_counts[join]+=len(sides['brushes'])
        for b in sides['brushes']:
            mask=int(b['contents'],16);contents,unknown_c=unpack(mask,cb)
            ids=[s['filter_index'] for s in b['sides']];surface=None;unknown_s=None;uniform=False
            traversal=None;traversal_codes=None;traversal_status='unjoined_surface_table'
            if joined:
                sets=[unpack(filters[i][0]&~0x3bf00000,sb) for i in ids]
                uniform=all(x==sets[0] for x in sets)
                surface=set.intersection(*(s for s,_ in sets));unknown_s=0
                for _,u in sets:unknown_s|=u
                traversal_codes=[filters[i][0]&0x38000000 for i in ids]
                distinct=set(traversal_codes)
                if distinct=={0}:traversal_status='none'
                elif not traversal_values:traversal_status='enum_table_not_captured'
                elif len(distinct)!=1:traversal_status='mixed_sides_retained'
                else:
                    traversal=traversal_values.get(next(iter(distinct)))
                    traversal_status='uniform_named_enum' if traversal else 'unknown_enum_value'
            decision=dict(choose(contents,surface,unknown_c,unknown_s,uniform,traversal))
            if traversal_status in ('enum_table_not_captured','mixed_sides_retained','unknown_enum_value'):
                decision['exact_known_properties']=False
                if decision['status']=='EXACT_NAMED_PROPERTIES':decision['status']='APPROXIMATE_BO3_TOOL'
            decision['suggested_material']=decision['material']
            if decision['status']=='UNRESOLVED_CONTENTS_FALLBACK':
                # Only genuinely unidentified behavior keeps the old fallback.
                # Named tools and closest collision matches are no longer erased.
                from export_cw_radiant_brushes import CHOICES
                fallback=CHOICES.get(mask,'clip')
                actual,actual_c,actual_s=next(x for x in candidates if x[0]['name']==fallback)
                decision.update(material=fallback,
                    source=actual['source'],source_line=actual['line'],exact_known_properties=False,
                    bo3_surface_type=actual['properties'].get('surfaceType'),
                    bo3_climb_type=actual['properties'].get('surfaceClimbType'),
                    bo3_no_draw=actual['properties'].get('noDraw'),bo3_non_solid=actual['properties'].get('nonSolid'),
                    added_contents=sorted(actual_c-contents),omitted_contents=sorted(contents-actual_c),
                    added_surface_flags=sorted(actual_s-surface) if surface is not None else [],
                    omitted_surface_flags=sorted(surface-actual_s) if surface is not None else [],
                    status='REVIEW_EXISTING_FALLBACK',
                    reason='No identified tool behavior or collision-query contents; retained unresolved fallback.')
            key=f"{model['index']}:{b['brush_index']}"
            choices[key]=dict(asset_index=model['index'],collision_hash=model['name_hash'],brush_index=b['brush_index'],
                contents_raw=hex(mask),named_contents=sorted(contents),unknown_contents=hex(unknown_c),
                common_surface_flags=sorted(surface) if surface is not None else None,
                unknown_surface_bits=hex(unknown_s) if unknown_s is not None else None,
                uniform_surface_flags=uniform,filter_association=join,side_filter_indices=ids,decision=decision)
            choices[key]['traversal']=dict(status=traversal_status,name=traversal,
                side_values=[hex(v) for v in traversal_codes] if traversal_codes is not None else None)
            if decision['material']=='clip_slick':slick.append(key)
    return dict(schema='greyhound-bo3-material-assignments-v2',map=capture['map'],map_hash=capture['map_hash'],
        catalogue_materials=len(reference['materials']),catalogue_sources=reference['sources'],
        type_capture_sha256=sha(native/'brush_type_capture.json'),filter_entries=types['filter_entries'],
        named_flag_evidence=types['named_flags'],brushes=choices,
        traversal_enum_evidence=traversal_rows,
        tool_image_references=reference.get('tool_images',[]),
        material_property_reference=reference.get('material_property_reference',{}),
        summary=dict(unique_brushes=len(choices),filter_associations=dict(join_counts),
            verified_all_sides_no_draw=sum(x['common_surface_flags'] is not None and 'noDraw' in x['common_surface_flags'] for x in choices.values()),
            chosen_materials=dict(Counter(x['decision']['material'] for x in choices.values())),
            statuses=dict(Counter(x['decision']['status'] for x in choices.values()))),
        limitations=['Named-property matches are not proof of identical BO3/CW gameplay.',
            'Basic named tools and closest supported collision matches are applied; differences and approximations are recorded.',
            'Null-pointer shapes do not inherit global-table surface names. Mixed sides need future side-to-polygon mapping.',
            'Uniform traversal enums select ladder, mantle and climbing tools; mixed or unjoined sides retain unresolved metadata.',
            'Categories and traversal encodings are preserved in raw filter words; no original authored texture claim.'])


def apply(normalized,native,reference,geometry):
    report=build_assignments(normalized,native,reference)
    path=geometry/'collision_metadata.json';metadata=json.loads(path.read_text());target=geometry/(metadata['map']+'_brush_collision.map')
    if sha(target)!=metadata['map_sha256']:raise ValueError('Map changed before type assignment')
    source=target.read_text();rows=metadata['rows'];layers={'000_Global','000_Global/CW_Types'}
    for row in rows:
        key=f"{row['collision_asset_index']}:{row['brush_index']}";item=report['brushes'][key]
        if int(row['collision_hash'],16)!=int(item['collision_hash'],16):raise ValueError('Type-to-brush identity mismatch')
        row['previous_material']=row['assigned_material'];row['assigned_material']=item['decision']['material']
        row['assignment_status']=item['decision']['status'];row['material_assignment_key']=key
        row['layer']='000_Global/CW_Types/'+row['assignment_status']+'/'+row['assigned_material']
        layers.update(['000_Global/CW_Types/'+row['assignment_status'],row['layer']])
    lines=[];index=None;faces=0;body=False
    pattern=re.compile(r'^(\s*\(.*\)\s+)(\S+)(\s+64 64 .*)$')
    for line in source.splitlines():
        if line.startswith('// entity '):body=True
        if not body:continue
        if line.startswith('// brush '):
            index=int(line.split()[-1])
            if index!=rows[index]['map_brush_index']:raise ValueError('Map brush order changed')
        if index is not None and line.startswith('layer '):line='layer "'+rows[index]['layer']+'"'
        match=pattern.fullmatch(line)
        if match:
            if index is None or match[2]!=rows[index]['previous_material']:raise ValueError('Map material/metadata mismatch')
            line=match[1]+rows[index]['assigned_material']+match[3];faces+=1
        elif line.lstrip().startswith('('):raise ValueError('Unrecognized map face')
        lines.append(line)
    if faces!=sum(r['face_count'] for r in rows):raise ValueError('Face coverage changed')
    result='\n'.join(['iwmap 4',*[f'"{l}" flags'+(' active' if l=='000_Global' else '') for l in sorted(layers)],*lines,''])
    before=[(m[1],m[3]) for l in source.splitlines() if (m:=pattern.fullmatch(l))]
    after=[(m[1],m[3]) for l in result.splitlines() if (m:=pattern.fullmatch(l))]
    if before!=after:raise ValueError('Type assignment changed geometry or projections')
    target.write_text(result);metadata['map_sha256']=sha(target)
    metadata['material_policy']='Basic named BO3 tools and closest collision matches are applied. Exact, contents-only, approximate and unidentified fallback assignments are distinguished in JSON.'
    report['placed_piece_material_counts']=dict(Counter(r['assigned_material'] for r in rows))
    report['geometry_and_projections_unchanged']=True
    (geometry/'material_assignments.json').write_text(json.dumps(report,indent=2))
    path.write_text(json.dumps(metadata,indent=2))
    return report
