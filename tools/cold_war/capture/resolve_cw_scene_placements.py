"""Resolve authored scene alignment markers, retaining object and shot identity."""

# Support direct execution and the isolated packaged Python runtime.
import sys as _tool_sys
from pathlib import Path as _ToolPath
TOOLS_ROOT = next(p for p in _ToolPath(__file__).resolve().parents if (p / "tool_bootstrap.py").is_file())
_tool_sys.path.insert(0, str(TOOLS_ROOT))
import tool_bootstrap as _tool_bootstrap
_tool_bootstrap.activate(__file__)
REPO_ROOT = TOOLS_ROOT.parent
import argparse, collections, copy, json
from pathlib import Path
from cw_scene_controls import alignment_pose, root_transform
from enrich_cw_scene_bundle import SCRIPT_URL

def resolve(root):
    root=Path(root).resolve()
    entities={e['EntityId']:e for p in (root/'entities').glob('*/*.json') for e in json.loads(p.read_text())}
    targets=collections.defaultdict(list)
    for e in entities.values():
        for k,v in e['Properties'].items():
            if k.lower()=='targetname' and isinstance(v,str):targets[v].append(e)
    rows=json.loads((root/'animation/scene_placements.json').read_text())
    object_names=collections.defaultdict(set)
    for row in rows:object_names[row['SourceEntityId'],row['BundleName']].add(row['ObjectControls'].get('name'))
    objects={};statuses=collections.Counter()
    for i,row in enumerate(rows):
        scene,obj,shot=(copy.deepcopy(row[k]) for k in ('SceneControls','ObjectControls','ShotControls'))
        # Both client and server select shot, object, then scene alignment. The
        # server can suppress the shot override; retain unresolved disagreement.
        chosen=next(((level,node['aligntarget']) for level,node in (('shot',shot),('object',obj),('scene',scene))
                     if node.get('aligntarget') is not None),('authored_root',None))
        level,name=chosen;target=entities[row['SourceEntityId']];status='authored_scene_root'
        if name is not None:
            hits=targets.get(name,[])
            if name in object_names[row['SourceEntityId'],row['BundleName']]:status='requires_scene_object_alignment'
            elif len(hits)!=1:status='missing_or_ambiguous_alignment_marker'
            elif level=='shot' and shot.get('hash_ab59a015'):status='client_server_alignment_rules_differ'
            else:target=hits[0];status='unique_authored_alignment_marker'
        transform=root_transform(target)
        if status in ('authored_scene_root','unique_authored_alignment_marker'):
            for node in (scene,obj,shot):node.pop('aligntarget',None)
            pose=alignment_pose(transform,scene,obj,shot)
            if pose['RequiresRuntimeAlignmentTargetOrTag']:status='requires_bone_tag_pose'
            elif pose['RequiresCurrentObjectAngles']:status='requires_current_object_angles'
            elif pose['Position'] is None or pose['AnglesPitchYawRoll'] is None:status='invalid_authored_transform'
        else:pose={'Position':None,'AnglesPitchYawRoll':None}
        statuses[status]+=1
        resolved={'Status':status,'AlignmentSelection':level,'AlignmentTargetName':name,
            'AlignmentSourceEntityId':target['EntityId'] if status in ('authored_scene_root','unique_authored_alignment_marker') else None,
            'Position':pose['Position'],'AnglesPitchYawRoll':pose['AnglesPitchYawRoll'],
            'BO3':{'origin':pose['Position'],'angles':pose['AnglesPitchYawRoll'],
                'status':'animation alignment reference; model identity and animation root motion must be handled separately'},
            'Meaning':'authored animation alignment transform, before animated bone/root motion; not an observed runtime pose',
            'SourceLookupRule':SCRIPT_URL+'#L2419-L2428','SourceOffsetRule':SCRIPT_URL+'#L1908-L1980'}
        row['ResolvedAuthoredAlignment']=resolved
        key=(row['SourceEntityId'],row['BundleName'],row['ObjectIndex'])
        if key not in objects:
            objects[key]={'SourceEntityId':row['SourceEntityId'],'BundleName':row['BundleName'],
                'ObjectIndex':row['ObjectIndex'],'ObjectName':row['ObjectControls'].get('name'),
                'ObjectType':row['ObjectControls'].get('type'),'ModelReference':row['ObjectControls'].get('model'),
                'SourceEntityModelScale':row['RootTransform']['ModelScale'],
                'ScaleMeaning':'source entity scale retained; scene child inheritance not asserted',
                'SourceBundleFile':'animation/scene_bundle_data.json','Shots':[]}
        objects[key]['Shots'].append({'ShotIndex':row['ShotIndex'],'ShotName':row['ShotControls'].get('name'),
            'SourceScenePlacementIndex':i,'SourceScenePlacementFile':'animation/scene_placements.json',
            'Alignment':resolved,'AnimationReferences':row['AnimationEntries']})
    (root/'animation/scene_placements.json').write_text(json.dumps(rows,indent=2)+'\n')
    directory=root/'animation/scene_objects';directory.mkdir(exist_ok=True)
    for name in sorted({x['BundleName'] for x in objects.values()}):
        assert Path(name).name==name
        (directory/(name+'.json')).write_text(json.dumps([x for x in objects.values() if x['BundleName']==name],indent=2)+'\n')
    (root/'animation/object_placements.json').write_text(json.dumps(list(objects.values()),indent=2)+'\n')
    report={'bundles':len({x['BundleName'] for x in rows}),'source_entities':len({x['SourceEntityId'] for x in rows}),
        'scene_objects':len(objects),'object_shot_references':len(rows),'alignment_statuses':dict(statuses),
        'resolved_alignment_markers':len({x['ResolvedAuthoredAlignment']['AlignmentSourceEntityId'] for x in rows
            if x['ResolvedAuthoredAlignment']['Status']=='unique_authored_alignment_marker'})}
    (root/'metadata/scene_placement_resolution.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('root',type=Path);a=p.parse_args();resolve(a.root)
