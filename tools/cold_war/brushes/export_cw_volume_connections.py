"""Convert checked CW volume pairs into directional BO3 stock navigation links.

Only actor types named by both games are mapped. Other source types are retained
for review, and target-only types are explicitly excluded. Width, placement and
animation choices are conversion policies requiring map/gameplay validation.
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
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import sys

from export_cw_bo3_navigation import select_motion
from export_cw_bo3_player_volumes import quoted
from audit_cw_bo3_brush_types import entities as parse_map


def edge_center(node):
    points=node['edge_points']
    if len(points)<2:raise ValueError('Insufficient sampled edge points')
    origin=points[0];last=points[-1]
    delta=[last[i]-origin[i] for i in range(2)]
    width=math.hypot(*delta)
    if width<=0:raise ValueError('Degenerate sampled edge')
    axis=[v/width for v in delta]
    distances=[sum((p[i]-origin[i])*axis[i] for i in range(2)) for p in points]
    if any(b<=a for a,b in zip(distances,distances[1:])):raise ValueError('Nonmonotonic edge samples')
    mid=width/2
    for i,(a,b) in enumerate(zip(distances,distances[1:])):
        if a<=mid<=b:
            t=(mid-a)/(b-a)
            center=[points[i][k]+t*(points[i+1][k]-points[i][k]) for k in range(3)]
            return center,width,dict(segment=[i,i+1],fraction=t)
    raise ValueError('Edge midpoint is outside sampled range')


def build(graph,reference):
    if graph.get('schema')!='cw-navigation-graph-evidence-v1':raise ValueError('Use a checked navigation graph')
    evidence=reference['navigation_reference']
    if not evidence.get('one_way_empty_end_animscript_reference'):raise ValueError('Missing BO3 one-way authoring evidence')
    allowed=reference['entity_reference']['classes']['node_negotiation_begin']['movementtype_ignore']['flags'].split(',')
    target_types=set(allowed)
    # This is an observed full named source group, not guessed per-bit ordering.
    volumes=[n for n in graph['nodes'] if n['classname']=='node_negotiation_volume']
    source_groups=[set(n['movement_ignore_names']) for n in volumes]
    complete_groups=[set(n['movement_ignore_names']) for n in volumes
                     if len(set(n['movement_ignore_names']))>=16 and
                     int(n['movement_ignore_mask'],16)==(1<<len(set(n['movement_ignore_names'])))-1]
    if not complete_groups:raise ValueError('No complete low-bit named ignore group establishes the source vocabulary')
    source_types=max(complete_groups,key=len)
    if any(not g<=source_types for g in source_groups):raise ValueError('Observed restrictions extend beyond the established source vocabulary')
    common=source_types&target_types
    if not common:raise ValueError('No common named actor vocabulary')
    nodes=graph['nodes'];emitted=[];skipped=[];pair_rows=[]
    for pair in graph['volume_pairs']:
        record=dict(source_pair=pair['index'],volume_nodes=pair['volume_nodes'],mantle_node=pair['mantle_node'],directions=[])
        for direction in pair['directions']:
            src=nodes[direction['start_node']];dst=nodes[direction['end_node']]
            source_ignored=set(direction['movement_ignore_names'])
            permitted=common-source_ignored
            key=f'cw_{graph["map_hash"][-8:].lower()}_p{pair["index"]:03d}_n{src["index"]}'
            row=dict(source_start_node=src['index'],source_end_node=dst['index'],
                     source_ignore=sorted(source_ignored),mapped_permitted_actor_types=sorted(permitted),
                     source_only_actor_types=sorted(source_types-target_types),
                     target_only_actor_types_excluded=sorted(target_types-common))
            record['directions'].append(row)
            if not permitted:
                row['status']='no_mapped_actor_type_permitted'
                skipped.append(row)
                continue
            start,width_start,interpolation_start=edge_center(src)
            end,width_end,interpolation_end=edge_center(dst)
            # The installed BO3 traversal examples author nodes 16 units above
            # the floor, and cod2map drops them onto its generated navmesh.
            start_author=[start[0],start[1],start[2]+16]
            end_author=[end[0],end[1],end[2]+16]
            vector=[end[i]-start[i] for i in range(2)]
            yaw=src['compiled_yaw']
            if math.cos(math.radians(yaw))*vector[0]+math.sin(math.radians(yaw))*vector[1]<0:yaw+=180
            end_yaw=dst['compiled_yaw']
            if math.cos(math.radians(end_yaw))*vector[0]+math.sin(math.radians(end_yaw))*vector[1]>0:end_yaw+=180
            origin=lambda p:' '.join(format(v,'.9g') for v in p)
            begin=dict(classname='node_negotiation_begin',origin=origin(start_author),angles=f'0 {yaw%360:.9g} 0',
                       targetname=key+'_begin',target=key+'_end',width=format(width_start,'.9g'),
                       movementtype_ignore=','.join(v for v in allowed if v not in permitted),
                       cost_modifier=format(src['cost_modifier'],'.9g'),PROCEDURAL='0',spawnflags='0')
            finish=dict(classname='node_negotiation_end',origin=origin(end_author),angles=f'0 {end_yaw%360:.9g} 0',
                        targetname=key+'_end',width=format(width_end,'.9g'),animscript='',PROCEDURAL='0',spawnflags='0')
            motion=select_motion(begin,finish,evidence['stock_traversals'])
            mid=pair['mantle_node']
            if mid is not None and abs(src['position'][2]-dst['position'][2])<=8:
                mantle=nodes[mid];crest,_,_=edge_center(mantle)
                height=crest[2]-start[2]
                choices=[a for a in evidence['stock_traversals'] if a['family']=='mantle_over']
                if not choices:raise ValueError('No stock mantle-over animation evidence')
                choice=min(choices,key=lambda a:(abs(a['nominal_distance']-height),a['nominal_distance']))
                motion=dict(animscript=choice['animscript'],compared_distance=height,
                            stock_nominal_distance=choice['nominal_distance'],nominal_difference=choice['nominal_distance']-height,
                            selection='paired_level_origins_and_captured_mantle_crest',
                            animation_evidence=choice['rows'],exact_motion_equivalence=False)
            begin['animscript']=motion['animscript']
            row.update(status='stock_directional_link',begin_properties=begin,end_properties=finish,motion=motion,
                       source_edge_centers=[start,end],authoring_vertical_offset=16,
                       interpolation=[interpolation_start,interpolation_end],widths=[width_start,width_end],
                       source_start_entity=src['source_entity_index'],source_end_entity=dst['source_entity_index'])
            emitted.append(row)
        pair_rows.append(record)
    return dict(schema='cw-bo3-volume-connections-v1',map=graph['map'],map_hash=graph['map_hash'],pairs=pair_rows,
        emitted=emitted,skipped=skipped,actor_mapping=dict(common_types=sorted(common),unmapped_source_types=sorted(source_types-target_types),
            excluded_target_only_types=sorted(target_types-common)),
        summary=dict(source_pairs=len(pair_rows),directional_connections=len(emitted),point_entities=2*len(emitted),
                     directions_with_no_mapped_actor=len(skipped),animation_counts=dict(Counter(r['motion']['animscript'] for r in emitted))),
        compiled=False,gameplay_validated=False,authoring_evidence=evidence['one_way_empty_end_animscript_reference'],
        limitations=['Mappings cover only the common named actor vocabulary; unknown source species have no automatic BO3 replacement.',
                     'Separate one-way pairs use an empty end animation as in the installed BO3 one-way example.',
                     'Width spans sampled edges; centers interpolate captured samples with a 16-unit authoring lift. Actual-map navmesh projection remains unverified.',
                     'Nearest stock jump/mantle animation is an approximation; obstacle clearance and playback need in-game testing.'])


def export(graph,reference,output,name,placement_only=False):
    report=build(graph,reference);output=Path(output);output.mkdir(parents=True,exist_ok=True)
    if placement_only:
        for row in report['emitted']:
            row['begin_properties']['animscript']=''
            row['end_properties']['animscript']=''
            row['status']='directional_placement_reference'
        report['animation_setup']='user_supplied; motion candidates are reference only'
        report['limitations']=[
            'Animation fields are empty for user setup; motion suggestions in JSON are unassigned approximations.',
            'Mappings cover only the common named actor vocabulary; source-only species remain in the report.',
            'Centers interpolate captured edges with a 16-unit authoring lift; these derived positions are distinct from original entity origins.',
            'Source direction restrictions are retained in JSON and mapped to begin-node properties; functional traversal requires manual setup.']
    path=output/(name+('_volume_connection_placements.map' if placement_only else '_volume_connections.map'))
    lines=['iwmap 4','"000_Global" flags active','"000_Global/CW_Volume_Connections" flags','// entity 0','{','"classname" "worldspawn"','}']
    props=[]
    for row in report['emitted']:
        for side in ('begin_properties','end_properties'):
            p=row[side];props.append(p)
            lines += [f'// entity {len(props)}','{','layer "000_Global/CW_Volume_Connections"']
            lines += [quoted(k)+' '+quoted(v) for k,v in p.items()]
            lines.append('}')
    path.write_text('\n'.join(lines)+'\n',encoding='utf-8')
    parsed=parse_map(path)
    if len(parsed)!=len(props)+1 or any(a['properties']!=b for a,b in zip(parsed[1:],props)):raise ValueError('Map entity round-trip differs')
    names=[p['targetname'] for p in props]
    if len(names)!=len(set(names)) or any(p['target'] not in names for p in props if 'target' in p):raise ValueError('Invalid exported link names')
    report['file']=path.name;report['sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--graph',required=True,type=Path);p.add_argument('--reference',required=True,type=Path)
    p.add_argument('--output',required=True,type=Path);p.add_argument('--name',required=True)
    p.add_argument('--placement-only',action='store_true',help='Leave animation fields empty for manual setup')
    a=p.parse_args()
    if Path(a.name).name!=a.name or any(c in a.name for c in '/\\:'):p.error('Name must be a filename stem')
    result=export(json.loads(a.graph.read_text()),json.loads(a.reference.read_text()),a.output,a.name,a.placement_only)
    result['sources']=[dict(file=str(f.resolve()),sha256=hashlib.sha256(f.read_bytes()).hexdigest()) for f in (a.graph,a.reference)]
    (a.output/'volume-connections-report.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result['summary']))
