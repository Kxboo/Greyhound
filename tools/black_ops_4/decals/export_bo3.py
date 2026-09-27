"""Package one measured BO4 decal material as native BO3 image/material assets.

Optional volume placements are kept separate from terrain. Only the verified
color/reveal shader and the conservative native projector subset are converted.
No BO3 installation file is changed; --output is a new BO3-root overlay.
"""
import argparse
import hashlib
import json
import math
import re
import shutil
import struct
import sys
import uuid
from pathlib import Path, PureWindowsPath

from PIL import Image


SCHEMA = 'greyhound-bo4-decal-source-v1'
SHADER_ID = '6e0a762e671e6047'
STOCK_TEMPLATE = 't7_decal_grunge_concrete_drip_01_blend'
TEMPLATE_FILE = Path(__file__).resolve().with_name('bo3_stock_template_v1.json')
# SHA-256 of canonical JSON, so Git's CRLF handling cannot change identity.
TEMPLATE_SHA256 = '7b2ff0837bf46669c26244f59c23ee687c850fbef139af7d8dbf01469f5d181a'
EXPECTED_BLEND = (0x27892624, 0x20082104, 0x20082104, 0)
SEMANTICS = {'0xA0AB1041': 'color', '0x34D849D5': 'reveal', '0x199A03D3': 'tint_mask'}
TEXTURE_BINDINGS = {(0xA0AB1041, 7, 1), (0x34D849D5, 11, 1), (0x199A03D3, 10, 1)}
SAMPLER_BINDINGS = {(0x86A55E5A, 2, 1, 0x2A2), (0xB55F9AA9, 1, 1, 0x14),
                    (0xDFA9373D, 3, 1, 0x13)}
# The BO4 priorities align with BO3 Radiant's native decal layer order:
# 1 Debris, 2 Damage - New, 3 Paper, ... 15 Grunge, ... 22 Asphalt.
# Same-name stock materials corroborate twelve categories, including Damage -
# New and Grunge. Paper follows the contiguous native category order.
DECAL_LAYERS = ('Debris (top)', 'Damage - New', 'Paper', 'Water', 'Snow', 'Ice',
                'Foliage', 'Grass', 'Mud', 'Sand', 'Gravel', 'Dirt', 'Signage - New',
                'Carpet', 'Grunge', 'Damage - Old', 'Signage - Old', 'Plaster',
                'Concrete', 'Brick', 'Rock', 'Asphalt (bottom)')
RECORD_BYTES = 216


def fail(message):
    raise ValueError(message)


def hex_number(value, label):
    try:
        if not isinstance(value, str) or not re.fullmatch(r'0[xX][0-9a-fA-F]+', value):
            raise ValueError()
        return int(value, 16)
    except ValueError:
        fail(f'Invalid {label}: expected a hexadecimal pointer or hash')


def input_file(base, reference, label):
    # Native capture names are leaf files beside decal_capture.json. Restrict
    # references to that contract; never follow a path from captured JSON.
    if not isinstance(reference, str) or not reference or Path(reference).name != reference or \
            PureWindowsPath(reference).name != reference or reference in ('.', '..'):
        fail(f'Unsafe {label} path')
    candidate = (base / reference).resolve()
    if candidate.parent != base.resolve() or not candidate.is_file():
        fail(f'Missing {label}: {reference}')
    return candidate


def quoted(value):
    return json.dumps(str(value), ensure_ascii=False)


def asset_block(name, kind, fields):
    lines = [f'\t{quoted(name)} ( {quoted(kind + ".gdf")} )', '\t{']
    lines += [f'\t\t{quoted(key)} {quoted(value)}' for key, value in sorted(fields.items())]
    return '\n'.join(lines + ['\t}'])


