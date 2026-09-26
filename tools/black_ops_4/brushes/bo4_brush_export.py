"""Independent BO4 capture intake for Greyhound's packaged Radiant exporter."""

# Support direct execution and the isolated packaged Python runtime.
import sys as _tool_sys
from pathlib import Path as _ToolPath
TOOLS_ROOT = next(p for p in _ToolPath(__file__).resolve().parents if (p / "tool_bootstrap.py").is_file())
_tool_sys.path.insert(0, str(TOOLS_ROOT))
import tool_bootstrap as _tool_bootstrap
_tool_bootstrap.activate(__file__)
REPO_ROOT = TOOLS_ROOT.parent
import contextlib
import hashlib
import json
import re
import shutil
from collections import Counter
import numpy as np
from pathlib import Path
from decode_bo4_collision import decode
from build_bo4_brush_hulls import build as hulls
from decode_bo4_entity_properties import decode as entities
from assign_bo4_bo3_types import build as assignments, Types
from export_bo4_radiant_brushes import export as brushes
from decode_bo4_model_physics import decode as physics
from export_bo4_model_physics_map import export as model_brushes
from export_bo4_trigger_prefabs import export as triggers
from bo4_prefab_layout import prefab_relative_path, remap_references
from decode_bo4_triangle_collision import decode as decode_triangles
from decode_bo4_model_collision import decode as decode_model_collision
from verify_bo4_brush_geometry import verify as verify_geometry
from bo4_brush_visual_materials import load_visuals


