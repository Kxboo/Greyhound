"""Recover original BO4 brush-face materials from captured render triangles.

No material is inferred from collision filters, nearest surfaces or majority
votes. A face needs same-owner, coplanar, nonoverlapping complete coverage by
one original material, complete exported dependencies and a common affine UV.
"""
from pathlib import Path
import json
import re
import struct
import hashlib
import numpy as np
from scipy.spatial import ConvexHull

PLANE_TOLERANCE = .002
AREA_RELATIVE_TOLERANCE = 1e-5
UV_TOLERANCE = 2e-5


def _area(poly):
    if len(poly)<3:return 0.
    p=np.asarray(poly);return abs(float(np.sum(p[:,0]*np.roll(p[:,1],-1)-p[:,1]*np.roll(p[:,0],-1))))/2


def _ccw(poly):
    p=np.asarray(poly,dtype=float)
    signed=np.sum(p[:,0]*np.roll(p[:,1],-1)-p[:,1]*np.roll(p[:,0],-1))
    return p if signed>=0 else p[::-1]


def _clip(subject,clipper):
    """Convex polygon intersection, retaining positive-area evidence only."""
    result=list(_ccw(subject))
    for a,b in zip(_ccw(clipper),np.roll(_ccw(clipper),-1,axis=0)):
        previous=result;result=[]
        if not previous:break
        edge=b-a
        side=lambda x:edge[0]*(x[1]-a[1])-edge[1]*(x[0]-a[0])
        start=previous[-1];ds=side(start)
        for end in previous:
            de=side(end)
            if (de>=0)!=(ds>=0):
                result.append(start+(end-start)*(ds/(ds-de)))
            if de>=0:result.append(end)
            start,ds=end,de
    return np.asarray(result).reshape(-1,2)


def _safe_file(root,name):
    path=(root/name).resolve()
    if not path.is_relative_to(root.resolve()):raise ValueError('Render source escapes capture folder')
    return path


