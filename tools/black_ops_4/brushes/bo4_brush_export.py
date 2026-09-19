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
        # A disabled type option preserves the same split by use, changing only surfaces.
        if not auto_types:
            for row in choices['rows']:
                row['material']='t7_concrete_poured_bunker_paint_01_grey_lt'
                row['collision_components']=[]
                row['brush_contents']=[]
                row['representation']='single_hull'
                row['status']='GREY_GEOMETRY_PLACEHOLDER'
            (world/'material_assignments.json').write_text(json.dumps(choices,separators=(',',':'))+'\n')
        world_out=staged/'world'
        prior=world_out/'collision_metadata.json'
        if prior.exists():
            wr=json.loads(prior.read_text())
            if wr['source_metadata_sha256']!=hashlib.sha256((world/'collision_data.json').read_bytes()).hexdigest():
                raise ValueError('Existing prefab work belongs to different source data')
            choice_by_id={r['brush_index']:r for r in choices['rows']}
            if wr.get('prefab_layout_version')!=2 or any(r['type_assignment']!=choice_by_id[r['source_brush_index']] for r in wr['rows']):
                raise ValueError('Existing prefab work uses different type settings')
            for file,record in wr['map_files'].items():
                if hashlib.sha256((world_out/file).read_bytes()).hexdigest()!=record['sha256']:
                    raise ValueError('Existing prefab changed')
        else: wr=brushes(world,world_out,name,choices)
        status('BO4: converting model-attached physics brushes',65)
        physics(model)
        filters=np.fromfile(world/probe['global_filter_candidate']['file'],'<u4').reshape(-1,2)
        pr=model_brushes(model,staged/'physics',name,Types(probe,reference) if auto_types else None,filters)
        tr=None
        if include_triggers:
            status('BO4: preserving entity properties and writing review volumes',85)
            entities(world);tr=triggers(world,world_out,name)
        # The triangle branch is a separate collision representation with its own
        # verified ranges. It is published as decoded metadata, not as brushes:
        # ownership and placement of these surfaces are still untraced.
        triangle_summary=model_collision_summary=None
        if model_triangles:
            status('BO4: decoding triangle collision surfaces',88)
            try:
                decode_triangles(world)
                triangle_summary=json.loads((world/'triangle_collision.json').read_text())['summary']
            except (ValueError, KeyError, StopIteration, FileNotFoundError) as error:
                triangle_summary={'decoded':False,'reason':str(error)}
            collision=capture/'model_collision'
            if collision.is_dir():
                status('BO4: recovering model collision triangles',91)
                try:
                    decode_model_collision(collision)
                    model_collision_summary=json.loads(
                        (collision/'model_collision_data.json').read_text())['summary']
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
                    files[relative]={'sha256':hashlib.sha256(target.read_bytes()).hexdigest()}
                elif path.suffix=='.json':
                    mapped=remap_references(json.loads(path.read_text()),paths)
                    (metadata/path.name).write_text(json.dumps(mapped,separators=(',',':'))+'\n')
        shutil.copy2(world/'material_assignments.json',metadata/'material_assignments.json')
        if include_triggers:shutil.copy2(world/'entity_properties.json',metadata/'entity_properties.json')
        rejections=wr['source_rejections'];omissions=pr['omissions']
        report=dict(schema='greyhound-bo4-brush-export-v1',status='exported_with_review',
            map_name=name,map_hash=hex(key),prefabs=files,prefab_geometry_verified=True,
            all_placed_brushes_present=False,
            summary=dict(world_inline_brushes=wr['summary']['brushes'],model_physics_brushes=pr['summary']['brushes'],
                source_brush_rejections=len(rejections),unresolved_model_primitive_instances=len(omissions),
                trigger_hulls=len(tr['rows']) if tr else 0,trigger_omissions=len(tr['omissions']) if tr else 0),
            collision_mapping=choices.get('collision_summary'),
            one_output_brush_per_source=True,
            review=['Runtime placements differing from authored records remain marked REVIEW',
                    'Trigger model/spawn association is provisional and prefabs are marked REVIEW',
                    'Unidentified model primitives are preserved in source JSON and omitted from maps',
                    'Named BO3 tool-property differences are recorded; scripts are not ported'],
            rejected_brushes=rejections,compiled=False,radiant_opened=False)
        if triangle_summary is not None:
            report['triangle_collision']=dict(triangle_summary,
                file='triangle_collision.json',
                representation='decoded_source_surfaces_not_radiant_brushes',
                ownership='untraced',exported_as_geometry=False)
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
        (metadata/'export_report.json').write_text(json.dumps(report,indent=2)+'\n')
        (output/'README.txt').write_text('BO4 category prefabs\n\nprefabs/brushes: world and inline brushes, non-colliding geometry, traversal, and optional review volumes/triggers.\nprefabs/clips: world and inline clips grouped together by use, with assigned tool/material layers inside the prefab.\nprefabs/model clips: model-attached collision, retained separately for later.\nCopy the three folders under prefabs into map_source. Do not import model clips for the current iteration.\nAll geometry uses world coordinates: origin, zero rotation, scale 1.\nNo terrain, render models, new GDT or gameplay scripts.\nSee metadata/export_report.json for differences and omissions.\n')
    status('BO4 prefabs exported; review/omissions are listed in metadata/export_report.json',100,status='exported_with_review',output=str(output))
    return 0
