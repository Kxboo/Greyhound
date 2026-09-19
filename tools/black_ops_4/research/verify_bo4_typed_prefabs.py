"""Read generated BO3 files independently of writer buffers and audit type choices."""

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
from pathlib import Path
import re

CLIPS = {'missileClip','bulletClip','playerClip','aiClip','vehicleClip','itemClip',
         'canShootClip','aiSightClip','utilityClip','playerVehicleClip'}
NATIVE = {'weaponClip': {'bulletClip','missileClip'}, 'ai_nosight': {'aiSightClip'}}


def verify(root, reference):
    materials={m['name']:m['properties'] for m in json.loads(reference.read_text())['materials']}
    report={}
    for folder, metadata in [('world','collision_metadata.json'),('model_physics','model_physics_metadata.json')]:
        data=json.loads((root/folder/metadata).read_text())
        rows={r['map_brush_index']:r for r in data['rows']}
        if len(rows)!=len(data['rows']):raise ValueError('Duplicate output brush identity')
        seen=set();counts=Counter();roles=Counter()
        for filename,record in data['map_files'].items():
            path=root/folder/filename
            if hashlib.sha256(path.read_bytes()).hexdigest()!=record['sha256']:raise ValueError('Prefab hash changed')
            blocks=re.findall(r'// brush (\d+)\s*\{(.*?)\n\}',path.read_text(),re.S)
            if len(blocks)!=record['brushes']:raise ValueError('Prefab brush count differs')
            for index,block in blocks:
                index=int(index)
                if index in seen:raise ValueError('Duplicate brush across prefabs')
                seen.add(index);row=rows[index];choice=row['type_assignment']
                if len(choice['collision_components'])>1:raise ValueError('Multiple collision components')
                planes=re.findall(r'^\( .* \) (\S+) 64 64 ',block,re.M)
                if len(planes)!=row.get('face_count',row.get('faces')) or set(planes)!={row['material']}:
                    raise ValueError('Face count or uniform tool differs')
                target_surface=materials.get(row['material'],{}).get('surfaceType')
                if target_surface!=choice['target_surface_type']:
                    raise ValueError('Emitted surface type differs from type report')
                if choice.get('surface_mapping_status')=='MATCHED' and target_surface!=choice['preferred_surface_type']:
                    raise ValueError('Claimed surface match is false')
                native=re.findall(r'^contents ([^;]+);',block,re.M)
                if len(native)>1:raise ValueError('Duplicate contents statement')
                native=native[0].split() if native else []
                if native!=choice['brush_contents']:raise ValueError('Native brush flags differ')
                actual={n for n in CLIPS if materials.get(row['material'],{}).get(n)=='1'}
                for flag in native:actual |= NATIVE[flag]
                wanted=set(choice['contents_names']) & CLIPS
                if sorted(actual-wanted)!=choice['added_collision_properties'] or sorted(wanted-actual)!=choice['omitted_collision_properties']:
                    raise ValueError('Emitted tool behavior differs from type report')
                counts['brushes']+=1
                counts['with_added_collision']+=bool(actual-wanted)
                counts['with_omitted_collision']+=bool(wanted-actual)
                counts['unresolved_surface_type_instances']+=bool(choice['unresolved_surface_type_codes'])
                if choice['role']=='clips' and choice.get('preferred_surface_type'):
                    counts['clip_instances_with_named_surface']+=1
                    counts['clip_instances_retaining_surface']+=target_surface==choice['preferred_surface_type']
                roles[choice['role']]+=1
        if seen!=set(rows):raise ValueError('Missing output brush')
        identities=[(r.get('entity_index'),r['source_brush_index']) if folder=='world'
                    else (r['instance_index'],r['entry_index']) for r in rows.values()]
        if len(set(identities))!=len(identities) or len(rows)!=data['summary']['source_brush_instances']:
            raise ValueError('Source-instance accounting is not one-to-one')
        report[folder]=dict(counts,prefabs=len(data['map_files']),roles=dict(roles),one_to_one_source_instances=True)
    report.update(compiled=False,scope='File integrity, source accounting and named properties; not BO3 gameplay validation')
    (root/'verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root',type=Path);parser.add_argument('reference',type=Path)
    args=parser.parse_args();verify(args.root,args.reference)
