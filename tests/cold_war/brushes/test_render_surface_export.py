"""Captured corner UVs survive publication; absent/foreign joins cannot be invented."""
import hashlib
import json
from pathlib import Path
import re
import sys

import pytest

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'tools'))
import tool_bootstrap
tool_bootstrap.activate(ROOT/'tools/tool_bootstrap.py')
from export_cw_render_surfaces import export


def fixture(tmp_path):
    normalized=tmp_path/'normalized';normalized.mkdir()
    (normalized/'capture.json').write_text('{"map":"fixture"}')
    digest=hashlib.sha256((normalized/'capture.json').read_bytes()).hexdigest()
    staged=tmp_path/'staged';staged.mkdir()
    (staged/'collision_metadata.json').write_text(json.dumps(dict(map='fixture',source_capture_sha256=digest,
        rows=[dict(collision_world=0,instance_index=7,collision_asset_index=2,brush_index=3)])))
    surface=dict(schema='brush-render-surface-v1',source_capture_sha256=digest,
        source_id=[0,7,2,3],association='verified',evidence='synthetic known UV surface',
        material='captured_wall',vertices=[[0,0,0],[64,0,0],[64,64,0],[0,64,0]],
        uv=[[.25,.5],[1.25,.5],[1.25,1.5],[.25,1.5]],texture_size=[1024,512])
    source=tmp_path/'surfaces.jsonl'
    return normalized,staged,surface,source


def test_missing_render_associations_are_explicit_without_fabricated_prefab(tmp_path):
    normalized,staged,_,_=fixture(tmp_path)
    report,prefabs,files=export(normalized,staged)
    assert report['status']=='render_material_uv_associations_unavailable'
    assert report['patches']==0 and not prefabs
    assert not list(staged.glob('*.map'))
    assert 'render_transfer.json' in files


def test_explicit_material_and_corner_uvs_are_preserved_as_noncolliding_patches(tmp_path):
    normalized,staged,surface,source=fixture(tmp_path)
    source.write_text(json.dumps(surface)+'\n')
    report,prefabs,files=export(normalized,staged,source)
    assert report['status']=='verified_surfaces_exported' and report['patches']==1
    text=(staged/prefabs['render_surfaces']['file']).read_text()
    assert 'contents nonColliding;' in text and '\ncaptured_wall\n' in text
    vertices=re.findall(r'^v (.*) c .* t (.*)$',text,re.M)
    actual={tuple(map(float,p.split())):tuple(map(float,uv.split()[:2])) for p,uv in vertices}
    expected={tuple(p):(uv[0]*1024,uv[1]*512) for p,uv in zip(surface['vertices'],surface['uv'])}
    assert actual==expected
    assert (staged/'verified_render_surfaces.jsonl').read_bytes()==source.read_bytes()
    for name,item in files.items():
        assert item['sha256']==hashlib.sha256((staged/name).read_bytes()).hexdigest()


@pytest.mark.parametrize('field,value', [('source_capture_sha256','wrong'),('source_id',[0,8,2,3]),
    ('association','guessed'),('evidence',''),('uv',[[float('nan'),0]]*4),('material','clip\n{')])
def test_invalid_or_unverified_surfaces_do_not_publish_a_render_map(tmp_path,field,value):
    normalized,staged,surface,source=fixture(tmp_path);surface[field]=value
    source.write_text(json.dumps(surface)+'\n')
    with pytest.raises(ValueError):export(normalized,staged,source)
    assert not list(staged.glob('*.map')) and not list(staged.glob('*.tmp'))


def test_triangles_keep_nondegenerate_patch_area_and_interpolated_uvs(tmp_path):
    normalized,staged,surface,source=fixture(tmp_path)
    surface['vertices']=surface['vertices'][:3];surface['uv']=surface['uv'][:3]
    source.write_text(json.dumps(surface)+'\n')
    report,prefabs,_=export(normalized,staged,source)
    text=(staged/prefabs['render_surfaces']['file']).read_text()
    assert report['patches']==3
    # Every serialized point remains on the known affine UV projection.
    for p,uv in re.findall(r'^v (.*) c .* t (.*)$',text,re.M):
        x,y,z=map(float,p.split());u,v=map(float,uv.split()[:2])
        assert z==0
        assert u==pytest.approx((x/64+.25)*1024)
        assert v==pytest.approx((y/64+.5)*512)
