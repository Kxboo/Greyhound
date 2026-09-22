"""Automatic BO3 clip naming from this capture and the bundled stock catalogue.

Every substitution records added/omitted properties and unknown source fields.
Geometry is unchanged. Similar names are never evidence for a surface flag.
"""

# Support direct execution and the isolated packaged Python runtime.
import sys as _tool_sys
from pathlib import Path as _ToolPath
TOOLS_ROOT = next(p for p in _ToolPath(__file__).resolve().parents if (p / "tool_bootstrap.py").is_file())
_tool_sys.path.insert(0, str(TOOLS_ROOT))
import tool_bootstrap as _tool_bootstrap
_tool_bootstrap.activate(__file__)
REPO_ROOT = TOOLS_ROOT.parent
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
from decode_cw_brush_side_filters import decode


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


RELATED_SURFACE_TYPES = {
    'metalcatwalk':'metal', 'metalcar':'metal', 'metalhollow':'metal',
    'metalthin':'metal', 'paintedmetal':'metal', 'glasscar':'glass',
    'glassbulletproof':'glass', 'watershallow':'water', 'tallgrass':'grass',
    'bark':'wood',
    # Authoring approximations where BO3 has no stock invisible tool for the
    # captured enum. These are response families, not decoded enum aliases.
    'asphalt':'concrete', 'ceramic':'brick', 'rubber':'plastic', 'paper':'cloth',
}


def material_score(missing, added, surface, actual_surface, distance):
    # Preserve query behavior before appearance. Within that constraint, a
    # surface-specific stock tool may add itemClip rather than erase a known
    # surface enum. The additional item response stays explicit in the audit.
    return (len(missing), len(added-{'itemClip'}),
            len((actual_surface^surface)&{'slick','nonSolid'}) if surface is not None else 0,
            distance, len(added),
            len(actual_surface^surface) if surface is not None else 0)


def surface_distance(source, target):
    """Explicit stock-family approximation, never an exact enum equivalence."""
    if source is None:return 0 if target=='<none>' else 3
    if source==target:return 0
    if RELATED_SURFACE_TYPES.get(source)==target:return 1
    return 2 if target=='<none>' else 3


def basic_tool_family(contents, surface, traversal=None):
    """Use named source behavior, never an arbitrary editor-volume alias."""
    names=contents | (surface or set())
    climb={'ladder':'ladder','mantleOn':'mantle_on','mantleOver':'mantle_over',
           'climbWall':'wall_climb','climbPipe':'pipe_climb'}.get(traversal)
    if climb:
        # Mantle's contents include mount already. Only the separate SURFACE
        # mount flag justifies BO3's combined mount_mantle variants.
        if traversal in ('mantleOn','mantleOver') and 'mount' in (surface or set()):climb='mount_'+climb
        if climb=='ladder':return {'ladder','ladder_metal','ladder_wood'}
        return {climb}
    if 'mount' in names:return {'mount'}
    if 'portal' in names:return {'portal'}
    if 'sky' in names:return {'sky'}
    if 'caulk' in names:
        return {'caulk','caulk_shadow','caulk_shadow_primary','caulk_transparent',
                'caulk_sun_shadow','caulk_outdoor_occluder'}
    # Non-solid without collision-query contents is closer to skip than a solid
    # player clip. This does not identify the original volume's authored purpose.
    if 'nonSolid' in names and contents <= {'nonColliding'}:return {'skip','nodraw_notsolid'}
    return set()


