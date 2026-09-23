"""Bake saved CW spline instances into per-model CAST folders with dependencies.

Position math follows the reflected GpuSplinedModelInstance/GpuSplineSegment
compute shader. Normals use the geometric deformation Jacobian, not CW's material
shader. Source capture and source models are never modified. Requires NumPy.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import struct
import sys

import numpy as np

_tools=next(p for p in Path(__file__).resolve().parents if (p/'tool_bootstrap.py').is_file())
sys.path.insert(0,str(_tools))
import tool_bootstrap
tool_bootstrap.activate(__file__)
from cw_spline_binary import CAST_TO_BO3, install_baked_models, write_xmodel_bin

CAST_SCALE = float(np.float32(2.54))  # Greyhound ScaleModel(2.54f).
EPS = struct.unpack('>d', bytes.fromhex('BE6777A5C0000000'))[0]
SIN_PI = struct.unpack('>d', bytes.fromhex('3E7777A5C0000000'))[0]
AXES = np.array([
    np.eye(3), [[-1,SIN_PI,0],[-SIN_PI,-1,0],[0,0,1]],
    [[EPS,-1,0],[1,EPS,0],[0,0,1]], [[EPS,1,0],[-1,EPS,0],[0,0,1]],
    [[EPS,0,-1],[0,1,0],[1,0,EPS]], [[EPS,0,1],[0,1,0],[-1,0,EPS]],
])


def normalize(v):
    length = np.linalg.norm(v, axis=-1, keepdims=True)
    if not np.isfinite(length).all() or np.any(length <= 1e-12):
        raise ValueError('Zero/nonfinite direction in spline deformation')
    return v / length


class Splines:
    def __init__(self, instances: bytes, segments: bytes):
        if not instances or len(instances) % 100 or not segments or len(segments) % 192:
            raise ValueError('Truncated or empty spline records (expected strides 100/192)')
        self.instances = np.frombuffer(instances, '<f4').reshape(-1,25).astype(float)
        self.indices = np.frombuffer(instances, '<u4').reshape(-1,25)[:,9:12]
        self.segments = np.frombuffer(segments, '<f4').reshape(-1,48).astype(float)

    def deform(self, vertices, index):
        if not isinstance(index, (int, np.integer)) or not 0 <= index < len(self.instances):
            raise ValueError('Spline instance index out of range')
        f = self.instances[index]
        begin, end, axis = map(int, self.indices[index])
        if not 0 <= begin < end <= len(self.segments) or axis > 5:
            raise ValueError('Invalid segment range or spline axis')
        if not np.isfinite(np.r_[f[:9],f[12:]]).all() or f[0] <= 0 or f[1] <= 0 or f[6] <= 0 or f[12] <= 0:
            raise ValueError('Invalid spline extent, length, scale, or transform')
        records = self.segments[begin:end]
        if not np.isfinite(records).all() or np.any(records[:,1] <= 0) or np.any(np.diff(records[:,0]) <= 0):
            raise ValueError('Invalid segment length, ordering, or coefficients')
        vertices = np.asarray(vertices, dtype=float)
        if vertices.ndim != 2 or vertices.shape[1] != 3 or not np.isfinite(vertices).all():
            raise ValueError('Expected finite Nx3 source positions')
        p = ((vertices*f[12]) @ f[16:25].reshape(3,3) + f[13:16]) @ AXES[axis]
        p = p*f[6] - f[2:5]
        p[:,1] += f[8]
        p[:,2] += f[7]
        distance = p[:,0]/f[0]*f[1] + f[5]
        selected = np.maximum(0, np.searchsorted(records[:,0], distance, side='right')-1)
        g = records[selected]
        t = (distance-g[:,0])/g[:,1]
        u = np.minimum(t,1)[:,None]  # Negative t deliberately extrapolates the cubic.
        coeff = g[:,2:14].reshape(-1,4,3)
        der = g[:,14:23].reshape(-1,3,3)
        tangent = normalize(der[:,0]*u*u + der[:,1]*u + der[:,2])
        x,y,z = tangent.T
        side = np.column_stack((-y,x,np.zeros_like(x)))
        vertical_case = np.hypot(x,y) <= float(np.float32(.01))
        side[vertical_case] = np.column_stack((z,np.zeros_like(x),-x))[vertical_case]
        side = normalize(side)
        vertical = np.cross(tangent,side)
        aligned = g[:,23:32].reshape(-1,3,3)
        side = np.einsum('ni,nij->nj',side,aligned)
        vertical = np.einsum('ni,nij->nj',vertical,aligned)
        a = (((g[:,47:48]*u+g[:,46:47])*u+g[:,45:46])*u+g[:,44:45])
        side_bank = np.cos(a)*side-np.sin(a)*vertical
        up_bank = np.sin(a)*side+np.cos(a)*vertical
        t3 = t[:,None]
        center = ((coeff[:,3]*t3+coeff[:,2])*t3+coeff[:,1])*t3+coeff[:,0]
        after = t > 1
        center[after] = (coeff.sum(axis=1)+(t3-1)*g[:,1:2]*np.einsum('ni,nij->nj',tangent,aligned))[after]
        q = center+p[:,1:2]*side_bank+p[:,2:3]*up_bank
        result = np.einsum('ni,nij->nj',q,g[:,32:41].reshape(-1,3,3))+g[:,41:44]
        if not np.isfinite(result).all():
            raise ValueError('Nonfinite deformed output')
        return result

    def normals(self, vertices, normals, index, step=1e-3):
        """Inverse-transpose geometric normals; retains authored hard-edge splits."""
        columns = []
        for axis in np.eye(3)*step:
            columns.append((self.deform(vertices+axis,index)-self.deform(vertices-axis,index))/(2*step))
        jacobian = np.stack(columns,axis=1)
        determinant = np.linalg.det(jacobian)
        if not np.isfinite(determinant).all() or np.any(determinant <= 1e-10):
            raise ValueError('Folded/singular deformation: normal/winding handling needs review')
        return normalize(np.linalg.solve(jacobian,np.asarray(normals)[...,None])[...,0])


# Preserve CAST property types, node identities, material references and topology.
TYPES = {b'b':('<u1',1),b'h':('<u2',1),b'i':('<u4',1),b'l':('<u8',1),
         b'f':('<f4',1),b'd':('<f8',1),b'2v':('<f4',2),b'3v':('<f4',3),b'4v':('<f4',4)}


class CastNode:
    def __init__(self, ident, hash_value, props, children):
        self.ident, self.hash, self.props, self.children = ident, hash_value, props, children

    def array(self, name):
        kind, count, raw = self.props[name]
        dtype, width = TYPES[kind]
        values = np.frombuffer(raw, dtype)
        return values.reshape(count,width) if width > 1 else values

    def set_array(self, name, values):
        kind, count, _ = self.props[name]
        dtype, width = TYPES[kind]
        arr = np.asarray(values,dtype=dtype)
        if arr.size != count*width:
            raise ValueError('CAST array shape changed')
        self.props[name] = kind,count,arr.tobytes()

    def walk(self):
        yield self
        for child in self.children:
            yield from child.walk()

    def encode(self):
        parts = []
        for name,(kind,count,raw) in self.props.items():
            encoded = name.encode('utf8')
            parts.append(struct.pack('<2sHI',kind,len(encoded),count)+encoded+raw)
        body = b''.join(parts)+b''.join(c.encode() for c in self.children)
        return struct.pack('<4sIQII',self.ident,len(body)+24,self.hash,len(self.props),len(self.children))+body


def read_cast(data):
    if len(data)<16:
        raise ValueError('Truncated CAST header')
    magic,version,count,flags = struct.unpack_from('<4sIII',data)
    if magic != b'cast' or version != 1 or not 0 < count <= 16:
        raise ValueError('Unsupported CAST header')
    def node(offset,limit,depth=0):
        if depth > 32 or offset+24 > limit:
            raise ValueError('Truncated/deep CAST node')
        ident,size,hash_value,pc,cc = struct.unpack_from('<4sIQII',data,offset)
        end = offset+size
        if size<24 or end>limit or pc>1024 or cc>100000:
            raise ValueError('Invalid CAST node size/counts')
        offset+=24; props={}
        for _ in range(pc):
            if offset+8>end: raise ValueError('Truncated CAST property')
            kind,ns,count = struct.unpack_from('<2sHI',data,offset);kind=kind.rstrip(b'\0');offset+=8
            if offset+ns>end: raise ValueError('Truncated CAST property name')
            name=data[offset:offset+ns].decode('utf8');offset+=ns
            if name in props: raise ValueError('Duplicate CAST property')
            if kind==b's':
                if count!=1: raise ValueError('Unsupported CAST string array')
                stop=data.find(b'\0',offset,end)+1
                if stop<=offset: raise ValueError('Unterminated CAST string')
            elif kind in TYPES:
                dtype,width=TYPES[kind];stop=offset+count*width*np.dtype(dtype).itemsize
            else: raise ValueError('Unknown CAST property type')
            if stop>end: raise ValueError('Truncated CAST property data')
            props[name]=(kind,count,data[offset:stop]);offset=stop
        children=[]
        for _ in range(cc):
            child,offset=node(offset,end,depth+1);children.append(child)
        if offset!=end: raise ValueError('CAST node size mismatch')
        return CastNode(ident,hash_value,props,children),end
    roots=[];offset=16
    for _ in range(count):
        child,offset=node(offset,len(data));roots.append(child)
    if offset!=len(data): raise ValueError('Trailing CAST data')
    return roots


def read_span(root, logical):
    path=root/logical
    if path.is_file(): return path.read_bytes()
    evidence=json.loads((root/'evidence.json').read_text(encoding='utf-8'))
    span=evidence['storage'][logical]
    target=(root/span['file']).resolve()
    if not target.is_relative_to(root.resolve()): raise ValueError('Invalid packed evidence path')
    with target.open('rb') as f:
        f.seek(span['offset']);data=f.read(span['bytes'])
    if len(data)!=span['bytes']: raise ValueError('Truncated packed span')
    return data


def triangle_normals(positions, faces, original_normals):
    """Fallback at folds: smooth only across the original shared vertex indices."""
    faces=np.asarray(faces).reshape(-1,3)
    area=np.cross(positions[faces[:,1]]-positions[faces[:,0]],positions[faces[:,2]]-positions[faces[:,0]])
    result=np.zeros_like(positions)
    for i in range(3): np.add.at(result,faces[:,i],area)
    lengths=np.linalg.norm(result,axis=1)
    cancelled=lengths<=1e-12
    # At exactly cancelling folds prefer a nonzero incident face. Unused or
    # degenerate-only vertices carry no rendered area, and keep the source normal.
    for triangle,normal in zip(faces[np.argsort(np.linalg.norm(area,axis=1))],area[np.argsort(np.linalg.norm(area,axis=1))]):
        if np.linalg.norm(normal)>1e-12:
            ids=triangle[cancelled[triangle]];result[ids]=normal
    empty=np.linalg.norm(result,axis=1)<=1e-12
    result[empty]=original_normals[empty]
    return normalize(result),int(empty.sum())


def bake(capture, placements_path, models, output, xmodel_bin=False):
    meta=json.loads((capture/'splined_models.json').read_text(encoding='utf-8'))
    if meta.get('status')!='captured_source_data' or not all(meta[k].get('readback_unchanged') for k in ('instances','segments')):
        raise ValueError('Spline source buffers did not pass capture validation')
    raw_instances=read_span(capture,'splines/instances.bin');raw_segments=read_span(capture,'splines/segments.bin')
    for key,raw,stride in [('instances',raw_instances,100),('segments',raw_segments,192)]:
        if meta[key].get('stride')!=stride or meta[key].get('count',-1)*stride!=len(raw):
            raise ValueError('Spline byte lengths do not match captured counts/strides')
    splines=Splines(raw_instances,raw_segments)
    data=json.loads(placements_path.read_text(encoding='utf-8-sig'))
    if isinstance(data,dict):
        if data.get('complete') is False: raise ValueError('Incomplete placement capture')
        data=data['StaticModels']
    rows=[r for r in data if r.get('RequiresSplineDeformation') or
          isinstance(r.get('SplineInstanceIndex'),int) and 0<=r['SplineInstanceIndex']<0xFFFFFFFF]
    if not rows: raise ValueError('No spline placements')
    keys=[(r['District'],r['ReferenceIndex']) for r in rows]
    if len(set(keys))!=len(keys): raise ValueError('Duplicate district/reference identity')
    if output.exists(): raise ValueError('Output must be a new directory')
    if any(output.resolve().is_relative_to(p.resolve()) for p in (capture,models)):
        raise ValueError('Output must be outside source capture/model trees')
    output.mkdir(parents=True)
    records=[]; baked_rows=[]; errors=[]
    for row in rows:
        try:
            name=row['Name'];index=row['SplineInstanceIndex']
            if not re.fullmatch(r'[A-Za-z0-9_.-]+',name) or name in ('.','..'):
                raise ValueError('Unsafe model identity')
            source=models/name/(name+'.cast')
            original=source.read_bytes();roots=read_cast(original)
            nodes=[n for root in roots for n in root.walk()]
            meshes=[n for n in nodes if n.ident==b'mesh']
            bones=[n for n in nodes if n.ident==b'bone']
            if len(bones)!=1 or any(n.ident in (b'blnd',b'anim') for n in nodes):
                raise ValueError('Only a static single-root mesh is supported')
            for key,want in [('lp',[0,0,0]),('wp',[0,0,0]),('lr',[0,0,0,1]),('wr',[0,0,0,1]),('s',[1,1,1])]:
                if key in bones[0].props and not np.allclose(bones[0].array(key).ravel(),want,atol=1e-6):
                    raise ValueError('Nonidentity bind transform needs explicit baking')
            if not meshes: raise ValueError('No meshes')
            positions=[];normals=[];normal_fallbacks=[]
            for mesh in meshes:
                vertices=mesh.array('vp').astype(float)/CAST_SCALE
                if not len(vertices): raise ValueError('Empty mesh')
                faces=mesh.array('f')
                if len(faces)%3 or not len(faces) or np.max(faces)>=len(vertices):
                    raise ValueError('Invalid triangle topology')
                if 'wb' in mesh.props and np.any(mesh.array('wb')!=0):
                    raise ValueError('Non-root skin weights')
                positions.append(splines.deform(vertices,index))
                try:
                    normals.append(splines.normals(vertices,mesh.array('vn'),index))
                except (ValueError,np.linalg.LinAlgError) as error:
                    n,empty=triangle_normals(positions[-1],faces,mesh.array('vn'))
                    normals.append(n)
                    normal_fallbacks.append(dict(mesh=len(positions)-1,reason=str(error),method='area-weighted original topology',vertices_without_nondegenerate_area=empty))
            all_positions=np.concatenate(positions)
            lo,hi=all_positions.min(0),all_positions.max(0)
            origin=(lo+hi)/2
            for mesh,p,n in zip(meshes,positions,normals):
                mesh.set_array('vp',(p-origin)*CAST_SCALE);mesh.set_array('vn',n)
            # Each placement owns its dependencies, just like a normal model export.
            # Include control/model content so another map cannot reuse a different shape.
            identity=hashlib.sha256(original+raw_instances[index*100:(index+1)*100]+raw_segments).hexdigest()[:20]
            baked_name=f'cwsp_{identity}_d{row["District"]}_r{row["ReferenceIndex"]}_s{index}'
            if not re.fullmatch(r'[a-z0-9_]+',baked_name): raise ValueError('Invalid spline placement identity')
            dest=output/baked_name
            dest.mkdir()
            for folder in ('_images','_mat_info'):
                dependency=source.parent/folder
                if not dependency.is_dir(): raise ValueError(f'Missing source model {folder}: {dependency}')
                for item in dependency.rglob('*'):
                    if not item.resolve().is_relative_to(source.parent.resolve()):
                        raise ValueError('Dependency path escapes source model folder')
                shutil.copytree(dependency,dest/folder)
            for node in nodes:
                if node.ident==b'file' and 'p' in node.props:
                    kind,count,path=node.props['p'];path=path.rstrip(b'\0').decode('utf8').replace('\\','/')
                    if path:
                        resolved=(source.parent/path).resolve()
                        if not resolved.is_relative_to((source.parent/'_images').resolve()):
                            raise ValueError('Texture path escapes source model folder')
                        relative=resolved.relative_to(source.parent.resolve()).as_posix()
                        if not (dest/relative).is_file(): raise ValueError(f'Missing model texture: {relative}')
                        node.props['p']=kind,count,relative.encode('utf8')+b'\0'
            raw=original[:16]+b''.join(root.encode() for root in roots)
            # Verify serialization, retained topology, UVs, colors and material links.
            reread=[n for r in read_cast(raw) for n in r.walk() if n.ident==b'mesh']
            old=[n for r in read_cast(original) for n in r.walk() if n.ident==b'mesh']
            for a,b in zip(old,reread):
                if {k:v for k,v in a.props.items() if k not in ('vp','vn')}!={k:v for k,v in b.props.items() if k not in ('vp','vn')}:
                    raise ValueError('Nongeometry mesh properties changed')
            (dest/(baked_name+'.cast')).write_bytes(raw)
            binary=write_xmodel_bin(dest/(baked_name+'.xmodel_bin'),roots) if xmodel_bin else None
            package_files={p.relative_to(dest).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
                           for p in sorted(dest.rglob('*')) if p.is_file()}
            bounds=np.array([[row[key][a] for a in 'XYZ'] for key in ('BoundsMin','BoundsMax')])
            records.append(dict(name=baked_name,source_model=name,index=index,district=row['District'],reference=row['ReferenceIndex'],
                vertices=len(all_positions),triangles=sum(len(m.array('f'))//3 for m in meshes),
                source_sha256=hashlib.sha256(original).hexdigest(),output_sha256=hashlib.sha256(raw).hexdigest(),
                bounds_max_difference=float(np.max(np.abs(np.array([lo,hi])-bounds))),origin=origin.tolist(),
                normal_fallbacks=normal_fallbacks,binary=binary,directory=baked_name,files=package_files,
                bo3_material_references=[n.props['n'][2].rstrip(b'\0').decode('utf8') for n in nodes if n.ident==b'matl']))
            baked_rows.append(dict(Name=baked_name,Position=dict(zip('XYZ',origin.tolist())),RotationDegrees=dict.fromkeys('XYZ',0),
                RotationQuaternion=dict(X=0,Y=0,Z=0,W=1),ModelScale=dict.fromkeys('XYZ',1),RequiresSplineDeformation=False,
                SourceModel=name,SourceSplineInstanceIndex=index,District=row['District'],ReferenceIndex=row['ReferenceIndex']))
        except (ValueError,OSError,KeyError,np.linalg.LinAlgError) as error:
            errors.append(dict(model=row.get('Name'),index=row.get('SplineInstanceIndex'),district=row.get('District'),reference=row.get('ReferenceIndex'),error=str(error)))
    report=dict(schema='cw-static-spline-bake-v2',layout='per_model_images_mat_info',complete=not errors,requested=len(rows),exported=len(records),errors=errors,records=records,
        source_capture=str(capture.resolve()),source_placements=str(placements_path.resolve()),
        source_instances_sha256=hashlib.sha256(raw_instances).hexdigest(),source_segments_sha256=hashlib.sha256(raw_segments).hexdigest(),
        units=dict(cast='centimeters',placements='game inches',xmodel_bin='game inches',
                   cast_units_per_game_unit=CAST_SCALE,cast_to_bo3_scale=CAST_TO_BO3,gdt_scale=1),
        limits=['Static model spline position deformation only; no decal splines, wind or animated material displacement.',
                'Normals use the deformation Jacobian with topology-based fallback at folds; CW material shader shading is not reproduced.',
                'Captured world bounds are diagnostics, not a per-vertex oracle.',
                'Models require BO3 asset compilation and material setup; collision and LODs are not generated.',
                'Supply placements and controls from the same map/session; numeric indices do not prove capture identity.'])
    (output/'bake_report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
    (output/'placements.json').write_text(json.dumps(baked_rows,indent=2)+'\n',encoding='utf8')
    lines=['iwmap 4','{','"classname" "worldspawn"','}']
    for row in baked_rows:
        lines+=['{','"classname" "misc_model"',f'"model" "{row["Name"]}"',
                '"origin" "'+' '.join(format(row['Position'][a],'.9g') for a in 'XYZ')+'"','"angles" "0 0 0"','}']
    (output/'spline_models_REVIEW.map').write_text('\n'.join(lines)+'\n',encoding='utf8')
    (output/'README.md').write_text(
        '# Baked Cold War spline models\n\n'
        f'{len(records)} of {len(rows)} requested instances exported. See bake_report.json for every result.\n\n'
        'Each uniquely named model folder contains its own *.cast, _mat_info/ and _images/. '
        'CAST contains a complete static mesh in centimeters, centered around its own origin. '
        'The offline helper defaults to CAST; optional --xmodel-bin converts directly with scale 0.3937007874. '
        'The native Greyhound spline action uses all model formats selected in Settings. '
        'The placement origins already use game inches; leave them unchanged. '
        'Material metadata and images are copied into every model folder. Material names and UVs are preserved.\n\n'
        'Compile/register each model under the matching file stem and map its material references to BO3 materials. '
        'Then import spline_models_REVIEW.map as a prefab at origin 0 0 0. The prefab uses game inches. '
        'Do not apply the original CW rigid placement or spline a second time. '
        'placements.json provides the same baked model identities and origins.\n\n'
        'This folder is the staging export. If installation was requested, see the destination installation manifest. '
        'No game compilation is performed. Collision, additional LODs, '
        'animated materials, wind, and spline decals are outside this bake. '
        'Normals are geometrically transformed; fallback meshes listed in the report use normals from '
        'the original triangle topology. Review their shading.\n',encoding='utf8')
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--capture',type=Path,required=True,help='gfx_map capture containing splined_models.json')
    p.add_argument('--placements',type=Path,required=True,help='Same-session district StaticModels document or spline row array')
    p.add_argument('--models',type=Path,required=True,help='Greyhound CAST model-batch-root')
    p.add_argument('--output',type=Path,required=True,help='New directory for baked models and review placements')
    p.add_argument('--xmodel-bin',action='store_true',help='Explicitly add XMODEL_BIN to the default CAST output')
    p.add_argument('--bo3-root',type=Path,help='BO3 installation root; required with --install-dir')
    p.add_argument('--install-dir',type=Path,help='Destination beneath BO3 _custom for model folders and placements')
    a=p.parse_args()
    if bool(a.bo3_root)!=bool(a.install_dir): p.error('--bo3-root and --install-dir must be supplied together')
    report=bake(a.capture,a.placements,a.models,a.output,a.xmodel_bin)
    result={k:report[k] for k in ('complete','requested','exported','errors')}
    if report['complete'] and a.install_dir:
        installed=install_baked_models(a.output,a.install_dir,a.bo3_root)
        result['installed']=dict(destination=installed['destination'],models=installed['models'])
    print(json.dumps(result,indent=2))
    return 0 if report['complete'] else 1


if __name__=='__main__':
    raise SystemExit(main())
