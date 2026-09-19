"""Link captured FX/ANM placement data to the user-supplied CW script dump."""

# Support direct execution and the isolated packaged Python runtime.
import sys as _tool_sys
from pathlib import Path as _ToolPath
TOOLS_ROOT = next(p for p in _ToolPath(__file__).resolve().parents if (p / "tool_bootstrap.py").is_file())
_tool_sys.path.insert(0, str(TOOLS_ROOT))
import tool_bootstrap as _tool_bootstrap
_tool_bootstrap.activate(__file__)
REPO_ROOT = TOOLS_ROOT.parent
import argparse, collections, hashlib, json, re, struct
from pathlib import Path
from cw_scene_controls import canonical
from enrich_cw_scene_bundle import COMMIT
from capture_cw_scriptbundles import fnv, MASK

def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2)+'\n')

def link(root, dump):
    root, dump = Path(root).resolve(), Path(dump).resolve()
    texts = {p.relative_to(dump).as_posix():p.read_text(encoding='utf-8')
             for p in (dump/'scripts').rglob('*') if p.suffix in ('.gsc','.csc')}
    hashes={p:hashlib.sha256(t.encode()).hexdigest() for p,t in texts.items()}
    def ref(path, line):
        return {'File':path, 'Line':line, 'URL':f'https://github.com/ate47/bocw-source/blob/{COMMIT}/{path}#L{line}',
                'FileSHA256':hashes[path]}
    fields, literals = collections.defaultdict(list), collections.defaultdict(list)
    for path, text in texts.items():
        function = None
        for line, code in enumerate(text.splitlines(), 1):
            m=re.search(r'\bfunction\s+(\w+)\s*\(',code)
            if m: function=m[1]
            if code.strip().startswith('//'):continue
            for name in set(re.findall(r'\.\s*(\w+)',code)):
                fields[name].append({**ref(path,line),'Function':function,'Code':code.strip()})
            for name in set(re.findall(r'"([^"\n]+)"',code)):
                literals[name].append({**ref(path,line),'Function':function,'Code':code.strip()})
    counts = {}
    for category in ('fx','animation'):
        rows=json.loads((root/category/'entity_references.json').read_text()); result=[]
        for row in rows:
            props=row['Properties']; controls=[]
            for key,value in props.items():
                if not re.search(r'anim|bundle|fx|explod|delay|trigger|script_(?:string|noteworthy|int|float|vector|angles|repeat)|target|spawnflags',key,re.I):continue
                checksum=canonical(key)
                matches=fields.get(key.lower(),[])+fields.get(f'var_{checksum:x}',[])
                controls.append({'Property':key,'Value':value,'ScriptIdentifierChecksum':hex(checksum),
                    'ConsumerReferences':matches,'Status':'identifier reference; caller/branch must be checked before treating as active'})
            result.append({'SourceEntityId':row['EntityId'],'ClassName':row['ClassName'],
                'Position':row.get('Position'),'SourceAngles':row.get('SourceAngles'),'Controls':controls})
        save(root/category/'playback_references.json',result)
        counts[category+'_entities_with_consumer_matches']=sum(any(c['ConsumerReferences'] for c in r['Controls']) for r in result)
    fx=json.loads((root/'fx/placements.json').read_text()); groups=collections.defaultdict(list)
    controls=[]
    for row in fx:
        b=bytes.fromhex(row['RawRecordHex'])
        controls.append({'SourceId':row['SourceId'],'SourcePlacementFile':'fx/placements.json',
            'FieldsByOffset':{'+32':{'s32':struct.unpack_from('<i',b,32)[0],'candidate':'delay; unit not verified'},
                '+36':{'f32':struct.unpack_from('<f',b,36)[0],'candidate':'timescale'},
                '+40':{'f32':struct.unpack_from('<f',b,40)[0],'candidate':'squared cull distance'},
                '+44':{'u32':struct.unpack_from('<I',b,44)[0]},'+48':{'bytes':list(b[48:52])},
                '+52':{'u32':struct.unpack_from('<I',b,52)[0],'candidate':'FX state bitmask'}},
            'SemanticStatus':'raw controls preserved; candidate labels are not validated conversion fields',
            'AttachedNameRecords':row['AttachedNameRecords']})
        for attached in row['AttachedNameRecords']:
            groups[attached['Name']].append({'SourceId':row['SourceId'],'AttachedRecordAddress':attached['RecordAddress']})
    save(root/'fx/playback_fields.json',controls)
    hashed_literals=collections.defaultdict(list)
    for name, refs in literals.items():
        if re.fullmatch(r'hash_[0-9a-fA-F]+',name):hashed_literals[int(name[5:],16)&MASK].extend(refs)
    events=[{'AttachedName':name,'Placements':rows,'ScriptReferences':literals.get(name,[])+hashed_literals.get(fnv(name),[]),
             'Status':'exact attached string or 60-bit hash match; does not prove this script branch ran in the captured map'} for name,rows in sorted(groups.items())]
    save(root/'fx/event_references.json',events)
    counts['attached_names_with_script_references']=sum(bool(r['ScriptReferences']) for r in events)
    # Decoded behavior is narrower than the automatic source-reference index.
    scenes=json.loads((root/'animation/scene_placements.json').read_text())
    blockers='scripts/zm_common/zm_blockers.gsc'
    for row in scenes:
        p=row['SourceEntityProperties']; controls={
            'SceneLooping':bool(row['SceneControls'].get('looping',0)),
            'DisableCrossSceneSynchronization':bool(row['SceneControls'].get('dontsync',0)),
            'ForceNoCull':bool(row['ObjectControls'].get('forcenocull',0)),
            'ShotBlend':row['ShotControls'].get('blend',0),
            'ShotLerpTime':row['ShotControls'].get('lerptime',row['ObjectControls'].get('lerptime',0)),
            'AnimationAssetLooping':None,
            'Status':'authored defaults; runtime scene parameters may override them',
        }
        if p.get('script_string')=='dynamite' and p.get('script_bundle')==row['BundleName']:
            assert canonical('n_explosion_delay')==0xf912ea8d
            assert canonical('bundle_not_hide')==0x3e0f3ca4
            controls['DynamiteBlockerPath']={
                'DelaySeconds':p.get('n_explosion_delay',5),
                'HideOriginalEntityAfterSceneCall':not bool(p.get('bundle_not_hide',0)),
                'SceneRoot':'source entity passed explicitly to scene::play',
                'Requires':'the normal dynamite blocker open branch; not proof of activation',
                'Sources':[ref(blockers,n) for n in (946,960,965)]}
        row['DecodedPlaybackControls']=controls
    save(root/'animation/scene_placements.json',scenes)
    report={'Scope':'placement and playback controls only; appearance data excluded by user request',
            'DumpCommit':COMMIT,'IndexedScriptFiles':len(texts),'Counts':counts,
            'Limitations':['Script identifier matches are references, not runtime execution evidence.',
                'Compiled FX delay/scale/culling/state byte semantics remain candidates.',
                'Scene looping and animation-asset looping are distinct; asset looping remains unresolved.']}
    save(root/'metadata/playback_reference_report.json',report)
    print(json.dumps(report,indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('root',type=Path);p.add_argument('dump',type=Path)
    a=p.parse_args();link(a.root,a.dump)