def explicit_assets(text, kind):
    pattern = re.compile(r'^\s*"([^"\n]+)"\s*\(\s*"' + kind + r'\.gdf"\s*\)\s*\{([^{}]*)\}', re.M)
    for match in pattern.finditer(text):
        fields = dict(re.findall(r'"([^"\n]+)"\s*"([^"\n]*)"', match[2]))
        yield match[1], fields


def load_template():
    if not TEMPLATE_FILE.is_file():
        fail(f'Missing bundled BO3 decal template: {TEMPLATE_FILE.name}')
    data = TEMPLATE_FILE.read_bytes()
    try:
        template = json.loads(data)
    except (ValueError, UnicodeDecodeError):
        fail(f'Corrupt bundled BO3 decal template: {TEMPLATE_FILE.name}')
    canonical = json.dumps(template, sort_keys=True, separators=(',', ':'),
                           ensure_ascii=False).encode('utf8')
    if hashlib.sha256(canonical).hexdigest() != TEMPLATE_SHA256:
        fail(f'Corrupt bundled BO3 decal template: {TEMPLATE_FILE.name}')
    if (template.get('schema') != 'greyhound-bo3-stock-template-v1' or
            template.get('material_asset') != STOCK_TEMPLATE or
            template.get('source_gdt') != 'texture_assets/t7_decal_grunge.gdt' or
            not isinstance(template.get('material_defaults'), dict) or
            template['material_defaults'].get('materialType') != 'lit_decal_diffuse_reveal' or
            not isinstance(template.get('image_defaults'), dict) or
            template['image_defaults'].get('type') != 'image'):
        fail('Invalid bundled BO3 decal template fields')
    return template


def finite_vector(values, count, label):
    if not isinstance(values, list) or len(values) != count or any(
            not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v) for v in values):
        fail(f'Invalid {label}')
    return [float(v) for v in values]


def fmt(value):
    if not math.isfinite(value):
        fail('Nonfinite BO3 numeric field')
    return format(0.0 if abs(value) < 1e-8 else value, '.9g')


def basis(angles):
    p, y, r = map(math.radians, angles)
    cp, sp, cy, sy, cr, sr = math.cos(p), math.sin(p), math.cos(y), math.sin(y), math.cos(r), math.sin(r)
    return [[cp*cy, cp*sy, -sp],
            [sr*sp*cy-cr*sy, sr*sp*sy+cr*cy, sr*cp],
            [cr*sp*cy+sr*sy, cr*sp*sy-sr*cy, cr*cp]]


def cod_angles(axes):
    axes = [finite_vector(row, 3, 'decal axis') for row in axes]
    for i in range(3):
        for j in range(3):
            dot = sum(axes[i][k]*axes[j][k] for k in range(3))
            if abs(dot - (1.0 if i == j else 0.0)) > 2e-4:
                fail('Nonorthogonal BO4 decal axes')
    pitch = math.asin(max(-1.0, min(1.0, -axes[0][2])))
    if math.hypot(axes[0][0], axes[0][1]) < 1e-4:
        # At vertical pitch, yaw and roll share one degree of freedom. Choose
        # yaw zero and solve roll from the other measured axis, then verify the
        # complete reconstructed basis below.
        # Float32 unit vectors may have z=0.99999994 at an exact right angle;
        # asin alone would spuriously reconstruct a 0.00035 horizontal axis.
        pitch = math.copysign(math.pi / 2, pitch)
        yaw = 0.0
        roll = math.atan2(axes[1][0] * (1 if pitch > 0 else -1), axes[1][1])
    else:
        yaw = math.atan2(axes[0][1], axes[0][0])
        roll = math.atan2(axes[1][2], axes[2][2])
    angles = list(map(math.degrees, (pitch, yaw, roll)))
    if max(abs(a-b) for row_a, row_b in zip(axes, basis(angles)) for a, b in zip(row_a, row_b)) > 2e-4:
        fail('BO4 decal axes cannot be represented by COD angles')
    return [a % 360 for a in angles]


