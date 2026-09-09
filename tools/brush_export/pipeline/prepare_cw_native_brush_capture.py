"""Normalize Greyhound collision evidence for the direct Radiant brush exporter."""
import argparse, hashlib, json, struct
from pathlib import Path
from collections import Counter
import numpy as np
from audit_cw_clip_payloads import read_logical
from export_cross_map_cw_geometry import decode_brushes
from export_cw_district_placements import rotation
from cw_collision_names import hash63

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('capture',type=Path);p.add_argument('--map',required=True);p.add_argument('--verified-map-hash')
    p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    e=json.loads((a.capture/'evidence.json').read_text())
    if e.get('required_reads_saved') is not True or e.get('descriptor_unchanged') is not True or e.get('headers_readback_unchanged') is not True:
        raise ValueError('Native capture is incomplete or failed its required stability checks')
    source=json.loads((a.capture/'clip_map_models.json').read_text())
    owners=json.loads((a.capture/'collision_world_instances.json').read_text())
    if owners['status']!='captured':raise ValueError('Native collision ownership capture failed')
    expected=int(a.verified_map_hash,16) if a.verified_map_hash else hash63('maps/zm/'+a.map+'.d3dbsp')
    if int(owners['map_hash'],16)!=expected:raise ValueError('Map hash differs from requested map')
    if (a.output/'capture.json').exists():raise ValueError('Choose a fresh output directory')
    (a.output/'payloads').mkdir(parents=True,exist_ok=True)
    models=[];statuses=Counter();instances=[]
    for i,m in enumerate(source['models']):
        model={**m,'index':i}
        payload=m['payload']
        if payload.get('status')!='captured' or payload.get('readback_unchanged') is not True:raise ValueError(('Missing or unverified payload',i))
        raw=read_logical(a.capture,e,payload['file'])
        if len(raw)!=payload['allocated_bytes']:raise ValueError(('Incomplete payload',i))
        if raw[336:360]!=struct.pack('<6f',*m['mins'],*m['maxs']):model['status']='outside_supported_brush_layout'
        elif len(raw)<372 or not struct.unpack_from('<I',raw,368)[0]:model['status']='layout_without_brushes'
        else:
            g=decode_brushes(raw,m)
            if not g or g['status']!='decoded':raise ValueError(('Unsupported brush payload',i))
            model.update(status='decoded',brush_count=g['brush_count'])
            name=f'payloads/{i:05d}.bin';(a.output/name).write_bytes(raw)
            model['payload']={**payload,'file':name,'sha256':hashlib.sha256(raw).hexdigest()}
        models.append(model);statuses[model['status']]+=1
    for inst in owners['instances']:
        m=models[inst['model_index']]
        if int(m['record_address'],16)!=int(inst['collision_pointer'],16):raise ValueError('Broken direct pointer join')
        if m['status']!='decoded':continue
        lo=np.array(m['mins']);hi=np.array(m['maxs']);r=rotation(inst['quaternion_xyzw']);s=inst['uniform_scale']
        center=r@((lo+hi)*.5*s)+inst['position'];half=abs(r)@((hi-lo)*.5*s)
        err=float(abs(np.r_[center-half-1,center+half+1]-np.r_[inst['stored_world_mins'],inst['stored_world_maxs']]).max())
        instances.append({**inst,'world_bounds_error':err,'bounds_within_silver_tolerance':err<=.001})
    summary={**owners['summary'],'statuses':dict(statuses),'unique_brushes':sum(m.get('brush_count',0) for m in models),'brush_asset_instances':len(instances),'placed_brushes':sum(models[x['model_index']]['brush_count'] for x in instances),'max_bounds_error':max((x['world_bounds_error'] for x in instances),default=0)}
    provenance={name:hashlib.sha256((a.capture/name).read_bytes()).hexdigest() for name in ('evidence.json','clip_map_models.json','collision_world_instances.json')}
    doc=dict(schema='cw_brush_pipeline_capture_v1',map=a.map,map_hash=owners['map_hash'],native_capture=str(a.capture.resolve()),native_source_sha256=provenance,summary=summary,models=models,instances=instances,worlds=owners['worlds'])
    (a.output/'capture.json').write_text(json.dumps(doc,indent=2));print(json.dumps(summary,indent=2))

if __name__=='__main__':main()
