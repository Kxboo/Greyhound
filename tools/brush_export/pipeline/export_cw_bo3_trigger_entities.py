"""Export source-owned CW trigger hulls and parameter entities using bundled BO3 classes."""
from collections import Counter
import json
import math
from pathlib import Path
import re
import numpy as np
from export_cw_bo3_player_volumes import map_identity, hull_planes, quoted, sha
from map_cw_trigger_ownership import run as ownership
from cw_canonical_map_planes import CanonicalPlaneWriter
from exact_cw_brush_halfspaces import reconstruct_exact
from build_cw_bo3_brush_prototype import read_map_planes
from audit_cw_bo3_brush_types import entities


def volume_identity(row, materials):
    props=row['properties']
    identifiers={k:props[k] for k in ('script_noteworthy','variantName','targetname','script_location') if props.get(k)}
    purpose=props.get('script_noteworthy') or props.get('variantName') or 'unclassified'
    # An instance targetname is preserved, not used to guess gameplay semantics.
    candidates=[props.get('script_noteworthy',''),props.get('variantName','')]
    aliases={'unlock_volume':'unlock','vol_death_zone':'kill'}
    eligible={n for n,m in materials.items() if m['properties'].get('noDraw')=='1' and
              ('volume' in n or n in ('fog','ambient','unlock','kill','sound_trigger','music_trigger'))}
    material='volume';status='source_label_preserved';matched=None
    for value in candidates:
        target=aliases.get(value,value)
        if target in eligible:
            material=target;matched=value
            status='basic_purpose_alias' if value in aliases else 'stock_tool_name_match'
            break
    return dict(purpose=purpose,source_identifiers=identifiers,material=material,status=status,
                matched_source_value=matched,gameplay_ported=False,
                note='Tool material labels preserve purpose; CW scripts, district toggles and gameplay behavior are not ported.')


def properties(row, definition, point):
    out={'classname':row['classname']};omitted={};flag_mask=0;flag_names={}
    for key,value in row['properties'].items():
        field=definition.get(key)
        if key in ('classname','origin','angles'):continue
        if key=='spawnflags':
            omitted[key]='Raw CW bits retained in JSON; BO3 bits reconstructed from explicit named flags'
        elif isinstance(field,dict) and 'spawnflag' in field:
            if field.get('type')=='bool' and str(value).lower() in ('0','1','false','true') and str(field['spawnflag']).isdigit():
                enabled=str(value).lower() in ('1','true');out[key]='1' if enabled else '0'
                flag_names[key]=int(field['spawnflag'])
                if enabled:flag_mask|=int(field['spawnflag'])
            else:omitted[key]='Unsupported BO3 flag value or enum'
        elif key in ('target','targetname') or key.startswith(('script_','zombie_')) or isinstance(field,dict) and not field.get('noExport') in (True,'true'):
            if isinstance(field,dict) and 'enum' in field and str(value) not in [v.strip() for v in field['enum'].split(',')]:
                omitted[key]='Value absent from bundled BO3 enum';continue
            try:quoted(key);quoted(value)
            except ValueError:omitted[key]='Not representable by supported Radiant property escaping'
            else:out[key]=str(value)
        else:omitted[key]='CW-specific or editor-only property; retained in JSON'
    if flag_names or 'spawnflags' in row['properties']:out['spawnflags']=str(flag_mask)
    if point:
        out['origin']=' '.join(format(v,'.9g') for v in row['origin'])
        out['angles']=' '.join(format(v,'.9g') for v in row['angles'])
    return out,omitted,flag_names


