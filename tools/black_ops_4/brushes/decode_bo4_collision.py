"""Decode measured BO4 collision arrays from Greyhound world-pool probe v2.

This records geometry and unresolved ownership separately. It does not apply
Cold War clip contents or place every collision-library shape at world origin.
"""
from __future__ import annotations

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


def inline_bounds_check(brush_extent, model_bounds):
    """A model's combined bounds may include rendered geometry beyond its clip.

    zm_red model 2 proves this: its render surface extends 0.724451 units past
    the brush on X. Their union equals the captured model bounds. Ownership
    still comes from the clip leaf graph; source points are never stretched.
    """
    brush = np.asarray(brush_extent, dtype=float)
    model = np.asarray(model_bounds, dtype=float)
    if (brush.shape != (6,) or model.shape != (6,) or
            not np.isfinite(np.r_[brush, model]).all() or
            np.any(brush[:3] > brush[3:]) or np.any(model[:3] > model[3:])):
        raise ValueError('Invalid inline model bounds')
    error = float(abs(brush-model).max())
    outside = max(0., float((model[:3]-brush[:3]).max()), float((brush[3:]-model[3:]).max()))
    if outside > .01:
        raise ValueError('Inline brushes exceed captured model bounds')
    return dict(status='equal_within_tolerance' if error <= .01 else 'contained_collision_subset',
                brush_bounds=brush.tolist(), combined_model_bounds=model.tolist(),
                maximum_difference=error, maximum_outside=outside, tolerance=.01,
                geometry_changed=False, ownership_basis='Clipmodel leaf brush references')


