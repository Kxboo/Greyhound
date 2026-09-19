"""BO4 types from captured BO4 declarations, checked against every brush side.

BO3 choices compare named properties in the shipped catalogue. Differences and
unnamed source bits remain explicit; no CW binary layouts or flag masks enter
this decoder.
"""

# Support direct execution and the isolated packaged Python runtime.
import sys as _tool_sys
from pathlib import Path as _ToolPath
TOOLS_ROOT = next(p for p in _ToolPath(__file__).resolve().parents if (p / "tool_bootstrap.py").is_file())
_tool_sys.path.insert(0, str(TOOLS_ROOT))
import tool_bootstrap as _tool_bootstrap
_tool_bootstrap.activate(__file__)
REPO_ROOT = TOOLS_ROOT.parent
import hashlib
import json
from collections import Counter
from pathlib import Path
import numpy as np

CLIP_NAMES = {'missileClip', 'bulletClip', 'playerClip', 'aiClip', 'vehicleClip',
              'itemClip', 'canShootClip', 'aiSightClip', 'utilityClip', 'playerVehicleClip'}
TRAVERSAL = {'ladder', 'mantleOn', 'mantleOver', 'climbWall', 'climbPipe'}
GREY = 't7_concrete_poured_bunker_paint_01_grey_lt'
CLIP_TOOLS = {'clip','clip_player','clip_ai','clip_full','clip_nosight','clip_slick',
    'clip_slick_player','clip_physics','clip_missile','nosight_noclip','clip_weapon',
    'clip_vehicle','clip_novehicle','clip_player_vehicle','clip_utility',
    'clip_playervehicle_only','clip_player_playervehicle','clip_missile_no_player',
    'clip_nosight_novehicle'}