def export(capture,name,output,reference,expected_hash=None):
    identity=map_identity(capture,name,expected_hash);source=ownership(capture)
    definitions=reference['entity_reference']['classes']
    materials={m['name']:m for m in reference['materials']}
    layers={'000_Global'};body=[];converted=[];skipped=[];writer=CanonicalPlaneWriter()
    all_rows=[*source['models'],*source['entities_without_precompiled_model']]
    for row in all_rows:
        cls=row['classname'];point=cls in ('trigger_box','trigger_radius');reason=None
        if cls not in definitions:reason='No supported bundled BO3 class definition'
        elif point and 'hulls' in row:reason='Parameter class unexpectedly owns a precompiled hull; representation needs review'
        elif not point and 'hulls' not in row:reason='No precompiled hull association'
        elif not point and any(row['angles']):reason='Rotated precompiled hull transform not validated'
        if reason is None and point:
            dims=('width','length','height') if cls=='trigger_box' else ('radius','height')
            try:valid=all(math.isfinite(float(row['properties'][key])) and float(row['properties'][key])>0 for key in dims)
            except (KeyError,ValueError,TypeError):valid=False
            if not valid:reason='Missing, nonfinite or nonpositive parameter dimensions'
        if reason:
            skipped.append(dict(source_entity_index=row['entity_index'],source_id=row['source_id'],classname=cls,reason=reason));continue
        props,omitted,flags=properties(row,definitions[cls],point)
        volume=volume_identity(row,materials) if cls=='info_volume' else None
        family='CW_Player_Volumes' if cls=='info_volume' and props.get('script_noteworthy')=='player_volume' else 'CW_Volumes' if cls=='info_volume' else 'CW_Triggers'
        parent='000_Global/'+family;group=parent+'/'+cls
        layers.update((parent,group))
        if volume:
            group+='/'+re.sub(r'[^a-zA-Z0-9_]', '_',volume['purpose'])
        label=re.sub(r'[^a-zA-Z0-9_]', '_',props.get('targetname',props.get('script_noteworthy','unnamed')))
        layer=group+'/'+label+'_e'+str(row['entity_index']);layers.update((parent,group,layer))
        ordinal=len(converted)+1
        block=[f'// entity {ordinal}: CW source {row["source_id"]}','{','layer '+quoted(layer)]
        block.extend(quoted(k)+' '+quoted(v) for k,v in props.items())
        material=volume['material'] if volume else 'trigger_damage' if cls=='trigger_damage' else 'trigger'
        if materials[material]['properties'].get('noDraw')!='1':raise ValueError('Invalid trigger tool reference')
        hulls=[]
        for bi,hull in enumerate(row.get('hulls',[])):
            equations=hull_planes(hull);mesh=reconstruct_exact(equations)
            if mesh['bad_directed_edges'] or mesh['volume']<=0:raise ValueError('Trigger hull is not closed with positive volume')
            active=[f['side_candidates'][0] for f in mesh['faces']]
            if len(active)>64 or max(len(f['vertices']) for f in mesh['faces'])>64:raise ValueError('Trigger hull exceeds Radiant face/winding limits')
            world=np.array(mesh['vertices'])+row['origin'];eq=equations[active].copy()
            eq[:,3]+=eq[:,:3]@np.array(row['origin']);eq/=np.linalg.norm(eq[:,:3],axis=1)[:,None]
            lines=writer.lines(eq,world.mean(axis=0),material);parsed=np.array(read_map_planes('\n'.join(lines)))
            drift=float(np.max(np.abs(parsed-eq)));outside=float(np.max(world@parsed[:,:3].T-parsed[:,3]))
            if drift>1e-6 or outside>1e-6:raise ValueError('Serialized trigger planes moved')
            block.extend([f'// brush {bi}','{','layer '+quoted(layer),*lines,'}'])
            hulls.append(dict(hull_index=hull['hull_index'],brush_index=bi,source_equations_local=equations.tolist(),
                active_source_planes=active,vertices_world=world.tolist(),face_count=len(active),volume=mesh['volume'],
                max_winding_points=max(len(f['vertices']) for f in mesh['faces']),serialized_plane_error=drift,max_vertex_outside=outside))
        block.append('}');body.append(block)
        converted.append(dict(source_entity_index=row['entity_index'],source_id=row['source_id'],map_entity_index=ordinal,
            layer=layer,emitted_properties=props,source_properties=row['properties'],source_origin=row['origin'],source_angles=row['angles'],
            material=material if not point else None,hulls=hulls,contents_raw=row.get('contents_raw'),
            volume_identity=volume,
            representation='native_parameter_entity' if point else 'precompiled_hulls_world_space',
            parameter_bounds_validated=False if point else None,omitted_map_properties=omitted,named_bo3_spawnflags=flags))
        if ordinal%24==0:print(f'Trigger entities: {ordinal}/{len(all_rows)}',flush=True)
    output.mkdir(parents=True,exist_ok=True);map_files={};written=[]
    for category in ('volumes','triggers'):
        selected=[(r,b) for r,b in zip(converted,body) if (r['emitted_properties']['classname']=='info_volume')==(category=='volumes')]
        target=output/(name+'_'+category+'.map');prefab_layers={'000_Global'};prefab_body=[]
        for index,(row,block) in enumerate(selected,1):
            row['map_entity_index']=index;row['map_file']=target.name
            parts=row['layer'].split('/')
            prefab_layers.update('/'.join(parts[:i]) for i in range(1,len(parts)+1))
            # Only the entity ordinal changes. Properties, hull lines and
            # source identity are retained exactly; each prefab has one worldspawn.
            prefab_body.extend([f'// entity {index}: CW source {row["source_id"]}',*block[1:]])
            written.append(row['source_entity_index'])
        target.write_text('\n'.join(['iwmap 4',*[quoted(l)+' flags'+(' active' if l=='000_Global' else '') for l in sorted(prefab_layers)],
            '// entity 0','{','"classname" "worldspawn"','}',*prefab_body,'']))
        parsed=entities(target)
        if len(parsed)!=len(selected)+1:raise ValueError('Prefab entity coverage changed')
        for actual,(expected,_) in zip(parsed[1:],selected):
            if actual['properties']!=expected['emitted_properties'] or actual['brush_blocks']!=len(expected['hulls']):raise ValueError('Trigger ownership or properties changed')
            if set(actual['face_material_counts'])!=({expected['material']} if expected['hulls'] else set()):raise ValueError('Wrong trigger material')
        map_files[category]=dict(file=target.name,sha256=sha(target),entities=len(selected),
            hull_brushes=sum(len(r['hulls']) for r,_ in selected))
    if sorted(written)!=sorted(r['source_entity_index'] for r in converted) or len(written)!=len(set(written)):
        raise ValueError('Split prefabs duplicate or omit a source entity')
    hulls=[h for r in converted for h in r['hulls']]
    classes=Counter(r['emitted_properties']['classname'] for r in converted)
    players=[r for r in converted if r['emitted_properties']['classname']=='info_volume' and r['emitted_properties'].get('script_noteworthy')=='player_volume']
    summary=dict(source_entities=len(all_rows),exported_entities=len(converted),class_counts=dict(classes),
        trigger_entities=sum(n for cls,n in classes.items() if cls.startswith('trigger_')),info_volume_entities=classes['info_volume'],
        player_volume_entities=len(players),hull_brushes=len(hulls),parameter_entities=sum(r['representation']=='native_parameter_entity' for r in converted),
        volume_purposes=dict(Counter(r['volume_identity']['purpose'] for r in converted if r['volume_identity'])),
        volume_materials=dict(Counter(r['material'] for r in converted if r['volume_identity'])),
        skipped_entities=len(skipped),max_faces=max((h['face_count'] for h in hulls),default=0),
        max_winding_points=max((h['max_winding_points'] for h in hulls),default=0),
        max_serialized_plane_error=max((h['serialized_plane_error'] for h in hulls),default=0),compiler_validated=False,gameplay_validated=False)
    report=dict(schema='cw_bo3_trigger_entities_v2',export_mode='separate_triggers_and_volumes',**identity,summary=summary,
        map_files=map_files,source_capture=str(capture.resolve()),
        source_evidence_sha256=sha(capture/'evidence.json'),implementation_sha256=sha(Path(__file__)),
        bo3_entity_reference=reference['entity_reference'],entities=converted,not_converted=skipped,raw_trigger_data=source,
        limitations=['Entity class and property names do not port CW gameplay scripts or referenced objects.',
            'Raw CW spawnflag bits are retained in JSON; only explicit names map to bundled BO3 flag bits.',
            'Hull origins are baked once, with no emitted origin/angles. Parameter entities retain origin/angles/dimensions; bounds equivalence is not proven.',
            'Rotated precompiled hulls and unsupported classes remain in JSON; no map-specific class or count overrides.'])
    (output/'triggers.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(summary,indent=2));return report
