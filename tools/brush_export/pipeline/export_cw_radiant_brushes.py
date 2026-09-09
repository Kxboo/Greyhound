"""Export captured CW brush hulls directly to BO3; no Blender or C2M needed.
This is a versioned conversion policy, not an original authored-brush recovery.
"""
import argparse,json,hashlib,time,math
from pathlib import Path
from collections import Counter
import numpy as np
from export_cross_map_cw_geometry import decode_brushes
from cw_exact_vertex_hull import exact_hull,sub,cross,dot
from export_cw_full_brush_map import hull_planes,face_text
from repair_cw_map_face_limit import planes_for_tetra
from export_cw_district_placements import rotation
from build_cw_bo3_brush_prototype import read_map_planes,materials
CHOICES={0x80:'clip_missile',0x400:'clip_physics',0x1040:'nosight_noclip',0x10000:'clip_player',0x20000:'clip_ai',0x130200:'clip',0x131640:'clip_nosight',0x1336c0:'clip_full'}
def pieces(vertices,faces,limit):
 eq=hull_planes(dict(vertices=vertices,faces=faces))
 if len(eq)<=limit:return [(np.array(vertices),eq)],dict(partitioned=False,source_support_planes=len(eq))
 v=np.array(vertices);points=np.vstack((v,v.mean(axis=0)));ci=len(v)
 ratios=[[float(x).as_integer_ratio() for x in p] for p in points];den=max(d for p in ratios for _,d in p);ints=[tuple(n*(den//d) for n,d in p) for p in ratios];boundary=Counter();vol=0;result=[]
 for f in faces:
  a,b,c=(sub(ints[i],ints[ci]) for i in f);d=dot(a,cross(b,c))
  if d<=0:raise ValueError('Nonpositive exact partition volume')
  vol+=d
  for tri in [(ci,f[1],f[0]),(ci,f[2],f[1]),(ci,f[0],f[2]),tuple(f)]:boundary[min(tri,tri[1:]+tri[:1],tri[2:]+tri[:2])]+=1
  tet=points[[ci,*f]];result.append((tet,planes_for_tetra(tet)))
 external=[]
 for f,n in boundary.items():
  rev=(f[0],f[2],f[1]);rev=min(rev,rev[1:]+rev[:1],rev[2:]+rev[:2])
  if ci in f:assert n==boundary[rev]==1
  else:assert n==1;external.append(f)
 assert sorted(external)==sorted(min(tuple(f),tuple(f[1:]+f[:1]),tuple(f[2:]+f[:2])) for f in faces)
 return result,dict(partitioned=True,source_support_planes=len(eq),pieces=len(result),internal_faces_cancel=True,external_triangles_unchanged=True,positive_exact_volumes=True,volume_numerator=str(vol),volume_denominator=str(6*den**3))
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('capture',type=Path);p.add_argument('--output',type=Path,required=True);p.add_argument('--gdt',type=Path,required=True);p.add_argument('--cleanup-world-tolerance',type=float,default=0.,help='Opt-in bounded outward simplification in world inches; source evidence is unchanged');p.add_argument('--max-faces',type=int,default=32);p.add_argument('--partition-trigger',type=int,help='Keep source hulls up to this plane count whole; subdivided regions still use max-faces');p.add_argument('--halfspace-partitions',action='store_true');p.add_argument('--canonical-planes',action='store_true');p.add_argument('--compact-partitions',action='store_true');p.add_argument('--spatial-partitions',action='store_true');a=p.parse_args();assert 4<=a.max_faces<=64
 if a.halfspace_partitions and (not a.cleanup_world_tolerance or a.compact_partitions or a.spatial_partitions):raise ValueError('Halfspace partition requires cleanup and a single partition policy')
 writer=None;write_faces=face_text
 if a.canonical_planes:
  from cw_canonical_map_planes import CanonicalPlaneWriter
  writer=CanonicalPlaneWriter();write_faces=writer.lines
 partition=pieces
 if a.compact_partitions:
  from cw_compact_brush_partition import compact_pieces
  partition=compact_pieces
 if a.spatial_partitions:
  if a.compact_partitions:raise ValueError('Select one partition policy')
  from cw_spatial_brush_partition import spatial_pieces
  partition=spatial_pieces
 if a.partition_trigger is not None:
  if not a.max_faces<=a.partition_trigger<=64:raise ValueError('Invalid partition trigger')
  selected=partition
  def partition(vertices,faces,limit):
   eq=hull_planes(dict(vertices=vertices,faces=faces))
   if len(eq)<=a.partition_trigger:return [(np.array(vertices),eq)],dict(partitioned=False,source_support_planes=len(eq))
   return selected(vertices,faces,limit)
 j=json.loads((a.capture/'capture.json').read_text());a.output.mkdir(exist_ok=True,parents=True);known=materials(a.gdt);assert set(CHOICES.values())|{'clip'}<=set(known)
 policy=dict(version=1,capture_sha256=hashlib.sha256((a.capture/'capture.json').read_bytes()).hexdigest(),max_faces=a.max_faces,partition_trigger=a.partition_trigger,cleanup_world_tolerance=a.cleanup_world_tolerance,halfspace_partitions=a.halfspace_partitions,compact_partitions=a.compact_partitions,spatial_partitions=a.spatial_partitions,helpers={n:hashlib.sha256((Path(__file__).parent/n).read_bytes()).hexdigest() for n in ['cw_bounded_brush_cleanup.py','cw_halfspace_partition.py','cw_exact_vertex_hull.py','cw_compact_brush_partition.py','cw_spatial_brush_partition.py','export_cw_full_brush_map.py']})
 policy_path=a.output/'hull-cache-policy.json'
 if policy_path.exists():
  if json.loads(policy_path.read_text())!=policy:raise ValueError('Cached geometry policy changed: select a fresh output directory')
 elif (a.output/'hull-cache').exists():raise ValueError('Cache provenance missing: select a fresh output directory')
 else:policy_path.write_text(json.dumps(policy,indent=2))
 mesh={};rows=[];certs=[];last=time.monotonic();checks=[];unsupported=Counter();source_brushes=0;placements=Counter(x['model_index'] for x in j['instances'])
 assert 0<=a.cleanup_world_tolerance<=.01
 scales={}
 for inst in j['instances']:
  k=inst['model_index'];scales[k]=max(scales.get(k,0.),float(np.linalg.norm(rotation(inst['quaternion_xyzw'])*inst['uniform_scale'],2)))
 for model in j['models']:
  if model['status']!='decoded':unsupported[model['status']]+=1;continue
  raw=(a.capture/model['payload']['file']).read_bytes();assert hashlib.sha256(raw).hexdigest()==model['payload']['sha256'];g=decode_brushes(raw,model);assert g and g['status']=='decoded'
  for brush in g['brushes']:
   cache_key=f"{model['index']}_{brush['brush_index']}"
   cache_dir=a.output/'hull-cache';cache_dir.mkdir(exist_ok=True)
   cache_path=cache_dir/(cache_key+'.json')
   if cache_path.exists():
    cached=json.loads(cache_path.read_text());assert cached['payload_sha256']==model['payload']['sha256']
    mesh[(model['index'],brush['brush_index'])]=([(np.array(v),np.array(e)) for v,e in cached['parts']],brush);certs.append(cached['certificate']);source_brushes+=1;continue
   faces,exact=exact_hull(brush['vertices'])
   cleanup_info=None
   if a.cleanup_world_tolerance:
    from cw_bounded_brush_cleanup import cleanup
    clean_points,clean_eq,cleanup_info=cleanup(brush['vertices'],faces,a.cleanup_world_tolerance/max(scales.get(model['index'],1.),1e-12),method='linear_program' if a.halfspace_partitions else 'cluster')
    cleanup_info['max_world_outward_distance']=cleanup_info['max_outward_distance']*scales.get(model['index'],1.)
    if len(clean_eq)<=a.max_faces:
     parts=[(clean_points,clean_eq)];cert=dict(partitioned=False,source_support_planes=cleanup_info['original_planes'])
    elif a.halfspace_partitions:
     from cw_halfspace_partition import partition as split_halfspaces
     parts,cert=split_halfspaces(clean_points,clean_eq,a.max_faces)
    else:
     # Do not silently apply a second approximate transformation.
     parts,cert=partition(brush['vertices'],faces,a.max_faces)
     cleanup_info['used']=False
    if a.halfspace_partitions:
     from cw_bounded_brush_cleanup import surface_distances
     source=np.asarray(brush['vertices']);base=source.mean(axis=0);old_eq=hull_planes(dict(vertices=brush['vertices'],faces=faces));output=np.vstack([v for v,e in parts]);outside=output[(output@old_eq[:,:3].T-old_eq[:,3]).max(axis=1)>1e-8]
     bound=max(surface_distances(outside-base,(source-base)[faces]),default=0.)*scales.get(model['index'],1.)
     if bound>a.cleanup_world_tolerance+1e-7:raise ValueError(('Final partition exceeds world bound',model['index'],brush['brush_index'],bound))
     cleanup_info['final_partition_world_distance']=bound
    cert['cleanup']=cleanup_info
   else:parts,cert=partition(brush['vertices'],faces,a.max_faces)
   key=(model['index'],brush['brush_index']);mesh[key]=(parts,brush);certs.append(dict(model_index=key[0],brush_index=key[1],name_hash=model['name_hash'],instances=placements[key[0]],**cert));source_brushes+=1
   cache_path.write_text(json.dumps(dict(payload_sha256=model['payload']['sha256'],parts=[(v.tolist(),e.tolist()) for v,e in parts],certificate=certs[-1])))
   if time.monotonic()-last>5:print(f'Hulls: {source_brushes}/{j["summary"]["unique_brushes"]}; asset {model["index"]}, brush {brush["brush_index"]}',flush=True);last=time.monotonic()
  if time.monotonic()-last>5:print(f'Hulls: {source_brushes}/{j["summary"]["unique_brushes"]}',flush=True);last=time.monotonic()
 layers={'000_Global'};body=a.output/'brush-body.tmp';maxerr=0.;maxoutside=0.;maxbounds=0.;rejected=[]
 with body.open('w') as out:
  for ordinal,inst in enumerate(j['instances']):
   model=j['models'][inst['model_index']];rot=rotation(inst['quaternion_xyzw']);scale=inst['uniform_scale'];pos=np.array(inst['position']);lo=np.array(model['mins']);hi=np.array(model['maxs'])
   # Scale-aware float32 roundoff budget, not a fitted geometry transform.
   budget=max(.001,float(8*np.finfo(np.float32).eps*(max(abs(pos))+max(abs(np.r_[lo,hi]))*scale+1)))
   if inst['world_bounds_error']>budget:rejected.append(dict(world=inst['collision_world'],instance=inst['instance_index'],error=inst['world_bounds_error'],budget=budget));continue
   maxbounds=max(maxbounds,inst['world_bounds_error']);checks.append(dict(world=inst['collision_world'],instance=inst['instance_index'],bounds_error=inst['world_bounds_error'],roundoff_budget=budget))
   for bi in range(model['brush_count']):
    parts,brush=mesh[(model['index'],bi)];mask=brush['collision_flags_raw'];mat=CHOICES.get(mask,'clip');kind='PROPERTY_MATCH' if mask in CHOICES else 'REVIEW_PLACEHOLDER';layer=f'000_Global/{kind}/{mask:08x}_{mat}';layers.update([f'000_Global/{kind}',layer])
    for piece,(points,local) in enumerate(parts):
     world=points@(rot*scale).T+pos;n=local[:,:3]@np.linalg.inv(rot*scale);eq=np.column_stack((n,local[:,3]+n@pos));eq/=np.linalg.norm(eq[:,:3],axis=1)[:,None];lines=write_faces(eq,world.mean(axis=0),mat);parsed=np.array(read_map_planes('\n'.join(lines)));error=float(abs(parsed-eq).max());outside=float((world@parsed[:,:3].T-parsed[:,3]).max())
     if not np.isfinite(parsed).all() or not np.isfinite(eq).all() or not np.isfinite(world).all() or error>1e-6 or outside>1e-6:raise ValueError(('Serialization drift',ordinal,bi,piece,error,outside))
     maxerr=max(maxerr,error);maxoutside=max(maxoutside,outside)
     out.write(f'// brush {len(rows)}\n{{\nlayer "{layer}"\n'+'\n'.join(lines)+'\n}\n')
     rows.append(dict(map_brush_index=len(rows),collision_asset_index=model['index'],collision_hash=model['name_hash'],brush_index=bi,collision_world=inst['collision_world'],instance_index=inst['instance_index'],collision_pointer=inst['collision_pointer'],partition_piece=piece,partitioned=len(parts)>1,face_count=len(eq),contents_low26=f'0x{mask:08x}',packed_flags_and_plane_count=f'0x{brush["packed_flags_and_plane_count"]:08x}',nonaxial_plane_count=brush['nonaxial_plane_count'],assigned_material=mat,assignment_status=kind,layer=layer,position=inst['position'],quaternion_xyzw=inst['quaternion_xyzw'],uniform_scale=scale,world_mins=world.min(axis=0).tolist(),world_maxs=world.max(axis=0).tolist()))
   if time.monotonic()-last>5:print(f'Placements: {ordinal+1}/{len(j["instances"])}; output brushes {len(rows)}',flush=True);last=time.monotonic()
 if rejected:(a.output/'rejected-placements.json').write_text(json.dumps(rejected,indent=2));raise ValueError('Bounds validation rejected placements')
 target=a.output/(j['map']+'_brush_collision.map')
 with target.open('w') as out:
  out.write('iwmap 4\n'+''.join(f'"{l}" flags'+(' active' if l=='000_Global' else '')+'\n' for l in sorted(layers))+'// entity 0\n{\n"classname" "worldspawn"\n');out.write(body.read_text());out.write('}\n')
 body.unlink()
 report=dict(schema='cw_radiant_brush_pipeline_v1',map=j['map'],source_capture=str(a.capture.resolve()),source_capture_sha256=hashlib.sha256((a.capture/'capture.json').read_bytes()).hexdigest(),summary=dict(unique_brushes=source_brushes,placed_source_brushes=j['summary']['placed_brushes'],output_brushes=len(rows),partitioned_unique_brushes=sum(c['partitioned'] for c in certs),max_faces=max(r['face_count'] for r in rows),max_serialized_plane_error=maxerr,max_source_vertex_outside=maxoutside,max_instance_bounds_error=maxbounds,unsupported_collision_assets=dict(unsupported)),partition_policy=dict(max_faces=a.max_faces,unpartitioned_source_limit=a.partition_trigger or a.max_faces,compact_exact_convex_merges=a.compact_partitions,spatial_exact_cuts=a.spatial_partitions,method=('Exact rational axial cuts, preserving exterior planes and volume; no map-specific indices' if a.spatial_partitions else 'Interior-point tetrahedral partition, preserving exterior triangles; no map-specific brush indices'),compiler_validated=False),geometry_policy='Exact-predicate hulls of captured vertices; stored runtime planes are retained in capture and may differ; no AABB substitution or cross-brush deduplication',material_policy='Reviewed BO3 contents-name matches only; unmatched masks are explicit clip placeholders, not proved gameplay equivalence',units='game inches; collision transforms baked once; no render-model placements or Blender intermediate',rows=rows,partition_certificates=certs,placement_validation=checks,map_sha256=hashlib.sha256(target.read_bytes()).hexdigest())
 if a.cleanup_world_tolerance:
  report['geometry_policy']='Bounded outward approximation of captured vertex hulls, followed by plane-preserving subdivision when selected. Source payloads retained; no brushes dropped or cross-brush deduplication. This is not exact original authored geometry.'
 if a.halfspace_partitions:
  report['partition_policy']['method']='Complementary halfspace cuts, including cuts through high-valence vertices. Exterior equations retained for these cuts; any tetrahedral fallback is explicitly recorded. Exact-predicate volume calculation with numerical relative-volume and source-distance acceptance.'
  report['partition_policy']['halfspace_partitions']=True
 report['bounded_cleanup']=dict(enabled=bool(a.cleanup_world_tolerance),world_tolerance=a.cleanup_world_tolerance,source_payloads_unchanged=True,method='Subset of source support planes; outer-vertex distance to source convex hull bounds outward deviation, evaluated numerically')
 if a.cleanup_world_tolerance:
  import platform,scipy
  report['runtime_versions']=dict(python=platform.python_version(),numpy=np.__version__,scipy=scipy.__version__)
  report['implementation_sha256']={n:hashlib.sha256((Path(__file__).parent/n).read_bytes()).hexdigest() for n in ['export_cw_radiant_brushes.py','cw_bounded_brush_cleanup.py','cw_halfspace_partition.py','cw_exact_vertex_hull.py','cw_canonical_map_planes.py']}
  report['bounded_cleanup']['summary']=dict(changed_unique_brushes=sum(bool(c.get('cleanup',{}).get('changed')) and c.get('cleanup',{}).get('used',True) for c in certs),partitioned_unique_brushes=sum(c['partitioned'] for c in certs),max_measured_world_outward_distance=max(c.get('cleanup',{}).get('final_partition_world_distance',c.get('cleanup',{}).get('max_world_outward_distance',0.)) for c in certs),remaining_tetra_fallback_regions=sum(len(c.get('tetrahedral_fallback_regions',[])) for c in certs),max_relative_cut_volume_error=max((cut['relative_volume_error'] for c in certs for cut in c.get('cuts',[])),default=0.))
 report['plane_serialization']=dict(canonical_exact_equation_reuse=writer is not None,basis=writer.basis if writer else 128,distinct_definitions=len(writer.cache) if writer else None)
 (a.output/'collision_metadata.json').write_text(json.dumps(report,indent=2));print(json.dumps(report['summary'],indent=2),flush=True)
if __name__=='__main__':main()
