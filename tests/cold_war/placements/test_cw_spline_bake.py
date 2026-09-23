import importlib.util
import hashlib
import json
from pathlib import Path
import struct
import tempfile

import numpy as np
import pytest

ROOT=next(p for p in Path(__file__).resolve().parents if (p/'build-greyhound.ps1').is_file())
spec=importlib.util.spec_from_file_location('cw_spline_bake',ROOT/'tools/cold_war/placements/bake_cw_splines.py')
bake=importlib.util.module_from_spec(spec);spec.loader.exec_module(bake)


def fixture(axis=0,segments=1):
    f=np.zeros(25,dtype='<f4');f[0:2]=10;f[6]=f[12]=1;f[16:25]=np.eye(3).ravel()
    f.view('<u4')[9:12]=[0,segments,axis]
    g=np.zeros((segments,48),dtype='<f4')
    for i,s in enumerate(g):
        s[0]=i*10;s[1]=10;s[2]=i*10;s[5]=10;s[20]=10
        s[23:32]=s[32:41]=np.eye(3).ravel()
    return f,g


@pytest.mark.parametrize('axis',range(6))
def test_all_axis_rotations_and_no_double_transform(axis):
    f,g=fixture(axis)
    vertices=np.array([[2,3,4],[-2,-3,1],[15,0,0]],float)
    actual=bake.Splines(f.tobytes(),g.tobytes()).deform(vertices,0)
    np.testing.assert_allclose(actual,vertices@bake.AXES[axis],atol=1e-12)


def test_cubic_before_start_linear_after_end_and_bank():
    f,g=fixture()
    # x=10t, y=2t^2. The derivative coefficients are in descending order.
    g[0,9]=2;g[0,18]=4
    s=bake.Splines(f.tobytes(),g.tobytes())
    v=np.array([[-5,0,0],[5,0,0],[15,0,0]])
    expected=np.array([[-5,.5,0],[5,.5,0],np.array([10,2,0])+5*np.array([10,4,0])/np.sqrt(116)])
    np.testing.assert_allclose(s.deform(v,0),expected)
    f,g=fixture();g[0,44]=np.pi/2
    actual=bake.Splines(f.tobytes(),g.tobytes()).deform([[5,2,3]],0)
    np.testing.assert_allclose(actual,[[5,3,-2]],atol=2e-7)


def test_segment_tie_uses_next_and_end_is_exclusive():
    f,g=fixture(segments=2);g[1,43]=7
    s=bake.Splines(f.tobytes(),g.tobytes())
    np.testing.assert_allclose(s.deform([[9,0,0],[10,0,0],[21,0,0]],0),[[9,0,0],[10,0,7],[21,0,7]])


def test_prefab_origin_scale_row_matrix_and_normal_jacobian():
    f,g=fixture();f[12]=2;f[13:16]=[1,2,3];f[16:25]=np.array([[0,1,0],[-1,0,0],[0,0,1]]).ravel()
    np.testing.assert_allclose(bake.Splines(f.tobytes(),g.tobytes()).deform([[2,3,4]],0),[[-5,6,11]])
    f,g=fixture();f[1]=20
    s=bake.Splines(f.tobytes(),g.tobytes())
    actual=s.normals(np.array([[2,3,4]],float),np.array([[1,1,0]])/np.sqrt(2),0)
    np.testing.assert_allclose(actual,np.array([[.5,1,0]])/np.sqrt(1.25),atol=1e-9)


def test_invalid_records_fail_explicitly():
    f,g=fixture()
    with pytest.raises(ValueError): bake.Splines(f.tobytes()[:-1],g.tobytes())
    for field,value in [(0,0),(6,0),(12,np.nan)]:
        bad=f.copy();bad[field]=value
        with pytest.raises(ValueError): bake.Splines(bad.tobytes(),g.tobytes()).deform([[0,0,0]],0)
    for indices in ([0,2,0],[0,1,6],[1,1,0]):
        bad=f.copy();bad.view('<u4')[9:12]=indices
        with pytest.raises(ValueError): bake.Splines(bad.tobytes(),g.tobytes()).deform([[0,0,0]],0)
    g[0,1]=0
    with pytest.raises(ValueError): bake.Splines(f.tobytes(),g.tobytes()).deform([[0,0,0]],0)


def prop(kind,value):
    if kind==b's': return kind,1,value.encode()+b'\0'
    dtype,width=bake.TYPES[kind];a=np.array(value,dtype=dtype)
    return kind,a.size//width,a.tobytes()


