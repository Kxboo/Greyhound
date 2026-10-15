"""Choose a BO4 terrain source, original-material CAST, or baked CAST export."""
from __future__ import annotations
import sys as _tool_sys
from pathlib import Path as _ToolPath
TOOLS_ROOT = next((p for p in _ToolPath(__file__).resolve().parents if (p / 'tool_bootstrap.py').is_file()))
_tool_sys.path.insert(0, str(TOOLS_ROOT))
import tool_bootstrap as _tool_bootstrap
_tool_bootstrap.activate(__file__)
import argparse, json, shutil, hashlib
from pathlib import Path
from package_bo4_terrain import package
from export_baked_terrain import export as bake, map_identity

def export(source, output, mode='source', progress=None):
    source, output = (Path(source).resolve(), Path(output).resolve())
    if mode not in ('source', 'native', 'baked'):
        raise ValueError('Unknown terrain export mode')
    if progress:
        Path(progress).parent.mkdir(parents=True, exist_ok=True)
    if mode == 'baked':
        if not source.is_file():
            raise ValueError('Baked mode requires the original full terraingfx_probe.json')
        return bake(source, output, max_models=4096, progress=progress)
    target = output / 'package'
    if target.exists():
        raise ValueError('Use a new export folder; package already exists')
    if source.is_dir():
        manifest = source / 'capture/terraingfx.json'
        if not manifest.is_file():
            raise ValueError('Select the source package folder containing capture/terraingfx.json')
        if target.is_relative_to(source):
            raise ValueError('Export output must be outside the input package')
        shutil.copytree(source, target)
        identity = hashlib.sha256(manifest.read_bytes()).hexdigest()[:12]
    else:
        identity = map_identity(json.loads(source.read_text(encoding='utf8')))
        package(source, target)
    if mode == 'native':
        from export_native_terrain import export_package
        report = export_package(target, output, identity, progress)
    else:
        report = {'schema': 'greyhound-bo4-terrain-source-v1', 'status': 'complete', 'mode': 'source', 'source_package': 'package'}
        (output / 'terrain_export.json').write_text(json.dumps(report, indent=2) + '\n')
        (output / 'README.txt').write_text('Select package/ in TerrainReconstructor. This is source data, with original material images; no model or texture bake was performed.\nConsult package_audit.json for capture omissions.\n')
    if progress:
        Path(progress).write_text('100')
    return report
if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path, help='full terrain probe JSON, or a source package for source/native mode')
    parser.add_argument('output', type=Path, help='new output folder')
    parser.add_argument('--mode', choices=['source', 'native', 'baked'], default='source')
    parser.add_argument('--progress', type=Path)
    args = parser.parse_args()
    print(json.dumps(export(args.source, args.output, args.mode, args.progress), indent=2))