def decode_record(raw, index):
    record = raw[index*RECORD_BYTES:(index+1)*RECORD_BYTES]
    f = lambda offset, n: list(struct.unpack_from(f'<{n}f', record, offset))
    axes = f(0x0C, 9)
    matrix = f(0x3C, 12)
    return {'index': index, 'hidden': record[8], 'axes': [axes[0:3], axes[3:6], axes[6:9]],
            'origin': f(0x30, 3), 'world_to_local': {'matrix': [matrix[0:3], matrix[3:6], matrix[6:9]],
                                                    'translation': matrix[9:12]},
            'half_extents': f(0x6C, 3), 'edge_feather': f(0x78, 3),
            'atlas_rect': f(0x84, 4), 'u_corners': f(0x94, 4), 'v_corners': f(0xA4, 4),
            'material': struct.unpack_from('<Q', record, 0xB8)[0],
            'forward_material': struct.unpack_from('<Q', record, 0xC0)[0],
            'priority': struct.unpack_from('<I', record, 0xC8)[0],
            'target_name': struct.unpack_from('<I', record, 0xCC)[0],
            'angle_threshold_cos': f(0xD0, 1)[0]}


def placement(decal, atlas):
    if decal['hidden']:
        fail('hidden source placement')
    if decal['forward_material']:
        fail('forward material is not represented by the tested BO3 decal')
    if decal['target_name']:
        fail('target filter is not represented by the tested BO3 decal')
    priority = decal['priority']
    if type(priority) is not int or not 1 <= priority <= len(DECAL_LAYERS):
        fail('BO4 decal priority is outside the defined native layer range')
    if abs(decal['angle_threshold_cos'] - .5) > 1e-4:
        fail('source facing threshold has no tested BO3 mapping')
    edge = finite_vector(decal['edge_feather'], 3, 'edge feather')
    if any(v < 0 or v > 1 for v in edge):
        fail('BO4 edge feather is outside native BO3 editor bounds')
    # BO3 Radiant loads each editor edgeFeather value, clamps it to [0,1],
    # then writes 1-value to the runtime projector (all three axes). The BO4
    # capture already holds this runtime threshold, so convert it back to the
    # BO3 editor representation. This preserves 1=hard and 0.5=half feather.
    bo3_edge = [1-v for v in edge]
    origin = finite_vector(decal['origin'], 3, 'origin')
    half = finite_vector(decal['half_extents'], 3, 'half extents')
    if any(v < .25 or v > 65536 for v in half):
        fail('decal half extents exceed BO3 editor bounds')
    angles = cod_angles(decal['axes'])
    # Verify the captured inverse at the centre and each local axis. This
    # catches a stale or transposed record before publishing its orientation.
    w2l = decal['world_to_local']
    rows = [finite_vector(row, 3, 'world-to-local matrix') for row in w2l['matrix']]
    translation = finite_vector(w2l['translation'], 3, 'world-to-local translation')
    for axis, expected in [(None, [0, 0, 0])] + [(k, [half[k] if i == k else 0 for i in range(3)]) for k in range(3)]:
        point = origin if axis is None else [origin[i]+decal['axes'][axis][i]*half[axis] for i in range(3)]
        local = [sum(point[i]*rows[i][j] for i in range(3))+translation[j] for j in range(3)]
        if max(abs(a-b) for a, b in zip(local, expected)) > max(.03, max(half)*.0002):
            fail('decal world-to-local transform disagrees with its axes and origin')
    u = finite_vector(decal['u_corners'], 4, 'U corners')
    v = finite_vector(decal['v_corners'], 4, 'V corners')
    if max(abs(u[0]-u[1]), abs(u[2]-u[3]), abs(v[0]-v[2]), abs(v[1]-v[3])) > 1e-4:
        fail('rotated or sheared decal UVs cannot use BO3 uvBaseAndScale')
    su, sv = u[2]-u[0], v[1]-v[0]
    if su <= 0 or sv <= 0:
        fail('mirrored or zero-scale decal UVs lack a tested BO3 mapping')
    rect = finite_vector(decal['atlas_rect'], 4, 'reveal atlas rectangle')
    width, height = atlas.size
    x, y, w, h = [round(value*extent) for value, extent in zip(rect, (width, height, width, height))]
    if any(abs(value*extent-rounded) > 1e-4 for value, extent, rounded in zip(rect, (width,height,width,height), (x,y,w,h))) or \
            w != h or w not in (4, 8, 16) or x < 0 or y < 0 or x+w > width or y+h > height:
        fail('unsupported reveal atlas cell')
    mask = list(atlas.getchannel('R').crop((x, y, x+w, y+h)).tobytes())
    return {'origin': ' '.join(map(fmt, origin)), 'angles': ' '.join(map(fmt, angles)),
            'decalLayerSort': DECAL_LAYERS[priority-1], 'decalLayerSortEnum': str(priority-1),
            'decalsize': ' '.join(map(fmt, half)), 'textureTiling': '1 1',
            'uvBaseAndScale': ' '.join(map(fmt, (u[0], v[0], su, sv))),
            'revealDataSize': f'{w}x{h}', 'revealData': ' '.join(map(str, mask))+' ',
            'edgeFeatherX': fmt(bo3_edge[0]), 'edgeFeatherY': fmt(bo3_edge[1]),
            'edgeFeatherZ': fmt(bo3_edge[2])}


