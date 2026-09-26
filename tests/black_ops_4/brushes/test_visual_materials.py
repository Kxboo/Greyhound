"""Source UV and material publication never substitutes a clip or stock texture."""
import json
from pathlib import Path
import re
import sys

import numpy as np
from PIL import Image
import pytest

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'tools'))
import tool_bootstrap
tool_bootstrap.activate(ROOT/'tools/tool_bootstrap.py')
from bo4_brush_visual_materials import VisualResolver, load_visuals, _validate_materials, _verify_prefab


def material(tmp_path):
    info=tmp_path/'_mat_info';info.mkdir(exist_ok=True)
    (info/'source_wall.txt').write_text('Name: wc/source_wall\nsemantic,image_name\n0xA0AB1041,color\n')
    images=tmp_path/'_images'/'source_wall';images.mkdir(parents=True,exist_ok=True)
    Image.new('RGBA',(32,16),(25,50,75,255)).save(images/'color.png')
    return dict(status='complete',name_resolved=True,identity_proven=True,source_name='wc/source_wall',material='source_wall',hash='0x123',
                texture_size=[32,16],metadata_file='_mat_info/source_wall.txt',images=[dict(semantic='0xA0AB1041',file='_images/source_wall/color.png',binding_uv_scale=[1,1],binding_offset_u16_raw=[0,0,0])])


def resolver(tmp_path,owner=0):
    positions=np.array([[0,0,0],[64,0,0],[64,64,0],[0,64,0.]])
    uv=np.array([[.25,.5],[1.25,.5],[1.25,1.5],[.25,1.5]])
    return VisualResolver(positions,uv,[[0,1,2],[0,2,3]],[owner,owner],[0,0],[0,0],[material(tmp_path)],'0x42')


def test_explicit_uv_material_dependency_publication(tmp_path):
    r=resolver(tmp_path)
    report=r.publish_patches(tmp_path,'fixture',[])
    assert report['summary']['exported_triangles']==2
    assert report['summary']['patches']==6 and report['geometry_verified']
    prefab=next(iter(report['prefabs'].values()))
    assert prefab['geometry_kind']=='explicit_uv_patch'
    text=(tmp_path/prefab['file']).read_text()
    assert '\nsource_wall\n' in text and 'contents nonColliding;' in text
    assert '64 64 0 0 0 0' not in text
    actual={tuple(map(float,p.split())):tuple(map(float,uv.split()[:2])) for p,uv in re.findall(r'^v (.*?) c .*? t (.*)$',text,re.M)}
    for position,uv in zip(r.positions,r.uv):assert actual[tuple(position)]==tuple(uv*[32,16])
    assert set(report['embedded_data'])=={'_mat_info/source_wall.txt','_images/source_wall/color.png'}


@pytest.mark.parametrize('change,reason',[
    ('missing','dependency_validation_failed'),('dimensions','dependency_validation_failed'),
    ('unresolved','original_material_name_unresolved')])
def test_dependency_failures_publish_no_substitute(tmp_path,change,reason):
    r=resolver(tmp_path);m=r.materials[0]
    if change=='missing':(tmp_path/m['images'][0]['file']).unlink()
    elif change=='dimensions':m['texture_size']=[128,64]
    else:m.update(status='unresolved',name_resolved=False,reason=reason)
    _validate_materials(r.materials,tmp_path)
    report=r.publish_patches(tmp_path,'fixture',[])
    assert report['summary']['exported_triangles']==0 and not report['prefabs']
    assert reason in report['omissions'][0]['reason']


@pytest.mark.parametrize('variant',['missing','scaled','offset'])
def test_unknown_or_nonidentity_diffuse_binding_is_not_claimed_faithful(tmp_path,variant):
    r=resolver(tmp_path);image=r.materials[0]['images'][0]
    if variant=='missing':image.pop('binding_uv_scale')
    elif variant=='scaled':image['binding_uv_scale']=[2,1]
    else:image['binding_offset_u16_raw']=[16,0,0]
    _validate_materials(r.materials,tmp_path)
    assert r.materials[0]['status']=='unresolved'
    assert not r.publish_patches(tmp_path,'fixture',[])['prefabs']


def test_unnamed_original_hash_alias_preserves_genuine_material_and_images(tmp_path):
    r=resolver(tmp_path);m=r.materials[0]
    m.update(name_resolved=False,source_name='',source_hash_alias=True,material='source_material_123')
    _validate_materials(r.materials,tmp_path)
    assert m['status']=='complete' and not m['name_resolved']
    report=r.publish_patches(tmp_path,'fixture',[])
    assert report['summary']['exported_triangles']==2
    text=(tmp_path/next(iter(report['prefabs']))).read_text()
    assert '\nsource_material_123\n' in text


@pytest.mark.parametrize('variant',['unknown_hash','unproven_identity','wrong_alias','missing_image'])
def test_source_hash_alias_is_not_a_generic_fallback(tmp_path,variant):
    r=resolver(tmp_path);m=r.materials[0]
    m.update(name_resolved=False,source_name='',source_hash_alias=True,material='source_material_123')
    if variant=='unknown_hash':m['hash']='unknown'
    elif variant=='unproven_identity':m['identity_proven']=False
    elif variant=='wrong_alias':m['material']='some_stock_material'
    else:(tmp_path/m['images'][0]['file']).unlink()
    _validate_materials(r.materials,tmp_path)
    assert m['status']=='unresolved'
    assert not r.publish_patches(tmp_path,'fixture',[])['prefabs']


