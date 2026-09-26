"""Portable material/geometry bake; consumes only Greyhound's saved inputs.

No process access, map-specific paths, Blender installation, or game shader is
bundled. Geometry is returned in game units to Greyhound's model exporters.
"""
import argparse
import hashlib
import json
import struct
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
from PIL import Image
from output_maps import to_maps

SHADER_SHA = '6159daeb7882198314ffe9e8b6fab53c1b314258b43a106c1694c5a53d77d9ff'
LIMITATIONS = [
    'Static logical grid with conservative four-corner holes; not adaptive LOD/morph topology.',
    'Reconstructed dispatch constants, provisional linear-wrap bindless samplers; no exact frame parity claim.',
    'Weather globals omitted, matching the approved blend examples.',
    'Conventional tangent-space normal adaptation. Collision is not included.',
]


def write(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n', encoding='utf8')


def sample_height(height, uv):
    h, w = height.shape
    p = np.clip(np.asarray(uv, np.float32), 0, 1) * np.array([w, h], np.float32) - np.float32(.5)
    low = np.floor(p).astype(np.int64)
    f = p - low.astype(np.float32)
    x0, y0 = np.clip(low[:, 0], 0, w-1), np.clip(low[:, 1], 0, h-1)
    x1, y1 = np.clip(low[:, 0]+1, 0, w-1), np.clip(low[:, 1]+1, 0, h-1)
    # Convert only sampled pixels, keeping full-map memory bounded.
    a = height[y0, x0].astype(np.float32) / np.float32(65535) * (1-f[:, 0]) + height[y0, x1].astype(np.float32) / np.float32(65535) * f[:, 0]
    b = height[y1, x0].astype(np.float32) / np.float32(65535) * (1-f[:, 0]) + height[y1, x1].astype(np.float32) / np.float32(65535) * f[:, 0]
    return a * (1-f[:, 1]) + b * f[:, 1]


def solid_mask(entry):
    words = np.fromfile(entry['file'], '<u4', count=entry['width']*entry['height']).reshape(entry['height'], entry['width'])
    solid = np.zeros((words.shape[0]*4+1, words.shape[1]*8+1), bool)
    for y in range(4):
        for x in range(8):
            solid[y:-1:4, x:-1:8] = (words >> (y*8+x)) & 1
    return solid


def cells(solid, x, y):
    s = solid[y*32:y*32+33, x*32:x*32+33]
    if s.shape != (33, 33):
        raise ValueError('Tile outside source mask')
    return s[:-1, :-1] & s[:-1, 1:] & s[1:, :-1] & s[1:, 1:]


def tile_geometry(mapping, tile, height, shared, keep, x, y, placement, resolution):
    origin, cell = np.asarray(mapping['origin']), mapping['cell']
    camera = np.asarray(mapping['camera'], np.float32)
    rows = np.array([struct.unpack_from('<3f', tile, 160), struct.unpack_from('<3f', tile, 188)], np.float32)
    bias, scale = struct.unpack_from('<2f', tile, 276)

    def zsample(xy):
        xy = np.asarray(xy, np.float32) - camera
        uv = np.c_[xy, np.ones(len(xy), np.float32)] @ rows.T
        return sample_height(height, uv) * np.float32(scale) + np.float32(bias + mapping['z_translation'])

    yy, xx = np.mgrid[y*32:y*32+33, x*32:x*32+33]
    xy = np.c_[origin[0]+xx.ravel()*cell, origin[1]+yy.ravel()*cell]
    world = np.c_[xy, zsample(xy)]
    dx = (zsample(xy+[cell, 0])-zsample(xy-[cell, 0]))/(2*cell)
    dy = (zsample(xy+[0, cell])-zsample(xy-[0, cell]))/(2*cell)
    normals = np.c_[-dx, -dy, np.ones(len(dx))]
    normals /= np.linalg.norm(normals, axis=1, keepdims=True)
    cy, cx = (shared//33).min(1), (shared % 33).min(1)
    faces = shared[keep[cy, cx]].copy()
    cross = np.cross(world[faces[:, 1]]-world[faces[:, 0]], world[faces[:, 2]]-world[faces[:, 0]])
    if len(faces) and np.all(cross[:, 2] < 0):
        faces = faces[:, [0, 2, 1]]
    elif len(faces) and not np.all(cross[:, 2] > 0):
        raise ValueError('Invalid terrain winding')
    uy, ux = np.mgrid[:33, :33]
    uv = (8 + np.stack([ux, uy], axis=-1)/32*(resolution-16))/resolution
    vertices = np.c_[world-placement, normals, uv.reshape(-1, 2)].astype('<f4')
    if not np.isfinite(vertices).all():
        raise ValueError('Nonfinite terrain geometry')
    return vertices, faces.astype('<u4')


def main(args):
    source = json.loads(args.inputs.read_text())
    if hashlib.sha256(Path(source['shader']).read_bytes()).hexdigest() != SHADER_SHA:
        raise ValueError('Unvalidated terrain composition shader')
    if not source.get('distortion'):
        raise ValueError('Recovered distortion is required; no neutral fallback')
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    work = args.inputs.resolve().parent
    runner = Path(__file__).with_name('run_composition.exe')
    if not runner.is_file():
        raise ValueError('Missing bundled terrain shader runner')
    # Compact stable names keep nested image paths usable by Windows importers.
    name = 't' + hashlib.sha256(source['name'].encode('utf8')).hexdigest()[:12]
    res = args.resolution
    scene = bytearray(2656)
    struct.pack_into('<4f', scene, 159*16, 1, 1, 1, 1)
    (work/'scene.bin').write_bytes(scene)
    textures = {e['id']: e for e in source['textures']}
    jobs = []
    for m in source['mappings']:
        tile = Path(m['tile']).read_bytes()
        height_id = struct.unpack_from('<I', tile, 300)[0] & 16383
        mask_id = (struct.unpack_from('<I', tile, 300)[0] >> 14) & 16383
        mask = solid_mask(textures[mask_id])
        if mask.shape != (m['height']+1, m['width']+1):
            raise ValueError('CPU/GPU mask dimensions disagree')
        nx, ny = m['width']//32, m['height']//32
        if args.area == 'nearby':
            center = np.floor((np.asarray(m['camera'])-m['origin'])/(32*m['cell'])).astype(int)
            x0, y0 = max(0, min(nx-5, center[0]-2)), max(0, min(ny-5, center[1]-2))
            bounds = [x0, y0, min(nx, x0+5), min(ny, y0+5)]
        else:
            bounds = [0, 0, nx, ny]
        selected = [(x, y) for y in range(bounds[1], bounds[3]) for x in range(bounds[0], bounds[2]) if cells(mask, x, y).any()]
        jobs.append((m, tile, mask, height_id, selected))
    total = sum(len(j[-1]) for j in jobs)
    if not total:
        raise ValueError('No solid terrain in the selected area')
    packages, completed = [], 0
    # PNG compression releases the GIL; overlap it with the next WARP dispatch.
    savers = ThreadPoolExecutor(max_workers=12)
    pending_saves = []

    def save(pixels, path):
        pending_saves.append(savers.submit(lambda: Image.fromarray(pixels).save(path)))

    def drain_saves(keep=0):
        # Wait on the oldest saves only, so the queue stays full without unbounded memory.
        while len(pending_saves) > keep:
            pending_saves.pop(0).result()

    for m, tile, mask, height_id, selected in jobs:
        h = textures[height_id]
        if h['format'] != 56:
            raise ValueError('Expected native R16 height atlas')
        height = np.memmap(h['file'], '<u2', mode='r', shape=(h['height'], h['width']))
        shared = np.fromfile(m['indices'], '<u2').reshape(-1, 3)
        if shared.shape != (2048, 3) or shared.max() != 1088:
            raise ValueError('Unsupported shared index topology')
        groups = {}
        # Groups bound mesh/material counts and provide useful placement origins.
        for x, y in selected:
            groups.setdefault((x//5, y//5), []).append((x, y))
        order = [(key, x, y) for key, pages in sorted(groups.items(), key=lambda kv: (kv[0][1], kv[0][0])) for x, y in pages]

        def generic_for(x, y, path):
            generic = bytearray(256)
            step = 32*m['cell']/(res-16)
            start = np.asarray(m['origin'])+np.array([x, y])*32*m['cell']+(.5-8)*step
            struct.pack_into('<4f', generic, 0, *start, step, step)
            struct.pack_into('<2f', generic, 32, *m['camera'])
            struct.pack_into('<f', generic, 60, 1)
            struct.pack_into('<2If', generic, 64, 0, 1, 1)
            path.write_bytes(generic)

        # One persistent runner per mapping: device, shader and source textures load once.
        generic_for(order[0][1], order[0][2], work/'generic.bin')
        write(work/'dispatch.json', dict(width=res, height=res, shader=source['shader'], tile=m['tile'], layers=source['layers'],
                                         textures=source['textures'], distortion=source['distortion'],
                                         generic=str(work/'generic.bin'), scene=str(work/'scene.bin'), output_directory='scratch'))
        server = subprocess.Popen([str(runner), str(work/'dispatch.json'), '--serve'], stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            if server.stdout.readline().strip() != 'ready':
                raise RuntimeError('Terrain shader runner failed to start: '+server.stderr.read())

            def request(i):
                _, x, y = order[i]
                generic = work/f'generic_{i % 2}.bin'
                generic_for(x, y, generic)
                server.stdin.write(f'{generic}\t{work/f"scratch{i % 2}"}\n')
                server.stdin.flush()

            def result():
                line = server.stdout.readline().strip()
                if not line.startswith('ok'):
                    raise RuntimeError('Terrain material bake failed: '+(line or server.stderr.read()))

            # Canonical gutters span package boundaries too. Keep just one row of
            # small edge strips in memory, not thousands of complete texture pages.
            edges = {}
            package = None

            def close_package():
                package['meshfile'].close()
                packages.append(dict(name=package['stem'], folder=str(package['folder']), mesh_file=str(package['mesh_path']),
                                     meshes=package['records'], placement_origin_game_units=package['placement'].tolist()))
                write(package['folder']/'export_report.json', dict(status='awaiting_model_export', mapping=m['mapping'],
                    placement_origin_game_units=package['placement'].tolist(), tiles=[r['tile'] for r in package['records']],
                    texture_resolution=res, distortion_enabled=True, collision_included=False, limitations=LIMITATIONS))

            request(0)
            for i, ((gx, gy), x, y) in enumerate(order):
                result()
                scratch = work/f'scratch{i % 2}'
                arrays = [np.fromfile(scratch/f'vt{k}.f32', '<f4').reshape(res, res, 4) for k in range(3)]
                if i+1 < len(order):
                    request(i+1)  # the runner works on the next tile while this one is post-processed
                if package is None or package['key'] != (gx, gy):
                    if package is not None:
                        close_package()
                    stem = f'{name}m{m["mapping"]}x{gx*5}y{gy*5}'
                    folder = output/stem
                    folder.mkdir(exist_ok=False)
                    (folder/'_images').mkdir()
                    (folder/'_mat_info').mkdir()
                    mesh_path = work/(stem+'.meshbin')
                    package = dict(key=(gx, gy), stem=stem, folder=folder, mesh_path=mesh_path, meshfile=mesh_path.open('wb'), records=[],
                                   placement=np.r_[np.asarray(m['origin'])+(np.array([gx*5, gy*5])+2.5)*32*m['cell'], 0.])
                if not all(np.isfinite(a).all() for a in arrays):
                    raise ValueError('Nonfinite shader output')
                maps, valid = to_maps(arrays)
                if not valid.any():
                    raise ValueError(f'No shader coverage on solid tile {x},{y}')
                material = f'{name}m{m["mapping"]}x{x}y{y}'
                image_dir = package['folder']/'_images'/material
                image_dir.mkdir()
                for suffix, pixels in maps.items():
                    left, below = edges.pop((x-1, y, suffix, 'right'), None), edges.pop((x, y-1, suffix, 'top'), None)
                    if left is not None:
                        pixels[:, :16] = left
                    if below is not None:
                        pixels[:16] = below
                    edges[(x, y, suffix, 'right')] = pixels[:, -16:].copy()
                    edges[(x, y, suffix, 'top')] = pixels[-16:].copy()
                    save(pixels, image_dir/f'{material}_{suffix}.png')
                info = f'Name: {material}\n\nTechset: lit_plus\n\nsemantic,image_name\n'
                info += ''.join(f'{semantic},{material}_{suffix}\n' for semantic, suffix in [('colorMap','c'),('normalMap','n'),('glossMap','g'),('aoMap','o')])
                info += '\nname,type,x,y,z,w\ncolorTint,float3,1.000000,1.000000,1.000000,0.000000\n'
                (package['folder']/'_mat_info'/f'{material}.txt').write_text(info, encoding='utf8')
                vertices, faces = tile_geometry(m, tile, height, shared, cells(mask,x,y), x,y,package['placement'],res)
                offset = package['meshfile'].tell()
                package['meshfile'].write(vertices.tobytes());package['meshfile'].write(faces.tobytes())
                package['records'].append(dict(material=material, vertices=len(vertices), faces=len(faces), offset=offset, tile=[x,y]))
                completed += 1
                drain_saves(keep=48)
                if args.progress:
                    args.progress.write_text(str(15+int(completed/total*75)))
                print(f'Baked {completed}/{total}: mapping {m["mapping"]}, tile {x},{y}', flush=True)
            close_package()
            drain_saves()
        finally:
            if server.poll() is None:
                try:
                    server.stdin.write('quit\n'); server.stdin.flush()
                    server.wait(timeout=30)
                except Exception:
                    server.kill()
    savers.shutdown()
    write(work/'models.json',dict(packages=packages))
    write(output/'terrain_export.json',dict(status='awaiting_model_export',map=source['name'],area=args.area,tiles=total,
        distortion_enabled=True,shader_sha256=SHADER_SHA,texture_resolution=res,collision_included=False,limitations=LIMITATIONS,
        source_textures=[dict(id=e['id'],width=e['width'],height=e['height'],format=e['format'],sha256=hashlib.sha256(Path(e['file']).read_bytes()).hexdigest()) for e in source['textures']],
        distortion_sha256=hashlib.sha256(Path(source['distortion']['file']).read_bytes()).hexdigest(),
        layers_sha256=hashlib.sha256(Path(source['layers']).read_bytes()).hexdigest(),
        packages=[{k:v for k,v in p.items() if k not in ('meshes','mesh_file')} for p in packages]))


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('inputs', type=Path)
    ap.add_argument('--output', required=True, type=Path)
    ap.add_argument('--area', choices=('whole','nearby'), default='whole')
    ap.add_argument('--resolution', type=int, choices=(256,512,1024), default=1024)
    ap.add_argument('--progress', type=Path)
    main(ap.parse_args())
