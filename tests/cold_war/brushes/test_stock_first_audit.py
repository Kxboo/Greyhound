
import sys as _tool_sys
from pathlib import Path as _ToolPath
REPO_ROOT = next(p for p in _ToolPath(__file__).resolve().parents if (p / "build-greyhound.ps1").is_file())
TOOLS_ROOT = REPO_ROOT / "tools"
_tool_sys.path.insert(0, str(TOOLS_ROOT))
import tool_bootstrap as _tool_bootstrap
_tool_bootstrap.activate(TOOLS_ROOT / "tool_bootstrap.py")
from copy import deepcopy
from pathlib import Path
import sys

from audit_stock_first import audit


def fixture():
    flags=[dict(name='noDraw',field_12='0x80',field_16='0'),
           dict(name='playerClip',field_12='0',field_16='0x10000')]
    reference=dict(material_property_reference=dict(fields=[dict(name=f['name']) for f in flags],
                    surfaceType=['metal'],surfaceClimbType=['<none>']),
                   materials=[dict(name='metal_clip_player',source='clip.gdt',line=1,
                       properties=dict(noDraw='1',playerClip='1',surfaceType='metal',surfaceClimbType='<none>'))])
    brush=dict(filter_association='pointer_backed_union_verified',side_filter_indices=[0]*6,
               contents_raw='0x10000',unknown_contents='0x0',traversal=dict(name=None),
               decision=dict(material='metal_clip_player',status='CLOSEST_BO3_APPLIED',
                 added_contents=[],omitted_contents=[],added_surface_flags=[],omitted_surface_flags=[],
                 bo3_climb_type='<none>'))
    assignments=dict(map='test',named_flag_evidence=flags,traversal_enum_evidence=[],
                     surface_enum_evidence=[dict(name='metal',field_12='0xd00000',field_16='0')],
                     filter_entries=[dict(surface_raw='0xd00080',contents_raw='0x10000')],brushes={'0:0':brush})
    return assignments,reference


def test_exact_stock_match_prevents_custom_recipe():
    assignments,reference=fixture()
    row=audit(assignments,reference)['profiles'][0]
    assert row['status']=='stock_named_profile_available'
    assert row['stock_matches'][0]['name']=='metal_clip_player'
    assert row['recipe'] is None


def test_similar_stock_is_kept_when_one_recorded_property_differs():
    assignments,reference=fixture()
    assignments['filter_entries'][0]['surface_raw']='0xd00000'
    assignments['brushes']['0:0']['decision']['added_surface_flags']=['noDraw']
    row=audit(assignments,reference)['profiles'][0]
    assert row['status']=='similar_stock_preferred'
    assert row['stock_approximation']['added_surface_flags']==['noDraw']
    assert row['recipe'] is None


def test_unjoined_filter_ids_cannot_author_a_custom_material():
    assignments,reference=fixture()
    assignments['brushes']['0:0']['filter_association']='unresolved_global_filter_association'
    row=audit(assignments,reference)['profiles'][0]
    assert row['status']=='needs_source_decode'
    assert row['recipe'] is None


def test_mixed_sides_require_face_mapping_even_when_each_has_stock_match():
    assignments,reference=fixture()
    assignments['filter_entries'].append(dict(surface_raw='0xd00080',contents_raw='0'))
    assignments['brushes']['0:0']['side_filter_indices']=[0,1,0,1,0,1]
    row=audit(assignments,reference)['profiles'][0]
    assert row['status']=='needs_source_decode'
    assert 'Mixed side' in row['blockers'][0]
