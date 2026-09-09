"""Developer-only regeneration of the BO3 reference shipped with Greyhound.

The application never needs the source installation or asks users to run this.
"""
import argparse
import hashlib
import json
import re
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / 'pipeline'))
from audit_cw_bo3_brush_types import entities, gdt


def build(root):
    materials, sources = [], []
    for relative in ('art_assets/t6_legacy/texture_assets/clip.gdt', 'texture_assets/tools.gdt'):
        path = root / relative
        sources.append(dict(file=relative, sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
        materials.extend(dict(**row, source=relative) for row in gdt(path))
    names = [m['name'] for m in materials]
    if len(names) != len(set(names)):
        raise ValueError('Duplicate material definitions require review before packaging')
    relative = 'map_source/zm/zm_giant.map'
    path = root / relative
    volumes = [e for e in entities(path) if e['properties'].get('classname') == 'info_volume'
               and e['properties'].get('script_noteworthy') == 'player_volume']
    if not volumes or any(set(e['face_material_counts']) != {'volume'} for e in volumes):
        raise ValueError('BO3 player-volume reference no longer matches the exporter')
    image_path=root/'texture_assets/images.gdt'
    text=image_path.read_text(encoding='utf-8-sig');tool_images=[]
    for match in re.finditer(r'"([^"\n]+)"\s*\(\s*"image.gdf"\s*\)\s*\{([^{}]*)\}',text):
        props=dict(re.findall(r'"([^"\n]*)"\s*"([^"\n]*)"',match[2]))
        image_file=re.sub(r'\\+', '/', props.get('baseImage',''))
        if not image_file.startswith('art_assets/t6_legacy/texture_assets/tools/'):continue
        tool_images.append(dict(name=match[1],image_file=image_file,source='texture_assets/images.gdt',
            source_line=text.count('\n',0,match.start())+1,
            referenced_by_materials=[m['name'] for m in materials if m['properties'].get('colorMap')==match[1]],
            same_name_material_in_catalogue=match[1] in names))
    sources.append(dict(file='texture_assets/images.gdt',sha256=hashlib.sha256(image_path.read_bytes()).hexdigest()))
    definition=root/'deffiles/material.awi';definitions=definition.read_text()
    fields=[]
    for number,line in enumerate(definitions.splitlines(),1):
        match=re.search(r'AddEntry_CheckBox\(\s*"([^"]+)"',line)
        if match and match[1] in {'noDraw','nonSolid','nonColliding','mount','sky','missileClip','bulletClip','aiSightClip'}:
            tooltip=re.search(r'SetToolTip\(\s*"([^"]+)"',line)
            fields.append(dict(name=match[1],line=number,tooltip=tooltip[1] if tooltip else None))
    enum=re.search(r'string SurfaceClimbTypeEntries\s*=\s*"""(.*?)"""',definitions,re.S)
    if not enum:raise ValueError('Missing BO3 surfaceClimbType definition')
    climb=[s.strip() for s in enum[1].split('|') if s.strip()]
    sources.append(dict(file='deffiles/material.awi',sha256=hashlib.sha256(definition.read_bytes()).hexdigest()))
    entity_path=root/'bin/t7.def.json'
    entity_rows=json.loads(entity_path.read_text())
    definitions_by_name={r.get('classname',r.get('templatename')):r for r in entity_rows}
    def resolved_entity(name,parents=()):
        if name in parents:raise ValueError('Cyclic BO3 entity inheritance')
        row=definitions_by_name[name];result={}
        for parent in row.get('parents','').split(','):
            if parent.strip():result.update(resolved_entity(parent.strip(),(*parents,name)))
        result.update(row);return result
    supported=('info_volume','trigger_multiple','trigger_once','trigger_damage','trigger_use',
               'trigger_use_touch','trigger_hurt','trigger_lookat','trigger_out_of_bounds','trigger_box','trigger_radius')
    entity_reference={name:resolved_entity(name) for name in supported if name in definitions_by_name}
    sources.append(dict(file='bin/t7.def.json',sha256=hashlib.sha256(entity_path.read_bytes()).hexdigest()))
    return dict(schema='bo3-tool-reference-v2', sources=sources, materials=materials,tool_images=tool_images,
                entity_reference=dict(source='bin/t7.def.json',classes=entity_reference),
                material_property_reference=dict(source='deffiles/material.awi',fields=fields,surfaceClimbType=climb),
                volume_reference=dict(map=relative, sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                    entity_class='info_volume', script_noteworthy='player_volume', material='volume',
                    observed_entities=len(volumes)))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bo3', required=True, type=Path)
    parser.add_argument('--output', type=Path, default=HERE / 'bo3_reference.json')
    args = parser.parse_args()
    reference = build(args.bo3)
    args.output.write_text(json.dumps(reference, indent=2), encoding='utf-8')
    print(f"Bundled {len(reference['materials'])} material definitions")