class VisualResolver:
    def __init__(self,positions,uv,triangles,owners,surface_ids,material_ids,materials,map_hash=None,colors=None):
        self.positions=np.asarray(positions,dtype=float);self.uv=np.asarray(uv,dtype=float)
        self.triangles=np.asarray(triangles,dtype=np.int64);self.owners=np.asarray(owners,dtype=np.int64)
        self.surface_ids=np.asarray(surface_ids,dtype=np.int64);self.material_ids=np.asarray(material_ids,dtype=np.int64)
        self.materials=materials;self.map_hash=map_hash
        self.colors=np.asarray(colors if colors is not None else np.full((len(self.positions),4),255),dtype=np.uint8)
        if (self.positions.ndim!=2 or self.positions.shape[1]!=3 or self.uv.shape!=(len(self.positions),2)
            or self.triangles.ndim!=2 or self.triangles.shape[1]!=3 or not len(self.triangles)
            or any(len(x)!=len(self.triangles) for x in (self.owners,self.surface_ids,self.material_ids))
            or self.triangles.min()<0 or self.triangles.max()>=len(self.positions)
            or self.colors.shape!=(len(self.positions),4)
            or not np.isfinite(self.positions).all() or not np.isfinite(self.uv).all()):raise ValueError('Invalid captured render geometry')
        self.points=self.positions[self.triangles]
        self.minimum=self.points.min(1);self.maximum=self.points.max(1)
        self.by_owner={int(owner):np.flatnonzero(self.owners==owner) for owner in np.unique(self.owners)}

    def publish_patches(self,output_root,map_name,entities):
        """Publish source render triangles, independently of collision-face joins.

        World triangles retain source coordinates. An inline model needs a
        unique authored entity whose translation agrees with captured bounds;
        nonzero Euler rotations are deliberately not guessed here.
        """
        from render_surface_patches import render_surface_patches
        root=Path(output_root);folder=root/'prefabs'/'brushes'/'render_surfaces';folder.mkdir(parents=True,exist_ok=True)
        name=re.sub(r'[^A-Za-z0-9_-]','_',str(map_name));prefabs={};omissions=[];exported=patches=0
        if isinstance(entities,dict):entities=entities.get('entities',[])
        placements={}
        for entity in entities or []:placements.setdefault(int(entity.get('model_index',-1)),[]).append(entity)
        dependencies={}
        for material in self.materials:
            if material.get('status')=='complete':
                for item in [dict(file=material.get('metadata_file'))]+material.get('images',[]):
                    if item.get('file'):
                        path=_safe_file(root,item['file'])
                        dependencies[item['file']]=dict(file=item['file'],sha256=_sha(path),bytes=path.stat().st_size)
        # Native capture can retain metadata/images for an unresolved material.
        # Account for those evidence files too; their presence does not promote
        # the material to publishable status.
        for directory in ('_mat_info','_images'):
            for path in (root/directory).rglob('*'):
                if path.is_file():
                    relative=path.relative_to(root).as_posix()
                    dependencies[relative]=dict(file=relative,sha256=_sha(path),bytes=path.stat().st_size)
        for owner,indices in self.by_owner.items():
            translation=np.zeros(3);entity_index=None
            if owner:
                rows=placements.get(owner,[])
                reason=None
                if len(rows)!=1:reason='inline_owner_has_no_unique_authored_entity'
                elif rows[0].get('placement_crosscheck')!='agrees':reason='inline_authored_translation_not_verified_against_gfx_bounds'
                elif (np.asarray(rows[0].get('angles',[]),dtype=float).shape!=(3,)
                      or not np.isfinite(np.asarray(rows[0]['angles'],dtype=float)).all()
                      or np.max(np.abs(np.asarray(rows[0]['angles'],dtype=float)))>1e-6):reason='inline_rotation_convention_not_verified'
                else:
                    translation=np.asarray(rows[0].get('origin'),dtype=float);entity_index=rows[0].get('index')
                    if translation.shape!=(3,) or not np.isfinite(translation).all():reason='inline_translation_invalid'
                if reason:
                    omissions.append(dict(model_index=owner,triangle_count=len(indices),reason=reason));continue
            selected=[]
            for mat_index in np.unique(self.material_ids[indices]):
                sub=indices[self.material_ids[indices]==mat_index];material=self.materials[int(mat_index)]
                if material.get('status')!='complete' or not _material_identity_available(material):
                    omissions.append(dict(model_index=owner,material_hash=material.get('hash'),triangle_count=len(sub),reason=material.get('reason','original_material_dependencies_unavailable')));continue
                selected.extend(sub.tolist())
            if not selected:continue
            relative=f'prefabs/brushes/render_surfaces/{name}_render_model_{owner:04d}.map';target=_safe_file(root,relative)
            if target.exists():raise ValueError('Render prefab already exists')
            temporary=target.with_suffix('.map.tmp');count=local_patches=0;published=[]
            try:
                with temporary.open('x',encoding='utf-8',newline='\n') as stream:
                    stream.write('iwmap 4\n"000_Global" flags active\n// entity 0\n{\n"classname" "worldspawn"\n')
                    for triangle_index in sorted(selected):
                        vertex_ids=self.triangles[triangle_index];xyz=self.positions[vertex_ids]+translation
                        if np.linalg.norm(np.cross(xyz[1]-xyz[0],xyz[2]-xyz[0]))<1e-10:
                            omissions.append(dict(triangle_index=triangle_index,model_index=owner,reason='degenerate_source_triangle'));continue
                        material=self.materials[int(self.material_ids[triangle_index])]
                        surface=dict(vertices=xyz,uv=self.uv[vertex_ids],colors=self.colors[vertex_ids],material=material['material'],texture_size=material['texture_size'])
                        for patch in render_surface_patches(surface):
                            stream.write(f'// source surface {int(self.surface_ids[triangle_index])}, triangle {triangle_index}\n'+patch);local_patches+=1
                        count+=1;published.append(triangle_index)
                    stream.write('}\n')
                if count:
                    temporary.rename(target)
                    verification=_verify_prefab(target,self,translation,published)
                    prefabs[relative]=dict(file=relative,sha256=_sha(target),bytes=target.stat().st_size,patches=local_patches,source_triangles=count,geometry_kind='explicit_uv_patch',model_index=owner,entity_index=entity_index,coordinates='world',collision='nonColliding',verification=verification)
                else:temporary.unlink()
            except Exception:
                temporary.unlink(missing_ok=True);raise
            exported+=count;patches+=local_patches
        return dict(schema='greyhound-bo4-visual-transfer-v1',status='verified_surfaces_exported' if exported else 'no_proven_original_material_surfaces',
                    map_hash=self.map_hash,prefabs=prefabs,geometry_verified=True,embedded_data=dependencies,
                    summary=dict(source_triangles=len(self.triangles),exported_triangles=exported,omitted_triangles=len(self.triangles)-exported,patches=patches,source_materials=len(self.materials),complete_materials=sum(m.get('status')=='complete' for m in self.materials)),
                    materials=self.materials,omissions=omissions,
                    scope='Authoritative GfxSurface material identity, indexed source geometry, corner UVs and RGBA. No collision-face association, target shader equivalence, installed GDT assets, original baked lighting or nonzero inline Euler convention asserted.')

    def resolve_brush(self,brush_index,model_index,local_points,local_equations):
        points=np.asarray(local_points,dtype=float);equations=np.asarray(local_equations,dtype=float)
        if (points.ndim!=2 or points.shape[1]!=3 or equations.ndim!=2 or equations.shape[1]!=4
            or not np.isfinite(points).all() or not np.isfinite(equations).all()):raise ValueError('Invalid brush face geometry')
        candidates=self.by_owner.get(int(model_index),np.zeros(0,dtype=np.int64))
        if len(candidates):
            lo=points.min(0)-PLANE_TOLERANCE;hi=points.max(0)+PLANE_TOLERANCE
            candidates=candidates[np.all(self.maximum[candidates]>=lo,axis=1)&np.all(self.minimum[candidates]<=hi,axis=1)]
        faces=[]
        for face_index,plane in enumerate(equations):
            normal=plane[:3];length=float(np.linalg.norm(normal))
            if abs(length-1)>1e-5:raise ValueError('Brush support plane must be normalized')
            fp=points[abs(points@normal-plane[3])<=PLANE_TOLERANCE]
            row=dict(face_index=face_index,status='unresolved',evidence=dict(brush_index=int(brush_index),model_index=int(model_index)))
            if len(fp)<3:
                row['reason']='support_face_has_fewer_than_three_vertices';faces.append(row);continue
            axis=np.eye(3)[np.argmin(abs(normal))];u=np.cross(normal,axis);u/=np.linalg.norm(u);v=np.cross(normal,u)
            origin=fp.mean(0);project=lambda p:(p-origin)@np.array([u,v]).T
            xy=project(fp)
            try:polygon=_ccw(xy[ConvexHull(xy).vertices])
            except Exception:
                row['reason']='support_face_degenerate';faces.append(row);continue
            face_area=_area(polygon);area_tolerance=max(1e-7,face_area*AREA_RELATIVE_TOLERANCE)
            hits=[]
            for tri in candidates:
                xyz=self.points[tri]
                if np.max(abs(xyz@normal-plane[3]))>PLANE_TOLERANCE:continue
                cross=np.cross(xyz[1]-xyz[0],xyz[2]-xyz[0]);cross_length=np.linalg.norm(cross)
                if cross_length<1e-10 or abs(float(cross@normal/cross_length))<1-1e-6:continue
                overlap=_clip(project(xyz),polygon);area=_area(overlap)
                if area>area_tolerance:hits.append((int(tri),overlap,area))
            row['evidence'].update(face_area=face_area,triangle_indices=[h[0] for h in hits],surface_indices=sorted({int(self.surface_ids[h[0]]) for h in hits}),
                                   plane_tolerance=PLANE_TOLERANCE,area_tolerance=area_tolerance)
            if not hits:
                row['reason']='no_same_owner_coplanar_positive_overlap';faces.append(row);continue
            materials={int(self.material_ids[h[0]]) for h in hits}
            if len(materials)!=1:
                row['reason']='multiple_original_materials_cover_face';row['evidence']['material_indices']=sorted(materials);faces.append(row);continue
            material=self.materials[next(iter(materials))]
            if material.get('status')!='complete' or not _material_identity_available(material) or not re.fullmatch(r'[A-Za-z0-9_/-]+',material.get('material','')):
                row['reason']='original_material_name_or_dependencies_unavailable';row['evidence']['material']=material;faces.append(row);continue
            overlapping=False
            for i,(_,a,_) in enumerate(hits):
                for _,b,_ in hits[:i]:
                    if np.any(a.max(0)<b.min(0)) or np.any(b.max(0)<a.min(0)):continue
                    if _area(_clip(a,b))>area_tolerance:overlapping=True;break
                if overlapping:break
            if overlapping:
                row['reason']='render_coverage_overlaps_or_layers';faces.append(row);continue
            covered=sum(h[2] for h in hits);row['evidence']['covered_area']=covered
            if abs(covered-face_area)>area_tolerance:
                row['reason']='render_coverage_incomplete';faces.append(row);continue
            ids=np.concatenate([self.triangles[h[0]] for h in hits]);coords=project(self.positions[ids])
            design=np.c_[coords,np.ones(len(coords))]
            coefficients,_,rank,_=np.linalg.lstsq(design,self.uv[ids],rcond=None)
            residual=float(abs(design@coefficients-self.uv[ids]).max())
            row['evidence']['uv_affine_max_error']=residual
            if rank<3 or residual>UV_TOLERANCE:
                row['reason']='source_uvs_not_one_affine_face_projection';faces.append(row);continue
            axes=[]
            for column in range(2):
                xyz=u*coefficients[0,column]+v*coefficients[1,column]
                axes.append([*map(float,xyz),float(coefficients[2,column]-origin@xyz)])
            row.update(status='proven',material=material['material'],source_material=material.get('source_name'),
                       uv_affine=dict(u=axes[0],v=axes[1]),texture_size=material.get('texture_size'),
                       face_vertices=fp[ConvexHull(xy).vertices].tolist(),reason=None)
            faces.append(row)
        okay=bool(faces) and all(f['status']=='proven' for f in faces)
        return dict(status='proven' if okay else 'unresolved',faces=faces,
                    reason=None if okay else 'one_or_more_original_faces_unresolved',
                    evidence=dict(map_hash=self.map_hash,policy='same_owner_coplanar_complete_nonoverlapping_unique_material_affine_uv'))


