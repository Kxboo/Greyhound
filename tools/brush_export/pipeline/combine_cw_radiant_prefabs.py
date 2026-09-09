"""Combine generated world brushes and same-map player volumes without moving geometry."""
import hashlib
import re
from collections import Counter
from audit_cw_bo3_brush_types import entities


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def combine(folder, name, map_hash, volumes):
    if int(volumes['name_hash'],16) != int(map_hash,16):
        raise ValueError('Cannot combine collision and volumes from different maps')
    brushes=folder/(name+'_brush_collision.map')
    volume_map=folder/volumes['map_file']
    if sha(volume_map)!=volumes['map_sha256']:
        raise ValueError('Player-volume prefab changed before combination')
    sources=[brushes,volume_map]
    headers=[];blocks=[]
    for path in sources:
        text=path.read_text()
        starts=list(re.finditer(r'^// entity (\d+)(?::[^\n]*)?\s*$',text,re.M))
        if not starts or [int(m[1]) for m in starts]!=list(range(len(starts))):
            raise ValueError('Unexpected generated entity numbering')
        header=text[:starts[0].start()].splitlines()
        if not header or header[0]!='iwmap 4':raise ValueError('Expected generated iwmap 4')
        headers.extend(header[1:])
        blocks.append([text[m.start():starts[i+1].start() if i+1<len(starts) else len(text)]
                       for i,m in enumerate(starts)])
    if len(blocks[0])!=1:raise ValueError('Collision prefab must contain one worldspawn')
    original=[entities(path) for path in sources]
    if any(rows[0]['properties'].get('classname')!='worldspawn' for rows in original):
        raise ValueError('Missing source worldspawn')
    if original[1][0]['brush_blocks']:raise ValueError('Unexpected volume world brushes')
    layers={}
    for line in headers:
        if not line.strip():continue
        match=re.fullmatch(r'"([^"]+)" flags( active)?',line)
        if not match:raise ValueError('Unexpected generated layer header')
        if match[1] in layers and layers[match[1]]!=line:raise ValueError('Conflicting layer definitions')
        layers[match[1]]=line
    body=blocks[0]+blocks[1][1:]
    output='\n'.join(['iwmap 4',*[layers[k] for k in sorted(layers)]])+'\n'+''.join(body)
    expanded=volumes.get('export_mode')=='triggers_and_volumes'
    target=folder/(name+('_collision_triggers_and_volumes.map' if expanded else '_collision_and_volumes.map'))
    target.write_text(output)
    expected=original[0]+original[1][1:]
    actual=entities(target)
    if len(expected)!=len(actual):raise ValueError('Combined entity coverage changed')
    for left,right in zip(expected,actual):
        for field in ('properties','brush_blocks','face_material_counts'):
            if left[field]!=right[field]:raise ValueError('Combined entity ownership changed')
    def faces(text):return [line for line in text.splitlines() if line.lstrip().startswith('(')]
    before=[line for path in sources for line in faces(path.read_text())]
    if before!=faces(output):raise ValueError('Combination changed planes, materials or texture projections')
    players=[r for r in actual[1:] if r['properties'].get('classname')=='info_volume' and r['properties'].get('script_noteworthy')=='player_volume']
    return dict(map_file=target.name,map_sha256=sha(target),map_hash=map_hash,
                source_files={p.name:sha(p) for p in sources},entities=len(actual),
                world_brushes=actual[0]['brush_blocks'],
                entity_class_counts=dict(Counter(r['properties']['classname'] for r in actual[1:])),
                trigger_entities=sum(r['properties']['classname'].startswith('trigger_') for r in actual[1:]),
                entity_hull_brushes=sum(r['brush_blocks'] for r in actual[1:]),
                player_volume_entities=len(players),
                player_volume_brushes=sum(r['brush_blocks'] for r in players),
                unchanged_face_definitions=len(before),layers=len(layers),
                coordinates='world; no extra transforms applied',compiler_validated=False)
