"""Audit focused FX/animation placement files against their captured bytes."""

# Support direct execution and the isolated packaged Python runtime.
import sys as _tool_sys
from pathlib import Path as _ToolPath
TOOLS_ROOT = next(p for p in _ToolPath(__file__).resolve().parents if (p / "tool_bootstrap.py").is_file())
_tool_sys.path.insert(0, str(TOOLS_ROOT))
import tool_bootstrap as _tool_bootstrap
_tool_bootstrap.activate(__file__)
REPO_ROOT = TOOLS_ROOT.parent
import argparse,json,struct,math
from pathlib import Path

def audit(root):
    root=Path(root)
    layout=json.loads((root/'catalog.json').read_text()) if (root/'catalog.json').is_file() else {}
    alias=layout.get('path_aliases',{})
    load=lambda name:json.loads((root/alias.get(name,name)).read_text(encoding='utf-8'))
    catalog=load('fx_anm_catalog.json');assert catalog['complete']
    blocks={}
    for source in ('level_fx','animation_references'):
        directory=root/'diagnostics/non_static'/source;e=json.loads((directory/'evidence.json').read_text());parts=[]
        assert all(v['status'] in ('unchanged','empty') for v in e['verifications'])
        for row in e['reads']:
            if row['status']=='reused_file':continue
            assert row['status']=='captured',row
            entry=e['storage'].get(row['file'])
            if entry:
                with (directory/entry['file']).open('rb') as f:f.seek(entry['offset']);b=f.read(entry['bytes'])
            else:b=(directory/row['file']).read_bytes()
            assert len(b)==row['requested_bytes'];parts.append((int(row['address'],16),b))
        blocks[source]=parts
    def raw(source,address,n):
        address=int(address,16)
        for base,b in blocks[source]:
            if base<=address and address+n<=base+len(b):return b[address-base:address-base+n]
        raise AssertionError(('missing bytes',source,address,n))
    fx=load('fx_placements.json');assets={x['EffectPointer']:x for x in load('fx_assets.json')}
    names=[]
    for row in fx:
        b=raw('level_fx',row['RecordAddress'],80);assert bytes.fromhex(row['RawRecordHex'])==b
        assert row['CandidatePosition']==list(struct.unpack_from('<3f',b,8))
        assert row['CandidateAngles']==list(struct.unpack_from('<3f',b,20))
        asset=assets[row['EffectPointer']];assert row['EffectName']==asset['Name']
        header=raw('level_fx',row['EffectPointer'],144);assert bytes.fromhex(asset['RawHeaderHex'])==header
        assert int(row['EffectHash'],16)==struct.unpack_from('<Q',header)[0]
        assert int(row['EffectHashMasked'],16)==int(row['EffectHash'],16)&((1<<60)-1)
        count=struct.unpack_from('<I',b,56)[0];pointer=struct.unpack_from('<Q',b,72)[0]
        assert count==row['AttachedNameCountRaw']==len(row['AttachedNameRecords'])
        for index,ref in enumerate(row['AttachedNameRecords']):
            assert int(ref['RecordAddress'],16)==pointer+index*32
            rb=raw('level_fx',ref['RecordAddress'],32);assert bytes.fromhex(ref['RawRecordHex'])==rb
            assert int(ref['NamePointer'],16)==struct.unpack_from('<Q',rb)[0]
            assert raw('level_fx',ref['NamePointer'],len(ref['Name'])+1)==ref['Name'].encode('ascii')+b'\0'
            assert all(ref['RawFieldsU32'][hex(off).upper().replace('0X','0x')]==struct.unpack_from('<I',rb,off)[0] for off in range(8,32,4))
            names.append(ref['Name'])
    entities={e['EntityId']:e for p in (root/'entities').glob('*/*.json') for e in json.loads(p.read_text())}
    for file in ('animation_entity_references.json','fx_entity_references.json'):
        for row in load(file):assert row['Properties']==entities[row['EntityId']]['Properties']
    models=load('animation_model_placements.json');source_models={alias.get(n,n):load(n) for n in ('static_models.json','non_static_models.json')}
    for row in models:
        source=source_models[row['SourcePlacementFile']][row['SourcePlacementIndex']]
        assert all(row[k]==v for k,v in source.items())
        if row['AttachedEntityProperties'] is not None:assert row['AttachedEntityProperties']==entities[row['SourceEntityId']]['Properties']
    animations=load('animation_assets.json');animation_hashes={int(a['AnimationHash'],16) for a in animations}
    for row in animations:
        b=raw('animation_references',row['RecordAddress'],288);assert bytes.fromhex(row['RawRecordHex'])==b
        assert int(row['AnimationHash'],16)==struct.unpack_from('<Q',b,112)[0]&((1<<60)-1)
        assert row['FrameRate']==struct.unpack_from('<f',b,176)[0] and math.isfinite(row['FrameRate'])
        assert row['FrameCount']==struct.unpack_from('<H',b,260)[0]
        assert row['BoneCount']==struct.unpack_from('<H',b,254)[0]
    refs=load('named_animation_references.json')
    for row in refs:
        assert row['Name']==entities[row['SourceEntityId']]['Properties'][row['Property']]
        h=0xcbf29ce484222325
        for x in row['Name'].encode('utf-8'):h=((h^x)*0x100000001b3)&((1<<64)-1)
        h&=(1<<60)-1
        assert int(row['LookupHash'],16)==h
        assert row['LoadedAnimationMatch']==(h in animation_hashes)
        if row['LoadedAnimationMatch']:assert int(row['AnimationHash'],16)==h
    return {'status':'passed','fx_placements':len(fx),'fx_assets':len(assets),'resolved_fx_asset_names':sum(a['NameResolved'] for a in assets.values()),
        'fx_placements_with_attached_names':sum(bool(r['AttachedNameRecords']) for r in fx),'attached_fx_name_records':len(names),'distinct_attached_fx_names':len(set(names)),
        'animation_model_placements':len(models),'animation_entities':len(load('animation_entity_references.json')),'fx_entities':len(load('fx_entity_references.json')),
        'named_animation_references':len(refs),'matched_loaded_animation_references':sum(r['LoadedAnimationMatch'] for r in refs),'animation_assets':len(animations)}

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('run',type=Path);a=p.parse_args()
    result=audit(a.run);out=a.run/('metadata/organized_fx_anm_validation.json' if (a.run/'catalog.json').is_file() else 'fx_anm_validation.json')
    out.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
