"""Route brush prefabs using captured behavior before stock material names."""

# Support direct execution and the isolated packaged Python runtime.
import sys as _tool_sys
from pathlib import Path as _ToolPath
TOOLS_ROOT = next(p for p in _ToolPath(__file__).resolve().parents if (p / "tool_bootstrap.py").is_file())
_tool_sys.path.insert(0, str(TOOLS_ROOT))
import tool_bootstrap as _tool_bootstrap
_tool_bootstrap.activate(__file__)
REPO_ROOT = TOOLS_ROOT.parent
from collections import Counter
import hashlib
import json
import re
from cw_collision_role_policy import POLICY, REFERENCE_MATERIAL, REFERENCE_LAYER, reference_reason, reference_properties


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def classify(row, reference, assignments):
    name = row['assigned_material']
    key = row.get('material_assignment_key')
    if key is None and 'collision_asset_index' in row and 'brush_index' in row:
        # Automatic material application is optional; source-role exclusions
        # still apply to its original generic material assignments.
        key = f"{row['collision_asset_index']}:{row['brush_index']}"
    assignment = assignments.get('brushes', {}).get(key, {})
    reason = reference_reason(assignment, {})
    if reason:
        return 'reference_brushes', reason
    matches = [m for m in reference['materials'] if m['name'] == name]
    if len(matches) != 1:
        return 'other_brushes', 'missing_or_ambiguous_bo3_definition'
    props = matches[0]['properties']
    if (props.get('climbType', '<none>') not in ('', '<none>', 'none')
            or props.get('mount') == '1' or name in ('ladder', 'wall_climb', 'pipe_climb')
            or 'mantle' in name):
        return 'other_brushes', 'traversal_tool'
    clip = name == 'nosight_noclip' or 'clip' in name.split('_')
    reason = reference_reason(assignment, props if clip else {})
    if reason:
        return 'reference_brushes', reason
    if clip:
        reason = ('assigned_clip_fallback_retained_with_unknown_source_behavior'
                  if row.get('assignment_status', '').startswith('REVIEW')
                  else 'assigned_bo3_collision_clip_family')
        return 'brushes_clips', reason
    return 'other_brushes', 'other_bo3_tool_family'


