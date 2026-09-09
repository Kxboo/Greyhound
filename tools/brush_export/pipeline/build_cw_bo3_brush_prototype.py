"""Build a small, auditable BO3 tool-material gallery from captured CW brushes.

This is a conversion prototype, not a Greyhound UI feature or a gameplay proof.
Source geometry and metadata remain separate from the gallery translation.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import struct

import numpy as np
from export_cross_map_cw_geometry import decode_brushes, relative_pointer
from decode_cw_brush_side_filters import decode as decode_sides
from exact_cw_brush_halfspaces import reconstruct_exact


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, indent=2), encoding='utf-8')


def materials(path):
    entries = re.findall(r'"([^"\n]+)"\s*\(\s*"material.gdf"\s*\)\s*\{([^{}]*)\}', path.read_text())
    result = {}
    for name, body in entries:
        if name in result:
            raise ValueError('Duplicate material definition: ' + name)
        result[name] = dict(re.findall(r'"([^"\n]+)"\s*"([^"\n]*)"', body))
    if not result:
        raise ValueError('No material definitions found')
    return result


def planes(raw, model, geo, brush):
    address = int(model['payload']['address'], 16)
    po = relative_pointer(raw, 400, address)
    so = relative_pointer(raw, 440, address)
    po = 520 if po is None else po
    so = geo['brush_run_offset'] - 4*geo['brush_count'] if so is None else so
    start = struct.unpack_from('<I', raw, so + 4*brush['brush_index'])[0]
    count = brush['nonaxial_plane_count']
    if start + count > geo['plane_count']:
        raise ValueError('Invalid plane range')
    equations = []
    for axis in range(3):
        n = [0., 0., 0.]; n[axis] = -1.
        equations.append(n + [-brush['mins'][axis]])
        n = [0., 0., 0.]; n[axis] = 1.
        equations.append(n + [brush['maxs'][axis]])
    equations += [list(struct.unpack_from('<4f', raw, po+16*i)) for i in range(start, start+count)]
    return equations


def number(v):
    return format(float(v), '.17g')


def map_brush(equations, offset, material):
    lines = ['iwmap 4', '// entity 0', '{', '"classname" "worldspawn"', '// brush 0', '{']
    for equation in equations:
        n = np.array(equation[:3]); d = equation[3] + np.dot(n, offset)
        center = n*d/np.dot(n, n)
        axis = np.eye(3)[np.argmin(abs(n))]
        u = np.cross(n, axis); u *= 64/np.linalg.norm(u)
        v = np.cross(u, n); v *= 64/np.linalg.norm(v)
        # Shipped iwmap brushes use inward cross products of the three points.
        points = [center, center+u, center+v]
        line = ' '.join('( ' + ' '.join(map(number, p)) + ' )' for p in points)
        lines.append(line + f' {material} 64 64 0 0 0 0 lightmap_gray 16384 16384 0 0 0 0')
    return '\n'.join(lines + ['}', '}', ''])


def read_map_planes(text):
    out = []
    for line in text.splitlines():
        groups = re.findall(r'\(\s*([^()]*)\)', line)
        if not groups:
            continue
        if len(groups) != 3:
            raise ValueError('Invalid face syntax')
        a, b, c = [np.array([float(x) for x in g.split()]) for g in groups]
        n = -np.cross(b-a, c-a)
        n /= np.linalg.norm(n)
        out.append([*n, float(n@a)])
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--capture', type=Path, required=True)
    ap.add_argument('--brush-index', type=Path, required=True)
    ap.add_argument('--placements', type=Path, required=True)
    ap.add_argument('--named-flags', type=Path, required=True)
    ap.add_argument('--gdt', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    out = args.output; out.mkdir(parents=True, exist_ok=True)
    mats = materials(args.gdt)
    table = json.loads(args.named_flags.read_text())
    assert table['readback_unchanged']
    flags = {r['name']: int(r['field_16'], 16) for r in table['records']
             if 0 < int(r['field_16'], 16) <= 0x3ffffff}
    known = 0
    for mask in flags.values(): known |= mask
    models = json.loads((args.capture/'clip_map_models.json').read_text())['models']
    items = json.loads(args.brush_index.read_text())['items']
    placement_data = json.loads(args.placements.read_text())
    by_model = {}
    for instance in placement_data['instances']:
        by_model.setdefault(instance['model_index'], []).append(instance)
    keys = set(flags) | {'colorMap', 'materialType', 'surfaceType', 'usage', 'nonSolid',
        'noDraw', 'noImpact', 'noMarks', 'noCastShadow', 'transparent', 'slick', 'detail', 'structural'}
    catalogue = {n: {k:v for k,v in d.items() if k in keys or 'clip' in k.lower()}
                 for n,d in mats.items()}
    save(out/'bo3-tool-materials.json', dict(source=str(args.gdt), sha256=sha(args.gdt),
        material_count=len(mats), properties=catalogue,
        scope='Selected properties from installed GDT; not an exhaustive compiler behavior model'))
    def describe(mask):
        names = sorted(n for n,b in flags.items() if mask & b)
        return dict(raw_contents=hex(mask), named_properties=names, residual_bits=hex(mask & ~known))
    counts = Counter(int(b['collision_flags_raw'],16) for b in items)
    mappings = []
    for mask, count in sorted(counts.items()):
        row = describe(mask); row['brush_count'] = count
        row['exact_named_property_candidates'] = [n for n,d in mats.items()
            if {k for k in flags if d.get(k)=='1'} == set(row['named_properties'])
            and d.get('surfaceType')=='<none>' and mask and not mask & ~known]
        row['status'] = 'named_property_comparison_only; other GDT effects and runtime unverified'
        mappings.append(row)
    save(out/'cw-to-bo3-material-candidates.json', dict(masks=mappings,
        source_brush_count=len(items), names_evidence=str(args.named_flags),
        names_status=table['status'], unknown_bits_are_not_discarded=True))
    annotations = []
    for b in items:
        mask = int(b['collision_flags_raw'], 16)
        desc = describe(mask)
        color_bytes = hashlib.sha256(struct.pack('<I',mask)).digest()[:3]
        label = '_'.join(desc['named_properties']) or 'unnamed'
        if mask & ~known: label += '_unknown_' + format(mask & ~known,'x')
        annotations.append(dict(name_hash=b['name_hash'], model_index=b['model_index'],
            brush_index=b['brush_index'], packed_flags_and_plane_count=b['packed_flags_and_plane_count'],
            nonaxial_plane_count=b['nonaxial_plane_count'], contents=desc,
            display_material_name=f'cw_{label}__{mask:08x}',
            display_rgb=[0.2+0.7*v/255 for v in color_bytes],
            source_world_instance_keys=[[r['collision_world'],r['instance_index']]
                for r in by_model.get(b['model_index'],[])],
            placement_status='direct_collision_instance' if b['model_index'] in by_model else
                'outside_supplied_orange_placement_inventory; not evidence of no placement'))
    save(out/'brush_flags.json',dict(schema='cw_brush_flags_v1', source=str(args.brush_index),
        source_sha256=sha(args.brush_index), placements_source=str(args.placements),
        placements_sha256=sha(args.placements), items=annotations,
        color_policy='Diagnostic RGB derived from full lower26 mask; not original material colors',
        names_status=table['status']))
    specs = [(0x10000,'clip_player',[0.2,0.55,1.]), (0x20000,'clip_ai',[1.,0.5,0.1]),
             (0x80,'clip_missile',[0.85,0.15,0.2]), (0x400,'clip_physics',[0.65,0.25,0.9]),
             (0x1040,'nosight_noclip',[0.15,0.85,0.65])]
    examples = []; cache = {}
    for slot, (mask, material, color) in enumerate(specs):
        expected = {n for n,b in flags.items() if mask & b}
        assert {n for n in flags if mats[material].get(n)=='1'} == expected
        candidates = [b for b in items if int(b['collision_flags_raw'],16)==mask and b['model_index'] in by_model]
        candidates.sort(key=lambda b:(b['nonaxial_plane_count'],max(np.array(b['maxs'])-b['mins'])))
        for candidate in candidates:
            mi = candidate['model_index']; bi = candidate['brush_index']; model = models[mi]
            if mi not in cache:
                raw = (args.capture/model['payload']['file']).read_bytes()
                cache[mi] = (raw, decode_brushes(raw,model), decode_sides(raw,model))
            raw, geo, sides = cache[mi]
            brush = next(b for b in geo['brushes'] if b['brush_index']==bi)
            equations = planes(raw,model,geo,brush)
            hull = reconstruct_exact(equations)
            a = np.array(hull['vertices']); b = np.array(brush['vertices'])
            distances = np.linalg.norm(a[:,None,:]-b[None,:,:],axis=2)
            error = max(distances.min(axis=0).max(),distances.min(axis=1).max())
            if hull['bad_directed_edges'] or hull['volume']<=0 or error>0.001:
                continue
            break
        else:
            raise ValueError('No validated prototype for '+material)
        offset = -np.array([(brush['mins'][i]+brush['maxs'][i])/2 for i in range(3)])
        offset[2] = -brush['mins'][2]
        stem = f'{slot+1:02}_{material}_collision_m{mi}_b{bi}'
        child = out/(stem+'.map'); child.write_text(map_brush(equations,offset,material))
        readback = np.array(read_map_planes(child.read_text()))
        wanted = np.array(equations,dtype=float)
        wanted[:,3] += wanted[:,:3]@offset
        wanted /= np.linalg.norm(wanted[:,:3],axis=1)[:,None]
        plane_error = float(abs(readback-wanted).max())
        assert plane_error < 1e-8
        rh = reconstruct_exact(readback.tolist())
        assert not rh['bad_directed_edges'] and rh['volume']>0
        assert abs(rh['volume']-hull['volume']) < max(1e-6,hull['volume']*1e-8)
        record = dict(id=stem, source_map='zm_silver', model_index=mi, name_hash=model['name_hash'],
            brush_index=bi, source_payload=str(args.capture/model['payload']['file']),
            payload_sha256=hashlib.sha256(raw).hexdigest(),
            geometry_representation='counted axial/nonaxial plane intersection; verified against captured vertices',
            source_brush=brush, source_planes_n_dot_x_le_d=equations,
            source_side_metadata=next(r for r in sides['brushes'] if r['brush_index']==bi),
            side_filter_table_status='not paired with this capture; category and raw filter words unavailable',
            source_world_instances=by_model[mi], contents=describe(mask),
            display_material_name='cw_'+ '_'.join(sorted(expected)) + f'__{mask:08x}',
            display_rgb=color, bo3_material=material, bo3_gdt_properties=catalogue[material],
            conversion_status='matching named contents properties; additional BO3 tool effects unverified',
            original_authored_texture=None, source_uvs=None,
            generated_uv_projection='BO3 default tool projection; not recovered UVs',
            gallery_local_translation=offset.tolist(), gallery_origin=[slot*192.,0.,0.],
            gallery_is_original_world_placement=False, child_map=child.name,
            gallery_vertices=(a+offset).tolist(), faces=hull['faces'],
            validation=dict(source_plane_vertex_set_error=float(error), serialized_plane_error=plane_error,
                            closed=True, positive_volume=hull['volume'], radiant_opened=False, compiled=False))
        examples.append(record)
    master = ['iwmap 4','// entity 0','{','"classname" "worldspawn"','}']
    for i,e in enumerate(examples,1):
        master += [f'// entity {i}','{','"classname" "misc_prefab"',
            f'"model" "_prefabs/superterrain/cw_clip_prototype_v1/{e["child_map"]}"',
            '"origin" "'+' '.join(map(number,e['gallery_origin']))+'"','}']
    (out/'cw_clip_gallery.map').write_text('\n'.join(master)+'\n')
    save(out/'brush_metadata.json', dict(schema='cw_bo3_brush_prototype_v1', units='game inches',
        coordinate_system='Z up, unchanged source axes', examples=examples,
        source_named_table=str(args.named_flags), source_named_table_sha256=sha(args.named_flags),
        gdt_sha256=sha(args.gdt), generator_sha256=sha(Path(__file__)),
        geometry_policy='No rescaling, coordinate snapping, or brush deduplication; gallery translation explicitly separate',
        unsupported_combinations='See cw-to-bo3-material-candidates.json; no automatic nearest material assignment'))
    save(out/'validation.json', dict(examples=len(examples), checks=[e['validation'] for e in examples],
        files={p.name:sha(p) for p in out.glob('*.map')}))
    print(json.dumps(dict(examples=len(examples), gdt_materials=len(mats), cw_masks=len(mappings), output=str(out))))


if __name__ == '__main__': main()
