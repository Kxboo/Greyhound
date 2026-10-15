"""Original BO4 material CAST export. Patch/collision fitting belongs to TerrainReconstructor."""
from pathlib import Path
import json, shutil, struct
import numpy as np
from PIL import Image
from bo4_native_source import NativeCapture
from build_bo4_terrain_cast import cast_node as node, cast_property as prop
from export_baked_terrain import write_placement_map
bone = node(b'bone', 16385, [prop('n', 's', 'tag_origin'), prop('p', 'i', np.array([4294967295], '<u4')), prop('lr', '4v', np.array([[0, 0, 0, 1]], '<f4')), prop('lp', '3v', np.zeros((1, 3), '<f4')), prop('wr', '4v', np.array([[0, 0, 0, 1]], '<f4')), prop('wp', '3v', np.zeros((1, 3), '<f4')), prop('s', '3v', np.ones((1, 3), '<f4'))])
skeleton = node(b'skel', 16384, [], [bone])

def write_native_cast(path, name, surfaces, matdata):
    children = [skeleton]
    names = sorted({a for a, g in surfaces})
    mh = {n: 8192 + i for i, n in enumerate(names)}
    for n in names:
        textures = matdata[n][0]
        files = {k: 1048576 + len(children) * 100 + i for i, k in enumerate(textures)}
        fn = [node(b'file', files[k], [prop('p', 's', v)]) for k, v in textures.items()]
        children.append(node(b'matl', mh[n], [prop('n', 's', n), prop('t', 's', 'pbr')] + [prop(k, 'l', np.array([v], '<u8')) for k, v in files.items()], fn))
    for idx, (n, g) in enumerate(surfaces):
        h, w = g.shape[:2]
        p = g[..., :3].reshape(-1, 3)
        nv = len(p)
        a = (np.arange(h - 1)[:, None] * w + np.arange(w - 1)).ravel()
        f = np.stack([np.stack([a, a + 1, a + w + 1], 1), np.stack([a, a + w + 1, a + w], 1)], 1).reshape(-1, 3)
        gx = np.gradient(g[..., 2], axis=1) / np.maximum(np.gradient(g[..., 0], axis=1), 1e-09)
        gy = np.gradient(g[..., 2], axis=0) / np.maximum(np.gradient(g[..., 1], axis=0), 1e-09)
        normals = np.stack([-gx, -gy, np.ones_like(gx)], -1)
        normals /= np.linalg.norm(normals, axis=-1, keepdims=True)
        uv = g[..., 7:9].copy()
        uv[..., 0] /= matdata[n][2][0]
        uv[..., 1] /= matdata[n][2][1]
        rgba = np.full(nv, 16777215, '<u4') | g[..., 6].ravel().astype('<u4') << 24
        assert nv <= 65535 and np.isfinite(p).all() and (f.max() < nv)
        children.append(node(b'mesh', 20480 + idx, [prop('n', 's', n + '_' + str(idx)), prop('vp', '3v', (p * 2.54).astype('<f4')), prop('vn', '3v', normals.reshape(-1, 3).astype('<f4')), prop('vc', 'i', rgba), prop('mi', 'b', np.ones(1, '<u1')), prop('wb', 'b', np.zeros(nv, '<u1')), prop('wv', 'f', np.ones(nv, '<f4')), prop('u0', '2v', uv.reshape(-1, 2).astype('<f4')), prop('ul', 'b', np.ones(1, '<u1')), prop('f', 'h', f.astype('<u2').ravel()), prop('m', 'l', np.array([mh[n]], '<u8'))]))
    data = struct.pack('<4sIII', b'cast', 1, 1, 0) + node(b'root', 1, [], [node(b'modl', 256, [prop('n', 's', name)], children)])
    path.write_bytes(data)
    (path.parent / '_mat_info' / (name + '.txt')).write_text('\n'.join((matdata[n][1] for n in names)))
    return names

