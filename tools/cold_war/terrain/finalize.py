"""Validate baked dependencies, seal final packages, then remove owned scratch files."""
import argparse
import hashlib
import json
from pathlib import Path


def finalize(root):
    root = root.resolve()
    manifest = json.loads((root/'terrain_export.json').read_text())
    work = root/'_work'
    if work.resolve().parent != root:
        raise ValueError('Scratch directory escapes export')
    for package in manifest['packages']:
        folder = root/package['name']
        if folder.resolve().parent != root:
            raise ValueError('Package escapes export')
        report = json.loads((folder/'export_report.json').read_text())
        materials = list((folder/'_mat_info').glob('*.txt'))
        if len(materials) != len(report['tiles']):
            raise ValueError('Missing terrain material info')
        for material in materials:
            for suffix in ('c','n','g','o'):
                image = folder/'_images'/material.stem/f'{material.stem}_{suffix}.png'
                if not image.is_file() or image.stat().st_size < 32:
                    raise ValueError('Missing baked image: '+str(image))
        models = [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in
                  {'.cast','.obj','.semodel','.xmodel_export','.xmodel_bin','.smd','.ma','.ascii','.gltf','.glb'}]
        if not models or any(p.stat().st_size == 0 for p in models):
            raise ValueError('Missing terrain model')
        report.update(status='complete', model_files=[p.name for p in models])
        (folder/'export_report.json').write_text(json.dumps(report,indent=2)+'\n')
        inventory = [dict(file=p.relative_to(folder).as_posix(),bytes=p.stat().st_size,
                          sha256=hashlib.sha256(p.read_bytes()).hexdigest())
                     for p in sorted(folder.rglob('*')) if p.is_file() and p.name!='inventory.json']
        (folder/'inventory.json').write_text(json.dumps(inventory,indent=2)+'\n')
    # Only files owned by this newly reserved export, after validation. Failed
    # exports retain their inputs for diagnosis. No historical exports touched.
    for p in sorted(work.rglob('*'), key=lambda p: len(p.parts), reverse=True):
        if not p.resolve().is_relative_to(work.resolve()):
            raise ValueError('Scratch link escapes export')
        if p.is_file():
            p.unlink()
        elif p.is_dir():
            p.rmdir()
    work.rmdir()
    manifest['status']='complete'
    (root/'terrain_export.json').write_text(json.dumps(manifest,indent=2)+'\n')
    (root/'README.txt').write_text('Terrain model packages\n\nKeep each model with its _mat_info and _images folders.\n'
        'terrain_export.json records each package placement in game units.\n'
        'CAST/OBJ/SEModel/glTF/Maya/XNA positions use centimetres (2.54 per game unit); XMODEL/SMD use game units.\n'
        'Distortion is enabled. Installed textures only; no texture-pack downloads.\n'
        'This is visual terrain geometry; collision and adaptive LODs are not included.\n')


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root',type=Path)
    finalize(parser.parse_args().root)
