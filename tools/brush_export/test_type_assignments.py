"""Integration regressions using a verified native capture (developer check)."""
import argparse
import copy
import json
from pathlib import Path
import sys
import tempfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / 'pipeline'))
from assign_cw_bo3_types import build_assignments


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capture', required=True, type=Path)
    parser.add_argument('--normalized', required=True, type=Path)
    args = parser.parse_args()
    reference = json.loads((HERE / 'bo3_reference.json').read_text())
    report = build_assignments(args.normalized, args.capture, reference)
    brushes = report['brushes'].values()
    assert report['summary']['unique_brushes'] > 0
    by_name = {m['name']: m for m in reference['materials']}
    tool_images={i['name']:i for i in reference.get('tool_images',[])}
    assert {'nodraw','nodraw_nonsolid','nodraw_decal'} <= tool_images.keys()
    assert 'mantleOn' in reference['material_property_reference']['surfaceClimbType']
    for brush in brushes:
        decision = brush['decision']
        assert decision['source_line'] == by_name[decision['material']]['line']
        if decision['material'].startswith('clip_slick'):
            assert brush['filter_association'] == 'pointer_backed_union_verified'
            assert brush['uniform_surface_flags'] and 'slick' in brush['common_surface_flags']
        if not brush['named_contents'] and decision['selection_policy']!='basic_named_tool':
            assert decision['status'] == 'REVIEW_EXISTING_FALLBACK'
        if decision['status'] == 'EXACT_NAMED_PROPERTIES':
            assert not any(decision[k] for k in ('added_contents', 'omitted_contents',
                                                'added_surface_flags', 'omitted_surface_flags'))
        if brush['filter_association'] == 'unresolved_global_filter_association':
            assert brush['common_surface_flags'] is None
        if 'mount' in brush['named_contents'] and not brush['traversal']['name']:
            assert decision['material']=='mount'
            assert decision['status']!='REVIEW_EXISTING_FALLBACK'
        if brush['named_contents']:
            assert decision['status']!='REVIEW_EXISTING_FALLBACK'
    source = json.loads((args.capture / 'brush_type_capture.json').read_text())
    with tempfile.TemporaryDirectory(prefix='greyhound-type-check-') as temporary:
        native = Path(temporary)
        for kind in ('wrong_map', 'changed_readback'):
            altered = copy.deepcopy(source)
            if kind == 'wrong_map':
                altered['map_hash'] = hex(int(altered['map_hash'], 16) ^ 1)
            else:
                altered['readback_unchanged'] = False
            (native / 'brush_type_capture.json').write_text(json.dumps(altered))
            try:
                build_assignments(args.normalized, native, reference)
            except ValueError:
                pass
            else:
                raise AssertionError(f'Accepted {kind}')
    print(json.dumps(dict(status='passed', summary=report['summary'],
        checks=['stock reference provenance', 'positive slick evidence',
                'zero/unknown contents fallback', 'exact property differences',
                'unresolved filter association', 'wrong-map rejection', 'unstable-readback rejection',
                'tool image and climb references', 'mount applies even without a joined surface table',
                'known behavior never replaced by legacy fallback'])))


if __name__ == '__main__':
    main()
