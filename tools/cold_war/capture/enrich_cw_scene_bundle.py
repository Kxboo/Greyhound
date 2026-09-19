"""Cross-check captured scene fields with the user-supplied CW dump and annotate behavior."""

# Support direct execution and the isolated packaged Python runtime.
import sys as _tool_sys
from pathlib import Path as _ToolPath
TOOLS_ROOT = next(p for p in _ToolPath(__file__).resolve().parents if (p / "tool_bootstrap.py").is_file())
_tool_sys.path.insert(0, str(TOOLS_ROOT))
import tool_bootstrap as _tool_bootstrap
_tool_bootstrap.activate(__file__)
REPO_ROOT = TOOLS_ROOT.parent
import argparse,copy,json,struct
from pathlib import Path
from capture_cw_scriptbundles import fnv,MASK
from cw_scene_controls import root_transform, alignment_pose

COMMIT='edd94bdfa2b37693cdb77c1493855ad14ddc435a'
SCRIPT_URL=f'https://github.com/ate47/bocw-source/blob/{COMMIT}/scripts/core_common/scene_shared.csc'
CANONICAL_SEMANTICS={
 0x922b4fc5:('position_offset_x','world-space addition to alignment origin'),
 0x3e692842:('position_offset_y','world-space addition to alignment origin'),
 0xbe60a82b:('position_offset_z','world-space addition to alignment origin'),
 0x16999a5d:('angle_offset_pitch','addition to alignment angles'),
 0x29563fd6:('angle_offset_yaw','addition to alignment angles'),
 0xeb00c330:('angle_offset_roll','addition to alignment angles'),
}