class UnavailableResolver:
    def __init__(self,reason):self.reason=reason;self.map_hash=None
    def resolve_brush(self,brush_index,model_index,local_points,local_equations):
        return dict(status='unresolved',faces=[],reason=self.reason,evidence=dict(brush_index=brush_index,model_index=model_index))
    def publish_patches(self,output_root,map_name,entities):
        return dict(schema='greyhound-bo4-visual-transfer-v1',status='native_render_capture_unavailable',prefabs={},geometry_verified=False,embedded_data={},summary=dict(source_triangles=0,exported_triangles=0,omitted_triangles=0,patches=0),materials=[],omissions=[dict(reason=self.reason)])


def _sha(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):digest.update(block)
    return digest.hexdigest()


def _material_identity_available(material):
    """A source hash aliases the original asset; it is never a replacement."""
    try:
        source_hash=int(material['hash'],16)
        if not 0<source_hash<(1<<60) or material.get('identity_proven') is not True:return False
        if material.get('name_resolved'):return bool(material.get('source_name'))
        return material.get('source_hash_alias') is True and material.get('material')==f'source_material_{source_hash:x}'
    except (KeyError,ValueError,TypeError):return False


def _verify_prefab(path,resolver,translation,published):
    """Reopen emitted patches and check them against original triangle data.

    This checks barycentric positions, interpolated UV/color, material identity,
    winding and summed surface area, not just the writer's success return.
    """
    expected=set(published);seen={};areas={};triangle=None;vertices=[];material_next=False;patches=0
    with Path(path).open(encoding='utf-8') as stream:
        for line in stream:
            line=line.strip()
            if line.startswith('// source surface '):
                match=re.fullmatch(r'// source surface (\d+), triangle (\d+)',line)
                if not match or vertices:raise ValueError('Saved patch source annotation invalid')
                surface,triangle=map(int,match.groups())
                if triangle not in expected or surface!=resolver.surface_ids[triangle]:raise ValueError('Saved patch source identity differs')
            elif line=='toolFlags;':material_next=True
            elif material_next:
                if triangle is None or line!=resolver.materials[int(resolver.material_ids[triangle])]['material']:raise ValueError('Saved patch material differs')
                material_next=False
            elif line.startswith('v '):
                tokens=line.split()
                if len(tokens)!=14 or tokens[4]!='c' or tokens[9]!='t' or triangle is None:raise ValueError('Saved patch vertex syntax invalid')
                values=np.array([float(x) for x in tokens[1:4]+tokens[5:9]+tokens[10:14]])
                if not np.isfinite(values).all():raise ValueError('Saved patch contains nonfinite vertex attributes')
                vertices.append(values)
                if len(vertices)==4:
                    data=np.array(vertices);vertices=[];xyz=data[:,:3];color=data[:,3:7];uv=data[:,7:9]
                    ids=resolver.triangles[triangle];source=resolver.positions[ids]+translation
                    edge=np.array([source[1]-source[0],source[2]-source[0]]).T
                    coordinate=np.linalg.lstsq(edge,(xyz-source[0]).T,rcond=None)[0].T
                    weight=np.c_[1-coordinate.sum(1),coordinate]
                    if np.max(abs(weight@source-xyz))>1e-7 or weight.min()<-1e-8 or weight.max()>1+1e-8:raise ValueError('Saved patch leaves source triangle')
                    mat=resolver.materials[int(resolver.material_ids[triangle])];expected_uv=(weight@resolver.uv[ids])*mat['texture_size']
                    if not np.allclose(uv,expected_uv,rtol=1e-10,atol=1e-6):raise ValueError('Saved patch UV differs from captured source')
                    if np.max(abs(color-np.rint(weight@resolver.colors[ids])))>1:raise ValueError('Saved patch vertex color differs')
                    cross1=np.cross(xyz[1]-xyz[2],xyz[0]-xyz[2]);cross2=np.cross(xyz[3]-xyz[2],xyz[1]-xyz[2]);normal=np.cross(edge[:,0],edge[:,1])
                    if cross1@normal<=0 or cross2@normal<=0:raise ValueError('Saved patch winding/area differs')
                    areas[triangle]=areas.get(triangle,0)+(np.linalg.norm(cross1)+np.linalg.norm(cross2))/2
                    seen[triangle]=seen.get(triangle,0)+1;patches+=1
    if vertices or material_next or set(seen)!=expected or any(count!=3 for count in seen.values()):raise ValueError('Saved patch partition is incomplete')
    for triangle in expected:
        xyz=resolver.points[triangle];area=np.linalg.norm(np.cross(xyz[1]-xyz[0],xyz[2]-xyz[0]))/2
        if not np.isclose(areas[triangle],area,rtol=1e-7,atol=1e-7):raise ValueError('Saved patch area does not cover source triangle')
    return dict(status='passed',reopened=True,source_triangles=len(expected),patches=patches,checks=['source_identity','material','finite_attributes','barycentric_position','interpolated_uv','vertex_color','winding','summed_area'])


