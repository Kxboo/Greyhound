"""Verify native light placements and independent authored-light layout evidence."""

# Support direct execution and the isolated packaged Python runtime.
import sys as _tool_sys
from pathlib import Path as _ToolPath
TOOLS_ROOT = next(p for p in _ToolPath(__file__).resolve().parents if (p / "tool_bootstrap.py").is_file())
_tool_sys.path.insert(0, str(TOOLS_ROOT))
import tool_bootstrap as _tool_bootstrap
_tool_bootstrap.activate(__file__)
REPO_ROOT = TOOLS_ROOT.parent
import argparse,hashlib,json,math,struct
from pathlib import Path

def basis(angles):
    p,y,r=map(math.radians,angles);cp,sp,cy,sy,cr,sr=math.cos(p),math.sin(p),math.cos(y),math.sin(y),math.cos(r),math.sin(r)
    return [[cp*cy,cp*sy,-sp],[sr*sp*cy-cr*sy,sr*sp*sy+cr*cy,sr*cp],[cr*sp*cy+sr*sy,cr*sp*sy-sr*cy,cr*cp]]

def verify(native,reference,destination):
    native,reference,destination=map(lambda p:Path(p).resolve(),(native,reference,destination))
    load=lambda p:json.loads(p.read_text())
    raw=load(native/'light_placement_candidates.json');decoded=load(native/'light_placements.json')
    previous=load(destination/'lights/placements.json')
    assert [(x['SourceId'],x['RawRecordHex']) for x in previous]==[(x['SourceId'],x['RawRecordHex']) for x in raw]
    assert len(raw)==len(decoded)
    worst=0
    for i,(a,b) in enumerate(zip(raw,decoded)):
        data=bytes.fromhex(a['RawRecordHex']);assert b['PlacementValidated']
        assert b['SourcePlacementIndex']==i and b['SourceId']==a['SourceId']
        assert b['Guid']==struct.unpack_from('<I',data,0x48)[0]
        assert b['Position']==list(struct.unpack_from('<3f',data,0x68))
        expected=[[-v for v in struct.unpack_from('<3f',data,0x80)],[-v for v in struct.unpack_from('<3f',data,0x8c)],list(struct.unpack_from('<3f',data,0x74))]
        rebuilt=basis(b['AnglesPitchYawRoll']);error=max(abs(x-y) for u,v in zip(expected,rebuilt) for x,y in zip(u,v))
        assert error<2e-5;worst=max(worst,error)
        assert b['LocalAxesInWorld']==expected
        assert b['BO3']['origin']==b['Position'] and b['BO3']['angles']==b['AnglesPitchYawRoll']
    # This correspondence establishes semantics independently of the decoder.
    entities=[e for p in (reference/'entities').glob('*/*.json') for e in load(p) if e['ClassName']=='light']
    compiled=load(reference/'lights/placements.json');matches=[]
    for e in entities:
        guid=e['Properties']['guid']&0xffffffff
        hits=[x for x in compiled if struct.unpack_from('<I',bytes.fromhex(x['RawRecordHex']),0x48)[0]==guid]
        assert len(hits)==1,(guid,len(hits));x=hits[0];data=bytes.fromhex(x['RawRecordHex'])
        pos=[e['Position'][k] for k in 'XYZ'];assert pos==list(struct.unpack_from('<3f',data,0x68))
        actual=basis([e['SourceAngles'][k] for k in 'XYZ'])
        stored=[[-v for v in struct.unpack_from('<3f',data,0x80)],[-v for v in struct.unpack_from('<3f',data,0x8c)],list(struct.unpack_from('<3f',data,0x74))]
        error=max(abs(a-b) for u,v in zip(actual,stored) for a,b in zip(u,v));assert error<1e-5
        matches.append({'AuthoredEntityId':e['EntityId'],'CompiledSourceId':x['SourceId'],'Guid':guid,
            'Position':pos,'AuthoredAngles':[e['SourceAngles'][k] for k in 'XYZ'],'BasisMaxError':error,
            'RawRecordSHA256':hashlib.sha256(data).hexdigest()})
    assert len(matches)>=10
    for row in decoded:row['SourcePlacementFile']='lights/placements.json'
    (destination/'lights/decoded_placements.json').write_text(json.dumps(decoded,indent=2)+'\n')
    report={'status':'passed','native_capture':str(native),'reference_capture':str(reference),
        'light_placements':len(decoded),'authored_guid_position_orientation_matches':len(matches),
        'rotation_roundtrip_max_error':worst,'authored_matches':matches,
        'layout':{'guid':72,'position':104,'up':116,'back':128,'right':140,'stride':688},
        'scope':'position and orientation; no claim about light type, intensity, radius or BO3 appearance equivalence'}
    (destination/'metadata/light_placement_validation.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k!='authored_matches'},indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('native');p.add_argument('reference');p.add_argument('destination');a=p.parse_args();verify(a.native,a.reference,a.destination)