def run(capture, output, reference, status, auto_types=True, include_triggers=True,
        model_triangles=False):
    capture, output = Path(capture), Path(output)
    world=capture/'world';model=capture/'model_physics'
    probe=json.loads((world/'world_pools_probe.json').read_text())
    if not probe['write_success']:raise ValueError('BO4 capture reported an incomplete write')
    clip=next(p for p in probe['pools'] if p['pool_index']==11)
    if len(clip['assets'])!=1:raise ValueError('Ambiguous BO4 map')
    asset=clip['assets'][0];key=int(asset['name_hash_candidate'],16)
    name='bo4_map_'+format(key,'x')
    candidates=[asset.get('resolved_name',''),asset.get('name','')]
    candidates += ['maps/zm/'+n+'.d3dbsp' for n in ('zm_white','zm_orange','zm_towers','zm_red','zm_blue','zm_gla','zm_mansion','zm_zod')]
    for candidate in candidates:
        h=0xcbf29ce484222325
        for b in candidate.encode():h=((h^b)*0x100000001b3)&0xffffffffffffffff
        stem=Path(candidate.replace('\\','/')).stem
        if h&0xfffffffffffffff==key and re.fullmatch('[a-zA-Z0-9_-]+',stem):name=stem;break
    pd=json.loads((model/'model_physics_probe.json').read_text())
    if int(pd['map_hash'],16)!=key:raise ValueError('World and model physics captures belong to different maps')
    staged=capture/'prefab_work';staged.mkdir(exist_ok=True)
    with (capture/'radiant_conversion.log').open('w') as log, contextlib.redirect_stdout(log):
        status('BO4: checking world/inline brush ownership',10)
        collision=decode(world);(world/'collision_data.json').write_text(json.dumps(collision,separators=(',',':'))+'\n')
        status('BO4: validating closed brush hulls',25);hulls(world)
        status('BO4: checking all side-filter contents and material choices',40)
        choices=assignments(world,reference)
        # BO4 always keeps source-derived named tool categories. The legacy CW
        # grey-only option cannot substitute a material for original visuals.
        resolver=load_visuals(capture)
        if resolver.map_hash is not None and int(str(resolver.map_hash),0)!=key:
            raise ValueError('Render and collision captures belong to different maps')
        world_out=staged/'world'
        wr=brushes(world,world_out,name,choices,resolver)
        status('BO4: converting model-attached physics brushes',65)
        physics(model)
        filters=np.fromfile(world/probe['global_filter_candidate']['file'],'<u4').reshape(-1,2)
        pr=model_brushes(model,staged/'physics',name,Types(probe,reference),filters)
        tr=None
        if include_triggers:
            status('BO4: preserving entity properties and writing review volumes',85)
            entities(world);tr=triggers(world,world_out,name)
        # The triangle branch is a separate collision representation with its own
        # verified ranges, surface-tree ownership and filter materials. It is
        # published as decoded metadata, not as brushes.
        triangle_summary=model_collision_summary=None
        if model_triangles:
            status('BO4: decoding triangle collision surfaces',88)
            try:
                decode_triangles(world)
                triangle_summary=json.loads((world/'triangle_collision.json').read_text())['summary']
            except (ValueError, KeyError, StopIteration, FileNotFoundError) as error:
                triangle_summary={'decoded':False,'reason':str(error)}
            model_collision_root=capture/'model_collision'
            if model_collision_root.is_dir():
                status('BO4: recovering model collision triangles',91)
                try:
                    decode_model_collision(model_collision_root,world/'world_pools_probe.json')
                    model_collision_summary=json.loads(
                        (model_collision_root/'model_collision_data.json').read_text())['summary']
                except (ValueError, KeyError, IndexError, FileNotFoundError) as error:
                    model_collision_summary={'decoded':False,'reason':str(error)}
        status('BO4: verifying separate prefabs and writing omission report',95)
        metadata=output/'metadata';metadata.mkdir(parents=True,exist_ok=True)
        paths={path.name:('prefabs/'+prefab_relative_path(path.name).as_posix())
               for folder in (world_out,staged/'physics') for path in folder.glob('*.map')}
        files={}
        for folder in (world_out,staged/'physics'):
            for path in folder.iterdir():
                if not path.is_file():continue
                if path.suffix=='.map':
                    relative=paths[path.name];target=output/relative
                    target.parent.mkdir(parents=True,exist_ok=True)
                    if target.exists():raise ValueError('Published prefab already exists')
                    shutil.copy2(path,target)
                    files[relative]={'sha256':hashlib.sha256(target.read_bytes()).hexdigest(),'bytes':target.stat().st_size,'geometry_kind':'brush'}
                elif path.suffix=='.json':
                    mapped=remap_references(json.loads(path.read_text()),paths)
                    (metadata/path.name).write_text(json.dumps(mapped,separators=(',',':'))+'\n')
        shutil.copy2(world/'material_assignments.json',metadata/'material_assignments.json')
        if include_triggers:shutil.copy2(world/'entity_properties.json',metadata/'entity_properties.json')
        visual=resolver.publish_patches(output,name,collision['entities'])
        for relative,record in visual.get('prefabs',{}).items():
            if relative in files:raise ValueError('Visual and collision prefab paths overlap')
            path=output/relative
            files[relative]=dict(record,sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                bytes=path.stat().st_size,geometry_kind='explicit_uv_patch')
        (metadata/'visual_surfaces.json').write_text(json.dumps(visual,indent=2)+'\n')
        (metadata/'bo3_material_reference.json').write_text(json.dumps(reference,separators=(',',':'))+'\n')
        published_reports=[remap_references(r,paths) if r else None for r in (wr,pr,tr)]
        verified=verify_geometry(output,published_reports,reference)
        (metadata/'geometry_verification.json').write_text(json.dumps(verified,indent=2)+'\n')
        rejections=wr['source_rejections'];omissions=pr['omissions']
        fallback_rows=[r for r in wr['rows']+pr['rows'] if r['type_assignment'].get('fallback')]
        visual_omissions=wr['omissions']+[r for r in omissions if r['status']=='requires_original_visual_material']
        mapping=dict(schema='greyhound-bo4-material-mapping-report-v1',
            policy='Source named collision categories select stock BO3 tools. Exact unions use coincident hulls. Remaining category differences are isolated in review. No generic visual fallback.',
            summary=dict(exact_category_source_choices=sum(not r['fallback'] and not r['visual_required'] for r in choices['rows']),
                category_union_source_choices=sum(len(r['collision_components'])>1 for r in choices['rows']),
                category_fallback_output_components=len(fallback_rows),visual_brush_instances_without_material=len(visual_omissions)),
            fallback_components=[dict(source_brush_index=r.get('source_brush_index'),entity_index=r.get('entity_index'),
                instance_index=r.get('instance_index'),entry_index=r.get('entry_index'),
                prefab_file=paths[r['prefab_file']],type_assignment=r['type_assignment']) for r in fallback_rows],
            original_visual_policy='Authoritative source render triangles use original materials and explicit UV. This does not establish original brush-face materials.',
            visual_brush_omissions=visual_omissions)
        grouped={}
        for row in wr['rows']+pr['rows']:
            decision=row['type_assignment']
            fields=('source_collision_properties','selected_stock_tools','representation',
                'added_collision_properties','omitted_collision_properties',
                'surface_type_names','added_surface_properties','omitted_surface_properties',
                'unknown_contents','fallback','fallback_reason')
            entry={field:decision[field] for field in fields}
            entry['target_surface_types']=sorted({c.get('surface_type') or '<unspecified>' for c in decision['collision_components']})
            key_summary=json.dumps(entry,sort_keys=True)
            if key_summary not in grouped:grouped[key_summary]=dict(entry,output_components=0)
            grouped[key_summary]['output_components']+=1
        mapping['named_stock_choices']=sorted(grouped.values(),key=lambda r:(not r['fallback'],r['selected_stock_tools']))
        (metadata/'material_mapping_report.json').write_text(json.dumps(mapping,indent=2)+'\n')
        readable=['BO4 stock tool assignments','',
            'Counts below are output components, including certified partitions and coincident category unions.',
            'Named collision category equality does not assert identical compiled gameplay or surface response.','']
        for entry in mapping['named_stock_choices']:
            readable.extend([
                ('REVIEW FALLBACK' if entry['fallback'] else 'EXACT NAMED CATEGORIES')+': '+', '.join(entry['selected_stock_tools']),
                '  Source categories: '+(', '.join(entry['source_collision_properties']) or '(none)'),
                '  Added collision categories: '+(', '.join(entry['added_collision_properties']) or '(none)'),
                '  Omitted collision categories: '+(', '.join(entry['omitted_collision_properties']) or '(none)'),
                '  Source surface response: '+(', '.join(entry['surface_type_names']) or '(unnamed)'),
                '  Tool surface response: '+', '.join(entry['target_surface_types']),
                '  Added surface properties: '+(', '.join(entry['added_surface_properties']) or '(none)'),
                '  Omitted surface properties: '+(', '.join(entry['omitted_surface_properties']) or '(none)'),
                '  Unresolved source contents bits: '+entry['unknown_contents'],
                '  Output components: '+str(entry['output_components']),''])
        (metadata/'material_mapping_report.txt').write_text('\n'.join(readable)+'\n')
        report=dict(schema='greyhound-bo4-brush-export-v2',status='exported_with_review',
            map_name=name,map_hash=hex(key),prefabs=files,
            prefab_geometry_verified=bool(verified['geometry_verified'] and
                (not visual.get('prefabs') or visual.get('geometry_verified') is True)),
            all_placed_brushes_present=False,auto_types_requested=bool(auto_types),
            summary=dict(world_inline_brushes=wr['summary']['brushes'],model_physics_brushes=pr['summary']['brushes'],
                source_brush_rejections=len(rejections),
                unresolved_model_primitive_instances=sum(o['status']!='requires_original_visual_material' for o in omissions),
                visual_brush_omissions=len(visual_omissions),category_fallback_components=len(fallback_rows),
                trigger_hulls=len(tr['rows']) if tr else 0,trigger_omissions=len(tr['omissions']) if tr else 0),
            collision_mapping=choices.get('collision_summary'),visual_surfaces=visual,
            one_output_brush_per_source=False,
            review=['Runtime placements differing from authored records remain marked REVIEW',
                    'Trigger model/spawn association is provisional and prefabs are marked REVIEW',
                    'Unidentified model primitives remain in diagnostics and are omitted from maps',
                    'Stock tool category differences are isolated in review; surface response differences remain in assignment metadata',
                    'Original visuals are separate explicit-UV render surfaces; brush-face identity is not inferred'],
            rejected_brushes=rejections,compiled=False,radiant_opened=False)
        if triangle_summary is not None:
            report['triangle_collision']=dict(triangle_summary,
                file='triangle_collision.json',
                representation='decoded_source_surfaces_not_radiant_brushes',
                exported_as_geometry=False)
            if (world/'triangle_collision.json').exists():
                shutil.copy2(world/'triangle_collision.json',metadata/'triangle_collision.json')
        if model_collision_summary is not None:
            report['model_collision']=dict(model_collision_summary,
                file='model_collision_data.json',
                representation='triangles_recovered_from_captured_equations',
                exported_as_geometry=False,
                note='Vertices are reconstructed from float32 plane/barycentric equations, not authored coordinates.')
            source=capture/'model_collision'/'model_collision_data.json'
            if source.exists():shutil.copy2(source,metadata/'model_collision_data.json')
        if not report['prefab_geometry_verified']:
            raise ValueError('A published prefab did not pass geometry verification')
        report['embedded_data']={}
        for folder in (metadata,output/'_mat_info',output/'_images'):
            if folder.exists():
                for path in sorted(folder.rglob('*')):
                    if path.is_file() and path.name!='export_report.json':
                        report['embedded_data'][path.relative_to(output).as_posix()]=dict(
                            sha256=hashlib.sha256(path.read_bytes()).hexdigest(),bytes=path.stat().st_size)
        (metadata/'export_report.json').write_text(json.dumps(report,indent=2)+'\n')
        (output/'README.txt').write_text(
            'BO4 Radiant output\n\n'
            'prefabs/brushes: named nonclip tool hulls and original-material render surfaces.\n'
            'prefabs/clips: source-derived stock clip categories.\n'
            'prefabs/model clips: model-attached stock collision hulls.\n'
            'prefabs/review: category fallbacks and provisional trigger/volume associations.\n'
            '_mat_info and _images: original render material dependencies, when captured successfully.\n\n'
            'All geometry uses world coordinates: origin 0, rotation 0, scale 1.\n'
            'Clip tools match named source categories exactly when possible. Some combinations require coincident stock-tool hulls.\n'
            'Every remaining category addition/omission is isolated in review and listed by name in metadata/material_mapping_report.json.\n'
            'Surface response differences remain in the detailed type assignments; named category equality is not a compiled gameplay claim.\n'
            'No generic grey fallback is used for original visual materials. Proven source render surfaces use explicit UV patches.\n'
            'Visual brush-face associations and unsupported placements may remain unresolved and are recorded as omissions.\n'
            'Legacy automatic-types checkbox does not disable verified BO4 collision category mapping.\n'
            'High-face hulls are partitioned with exact volume and exterior checks; each output brush has at most 64 faces.\n'
            'Raw diagnostics retain excluded source geometry. No scripts are ported; Radiant open/compile has not been tested.\n')
    status('BO4 prefabs exported; review/omissions are listed in metadata/export_report.json',100,status='exported_with_review',output=str(output))
    return 0
