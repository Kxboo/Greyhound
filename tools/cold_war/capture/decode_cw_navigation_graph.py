"""Validate GAME_MAP volume partners, mantle references and sampled edge points.

Offsets are hypotheses checked against independent ENTITYLIST properties and
reciprocal index structure. No claim of complete navigation/runtime semantics.
"""

# Support direct execution and the isolated packaged Python runtime.
import sys as _tool_sys
from pathlib import Path as _ToolPath
TOOLS_ROOT = next(p for p in _ToolPath(__file__).resolve().parents if (p / "tool_bootstrap.py").is_file())
_tool_sys.path.insert(0, str(TOOLS_ROOT))
import tool_bootstrap as _tool_bootstrap
_tool_bootstrap.activate(__file__)
REPO_ROOT = TOOLS_ROOT.parent
import argparse
from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path
import struct
from decode_cw_entitylist import require


VOLUME = 'node_negotiation_volume'
MANTLE = 'node_negotiation_mantle'
NULL_INDEX = 0xFFFFFFFF
KNOWN_IGNORE_BITS = {'bot':0, 'vehicle':10, 'dog':8, 'zombie_dog':14}


def decode(root, entity_document):
    root = Path(root)
    capture = json.loads((root/'capture.json').read_text())
    require(capture['required_reads_unchanged'], 'Unstable node capture')
    for entry in capture['files']:
        path=(root/entry['file']).resolve()
        require(path.is_relative_to(root.resolve()),'Capture file escapes root')
        data=path.read_bytes()
        require(len(data)==entry['bytes'] and hashlib.sha256(data).hexdigest()==entry['sha256'],'Capture file integrity failed: '+entry['file'])
    header=(root/'header.bin').read_bytes()
    raw=(root/'nodes176.bin').read_bytes()
    child_bytes=(root/'children12.bin').read_bytes()
    children=json.loads((root/'children-capture.json').read_text())
    maphash=entity_document['source']['name_hash']
    require(int(maphash,16)==struct.unpack_from('<Q',header)[0] and capture['map_hash']==maphash,'Map hashes differ')
    entities=[e for e in entity_document['entities'] if e['classname'].startswith('node_')]
    count,=struct.unpack_from('<I',header,8)
    require(len(raw)==count*176 and len(entities)==count,'Node and filtered entity counts disagree')
    require(children['readback_unchanged'] and children['node_and_header_readback_unchanged'],'Unstable children capture')
    arrays={a['node']:a for a in children['arrays']}
    base=int(children['address'],16)
    nodes=[]
    for i,e in enumerate(entities):
        row=raw[i*176:(i+1)*176]
        typ,=struct.unpack_from('<H',row,40)
        partner,mantle=struct.unpack_from('<II',row,84)
        mask,=struct.unpack_from('<I',row,68)
        position=struct.unpack_from('<3f',row,20)
        half=struct.unpack_from('<3f',row,8)
        direction=struct.unpack_from('<2f',row,32)
        yaw,=struct.unpack_from('<f',row,104)
        named=e['conversion_keyvalues']
        ignored=[v.strip() for v in named.get('movementtype_ignore','').split(',') if v.strip()]
        points=[];geometry=None
        if e['classname'] in (VOLUME,MANTLE):
            require(typ==(20 if e['classname']==VOLUME else 19),'Node class/type correspondence changed')
            require(list(position)==e['origin'],'Volume/mantle record position differs from ENTITYLIST')
            require(all(2*h==float(named[k]) for h,k in zip(half,('width','length','height'))),'Node dimensions differ from ENTITYLIST')
            require(abs((yaw-e['angles'][1]+180)%360-180)<0.001,'Yaw differs from ENTITYLIST')
            require(max(abs(direction[0]-math.cos(math.radians(yaw))),abs(direction[1]-math.sin(math.radians(yaw))))<0.001,'Direction differs from yaw')
            require(i in arrays,'Missing volume/mantle edge points')
            a=arrays[i];at=struct.unpack_from('<Q',row)[0];n=struct.unpack_from('<H',row,116)[0]
            require(at==a['address'] and n==a['count'],'Child pointer/count differs')
            offset=at-base
            require(offset>=0 and offset+n*12<=len(child_bytes),'Child points outside capture')
            points=[list(struct.unpack_from('<3f',child_bytes,offset+j*12)) for j in range(n)]
            require(all(math.isfinite(v) for p in points for v in p),'Nonfinite edge point')
            co,si=direction;px,py,pz=position
            local=[[(x-px)*co+(y-py)*si,-(x-px)*si+(y-py)*co,z-pz] for x,y,z in points]
            side=0 if typ==19 else (1 if local[0][0]>0 else -1)
            order=-1 if typ==19 else side
            error_x=max(abs(p[0]-side*half[0]) for p in local)
            error_end=max(abs(local[0][1]-order*(-half[1]+1)),abs(local[-1][1]-order*(half[1]-1)))
            error_step=max([abs(local[j+1][1]-local[j][1]-order*8) for j in range(n-2)] or [0])
            require(n==math.ceil((2*half[1]-2)/8)+1 and max(error_x,error_end,error_step)<0.001,'Sampled edge geometry no longer agrees')
            if typ==20:
                for name,bit in KNOWN_IGNORE_BITS.items():
                    require(bool(mask&(1<<bit))==(name in ignored),'Known movement-ignore bit differs: '+name)
            geometry=dict(measured_local_side=side,source_local_half_dimensions=list(half),
                          x_error=error_x,endpoint_error=error_end,step_error=error_step,
                          sampling='Local Y from length/2-1 to opposite inset, steps of 8 with shortened last interval',
                          z_rule='Captured values retained; no height projection or constant vertical offset assumed')
        cost,=struct.unpack_from('<f',row,92)
        if 'cost_modifier' in named:
            require(struct.pack('<f',float(named['cost_modifier']))==row[92:96],'Cost differs from named property')
        nodes.append(dict(index=i,source_entity_index=e['index'],classname=e['classname'],type_u16=typ,
                          position=list(position),angles=e['angles'],compiled_yaw=yaw,compiled_direction=list(direction),raw_record_hex=row.hex(),
                          partner_index=partner,mantle_index=mantle,movement_ignore_mask=hex(mask),
                          movement_ignore_names=ignored,cost_modifier=cost,edge_points=points,
                          geometry_validation=geometry,source_properties=named))
    named=defaultdict(list)
    for i,e in enumerate(entities):
        if e['conversion_keyvalues'].get('targetname'):
            named[e['conversion_keyvalues']['targetname']].append(i)
    pairs=[];text_checks=[];recoveries=[];referenced_mantles=set()
    for node in nodes:
        if node['classname']!=VOLUME:continue
        i=node['index'];j=node['partner_index'];m=node['mantle_index']
        require(j<count and nodes[j]['classname']==VOLUME and nodes[j]['partner_index']==i and j!=i,'Partner relationship is not reciprocal between volumes')
        require(nodes[j]['mantle_index']==m,'Partners disagree about mantle index')
        require(m==NULL_INDEX or m<count and nodes[m]['classname']==MANTLE,'Invalid mantle reference')
        text_target=node['source_properties'].get('target')
        if text_target:
            expected=m if m!=NULL_INDEX else j
            if text_target in named:
                require(expected in named[text_target],'Compiled pair disagrees with entity target')
                text_checks.append(i)
            else:
                recoveries.append(dict(source_node=i,source_entity_index=node['source_entity_index'],
                                       missing_text_target=text_target,compiled_partner_node=j,
                                       compiled_partner_entity=nodes[j]['source_entity_index']))
        if i>j:continue
        if m!=NULL_INDEX:
            require(m not in referenced_mantles,'Mantle shared by multiple pairs')
            referenced_mantles.add(m)
            target=nodes[m]['source_properties'].get('target')
            require(target in named and any(index in (i,j) for index in named[target]),'Mantle text target is outside its compiled volume pair')
        directions=[]
        for start,end in ((i,j),(j,i)):
            ignored=nodes[start]['movement_ignore_names']
            directions.append(dict(start_node=start,end_node=end,
                movement_ignore_names=ignored,movement_ignore_mask=nodes[start]['movement_ignore_mask'],
                zombie_excluded_by_source_ignore='zombie' in ignored,
                interpretation='Start-volume ignore properties; not proof of complete runtime edge eligibility'))
        pairs.append(dict(index=len(pairs),volume_nodes=[i,j],source_entities=[nodes[i]['source_entity_index'],nodes[j]['source_entity_index']],
                          mantle_node=None if m==NULL_INDEX else m,directions=directions))
    require(referenced_mantles=={n['index'] for n in nodes if n['classname']==MANTLE},'Unassociated mantle nodes')
    return dict(schema='cw-navigation-graph-evidence-v1',map=entity_document['map'],map_hash=maphash,
                summary=dict(nodes=count,volume_pairs=len(pairs),pairs_with_mantles=len(referenced_mantles),
                    edge_arrays=len(arrays),edge_points=sum(len(n['edge_points']) for n in nodes),
                    matching_volume_text_targets=len(text_checks),recovered_missing_text_targets=len(recoveries),
                    pairs_by_directions_not_excluding_zombie=dict(Counter(sum(not d['zombie_excluded_by_source_ignore'] for d in p['directions']) for p in pairs))),
                decoded_fields=dict(partner_index=84,mantle_index=88,cost_modifier=92,movement_ignore_mask=68,
                    independently_identified_ignore_bits=KNOWN_IGNORE_BITS),
                source=dict(capture_directory=str(root.resolve()),capture_report_sha256=hashlib.sha256((root/'capture.json').read_bytes()).hexdigest()),
                nodes=nodes,volume_pairs=pairs,recovered_targets=recoveries,
                limitations=['Verified against this Silver capture; additional maps/builds remain untested.',
                    'Only four individual movement bits are independently identified by sparse named patterns; the remaining bit meanings are not inferred from list order.',
                    'Pair indices and sampled edge geometry do not decode the complete navigation mesh or actor traversal eligibility.',
                    'BO3 conversion must preserve directed restrictions and validate animation clearance; materials alone cannot do this.'])


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--capture',required=True,type=Path)
    p.add_argument('--entities',required=True,type=Path)
    p.add_argument('--output',required=True,type=Path)
    a=p.parse_args()
    report=decode(a.capture,json.loads(a.entities.read_text()))
    report['source']['entity_json']=str(a.entities.resolve())
    report['source']['entity_json_sha256']=hashlib.sha256(a.entities.read_bytes()).hexdigest()
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
    print(json.dumps(report['summary']))
