"""Reconstruction must retain source volume, identity and final MAP planes."""
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'tools'))
import tool_bootstrap
tool_bootstrap.activate(ROOT / 'tools/tool_bootstrap.py')
from cw_brush_reconstruction import Solid, compact_partition, face_polygon, reconstruct_parts, write_face_audit
from cw_canonical_map_planes import CanonicalPlaneWriter
from export_cw_district_placements import rotation


def box(lo, hi):
    vertices = [[x,y,z] for x in [lo[0],hi[0]] for y in [lo[1],hi[1]] for z in [lo[2],hi[2]]]
    planes = [e for i,n in enumerate(np.eye(3)) for e in [np.r_[n,hi[i]],np.r_[-n,-lo[i]]]]
    return Solid.from_arrays(vertices, planes)


def test_convex_recombination_preserves_supplied_planes_volume_and_winding():
    parts = [box([0,0,0],[5,10,10]), box([5,0,0],[10,10,10])]
    solids, check = compact_partition(parts)
    assert len(solids) == 1 and check['merged']
    assert len(solids[0].planes) == 6 and solids[0].volume() == pytest.approx(1000)
    source = {tuple(e) for p in parts for e in p.planes}
    for e in solids[0].planes:
        assert tuple(e) in source
        poly, area = face_polygon(solids[0], e)
        assert area == pytest.approx(100)
        assert np.dot(np.cross(poly[1]-poly[0],poly[2]-poly[1]),e[:3]) > 0


@pytest.mark.parametrize('second', [([8,0,0],[10,10,10]), ([2,0,0],[10,2,10])])
def test_does_not_fill_gap_or_concavity(second):
    solids, check = compact_partition([box([0,0,0],[2,10,10]),box(*second)])
    assert len(solids) == 2 and not check['merged']


def test_noncertified_partitions_are_retained_and_unsafe_face_budget_rejected():
    solids = [box([0,0,0],[5,10,10]),box([5,0,0],[10,10,10])]
    parts = [(s.vertices,s.planes) for s in solids]
    kept, check = reconstruct_parts(parts, {'partitioned':True})
    assert kept is parts and not check['merged']
    kept, check = reconstruct_parts(parts, {'partitioned':True,'cuts':[{}],'tetrahedral_fallback_regions':[1]})
    assert kept is parts and not check['merged']
    merged, check = reconstruct_parts(parts, {'partitioned':True,'cuts':[{}]})
    assert len(merged) == 1 and check['original_pieces'] == 2
    with pytest.raises(ValueError, match='between 4 and 32'):
        reconstruct_parts(parts, {}, 64)


def fixture(tmp_path):
    geometry, staged, normalized = [tmp_path/name for name in ('geometry','final','normalized')]
    for p in (geometry/'hull-cache',staged,normalized): p.mkdir(parents=True)
    capture = normalized/'capture.json'
    capture.write_text(json.dumps(dict(models=[dict(payload=dict(sha256='payload'))])))
    digest = hashlib.sha256(capture.read_bytes()).hexdigest()
    (geometry/'hull-cache-policy.json').write_text(json.dumps(dict(capture_sha256=digest)))
    solid = box([0,0,0],[10,10,10])
    cert = dict(model_index=0,brush_index=0,partitioned=False)
    (geometry/'hull-cache/0_0.json').write_text(json.dumps(dict(payload_sha256='payload',certificate=cert,
        parts=[[solid.vertices.tolist(),solid.planes.tolist()]])))
    rows = []
    # Role splitting preserves global comments; ordinal within each file differs.
    for instance,material in enumerate(['clip','sky']):
        name = material+'.map'; pos = [1234.5,-4532.25,instance*100]
        q = [0.,0.,.38268343,.92387950]
        world = solid.transformed(rotation(q),2.54,pos)
        lines = CanonicalPlaneWriter().lines(world.planes,world.vertices.mean(0),material)
        (staged/name).write_text('iwmap 4\n{\n"classname" "worldspawn"\n// brush '+str(instance+20)+
            '\n{\ncontents detail;\n'+'\n'.join(lines)+'\n}\n}\n')
        rows.append(dict(collision_asset_index=0,brush_index=0,collision_world=0,instance_index=instance,
            partition_piece=0,position=pos,quaternion_xyzw=q,uniform_scale=2.54,prefab_file=name,
            prefab_brush_index=0,map_brush_index=instance+20,assigned_material=material,face_count=6,
            contents_low26='0x80'))
    (staged/'collision_metadata.json').write_text(json.dumps(dict(rows=rows,source_capture_sha256=digest,
        partition_certificates=[cert])))
    return geometry, staged


