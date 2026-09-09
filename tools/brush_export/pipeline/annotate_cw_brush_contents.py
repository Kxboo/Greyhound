"""Attach named-table candidates to packed brush masks without losing unknowns."""
import argparse
import collections
import json
from pathlib import Path
LOW26=0x3ffffff


def annotate_word(word,table):
    if not isinstance(word,int) or not 0<=word<=0xffffffff:
        raise ValueError('Expected a packed32-bit brush word')
    contents=word&LOW26
    names=[];covered=0
    for entry in table:
        mask=int(entry['field_16'],16)
        # Bits26..31 hold the plane count in a packed brush word. Never use
        # table entries such as noDrop/detail/structural to label those bits.
        if mask and mask&~LOW26==0 and contents&mask==mask:
            names.append(entry['name']);covered|=mask
    return dict(raw_packed_word=f'0x{word:08x}',plane_count=word>>26,
                contents_low26=f'0x{contents:08x}',named_contents_candidates=names,
                unnamed_contents_bits=f'0x{contents&~covered:08x}')


def annotate_mask(mask, table):
    """An aggregate contents mask has no single packed word or plane count."""
    if mask & ~LOW26:
        raise ValueError('Expected lower26 contents only')
    row = annotate_word(mask, table)
    return {key:value for key,value in row.items()
            if key not in ('raw_packed_word', 'plane_count')}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('brush_index',type=Path)
    parser.add_argument('--table',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    source=json.loads(args.brush_index.read_text())
    table=json.loads(args.table.read_text())
    if not table.get('readback_unchanged'):
        raise ValueError('Named table was not verified by reread')
    rows=[];counts=collections.Counter();masks=collections.Counter()
    for item in source['items']:
        row=dict(item);row.update(annotate_word(int(item['contents'],16),table['records']))
        rows.append(row);counts.update(row['named_contents_candidates']);masks[row['contents_low26']]+=1
    report=dict(schema='cw_brush_named_contents_candidates_v1',source_index=str(args.brush_index),
                named_table=str(args.table),evidence_status=table['status'],
                summary=dict(brushes=len(rows),with_named_bits=sum(bool(r['named_contents_candidates']) for r in rows),
                             with_unnamed_bits=sum(int(r['unnamed_contents_bits'],16)!=0 for r in rows),
                             name_counts=dict(counts),distinct_masks=len(masks)),
                mask_inventory=[dict(**annotate_mask(int(mask,16),table['records']),brushes=n) for mask,n in masks.most_common()],
                limitations=['Names come directly from a current-build table; its consumer is not traced.',
                             'Properties from different flag columns are never merged.',
                             'Names describe flag candidates, not render materials or complete gameplay behavior.'],
                items=rows)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report['summary'],indent=2))
