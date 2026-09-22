"""Publish supplied render associations without guessing textures from collision."""
import hashlib
import json
from pathlib import Path

from render_surface_patches import render_surface_patches


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def export(normalized, staged, source=None):
    metadata = json.loads((staged/'collision_metadata.json').read_text())
    capture_hash = sha(normalized/'capture.json')
    if capture_hash != metadata['source_capture_sha256']:
        raise ValueError('Render export capture identity differs from brush metadata')
    identities = {(r['collision_world'], r['instance_index'], r['collision_asset_index'], r['brush_index'])
                  for r in metadata['rows']}
    report = dict(schema='greyhound-cw-render-transfer-v1', source_capture_sha256=capture_hash,
        status='render_material_uv_associations_unavailable', surfaces=0, patches=0,
        materials=[], source_brush_instances=0, coordinates='world', collision='nonColliding',
        association_validation='Producer-supplied verified association, capture hash and source identity checked. The exporter does not independently establish the producer join.',
        material_assets_installed=False,
        scope='Explicit render polygons, material names, corner UVs and optional colors only. No texture inference from collision categories; source shaders and baked lightmaps are not recovered.')
    prefabs = {}; files = {}
    if source is not None:
        source = Path(source)
        data = source.read_bytes()
        filename = metadata['map']+'_render_surfaces.map'
        temporary = staged/(filename+'.tmp')
        materials = set(); associated = set(); count = patches = 0
        try:
            with temporary.open('x', encoding='utf-8', newline='\n') as stream:
                stream.write('iwmap 4\n"000_Global" flags active\n// entity 0\n{\n"classname" "worldspawn"\n')
                for line_number, line in enumerate(data.decode('utf-8-sig').splitlines(), 1):
                    if not line.strip():
                        continue
                    surface = json.loads(line)
                    identity = surface.get('source_id')
                    if (surface.get('schema') != 'brush-render-surface-v1'
                            or surface.get('source_capture_sha256') != capture_hash
                            or not isinstance(identity, list) or len(identity) != 4
                            or any(type(value) is not int for value in identity)
                            or tuple(identity) not in identities
                            or surface.get('association') != 'verified' or not surface.get('evidence')):
                        raise ValueError(f'Render association is unverified or belongs to another capture/brush at line {line_number}')
                    for patch in render_surface_patches(surface):
                        stream.write(f'// brush {patches}\n'+patch)
                        patches += 1
                    count += 1; materials.add(surface['material']); associated.add(tuple(identity))
                stream.write('}\n')
            if not count:
                raise ValueError('Supplied render association file contains no surfaces')
            target = staged/filename
            if target.exists():
                raise ValueError('Render prefab already exists')
            temporary.rename(target)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
        copied = staged/'verified_render_surfaces.jsonl'
        copied.write_bytes(data)
        files[copied.name] = dict(file='metadata/'+copied.name, sha256=sha(copied))
        prefabs['render_surfaces'] = dict(file=filename, patches=patches, surfaces=count,
            coordinates='world', collision='nonColliding', sha256=sha(target))
        report.update(status='verified_surfaces_exported', surfaces=count, patches=patches,
            materials=sorted(materials), source_brush_instances=len(associated),
            source_file_sha256=sha(copied), source_file='metadata/'+copied.name,
            prefab=filename, material_assets_note='Install the referenced target materials and images separately; names and UVs are retained without replacement by clip.')
    path = staged/'render_transfer.json'
    path.write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    files[path.name] = dict(file='metadata/'+path.name, sha256=sha(path))
    return report, prefabs, files