def test_final_audit_preserves_instances_sky_and_raw_quaternion(tmp_path):
    geometry, staged = fixture(tmp_path)
    report, files = write_face_audit(geometry,staged)
    assert report['counts']['faces'] == report['counts']['ordered_polygons'] == 12
    assert report['counts']['brushes'] == 2
    assert report['maximum']['float32_signed_distance_error'] < .01
    faces = [json.loads(l) for l in (staged/'brush_faces.jsonl').read_text().splitlines()]
    assert {f['source_id'][1] for f in faces} == {0,1}
    assert {f['material'] for f in faces} == {'clip','sky'}
    assert all(f['render_uv'] is None and f['prefab_brush_index'] == 0 for f in faces)
    for entry in files.values():
        assert hashlib.sha256((staged/Path(entry['file']).name).read_bytes()).hexdigest() == entry['sha256']


@pytest.mark.parametrize('damage', ['material','placement','cache','capture'])
def test_final_readback_rejects_mismatched_inputs(tmp_path, damage):
    geometry, staged = fixture(tmp_path)
    if damage == 'material':
        p = staged/'clip.map'; p.write_text(p.read_text().replace(' clip ',' caulk '))
    elif damage == 'placement':
        p = staged/'collision_metadata.json'; data = json.loads(p.read_text()); data['rows'][0]['position'][0] += 1
        p.write_text(json.dumps(data))
    elif damage == 'cache':
        p = geometry/'hull-cache/0_0.json'; data = json.loads(p.read_text()); data['payload_sha256'] = 'other'
        p.write_text(json.dumps(data))
    else:
        (geometry.parent/'normalized/capture.json').write_text('{}')
    with pytest.raises(ValueError): write_face_audit(geometry,staged)


def test_native_pipeline_recombines_certified_cuts_and_retains_two_placements(tmp_path, monkeypatch):
    import export_cw_radiant_brushes as exporter
    capture, output = tmp_path/'capture', tmp_path/'geometry'
    capture.mkdir(); payload = capture/'payload.bin'; payload.write_bytes(b'captured fixture')
    # A convex 14-sided prism requires the conservative 12-face split, but its
    # original exterior can safely fit in one reconstructed 32-face brush.
    vertices = [[100*np.cos(t),100*np.sin(t),z] for z in [-10,10]
                for t in np.arange(14)*2*np.pi/14]
    brush = dict(vertices=vertices,brush_index=0,collision_flags_raw=0x80,
                 packed_flags_and_plane_count=0x80,nonaxial_plane_count=14)
    monkeypatch.setattr(exporter,'decode_brushes',lambda *_: dict(status='decoded',brushes=[brush]))
    model = dict(status='decoded',index=0,brush_count=1,name_hash='0x42',
        payload=dict(file=payload.name,sha256=hashlib.sha256(payload.read_bytes()).hexdigest()),
        mins=np.min(vertices,axis=0).tolist(),maxs=np.max(vertices,axis=0).tolist())
    instances = [dict(model_index=0,quaternion_xyzw=[0,0,0,1],uniform_scale=1,
        position=[i*300,0,0],world_bounds_error=0,collision_world=0,instance_index=i,
        collision_pointer='0x123') for i in range(2)]
    (capture/'capture.json').write_text(json.dumps(dict(map='fixture',models=[model],instances=instances,
        summary=dict(unique_brushes=1,placed_brushes=2))))
    gdt = tmp_path/'tools.gdt'; gdt.write_text('{\n'+''.join('"'+name+'" ( "material.gdf" ) { "noDraw" "1" }\n'
        for name in set(exporter.CHOICES.values())|{'clip'})+'}\n')
    monkeypatch.setattr(sys,'argv',['export',str(capture),'--output',str(output),'--gdt',str(gdt),
        '--max-faces','12','--cleanup-world-tolerance','0.01','--halfspace-partitions',
        '--canonical-planes','--recombine-max-faces','32'])
    exporter.main()
    report = json.loads((output/'collision_metadata.json').read_text())
    assert report['summary']['output_brushes'] == 2
    assert report['reconstruction']['original_output_brushes'] > 2
    assert report['reconstruction']['recombined_placed_brushes'] == 2
    assert report['partition_policy']['max_faces'] == 32
    assert report['summary']['max_faces'] == 16
    assert len({row['instance_index'] for row in report['rows']}) == 2
    cert = report['partition_certificates'][0]
    assert not cert['partitioned'] and cert['pieces'] == 1 and cert['cuts']
    assert cert['reconstruction']['merged']
    assert json.loads((output/'hull-cache/0_0.json').read_text())['certificate'] == cert
