"""Export centered navigation tool bounds from a checked CW GAME_MAP graph.

Tool geometry is separate from navigation edges and actor restrictions. The
mantle material choice remains a documented similar-stock approximation.
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
import numpy as np

from cw_canonical_map_planes import CanonicalPlaneWriter
from build_cw_bo3_brush_prototype import read_map_planes
from export_cw_bo3_player_volumes import quoted
from audit_cw_bo3_brush_types import entities as parse_map


def export(graph, reference, destination, name):
    if graph.get('schema')!='cw-navigation-graph-evidence-v1':raise ValueError('Use a verified navigation graph')
    materials={m['name']:m for m in reference['materials']}
    for material,climb in (('traverse','<none>'),('mantle_on','mantleOn'),('mantle_over','mantleOver')):
        p=materials[material]['properties']
        if p.get('surfaceClimbType')!=climb or p.get('noDraw')!='1' or p.get('nonSolid')!='1':
            raise ValueError('Stock navigation tool properties changed')
    by_mantle={p['mantle_node']:p for p in graph['volume_pairs'] if p['mantle_node'] is not None}
    writer=CanonicalPlaneWriter();blocks=[];records=[];layers={'000_Global','000_Global/CW_Navigation_Tools'}
    nodes=graph['nodes']
    for node in nodes:
        if node['classname'] not in ('node_negotiation_volume','node_negotiation_mantle'):continue
        evidence=node['geometry_validation']
        if not evidence:raise ValueError('Missing geometry validation')
        # Compiled edge samples and half-dimensions were checked in the GAME_MAP
        # yaw-only frame, including source entities with pitch/roll. Preserve
        # those authored angles in metadata, not in this compiled-bound frame.
        yaw=math.radians(node['compiled_yaw']);co,si=math.cos(yaw),math.sin(yaw)
        axes=np.array([[co,si,0],[-si,co,0],[0,0,1]])
        center=np.array(node['position']);half=np.array(evidence['source_local_half_dimensions'])
        if not np.isfinite(half).all() or np.min(half)<=0:raise ValueError('Invalid dimensions')
        # GAME_MAP provides half-dimensions about this center. No vertical
        # half-height is added: that moved earlier boxes above their edge points.
        equations=np.array([[*(sign*axis),sign*axis@center+h] for axis,h in zip(axes,half) for sign in (1,-1)])
        points=np.array(node['edge_points'])
        source_outside=float(np.max(points@equations[:,:3].T-equations[:,3]))
        if source_outside>.001:raise ValueError('Captured edge points escape the proposed centered bound')
        material='traverse';choice=dict(status='stock_traverse_tool_geometry_only')
        if node['classname']=='node_negotiation_mantle':
            pair=by_mantle[node['index']];volumes=[nodes[i] for i in pair['volume_nodes']]
            drops=[center[2]-v['position'][2] for v in volumes]
            material='mantle_over' if abs(drops[0]-drops[1])<=8 else 'mantle_on'
            choice=dict(status='paired_height_stock_approximation',drops_to_volume_origins=drops,
                        decoded_climb_enum=False,source_pair=pair['index'])
        layer='000_Global/CW_Navigation_Tools/'+material;layers.add(layer)
        lines=writer.lines(equations,center,material)
        parsed=np.array(read_map_planes('\n'.join(lines)))
        drift=float(np.max(np.abs(parsed-equations)))
        outside=float(np.max(points@parsed[:,:3].T-parsed[:,3]))
        if drift>1e-6 or outside>.001:raise ValueError('Serialized navigation bound differs')
        blocks.extend([f'// brush {len(records)}: source entity {node["source_entity_index"]}', '{','layer '+quoted(layer),*lines,'}'])
        records.append(dict(source_node=node['index'],source_entity_index=node['source_entity_index'],
            classname=node['classname'],material=material,material_choice=choice,center=center.tolist(),half_dimensions=half.tolist(),
            bounds_orientation=dict(compiled_yaw=node['compiled_yaw'],source_entity_angles=node['angles'],
                                    basis='GAME_MAP yaw-only frame verified against sampled edges'),
            source_points=len(points),max_source_point_outside=source_outside,max_serialized_point_outside=outside,
            serialized_plane_error=drift,source_properties=node['source_properties'],
            movement_restrictions_implemented_by_brush=False,source_link_implemented_by_brush=False))
    destination=Path(destination);destination.mkdir(parents=True,exist_ok=True)
    path=destination/(name+'_navigation_tools.map')
    lines=['iwmap 4']+[quoted(layer)+' flags'+(' active' if layer=='000_Global' else '') for layer in sorted(layers)]
    lines+=['// entity 0','{','"classname" "worldspawn"',*blocks,'}']
    path.write_text('\n'.join(lines)+'\n',encoding='utf-8')
    parsed=parse_map(path)
    expected=Counter(r['material'] for r in records for _ in range(6))
    if len(parsed)!=1 or parsed[0]['brush_blocks']!=len(records) or parsed[0]['face_material_counts']!=dict(expected):
        raise ValueError('Navigation brush count/material round-trip failed')
    return dict(schema='cw-bo3-centered-navigation-tools-v1',map=graph['map'],map_hash=graph['map_hash'],
        summary=dict(brushes=len(records),materials=dict(Counter(r['material'] for r in records)),
                     verified_edge_points=sum(r['source_points'] for r in records)),
        file=path.name,sha256=hashlib.sha256(path.read_bytes()).hexdigest(),records=records,
        compiled=False,gameplay_validated=False,
        limitations=['Centered bounds are corroborated by captured half-dimensions and all edge points on this map.',
                     'Mantle-on/over selection remains a paired-height approximation, not a decoded source enum.',
                     'Tool brushes do not implement the paired navigation links or movement restrictions.',
                     'Use this instead of the old navigation tool brushes; it contains no endpoint entities.'])


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--graph',required=True,type=Path);p.add_argument('--reference',required=True,type=Path)
    p.add_argument('--output',required=True,type=Path);p.add_argument('--name',required=True)
    a=p.parse_args()
    if Path(a.name).name!=a.name or any(c in a.name for c in '/\\:'):p.error('Name must be a filename stem')
    report=export(json.loads(a.graph.read_text()),json.loads(a.reference.read_text()),a.output,a.name)
    report['sources']=[dict(file=str(path.resolve()),sha256=hashlib.sha256(path.read_bytes()).hexdigest()) for path in (a.graph,a.reference)]
    (a.output/'navigation-tools-report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report['summary']))
