"""Check the installed Greyhound conversion bundle without a running game."""

# Support direct execution and the isolated packaged Python runtime.
import sys as _tool_sys
from pathlib import Path as _ToolPath
TOOLS_ROOT = next(p for p in _ToolPath(__file__).resolve().parents if (p / "tool_bootstrap.py").is_file())
_tool_sys.path.insert(0, str(TOOLS_ROOT))
import tool_bootstrap as _tool_bootstrap
_tool_bootstrap.activate(__file__)
REPO_ROOT = TOOLS_ROOT.parent
import argparse
import hashlib
import importlib
import json
from pathlib import Path
import subprocess
import sys


def verify(bundle):
    bundle = Path(bundle).resolve()
    checks = []

    def check(name, operation):
        try:
            detail = operation()
            checks.append(dict(name=name, passed=True, detail=detail))
        except Exception as error:
            checks.append(dict(name=name, passed=False, error=str(error)))

    def integrity():
        manifest = json.loads((bundle / 'manifest.json').read_text())
        files = manifest['files']
        required = {'shared/runtime/export_brushes.py', 'shared/runtime/verify_runtime.py', 'shared/runtime/verify_saved_export.py', 'black_ops_3/reference/bo3_reference.json',
                    'black_ops_4/brushes/bo4_brush_export.py', 'cold_war/brushes/export_cw_radiant_brushes.py',
                    'cold_war/brushes/export_cw_model_collmaps.py',
                    'cold_war/brushes/cw_brush_reconstruction.py',
                    'cold_war/brushes/cw_collision_role_policy.py',
                    'cold_war/brushes/export_cw_render_surfaces.py', 'shared/brushes/render_surface_patches.py',
                    'shared/brushes/stock_material_metadata.py', 'shared/brushes/material_comparison_report.py'}
        if not required.issubset(files):
            raise ValueError('Manifest omits required tools: ' + ', '.join(sorted(required - files.keys())))
        for name, digest in files.items():
            path = (bundle / name).resolve()
            if not path.is_relative_to(bundle) or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                raise ValueError('Missing or changed packaged file: ' + name)
        return dict(files=len(files), version=manifest['version'])

    check('converter_integrity', integrity)
    for name in ('numpy', 'scipy'):
        check(name, lambda name=name: importlib.import_module(name).__version__)
    for name in ('cw_brush_reconstruction', 'cw_collision_role_policy', 'stock_material_metadata', 'export_cw_render_surfaces', 'export_cw_radiant_brushes', 'export_cw_model_collmaps',
                 'export_cw_bo3_trigger_entities', 'export_cw_bo3_navigation', 'export_cw_navigation_tools', 'export_cw_volume_connections', 'bo4_brush_export',
                 'decode_cw_float_collision_triangles', 'decode_bo4_model_collision'):
        check(name, lambda name=name: str(importlib.import_module(name).__file__))

    def catalogue():
        data = json.loads((TOOLS_ROOT / 'black_ops_3/reference/bo3_reference.json').read_text())
        names = {material['name'] for material in data['materials']}
        required = {'clip', 'mantle_on', 'mantle_over', 'ladder', 'mount', 'volume', 'nodraw_notsolid'}
        if not required.issubset(names):
            raise ValueError('BO3 catalogue missing: ' + ', '.join(sorted(required - names)))
        return dict(materials=len(names))

    check('bo3_material_catalogue', catalogue)
    # These are the entry points actually launched by the native terrain exporter.
    for helper in ('shared/capture/organize_export.py', 'shared/capture/finalize_research_capture.py'):
        def help_check(helper=helper):
            path = bundle / helper
            result = subprocess.run([sys.executable, '-I', str(path), '--help'],
                                    capture_output=True, text=True, timeout=30)
            if result.returncode:
                raise ValueError(result.stderr.strip() or result.stdout.strip())
            return str(path)
        check(helper, help_check)
    return dict(schema='greyhound-runtime-check-v1',
                status='passed' if all(row['passed'] for row in checks) else 'failed',
                bundle=str(bundle), python=sys.executable, checks=checks,
                scope='Installed files, imports, catalogue and helper entry points. Live capture and BO3 compilation are not exercised.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = verify(TOOLS_ROOT)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report))
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