def decode(root):
    doc = json.loads((root / 'world_pools_probe.json').read_text())
    if doc['schema'] not in tuple(f'greyhound-bo4-world-pool-probe-v{i}' for i in range(2,9)):
        raise ValueError('Requires full-array probe v2')
    pools = {p['pool_index']: p for p in doc['pools']}
    for i in [11, 14, 118]:
        if not pools[i]['active_count_matches_directory'] or len(pools[i]['assets']) != 1:
            raise ValueError('Ambiguous map allocation')
    tables = {(i, t['label']): t for i, p in pools.items()
              for a in p['assets'] for t in a.get('tables', [])}
    source_files = {}

    def load(label, dtype='<u4', pool=11):
        t = tables[pool, label]
        if t['status'] != 'captured_stable' or not t['readback_unchanged']:
            raise ValueError('Missing/unstable table: ' + label)
        path = root / t['file']
        raw = path.read_bytes()
        if len(raw) != t['count'] * t['stride']:
            raise ValueError('Table byte count changed: ' + label)
        source_files[t['file']] = {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
        return np.frombuffer(raw, dtype=dtype), t

    u32, brush_table = load('records_candidate_2B0')
    records = u32.reshape(-1, 16)
    floats = records.view('<f4')
    pointers = records.view('<u8').reshape(-1, 8)
    raw, vertex_table = load('triples_candidate_290', '<f4')
    vertices = raw.reshape(-1, 3)
    sides, side_table = load('planes_candidate_260', [('plane', '<f4', (4,)), ('material', '<u4')])
    nv, ns = records[:, 14] & 65535, records[:, 14] >> 16
    if int(nv.sum()) != len(vertices) or int(ns.sum()) != len(sides):
        raise ValueError('Brush counts do not account for vertex/side arrays')
    vp, sp = int(vertex_table['pointer'], 16), int(side_table['pointer'], 16)
    if not np.isfinite(vertices).all() or not np.isfinite(sides['plane']).all():
        raise ValueError('Nonfinite geometry')
    norm = np.linalg.norm(sides['plane'][:, :3].astype(float), axis=1)
    if np.max(abs(norm - 1)) > 1e-5:
        raise ValueError('Plane normals differ from measured unit-normal layout')

    brushes, vertex_ranges, side_ranges = [], [], []
    for i, r in enumerate(records):
        vcount, scount = int(nv[i]), int(ns[i])
        vdelta = int(pointers[i, 1]) - vp
        sdelta = int(pointers[i, 0]) - sp
        if vdelta < 0 or vdelta % 12 or vdelta//12 + vcount > len(vertices):
            raise ValueError('Invalid brush vertex range: ' + str(i))
        if scount and (sdelta < 0 or sdelta % 20 or sdelta//20 + scount > len(sides)):
            raise ValueError('Invalid brush side range: ' + str(i))
        vi, si = vdelta//12, sdelta//20 if scount else None
        vertex_ranges.append((vi, vi+vcount))
        if scount: side_ranges.append((si, si+scount))
        points = vertices[vi:vi+vcount].astype(float)
        stored = np.r_[floats[i, 4:7], floats[i, 8:11]].astype(float)
        actual = np.r_[points.min(0), points.max(0)]
        if not np.all(stored[:3] <= stored[3:]):
            raise ValueError('Inverted brush bounds: ' + str(i))
        side_error = 0.
        if scount:
            equations = sides['plane'][si:si+scount].astype(float)
            side_error = float(max(0., (points @ equations[:, :3].T - equations[:, 3]).max()))
        brushes.append({'index': i, 'vertex_start': vi, 'vertex_count': vcount,
                        'side_start': si, 'side_count': scount,
                        'bounds': stored.tolist(), 'vertex_bounds': actual.tolist(),
                        'bounds_max_error': float(abs(stored-actual).max()),
                        'max_vertex_outside_side_plane': side_error,
                        'contents_raw': hex(int(r[7])),
                        'axial_material_u16': records[i, 11:14].view('<u2').tolist(),
                        'coordinate_space': 'Source brush coordinates; ownership not yet decoded'})

    def exact_partition(ranges, length):
        cursor = 0
        for start, end in sorted(ranges):
            if start != cursor: return False
            cursor = end
        return cursor == length
    if not exact_partition(vertex_ranges, len(vertices)) or not exact_partition(side_ranges, len(sides)):
        raise ValueError('Brush ranges overlap or leave holes in the source arrays')

    c, _ = load('clip_models_candidate', '<f4')
    g, _ = load('brush_models_candidate', '<f4', 14)
    c, g = c.reshape(-1, 22), g.reshape(-1, 20)
    if len(c) != len(g): raise ValueError('Clip/gfx model counts differ')
    model_errors = np.max(abs(c[:, :6].astype(float) - g[:, 12:18] - [-1,-1,-1,1,1,1]), axis=1)
    if np.max(model_errors) > 1e-4: raise ValueError('Clip/gfx model index join differs')
    models = [{'index': i, 'clip_bounds': c[i, :6].tolist(), 'gfx_local_bounds': g[i, 12:18].tolist(),
               'gfx_world_bounds': np.r_[g[i, :3], g[i, 4:7]].tolist(),
               'leaf_node_index_candidate': int(c.view('<u4')[i, 18]),
               'clip_gfx_one_unit_expansion_error': float(model_errors[i])}
              for i in range(len(c))]

    ownership = None
    if (11, 'leaf_brush_indices_candidate') in tables:
        node_words, _ = load('brushes_candidate')
        node_words = node_words.reshape(-1, 8)
        leaf_indices, index_table = load('leaf_brush_indices_candidate')
        index_base = int(index_table['pointer'], 16)
        node_count = node_words[:, 1].view('<i4')
        node_pointers = node_words[:, 4:6].copy().view('<u8').ravel()
        used_index_ranges = set()
        reached_nodes = set()

        def leaf_brushes(root_node):
            seen = set()
            def visit(i):
                if i == 0: return []
                if not 0 < i < len(node_words) or i in seen:
                    raise ValueError('Invalid/repeated leaf node')
                seen.add(i); reached_nodes.add(i)
                count = int(node_count[i])
                if count > 0:
                    delta = int(node_pointers[i]) - index_base
                    if delta < 0 or delta % 4 or delta//4+count > len(leaf_indices):
                        raise ValueError('Invalid leaf index pointer')
                    first = delta//4
                    ids = leaf_indices[first:first+count].tolist()
                    if any(j >= len(brushes) for j in ids):
                        raise ValueError('Reachable leaf references nonexistent brush')
                    used_index_ranges.add((first, first+count))
                    return ids
                if count not in (0, -1) or int(node_words[i, 0]) > 2:
                    raise ValueError('Unknown branch layout')
                result = []
                for offset in node_words[i, 6:8]:
                    if not int(offset): raise ValueError('Zero branch offset')
                    result.extend(visit(i+int(offset)))
                if count == -1: result.extend(visit(i+1))
                return result
            return visit(root_node)

        leaves, _ = load('records_candidate_60')
        leaves = leaves.reshape(-1, 14)
        leaf_sets, leaf_errors, empty_leaves = [], [], []
        for leaf_index, leaf in enumerate(leaves):
            ids = leaf_brushes(int(leaf[10]))
            if not ids:
                # zm_towers ends the table with a leaf rooted at node 0 with zero
                # brush contents/bounds: a triangle-only leaf (word 0 = surface
                # tree, word 2 = triangle contents; decode_bo4_triangle_collision).
                # The BSP check below rejects it if the world tree reaches it.
                if int(leaf[10]) or int(leaf[1]) or np.any(leaf.view('<f4')[3:9]):
                    raise ValueError('Brushless collision leaf carries brush data')
                empty_leaves.append({'leaf': leaf_index, 'surface_tree': int(leaf[0].view('<i4')),
                                     'triangle_contents': hex(int(leaf[2]))})
                leaf_errors.append(0.); leaf_sets.append(set())
                continue
            bb = np.array([brushes[j]['bounds'] for j in ids])
            extent = np.r_[bb[:, :3].min(0), bb[:, 3:].max(0)]
            error = float(abs(leaf.view('<f4')[3:9]-extent-[-.125,-.125,-.125,.125,.125,.125]).max())
            contents = int(np.bitwise_or.reduce(records[ids, 7]))
            if error > 1e-4 or contents != int(leaf[1]):
                raise ValueError('Leaf bounds or combined brush contents disagree')
            leaf_errors.append(error); leaf_sets.append(set(ids))

        # Leaf-brush branches follow CoD's cLeafBrushNode: axis +0, split distance +16,
        # child offsets +24/+28. zm_towers: every child-0 brush starts at or above the
        # split, every child-1 brush ends at or below it, the following node of a -1
        # branch holds exactly the straddlers, and node contents OR the subtree's.
        bounds = np.array([b['bounds'] for b in brushes])
        split = node_words.view('<f4')[:, 4]
        split_nodes = 0
        for i in range(1, len(node_words)):
            if node_count[i] > 0 or not (node_words[i, 6] or node_words[i, 7]): continue
            axis, dist = int(node_words[i, 0]), float(split[i])
            above = leaf_brushes(i + int(node_words[i, 6]))
            below = leaf_brushes(i + int(node_words[i, 7]))
            across = leaf_brushes(i + 1) if node_count[i] == -1 else []
            if (above and bounds[above, axis].min() < dist - 1e-3) or (below and bounds[below, axis+3].max() > dist + 1e-3):
                raise ValueError('Leaf-brush split disagrees with brush bounds')
            if across and not np.all((bounds[across, axis] < dist) & (bounds[across, axis+3] > dist)):
                raise ValueError('Straddling leaf-brush set holds a brush on one side of the split')
            if above + below + across and int(node_words[i, 2]) != int(np.bitwise_or.reduce(records[above + below + across, 7])):
                raise ValueError('Leaf-brush node contents disagree with its brushes')
            split_nodes += 1

        # World BSP nodes: plane normal +0, distance +12, signed children +16.
        bsp, _ = load('planes_candidate_50')
        bsp = bsp.reshape(-1, 6)
        planes = bsp.view('<f4')[:, :4].astype(float)
        children = bsp[:, 4].copy().view('<i2').reshape(-1, 2)
        bsp_seen, world_leaves = set(), set()
        bsp_rounding_cases = []
        def walk_bsp(i, path=()):
            if i < 0:
                leaf = -i-1
                if leaf >= len(leaves): raise ValueError('Invalid BSP leaf')
                world_leaves.add(leaf)
                ids = sorted(leaf_sets[leaf])
                for normal, dist, front in path:
                    if not ids: break
                    lo, hi = bounds[ids, :3], bounds[ids, 3:]
                    reach = (np.where(normal > 0, hi, lo) if front else np.where(normal > 0, lo, hi)) @ normal
                    outside = dist-reach if front else reach-dist
                    # Keep graph ownership independent of this approximate bound test.
                    # Float32 brush geometry can lie a few ULPs across a BSP plane.
                    # The existing 0.125 leaf expansion is a hard diagnostic bound,
                    # not a claim about the native traversal's numeric epsilon.
                    if np.any(outside > .125):
                        raise ValueError('World BSP brush separation exceeds captured leaf expansion')
                    for brush, error in zip(ids, outside):
                        if error > 1e-3:
                            magnitude=max(abs(dist), float(np.max(abs(bounds[brush]))), 1.)
                            ulp=float(np.spacing(np.float32(magnitude)))
                            bsp_rounding_cases.append({'leaf':leaf,'brush':brush,'normal':normal.tolist(),
                                'distance':float(dist),'front':front,'outside':float(error),
                                'float32_ulp_at_coordinate_magnitude':ulp,'outside_ulps':float(error/ulp)})
                return
            if i >= len(bsp) or i in bsp_seen: raise ValueError('Invalid BSP node')
            bsp_seen.add(i)
            normal, dist = planes[i, :3], planes[i, 3]
            walk_bsp(int(children[i, 0]), path + ((normal, dist, True),))
            walk_bsp(int(children[i, 1]), path + ((normal, dist, False),))
        walk_bsp(0)
        if world_leaves & {e['leaf'] for e in empty_leaves}: raise ValueError('World BSP reaches a brushless collision leaf')
        world_brushes = set.union(*(leaf_sets[i] for i in world_leaves))
        inline_brushes = set()
        model_sets = [world_brushes]
        # Clip models embed a 56-byte cLeaf_t at +32 (word 8), laid out like the
        # leaf table: surface tree +0, brush contents +4, triangle contents +8,
        # bounds +12, leafbrush root +40 (clip word 18).
        # Clip model 0 is the world: its embedded leaf is zero and the world uses
        # the BSP collision leaves instead.
        embedded = c.view('<u4')[:, 8:22]
        if np.any(embedded[0]): raise ValueError('World clip model embeds a non-empty leaf')
        for model, leaf in zip(models[1:], embedded[1:]):
            model['surface_tree'] = int(leaf[0].view('<i4'))
            model['triangle_contents'] = hex(int(leaf[2]))
        for model in models[1:]:
            leaf = embedded[model['index']]
            if not model['leaf_node_index_candidate']:
                # Brush model with no brush collision (render-only or triangle/xmodel collision).
                if int(leaf[1]) or np.any(leaf.view('<f4')[3:9]):
                    raise ValueError('Brushless clip model carries brush data')
                model['brush_bounds_join_error'] = None; model_sets.append(set())
                continue
            ids = set(leaf_brushes(model['leaf_node_index_candidate']))
            if ids not in leaf_sets: raise ValueError('Inline brush set missing from leaf table')
            bb = np.array([brushes[j]['bounds'] for j in ids])
            extent = np.r_[bb[:, :3].min(0), bb[:, 3:].max(0)]
            if (int(leaf[1]) != int(np.bitwise_or.reduce(records[sorted(ids), 7])) or
                    abs(leaf.view('<f4')[3:9]-extent-[-.125,-.125,-.125,.125,.125,.125]).max() > 1e-4):
                raise ValueError('Clip model embedded leaf disagrees with its brushes')
            model['brush_bounds_check'] = inline_bounds_check(extent, model['gfx_local_bounds'])
            model['brush_bounds_join_error'] = model['brush_bounds_check']['maximum_difference']
            inline_brushes.update(ids); model_sets.append(ids)
        if world_brushes & inline_brushes or world_brushes | inline_brushes != set(range(len(brushes))):
            raise ValueError('World/inline ownership does not partition source brushes')
        for model, ids in zip(models, model_sets):
            model['brush_indices'] = sorted(ids)
            model['ownership_basis'] = ('BSP root 0 leaves' if model['index'] == 0 else
                'Clipmodel leaf brush references' if ids else 'Clipmodel has no brush leaf (root node 0)')
            for j in ids:
                brushes[j].setdefault('model_indices', []).append(model['index'])
                brushes[j]['coordinate_space'] = 'world' if model['index'] == 0 else 'inline_model_local'
        ownership = {'world_brushes': len(world_brushes), 'inline_brushes': len(inline_brushes),
            'world_bsp_nodes': len(bsp_seen), 'world_bsp_leaf_indices': sorted(world_leaves),
            'world_bsp_plane_sides_agree': not bsp_rounding_cases,
            'world_bsp_plane_side_rounding_cases': bsp_rounding_cases,
            'maximum_world_bsp_plane_separation':max((r['outside'] for r in bsp_rounding_cases),default=0.),
            'bsp_validation_policy':'Exact reference graph ownership; approximate bounds separation retained. Reject separation beyond captured leaf expansion0.125; native epsilon not inferred.',
            'leaf_brush_split_nodes_checked': split_nodes,
            'validated_collision_leaves': len(leaves), 'maximum_leaf_bounds_error': max(leaf_errors),
            'brushless_unreferenced_leaves': empty_leaves,
            'clip_model_embedded_leaves_agree': True,
            'collision_subset_of_combined_model_bounds': [m['index'] for m in models
                if m.get('brush_bounds_check', {}).get('status') == 'contained_collision_subset'],
            'brushless_inline_models': [m['index'] for m, ids in zip(models, model_sets) if m['index'] and not ids],
            'all_leaf_contents_agree': True, 'all_brushes_owned': True,
            'index_count_field': index_table['count'],
            'sum_leaf_references': sum(len(leaf_brushes(int(leaf[10]))) for leaf in leaves),
            'max_referenced_index_end': max(end for _, end in used_index_ranges),
            'unreached_nonzero_nodes': sorted(set(range(1,len(node_words)))-reached_nodes),
            'index_storage_note': 'Shared pointer ranges; declared count is not a unique contiguous allocation. Unreferenced tail is not decoded.'}

    e, _ = load('entities', '<u4', 118)
    e = e.reshape(-1, 12); ef = e.view('<f4')
    entity_rows = []
    for i, row in enumerate(e):
        model = int(row[4].view('<i4'))
        if not -1 <= model < len(models): raise ValueError('Entity model index out of range')
        # Measured runtime layout differs from the external source's offset 20.
        # Field +20 is an integer identifier; +24/+36 reproduce placements.
        origin, angles = ef[i, 6:9].astype(float), ef[i, 9:12].astype(float)
        if not np.isfinite(np.r_[origin, angles]).all(): raise ValueError('Nonfinite entity transform')
        out = {'index': i, 'model_index': model, 'origin': origin.tolist(), 'angles': angles.tolist(),
               'property_count': int(row[0]), 'unknown_u32_14': int(row[5]),
               'placement_basis': 'entity authored placement; runtime motion not applied'}
        if model >= 0:
            m = models[model]
            world = np.array(m['gfx_world_bounds'])
            if np.any(world) and not np.any(angles):
                error = float(abs(world - np.array(m['gfx_local_bounds']) - np.r_[origin,origin]).max())
                out['gfx_world_bounds_translation_error'] = error
                out['placement_crosscheck'] = 'agrees' if error < .01 else 'differs; no automatic correction'
            else:
                out['placement_crosscheck'] = 'world bounds unavailable or rotation not validated'
        entity_rows.append(out)

    v, _ = load('vertices_candidate', '<f4'); tri, _ = load('triangles_candidate', '<u4')
    v, tri = v.reshape(-1, 3), tri.reshape(-1, 3)
    if not np.isfinite(v).all() or np.any(tri >= len(v)): raise ValueError('Invalid collision triangle array')
    placed = [r for r in entity_rows if r['model_index'] >= 0]
    summary = {'brush_records': len(brushes), 'brush_vertices': len(vertices), 'brush_sides': len(sides),
        'brush_vertex_and_side_arrays_partition_exactly': True,
        'maximum_bounds_error': max(r['bounds_max_error'] for r in brushes),
        'maximum_side_plane_error': max(r['max_vertex_outside_side_plane'] for r in brushes),
        'clip_gfx_models_matched': len(models), 'maximum_model_join_error': float(model_errors.max()),
        'entities': len(entity_rows), 'entities_referencing_inline_models': len(placed),
        'entity_gfx_placements_agree': sum(r.get('placement_crosscheck') == 'agrees' for r in placed),
        'entity_gfx_placements_differ': sum(r.get('placement_crosscheck') == 'differs; no automatic correction' for r in placed),
        'triangle_vertices': len(v), 'triangles': len(tri), 'triangle_indices_all_in_range': True}
    if ownership: summary['ownership'] = ownership
    return {'schema': 'greyhound-bo4-collision-data-v3', 'summary': summary,
        'sources': source_files, 'brushes': brushes, 'models': models, 'entities': entity_rows,
        'brush_vertices': vertex_table, 'brush_sides': side_table,
        'unfinished': ([] if ownership else ['Brush-to-model leaf/index ownership']) + ['Full entity property keys and values',
            'BO4 contents-to-BO3 tool-material interpretation', 'Resolved runtime placements for moving models',
            'Radiant brush export through existing Greyhound hull pipeline']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('capture', type=Path)
    args = parser.parse_args()
    result = decode(args.capture)
    (args.capture / 'collision_data.json').write_text(json.dumps(result, separators=(',', ':'))+'\n')
    print(json.dumps(result['summary'], indent=2))
