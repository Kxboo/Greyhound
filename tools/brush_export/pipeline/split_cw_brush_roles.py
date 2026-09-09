"""Keep assigned collision clip families together, preserving source uncertainty."""
from collections import Counter
import hashlib
import json
import re


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def classify(row, reference, assignments):
    name = row['assigned_material']
    matches = [m for m in reference['materials'] if m['name'] == name]
    if len(matches) != 1:
        return 'other_brushes', 'missing_or_ambiguous_bo3_definition'
    props = matches[0]['properties']
    # Prefab organization follows the assigned BO3 tool family, not which
    # actors it blocks or how certain the original CW interpretation is.
    # Keep fallback clip assignments and their evidence/uncertainty intact.
    if name == 'nosight_noclip' or name == 'clip' or name.startswith('clip_') or name.endswith('_clip'):
        reason = ('assigned_clip_fallback_retained_for_review'
                  if row.get('assignment_status', '').startswith('REVIEW')
                  else 'assigned_bo3_collision_clip_family')
        return 'brushes_clips', reason
    if (props.get('climbType', '<none>') not in ('', '<none>', 'none')
            or props.get('mount') == '1' or name in ('ladder', 'wall_climb', 'pipe_climb')
            or 'mantle' in name):
        return 'other_brushes', 'traversal_tool'
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
    buckets = {'brushes_clips': [], 'other_brushes': []}
    counts = {k: Counter() for k in buckets}
    reasons = Counter()
    filenames = {'brushes_clips': source.name, 'other_brushes': metadata['map'] + '_other_brushes.map'}
    for row, match in zip(rows, matches):
        if int(match[1]) != row['map_brush_index']:
            raise ValueError('Source brush index mismatch')
        block = match[0]
        faces = re.findall(r'^\s*\(.*\)\s+(\S+)\s+.*$', block, re.M)
        if len(faces) != row['face_count'] or set(faces) != {row['assigned_material']}:
            raise ValueError('Face materials differ from metadata')
        role, reason = classify(row, reference, assignments)
        row.update(prefab_file=filenames[role], prefab_brush_index=len(buckets[role]),
                   prefab_role=role, prefab_role_reason=reason)
        buckets[role].append(block)
        counts[role][row['assigned_material']] += 1
        reasons[reason] += 1
    # Keep original brush comments/planes/projections verbatim, including the
    # per-piece projection offsets which prevent merged winding failures.
    if Counter(m[0] for m in matches) != Counter(b for group in buckets.values() for b in group):
        raise ValueError('Split changed brush coverage')
    prefabs = {}
    for role, blocks in buckets.items():
        layers = set(re.findall(r'^layer "([^"]+)"', ''.join(blocks), re.M))
        header = ''.join(line for line in prefix.splitlines(keepends=True)
                         if not re.match(r'^"000_Global/CW_Types/', line)
                         or any('"'+layer+'"' in line or layer.startswith(line.split('"')[1]+'/') for layer in layers))
        dest = folder / filenames[role]
        dest.write_text(header + ''.join(blocks) + suffix)
        prefabs[role] = dict(file=dest.name, sha256=sha(dest), brushes=len(blocks),
                             material_counts=dict(counts[role]))
    metadata['unsplit_map_sha256'] = metadata['map_sha256']
    metadata['map_sha256'] = prefabs['brushes_clips']['sha256']
    metadata['prefabs'] = prefabs
    metadata['role_split'] = dict(version=3, all_brush_blocks_preserved=True,
        geometry_materials_and_projection_offsets_unchanged=True, reasons=dict(reasons),
        policy='Primary prefab keeps assigned BO3 clip families, including nosight_noclip, missile, physics, AI, AI-wallrun and unresolved clip fallbacks. Membership does not imply physical collision. Original source flags and assignment uncertainty remain unchanged. Traversal and other tool families are separate.',
        row_index_note='map_brush_index retains the source index/comment; prefab_brush_index is the ordinal within prefab_file.')
    metadata_path.write_text(json.dumps(metadata, indent=2))
    return prefabs