def cast_fixture():
    node=bake.CastNode
    mesh=node(b'mesh',11,{'vp':prop(b'3v',np.array([[0,0,0],[1,0,0],[0,1,0]])*bake.CAST_SCALE),
        'vn':prop(b'3v',[[0,0,1]]*3),'f':prop(b'h',[0,1,2]),'u0':prop(b'2v',[[0,0],[1,0],[0,1]]),
        'vc':prop(b'i',[0xffffffff]*3),'m':prop(b'l',[9]),'wb':prop(b'b',[0]*3),'wv':prop(b'f',[1]*3)},[])
    material=node(b'matl',9,{'n':prop(b's','test_material'),'albedo':prop(b'l',[14])},[
        node(b'file',14,{'p':prop(b's','_images/example.png')},[])])
    bone=node(b'bone',10,{'lp':prop(b'3v',[0,0,0]),'lr':prop(b'4v',[0,0,0,1])},[])
    roots=[node(b'root',1,{},[node(b'modl',2,{},[node(b'skel',3,{},[bone]),mesh,material])])]
    return struct.pack('<4sIII',b'cast',1,1,0)+b''.join(n.encode() for n in roots)


def test_cast_roundtrip_rejects_truncation_and_binary_winding_units():
    raw=cast_fixture();roots=bake.read_cast(raw)
    assert raw==raw[:16]+b''.join(n.encode() for n in roots)
    for broken in (raw[:10],raw[:-1],raw+b'\0'):
        with pytest.raises(ValueError):bake.read_cast(broken)
    with tempfile.TemporaryDirectory() as td:
        path=Path(td)/'test.xmodel_bin'
        report=bake.write_xmodel_bin(path,roots)
        assert report['readback_verified'] and report['material_references']==['test_material']
        assert report['cast_to_bo3_scale']==0.3937007874
        from cw_spline_binary import pycod
        decoded=pycod().Model.FromFile_Bin(str(path),split_meshes=False).meshes[0]
        # 2.54 CAST centimeters becomes one BO3 inch; UV V stays unchanged.
        np.testing.assert_allclose(decoded.verts[1].offset,[1,0,0],atol=1e-7)
        corners=decoded.faces[0].indices
        assert [v.vertex for v in corners]==[0,2,1]
        assert corners[1].normal==(0,0,1) and corners[1].uv==(0,1)
        assert not list(Path(td).glob('*.xmodel_export'))


def test_complete_bake_preserves_sources_and_places_recentered_geometry():
    with tempfile.TemporaryDirectory() as td:
        root=Path(td);capture=root/'capture';capture.mkdir();(capture/'splines').mkdir()
        f,g=fixture();g[0,41:44]=[100,200,300]
        (capture/'splines/instances.bin').write_bytes(f.tobytes());(capture/'splines/segments.bin').write_bytes(g.tobytes())
        (capture/'splined_models.json').write_text(json.dumps(dict(status='captured_source_data',instances=dict(readback_unchanged=True,stride=100,count=1),segments=dict(readback_unchanged=True,stride=192,count=1))))
        models=root/'source';(models/'test/_images').mkdir(parents=True);(models/'test/_mat_info').mkdir()
        (models/'test/_images/example.png').write_bytes(b'image fixture')
        (models/'test/_mat_info/test_images.txt').write_bytes(b'material fixture')
        source=models/'test/test.cast';source.write_bytes(cast_fixture());before=source.read_bytes()
        row=dict(Name='test',District=2,ReferenceIndex=3,SplineInstanceIndex=0,RequiresSplineDeformation=True,
            BoundsMin=dict(X=100,Y=200,Z=300),BoundsMax=dict(X=101,Y=201,Z=300))
        placements=root/'placements.json';placements.write_text(json.dumps([row]))
        out=root/'out';report=bake.bake(capture,placements,models,out)
        assert report['complete'] and report['exported']==1 and source.read_bytes()==before
        target=next(out.glob('*/*.cast'))
        mesh=next(n for r in bake.read_cast(target.read_bytes()) for n in r.walk() if n.ident==b'mesh')
        origin=np.array(report['records'][0]['origin'])
        expected=np.array([[100,200,300],[101,200,300],[100,201,300]])
        np.testing.assert_allclose(mesh.array('vp')/bake.CAST_SCALE+origin,expected,atol=1e-6)
        assert mesh.props['u0']==next(n for r in bake.read_cast(before) for n in r.walk() if n.ident==b'mesh').props['u0']
        assert json.loads((out/'placements.json').read_text())[0]['RequiresSplineDeformation'] is False
        file_node=next(n for r in bake.read_cast(target.read_bytes()) for n in r.walk() if n.ident==b'file')
        relative=file_node.props['p'][2].rstrip(b'\0').decode()
        assert (target.parent/relative).read_bytes()==b'image fixture'
        bo3=root/'bo3';destination=bo3/'_custom/kuboo/models/t9/splines'
        destination.mkdir(parents=True)
        (destination/'old.xmodel_bin').write_bytes(b'previous flat export')
        (destination/'spline_install_manifest.json').write_text(json.dumps(dict(
            schema='cw-spline-install-v1',destination=str(destination.resolve()),
            files={'old.xmodel_bin':hashlib.sha256(b'previous flat export').hexdigest()})))
        installed=bake.install_baked_models(out,destination,bo3)
        assert (Path(installed['previous_export'])/'old.xmodel_bin').read_bytes()==b'previous flat export'
        assert not (destination/'old.xmodel_bin').exists()
        assert installed['models']==1 and not list(destination.glob('*.xmodel_export'))
        assert not list(destination.glob('cwsp_*/*.xmodel_bin')) and not list(destination.glob('*.gdt'))
        name=report['records'][0]['name'];folder=destination/name
        assert (folder/(name+'.cast')).is_file()
        assert (folder/'_images/example.png').read_bytes()==b'image fixture'
        assert (folder/'_mat_info/test_images.txt').read_bytes()==b'material fixture'
        assert (destination/'placements.json').read_bytes()==(out/'placements.json').read_bytes()
        assert bake.install_baked_models(out,destination,bo3)['files']==installed['files']
        # A rerun preserves edited dependencies and preflights before any writing.
        (folder/'_mat_info/test_images.txt').write_text('user edit')
        model=folder/(name+'.cast');model.unlink()
        with pytest.raises(ValueError,match='user-modified/unowned'):
            bake.install_baked_models(out,destination,bo3)
        assert not model.exists() and (folder/'_mat_info/test_images.txt').read_text()=='user edit'
        report['complete']=False;(out/'bake_report.json').write_text(json.dumps(report))
        with pytest.raises(ValueError,match='complete, nonempty'):
            bake.install_baked_models(out,destination,bo3)
        with pytest.raises(ValueError): bake.bake(capture,placements,models,out)
        (capture/'splines/instances.bin').write_bytes(f.tobytes()*2)
        with pytest.raises(ValueError,match='counts/strides'): bake.bake(capture,placements,models,root/'bad')


