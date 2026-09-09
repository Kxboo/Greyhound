"""Audit saved CW payloads and describe byte windows without assigning geometry semantics."""
import argparse
import collections
import hashlib
import json
import math
from pathlib import Path
import struct


def read_logical(root, evidence, name):
    location = evidence.get('storage', {}).get(name)
    if location:
        offset, size = location['offset'], location['bytes']
        if offset < 0 or size < 0:
            raise ValueError(f'negative storage range: {name}')
        with (root / location['file']).open('rb') as stream:
            stream.seek(offset)
            data = stream.read(size)
        if len(data) != size:
            raise ValueError(f'truncated packed range: {name}')
        return data
    return (root / name).read_bytes()


def describe(data):
    counts = collections.Counter(data)
    n = len(data)
    return {
        'bytes': n, 'nonzero_bytes': n - counts[0],
        'entropy_bits_per_byte': round(-sum((v/n)*math.log2(v/n) for v in counts.values()), 5) if n else 0,
        'distinct_bytes': len(counts),
    }


def audit(root):
    evidence = json.loads((root / 'evidence.json').read_text())
    document = json.loads((root / 'clip_map_models.json').read_text())
    results, errors, exemplars = [], [], []
    verified = {(v.get('address'), v.get('bytes')) for v in evidence.get('verifications', []) if v.get('status') == 'unchanged'}
    for model in document['models']:
        payload = model['payload']
        try:
            data = read_logical(root, evidence, payload['file'])
            words = [int(w, 16) for w in model['descriptor_b']['words']]
            allocation = words[6] & 0xffffffff
            leading = struct.unpack_from('<I', data)[0]
            if not (len(data) == allocation == payload['captured_bytes'] == payload['allocated_bytes']):
                raise ValueError('saved length disagrees with descriptor/JSON')
            if leading != payload['declared_bytes']:
                raise ValueError('leading u32 disagrees with JSON')
            bounds = struct.pack('<6f', *model['mins'], *model['maxs'])
            matches = [o for o in range(0, len(data)-23, 4) if data[o:o+24] == bounds]
            row = {'name': model['name'], 'hash': model['name_hash'],
                   'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
                   'allocation_minus_leading': allocation-leading,
                   'format_high32': hex(words[6] >> 32),
                   'previously_omitted_tail': describe(data[leading:]),
                   'exact_bounds_offsets': matches,
                   'full_range_live_verified': (payload['address'], len(data)) in verified}
            results.append(row)
            if 'ladder' in model['name']:
                exemplars.append({**row, 'mins': model['mins'], 'maxs': model['maxs'],
                    'count_0x20_unresolved': model['count_0x20'],
                    'windows_64': [{'offset': o, **describe(data[o:o+64])} for o in range(0, len(data), 64)],
                    'words_256_384': [{'offset': o, 'u32': struct.unpack_from('<I', data, o)[0],
                                      'hex': data[o:o+4].hex()} for o in range(256, min(384, len(data)-3), 4)]})
        except (OSError, ValueError, KeyError, struct.error) as exc:
            errors.append({'name': model.get('name'), 'error': str(exc)})
    reads = evidence.get('reads', [])
    return {'schema': 'cw-clip-payload-offline-audit-v1', 'source': str(root.resolve()),
            'scope': 'Saved-byte integrity and structural observations; no mesh or topology decoded.',
            'model_count': len(document['models']), 'audited': len(results), 'errors': errors,
            'payload_bytes': sum(r['bytes'] for r in results),
            'size_deltas': dict(collections.Counter(r['allocation_minus_leading'] for r in results)),
            'nonzero_omitted_tails': sum(r['previously_omitted_tail']['nonzero_bytes'] > 0 for r in results),
            'exact_bounds_match_models': sum(bool(r['exact_bounds_offsets']) for r in results),
            'bounds_offset_counts': dict(collections.Counter(o for r in results for o in r['exact_bounds_offsets'])),
            'full_payloads_live_verified': sum(r['full_range_live_verified'] for r in results),
            'capture_required_reads_saved': evidence.get('required_reads_saved'),
            'capture_read_statuses': dict(collections.Counter(r['status'] for r in reads)),
            'empty_filename_write_failures': sum(r['status'] == 'write_failed' and not r.get('file') for r in reads),
            'models': results, 'ladder_exemplars': exemplars}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('capture', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = audit(args.capture)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({k: v for k, v in report.items() if k not in ('models', 'ladder_exemplars')}, indent=2))
    raise SystemExit(1 if report['errors'] else 0)
