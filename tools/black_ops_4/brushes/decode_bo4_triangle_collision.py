"""Decode BO4 collision surfaces, preserving original vertices and triangles.

Each surface references a triangle range and a separate vertex-index range.
The ranges and bounds are checked against all source records.

Ownership: clipmap +0xA0/+0xA8 lists {blob pointer, byte size} surface trees.
A tree is a variable-width BVH of u32 words. A branch holds a child count n
(2..8), n node-relative child word offsets, then minX[n] minY[n] minZ[n]
maxX[n] maxY[n] maxZ[n]. A leaf holds 0x100|count, then that many surface
indices. Collision leaves (+0x68, 56 bytes) and the cLeaf_t embedded at clip
model +32 name their tree at word 0 (-1 = none) and the OR of their triangle
contents at word 2. Clip model 0 (the world) embeds a zero leaf. zm_towers:
tree 0 is the world (BSP leaf 3), tree 1 is clip model 2 (and its copy,
leaf 209); the trees partition every surface exactly.

Materials: the +34 u16 indexes the executable's global filter table of
{surfaceFlags, contents} pairs, the same table brush sides use. Names come
from the game's own flag declarations captured beside it.
"""

# Support direct execution and the isolated packaged Python runtime.
import sys as _tool_sys
from pathlib import Path as _ToolPath
TOOLS_ROOT = next(p for p in _ToolPath(__file__).resolve().parents if (p / "tool_bootstrap.py").is_file())
_tool_sys.path.insert(0, str(TOOLS_ROOT))
import tool_bootstrap as _tool_bootstrap
_tool_bootstrap.activate(__file__)
REPO_ROOT = TOOLS_ROOT.parent
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np

SURFACE_TYPE_MASK = 0x1F00000
TREE_LEAF = 0x100


def parse_tree(words, surface_bounds):
    """Walk one surface BVH; return its surface indices and node counts."""
    floats = words.view('<f4')
    surfaces, seen, branches, leaves = [], set(), 0, 0
    stack = [(0, None)]
    while stack:
        offset, box = stack.pop()
        if offset in seen or not 0 <= offset < len(words):
            raise ValueError('Surface tree node repeated or outside its blob')
        seen.add(offset)
        head = int(words[offset])
        if head & TREE_LEAF:
            count = head & 0xFF
            if head & ~0x1FF or not count or offset + 1 + count > len(words):
                raise ValueError('Unknown surface tree leaf layout')
            ids = words[offset+1:offset+1+count].astype(np.int64)
            if np.any(ids >= len(surface_bounds)):
                raise ValueError('Surface tree references a nonexistent surface')
            if box is not None:
                sb = surface_bounds[ids]
                if np.any(sb[:, :3] < box[:3]) or np.any(sb[:, 3:] > box[3:]):
                    raise ValueError('Surface lies outside its surface tree box')
            surfaces.extend(ids.tolist()); leaves += 1
            continue
        if not 2 <= head <= 8 or offset + 1 + 7*head > len(words):
            raise ValueError('Unknown surface tree branch layout')
        branches += 1
        children = words[offset+1:offset+1+head].astype(np.int64)
        boxes = floats[offset+1+head:offset+1+7*head].reshape(6, head).T.astype(float)
        for child, child_box in zip(children, boxes):
            if box is not None and (np.any(child_box[:3] < box[:3]) or np.any(child_box[3:] > box[3:])):
                raise ValueError('Surface tree child box lies outside its parent')
            if child <= 0: raise ValueError('Surface tree child offset is not forward')
            stack.append((offset + int(child), child_box))
    return surfaces, branches, leaves


def flag_names(probe):
    """BO4's declared surface types and named flag masks, deduplicated by name."""
    rows = {}
    for table in probe.get('named_flag_candidates', []):
        for row in table['rows']:
            masks = (int(row['field_12'], 16), int(row['field_16'], 16))
            if rows.setdefault(row['name'], masks) != masks:
                raise ValueError(f"Conflicting declarations for flag {row['name']}")
    types, flags = {}, {}
    for name, (surface, contents) in rows.items():
        if surface and not surface & ~SURFACE_TYPE_MASK:
            types[surface >> 20] = (name, contents)
        elif surface or contents:
            flags[name] = (surface, contents)
    return types, flags