def _validate_materials(materials,output_root):
    """Check actual dependency artifacts, not the producer's success flag."""
    from PIL import Image
    aliases={}
    for material in materials:
        if material.get('status')!='complete':continue
        try:
            alias=material['material'];identity=material['hash']
            if not re.fullmatch(r'[A-Za-z0-9_-]+',alias) or not _material_identity_available(material):raise ValueError('Original material identity or source-hash alias unavailable')
            if alias.lower() in aliases and aliases[alias.lower()]!=identity:raise ValueError('Material filename alias collision')
            aliases[alias.lower()]=identity
            info=_safe_file(output_root,material['metadata_file'])
            if not info.is_file() or not info.stat().st_size:raise ValueError('Original material metadata missing')
            dimensions=[]
            for image in material['images']:
                path=_safe_file(output_root,image['file'])
                with Image.open(path) as decoded:
                    size=decoded.size
                    if decoded.format!='PNG' or min(size)<=0:raise ValueError('Invalid exported original image')
                    decoded.verify()
                image['sha256']=_sha(path);image['exported_dimensions']=list(size)
                if int(image['semantic'],16)==0xA0AB1041:
                    if 'binding_uv_scale' not in image or 'binding_offset_u16_raw' not in image:raise ValueError('Diffuse binding interpretation unavailable')
                    if image['binding_uv_scale']!=[1,1] or any(image['binding_offset_u16_raw']):raise ValueError('Diffuse binding uses a nonidentity UV transform not reproduced in target material')
                    dimensions.append(list(size))
            if len(dimensions)!=1 or dimensions[0]!=material['texture_size']:raise ValueError('Diffuse image dimensions are unavailable or differ from captured source')
        except (KeyError,ValueError,OSError) as error:
            material['status']='unresolved';material['reason']='dependency_validation_failed: '+str(error)