def enrich(capture,dump_root,output):
    source=json.loads(Path(capture).read_text());result=copy.deepcopy(source);checks=[]
    # All public source paths are relative to the organized capture root.
    root=Path(output).resolve().parent.parent
    evidence_root=Path(capture).resolve().parent
    result['EvidenceBaseDirectory']=(evidence_root.relative_to(root).as_posix()
        if evidence_root.is_relative_to(root) else str(evidence_root))
    assert source['complete']
    references={}
    for p in (Path(dump_root)/'scriptbundle').rglob('*.json'):
        h=(int(p.stem[5:],16)&MASK) if p.stem.startswith('hash_') else fnv(p.stem)
        references[h]=p
    def compare(node,ref,path):
        def key_for(h,canon):
            candidates=[key for key in ref if (key.startswith('hash_') and int(key[5:],16)==canon) or (not key.startswith('hash_') and fnv(key)==h)]
            assert len(candidates)==1,(path,hex(h),hex(canon),candidates)
            return candidates[0]
        seen=set()
        for field in node['fields']:
            key=key_for(int(field['key_hash'],16),field['key_canonical']);seen.add(key);value=ref[key]
            field['ReferenceKey']=key;field['ReferencePath']=path+'/'+key
            if not key.startswith('hash_'):field['key']=key
            if field['type'] in (2,23,26):assert field['value']==value,(path,key,field['value'],value)
            elif field['type']==3:assert abs(field['value']-value)<1e-5*max(1,abs(value)),(path,key)
            elif 'string_hash' in field:
                assert isinstance(value,str),(path,key,value)
                asset=value.split('&',1)[1] if '&' in value else value
                expected=(int(asset[5:],16)&MASK) if asset.startswith('hash_') else fnv(asset)
                assert expected==int(field['string_hash'],16),(path,key,value)
                field['value']=asset;field['status']='live_string_hash_matches_dump_value'
                field['DumpEncodedValue']=value
            elif 'value_hash' in field:
                assert isinstance(value,str) and '#' in value,(path,key,value)
                asset=value.split('#',1)[1]
                expected=(int(asset[5:],16)&MASK) if asset.startswith('hash_') else fnv(asset.lower().replace('\\','/'))
                assert expected==int(field['value_hash'],16),(path,key,value)
                if not asset.startswith('hash_'):field['value_name']=asset.lower().replace('\\','/')
            else:raise AssertionError(('unverified field type',field))
            field['ReferenceValueMatched']=True;checks.append(field['ReferencePath'])
            if field['key_canonical'] in CANONICAL_SEMANTICS:
                name,meaning=CANONICAL_SEMANTICS[field['key_canonical']]
                field['DecodedMeaning']={'field':name,'meaning':meaning,'source':SCRIPT_URL+'#L1908-L1980','confidence':'script consumer identifies vector role and component order'}
        for sub in node['subarrays']:
            canon=struct.unpack_from('<I',bytes.fromhex(sub['raw_hex']),8)[0]
            key=key_for(int(sub['key_hash'],16),canon);seen.add(key);sub['key']=key
            assert isinstance(ref[key],list) and len(ref[key])==len(sub['items'])
            for i,child in enumerate(sub['items']):compare(child,ref[key][i],path+'/'+key+'/'+str(i))
        assert seen==set(ref),(path,'field set differs',seen^set(ref))
    for record in result['records']:
        assert record['loaded']
        dump=references.get(int(record['hash'],16))
        if dump is None:
            record['ReferenceValidationStatus']='no matching bundle in checked dump directories; raw capture retained'
            continue
        reference=json.loads(dump.read_text());name=dump.stem
        compare(record['objects'],reference,'/'+name)
        record['name']=name
        record['ReferenceValidationStatus']='all captured fields match reference'
        record['DumpReference']={'file':str(dump.resolve()),'commit':COMMIT,'url':f'https://github.com/ate47/bocw-source/blob/{COMMIT}/{dump.relative_to(dump_root).as_posix()}'}
    result['reference_validation']={'matched_fields':len(checks),'all_fields_match':True,'paths':checks,'commit':COMMIT,
      'alignment_rule':'Use nonzero shot offset, else nonzero object offset, else scene offset; position offsets add in world coordinates. Preserve-angle can retain current entity angles instead of alignment angles.',
      'matched_bundles':sum('DumpReference' in r for r in result['records']),
      'unmatched_bundles':sum('DumpReference' not in r for r in result['records']),
      'scope':'All fields of matched bundles only. Unmatched bundles remain raw. Does not prove a full BO3 port.'}
    Path(output).parent.mkdir(parents=True,exist_ok=True);Path(output).write_text(json.dumps(result,indent=2)+'\n')
    if (root/'entities').is_dir() and (root/'animation/assets.json').is_file():
        entities={e['EntityId']:e for p in (root/'entities').glob('*/*.json') for e in json.loads(p.read_text())}
        assets={int(a['AnimationHash'],16):a for a in json.loads((root/'animation/assets.json').read_text())}
        def values(node):return {f['ReferenceKey']:f.get('value',f.get('value_name') or f.get('value_hash')) for f in node['fields']}
        def children(node,key):return next((s['items'] for s in node['subarrays'] if s['key']==key),[])
        placed=[]
        for bundle in result['records']:
            if 'DumpReference' not in bundle or int(bundle['bundle_type_hash'],16)!=fnv('scene'):continue
            scene=bundle['objects'];scene_values=values(scene)
            for reference in bundle['source_entities']:
                entity=entities[reference['entity']];root_pose=root_transform(entity)
                for oi,obj in enumerate(children(scene,'objects')):
                    ov=values(obj)
                    for si,shot in enumerate(children(obj,'shots')):
                        sv=values(shot);pose=alignment_pose(root_pose,scene_values,ov,sv)
                        overridden=pose['RequiresRuntimeAlignmentTargetOrTag'] or pose['RequiresCurrentObjectAngles']
                        entries=[]
                        for entry in children(shot,'entry'):
                            for field in entry['fields']:
                                if field['type'] not in (4,5,6):continue
                                h=int(field['value_hash'],16);asset=assets.get(h)
                                entries.append({'AnimationHash':field['value_hash'],'Name':field.get('value_name'),'FieldPath':field['ReferencePath'],
                                    'AssetMetadata':{k:asset[k] for k in ('FrameRate','Frequency','FrameCount','BoneCount')} if asset else None})
                        placed.append({'SourceEntityId':entity['EntityId'],'ClassName':entity['ClassName'],'SourceEntityProperties':entity['Properties'],
                            'BundleName':bundle['name'],'ObjectIndex':oi,'ShotIndex':si,'SceneControls':scene_values,'ObjectControls':ov,'ShotControls':sv,
                            'AnimationEntries':entries,'RootTransform':root_pose,
                            'DefaultAlignmentPoseReference':pose,'AlignmentStatus':'requires runtime alignment target/current angles' if overridden else 'scene/object/shot offsets applied to authored root; scripts may choose a different root at runtime',
                            'SourceBundleFile':'animation/scene_bundle_data.json','SemanticsSource':SCRIPT_URL+'#L1908-L1980'})
        (root/'animation/scene_placements.json').write_text(json.dumps(placed,indent=2)+'\n')
    print(json.dumps({'matched_fields':len(checks),'output':str(Path(output).resolve())},indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('capture',type=Path);p.add_argument('dump_root',type=Path);p.add_argument('output',type=Path);a=p.parse_args();enrich(a.capture,a.dump_root,a.output)