def split(folder, reference):
    metadata_path = folder / 'collision_metadata.json'
    metadata = json.loads(metadata_path.read_text())
    source = folder / (metadata['map'] + '_brush_collision.map')
    if sha(source) != metadata['map_sha256']:
        raise ValueError('Brush map differs from its source metadata')
    text = source.read_text()
    # The exporter emits only a worldspawn followed by complete brush blocks.
    pattern = re.compile(r'^// brush (\d+)\n\{\n.*?^\}\n', re.M | re.S)
    matches = list(pattern.finditer(text))
    rows = metadata['rows']
    if len(matches) != len(rows) or not matches:
        raise ValueError('Brush block coverage differs from metadata')
    prefix, suffix = text[:matches[0].start()], text[matches[-1].end():]
    if not re.search(r'"classname"\s+"worldspawn"', prefix) or suffix.strip() != '}':
        raise ValueError('Expected a single worldspawn brush export')
    if any(text[a.end():b.start()].strip() for a,b in zip(matches, matches[1:])):
        raise ValueError('Unaccounted text between brush blocks')
    assignments_path = folder / 'material_assignments.json'
    assignments = json.loads(assignments_path.read_text()) if assignments_path.exists() else {}
    reference_properties(reference)
    buckets = {'brushes_clips': [], 'other_brushes': [], 'reference_brushes': []}
    counts = {k: Counter() for k in buckets}
    reasons = Counter()
    filenames = {'brushes_clips': source.name, 'other_brushes': metadata['map'] + '_other_brushes.map',
                 'reference_brushes': metadata['map'] + '_nonblocking_reference.map'}
    material_changes = 0
    for row, match in zip(rows, matches):
        if int(match[1]) != row['map_brush_index']:
            raise ValueError('Source brush index mismatch')
        block = match[0]
        faces = re.findall(r'^\s*\(.*\)\s+(\S+)\s+.*$', block, re.M)
        if len(faces) != row['face_count'] or set(faces) != {row['assigned_material']}:
            raise ValueError('Face materials differ from metadata')
        role, reason = classify(row, reference, assignments)
        if role == 'reference_brushes':
            old_material = row['assigned_material']
            block, changed = re.subn(r'(^\s*\(.*\)\s+)' + re.escape(old_material) + r'(?=\s)',
                                    lambda m: m[1] + REFERENCE_MATERIAL, block, flags=re.M)
            if changed != row['face_count']:
                raise ValueError('Reference material replacement missed a face')
            row.update(collision_candidate_material=old_material, assigned_material=REFERENCE_MATERIAL,
                       reference_material_policy=POLICY, previous_layer=row.get('layer'),
                       layer=REFERENCE_LAYER, compile_excluded=True)
            block, layers_changed = re.subn(r'^layer "[^"]+"$', 'layer "'+REFERENCE_LAYER+'"', block, flags=re.M)
            if layers_changed != 1:
                raise ValueError('Reference brush must have exactly one editor layer')
            material_changes += old_material != REFERENCE_MATERIAL
        row.update(prefab_file=filenames[role], prefab_brush_index=len(buckets[role]),
                   prefab_role=role, prefab_role_reason=reason)
        buckets[role].append(block)
        counts[role][row['assigned_material']] += 1
        reasons[reason] += 1
    # Only material and editor layer may change. All comments, planes,
    # transforms and per-piece projection offsets must remain verbatim.
    def geometry(block):
        block = re.sub(r'^layer "[^"]+"$', 'layer "<ROLE>"', block, flags=re.M)
        return re.sub(r'(^\s*\(.*\)\s+)\S+(?=\s)', r'\1<MATERIAL>', block, flags=re.M)
    if Counter(geometry(m[0]) for m in matches) != Counter(geometry(b) for group in buckets.values() for b in group):
        raise ValueError('Split changed brush coverage')
    prefabs = {}
    for role, blocks in buckets.items():
        layers = set(re.findall(r'^layer "([^"]+)"', ''.join(blocks), re.M))
        header = ''.join(line for line in prefix.splitlines(keepends=True)
                         if not re.match(r'^"000_Global/CW_Types/', line)
                         or any('"'+layer+'"' in line or layer.startswith(line.split('"')[1]+'/') for layer in layers))
        if role == 'reference_brushes':
            # Corvid's BO3 No Comp layer uses `ignore`. Keep it visible here:
            # references remain selectable in Radiant, outside BSP compilation.
            header = header.replace('iwmap 4\n', 'iwmap 4\n"'+REFERENCE_LAYER+'" flags ignore\n', 1)
        dest = folder / filenames[role]
        dest.write_text(header + ''.join(blocks) + suffix)
        prefabs[role] = dict(file=dest.name, sha256=sha(dest), brushes=len(blocks),
                             material_counts=dict(counts[role]))
        if role == 'reference_brushes':
            prefabs[role].update(compile_excluded=True, editor_layer=REFERENCE_LAYER)
    metadata['unsplit_map_sha256'] = metadata['map_sha256']
    metadata['map_sha256'] = prefabs['brushes_clips']['sha256']
    metadata['prefabs'] = prefabs
    metadata['role_split'] = dict(version=4, all_brush_blocks_preserved=True,
        geometry_and_projection_offsets_unchanged=True, reasons=dict(reasons),
        reference_material_changes=material_changes, policy_id=POLICY,
        reference_layer=REFERENCE_LAYER, reference_layer_flags=['ignore'],
        policy='Source non-solid/no-query brushes, zero-contents brushes with unjoined surfaces, and clip candidates that add player collision to fully decoded non-player query masks are separate nonblocking references. Reference status does not prove the source had no other collision queries. Unknown contents are not treated as empty. Original selected materials and source assignments remain recorded. Traversal and other tools are separate.',
        row_index_note='map_brush_index retains the source index/comment; prefab_brush_index is the ordinal within prefab_file.')
    metadata_path.write_text(json.dumps(metadata, indent=2))
    return prefabs