def test_same_owner_full_coverage_face_proof_and_counterexamples(tmp_path):
    r=resolver(tmp_path);planes=[[0,0,1,0]]
    good=r.resolve_brush(0,0,r.positions,planes)
    assert good['status']=='proven'
    assert np.allclose(good['faces'][0]['uv_affine']['u'],[1/64,0,0,.25])
    assert r.resolve_brush(0,1,r.positions,planes)['status']=='unresolved'
    assert r.resolve_brush(0,0,r.positions+[0,0,.1],[[0,0,1,.1]])['status']=='unresolved'
    r.material_ids[1]=1;r.materials.append(dict(r.materials[0],hash='0x124',material='other'))
    assert r.resolve_brush(0,0,r.positions,planes)['faces'][0]['reason']=='multiple_original_materials_cover_face'


def test_inline_rotation_is_explicitly_unresolved(tmp_path):
    r=resolver(tmp_path,owner=1)
    report=r.publish_patches(tmp_path,'fixture',[dict(index=4,model_index=1,origin=[2,3,4],angles=[0,90,0],placement_crosscheck='agrees')])
    assert not report['prefabs']
    assert report['omissions'][0]['reason']=='inline_rotation_convention_not_verified'


def test_inline_translation_preserves_uv(tmp_path):
    r=resolver(tmp_path,owner=1)
    report=r.publish_patches(tmp_path,'fixture',[dict(index=4,model_index=1,origin=[2,3,4],angles=[0,0,0],placement_crosscheck='agrees')])
    assert report['summary']['exported_triangles']==2
    text=(tmp_path/next(iter(report['prefabs']))).read_text()
    assert 'v 2 3 4 c 255 255 255 255 t 8 8 ' in text


@pytest.mark.parametrize('angles',[[0,float('nan'),0],[],[0,0]])
def test_invalid_inline_angles_cannot_pass_as_zero(tmp_path,angles):
    r=resolver(tmp_path,owner=1)
    report=r.publish_patches(tmp_path,'fixture',[dict(index=4,model_index=1,origin=[2,3,4],angles=angles,placement_crosscheck='agrees')])
    assert not report['prefabs']


@pytest.mark.parametrize('replacement',['source_other','t 99 8 '])
def test_saved_output_verification_rejects_material_or_uv_tampering(tmp_path,replacement):
    r=resolver(tmp_path);report=r.publish_patches(tmp_path,'fixture',[])
    path=tmp_path/next(iter(report['prefabs']))
    text=path.read_text()
    text=text.replace('source_wall',replacement,1) if replacement=='source_other' else text.replace('t 8 8 ',replacement,1)
    path.write_text(text)
    with pytest.raises(ValueError,match='material|UV'):_verify_prefab(path,r,np.zeros(3),[0,1])


def test_native_array_capture_validation_and_missing_dependency(tmp_path):
    r=resolver(tmp_path);folder=tmp_path/'diagnostics'/'render';folder.mkdir(parents=True)
    attrs=np.zeros((4,5),dtype='<u4');attrs[:,0]=0xffffffff;attrs[:,1:3]=r.uv.astype('<f4').view('<u4')
    surface=np.zeros((1,24),dtype='<u4');surface[0,9]=2<<16;surface[0,18]=0x10000
    surface.view('<f4')[0,12:18]=[0,0,0,64,64,0]
    brushes=np.zeros((1,20),dtype='<u4');brushes[0,18]=1
    arrays={}
    for name,data,stride in [('positions',r.positions.astype('<f4'),12),('attributes',attrs,20),('indices',r.triangles.astype('<u2').ravel(),2),('surfaces',surface,96),('brush_models',brushes,80)]:
        raw=data.tobytes();(folder/(name+'.bin')).write_bytes(raw)
        arrays[name]=dict(file=name+'.bin',count=len(raw)//stride,stride=stride,status='captured_stable')
    mat=r.materials[0];mat['pointer']='0x10000';mat['bindings_file']='bindings.bin'
    mat['images'][0]['pointer']='0x20000'
    import struct
    bindings=bytearray(32);struct.pack_into('<QI2f',bindings,0,0x20000,0xA0AB1041,1,1)
    (folder/'bindings.bin').write_bytes(bindings)
    doc=dict(schema='bo4-brush-render-capture-v1',status='captured',map_hash='0x42',arrays=arrays,materials=[mat])
    (folder/'render_capture.json').write_text(json.dumps(doc))
    loaded=load_visuals(folder.parent)
    assert np.array_equal(loaded.triangles,r.triangles)
    assert loaded.materials[0]['status']=='complete'
    (tmp_path/mat['images'][0]['file']).unlink()
    loaded=load_visuals(folder.parent)
    assert loaded.materials[0]['status']=='unresolved'
    surface[0,10]=1;(folder/'surfaces.bin').write_bytes(surface.tobytes())
    with pytest.raises(ValueError,match='partition'):load_visuals(folder.parent)