def tile_surfaces(sector, i, j, matdata):
    ys = np.arange(j * 32, (j + 1) * 32 + 1)
    xs = np.arange(i * 32, (i + 1) * 32 + 1)
    yy, xx = np.meshgrid(ys, xs, indexing='ij')
    solid = sector.sample_solid(yy, xx)
    cells = solid[:-1, :-1] & solid[1:, :-1] & solid[:-1, 1:] & solid[1:, 1:]
    if not cells.any():
        return []
    surfaces = []
    for row in range(32):
        padded = np.r_[False, cells[row], False].astype(int)
        starts = np.flatnonzero(np.diff(padded) == 1)
        ends = np.flatnonzero(np.diff(padded) == -1)
        for lo, hi in zip(starts, ends):
            gy, gx = (yy[row:row + 2, lo:hi + 1], xx[row:row + 2, lo:hi + 1])
            base = np.zeros((*gx.shape, 11))
            base[..., 0] = sector.origin[0] + gx * sector.cell
            base[..., 1] = sector.origin[1] + gy * sector.cell
            base[..., 2] = sector.sample_height(gy, gx)
            base[..., 3:7] = 255
            for slot, layer in enumerate(sector.layers):
                alpha = np.rint(sector.sample_weight(slot, gy, gx) * 255)
                if slot and (not alpha.any()):
                    continue
                name = layer['material'] + ('_blend' if slot else '')
                g = base.copy()
                g[..., 6] = alpha
                u, v = sector.uv(slot, g[..., 0], g[..., 1])
                w, h = matdata[name][2]
                g[..., 7] = u * w
                g[..., 8] = v * h
                g[..., 2] += slot * 0.015625
                surfaces.append((name, g))
    return surfaces

def export_package(package_root, output, map_id, progress=None):
    package_root, output = (Path(package_root), Path(output))
    source = NativeCapture(package_root)
    audit = package_root / 'package_audit.json'
    if audit.is_file() and json.loads(audit.read_text()).get('excluded_sectors'):
        raise ValueError('Source package excludes sectors; inspect package_audit.json before model export')
    models = output / 'models'
    if models.exists():
        raise ValueError('Use a new export folder; models already exist')
    models.mkdir(parents=True)
    (models / '_mat_info').mkdir()
    (models / '_images').mkdir()
    matdata = {}
    bindings = []
    for name, m in source.materials.items():
        color = source.binding({'material': name}, 'color')
        if color is None:
            raise ValueError('Missing source colour image: ' + name)
        with Image.open(package_root / color['png_file']) as im:
            size = im.size
        for variant in (name, name + '_blend'):
            textures = {}
            lines = ['Name: ' + variant, '', 'semantic,image_name']
            for binding in m['bindings']:
                if not binding.get('png_file'):
                    continue
                original = (package_root / binding['png_file']).resolve()
                if not original.is_relative_to(package_root.resolve()):
                    raise ValueError('Image path escapes package')
                target = models / '_images' / original.name
                if target.exists() and target.read_bytes() != original.read_bytes():
                    raise ValueError('Conflicting image basename: ' + original.name)
                if not target.exists():
                    shutil.copy2(original, target)
                lines.append(binding['semantic'] + ',' + target.stem)
                role = {'color': 'albedo', 'normal': 'normal', 'gloss': 'gloss', 'occlusion': 'ao', 'reveal': 'reveal'}.get(binding['role'])
                if role:
                    textures[role] = '_images/' + target.name
            matdata[variant] = (textures, '\n'.join(lines) + '\n', size)
            bindings.append({'material': variant, 'source_material': name, 'textures': textures})
    rows = []
    total = sum((s.meta['tiles_across'] ** 2 for s in source.sectors))
    done = 0
    for sector in source.sectors:
        for j in range(sector.meta['tiles_across']):
            for i in range(sector.meta['tiles_across']):
                surfaces = tile_surfaces(sector, i, j, matdata)
                done += 1
                if surfaces:
                    name = f'bo4_native_{map_id}_s{sector.index}_x{i:03d}_y{j:03d}'
                    materials = write_native_cast(models / (name + '.cast'), name, surfaces, matdata)
                    rows.append({'name': name, 'sector': sector.index, 'tile': [i, j], 'materials': materials})
                if progress:
                    Path(progress).write_text(str(10 + int(85 * done / total)))
        print(f'BO4 original materials: sector {sector.index}, {len(rows)} models', flush=True)
    if not rows:
        raise ValueError('Source has no solid terrain model sections')
    write_placement_map(output / 'terrain.map', rows)
    report = {'schema': 'greyhound-bo4-native-terrain-v1', 'status': 'complete', 'mode': 'native', 'models': rows, 'model_count': len(rows), 'materials': bindings, 'source_package': 'package', 'textures_baked': False, 'geometry': 'Native height samples with conservative four-corner cutouts; runtime displacement not applied', 'blending': 'Original UVs and independent vertex alpha; reveal blending is not guaranteed in model importers', 'patches': 'Use the package folder in TerrainReconstructor for Radiant patches and collision budgets'}
    (output / 'terrain_export.json').write_text(json.dumps(report, indent=2) + '\n')
    (output / 'README.txt').write_text('Original BO4 materials, not composited terrain textures.\nModels, _mat_info and _images are in models/. terrain.map places them at origin.\nImport package/ in TerrainReconstructor for patches and collision-control settings.\nNative height lattice only; no shader displacement or BO3 compilation. See terrain_export.json.\n')
    return report