class Types:
    def __init__(self, probe, reference):
        declarations = {}
        for candidate in probe['named_flag_candidates']:
            for row in candidate['rows']:
                fields = tuple(int(row[f'field_{n}'], 16) for n in (8, 12, 16, 20))
                if row['name'] in declarations and declarations[row['name']] != fields:
                    raise ValueError('BO4 named declarations disagree')
                declarations[row['name']] = fields
        if not CLIP_NAMES <= declarations.keys():
            raise ValueError('Missing BO4 named collision declarations')
        self.declarations = declarations
        self.surface_types = {f[1]: n for n, f in declarations.items()
                              if f[1] and (f[1] & 0x03f00000)==f[1]}
        self.contents = {n: f[2] for n, f in declarations.items()
                         if f[2] and n not in TRAVERSAL and f[1] not in self.surface_types}
        self.surface = {n: f[1] for n, f in declarations.items()
                        if f[1] and f[1] & (f[1]-1) == 0 and not f[1] & 0x3bf00000}
        self.traversal = {f[1]: n for n, f in declarations.items() if n in TRAVERSAL}
        native=json.loads((TOOLS_ROOT / 'black_ops_3/reference/bo3_brush_contents.json').read_text())
        native_bits={r['name']:int(r['contents_mask'],16) for r in native['rows']}
        if (self.contents['bulletClip']|self.contents['missileClip'])!=native_bits['weaponClip'] or self.contents['aiSightClip']!=native_bits['ai_nosight']:
            raise ValueError('Captured BO4 bits disagree with the verified BO3 brush flag recipe')
        self.materials = reference['materials']
        self.by_name = {m['name']: m for m in self.materials}
        self.cache = {}

    @staticmethod
    def unpack(value, names):
        found = {n for n, bit in names.items() if value & bit == bit}
        covered = 0
        for n in found: covered |= names[n]
        return found, value & ~covered

    def choose(self, contents, surfaces):
        key = contents, tuple(sorted(surfaces))
        if key in self.cache: return self.cache[key]
        cn, unknown = self.unpack(contents, self.contents)
        surface_codes = {s & 0x03f00000 for s in surfaces}
        surface_type_names = {self.surface_types[s] for s in surface_codes if s in self.surface_types}
        surface_counts=Counter(self.surface_types[s & 0x03f00000] for s in surfaces
                               if (s & 0x03f00000) in self.surface_types)
        preferred_surface=min(surface_counts,key=lambda n:(-surface_counts[n],n)) if surface_counts else None
        # Glass/car-glass/bulletproof-glass share a contents bit. Their surface
        # enum disambiguates it; a shared bit alone cannot identify all aliases.
        for n in surface_type_names:
            bit=self.declarations[n][2]
            if bit and contents & bit == bit:
                cn.add(n);unknown &= ~bit
        decoded = [self.unpack(s, self.surface) for s in surfaces]
        sn = set.intersection(*(x[0] for x in decoded)) if decoded else set()
        clips = cn & CLIP_NAMES
        brush_flags=[];brush_collision=set()
        if {'bulletClip','missileClip'} <= clips:
            brush_flags.append('weaponClip');brush_collision.update(('bulletClip','missileClip'))
        if 'aiSightClip' in clips:
            brush_flags.append('ai_nosight');brush_collision.add('aiSightClip')
        traversals = {self.traversal.get(s & 0x38000000) for s in surfaces}
        traversal = next(iter(traversals)) if len(traversals) == 1 else None
        family = {'ladder': 'ladder', 'mantleOn': 'mantle_on', 'mantleOver': 'mantle_over',
                  'climbWall': 'wall_climb', 'climbPipe': 'pipe_climb'}.get(traversal)
        if not family:
            for flag, material in [('mount', 'mount'), ('portal', 'portal'), ('sky', 'sky'),
                                   ('noDrop', 'nodrop'), ('caulk', 'caulk_shadow')]:
                if flag in (sn if flag == 'mount' else cn | sn) and material in self.by_name and not clips:
                    family = material; break
        if not family and not clips:
            for source,tool in [('glass','glass_clip'),('glasscar','glass_clip_car'),('glassbulletproof','glass_clip_bulletproof')]:
                if source in cn and tool in self.by_name:
                    family=tool;break
        if not family and not clips and ('nonSolid' in sn or 'nonColliding' in cn):
            family = 'skip'
        if family and family in self.by_name:
            candidates = [self.by_name[family]]
        elif clips:
            candidates = [m for m in self.materials if
                (m['name'] in CLIP_TOOLS or
                 ('clip' in m['name'].split('_') and m['properties'].get('surfaceType') in surface_type_names)) and
                m['properties'].get('noDraw') == '1' and
                (m['properties'].get('slick') != '1' or 'slick' in sn)]
        else:
            candidates = []
        if brush_flags:
            candidates += [self.by_name[n] for n in ('caulk_shadow','skip') if n in self.by_name and (n=='skip' or 'weaponClip' in brush_flags)]
        ranked = []
        for m in candidates:
            props = m['properties']; mc = {n for n in CLIP_NAMES if props.get(n) == '1'} | brush_collision
            ms = {n for n in self.surface if props.get(n) == '1'}
            # Collision behavior is primary. Appearance flags cannot justify
            # dropping bullet/AI/player collision to get a closer-looking tool.
            # Preserve movement/solidity flags before material response. For
            # equal collision behavior prefer the captured surface type. Mixed
            # source faces use a deterministic majority, recorded below.
            score = (len(clips-mc), len(mc-clips),
                     len((ms ^ sn) & {'slick','nonSolid'}),
                     int(preferred_surface is not None and props.get('surfaceType')!=preferred_surface),
                     len(ms ^ sn))
            ranked.append((score, len(m['name']), m['name'], mc, ms, m))
        if ranked:
            _, _, name, mc, ms, material = min(ranked, key=lambda x: x[:3])
            added, omitted = sorted(mc-clips), sorted(clips-mc)
            added_s, omitted_s = sorted(ms-sn), sorted(sn-ms)
        else:
            name, added, omitted, added_s, omitted_s = GREY, [], sorted(clips), [], sorted(sn)
        selected = [next(r for r in ranked if r[2] == name)] if ranked else []
        # One source brush stays one output brush. When no exact stock tool
        # exists, choose the closest single tool and retain explicit differences.
        components = [dict(material=r[2], brush_contents=list(brush_flags),
                           collision_properties=sorted(r[3])) for r in selected]
        role = ('traversal' if traversal or 'mount' in sn else
                'clips' if clips else 'non_colliding' if 'nonColliding' in cn or 'nonSolid' in sn else 'brushes')
        result = dict(material=name, role=role, brush_contents=brush_flags,
            collision_components=components,
            representation='single_hull',
            native_brush_collision_properties=sorted(brush_collision), contents_raw=hex(contents),
            contents_names=sorted(cn), surface_names_common=sorted(sn),
            surface_type_names=sorted(surface_type_names),
            source_surface_type_counts=dict(surface_counts), preferred_surface_type=preferred_surface,
            surface_mapping_status=('NO_NAMED_SOURCE_SURFACE' if preferred_surface is None else
                'MATCHED' if self.by_name.get(name,{}).get('properties',{}).get('surfaceType')==preferred_surface else
                'FALLBACK_COLLISION_PRIORITY'),
            unresolved_surface_type_codes=sorted(hex(s) for s in surface_codes if s and s not in self.surface_types),
            target_surface_type=self.by_name.get(name,{}).get('properties',{}).get('surfaceType'),
            side_surface_raw=[hex(s) for s in sorted(set(surfaces))], traversal=traversal,
            unknown_contents=hex(unknown),
            surface_type_codes=sorted({hex(s & 0x03f00000) for s in surfaces}),
            added_collision_properties=added, omitted_collision_properties=omitted,
            added_surface_properties=added_s, omitted_surface_properties=omitted_s,
            status=('COLLISION_PROPERTIES_MATCH' if not added and not omitted else 'CLOSEST_NAMED_BO3_TOOL') if ranked else 'GREY_GEOMETRY_PLACEHOLDER',
            scope='Named-property mapping; BO3 compiled behavior and source surface material identity are not asserted')
        self.cache[key] = result
        return result


