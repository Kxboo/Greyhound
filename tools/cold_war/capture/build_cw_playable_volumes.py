"""Author BO3 playable coverage from Silver's captured named location hulls.

Room envelopes are captured geometry. Subdivision between multiple CW node
regions in one named location is explicitly authored, not a decoded region mesh.
"""

# Support direct execution and the isolated packaged Python runtime.
import sys as _tool_sys
from pathlib import Path as _ToolPath
TOOLS_ROOT = next(p for p in _ToolPath(__file__).resolve().parents if (p / "tool_bootstrap.py").is_file())
_tool_sys.path.insert(0, str(TOOLS_ROOT))
import tool_bootstrap as _tool_bootstrap
_tool_bootstrap.activate(__file__)
REPO_ROOT = TOOLS_ROOT.parent
from pathlib import Path
import json,hashlib,sys,re,shutil
from collections import Counter
from datetime import datetime
import numpy as np
from scipy.optimize import linprog
from scipy.spatial import HalfspaceIntersection,ConvexHull
from build_cw_door_model_prefab import parse,point_entity
from build_cw_zone_progression import Prefab

BO3=Path(r'C:\Program Files (x86)\Steam\steamapps\common\Call of Duty Black Ops III')
ROOT=Path(r'C:\SuperTerrain\research\cw-clip')
OUT=ROOT/'playable-volumes-v3'
SUPPLIED=BO3/'map_source/_prefabs/zm/black_ops_5/zm_silver/other/zm_silver_volumes.map'
GROUPS={
    'zone_proto_start':['zone_proto_start','zone_proto_start2'],
    'zone_proto_interior_lower':['zone_proto_interior_lower','zone_wonder_weapon_room'],
    'zone_proto_upstairs_2':['zone_proto_upstairs_2'],
    'zone_proto_roof':['zone_proto_roof_center','zone_proto_roof_plane'],
    'zone_proto_interior_cave':['zone_proto_interior_cave'],
    'zone_proto_upstairs':['zone_proto_upstairs'],
    'zone_proto_plane_exterior':['zone_proto_plane_exterior','zone_proto_plane_exterior2'],
    'zone_proto_exterior_rear':['zone_proto_exterior_rear','zone_proto_exterior_rear2'],
    'zone_tunnel_interior':['zone_tunnel_interior'],
    'zone_power_room':['zone_power_room','zone_power_room_outside','zone_power_trans_north','zone_power_trans_south'],
    'zone_trans_north':['zone_trans_north','zone_trans_north_pap_room'],
    'zone_trans_south':['zone_trans_south','zone_trans_south_pap_room','zone_trans_south_tunnel'],
    'zone_particle':['zone_center_lower','zone_center_upper','zone_center_upper_north','zone_center_upper_west'],
    'zone_power_tunnel':['zone_power_tunnel'],
}

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def source_planes(row,hull):
    eq=np.array(hull['source_equations_local'],float)[hull['active_source_planes']]
    eq[:,3]+=eq[:,:3]@np.array(row['source_origin'])
    return eq/np.linalg.norm(eq[:,:3],axis=1)[:,None]

def bounded_mesh(eq):
    eq=eq/np.linalg.norm(eq[:,:3],axis=1)[:,None]
    lp=linprog([0,0,0,-1],A_ub=np.column_stack((eq[:,:3],np.ones(len(eq)))),b_ub=eq[:,3],
               bounds=[(None,None)]*3+[(0,None)],method='highs')
    if not lp.success or lp.x[3]<.025:return None
    vertices=HalfspaceIntersection(np.column_stack((eq[:,:3],-eq[:,3])),lp.x[:3]).intersections
    active=np.array([i for i,p in enumerate(eq) if np.count_nonzero(np.abs(vertices@p[:3]-p[3])<1e-5)>=3])
    eq=eq[active]
    assert len(eq)<=64 and np.max(vertices@eq[:,:3].T-eq[:,3])<1e-5
    return eq,vertices,float(ConvexHull(vertices).volume)

