"""Compare saved CW contents/trigger evidence with installed BO3 materials/entities.
Read-only to captures, .map files and GDTs; creates research JSON only.
"""
import argparse,hashlib,json,re,struct
from collections import Counter
from pathlib import Path
from annotate_cw_brush_contents import annotate_mask

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,obj):p.write_text(json.dumps(obj,indent=2),encoding='utf-8')

def gdt(path):
    result=[]
    text=path.read_text(encoding='utf-8-sig')
    for m in re.finditer(r'"([^"\n]+)"\s*\(\s*"material.gdf"\s*\)\s*\{([^{}]*)\}',text):
        result.append(dict(name=m[1],line=text.count('\n',0,m.start())+1,properties=dict(re.findall(r'"([^"\n]*)"\s*"([^"\n]*)"',m[2]))))
    if not result:raise ValueError('No material definitions: '+str(path))
    return result

def entities(path):
    depth=0;current=None;out=[]
    for number,line in enumerate(path.read_text(encoding='utf-8-sig').splitlines(),1):
        if line.lstrip().startswith('//'):continue
        bare=re.sub(r'"(?:\\.|[^"\\])*"','""',line)
        if depth==0 and bare.strip()=='{':current=dict(line=number,properties={},face_material_counts=Counter(),brush_blocks=0)
        if current is not None:
            kv=re.fullmatch(r'\s*"([^"\r\n]+)"\s+"([^"\r\n]*)"\s*',line)
            if depth==1 and kv:current['properties'][kv[1]]=kv[2]
            if depth==1 and bare.strip()=='{':current['brush_blocks']+=1
            face=re.match(r'\s*\([^)]*\)\s*\([^)]*\)\s*\([^)]*\)\s+(\S+)',line)
            if face:current['face_material_counts'][face[1]]+=1
        depth+=bare.count('{')-bare.count('}')
        if depth<0:raise ValueError('Unbalanced map braces')
        if depth==0 and current is not None:
            current['entity_index']=len(out);current['face_material_counts']=dict(current['face_material_counts']);out.append(current);current=None
    if depth:raise ValueError('Unclosed map braces')
    return out

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--bo3',type=Path,default=Path(r'C:\Program Files (x86)\Steam\steamapps\common\Call of Duty Black Ops III'))
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=True)
    table_path=Path('research/cw-clip/brush-mask-callers/named-flag-table.json');table=json.loads(table_path.read_text());assert table['readback_unchanged']
    names={x['name'] for x in table['records'] if 0<int(x['field_16'],16)<=0x3ffffff}
    definitions=[]
    for rel in ['art_assets/t6_legacy/texture_assets/clip.gdt','texture_assets/tools.gdt']:
        path=a.bo3/rel
        for r in gdt(path):
            props=r['properties'];r.update(source=str(path),source_sha256=sha(path),named_contents_properties=sorted(n for n in names if props.get(n)=='1'))
            # Preserve the full GDT property dictionary, including nonSolid,
            # slick, noImpact and surfaceType. Named contents alone are not equivalence.
            definitions.append(r)
    save(a.output/'bo3-material-reference.json',definitions)
    references=[]
    for path in [a.bo3/'map_source/zm/zm_giant.map',*sorted((a.bo3/'map_source/mp').glob('*.map'))]:
        rows=entities(path);interesting=[r for r in rows if re.search('volume|trigger|zone',r['properties'].get('classname',''),re.I) or r['properties'].get('script_noteworthy')=='player_volume']
        references.append(dict(path=str(path),sha256=sha(path),entity_count=len(rows),class_counts=dict(Counter(r['properties'].get('classname','') for r in rows)),examples=interesting,
            prefab_references=[r['properties']['model'] for r in rows if r['properties'].get('classname')=='misc_prefab'],scope='Direct entities only; nested prefab contents are not flattened'))
    save(a.output/'bo3-entity-reference.json',references)
    maps=[];global_masks=set()
    for label,folder in [('silver','bo3-silver-brush-map-v3'),('platinum','radiant-greyhound-platinum'),('gold','radiant-gold-tool-projections'),('tungsten','radiant-tungsten')]:
        path=Path('research/cw-clip')/folder/'collision_metadata.json';m=json.loads(path.read_text());seen={};unique={};piece_counts=Counter();examples={}
        for r in m['rows']:
            if label=='silver':
                s=r['source_properties'];mask=int(s['contents_mask'],16);asset=s['collision_model_index'];brush=s['brush_index'];world=s.get('collision_world','legacy_renderer_reference');inst=s.get('collision_instance_index',r['source_object'])
            else:mask=int(r['contents_low26'],16);asset=r['collision_asset_index'];brush=r['brush_index'];world=r['collision_world'];inst=r['instance_index']
            key=(world,inst,asset,brush);u=(asset,brush)
            value=(mask,r['assigned_material'],r['assignment_status'])
            if key in seen and seen[key]!=value:raise ValueError('Partition metadata disagreement')
            if u in unique and unique[u]!=mask:raise ValueError('Unique brush mask disagreement')
            seen[key]=value;unique[u]=mask;piece_counts[mask]+=1;global_masks.add(mask)
            examples.setdefault(mask,dict(map_brush_index=r['map_brush_index'],asset_index=asset,brush_index=brush,world=world,instance_index=inst,world_mins=r['world_mins'],world_maxs=r['world_maxs']))
        by_mask=[];added_player=0
        for mask,count in sorted(Counter(v[0] for v in seen.values()).items()):
            annotation=annotate_mask(mask,table['records']);wanted=set(annotation['named_contents_candidates']);unknown=int(annotation['unnamed_contents_bits'],16)
            candidates=[dict(name=d['name'],source=d['source'],line=d['line']) for d in definitions if set(d['named_contents_properties'])==wanted and unknown==0 and mask!=0]
            assigned=Counter(v[1] for v in seen.values() if v[0]==mask)
            differences=[]
            for material,n in assigned.items():
                matched=[d for d in definitions if d['name']==material]
                for d in matched:
                    props=set(d['named_contents_properties']);extra=sorted(props-wanted);missing=sorted(wanted-props)
                    differences.append(dict(material=material,placed_brushes=n,added_named_properties=extra,missing_named_properties=missing,source=d['source']))
                    if 'playerClip' in extra:added_player+=n
            by_mask.append(dict(**annotation,unique_brushes=sum(v==mask for v in unique.values()),placed_brushes=count,output_pieces=piece_counts[mask],current_materials=dict(assigned),exact_named_property_candidates=candidates,current_property_differences=differences,example=examples[mask]))
        summary=dict(unique_brushes=len(unique),placed_brushes=len(seen),output_pieces=len(m['rows']),legacy_renderer_reference_instances=sum(k[0]=='legacy_renderer_reference' for k in seen),review_placeholder_brushes=sum(v[2]=='REVIEW_PLACEHOLDER' for v in seen.values()),zero_content_brushes=sum(v[0]==0 for v in seen.values()),trigger_bit_brushes=sum(bool(v[0]&0x2000000) for v in seen.values()),added_player_clip_property_brushes=added_player)
        maps.append(dict(map=label,source_metadata=str(path),source_sha256=sha(path),summary=summary,masks=by_mask))
    save(a.output/'brush-type-audit.json',dict(named_table=str(table_path),named_table_sha256=sha(table_path),evidence_status=table['status'],maps=maps,distinct_masks=len(global_masks),note='Counts use placed source brushes, not subdivision pieces. Property-name differences are not a compiled BO3 behavior proof. Unknown/zero contents do not identify a zone. No map/material edits.'))
    trigger_path=Path('research/cw-clip/trigger-code-trace/trigger-ownership.json');tr=json.loads(trigger_path.read_text());rows=tr['models']
    trigger_header=Path(tr['source_capture'])/'headers.bin'
    map_hash=struct.unpack_from('<Q',trigger_header.read_bytes())[0]
    if map_hash!=0x6bf83815978fde24:raise ValueError('Saved trigger audit expects the verified Silver capture')
    zones=[r for r in rows if r['classname']=='info_volume' and r['properties'].get('script_noteworthy')=='player_volume']
    save(a.output/'cw-volume-candidates.json',dict(map='zm_silver',map_asset='maps/zm/zm_silver.d3dbsp',map_hash=hex(map_hash),source_header_sha256=sha(trigger_header),source=str(trigger_path),source_sha256=sha(trigger_path),source_capture=tr['source_capture'],association_evidence=tr['association_evidence'],summary=tr['summary'],
        player_volume_count=len(zones),zone_names=dict(Counter(r['properties'].get('targetname','') for r in zones)),
        models=rows,note='Saved trigger ownership, not a CLIP_MAP brush join. All raw properties and hull/slab geometry retained. Script dependencies and cross-map ownership validation remain required.'))
    print(json.dumps(dict(bo3_materials=len(definitions),distinct_brush_masks=len(global_masks),maps={r['map']:r['summary'] for r in maps},saved_trigger_models=len(rows),player_volumes=len(zones),zone_names=sorted({r['properties'].get('targetname','') for r in zones}),bo3_reference_classes={r['path']:r['class_counts'] for r in references}),indent=2))

if __name__=='__main__':main()