def build_assignments(normalized, native, reference):
    capture=json.loads((normalized/'capture.json').read_text())
    types=json.loads((native/'brush_type_capture.json').read_text())
    if not types['readback_unchanged'] or int(types['map_hash'],16)!=int(capture['map_hash'],16):
        raise ValueError('Brush types do not belong to this verified map capture')
    cb={r['name']:int(r['field_16'],16) for r in types['named_flags'] if 0<int(r['field_16'],16)<=0x3ffffff}
    sb={r['name']:int(r['field_12'],16) for r in types['named_flags'] if int(r['field_12'],16) and not int(r['field_12'],16)&0x3bf00000}
    traversal_rows=types.get('traversal_flags',[]);traversal_values={}
    surface_rows=types.get('surface_types',[]);surface_values={}
    for row in surface_rows:
        value=int(row['field_12'],16)
        if not value or value&~0x03f00000 or value in surface_values:raise ValueError('Invalid surface enum table')
        surface_values[value]=row['name']
    # Surface enum declarations also contribute contents (glass variants share
    # one contents bit). Decode each shared bit once, using its canonical name.
    for row in surface_rows:
        if row['name'] in ('glass','water','foliage') and int(row['field_16'],16):
            cb[row['name']]=int(row['field_16'],16)
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
    primary_names={m['name'] for m,_,_ in candidates}
    comparison_candidates=list(candidates)
    for material in reference.get('supplemental_materials',[]):
        props=material['properties']
        comparison_candidates.append((material,{n for n in cb if props.get(n)=='1'},
                                      {n for n in sb if props.get(n)=='1'}))
    filters=[(int(f['surface_raw'],16),int(f['contents_raw'],16)) for f in types['filter_entries']]
    choices={};join_counts=Counter();cache={};slick=[];candidate_profiles={}
    def choose(contents,surface,unknown_c,unknown_s,uniform,traversal,surface_counts):
        preferred=min(surface_counts,key=lambda n:(-surface_counts[n],n)) if surface_counts else None
        key=(tuple(sorted(contents)),None if surface is None else tuple(sorted(surface)),unknown_c,unknown_s,uniform,traversal,tuple(sorted(surface_counts.items())))
        if key in cache:return cache[key]
        ranked=[];family=basic_tool_family(contents,surface,traversal)
        for m,c,s in comparison_candidates:
            c=set(c)
            # BO3 uses a climb enum; CW's enum table also supplies contents
            # contributed by that climb type, separately from named booleans.
            for tr in traversal_rows:
                if tr['name']==m['properties'].get('surfaceClimbType'):
                    c.update(unpack(int(tr['field_16'],16),cb)[0])
            props=m['properties']
            for sr in surface_rows:
                if sr['name']==props.get('surfaceType'):
                    c.update(unpack(int(sr['field_16'],16),cb)[0])
            allowed_surfaces=set(surface_counts)|{RELATED_SURFACE_TYPES[n] for n in surface_counts if n in RELATED_SURFACE_TYPES}|{'<none>'}
            reasons=[]
            if m['name'] not in primary_names:reasons.append('supplemental_engine_or_render_tool_requires_role_evidence')
            if family:
                if m['name'] not in family:reasons.append('different_named_tool_family')
            else:
                if not ('clip' in m['name'].split('_') or m['name']=='nosight_noclip'):
                    reasons.append('different_editor_role_requires_evidence')
                if props.get('noDraw')!='1':reasons.append('visible_material_for_collision_capture')
                if props.get('surfaceType') not in allowed_surfaces:reasons.append('different_surface_family')
            # Positive slick evidence on every side is needed to make a whole
            # output brush slippery. This also protects null-pointer shapes.
            if ('slick' in s) and (surface is None or 'slick' not in surface or not uniform):
                reasons.append('slick_requires_verified_uniform_sides')
            eligible=not reasons
            extra_c=c-contents;missing_c=contents-c
            extra_s=s-surface if surface is not None else set()
            missing_s=surface-s if surface is not None else set()
            surface_match=preferred is not None and props.get('surfaceType')==preferred
            score=material_score(missing_c,extra_c,surface,s,
                                 surface_distance(preferred,props.get('surfaceType')))
            # Prefer generic shipped tools when named fields cannot distinguish
            # campaign-specific aliases. Keep all ties in the audit.
            tie=(0 if m['name'] in {'clip','clip_player','clip_ai','clip_full','clip_nosight','clip_slick','clip_slick_player','clip_physics','clip_missile','nosight_noclip','caulk_shadow'} else 1,len(m['name']),m['name'])
            exact=not(extra_c or missing_c or extra_s or missing_s or unknown_c or unknown_s) and surface is not None and uniform and (preferred is None or surface_match) and len(surface_counts)<=1
            ranked.append((score,tie,dict(material=m['name'],source=m['source'],source_line=m['line'],
                added_contents=sorted(extra_c),omitted_contents=sorted(missing_c),
                added_surface_flags=sorted(extra_s),omitted_surface_flags=sorted(missing_s),
                exact_known_properties=exact,automatic_selection_eligible=eligible,
                not_automatically_applied_reasons=reasons,ranking_score=list(score),
                bo3_surface_type=props.get('surfaceType'),bo3_climb_type=props.get('surfaceClimbType'),
                bo3_no_draw=props.get('noDraw'),bo3_non_solid=props.get('nonSolid'),
                preferred_source_surface=preferred,source_surface_counts=dict(surface_counts),
                surface_type_retained=surface_match,
                surface_type_match='exact_named_enum' if surface_match else 'related_stock_family' if surface_distance(preferred,props.get('surfaceType'))==1 else 'generic_or_different',
                comparison_scope='Named fields only; compiled contents, surface/climb enums and tool-specific behavior are not proven')))
        ranked.sort(key=lambda x:(x[0],x[1]))
        # Keep every comparison once per semantic profile, rather than copying
        # hundreds of candidates into every placed brush. Side-by-side source
        # words and counts remain on the brush itself; no candidates are hidden.
        profile_source=dict(named_contents=sorted(contents),
            common_surface_flags=sorted(surface) if surface is not None else None,
            unknown_contents=hex(unknown_c),unknown_surface_bits=hex(unknown_s) if unknown_s is not None else None,
            uniform_surface_flags=uniform,traversal=traversal,
            surface_types=sorted(surface_counts),preferred_source_surface=preferred)
        profile_id=hashlib.sha256(json.dumps(profile_source,sort_keys=True).encode()).hexdigest()[:16]
        if profile_id not in candidate_profiles:
            candidate_profiles[profile_id]=dict(source=profile_source,
                candidates=[dict(rank=i+1,**{k:v for k,v in r[2].items() if k!='source_surface_counts'})
                            for i,r in enumerate(ranked)])
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
            candidate_profile=profile_id,
            selection_policy='basic_named_tool' if family else 'closest_named_collision_properties',
            reason='Basic BO3 tool selected from named CW behavior; property differences remain in JSON.' if family else 'Closest supported BO3 collision properties are applied; approximation is recorded.',
            closest_candidates=[x[2] for x in ranked[:5]])
        cache[key]=result;return result
    for model in capture['models']:
        if model['status']!='decoded':continue
        raw=(normalized/model['payload']['file']).read_bytes()
        if sha(normalized/model['payload']['file'])!=model['payload']['sha256']:raise ValueError('Payload hash changed')
        sides=decode(raw,model)
        for b in sides['brushes']:
            mask=int(b['contents'],16);contents,unknown_c=unpack(mask,cb)
            ids=[s['filter_index'] for s in b['sides']];surface=None;unknown_s=None;uniform=False
            # The array layout belongs to the asset, but a contents union belongs
            # to one brush. A bad sibling must not erase independently matching
            # source evidence across an otherwise pointer-verified asset.
            in_range=bool(ids) and all(0<=i<len(filters) for i in ids)
            side_union=0
            if in_range:
                for i in ids:side_union|=filters[i][1]
            joined=bool(sides['pointer_layout_verified'] and in_range and side_union==mask)
            join='pointer_backed_union_verified' if joined else 'unresolved_global_filter_association'
            join_counts[join]+=1
            traversal=None;traversal_codes=None;traversal_status='unjoined_surface_table'
            surface_counts=Counter();surface_codes=[]
            if joined:
                surface_codes=[filters[i][0]&0x03f00000 for i in ids]
                surface_counts.update(surface_values[v] for v in surface_codes if v in surface_values)
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
            decision=dict(choose(contents,surface,unknown_c,unknown_s,uniform,traversal,surface_counts))
            if any(v and v not in surface_values for v in surface_codes):
                decision['exact_known_properties']=False
                if decision['status']=='EXACT_NAMED_PROPERTIES':decision['status']='APPROXIMATE_BO3_TOOL'
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
                # An unresolved contents bit does not invalidate a separately
                # verified, uniform surface enum. Preserve that response using
                # the closest stock variant of the existing clip fallback.
                # Do not infer base-solid compiler behavior or pick a majority
                # surface for mixed/default/unknown sides.
                surface_fallback=False
                if (joined and surface_codes and len(set(surface_codes))==1
                        and surface_codes[0] in surface_values):
                    source_surface=surface_values[surface_codes[0]]
                    variants=[(m,c,s) for m,c,s in candidates
                        if surface_distance(source_surface,m['properties'].get('surfaceType'))<=1
                        and m['properties'].get('usage')=='clip'
                        and m['properties'].get('noDraw')=='1'
                        and actual_c <= c and ('slick' not in s or (uniform and 'slick' in surface))
                        and m['properties'].get('surfaceClimbType','<none>')=='<none>']
                    if variants:
                        actual,actual_c,actual_s=min(variants,key=lambda x:(
                            len((x[1]-actual_c)-{'itemClip'}),
                            surface_distance(source_surface,x[0]['properties'].get('surfaceType')),
                            len(x[1]-actual_c),len(x[2]^actual_s),len(x[0]['name']),x[0]['name']))
                        fallback=actual['name'];surface_fallback=True
                decision.update(material=fallback,
                    source=actual['source'],source_line=actual['line'],exact_known_properties=False,
                    bo3_surface_type=actual['properties'].get('surfaceType'),
                    bo3_climb_type=actual['properties'].get('surfaceClimbType'),
                    bo3_no_draw=actual['properties'].get('noDraw'),bo3_non_solid=actual['properties'].get('nonSolid'),
                    added_contents=sorted(actual_c-contents),omitted_contents=sorted(contents-actual_c),
                    added_surface_flags=sorted(actual_s-surface) if surface is not None else [],
                    omitted_surface_flags=sorted(surface-actual_s) if surface is not None else [],
                    surface_type_retained=bool(surface_counts) and actual['properties'].get('surfaceType') in surface_counts,
                    surface_type_match=('exact_named_enum' if actual['properties'].get('surfaceType')==source_surface
                        else 'related_stock_family') if surface_fallback else 'generic_or_different',
                    status='REVIEW_STOCK_SURFACE_FALLBACK' if surface_fallback else 'REVIEW_EXISTING_FALLBACK',
                    selection_policy='stock_surface_variant_of_unresolved_clip' if surface_fallback else decision['selection_policy'],
                    reason=('Verified uniform surface matched to an exact or explicitly related stock variant of the existing clip fallback. '
                            'Unresolved contents and added query properties still require review.' if surface_fallback else
                            'No identified tool behavior or collision-query contents; retained unresolved fallback.'))
            key=f"{model['index']}:{b['brush_index']}"
            choices[key]=dict(asset_index=model['index'],collision_hash=model['name_hash'],brush_index=b['brush_index'],
                contents_raw=hex(mask),named_contents=sorted(contents),unknown_contents=hex(unknown_c),
                common_surface_flags=sorted(surface) if surface is not None else None,
                unknown_surface_bits=hex(unknown_s) if unknown_s is not None else None,
                uniform_surface_flags=uniform,filter_association=join,side_filter_indices=ids,decision=decision)
            choices[key]['filter_validation']=dict(scope='source_brush',
                pointer_layout_verified=bool(sides['pointer_layout_verified']),
                indices_in_range=in_range,side_contents_union=hex(side_union) if in_range else None,
                source_contents=hex(mask),union_matches_brush=in_range and side_union==mask)
            choices[key]['traversal']=dict(status=traversal_status,name=traversal,
                side_values=[hex(v) for v in traversal_codes] if traversal_codes is not None else None)
            choices[key]['surface_types']=dict(counts=dict(surface_counts),side_values=[hex(v) for v in surface_codes],
                unknown_values=sorted({hex(v) for v in surface_codes if v and v not in surface_values}))
            if decision['material']=='clip_slick':slick.append(key)
    for profile_id,profile in candidate_profiles.items():
        keys=[key for key,b in choices.items() if b['decision']['candidate_profile']==profile_id]
        profile['brush_keys']=keys
        profile['chosen_material_counts']=dict(Counter(choices[key]['decision']['material'] for key in keys))
    return dict(schema='greyhound-bo3-material-assignments-v5',map=capture['map'],map_hash=capture['map_hash'],
        related_surface_families=RELATED_SURFACE_TYPES,
        material_preference_policy='Preserve omitted query flags, added non-item queries and slick/nonSolid first; then prefer exact surface, documented related family, generic. An extra itemClip flag is recorded but does not erase an otherwise compatible surface match. Related families are authoring approximations, not recovered texture identities.',
        catalogue_materials=len(reference['materials']),catalogue_sources=reference['sources'],
        compared_materials=len(comparison_candidates),candidate_profiles=candidate_profiles,
        candidate_comparison_scope='Every primary and supplemental tool is listed for every source profile, including candidates not automatically applied. No top-N truncation; closest_candidates is a convenience preview only.',
        type_capture_sha256=sha(native/'brush_type_capture.json'),filter_entries=types['filter_entries'],
        named_flag_evidence=types['named_flags'],brushes=choices,
        traversal_enum_evidence=traversal_rows,
        surface_enum_evidence=surface_rows,
        tool_image_references=reference.get('tool_images',[]),
        material_property_reference=reference.get('material_property_reference',{}),
        summary=dict(unique_brushes=len(choices),filter_associations=dict(join_counts),
            verified_all_sides_no_draw=sum(x['common_surface_flags'] is not None and 'noDraw' in x['common_surface_flags'] for x in choices.values()),
            chosen_materials=dict(Counter(x['decision']['material'] for x in choices.values())),
            statuses=dict(Counter(x['decision']['status'] for x in choices.values()))),
        limitations=['Named-property matches are not proof of identical BO3/CW gameplay.',
            'Basic named tools and closest supported collision matches are applied; differences and approximations are recorded.',
            'Null-pointer shapes do not inherit global-table surface names. Mixed sides need future side-to-polygon mapping.',
            'Pointer-backed filter indices and contents unions are checked per brush; a mismatched sibling does not invalidate other brushes.',
            'A verified uniform surface may refine an unresolved clip fallback, but does not decode base-solid contents or prove matching collision behavior.',
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
