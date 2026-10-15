"""Synthetic end-to-end checks for source/native terrain export (no game assets)."""
import json
from pathlib import Path
import sys
import numpy as np
from PIL import Image
import pytest
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'build-greyhound.ps1').is_file())
sys.path.insert(0,str(ROOT/'tools/black_ops_4/capture'))
from export_terrain import export
from export_baked_terrain import plan
sys.path.insert(0,str(ROOT/'tools/cold_war/placements'))
from bake_cw_splines import read_cast

def fixture(root):
    (root/'capture').mkdir(parents=True)
    (root/'materials/images').mkdir(parents=True)
    np.arange(36*36,dtype='<u2').reshape(36,36).tofile(root/'capture/height.bin')
    np.full((9,5),0xffffffff,'<u4').tofile(root/'capture/cutout.bin')
    (root/'capture/weights.bin').write_bytes(bytes([128,128,0,0,0,0,0,0])*81)
    materials=[]
    for name in ['base','top']:
        Image.new('RGBA',(4,4),(20,60,90,128)).save(root/f'materials/images/{name}.png')
        materials.append({'name':'mc/'+name,'bindings':[{'png_file':f'materials/images/{name}.png','role':'color','semantic':'colorMap','engine_semantic':'colorMap','asset_name':name,'exported_size':[4,4]}]})
    sector={'sector':0,'grid_samples':33,'tiles_across':1,'units_per_sample':1,'world_xy_origin':[0,0],'world_height_bias':0,'local_height_bias':0,'placement':[16,16,0,1],
        'height':{'file':'capture/height.bin','format':'R16_UNORM_LE','width':36,'height':36,'scale':.01},
        'cutout':{'file':'capture/cutout.bin','format':'R32_UINT_LE','width':5,'height':9,'packing':'x8_y4_lsb_first','set_bit':'solid'},
        'layer_weights':{'file':'capture/weights.bin','format':'BC4_UNORM','width':36,'height':36,'storage':'slice_major','slices':1,'base_layer':0,'slice_to_layer_slot':[1],'independent_fields':True,'normalization_applied':False},
        'layers':[{'slot':i,'material':m['name'],'weight_slice':i-1 if i else None,'uv_matrix_2x4':[.125,0,0,0,0,-.125,0,0]} for i,m in enumerate(materials)]}
    doc={'schema':'superterrain-bo4-source-package-v1','path_base':'package root (parent of capture)','materials':materials,'sectors':[sector]}
    (root/'capture/terraingfx.json').write_text(json.dumps(doc))
    return root

def test_source_is_unchanged_and_has_no_models(tmp_path):
    source=fixture(tmp_path/'input');out=tmp_path/'output'
    result=export(source,out,'source')
    assert result['mode']=='source' and not (out/'models').exists()
    for p in source.rglob('*'):
        if p.is_file():assert (out/'package'/p.relative_to(source)).read_bytes()==p.read_bytes()

def test_native_preserves_material_names_images_uvs_and_alpha(tmp_path):
    source=fixture(tmp_path/'input');out=tmp_path/'output'
    report=export(source,out,'native');assert report['model_count']==1 and not report['textures_baked']
    row=report['models'][0];assert set(row['materials'])=={'mc/base','mc/top_blend'}
    for n in ['base','top']:assert (source/f'materials/images/{n}.png').read_bytes()==(out/f'models/_images/{n}.png').read_bytes()
    model=read_cast((out/'models'/(row['name']+'.cast')).read_bytes())[0].children[0]
    mats={n.hash:n.props['n'][2].rstrip(b'\0').decode() for n in model.children if n.ident==b'matl'}
    meshes=[n for n in model.children if n.ident==b'mesh']
    for mesh in meshes:
        name=mats[int(mesh.array('m')[0])]
        assert np.all(mesh.array('vc')>>24==(255 if name=='mc/base' else 128))
        xyz=mesh.array('vp')/2.54;uv=mesh.array('u0')
        np.testing.assert_allclose(uv[:,0],xyz[:,0]*.125,atol=1e-6)
        np.testing.assert_allclose(uv[:,1],-xyz[:,1]*.125,atol=1e-6)
    text=(out/'models/_mat_info'/(row['name']+'.txt')).read_text()
    assert 'Name: mc/top_blend' in text and 'colorMap,top' in text
    assert not list(out.glob('*patch*.map')) and not list(out.glob('*collision*.map'))

def test_reject_existing_output_and_recursive_copy(tmp_path):
    source=fixture(tmp_path/'input');out=tmp_path/'output'
    export(source,out,'source')
    with pytest.raises(ValueError,match='new export'):export(source,out,'source')
    with pytest.raises(ValueError,match='outside'):export(source,source/'nested','source')

def test_baked_dispatch_and_1024_limit(tmp_path,monkeypatch):
    import export_terrain
    probe=tmp_path/'probe.json';probe.write_text('{}');calls=[]
    monkeypatch.setattr(export_terrain,'bake',lambda *a,**k:calls.append((a,k)) or {'mode':'baked'})
    assert export(probe,tmp_path/'out','baked')['mode']=='baked'
    assert calls[0][1]['max_models']==4096
    folder=tmp_path/'package/capture/sectors/sector_0';folder.mkdir(parents=True)
    (folder/'sector.json').write_text(json.dumps({'sector':0,'grid_samples':257,'units_per_sample':32,'world_xy_origin':[0,0]}))
    jobs=plan(tmp_path/'package',128,.5,64)
    assert all((j['box'][2]-j['box'][0])*.5<=1024 for j in jobs)