def load_visuals(capture_root):
    root=Path(capture_root)/'render';path=root/'render_capture.json'
    if not path.is_file():return UnavailableResolver('native_render_capture_unavailable')
    doc=json.loads(path.read_text())
    if doc.get('schema')!='bo4-brush-render-capture-v1' or doc.get('status')!='captured':
        return UnavailableResolver('native_render_capture_incomplete')
    output_root=Path(capture_root).parent
    for material in doc['materials']:
        if material.get('bindings_file'):
            bindings=_safe_file(root,material['bindings_file']).read_bytes()
            if len(bindings)!=32*len(material['images']):raise ValueError('Material binding/image count differs')
            for j,image in enumerate(material['images']):
                pointer,semantic=struct.unpack_from('<QI',bindings,j*32)
                if pointer!=int(image['pointer'],16) or semantic!=int(image['semantic'],16):raise ValueError('Material binding/image identity differs')
                image['binding_uv_scale']=list(struct.unpack_from('<2f',bindings,j*32+12))
                image['binding_offset_u16_raw']=list(struct.unpack_from('<3H',bindings,j*32+22))
                image['binding_usage_u16']=struct.unpack_from('<H',bindings,j*32+28)[0]
        elif material.get('status')=='complete':
            material['status']='unresolved';material['reason']='captured_material_bindings_unavailable'
    _validate_materials(doc['materials'],output_root)
    for material in doc['materials']:
        if material.get('metadata_file') and _material_identity_available(material):
            info=_safe_file(output_root,material['metadata_file'])
            if info.is_file():
                sidecar=info.with_suffix('.source.json')
                material['source_metadata_file']=sidecar.relative_to(output_root).as_posix()
                sidecar.write_text(json.dumps(dict(schema='greyhound-bo4-original-material-v1',scope='Captured source identity, image bindings and dependency status; target shader equivalence is not asserted.',material=material),indent=2)+'\n',encoding='utf-8')
    def array(name,dtype,width):
        info=doc['arrays'][name];raw=_safe_file(root,info['file']).read_bytes()
        if len(raw)!=info['count']*info['stride'] or info['status']!='captured_stable':raise ValueError('Render array size/stability differs')
        return np.frombuffer(raw,dtype).reshape(-1,width)
    positions=array('positions','<f4',3);attrs=array('attributes','<u4',5);surfaces=array('surfaces','<u4',24)
    indices=array('indices','<u2',1).ravel();brushes=array('brush_models','<u4',20)
    owner=np.full(len(surfaces),-1,dtype=np.int64)
    for i,b in enumerate(brushes):
        count,start=int(b[18]),int(b[19])
        if count:
            if start+count>len(owner) or np.any(owner[start:start+count]>=0):raise ValueError('Render model ownership overlaps')
            owner[start:start+count]=i
    if np.any(owner<0):raise ValueError('Render surface missing owner')
    mats={int(m['pointer'],16):i for i,m in enumerate(doc['materials'])};triangles=[];owners=[];ids=[];materials=[];cursor=0
    for i,s in enumerate(surfaces):
        count,start,base=int(s[9]>>16),int(s[10]),int(s[3])
        if start!=cursor or not count:raise ValueError('Render index partition differs')
        cursor+=count*3
        if cursor>len(indices):raise ValueError('Render index range exceeds capture')
        tri=indices[start:cursor].astype(np.int64).reshape(-1,3)+base
        if tri.max()>=len(positions):raise ValueError('Render vertex index exceeds capture')
        actual=np.r_[positions[tri].min((0,1)),positions[tri].max((0,1))]
        bounds=s.view('<f4')[12:18]
        if abs(actual-bounds).max()>.002:raise ValueError('Indexed render bounds differ')
        pointer=int(s[18])|(int(s[19])<<32)
        if pointer not in mats:raise ValueError('Uncaptured render material identity')
        triangles.extend(tri.tolist());owners.extend([int(owner[i])]*count);ids.extend([i]*count);materials.extend([mats[pointer]]*count)
    if cursor!=len(indices):raise ValueError('Unowned render indices')
    colors=attrs[:,0].copy().view('u1').reshape(-1,4)
    return VisualResolver(positions,attrs[:,1:3].copy().view('<f4'),triangles,owners,ids,materials,doc['materials'],doc['map_hash'],colors)