def make_prefab(name, authored):
    key = uuid.uuid5(uuid.NAMESPACE_URL, 'greyhound-bo4-decal:'+name)
    lines = ['iwmap 4', '"script_startingnumber" 0', '"000_Global" flags expanded active',
             '"The Map" flags expanded', '// entity 0', '{', f'guid "{{{str(key).upper()}}}"',
             '"classname" "worldspawn"', '"ssi" "default_day"', '"wsi" "default_day"',
             '"fsi" "default"', '"skyboxmodel" "skybox_default_day"', '}']
    for entity_number, (index, properties) in enumerate(authored, start=1):
        guid = uuid.uuid5(uuid.NAMESPACE_URL, f'greyhound-bo4-decal:{name}:{index}')
        fields = {'classname': 'misc_volume_decal', 'model': 'vol_decal_cube',
                  'modeloverridematerial': name, 'decalEditorSortEnum': '-1', **properties}
        lines += [f'// entity {entity_number}: source decal index {index}', '{', f'guid "{{{str(guid).upper()}}}"']
        lines += [f'{quoted(k)} {quoted(v)}' for k, v in fields.items()]
        lines += ['}']
    return '\n'.join(lines)+'\n'


def prepare(capture, bo3_root=None, include_placements=False):
    capture = Path(capture).resolve()
    source = json.loads(capture.read_text(encoding='utf8'))
    if source.get('schema') != SCHEMA:
        fail('Unsupported BO4 decal capture schema')
    volume = source.get('volume_decals')
    if not isinstance(volume, dict) or volume.get('status') != 'captured':
        fail('BO4 volume decal source is not a complete captured material')
    pointer = hex_number(source.get('material_pointer'), 'selected material')
    if hex_number(volume.get('selected_material'), 'volume selected material') != pointer:
        fail('Selected material differs from volume source')
    materials = volume.get('materials')
    if not isinstance(materials, list) or len(materials) != 1:
        fail('Capture must contain exactly one selected decal material')
    material = materials[0]
    if hex_number(material.get('material'), 'material pointer') != pointer:
        fail('Capture material pointer mismatch')
    material_hash = hex_number(material.get('hash'), 'material hash')
    if not (0 < material_hash < 1 << 60):
        fail('Invalid BO4 material hash')
    name = f'bo4_decal_{material_hash:015x}'
    base = capture.parent
    shader = input_file(base, material.get('pixel_shader'), 'decal shader')
    shader_data = shader.read_bytes()
    shader_id = hashlib.sha1(shader_data).hexdigest()[:16]
    if not shader_data.startswith(b'DXBC') or shader_id != SHADER_ID:
        fail(f'Unsupported decal shader {shader_id}; only {SHADER_ID} color/reveal is validated')
    constants = input_file(base, material.get('cbuffer'), 'material constants')
    constant_data = constants.read_bytes()
    if len(constant_data) < 60 or len(constant_data) % 4:
        fail('Incomplete BO4 decal constant buffer')
    cb = struct.unpack('<'+str(len(constant_data)//4)+'f', constant_data)
    if not all(math.isfinite(v) for v in cb[:15]):
        fail('Nonfinite BO4 decal constants')
    if any(v < 0 or v > 1 for v in cb[1:4]) or any(v <= 0 or v > 32 for v in cb[10:14]) or abs(cb[14]) > 1e-6:
        fail('Unsupported BO4 tint, reveal scale, or reveal inversion')
    words = material.get('blend_words')
    if not isinstance(words, list) or tuple(hex_number(v, 'blend state') for v in words) != EXPECTED_BLEND:
        fail('Unsupported BO4 decal blend state')
    arguments = material.get('pass_arguments')
    if not isinstance(arguments, list):
        fail('Missing BO4 decal pass arguments')
    texture_args, sampler_args = [], []
    for row in arguments:
        if not isinstance(row, dict) or type(row.get('slot')) is not int or type(row.get('count')) is not int:
            fail('Invalid BO4 decal pass argument')
        binding = (hex_number(row.get('hash'), 'pass argument'), row['slot'], row['count'])
        if row.get('kind') == 'texture':
            texture_args.append(binding)
        elif row.get('kind') == 'sampler':
            sampler_args.append(binding)
        else:
            fail('Untested BO4 decal pass argument kind')
    if len(texture_args) != len(TEXTURE_BINDINGS) or set(texture_args) != TEXTURE_BINDINGS:
        fail('Unsupported BO4 decal texture bindings or slots')
    samplers = material.get('samplers')
    if not isinstance(samplers, list):
        fail('Missing BO4 decal sampler states')
    sampler_states = {}
    for row in samplers:
        sampler_hash = hex_number(row.get('hash'), 'sampler hash')
        if sampler_hash in sampler_states:
            fail('Duplicate BO4 decal sampler state')
        sampler_states[sampler_hash] = hex_number(row.get('state'), 'sampler state')
    actual_samplers = {(key, slot, count, sampler_states.get(key)) for key, slot, count in sampler_args}
    if len(sampler_args) != len(SAMPLER_BINDINGS) or actual_samplers != SAMPLER_BINDINGS:
        fail('Unsupported BO4 decal sampler bindings or states')
    images = material.get('images')
    if not isinstance(images, list) or len(images) != 3:
        fail('Color/reveal decal requires exactly three verified image bindings')
    bound = {}
    for image in images:
        semantic = SEMANTICS.get(f'0x{hex_number(image.get("semantic"), "image semantic"):08X}')
        if semantic is None or semantic in bound:
            fail('Unknown or duplicate BO4 decal image semantic')
        path = input_file(base, image.get('file'), semantic+' image')
        try:
            with Image.open(path) as opened:
                opened.verify()
            with Image.open(path) as opened:
                if opened.size != (image.get('width'), image.get('height')):
                    fail(f'{semantic} image dimensions disagree with capture')
                if semantic == 'color' and 'A' not in opened.getbands():
                    fail('Color image alpha is required for BO3 decal parity')
                if semantic == 'tint_mask' and opened.getchannel('R').getextrema() != (255, 255):
                    fail('Only the measured white tint mask is supported')
        except (OSError, SyntaxError) as error:
            fail(f'Invalid {semantic} PNG: {error}')
        definition = image.get('texture_def')
        if not isinstance(definition, str) or len(definition) != 64:
            fail('Missing 32-byte BO4 image binding definition')
        try:
            uv_scale = struct.unpack_from('<2f', bytes.fromhex(definition), 12)
        except (ValueError, struct.error):
            fail('Invalid BO4 image binding definition')
        if any(not math.isfinite(v) or abs(v-1) > 1e-4 for v in uv_scale):
            fail('Only unit BO4 material UV scales have a tested BO3 mapping')
        bound[semantic] = path
    selected = volume.get('selected_source_indices')
    if not isinstance(selected, list) or not selected or any(type(i) is not int or i < 0 for i in selected) or len(set(selected)) != len(selected):
        fail('Invalid selected BO4 source indices')
    count = volume.get('count')
    if type(count) is not int or count <= 0 or count > 65536 or max(selected) >= count:
        fail('Invalid BO4 source world count')
    if material.get('decals') != len(selected):
        fail('Selected source count differs from material usage')
    if bool(source.get('include_placements')) != (volume.get('records_scope') == 'full_world'):
        fail('BO4 placement scope disagrees with capture envelope')
    authored, omitted, mappings = [], [], []
    if include_placements:
        if not source['include_placements'] or volume.get('record_bytes') != RECORD_BYTES:
            fail('Placements require the full 216-byte BO4 world records')
        records = input_file(base, volume.get('file'), 'volume records').read_bytes()
        if len(records) != count*RECORD_BYTES:
            fail('BO4 volume record length disagrees with full world count')
        atlas_row = volume.get('atlas')
        if not isinstance(atlas_row, dict):
            fail('Placements require a captured reveal atlas')
        atlas_file = input_file(base, atlas_row.get('file'), 'reveal atlas')
        with Image.open(atlas_file) as image:
            image.load()
            if image.size != (atlas_row.get('width'), atlas_row.get('height')):
                fail('Reveal atlas dimensions disagree with capture')
            for index in selected:
                decal = decode_record(records, index)
                if decal['material'] != pointer:
                    fail(f'Selected source index {index} references another material')
                try:
                    native = placement(decal, image)
                    authored.append((index, native))
                    mappings.append({'source_index': index, 'source_priority': decal['priority'],
                                     'bo3_layer': native['decalLayerSort'],
                                     'bo3_layer_enum': int(native['decalLayerSortEnum']),
                                     'bo4_runtime_feather': decal['edge_feather'],
                                     'bo3_editor_feather': [float(native['edgeFeather'+axis])
                                                            for axis in 'XYZ']})
                except ValueError as error:
                    omitted.append({'source_index': index, 'reason': str(error)})
    template = load_template()
    return {'name': name, 'source': source, 'capture': capture, 'material': material,
            'shader_id': shader_id, 'constants': constants, 'shader': shader,
            'cb': cb, 'bound': bound, 'selected': selected, 'world_count': count,
            'stock_material': template['material_defaults'],
            'stock_image': template['image_defaults'], 'template': template,
            'authored': authored, 'omitted': omitted, 'mappings': mappings}


def package(prepared, output, bo3_root=None, include_placements=False):
    root = Path(output).resolve()
    if bo3_root is not None and (root == Path(bo3_root).resolve() or root.is_relative_to(Path(bo3_root).resolve())):
        fail('Output must be a separate overlay, outside the BO3 installation')
    if root == prepared['capture'].parent or root.is_relative_to(prepared['capture'].parent):
        fail('Output must not modify the captured source')
    if root.exists() and any(root.iterdir()):
        fail('Output overlay directory must be new or empty')
    root.mkdir(parents=True, exist_ok=True)
    name = prepared['name']
    image_dir = Path('texture_assets/black_ops_4/decals')
    gdt_rel = Path('source_data/black_ops_4/decals') / (name+'.gdt')
    prefab_rel = Path('map_source/_prefabs/black_ops_4/decals') / (name+'.map')
    fields = dict(prepared['stock_material'])
    cb = prepared['cb']
    tint = [12.92*v if v <= .0031308 else 1.055*v**(1/2.4)-.055 for v in cb[1:4]]
    images = []
    blocks = []
    for role, suffix, semantic, core, srgb in [('color','c','diffuseMap','sRGB3chAlpha','1'),
                                                ('reveal','r','revealMap','Linear1ch','0')]:
        asset = 'i_'+name+'_'+suffix
        relative = image_dir / (asset+'.png')
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(prepared['bound'][role], destination)
        cfg = dict(prepared['stock_image'])
        cfg.update({'baseImage': str(PureWindowsPath(*relative.parts)), 'semantic': semantic,
                    'coreSemantic': core, 'colorSRGB': srgb, 'type': 'image', 'imageType': 'Texture',
                    'compressionMethod': 'uncompressed', 'fromAlpha': '0', 'premulAlpha': '0',
                    'streamable': '1', 'clampU': '0', 'clampV': '0'})
        blocks.append(asset_block(asset, 'image', cfg))
        images.append({'asset': asset, 'file': relative.as_posix(),
                       'sha256': hashlib.sha256(destination.read_bytes()).hexdigest()})
    fields.update({'materialCategory': 'Decal', 'materialType': 'lit_decal_diffuse_reveal',
                   'usage': 'decal', 'layerSortDecal': 'Grunge', 'surfaceType': '<none>',
                   'colorMap': 'i_'+name+'_c', 'colorMap00': '$white_reveal',
                   'colorTint': ' '.join(map(fmt, tint))+' 1',
                   'alphaRevealMap': 'i_'+name+'_r',
                   'alphaRevealSoftEdge': fmt(cb[10]), 'alphaRevealRamp': fmt(cb[11]),
                   'revealScaleX': fmt(cb[12]), 'revealScaleY': fmt(cb[13]),
                   'tileColor': 'tile both*', 'tileReveal': 'tile both*',
                   'filterColor': 'aniso2x (mip linear)', 'filterReveal': 'linear (mip linear)'})
    for key in ('normalMap','cosinePowerMap','specColorMap','occMap','normalDetailMap',
                'colorDetailMap','thermalMaterial','enemyMaterial'):
        if key in fields:
            fields[key] = ''
    blocks.append(asset_block(name, 'material', fields))
    gdt = root / gdt_rel
    gdt.parent.mkdir(parents=True, exist_ok=True)
    gdt.write_text('{\n'+'\n\n'.join(blocks)+'\n}\n', encoding='utf8')
    authored, omitted = prepared['authored'], prepared['omitted']
    if include_placements and authored:
        prefab = root / prefab_rel
        prefab.parent.mkdir(parents=True, exist_ok=True)
        prefab.write_text(make_prefab(name, authored), encoding='utf8')
    else:
        prefab = None
    complete = not include_placements or not omitted
    status = 'assets_only' if not include_placements else 'placements_packaged_unverified' if complete else 'partial'
    report = {'schema': 'greyhound-bo3-decal-package-v1', 'status': status, 'complete': complete,
              'material_asset': name, 'source_material_hash': prepared['material']['hash'],
              'source_material_name': prepared['material'].get('name'),
              'source_world_count': prepared['world_count'], 'selected_source_count': len(prepared['selected']),
              'placements_requested': include_placements, 'placement_exported': len(authored),
              'placement_omitted': len(omitted), 'omitted_placements': omitted,
              'placement_mappings': prepared['mappings'],
              'mapping_evidence': {
                  'priority': 'Source priority 1..22 aligns with BO3 decal layers 0..21; '
                              'same-name stock materials corroborate 12 categories, including '
                              '2 and 15. Priority 3 follows the native contiguous order.',
                  'feather': 'BO3 Radiant writes runtime feather 1-clamp(editor feather) on each axis; '
                             'the BO4 capture holds the runtime threshold.'},
              'gdt': gdt_rel.as_posix(), 'prefab': prefab_rel.as_posix() if prefab else None,
              'images': images, 'source_shader_sha1_16': prepared['shader_id'],
              'source_cbuffer_sha256': hashlib.sha256(prepared['constants'].read_bytes()).hexdigest(),
              'source_capture_sha256': hashlib.sha256(prepared['capture'].read_bytes()).hexdigest(),
              'stock_template': 'texture_assets/t7_decal_grunge.gdt:'+STOCK_TEMPLATE,
              'bundled_template': {'file': TEMPLATE_FILE.name, 'canonical_sha256': TEMPLATE_SHA256,
                                   'file_sha256': hashlib.sha256(TEMPLATE_FILE.read_bytes()).hexdigest(),
                                   'source_gdt': prepared['template']['source_gdt'],
                                   'source_gdt_sha256': prepared['template']['source_gdt_sha256'],
                                   'material_asset': prepared['template']['material_asset'],
                                   'image_asset': prepared['template']['image_asset']},
              'stock_dependencies': ['$white_reveal','vol_decal_cube','default_day','default','skybox_default_day'],
              'bo3_in_game_verified': False,
              'limitations': ['Only the measured color/reveal decal shader and blend state are supported.',
                              'BO4 and BO3 decal projection, facing and draw order are not proven pixel-identical.',
                              'Native placements are editable and separate from terrain; omitted source instances are listed.']}
    (root / 'package_report.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf8')
    outcome = ('PARTIAL: some requested placements could not be converted.' if omitted else
               'Placement package created; BO3 in-game rendering is unverified.' if include_placements else
               'Asset-only package; original world placements were not requested.')
    readme = (f'BO4 decal material for BO3: {name}\n\n'
              f'{outcome}\n\n'
              'Merge source_data, texture_assets and, when present, map_source into the BO3 root.\n'
              f'In APE convert {name} and its two image dependencies.\n'
              'Use the optional map_source prefab in Radiant; it contains original world placements only.\n'
              f'Decal placements: {len(authored)} exported, {len(omitted)} omitted '
              f'from {len(prepared["selected"])} selected source records.\n'
              'See package_report.json for every omitted source index and reason.\n'
              'This package does not modify or bake terrain. BO3 in-game rendering remains unverified.\n')
    (root / 'README.txt').write_text(readme, encoding='utf8')
    for path in root.rglob('*'):
        if path.is_file() and path.suffix.lower() in ('.gdt','.map','.txt','.json'):
            if re.search(r'[A-Za-z]:[\\/]', path.read_text(encoding='utf8')):
                fail(f'Absolute filesystem path leaked into package: {path.relative_to(root)}')
    return {'schema': report['schema'], 'status': status, 'complete': complete,
            'package_root': str(root), 'report': str(root/'package_report.json'),
            'gdt': str(gdt), 'prefab': str(prefab) if prefab else None,
            'source_count': prepared['world_count'], 'selected_count': len(prepared['selected']),
            'placement_exported': len(authored), 'placement_omitted': len(omitted)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capture', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--bo3-root', type=Path,
                        help='Optional output-containment hint; no installed BO3 files are read')
    parser.add_argument('--placements', action='store_true')
    args = parser.parse_args(argv)
    try:
        prepared = prepare(args.capture, args.bo3_root, args.placements)
        result = package(prepared, args.output, args.bo3_root, args.placements)
        print(json.dumps(result))
        return 0 if result['complete'] else 3
    except (ValueError, KeyError, TypeError, OSError, struct.error) as error:
        print(json.dumps({'schema': 'greyhound-bo3-decal-package-v1', 'status': 'failed',
                          'complete': False, 'error': str(error)}))
        return 2


if __name__ == '__main__':
    sys.exit(main())