def test_binary_multiple_surfaces_and_nontrivial_attributes(tmp_path):
    import copy
    from cw_spline_binary import pycod
    roots=bake.read_cast(cast_fixture())
    model=roots[0].children[0]
    mesh=next(n for n in model.children if n.ident==b'mesh')
    mesh.set_array('vn',np.tile(np.array([1,2,3])/np.sqrt(14),(3,1)))
    mesh.set_array('u0',[[.15,.3],[1.25,-.75],[.45,.6]])
    mesh.set_array('vc',[0xffcc6633,0x11223344,0xffffffff])
    second=copy.deepcopy(mesh);second.hash=12;second.set_array('m',[13])
    second.set_array('vp',second.array('vp')+[25.4,0,0])
    model.children.extend([second,bake.CastNode(b'matl',13,{'n':prop(b's','second_material')},[])])
    path=tmp_path/'test.xmodel_bin';report=bake.write_xmodel_bin(path,roots)
    decoded=pycod().Model.FromFile_Bin(str(path),split_meshes=False)
    assert report['vertices']==6 and report['triangles']==2 and report['readback_verified']
    assert [m.name for m in decoded.materials]==['test_material','second_material']
    assert [(f.mesh_id,f.material_id) for f in decoded.meshes[0].faces]==[(0,0),(1,1)]
    assert [v.vertex for v in decoded.meshes[0].faces[1].indices]==[3,5,4]
    np.testing.assert_allclose(decoded.meshes[0].verts[3].offset,[10,0,0],atol=1e-6)


def test_fold_normal_fallback_uses_original_vertex_splits():
    p=np.array([[0,0,0],[1,0,0],[0,1,0],[0,0,0],[0,1,0],[0,0,1]],float)
    normals,empty=bake.triangle_normals(p,[0,1,2,3,4,5],np.array([[0,0,1]]*6))
    np.testing.assert_allclose(normals,[[0,0,1]]*3+[[1,0,0]]*3)
    assert empty==0


def test_packed_source_span_and_truncation():
    with tempfile.TemporaryDirectory() as td:
        root=Path(td);(root/'packed.bin').write_bytes(b'HEADpayloadTAIL')
        (root/'evidence.json').write_text(json.dumps(dict(storage={'splines/instances.bin':dict(file='packed.bin',offset=4,bytes=7)})))
        assert bake.read_span(root,'splines/instances.bin')==b'payload'
        # A truncated physical file must not satisfy the logical span.
        (root/'packed.bin').write_bytes(b'HEADshort')
        with pytest.raises(ValueError,match='Truncated'):bake.read_span(root,'splines/instances.bin')
