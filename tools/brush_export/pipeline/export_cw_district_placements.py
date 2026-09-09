"""Decode captured CW district reference/transform arrays and place clip meshes."""
import argparse,json,struct,math
from pathlib import Path
import numpy as np
from export_cw_clip_mesh_candidates import decode
from cw_collision_names import hash63, collision_instance_name

def rotation(q):
 x,y,z,w=q
 return np.array([[1-2*(y*y+z*z),2*(x*y-z*w),2*(x*z+y*w)],
 [2*(x*y+z*w),1-2*(x*x+z*z),2*(y*z-x*w)],
 [2*(x*z-y*w),2*(y*z+x*w),1-2*(x*x+y*y)]])

def run(a):
 a.output.mkdir(parents=True,exist_ok=True)
 sources=json.loads((a.payloads/'report.json').read_text())
 hashes={int(r['address'],16):r for r in json.loads((a.hashes/'hashes.json').read_text())}
 models=json.loads((a.clips/'clip_map_models.json').read_text())['models']
 clips={int(m['name_hash'],16):m for m in models};meshes={}
 for h,m in clips.items():
  try:v,f,r=decode((a.clips/m['payload']['file']).read_bytes(),m)
  except (ValueError,struct.error):continue
  meshes[h]=(np.array(v),f,r)
 names={}
 if a.names:
  for m in json.loads(a.names.read_text())['models']:
   if m.get('name_resolved') is True and hash63(m['name'])==int(m['name_hash'],16):names[int(m['name_hash'],16)]=m['name']
 if a.name_index:
  from resolve_cw_ownership_names import load_names
  index=load_names(a.name_index)
  for h in clips:
   name=index.get(h&0xfffffffffffffff)
   if name and hash63(name)==h:names[h]=name
 instances=[];districts=[];base=1;placed=0;verts=0;faces=0;errors=[]
 with (a.output/'placed-clip-candidates.obj').open('w') as out:
  out.write('# World-space CW collision candidates; inches, Z up. Strip topology provisional.\n')
  for ordinal,source in enumerate(sources):
   # Source list was captured in district-table order, 0 followed by 12..23.
   district=0 if ordinal==0 else ordinal+11
   if 'file' not in source:
    districts.append(dict(district=district,status='payload_unavailable',source=source));continue
   b=(a.payloads/source['file']).read_bytes();address=int(source['address'],16)
   start,n=struct.unpack_from('<II',b,264);rp,tp=struct.unpack_from('<QQ',b,272);ro=rp-address;to=tp-address
   assert n>0 and ro>=0 and to>=0 and ro+64*n<=len(b) and to+64*n<=len(b)
   raw=np.frombuffer(b,dtype='<f4',count=n*16,offset=to).reshape(n,16)
   ids=raw.view('<u4')[:,14]&0x7fffffff
   assert sorted(ids.tolist())==list(range(n))
   assert np.isfinite(raw[:,:14]).all()
   assert np.max(abs((raw[:,:4].astype('float64')**2).sum(1)-1))<.002
   assert (raw[:,7]>0).all()
   districts.append(dict(district=district,status='decoded',start=start,count=n,readback_unchanged=source['stable'],reference_offset=ro,transform_offset=to,index_permutation=True))
   for row,t in enumerate(raw):
    idx=int(ids[row]);ref=ro+64*idx;ptr=struct.unpack_from('<Q',b,ref+16)[0]
    hrow=hashes[ptr];assert hrow.get('stable');h=int(hrow['hash'],16)
    q=list(map(float,t[:4]));pos=list(map(float,t[4:7]));scale=float(t[7]);x,y,z,w=q
    euler=[math.degrees(math.atan2(2*(w*x+y*z),1-2*(x*x+y*y))),math.degrees(math.asin(max(-1,min(1,2*(w*y-z*x))))),math.degrees(math.atan2(2*(w*z+x*y),1-2*(y*y+z*z)))]
    item=dict(district=district,transform_row=row,reference_index=idx,model_hash=hex(h),name=names.get(h,hex(h)),position=pos,quaternion_xyzw=q,uniform_scale=scale,rotation_degrees_xyz=euler,stored_world_mins=t[8:11].tolist(),stored_world_maxs=t[11:14].tolist(),clip_hash_match=h in clips,clip_mesh_exported=h in meshes)
    if h in meshes:
     v,f,r=meshes[h];world=(v*scale)@rotation(q).T+pos
     obj=collision_instance_name(names.get(h),h,district,idx);out.write('o '+obj+'\n')
     out.writelines('v '+' '.join(f'{c:.7g}' for c in p)+'\n' for p in world)
     out.writelines('f '+' '.join(str(base+i) for i in tri)+'\n' for tri in f)
     base+=len(v);verts+=len(v);faces+=len(f);placed+=1
     item['obj_object']=obj;item['clip_coordinate_bounds_pass']=r['bounds_within_one_quantum']
    instances.append(item)
 summary=dict(map='zm_silver',expected_instances=38334,decoded_instances=len(instances),unavailable_instances=38334-len(instances),unique_model_hashes=len({i['model_hash'] for i in instances}),clip_hash_matched_instances=sum(i['clip_hash_match'] for i in instances),placed_clip_instances=placed,obj_vertices=verts,obj_triangles=faces,districts=districts,units='game inches',euler_convention='ZYX intrinsic; XYZ roll/pitch/yaw degrees',status='District index mapping established; final district unavailable; mesh topology provisional')
 (a.output/'placements.json').write_text(json.dumps(dict(summary=summary,instances=instances),indent=2))
 (a.output/'summary.json').write_text(json.dumps(summary,indent=2));print(json.dumps({k:v for k,v in summary.items() if k!='districts'},indent=2))

if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__)
 for name in ('payloads','hashes','clips','output'):p.add_argument('--'+name,type=Path,required=True)
 p.add_argument('--names',type=Path)
 p.add_argument('--name-index',type=Path,help='Greyhound fnv1a_xmodels.wni; names must pass full collision-hash verification')
 run(p.parse_args())
