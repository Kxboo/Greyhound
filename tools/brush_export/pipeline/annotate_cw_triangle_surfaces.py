"""Annotate same-capture filter entries; distinguish categories from bit flags."""
import collections
import hashlib
import json
from pathlib import Path
import struct

TYPE_MASK=0x03f00000
TRAVERSAL_MASK=0x38000000


def describe(low, high, categories, flags, traversal):
    encoded=low&TYPE_MASK
    names=[r['name'] for r in categories if int(r['field_12'],16)==encoded]
    traversal_value=low&TRAVERSAL_MASK
    traversal_names=[r['name'] for r in traversal if int(r['field_12'],16)==traversal_value]
    rest=low&~(TYPE_MASK|TRAVERSAL_MASK)
    named=[];covered=0
    for row in flags:
        mask=int(row['field_12'],16)
        if mask and not mask&(TYPE_MASK|TRAVERSAL_MASK) and rest&mask==mask:
            named.append(row['name']);covered|=mask
    return dict(raw_low32=hex(low),contents=hex(high),category_id=encoded>>20,
        surface_category_candidate=names[0] if len(names)==1 else None,
        traversal_code_candidate=traversal_value>>27,
        traversal_name_candidate=traversal_names[0] if len(traversal_names)==1 else None,
        surface_flag_candidates=named,unknown_noncategory_bits=hex(rest&~covered))


def run(root, surface_table, named_flags):
    tables=json.loads(surface_table.read_text())
    if not tables['readback_unchanged']:raise ValueError('Unverified surface table')
    categories=tables['tables'][0]['records']
    traversal=tables['tables'][1]['records']
    flags=json.loads(named_flags.read_text())['records']
    evidence=json.loads((root/'report.json').read_text())
    raw=(root/'filter-table.bin').read_bytes()
    if len(raw)!=evidence['filter_count']*8:raise ValueError('Filter table count mismatch')
    entries=[describe(lo,hi,categories,flags,traversal) for lo,hi in struct.iter_unpack('<II',raw)]
    models=[]
    for model in evidence['models']:
        payload=(root/f"{model['model_index']}.bin").read_bytes()
        if hashlib.sha256(payload).hexdigest()!=model['payload_sha256']:
            raise ValueError('Payload association mismatch')
        groups=[]
        for g in model['groups']:
            entry=entries[g['filter_index']]
            if int(g['filter_contents'],16)!=int(entry['contents'],16) or int(g['filter_unknown_low32'],16)!=int(entry['raw_low32'],16):
                raise ValueError('Group/filter association mismatch')
            groups.append(dict(index=g['index'],filter_index=g['filter_index'],triangle_count=g['triangle_count'],**entry))
        models.append(dict(model_index=model['model_index'],groups=groups))
    return dict(status='named-table surface candidates; exact table consumer unresolved',
        category_mask=hex(TYPE_MASK),category_zero_name='unresolved',
        filter_table_sha256=hashlib.sha256(raw).hexdigest(),entries=entries,models=models,
        summary=dict(filter_entries=len(entries),named_category_entries=sum(e['surface_category_candidate'] is not None for e in entries),
            distinct_category_ids=sorted({e['category_id'] for e in entries}),
            category_counts=dict(collections.Counter(e['surface_category_candidate'] or f"unknown_category_{e['category_id']}" for e in entries))))


if __name__=='__main__':
    root=Path('research/cw-clip/triangle-mask-trace/live-examples')
    report=run(root,Path('research/cw-clip/triangle-mask-trace/surface-tables/report.json'),
               Path('research/cw-clip/brush-mask-callers/named-flag-table.json'))
    (root/'surface-candidates.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report['summary'],indent=2))
