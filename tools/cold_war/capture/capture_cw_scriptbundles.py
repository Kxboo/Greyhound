"""Capture typed script bundles referenced by map entities (read-only process access)."""

# Support direct execution and the isolated packaged Python runtime.
import sys as _tool_sys
from pathlib import Path as _ToolPath
TOOLS_ROOT = next(p for p in _ToolPath(__file__).resolve().parents if (p / "tool_bootstrap.py").is_file())
_tool_sys.path.insert(0, str(TOOLS_ROOT))
import tool_bootstrap as _tool_bootstrap
_tool_bootstrap.activate(__file__)
REPO_ROOT = TOOLS_ROOT.parent
import argparse,ctypes as c,hashlib,json,struct,re
from pathlib import Path
import lz4.block

MASK=(1<<60)-1
def fnv(s):
 h=0xcbf29ce484222325
 for v in s.encode():h=((h^v)*0x100000001b3)&((1<<64)-1)
 return h&MASK
def dictionary(path):
 if not path.is_file():return {}
 b=path.read_bytes();magic,version,count,packed,size=struct.unpack_from('<IHIII',b);assert magic==0x20494e57 and version==1
 b=lz4.block.decompress(b[18:18+packed],uncompressed_size=size);out={};p=0
 for _ in range(count):
  h=struct.unpack_from('<Q',b,p)[0];p+=8;end=b.index(0,p);out[h&MASK]=b[p:end].decode('utf-8');p=end+1
 assert p==len(b);return out

