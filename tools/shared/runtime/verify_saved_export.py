"""Read-only verification of published brush prefabs and sealed terrain captures."""

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
import importlib.util
import json
from pathlib import Path
import sys


def verify(report_path):
    report_path = Path(report_path).resolve()
    report = json.loads(report_path.read_text(encoding='utf-8-sig'))
    if report_path.name == 'research_capture.report.json':
        helper = TOOLS_ROOT / 'shared/capture/finalize_research_capture.py'
        spec = importlib.util.spec_from_file_location('terrain_inventory_verifier', helper)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        result = module.verify(report_path.parent)
        return dict(schema='greyhound-saved-export-check-v1', source=str(report_path),
                    status='passed' if result['integrity_ok'] else 'failed',
                    kind='terrain_inventory', result=result,
                    scope='Sealed source inventory integrity; no terrain reconstruction or live readback.')
    schema = report.get('schema', '')
    if not (schema.startswith('greyhound-cw-radiant-v') or schema == 'greyhound-bo4-brush-export-v1'):
        raise ValueError('Choose metadata/export_report.json from a Greyhound brush export, or research_capture.report.json from a sealed terrain capture.')
    root = report_path.parent.parent if report_path.parent.name == 'metadata' else report_path.parent
    prefabs = report.get('prefabs', {})
    if not prefabs:
        raise ValueError('Report contains no prefab inventory')
    embedded = report.get('embedded_data', {})
    if schema in ('greyhound-cw-radiant-v7','greyhound-cw-radiant-v8','greyhound-cw-radiant-v9','greyhound-cw-radiant-v10','greyhound-cw-radiant-v11'):
        required = {'bo3_stock_reference.json', 'material_assignments.json', 'stock_material_audit.json'}
        if schema in ('greyhound-cw-radiant-v8','greyhound-cw-radiant-v9','greyhound-cw-radiant-v10','greyhound-cw-radiant-v11'):
            required.update({'STOCK_MATERIALS.md','CAPTURED_BRUSH_MATERIALS.md','BO3_RENDER_MATERIALS.md'})
        if schema in ('greyhound-cw-radiant-v9','greyhound-cw-radiant-v10','greyhound-cw-radiant-v11'):
            required.update({'brush_faces.jsonl','brush_face_audit.json','collision_metadata.json'})
        if schema == 'greyhound-cw-radiant-v11':
            required.add('render_transfer.json')
            transfer=report.get('texture_transfer',{})
            if transfer.get('status') not in ('verified_surfaces_exported','render_material_uv_associations_unavailable'):
                raise ValueError('Export omits texture transfer status')
            if transfer['status']=='verified_surfaces_exported':
                required.add('verified_render_surfaces.jsonl')
                if 'render_surfaces' not in prefabs:
                    raise ValueError('Export omits declared render surface prefab')
        if not required.issubset(embedded):
            raise ValueError('Export omits required embedded stock material data')
    checks = []
    for key, entry in [*prefabs.items(), *embedded.items()]:
        name = entry.get('file', key)
        item = dict(file=name, passed=False)
        try:
            path = (root / name).resolve()
            if not path.is_relative_to(root):
                raise ValueError('File reference escapes the export folder')
            expected = entry.get('sha256')
            if not isinstance(expected, str) or len(expected) != 64:
                raise ValueError('Published report has no valid SHA-256 for this prefab; integrity cannot be verified')
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if digest != expected:
                raise ValueError('File hash differs from the published inventory')
            item.update(passed=True, sha256=digest, bytes=path.stat().st_size)
        except (OSError, KeyError, ValueError) as error:
            item['error'] = str(error)
        checks.append(item)
    accepted = report.get('status') in ('exported', 'exported_with_review')
    return dict(schema='greyhound-saved-export-check-v1', source=str(report_path),
                status='passed' if accepted and all(row['passed'] for row in checks) else 'failed',
                kind='brush_prefab_inventory', export_status=report.get('status'), checks=checks,
                source_coverage=report.get('summary'), review=report.get('review', []),
                scope='Published prefab file integrity. Original omissions, geometry limits and BO3 gameplay equivalence are not resolved by this check.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.resolve() == args.input.resolve():
        parser.error('Verification output must differ from its source report')
    try:
        result = verify(args.input)
    except Exception as error:
        result = dict(schema='greyhound-saved-export-check-v1', source=str(args.input),
                      status='failed', error=str(error))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result))
    return 0 if result['status'] == 'passed' else 1


if __name__ == '__main__':
    sys.exit(main())