def build(root, reference, flag_probe=None):
    root = Path(root); probe = json.loads((root/'world_pools_probe.json').read_text())
    supplement=None
    if flag_probe is not None:
        path=Path(flag_probe);supplement=json.loads(path.read_text())
        if not supplement['write_success'] or supplement.get('named_flags_version',0)<3:
            raise ValueError('Supplement requires the complete stable declaration capture')
        # Types rejects any disagreement with original captured declarations.
        probe['named_flag_candidates'] += supplement['named_flag_candidates']
    meta = json.loads((root/'collision_data.json').read_text())
    types = Types(probe, reference)
    t = probe['global_filter_candidate']
    if not t['readback_unchanged']: raise ValueError('Unstable BO4 filter table')
    raw = (root/t['file']).read_bytes()
    if len(raw) != t['bytes']: raise ValueError('Truncated filter capture')
    filters = np.frombuffer(raw, '<u4').reshape(-1, 2)
    side_path = root/meta['brush_sides']['file']
    if hashlib.sha256(side_path.read_bytes()).hexdigest() != meta['sources'][side_path.name]['sha256']:
        raise ValueError('Brush side capture changed')
    sides = np.frombuffer(side_path.read_bytes(), '<u4').reshape(-1, 5)
    rows = []
    for b in meta['brushes']:
        ids = list(b['axial_material_u16'])
        if b['side_count']:
            ids.extend(map(int, sides[b['side_start']:b['side_start']+b['side_count'], 4]))
        if not ids or max(ids) >= len(filters): raise ValueError('Uncaptured side filter index')
        union = int(np.bitwise_or.reduce(filters[ids, 1]))
        if union != int(b['contents_raw'], 16):
            raise ValueError(f"BO4 filter union disagrees with brush {b['index']}")
        choice = types.choose(union, list(map(int, filters[ids, 0])))
        rows.append(dict(choice, brush_index=b['index'], filter_indices=ids))
    clip_rows=[r for r in rows if r['role']=='clips']
    result = dict(schema='greyhound-bo4-brush-types-v2', rows=rows,
        mapping_policy='One output hull per source brush; native BO3 contents flags plus the closest single stock tool. Collision omissions are penalized before additions; all differences remain explicit.',
        collision_summary=dict(source_clip_brushes=len(clip_rows),
            exact_named_properties=sum(not r['added_collision_properties'] and not r['omitted_collision_properties'] for r in clip_rows),
            with_added_properties=sum(bool(r['added_collision_properties']) for r in clip_rows),
            with_omitted_properties=sum(bool(r['omitted_collision_properties']) for r in clip_rows)),
        all_side_contents_unions_verified=True, brushes_checked=len(rows),
        filter_sha256=hashlib.sha256(raw).hexdigest(),
        source_metadata_sha256=hashlib.sha256((root/'collision_data.json').read_bytes()).hexdigest(),
        named_declarations=types.declarations,
        material_counts=dict(Counter(r['material'] for r in rows)),
        role_counts=dict(Counter(r['role'] for r in rows)),
        unresolved_contents_counts=dict(Counter(r['unknown_contents'] for r in rows)))
    if supplement is not None:
        result['declaration_supplement']=dict(file=str(path.resolve()),sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            raw_files={r['file']:hashlib.sha256((path.parent/r['file']).read_bytes()).hexdigest() for r in supplement['named_flag_candidates']})
    (root/'material_assignments.json').write_text(json.dumps(result, separators=(',', ':'))+'\n')
    return result
