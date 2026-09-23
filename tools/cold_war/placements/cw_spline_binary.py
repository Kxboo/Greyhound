"""Direct static XMODEL_BIN output and verified BO3 spline-folder installation."""
from __future__ import annotations

from functools import lru_cache
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile

import numpy as np

CAST_TO_BO3 = 0.3937007874


@lru_cache(maxsize=1)
def pycod():
    tools=next(p for p in Path(__file__).resolve().parents if (p/'tool_bootstrap.py').is_file())
    package=tools/'shared/models/pycod'
    name='_greyhound_spline_pycod'
    spec=importlib.util.spec_from_file_location(name,package/'__init__.py',submodule_search_locations=[str(package)])
    module=importlib.util.module_from_spec(spec)
    sys.modules[name]=module
    spec.loader.exec_module(module)
    return sys.modules[name+'.xmodel']


def write_xmodel_bin(path, roots):
    """Use the add-on's unchanged PyCoD writer without a text intermediate."""
    X=pycod()
    nodes=[n for root in roots for n in root.walk()]
    meshes=[n for n in nodes if n.ident==b'mesh']
    materials={n.hash:n.props['n'][2].rstrip(b'\0').decode('utf8') for n in nodes if n.ident==b'matl'}
    used=list(dict.fromkeys(int(m.array('m')[0]) for m in meshes))
    names=[materials[k] for k in used]
    vertex_count=sum(len(m.array('vp')) for m in meshes)
    if not 0 < vertex_count <= 65535:
        raise ValueError('Version 6 XMODEL_BIN requires 1..65535 vertices per model')
    if len(meshes)>255 or len(names)>255:
        raise ValueError('Version 6 mesh/material count limit exceeded')
    model=X.Model(path.stem)
    bone=X.Bone('tag_origin',-1);bone.offset=(0,0,0);bone.matrix=[(1,0,0),(0,1,0),(0,0,1)]
    model.bones.append(bone)
    model.materials=[X.Material(name,'Lambert',{}) for name in names]
    for mi,source in enumerate(meshes):
        mesh=X.Mesh(f'SplineMesh_{mi}')
        positions=source.array('vp').astype(float)*CAST_TO_BO3
        normals=source.array('vn');uvs=source.array('u0');colors=source.array('vc')
        mesh.verts=[X.Vertex(tuple(p),[(0,1.0)]) for p in positions]
        mat=used.index(int(source.array('m')[0]))
        # Blender's CAST importer flips V, and the CoD exporter flips it back.
        # CAST -> CoD directly therefore retains UVs and swaps winding once.
        for indices in source.array('f').reshape(-1,3)[:,[0,2,1]]:
            face=X.Face(mi,mat)
            face.indices=[X.FaceVertex(int(v),tuple(map(float,normals[v])),
                tuple(((int(colors[v])>>shift)&255)/255 for shift in (0,8,16,24)),
                tuple(map(float,uvs[v]))) for v in indices]
            mesh.faces.append(face)
        model.meshes.append(mesh)
    model.WriteFile_Bin(str(path),version=6,header_message='Greyhound static CW spline bake; game inches')
    check=X.Model.FromFile_Bin(str(path),split_meshes=False)
    if check.version!=6 or [m.name for m in check.materials]!=names:
        raise ValueError('Binary version/material readback mismatch')
    if len(check.bones)!=1 or check.bones[0].parent!=-1 or check.bones[0].offset!=(0,0,0):
        raise ValueError('Binary root-bone readback mismatch')
    decoded=check.meshes[0]
    vertices=[v for mesh in model.meshes for v in mesh.verts]
    if len(decoded.verts)!=len(vertices) or any(v.weights!=[(0,1.0)] for v in decoded.verts):
        raise ValueError('Binary vertex/weight readback mismatch')
    positions=np.asarray([v.offset for v in vertices])
    actual=np.asarray([v.offset for v in decoded.verts])
    error=float(np.max(np.abs(actual-positions)))
    if not np.isfinite(actual).all() or not np.array_equal(actual,positions.astype('<f4').astype(float)):
        raise ValueError('Binary position readback differs from expected float32 encoding')
    offset=0;faces=[];indices=[]
    for mesh in model.meshes:
        for face in mesh.faces:
            faces.append(face);indices.append([v.vertex+offset for v in face.indices])
        offset+=len(mesh.verts)
    if len(decoded.faces)!=len(faces): raise ValueError('Binary face count mismatch')
    if not np.array_equal([[v.vertex for v in f.indices] for f in decoded.faces],indices):
        raise ValueError('Binary topology/winding mismatch')
    if [(f.mesh_id,f.material_id) for f in decoded.faces]!=[(f.mesh_id,f.material_id) for f in faces]:
        raise ValueError('Binary surface/material assignment mismatch')
    before=[v for f in faces for v in f.indices];after=[v for f in decoded.faces for v in f.indices]
    normal_error=float(np.max(np.abs(np.array([v.normal for v in after])-np.array([v.normal for v in before]))))
    if normal_error>1/32767+1e-7: raise ValueError('Binary normal readback exceeds quantization tolerance')
    if not np.array_equal(np.array([v.uv for v in after]),np.array([v.uv for v in before],dtype='<f4').astype(float)):
        raise ValueError('Binary UV readback mismatch')
    if np.max(np.abs(np.array([v.color for v in after])-np.array([v.color for v in before])))>1/255+1e-7:
        raise ValueError('Binary color readback mismatch')
    return dict(file=path.name,sha256=hashlib.sha256(path.read_bytes()).hexdigest(),version=6,
                material_references=names,vertices=vertex_count,triangles=len(faces),readback_verified=True,
                cast_to_bo3_scale=CAST_TO_BO3,
                position_quantization_max=error,normal_quantization_max=normal_error)


