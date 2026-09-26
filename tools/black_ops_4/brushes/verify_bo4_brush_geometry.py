"""Reopen published BO4 collision prefabs and independently check every brush row."""
from collections import defaultdict
import hashlib
import re
import numpy as np
from bo3_map_planes import read_map_planes
from assign_bo4_bo3_types import CLIP_NAMES


def verify(output, reports, reference):
    by_name={m['name']:m['properties'] for m in reference['materials']}
    files=defaultdict(list)
    for report in reports:
        if not report:continue
        for cert in report.get('partition_certificates',{}).values():
            if cert['partitioned'] and not all(cert[k] is True for k in
                ('internal_faces_cancel','external_triangles_unchanged','positive_exact_volumes')):
                raise ValueError('Uncertified brush partition')
        grouped=defaultdict(list)
        for row in report['rows']:
            files[row['prefab_file']].append(row)
            if 'type_assignment' in row:
                key=(row.get('source_brush_index'),row.get('entity_index'),row.get('instance_index'),row.get('entry_index'))
                grouped[key].append(row)
        for identity,rows in grouped.items():
            choice=rows[0]['type_assignment'];components=choice['collision_components']
            expected={(p,c) for p in range(rows[0]['partition_count']) for c in range(len(components))}
            actual=[(r['partition_index'],r['collision_component_index']) for r in rows]
            if len(actual)!=len(set(actual)) or set(actual)!=expected:
                raise ValueError('Partition/category Cartesian coverage changed')
            for piece in range(rows[0]['partition_count']):
                part=[r for r in rows if r['partition_index']==piece]
                if any(r['expected_planes']!=part[0]['expected_planes'] for r in part):
                    raise ValueError('Coincident category components changed geometry')
            properties=set()
            for component in components:
                props=by_name[component['material']]
                properties|={n for n in CLIP_NAMES if props.get(n)=='1'}
                if 'weaponClip' in component['brush_contents']:properties|={'bulletClip','missileClip'}
                if 'ai_nosight' in component['brush_contents']:properties.add('aiSightClip')
            source=set(choice['source_collision_properties'])
            if sorted(properties-source)!=choice['added_collision_properties'] or sorted(source-properties)!=choice['omitted_collision_properties']:
                raise ValueError('Stock category union differs from recorded source comparison')
            if (properties!=source) and any('/review/' not in '/'+r['prefab_file'] for r in rows):
                raise ValueError('Tool category fallback escaped review folder')
    count=0
    for relative,rows in files.items():
        path=output/relative;text=path.read_text()
        blocks=re.findall(r'// brush \d+\s*\{(.*?)\n\}',text,re.S)
        if len(blocks)!=len(rows):raise ValueError('Published brush count differs from metadata')
        for block,row in zip(blocks,rows):
            planes=np.asarray(read_map_planes(block));expected=np.asarray(row['expected_planes'])
            if planes.shape!=expected.shape or not 4<=len(planes)<=64 or not np.isfinite(planes).all() or np.max(abs(planes-expected))>1e-6:
                raise ValueError('Published planes differ from checked source partition')
            materials=re.findall(r'^\([^\n]+?\)\s+(\S+)\s+64 64 ',block,re.M)
            if len(materials)!=len(planes) or set(materials)!={row['material']}:
                raise ValueError('Published stock tool material changed')
            flags=re.findall(r'^contents (.*);$',block,re.M)
            expected_flags=row.get('collision_component',{}).get('brush_contents',[])
            if flags != ([' '.join(expected_flags)] if expected_flags else []):
                raise ValueError('Published native brush flags changed')
            count+=1
    return dict(geometry_verified=True,brushes=count,prefabs=len(files),
        checks=['Published plane equations and materials','4..64 faces per brush',
            'Certified exterior/volume partition union','Exact coincident stock-category component coverage',
            'Category differences isolated under review'])