def main(install=False):
    OUT.mkdir(exist_ok=True)
    source=json.loads((ROOT/'stock-first-review-20260915/review-prefabs/metadata/triggers.json').read_text())
    assert sha(SUPPLIED)==source['map_files']['volumes']['sha256'],'Supplied geometry changed; re-read its planes'
    mapping=json.loads((ROOT/'zone-progression-v1/zone-progression-mapping.json').read_text())
    entities={r['index']:r for r in json.loads((ROOT/'stock-first-review-20260915/entitylist/entities.decoded.json').read_text())['entities']}
    zones={z['name']:z for z in mapping['zones']}
    seeds={z:[np.array(entities[i]['origin']) for i in row['source_region_entity_indices']] for z,row in zones.items()}
    assert set(zones)=={z for group in GROUPS.values() for z in group}
    source_rows={r['source_entity_index']:r for r in source['entities']}
    locations=[r for r in source_rows.values() if r['source_properties'].get('targetname')=='location_zone']
    assert len(locations)==29
    prefab=Prefab();records=[]
    def add(zone,eq,vertices,layer,provenance):
        props=dict(classname='info_volume',targetname=zone,target=zones[zone]['spawn_target'],script_noteworthy='player_volume')
        num=prefab.add(props,'000_Global/'+layer,[prefab.brush(eq,vertices.mean(axis=0),'volume')],provenance['kind'])
        records.append(dict(zone=zone,prefab_entity=num,equations=eq.tolist(),mins=vertices.min(axis=0).tolist(),
                            maxs=vertices.max(axis=0).tolist(),**provenance))
    # Preserve every previously captured player hull; remove all reference cubes.
    for zone,row in zones.items():
        for index in row['source_trigger_indices']:
            source_row=source_rows[index]
            for hi,hull in enumerate(source_row['hulls']):
                add(zone,source_planes(source_row,hull),np.array(hull['vertices_world']),
                    'Captured_Player_Hulls/'+zone,dict(kind='captured_player_hull',source_trigger=index,source_hull=hi))
    # Subdivide the genuine room envelopes by captured node positions. Vertical
    # distance has four times the weight to distinguish stacked bunker floors.
    # Adjacent cells overlap by eight units to tolerate player/brush seams.
    metric=np.array([1.,1.,16.])
    for row in locations:
        label=row['source_properties']['script_location']
        sites=[(z,p) for z in GROUPS[label] for p in seeds[z]]
        for hi,hull in enumerate(row['hulls']):
            base=source_planes(row,hull)
            for site_index,(zone,p) in enumerate(sites):
                cuts=[]
                for j,(_,q) in enumerate(sites):
                    if j==site_index:continue
                    normal=2*metric*(q-p);length=np.linalg.norm(normal)
                    distance=float((q*metric)@q-(p*metric)@p)
                    cuts.append([*(normal/length),distance/length+8.])
                eq=np.vstack((base,cuts)) if cuts else base
                result=bounded_mesh(eq)
                if result is None:continue
                eq,vertices,volume=result
                add(zone,eq,vertices,'Location_Coverage/'+zone,dict(kind='captured_location_authored_region_subdivision',
                    source_trigger=row['source_entity_index'],source_hull=hi,source_location=label,
                    region_seed=p.tolist(),subdivision_metric=metric.tolist(),seam_overlap=8.,volume=volume))
    # Both connected zones cover each captured interaction hull. This avoids a
    # lethal sliver at the door approach while the destination zone is locked.
    for door in mapping['doors']:
        center=np.array(door['gate_center']);flag=door['bo3_properties']['script_flag']
        edges=[e for e in mapping['connections'] if e['flag']==flag]
        assert edges
        edge=min(edges,key=lambda e:sum(min(np.linalg.norm((p-center)*[1,1,4]) for p in seeds[e[k]]) for k in ('a','b')))
        r=source_rows[door['source_trigger_index']]
        for zone in (edge['a'],edge['b']):
            for hi,hull in enumerate(r['hulls']):
                add(zone,source_planes(r,hull),np.array(hull['vertices_world']),'Door_Thresholds/'+zone,
                    dict(kind='captured_door_approach',source_trigger=r['source_entity_index'],source_hull=hi,connection=edge))
    volume_rel='_prefabs/codex/cw_silver_player_volumes_v3.map'
    prefab.save(OUT/Path(volume_rel).name)

    # Deterministic coverage checks sample the source room hulls, not generated
    # cell centroids alone. Also verify every region and actual map spawn point.
    eqs=[(r['zone'],np.array(r['equations'])) for r in records]
    def hits(points,zone=None):
        found=np.zeros(len(points),bool)
        for name,eq in eqs:
            if zone is None or name==zone:found |= np.all(points@eq[:,:3].T<=eq[:,3]+.02,axis=1)
        return found
    region_checks=[]
    for zone,points in seeds.items():
        for point in points:
            samples=np.array([point,point+[0,0,40],point+[0,0,64]])
            assert np.all(hits(samples,zone)),('Uncovered region',zone,samples)
            region_checks.append(dict(zone=zone,point=point.tolist(),checked_height_offsets=[0,40,64]))
    rng=np.random.default_rng(20260915);coverage=[]
    for row in locations:
        for hi,hull in enumerate(row['hulls']):
            vertices=np.array(hull['vertices_world']);eq=source_planes(row,hull)
            samples=rng.uniform(vertices.min(axis=0),vertices.max(axis=0),size=(4000,3))
            samples=samples[np.all(samples@eq[:,:3].T<=eq[:,3],axis=1)]
            assert len(samples)>100
            assert np.all(hits(samples)),('Coverage hole',row['source_entity_index'])
            coverage.append(dict(source_trigger=row['source_entity_index'],hull=hi,samples=len(samples),uncovered=0))

    old_game=BO3/'map_source/_prefabs/codex/cw_silver_doors_zones_v2.map'
    old_model=BO3/'map_source/_prefabs/codex/cw_silver_models_doors_v2.map'
    game_bytes=old_game.read_bytes();game=game_bytes.decode()
    for row in reversed(parse(game)):
        if row['props'].get('classname')=='info_volume':game=game[:row['start']]+game[row['end']:]
    # Remove obsolete layer declarations as well as their reference geometry.
    game='\n'.join(line for line in game.splitlines() if not (line.startswith('"') and ' flags' in line and
                  ('/Zones_Captured/' in line or '/REVIEW_Zone_Extents/' in line)))+'\n'
    game+=point_entity(dict(classname='misc_prefab',model=volume_rel,origin='0 0 0'),'Continuous authored BO3 player coverage')
    game+=point_entity(dict(classname='misc_prefab',model='_prefabs/codex/cw_silver_zone_progression_v1_spawn_locations.map',origin='0 0 0'),'54 captured basic zombie spawn locations')
    game_rel='_prefabs/codex/cw_silver_doors_zones_v3.map'
    model_rel='_prefabs/codex/cw_silver_models_doors_v3.map'
    model_bytes=old_model.read_bytes()
    model=model_bytes.decode().replace('_prefabs/codex/cw_silver_doors_zones_v2.map',game_rel)
    assert model!=model_bytes.decode()

    map_path=BO3/'map_source/zm/zm_silver.map';map_bytes=map_path.read_bytes();maptext=map_bytes.decode()
    assert maptext.count('_prefabs/codex/cw_silver_models_doors_v2.map')==1
    spawn_checks=[]
    for row in parse(maptext):
        p=row['props']
        if p.get('classname')=='info_player_start' or p.get('targetname')=='initial_spawn_points' or p.get('script_noteworthy')=='start_room':
            world=np.array(list(map(float,p['origin'].split())));cw=world-[-812,57,-36]
            assert np.all(hits(np.array([cw,cw+[0,0,40],cw+[0,0,64]]),'zone_proto_start')),('Spawn outside enabled start zone',p)
            spawn_checks.append(p)
    updated=maptext.replace('_prefabs/codex/cw_silver_models_doors_v2.map',model_rel)
    updated=updated.replace('"targetname" "start_zone"','"targetname" "zone_proto_start"')
    updated=updated.replace('"start_zone_spawners"','"zone_proto_start_spawns"')
    updated=updated.replace('"script_noteworthy" "start_room"','"script_noteworthy" "zone_proto_start"')
    script_path=BO3/'usermaps/zm_silver/scripts/zm/zm_silver.gsc';script_bytes=script_path.read_bytes();script=script_bytes.decode()
    assert 'zm_usermap::main();' not in script
    needle='    assert( !level flag::get( "zones_initialized" )'
    assert script.count(needle)==1
    script=script.replace(needle,'    level._zombie_custom_add_weapons = &custom_add_weapons;\n    zm_usermap::main();\n'+needle)

    files={BO3/'map_source'/volume_rel:(OUT/Path(volume_rel).name).read_bytes(),
           BO3/'map_source'/game_rel:game.encode(),BO3/'map_source'/model_rel:model.encode(),
           map_path:updated.encode(),script_path:script.encode()}
    for path,data in files.items():(OUT/path.name).write_bytes(data)
    report=dict(source_volume_prefab=str(SUPPLIED),source_sha256=sha(SUPPLIED),
        policy='Captured player hulls plus complete named-location hull coverage, authored per-region subdivisions, and captured door approaches. No reference cubes or blanket safety zone.',
        records=records,region_checks=region_checks,room_coverage_checks=coverage,spawn_checks=spawn_checks,
        summary=dict(zones=len(zones),player_volume_entities=len(records),kinds=dict(Counter(r['kind'] for r in records)),
                     named_location_hulls=len(coverage),coverage_samples=sum(r['samples'] for r in coverage),
                     uncovered_samples=0,placeholder_boxes=0,region_nodes_verified=len(region_checks),
                     map_spawn_points_verified=len(spawn_checks),added_basic_spawn_locations=54),
        limitations=['Subdivisions are authored from captured region nodes, not decoded native CW region boundaries.',
                     'Coverage is verified against the supplied named location hulls and sampled points; in-game player collision/navigation still requires testing.',
                     'Existing explosive door handling and the four external quest flags are unchanged.'])
    if install:
        assert map_path.read_bytes()==map_bytes and script_path.read_bytes()==script_bytes
        backup=OUT/('backup-'+datetime.now().strftime('%Y%m%d-%H%M%S'));backup.mkdir()
        for p in [map_path,script_path,old_game,old_model]:shutil.copy2(p,backup/p.name)
        for path,data in files.items():
            if path not in (map_path,script_path):assert not path.exists(),path
            path.write_bytes(data)
        report['backup_directory']=str(backup)
        report['installed_files']={str(p):hashlib.sha256(b).hexdigest() for p,b in files.items()}
    (OUT/'coverage-mapping.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report['summary']))

if __name__=='__main__':main('--install' in sys.argv)