def install_baked_models(source, destination, bo3):
    """Install self-contained model folders; preserve edits and archive old layouts."""
    source=source.resolve();destination=destination.resolve();bo3=bo3.resolve()
    custom=bo3/'_custom'
    if destination==custom or not destination.is_relative_to(custom):
        raise ValueError('Installation must be in a folder beneath the specified BO3 _custom directory')
    if destination.is_relative_to(source) or source.is_relative_to(destination):
        raise ValueError('Installation and source bake must be separate folders')
    report=json.loads((source/'bake_report.json').read_text(encoding='utf8'))
    if not report['complete'] or report['exported']!=report['requested'] or not report['records']:
        raise ValueError('Only a complete, nonempty bake may be installed')
    if report.get('layout')!='per_model_images_mat_info':
        raise ValueError('Rebake using the per-model dependency layout before installing')

    def contained(root, relative):
        path=root/relative
        if not relative or Path(relative).is_absolute() or '..' in Path(relative).parts or not path.resolve().is_relative_to(root):
            raise ValueError('Invalid package/manifest path')
        return path

    files={};hashes={};names=[]
    for record in report['records']:
        name=record['name'];binary=record.get('binary') or {}
        if not re.fullmatch(r'[a-z0-9_]+',name) or record.get('directory')!=name:
            raise ValueError('Invalid model folder identity')
        if name in names: raise ValueError('Duplicate model identity')
        names.append(name)
        filename=name+'.xmodel_bin'
        if binary and (binary.get('file')!=filename or not binary.get('readback_verified')):
            raise ValueError('Model has no verified binary output')
        inventory=record['files']
        if binary and inventory.get(filename)!=binary['sha256']:
            raise ValueError('Binary inventory mismatch')
        if inventory.get(name+'.cast')!=record['output_sha256']:
            raise ValueError('CAST inventory mismatch')
        for folder in ('_images','_mat_info'):
            if not (source/name/folder).is_dir(): raise ValueError('Missing model dependency folder')
        for relative,digest in inventory.items():
            key=name+'/'+relative;path=contained(source,key)
            if hashlib.sha256(path.read_bytes()).hexdigest()!=digest:
                raise ValueError(f'Model file changed after verification: {key}')
            files[key]=path;hashes[key]=digest
    placements=json.loads((source/'placements.json').read_text(encoding='utf8'))
    if [r['Name'] for r in placements]!=names: raise ValueError('Placement/binary identities differ')
    for name in ('placements.json','spline_models_REVIEW.map','spline_export_report.json'):
        if name!='placements.json' and not (source/name).is_file(): continue
        files[name]=source/name;hashes[name]=hashlib.sha256(files[name].read_bytes()).hexdigest()
    manifest_name='spline_install_manifest.json';old={}
    manifest_path=destination/manifest_name
    if manifest_path.exists():
        existing=json.loads(manifest_path.read_text(encoding='utf8'))
        if existing.get('schema') not in ('cw-spline-install-v1','cw-spline-install-v2') or existing.get('destination')!=str(destination):
            raise ValueError('Unrecognized spline installation manifest')
        old=existing['files']
    # Validate every old and new destination before changing any files.
    for name in set(old)|set(files):
        target=contained(destination,name)
        if target.exists():
            current=hashlib.sha256(target.read_bytes()).hexdigest()
            if current!=hashes.get(name) and current!=old.get(name):
                raise ValueError(f'Existing user-modified/unowned file: {target}')
    manifest=dict(schema='cw-spline-install-v2',layout='per_model_images_mat_info',source=str(source),
        destination=str(destination),bo3_root=str(bo3),models=len(names),asset_names=names,
        files=hashes,game_compilation_run=False)
    destination.mkdir(parents=True,exist_ok=True)
    for name in names:
        for folder in ('_images','_mat_info'):
            (destination/name/folder).mkdir(parents=True,exist_ok=True)
    for name,path in files.items():
        target=contained(destination,name);target.parent.mkdir(parents=True,exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=target.parent,prefix='.spline-',delete=False) as f:
            temporary=Path(f.name)
        try:
            shutil.copyfile(path,temporary);os.replace(temporary,target)
        finally:
            if temporary.exists(): temporary.unlink()
    if any(hashlib.sha256((destination/n).read_bytes()).hexdigest()!=h for n,h in hashes.items()):
        raise ValueError('Installed file checksum mismatch')
    retired=set(old)-set(files)
    if retired:
        archive=Path(tempfile.mkdtemp(prefix='previous-export-',dir=destination))
        # Preserve the earlier manifest and only retire checksum-verified owned files.
        shutil.copy2(manifest_path,archive/manifest_name)
        for name in sorted(retired):
            path=contained(destination,name)
            if path.exists():
                target=contained(archive,name);target.parent.mkdir(parents=True,exist_ok=True)
                path.replace(target)
        manifest['previous_export']=str(archive)
    with tempfile.NamedTemporaryFile(dir=destination,prefix='.spline-',delete=False,mode='w',encoding='utf8') as f:
        temporary=Path(f.name);f.write(json.dumps(manifest,indent=2)+'\n')
    try: os.replace(temporary,manifest_path)
    finally:
        if temporary.exists(): temporary.unlink()
    return manifest