def describe(surface_flags, contents, types, flags):
    matched = {n: m for n, m in flags.items()
               if surface_flags & m[0] == m[0] and contents & m[1] == m[1]}
    # Drop a name whose masks are a strict subset of another match (mantleOn in mantleOver).
    names = sorted(n for n, (s, c) in matched.items() if not any(
        o != n and s & t == s and c & u == c and (s, c) != (t, u) for o, (t, u) in matched.items()))
    covered_s = SURFACE_TYPE_MASK | int(np.bitwise_or.reduce([matched[n][0] for n in names] or [0]))
    covered_c = int(np.bitwise_or.reduce([matched[n][1] for n in names] or [0]))
    # A type declaration can carry contents too (water: 0x20, glass: 0x10).
    type_name, type_contents = types.get((surface_flags & SURFACE_TYPE_MASK) >> 20, (None, 0))
    if contents & type_contents == type_contents: covered_c |= type_contents
    return {'surface_type': type_name,
            'surface_type_index': (surface_flags & SURFACE_TYPE_MASK) >> 20,  # 0 has no declaration
            'named_flags': names,
            'unnamed_surface_flag_bits': hex(surface_flags & ~covered_s),
            'unnamed_contents_bits': hex(contents & ~covered_c)}


def decode(root, write_output=True):
    probe = json.loads((root/'world_pools_probe.json').read_text())
    pool = next(p for p in probe['pools'] if p['pool_index'] == 11)
    if not pool['active_count_matches_directory'] or len(pool['assets']) != 1:
        raise ValueError('Ambiguous collision asset')
    tables = {t['label']: t for t in pool['assets'][0]['tables']}
    sources = {}
    def read(label, dtype):
        t = tables[label]
        if t['status'] != 'captured_stable' or not t['readback_unchanged']:
            raise ValueError('Source table was not captured stably')
        raw = (root/t['file']).read_bytes()
        if len(raw) != t['count']*t['stride']: raise ValueError('Source byte count differs')
        sources[label] = {**t, 'sha256': hashlib.sha256(raw).hexdigest()}
        return np.frombuffer(raw, dtype=dtype)
    records = read('bounds_candidate', '<u4').reshape(-1, 9)
    vertices = read('vertices_candidate', '<f4').reshape(-1, 3)
    triangles = read('triangles_candidate', '<u4').reshape(-1, 3)
    vertex_ids = read('indices_candidate_2A0', '<u4')
    if not np.isfinite(vertices).all() or np.any(vertex_ids >= len(vertices)) or np.any(triangles >= len(vertices)):
        raise ValueError('Invalid global collision vertices or indices')
    rows, tri_cursor, vertex_cursor = [], 0, 0
    for i, record in enumerate(records):
        ti, vi = int(record[6]), int(record[7])
        nt, nv, material = int(record[8]&255), int((record[8]>>8)&255), int(record[8]>>16)
        if ti != tri_cursor or vi != vertex_cursor or nt == 0 or nv == 0:
            raise ValueError('Surface ranges do not partition the source arrays')
        tri_cursor += nt; vertex_cursor += nv
        if tri_cursor > len(triangles) or vertex_cursor > len(vertex_ids):
            raise ValueError('Surface range exceeds source table')
        ids = vertex_ids[vi:vi+nv]; tris = triangles[ti:ti+nt]
        if set(ids.tolist()) != set(tris.ravel().tolist()):
            raise ValueError('Surface triangle vertices disagree with vertex list')
        points = vertices[ids]
        bounds = np.r_[points.min(0), points.max(0)]
        if not np.array_equal(bounds, record.view('<f4')[:6]):
            raise ValueError('Surface bounds do not exactly match captured vertices')
        rows.append({'index': i, 'bounds': bounds.tolist(), 'triangle_start': ti,
                     'triangle_count': nt, 'vertex_reference_start': vi,
                     'vertex_reference_count': nv, 'material_index': material})
    if tri_cursor != len(triangles) or vertex_cursor != len(vertex_ids):
        raise ValueError('Trailing unused array data')
    material_ids = records[:, 8] >> 16

    # Materials through the global filter table.
    materials, material_policy = None, 'Raw u16 index; global filter table not captured'
    filter_info = probe.get('global_filter_candidate')
    if filter_info:
        raw = (root/filter_info['file']).read_bytes()
        filters = np.frombuffer(raw, '<u4').reshape(-1, 2)
        if int(material_ids.max()) >= len(filters):
            raise ValueError('Surface material index beyond the captured global filter table')
        sources['global_filter'] = {**filter_info, 'sha256': hashlib.sha256(raw).hexdigest()}
        types, flags = flag_names(probe)
        materials = {}
        for m in np.unique(material_ids).tolist():
            surface_flags, contents = map(int, filters[m])
            materials[str(m)] = {'surface_flags': hex(surface_flags), 'contents': hex(contents),
                                 'surfaces': int(np.sum(material_ids == m)),
                                 **describe(surface_flags, contents, types, flags)}
        material_policy = ('material_index is a global filter index {surfaceFlags, contents}; the same table '
                           'brush sides use. Names are BO4 declarations; unnamed bits kept as hex')

    # Ownership through the surface trees.
    ownership, trees = None, []
    tree_table = tables.get('surface_trees')
    if tree_table and tree_table.get('blobs'):
        leaves = read('records_candidate_60', '<u4').reshape(-1, 14)
        clip = read('clip_models_candidate', '<u4').reshape(-1, 22)
        # Clip models embed a 56-byte cLeaf_t at +32 (word 8), same field meanings.
        # Clip model 0 is the world: its embedded leaf is zero and the world
        # reaches its trees through BSP collision leaves instead.
        if np.any(clip[0, 8:22]): raise ValueError('World clip model embeds a non-empty leaf')
        owners = [('collision_leaf', i, leaf) for i, leaf in enumerate(leaves)] + \
                 [('clip_model', i, row[8:22]) for i, row in enumerate(clip) if i]
        surface_bounds = records.view('<f4')[:, :6].astype(float)
        owner_of = np.full(len(records), -1)
        semantic_owner = np.full(len(records), -1)
        trees_of = [[] for _ in records]
        for blob in tree_table['blobs']:
            if blob['status'] != 'captured_stable': raise ValueError('Surface tree blob was not captured stably')
            raw = (root/blob['file']).read_bytes()
            if len(raw) != blob['bytes']: raise ValueError('Surface tree byte count differs')
            k = blob['tree']
            sources[f'surface_tree_{k}'] = {**blob, 'sha256': hashlib.sha256(raw).hexdigest()}
            ids, branches, leaf_count = parse_tree(np.frombuffer(raw, '<u4'), surface_bounds)
            if len(set(ids)) != len(ids):
                raise ValueError('Surface referenced twice within one surface tree')
            refs = [(kind, i, int(leaf[2])) for kind, i, leaf in owners if int(leaf[0].view('<i4')) == k]
            contents = int(np.bitwise_or.reduce(filters[material_ids[ids], 1])) if materials else None
            if not refs: raise ValueError(f'Surface tree {k} has no owner')
            if contents is not None and any(c != contents for _, _, c in refs):
                raise ValueError(f'Surface tree {k} contents disagree with its owner')
            # A tree named by an inline clip model is that model's; one named only
            # by collision leaves is the world's (zm_towers: BSP leaf 3). The leaf
            # table also keeps a copy of an inline model's leaf (leaf 209).
            clip_models = [i for kind, i, _ in refs if kind == 'clip_model']
            if len(clip_models) > 1: raise ValueError(f'Surface tree {k} shared by clip models')
            owner = ({'kind': 'clip_model', 'clip_model': clip_models[0]} if clip_models
                     else {'kind': 'world', 'clip_model': 0})
            model_index=owner['clip_model']
            if any(semantic_owner[j] not in (-1,model_index) for j in ids):
                raise ValueError('Surface shared across different coordinate-space/model owners')
            for j in ids:
                semantic_owner[j]=model_index
                trees_of[j].append(k)
                if owner_of[j] < 0: owner_of[j]=k
            owner['collision_leaves'] = [i for kind, i, _ in refs if kind == 'collision_leaf']
            trees.append({'tree': k, 'owner': owner, 'surfaces': len(ids),
                          'first_surface': min(ids), 'last_surface': max(ids),
                          'branches': branches, 'leaves': leaf_count,
                          'triangle_contents': hex(contents) if contents is not None else None,
                          'coordinate_space': 'world' if owner['kind'] == 'world' else 'clip_model_local'})
        if np.any(owner_of < 0): raise ValueError('Surface trees leave surfaces unowned')
        for tree in trees:
            if tree['owner']['kind'] == 'world' and tree['owner']['collision_leaves'] == []:
                raise ValueError('World surface tree has no collision leaf')
        for row, ks, model in zip(rows, trees_of, semantic_owner.tolist()):
            row['surface_trees'] = ks
            row['surface_tree'] = ks[0] if len(ks)==1 else None
            row['clip_model_owner'] = model
        ownership = {'trees': len(trees), 'all_surfaces_owned_once': all(len(ks)==1 for ks in trees_of),
                     'all_surfaces_have_one_semantic_owner':True,
                     'surface_tree_references':sum(map(len,trees_of)),
                     'surfaces_referenced_by_multiple_trees':sum(len(ks)>1 for ks in trees_of),
                     'additional_same_owner_tree_references':sum(len(ks)-1 for ks in trees_of),
                     'maximum_tree_reference_multiplicity':max(map(len,trees_of)),
                     'tree_boxes_contain_children_and_surfaces': True,
                     'owner_triangle_contents_agree': materials is not None,
                     'world_surfaces': int(np.sum(semantic_owner==0)),
                     'clip_model_surfaces': int(np.sum(semantic_owner>0))}

    vectors = vertices[triangles].astype(float)
    areas = np.linalg.norm(np.cross(vectors[:,1]-vectors[:,0], vectors[:,2]-vectors[:,0]), axis=1)*.5
    summary = {'surfaces': len(rows), 'vertices': len(vertices), 'triangles': len(triangles),
        'vertex_references': len(vertex_ids), 'ranges_partition_exactly': True,
        'all_surface_vertex_lists_match_triangles': True, 'all_bounds_match_exactly': True,
        'zero_area_triangles': int(np.sum(areas == 0)),
        'material_index_min': int(material_ids.min()), 'material_index_max': int(material_ids.max()),
        'distinct_materials': len(np.unique(material_ids)),
        'materials_resolved': materials is not None,
        'ownership': ownership or 'surface trees not captured'}
    result = {'schema': 'greyhound-bo4-triangle-collision-v3', 'summary': summary,
        'sources': sources, 'surface_trees': trees, 'materials': materials, 'surfaces': rows,
        'coordinate_policy': ('Unmodified source coordinates. World-tree surfaces are in world space; '
                              'clip-model-tree surfaces are model-local, placed by the entities that use '
                              'that clip model (collision_data.json).' if trees else
                              'Unmodified source coordinates; ownership not captured'),
        'topology_policy': 'Original triangle order and indices; no retriangulation or invented thickness',
        'material_policy': material_policy}
    if write_output:
        (root/'triangle_collision.json').write_text(json.dumps(result,separators=(',',':'))+'\n')
    print(json.dumps(summary, indent=2))
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('capture', type=Path)
    decode(parser.parse_args().capture)
