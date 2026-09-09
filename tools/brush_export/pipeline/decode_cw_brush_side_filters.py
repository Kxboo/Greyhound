"""Decode code-traced brush-side filter indices; names require a paired table.

Current @336 collision layout only. Does not change geometry or call game code.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import struct

from export_cross_map_cw_geometry import decode_brushes
from annotate_cw_triangle_surfaces import describe


def u32(raw, at):
    return struct.unpack_from('<I', raw, at)[0]


def decode(raw, model, filters=None, names=None):
    if len(raw) < 520:
        raise ValueError('Truncated shape header')
    geo = decode_brushes(raw, model)
    if not geo or geo.get('status') != 'decoded':
        raise ValueError('Unsupported or invalid brush geometry')
    nb = geo['brush_count']
    # Pointer-backed models independently check this compact layout rule.
    starts_at = geo['vertex_offset'] + 12 * geo['vertex_count'] + 8 * nb
    packed_at = (starts_at + 4 * nb + 7) & ~7
    if starts_at < 520 or packed_at > geo['bounds_offset']:
        raise ValueError('Side arrays outside brush data')
    address = int(model['payload']['address'], 16)
    pointers = [struct.unpack_from('<Q', raw, off)[0] for off in (456, 416)]
    if any(pointers):
        if pointers != [address + starts_at, address + packed_at]:
            raise ValueError('Side pointers disagree with allocation layout')
    starts = [u32(raw, starts_at + 4*i) for i in range(nb)]
    ordered = sorted(geo['brushes'], key=lambda x: x['brush_index'])
    ranges = [(starts[i], starts[i] + 6 + b['nonaxial_plane_count'])
              for i, b in enumerate(ordered)]
    # This is an observed validity invariant; reject rather than guessing if it changes.
    cursor = 0
    for first, end in sorted(ranges):
        if first != cursor:
            raise ValueError('Side ranges overlap or leave a gap')
        cursor = end
    packed_bytes = 8*((cursor + 5)//6)
    if packed_at + packed_bytes != geo['bounds_offset']:
        raise ValueError('Packed side array does not end at brush records')
    if filters is not None and (not filters or len(filters) > 1024):
        raise ValueError('Invalid paired filter table count')
    rows = []
    side_categories = Counter()
    union_mismatches = []
    for i, b in enumerate(ordered):
        sides = []
        union = 0
        for side in range(6 + b['nonaxial_plane_count']):
            slot = starts[i] + side
            word = struct.unpack_from('<Q', raw, packed_at + 8*(slot//6))[0]
            fi = (word >> (10*(slot % 6))) & 1023
            item = dict(side_index=side, filter_slot=slot, filter_index=fi)
            if side < 6:
                item.update(kind='axial', axis='xyz'[side//2],
                            bound='min' if side % 2 == 0 else 'max')
            else:
                item.update(kind='nonaxial', brush_plane_index=side-6)
            if filters is not None:
                if fi >= len(filters):
                    raise ValueError('Side index outside paired filter table')
                low, high = filters[fi]
                item.update(raw_low32=hex(low), contents=hex(high))
                union |= high
                if names is not None:
                    item.update(describe(low, high, *names))
                    side_categories[item['surface_category_candidate'] or
                                    f"unknown_category_{item['category_id']}"] += 1
            sides.append(item)
        row = dict(brush_index=i, side_start=starts[i],
                   contents=hex(b['collision_flags_raw']), sides=sides)
        if filters is not None:
            row.update(side_contents_union=hex(union),
                       union_matches_brush=union == b['collision_flags_raw'])
            if not row['union_matches_brush']:
                union_mismatches.append(i)
        rows.append(row)
    # The high four bits of each packed word are retained as observations, not named.
    high_nibbles = Counter(struct.unpack_from('<Q', raw, at)[0] >> 60
                          for at in range(packed_at, packed_at + packed_bytes, 8))
    return dict(name_hash=model['name_hash'], payload_sha256=hashlib.sha256(raw).hexdigest(),
                brush_count=nb, side_count=cursor, side_starts_offset=starts_at,
                packed_filters_offset=packed_at, packed_filter_bytes=packed_bytes,
                pointer_layout_verified=bool(all(pointers)), complete_side_partition=True,
                packed_high_nibbles=dict(high_nibbles),
                paired_filter_table=filters is not None,
                side_contents_union_mismatches=union_mismatches if filters is not None else None,
                category_counts=dict(side_categories), brushes=rows)


def run(root, paired=False):
    filters = names = None
    if paired:
        evidence = json.loads((root/'report.json').read_text())
        if not evidence.get('readback_unchanged'):
            raise ValueError('Capture readback not verified')
        table = (root/'filter-table.bin').read_bytes()
        if len(table) != evidence['filter_count']*8:
            raise ValueError('Paired filter table length mismatch')
        filters = list(struct.iter_unpack('<II', table))
        tables = json.loads(Path('research/cw-clip/triangle-mask-trace/surface-tables/report.json').read_text())
        flags = json.loads(Path('research/cw-clip/brush-mask-callers/named-flag-table.json').read_text())
        if not tables['readback_unchanged']:
            raise ValueError('Category table readback not verified')
        names = (tables['tables'][0]['records'], flags['records'], tables['tables'][1]['records'])
        sources = [(m['model_index'], m['model'], m['payload_sha256']) for m in evidence['models']]
    else:
        sources = [(i, m, None) for i, m in enumerate(json.loads((root/'clip_map_models.json').read_text())['models'])]
    rows, skipped = [], []
    for i, model, expected in sources:
        raw = (root/model['payload']['file']).read_bytes()
        if expected and hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError('Payload does not match paired capture')
        if len(raw) < 520 or raw[336:360] != struct.pack('<6f', *(model['mins']+model['maxs'])) or not u32(raw,368):
            skipped.append(i)
            continue
        result = decode(raw, model, filters, names)
        result['model_index'] = i
        if not paired:
            # Full side annotations are reserved for capture-paired examples.
            result.pop('brushes')
        rows.append(result)
    summary = dict(models=len(rows), brushes=sum(r['brush_count'] for r in rows),
                   sides=sum(r['side_count'] for r in rows),
                   pointer_layout_checks=sum(r['pointer_layout_verified'] for r in rows),
                   union_checks=sum(r['brush_count'] for r in rows) if paired else 0,
                   union_mismatches=sum(len(r['side_contents_union_mismatches']) for r in rows) if paired else None)
    return dict(summary=summary, models=rows, skipped_model_indices=skipped,
                filter_table_sha256=hashlib.sha256(table).hexdigest() if paired else None,
                scope='brush side constraints; not necessarily nonzero-area polygon faces',
                category_status='named-table candidates; render materials not recovered')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    parser.add_argument('--paired', action='store_true')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = run(args.root, args.paired)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result['summary'], indent=2))
