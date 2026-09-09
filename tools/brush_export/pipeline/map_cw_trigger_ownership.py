"""Join trigger entities to hull models using the traced Cold War spawn loop.

RVA0x7281000 increments the spawn-record offset by48 and model counter by1
on every iteration, including skipped spawns. It writes entity+0x290 only
when that counter is below triggerlist+8's model count. Do not compact the
entity array by classname, client/server status, or spawn eligibility.
"""
import argparse
import collections
import json
import math
import struct
from pathlib import Path
from audit_cw_clip_payloads import read_logical


def read_counted(root, evidence, name, width, expected_count=None):
    layout=json.loads((root/evidence['typed_candidates']['file']).read_text())
    records=[a for a in layout['arrays'] if a['file']==name]
    if len(records)!=1:raise ValueError('Missing or duplicate counted trigger array: '+name)
    record=records[0];count=record['count']
    if not isinstance(count,int) or not 0<=count<=200000 or record['candidate_stride']!=width or record['captured_bytes']!=count*width:
        raise ValueError('Invalid counted trigger array: '+name)
    if expected_count is not None and count!=expected_count:
        raise ValueError('Header count differs from trigger array: '+name)
    # Greyhound deliberately does not write files for zero-count arrays.
    data=read_logical(root,evidence,name) if count else b''
    if len(data)!=count*width:raise ValueError('Truncated trigger array: '+name)
    return data


def run(root):
    evidence = json.loads((root/'evidence.json').read_text())
    properties = json.loads((root/'triggers.json').read_text())['Entities']
    models = read_counted(root,evidence,'typed/trigger_models.bin',8)
    hulls = read_counted(root,evidence,'typed/trigger_hulls.bin',32)
    slabs = read_counted(root,evidence,'typed/trigger_slabs.bin',20)
    entities = read_counted(root,evidence,'typed/entity_records.bin',48)
    if len(models)%8 or len(hulls)%32 or len(slabs)%20 or len(entities)%48:
        raise ValueError('Record size mismatch')
    nm,nh,ns,ne = len(models)//8,len(hulls)//32,len(slabs)//20,len(entities)//48
    if nm>ne or len(properties)!=ne:
        raise ValueError('Model/entity counts inconsistent')
    if ne>32768:
        raise ValueError('Capture exceeds the nonnegative signed16 index range traced here')
    rows,extra = [],[]
    used_hulls,used_slabs = collections.Counter(),collections.Counter()
    class_masks = collections.defaultdict(collections.Counter)
    for index,props in enumerate(properties):
        origin = struct.unpack_from('<3f',entities,index*48+24)
        angles = struct.unpack_from('<3f',entities,index*48+36)
        if not all(math.isfinite(v) for v in (*origin,*angles)):
            raise ValueError('Nonfinite entity transform')
        name = props.get('targetname') or props.get('script_noteworthy') or props.get('classname','trigger')
        row = dict(entity_index=index,name=name,classname=props.get('classname'),
                   source_id=struct.unpack_from('<I',entities,index*48+20)[0],
                   origin=origin,angles=angles,properties=props)
        if index>=nm:
            row['geometry_status']='no_precompiled_model_index_assigned_by_traced_loop'
            extra.append(row)
            continue
        mask,count,first = struct.unpack_from('<IHH',models,index*8)
        if count==0 or first+count>nh:
            raise ValueError('Invalid hull range')
        decoded_hulls,combined = [],0
        for hi in range(first,first+count):
            center = struct.unpack_from('<3f',hulls,hi*32)
            half = struct.unpack_from('<3f',hulls,hi*32+12)
            contents,sc,sf = struct.unpack_from('<IHH',hulls,hi*32+24)
            if not all(math.isfinite(v) for v in (*center,*half)) or any(v<0 for v in half) or sf+sc>ns:
                raise ValueError('Invalid hull bounds or slab range')
            used_hulls[hi]+=1
            combined |= contents
            decoded_slabs=[]
            for si in range(sf,sf+sc):
                direction_x,direction_y,direction_z,midpoint,halfsize=struct.unpack_from('<5f',slabs,si*20)
                values=(direction_x,direction_y,direction_z,midpoint,halfsize)
                if not all(math.isfinite(v) for v in values) or halfsize<0 or abs(sum(v*v for v in values[:3])-1)>.001:
                    raise ValueError('Invalid slab')
                used_slabs[si]+=1
                decoded_slabs.append(dict(index=si,direction=values[:3],midpoint=midpoint,halfsize=halfsize))
            hrow=dict(hull_index=hi,local_center=center,local_halfsize=half,contents_raw=hex(contents),slabs=decoded_slabs)
            if all(a==0 for a in angles):
                hrow['world_aabb_min']=[o+c-h for o,c,h in zip(origin,center,half)]
                hrow['world_aabb_max']=[o+c+h for o,c,h in zip(origin,center,half)]
            decoded_hulls.append(hrow)
        row.update(model_index=index,association='code_traced_spawn_record_index',contents_raw=hex(mask),
                   model_contents_equal_hull_union=mask==combined,hulls=decoded_hulls)
        class_masks[row['classname']][hex(mask)]+=1
        rows.append(row)
    return dict(schema='cw_trigger_ownership_v1',source_capture=str(root),
                association_evidence=dict(spawn_loop_rva='0x7281000',index_write_rva='0x728118f',
                                          model_lookup_rva='0xc594b60',hull_bounds_rva='0xc5c2ea0'),
                summary=dict(entities=ne,models=nm,hulls=nh,slabs=ns,
                             hulls_referenced=len(used_hulls),slabs_referenced=len(used_slabs),
                             hulls_referenced_more_than_once=sum(v>1 for v in used_hulls.values()),
                             model_masks_equal_hull_union=sum(r['model_contents_equal_hull_union'] for r in rows),
                             zero_angle_models=sum(all(a==0 for a in r['angles']) for r in rows),
                             class_contents_histogram=dict(class_masks)),
                limitations=['Static code trace establishes the index rule; spawn eligibility is not inferred.',
                             'Contents values stay raw; classname does not name every contents bit.',
                             'World AABBs are emitted only for exactly zero rotation.'],
                models=rows,entities_without_precompiled_model=extra)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('capture',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    report=run(args.capture)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report['summary'],indent=2))