def capture(run,output):
 run=Path(run).resolve();output=Path(output).resolve()
 if output.exists():raise ValueError('Use a new evidence folder.')
 e=json.loads((run/'diagnostics/non_static/level_fx/evidence.json').read_text());process=e['process'];base=int(process['module_base'],16)
 poolbase=int(next(r['address'] for r in e['reads'] if r['file']=='pool_descriptor.bin'),16)-0x7f*32
 k=c.WinDLL('kernel32',use_last_error=True);k.OpenProcess.argtypes=[c.c_uint32,c.c_int,c.c_uint32];k.OpenProcess.restype=c.c_void_p
 k.ReadProcessMemory.argtypes=[c.c_void_p,c.c_void_p,c.c_void_p,c.c_size_t,c.POINTER(c.c_size_t)];k.CloseHandle.argtypes=[c.c_void_p]
 handle=k.OpenProcess(0x410,False,process['pid'])
 if not handle:raise OSError(c.get_last_error())
 output.mkdir(parents=True);(output/'evidence').mkdir();reads={};total=0
 def memory(at,n):
  nonlocal total
  if not 0x10000<=at<0x800000000000 or not 0<n<=8*1024*1024 or total+n>128*1024*1024:raise ValueError('Read bounds exceeded')
  total+=n;b=c.create_string_buffer(n);got=c.c_size_t()
  if not k.ReadProcessMemory(handle,at,b,n,c.byref(got)) or got.value!=n:raise OSError(c.get_last_error())
  return b.raw
 def read(at,n):
  key=(at,n)
  if key not in reads:
   b=memory(at,n);name=f'evidence/{at:x}_{n:x}.bin';(output/name).write_bytes(b);reads[key]=(b,name)
  return reads[key][0]
 try:
  assert memory(base,2)==b'MZ'
  fxheader=read(struct.unpack_from('<Q',read(poolbase+0x7f*32,32))[0],40)
  maphash=int(json.loads((run/'fx_anm_catalog.json').read_text())['map_hash'],16)
  assert struct.unpack_from('<Q',fxheader)[0]&MASK==maphash,'Map changed since placement capture'
  entities=[r for p in (run/'entities').glob('*/*.json') for r in json.loads(p.read_text())]
  requests={}
  for entity in entities:
   for key,value in entity['Properties'].items():
    if 'bundle' in key.lower() and isinstance(value,str) and value:
     if re.fullmatch(r'0x[0-9a-fA-F]+',value):h=int(value,16)&MASK;name=None
     else:h=fnv(value);name=value
     request=requests.setdefault(h,{'name':name,'references':[]})
     if name:request['name']=name
     request['references'].append({'entity':entity['EntityId'],'property':key,'value':value})
  d=read(poolbase+0x57*32,32);pool,stride,capacity=struct.unpack_from('<QII',d);loaded=struct.unpack_from('<I',d,20)[0]
  assert stride==48 and capacity<=65536 and loaded<=capacity
  headers=read(pool,capacity*stride);free=set();ptr=struct.unpack_from('<Q',d,24)[0]
  while ptr:
   assert pool<=ptr<pool+len(headers) and (ptr-pool)%48==0
   index=(ptr-pool)//48;assert index not in free;free.add(index);ptr=struct.unpack_from('<Q',headers,index*48)[0]
  assert len(free)==capacity-loaded
  release=REPO_ROOT/'src/WraithXCOD/x64/Release'
  names=dictionary(release/'package_index/fnv1a_string.wni')
  for file in ('fnv1a_xanims.wni','fnv1a_xmodels.wni'):names.update(dictionary(release/'package_index/echo000_bo4'/file))
  bo3_definition=Path('C:/Program Files (x86)/Steam/steamapps/common/Call of Duty Black Ops III/deffiles/scriptbundle.awi')
  key_sources={}
  if bo3_definition.is_file():
   for word in re.findall(r'"([A-Za-z_][A-Za-z_0-9]*)"',bo3_definition.read_text()):
    for value in (word,word.lower()):names.setdefault(fnv(value),value);key_sources[fnv(value)]=str(bo3_definition)
  # Same signature/LEA calculation as GameBlackOpsCW::LoadOffsets, followed
  # by LoadStringEntry's 16-byte entries. Code scanning has its own byte budget.
  pe=struct.unpack_from('<I',memory(base,64),60)[0];peh=memory(base+pe,264)
  section_count=struct.unpack_from('<H',peh,6)[0];optional=struct.unpack_from('<H',peh,20)[0]
  sections=memory(base+pe+24+optional,section_count*40);string_table=None;scan_bytes=0
  signature=re.compile(b'\x48\x8b\x53.\x48\x85\xd2\x74.\x48\x8b\x03\x48\x89\x02',re.S)
  for si in range(section_count):
   sec=sections[si*40:(si+1)*40];size,rva=struct.unpack_from('<II',sec,8)
   if not struct.unpack_from('<I',sec,36)[0]&0x20000000:continue
   for offset in range(0,size,1024*1024):
    n=min(size-offset,1024*1024+32);scan_bytes+=n
    if scan_bytes>512*1024*1024:raise ValueError('String-table signature scan limit')
    # Scan bytes are not retained wholesale. Preserve just the matching
    # instruction and the string entries actually used by the bundle.
    saved_total=total
    try:b=memory(base+rva+offset,n)
    except OSError:total=saved_total;continue
    total=saved_total
    match=signature.search(b)
    if match and match.start()+22<=len(b):
     at=base+rva+offset+match.start();code=read(at,22)
     string_table=at+22+struct.unpack_from('<i',code,18)[0];break
   if string_table is not None:break
  def string_value(index):
   if string_table is None or index>4000000:return {'string_handle':index,'value':None,'status':'string table resolution pending'}
   at=string_table+index*16+16;entry=read(at,8);h=struct.unpack('<Q',entry)[0]&MASK
   return {'string_handle':index,'string_entry_address':hex(at),'string_hash':hex(h),'value':names.get(h),'status':'resolved_from_string_table' if h in names else 'string_value_name_unresolved'}
  type_names={0:'string_handle',1:'hash',2:'integer',3:'float',4:'animation',5:'player_animation',6:'siege_animation',7:'model',10:'fx',13:'scriptbundle_string_handle',14:'scriptbundle',16:'material',17:'image',23:'enum_integer',26:'duration_integer'}
  found={struct.unpack_from('<Q',headers,i*48)[0]&MASK:i for i in range(capacity) if i not in free}
  records=[];active=set()
  def array(at,data,depth=0):
   if depth>12 or at in active:raise ValueError('Nested bundle depth/cycle limit')
   active.add(at);count,fields,subcount,subs=struct.unpack('<QQQQ',data)
   assert count<=8192 and subcount<=1024
   out={'address':hex(at),'fields':[],'subarrays':[]}
   values=read(fields,count*32) if count else b''
   for i in range(count):
    r=values[i*32:(i+1)*32];key,value,canon,string_ref,tag=struct.unpack_from('<QQIII',r)
    field={'address':hex(fields+i*32),'key_hash':hex(key&MASK),'key':names.get(key&MASK),'key_canonical':canon,'type':tag,'type_name':type_names.get(tag,'other_asset_type'),'raw_hex':r.hex()}
    if key&MASK in key_sources:field['key_reference']=key_sources[key&MASK]
    if tag in (2,23,26):field['value']=struct.unpack_from('<i',r,28)[0]
    elif tag==3:field['value']=struct.unpack_from('<f',r,28)[0]
    elif tag in (0,12,13,15,24,25,30):field.update(string_value(string_ref))
    else:field.update(value_hash=hex(value&MASK),value_name=names.get(value&MASK))
    out['fields'].append(field)
   subdata=read(subs,subcount*32) if subcount else b''
   for i in range(subcount):
    r=subdata[i*32:(i+1)*32];key,canon,unknown,n,items=struct.unpack('<QIIQQ',r);assert n<=2048
    children=read(items,n*32) if n else b''
    out['subarrays'].append({'key_hash':hex(key&MASK),'key':names.get(key&MASK),'raw_hex':r.hex(),'items':[array(items+j*32,children[j*32:(j+1)*32],depth+1) for j in range(n)]})
   active.remove(at);return out
  for h,request in requests.items():
   row={'name':request['name'] or names.get(h),'hash':hex(h),'source_entities':request['references'],'loaded':h in found}
   if h in found:
    i=found[h];header=headers[i*48:(i+1)*48];row.update(address=hex(pool+i*48),bundle_type_hash=hex(struct.unpack_from('<Q',header,8)[0]&MASK),objects=array(pool+i*48+16,header[16:48]))
   records.append(row)
  stable=[]
  for (at,n),(b,name) in reads.items():
   same=memory(at,n)==b;stable.append({'address':hex(at),'bytes':n,'file':name,'unchanged':same,'sha256':hashlib.sha256(b).hexdigest()})
  report={'schema':'cw-referenced-scriptbundles-v1','process':process,'map_hash':hex(maphash),'source_run':str(run),'read_only':True,'string_table':hex(string_table) if string_table else None,'records':records,'reads':stable,'complete':all(r['unchanged'] for r in stable)}
  (output/'bundles.json').write_text(json.dumps(report,indent=2)+'\n')
  print(json.dumps({'requested':len(requests),'loaded':sum(r['loaded'] for r in records),'complete':report['complete'],'output':str(output)},indent=2))
 finally:k.CloseHandle(handle)

if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('run',type=Path);p.add_argument('output',type=Path);a=p.parse_args();capture(a.run,a.output)
