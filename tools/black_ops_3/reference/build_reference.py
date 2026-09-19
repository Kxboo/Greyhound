"""Developer-only regeneration of the BO3 reference shipped with Greyhound.

The application never needs the source installation or asks users to run this.
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
import csv
import hashlib
import json
import re
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
from audit_cw_bo3_brush_types import entities
from bo3_material_definitions import materials as resolve_materials


def build(root):
    sources = []
    material_paths = ('art_assets/t6_legacy/texture_assets/clip.gdt', 'texture_assets/tools.gdt')
    for relative in material_paths:
        path = root / relative
        sources.append(dict(file=relative, sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    materials = resolve_materials([root / relative for relative in material_paths], relative_to=root)
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
    property_start=definitions.index('Asset.AddEntry_CheckBox( "missileClip"')
    property_end=definitions.index('// Surface Type',property_start)
    first_property_line=definitions.count('\n',0,property_start)+1
    last_property_line=definitions.count('\n',0,property_end)+1
    for number,line in enumerate(definitions.splitlines(),1):
        match=re.search(r'AddEntry_CheckBox\(\s*"([^"]+)"',line)
        if match and first_property_line <= number < last_property_line:
            tooltip=re.search(r'SetToolTip\(\s*"([^"]+)"',line)
            fields.append(dict(name=match[1],line=number,tooltip=tooltip[1] if tooltip else None))
    enum=re.search(r'string SurfaceClimbTypeEntries\s*=\s*"""(.*?)"""',definitions,re.S)
    if not enum:raise ValueError('Missing BO3 surfaceClimbType definition')
    climb=[s.strip() for s in enum[1].split('|') if s.strip()]
    surface_enum=re.search(r'string SurfaceTypeEntries\s*=\s*(?://[^\n]*\n\s*)?"""(.*?)"""',definitions,re.S)
    if not surface_enum:raise ValueError('Missing BO3 surfaceType definition')
    surfaces=[s.strip() for s in surface_enum[1].split('|') if s.strip()]
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
               'trigger_use_touch','trigger_hurt','trigger_lookat','trigger_out_of_bounds','trigger_box','trigger_radius',
               'node_negotiation_begin','node_negotiation_end')
    entity_reference={name:resolved_entity(name) for name in supported if name in definitions_by_name}
    sources.append(dict(file='bin/t7.def.json',sha256=hashlib.sha256(entity_path.read_bytes()).hexdigest()))
    zombie_relative='share/raw/scripts/shared/ai/zombie.gsc'
    flags_relative='share/raw/scripts/shared/shared.gsh'
    zombie_text=(root/zombie_relative).read_text()
    flags_text=(root/flags_relative).read_text()
    predicate=re.search(r'function zombieShouldProceduralTraverse\([^)]*\)\s*\{([^}]+)\}',zombie_text)
    flag=re.search(r'#define\s+SPAWNFLAG_PATH_PROCEDURAL\s+(\d+)',flags_text)
    if not predicate or not flag:raise ValueError('Missing BO3 zombie procedural traversal evidence')
    compact=re.sub(r'\s+','',predicate[1])
    if 'entity.traverseStartNode.spawnflags&SPAWNFLAG_PATH_PROCEDURAL&&entity.traverseEndNode.spawnflags&SPAWNFLAG_PATH_PROCEDURAL' not in compact:
        raise ValueError('BO3 zombie traversal flag predicate changed; review before regenerating')
    procedural_bit=int(flag[1])
    if any(int(entity_reference[cls]['PROCEDURAL']['spawnflag'])!=procedural_bit for cls in ('node_negotiation_begin','node_negotiation_end')):
        raise ValueError('BO3 editor and zombie script procedural flags disagree')
    navigation_sources=[]
    for relative,text,match in ((zombie_relative,zombie_text,predicate),(flags_relative,flags_text,flag)):
        entry=dict(file=relative,sha256=hashlib.sha256((root/relative).read_bytes()).hexdigest(),
                   line=text.count('\n',0,match.start())+1)
        sources.append(dict(entry));navigation_sources.append(entry)
    ast_relative='share/raw/animtables/zombie.ai_ast'
    am_relative='share/raw/animtables/zombie.ai_am'
    alias_rows=list(csv.reader((root/am_relative).read_text().splitlines()))
    aliases={row[0].lower():row[1] for row in alias_rows if len(row)>1 and row[0] and row[1]}
    traversals={};section=None;columns=[]
    for number,row in enumerate(csv.reader((root/ast_relative).read_text().splitlines()),1):
        if len(row)==1 and '@' in row[0]:section=row[0];columns=[];continue
        if section!='traverse@zombie' or not any(row):continue
        if row[0].startswith('_'):columns=row;continue
        if not columns:continue
        values=dict(zip(columns,row));name=values.get('_traversal_type','').lower()
        match=re.fullmatch(r'(jump_up|jump_down|jump_across|mantle_over)_(\d+)',name)
        alias=values.get('_animation_alias','').lower()
        if not match or alias not in aliases:continue
        entry=traversals.setdefault(name,dict(animscript=name,family=match[1],nominal_distance=int(match[2]),rows=[]))
        entry['rows'].append(dict(source=ast_relative,line=number,conditions=values,
                                 animation_alias=alias,xanim=aliases[alias],animation_map=am_relative))
    if not traversals:raise ValueError('No stock zombie traversal animations resolved')
    reverse_prefab='map_source/_prefabs/library/traverse/t7_zm_jump_128.map'
    example_nodes=entities(root/reverse_prefab)
    if not any(e['properties'].get('classname')=='node_negotiation_end' and e['properties'].get('animscript')=='jump_down_128' for e in example_nodes):
        raise ValueError('BO3 reverse traversal animation authoring example changed')
    one_way_prefab='map_source/_prefabs/library/traverse/t7_zm_jump_down_160_one_way.map'
    one_way_nodes=entities(root/one_way_prefab)
    if not any(e['properties'].get('classname')=='node_negotiation_end' and e['properties'].get('animscript')=='' for e in one_way_nodes):
        raise ValueError('BO3 one-way traversal authoring example changed')
    for relative in (ast_relative,am_relative,'share/raw/behavior/zm_genesis_zombie.ai_bt',
                     'share/raw/behavior/zombie/ZombieTraverseBehavior.json',reverse_prefab,one_way_prefab):
        entry=dict(file=relative,sha256=hashlib.sha256((root/relative).read_bytes()).hexdigest())
        sources.append(dict(entry));navigation_sources.append(entry)
    return dict(schema='bo3-tool-reference-v2', sources=sources, materials=materials,tool_images=tool_images,
                entity_reference=dict(source='bin/t7.def.json',classes=entity_reference),
                navigation_reference=dict(procedural_flag=procedural_bit,requires_both_endpoints=True,
                    source_function='zombieShouldProceduralTraverse',sources=navigation_sources,
                    procedural_behavior_requirement='zm_genesis_zombie includes the procedural branch; the default ZombieTraverseBehavior uses animation traversal instead',
                    stock_traversals=list(traversals.values()),animation_profile='zombie.ai_ast + zombie.ai_am',
                    reverse_end_animscript_reference=reverse_prefab,
                    one_way_empty_end_animscript_reference=one_way_prefab,
                    scope='Installed animation table mappings, zombie script predicate and editor flags; no compiled gameplay validation'),
                material_property_reference=dict(source='deffiles/material.awi',fields=fields,surfaceClimbType=climb,surfaceType=surfaces),
                volume_reference=dict(map=relative, sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                    entity_class='info_volume', script_noteworthy='player_volume', material='volume',
                    observed_entities=len(volumes)))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bo3', required=True, type=Path)
    parser.add_argument('--output', type=Path, default=TOOLS_ROOT / 'black_ops_3/reference/bo3_reference.json')
    args = parser.parse_args()
    reference = build(args.bo3)
    args.output.write_text(json.dumps(reference, indent=2), encoding='utf-8')
    print(f"Bundled {len(reference['materials'])} material definitions")
