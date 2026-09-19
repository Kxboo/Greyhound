"""Read animation notetracks for a captured map; no process writes or code injection."""

# Support direct execution and the isolated packaged Python runtime.
import sys as _tool_sys
from pathlib import Path as _ToolPath
TOOLS_ROOT = next(p for p in _ToolPath(__file__).resolve().parents if (p / "tool_bootstrap.py").is_file())
_tool_sys.path.insert(0, str(TOOLS_ROOT))
import tool_bootstrap as _tool_bootstrap
_tool_bootstrap.activate(__file__)
REPO_ROOT = TOOLS_ROOT.parent
import argparse, ctypes as c, hashlib, json, math, struct
from pathlib import Path
from capture_cw_scriptbundles import MASK, dictionary, fnv

def capture(root, output):
    root, output=Path(root).resolve(), Path(output).resolve()
    if output.exists():raise ValueError('Choose a new evidence directory')
    bundles=json.loads((root/'animation/scriptbundles_decoded/bundles.json').read_text())
    process=bundles['process'];table=int(bundles['string_table'],16)
    k=c.WinDLL('kernel32',use_last_error=True)
    k.OpenProcess.argtypes=[c.c_uint32,c.c_int,c.c_uint32];k.OpenProcess.restype=c.c_void_p
    k.ReadProcessMemory.argtypes=[c.c_void_p,c.c_void_p,c.c_void_p,c.c_size_t,c.POINTER(c.c_size_t)]
    k.CloseHandle.argtypes=[c.c_void_p]
    handle=k.OpenProcess(0x410,False,process['pid'])
    if not handle:raise OSError(c.get_last_error())
    output.mkdir(parents=True);(output/'evidence').mkdir();reads={};total=0
    def memory(at,n):
        nonlocal total
        if not 0x10000<=at<0x800000000000 or not 0<n<=1024*1024 or total+n>32*1024*1024:raise ValueError('Read bounds exceeded')
        total+=n;b=c.create_string_buffer(n);got=c.c_size_t()
        if not k.ReadProcessMemory(handle,at,b,n,c.byref(got)) or got.value!=n:raise OSError(c.get_last_error())
        return b.raw
    def read(at,n):
        if (at,n) not in reads:
            b=memory(at,n);name=f'evidence/{at:x}_{n:x}.bin';(output/name).write_bytes(b);reads[at,n]=(b,name)
        return reads[at,n][0]
    try:
        assert memory(int(process['module_base'],16),2)==b'MZ'
        # Verify the exact map descriptor and singleton used for the saved capture.
        source=root/'diagnostics/non_static/level_fx'
        e=json.loads((source/'evidence.json').read_text())
        descriptor=next(r for r in e['reads'] if r['file']=='pool_descriptor.bin')
        d=read(int(descriptor['address'],16),32)
        h=read(struct.unpack_from('<Q',d)[0],40)
        assert struct.unpack_from('<Q',h)[0]&MASK==int(bundles['map_hash'],16),'Map changed'
        release=REPO_ROOT/'src/WraithXCOD/x64/Release'
        names=dictionary(release/'package_index/fnv1a_string.wni')
        for name in ('sound','rumble','vox','end','start','fx'):names.setdefault(fnv(name),name)
        def string(index):
            if index>4000000:raise ValueError('String handle out of bounds')
            at=table+index*16+16;h=struct.unpack('<Q',read(at,8))[0]&MASK
            return {'Handle':index,'Hash':hex(h),'Name':names.get(h),'StringEntryAddress':hex(at)}
        rows=[]
        for asset in json.loads((root/'animation/assets.json').read_text()):
            at=int(asset['RecordAddress'],16);b=read(at,288)
            assert b==bytes.fromhex(asset['RawRecordHex']),'Animation header changed'
            count=b[0x100];pointer=struct.unpack_from('<Q',b,0x38)[0]
            data=read(pointer,count*32) if count else b''
            notes=[]
            for i in range(count):
                nb=data[i*32:(i+1)*32];time=struct.unpack_from('<f',nb,24)[0]
                assert math.isfinite(time) and 0<=time<=1
                # Match Greyhound's single-precision multiply then integer cast.
                frame=int(struct.unpack('<f',struct.pack('<f',asset['FrameCount']*time))[0])
                notes.append({'Index':i,'RecordAddress':hex(pointer+i*32),'RawRecordHex':nb.hex(),
                    'PayloadHashRaw':hex(struct.unpack_from('<Q',nb)[0]),'PayloadHash':hex(struct.unpack_from('<Q',nb)[0]&MASK),
                    'Tag':string(struct.unpack_from('<I',nb,8)[0]),'Type':string(struct.unpack_from('<I',nb,20)[0]),
                    'NormalizedTime':time,'FrameUsingGreyhoundConvention':frame,
                    'SecondsUsingGreyhoundFrameConvention':frame/asset['FrameRate'] if asset['FrameRate']>0 else None})
            rows.append({'AnimationHash':asset['AnimationHash'],'Name':asset['Name'],
                'SourceAssetFile':'animation/assets.json','NotificationCount':count,'Notifications':notes,
                'SourceLayout':'BOCWXAnim +0x38 pointer, +0x100 count; NotetracksCW stride32, hash+0, tag+8, type+20, time+24',
                'PlacementMeaning':'events belong to the animation; placement requires a separate entity/bundle link'})
        stable=[]
        for (at,n),(b,name) in reads.items():
            stable.append({'address':hex(at),'bytes':n,'file':name,'unchanged':memory(at,n)==b,'sha256':hashlib.sha256(b).hexdigest()})
        report={'schema':'cw-animation-events-v1','process':process,'map_hash':bundles['map_hash'],
            'read_only':True,'records':rows,'reads':stable,'complete':all(r['unchanged'] for r in stable)}
        (output/'events.json').write_text(json.dumps(report,indent=2)+'\n')
        assert report['complete'],'Source changed during read'
        (root/'animation/notifications.json').write_text(json.dumps(rows,indent=2)+'\n')
        print(json.dumps({'assets':len(rows),'notifications':sum(r['NotificationCount'] for r in rows),'complete':report['complete']}))
    finally:k.CloseHandle(handle)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('root',type=Path);p.add_argument('output',type=Path)
    a=p.parse_args();capture(a.root,a.output)
