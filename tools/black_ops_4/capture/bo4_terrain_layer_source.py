"""BO4 terrain layers from their captured expanded records, without material guesses.

Native path verified against the running BO4 executable on 2026-10-12:
prepare 0x3CB4450, texture lookup 0x3CBFDF0, pack 0x3CBF0B0.
The 264-byte source layer contains a 196-byte parameter block at +0x40.
Preparation inserts the sector's weight slice and eight image descriptors.
This module reproduces that path offline. It does not bake or read game memory.
Ground-cover overrides need an additional runtime setting and are rejected.
"""
import hashlib
import math
from pathlib import Path
import struct

SOURCE_BYTES = 264
PARAMETER_BYTES = 196
RUNTIME_BYTES = 112
SEMANTICS = (0xFBFD3A43, 0xA0AB1041, 0x199A03D3, 0xEB529B4D,
             0x59D30D0F, 0x34D849D5, 0x6D0A6C98, 0xEC443804)
DESCRIPTOR_OFFSETS = (0x2C, 0x80, 0x84, 0x90, 0x8C, 0x98, 0x9C, 0xA0)


class SourceUnavailable(ValueError):
    """A capture lacks inputs required for native-equivalent reconstruction."""


def _source_file(root, relative):
    root = Path(root).resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise ValueError('Terrain source path escapes capture')
    return path


def half_bits(bits):
    """BO4's bitwise float-to-half conversion, including its exponent clamp.

    This truncates the mantissa and saturates large values; it is not Python's
    IEEE round-to-nearest half conversion. Underflow keeps the selected mantissa
    bits while clamping the exponent, exactly as the native routine does.
    """
    exponent = ((bits >> 23) & 0xFF) - 112
    sign = (bits >> 16) & 0x8000
    if exponent > 30:
        return sign | 0x7BFF
    return sign | (max(0, exponent) << 10) | ((bits >> 13) & 0x3FF)


def unorm8(bits):
    value = struct.unpack('<f', struct.pack('<I', bits))[0]
    try:
        scaled = struct.unpack('<f', struct.pack('<f', value * 255.0))[0]
    except OverflowError:
        return 0
    # x86 CVTTSS2SI returns INT_MIN for NaN/infinity/out-of-range. The following
    # signed clamps in BO4 then return zero.
    if not math.isfinite(scaled) or not -(1 << 31) <= scaled < (1 << 31):
        return 0
    return min(255, max(0, math.trunc(scaled)))


def pack_parameters(parameters):
    """Pack the prepared native 196-byte structure into the shader's 112 bytes."""
    if len(parameters) != PARAMETER_BYTES:
        raise ValueError('Expected 196 prepared layer bytes')
    source = struct.unpack('<49I', parameters)
    u = lambda at: source[at // 4]
    h = lambda at: half_bits(u(at))
    byte = lambda at: unorm8(u(at))
    pair = lambda at: h(at) | (h(at + 4) << 16)
    words = list(source[:8]) + [0] * 20
    words[8] = u(0x24)
    for index, offset in ((9, 0x34), (10, 0x3C), (11, 0x44), (12, 0x5C),
                          (14, 0xA4), (15, 0xAC), (16, 0xB4)):
        words[index] = pair(offset)
    words[13] = (u(0x20) & 0xFFFF) | (h(0x30) << 16)
    words[17] = h(0xBC) | ((u(0x28) & 0xFF) << 16) | (byte(0x58) << 24)
    words[18] = byte(0x64) | (byte(0x68) << 8) | (byte(0x78) << 16) | ((u(0x7C) & 0xFF) << 24)
    words[19] = (((((u(0xC0) & 3) << 16) | (h(0x4C) & 0xFFC0)) << 2
                  | (u(0x94) & 0xFF)) << 8) | (u(0x88) & 0xFF)
    for index, color_offset, descriptor_offset in ((20, 0x50, 0x2C), (21, 0x54, 0x80),
                (22, 0x6C, 0x84), (23, 0x70, 0x8C), (24, 0x74, 0x90)):
        words[index] = ((h(color_offset) << 16) & 0xFFC00000) | (u(descriptor_offset) & 0x3FFFFF)
    words[25:28] = [u(offset) & 0x3FFFFF for offset in (0x98, 0x9C, 0xA0)]
    return struct.pack('<28I', *(word & 0xFFFFFFFF for word in words))


def prepare_parameters(source, weight_slice, texture_bindings, image_descriptors):
    """Prepare one layer using its own flags and the captured image registry.

    texture_bindings maps numeric material semantic -> numeric image pointer.
    image_descriptors maps numeric image pointer -> the native packed descriptor.
    A semantic absent from the material leaves its source default unchanged.
    A bound image absent from the terrain registry resolves to zero, as in BO4.
    """
    if len(source) != SOURCE_BYTES:
        raise ValueError('Expected one 264-byte expanded layer')
    if source[0x3D]:
        raise SourceUnavailable('Ground-cover override requires its runtime setting')
    if not 0 <= weight_slice <= 0xFFFF:
        raise ValueError('Weight-slice value does not fit the captured u16 table')
    parameters = bytearray(source[0x40:0x104])
    struct.pack_into('<I', parameters, 0x24, weight_slice)
    for semantic, offset in zip(SEMANTICS, DESCRIPTOR_OFFSETS):
        if semantic in texture_bindings:
            struct.pack_into('<I', parameters, offset, image_descriptors.get(texture_bindings[semantic], 0))
    return bytes(parameters)


def image_registry(root, probe):
    """Read the terrain asset's native 48-byte image entries from the raw probe."""
    region = next((r for r in probe.get('regions', []) if r.get('header_offset') == '0x90' and r.get('file')), None)
    if region is None or not probe.get('asset', {}).get('header_file'):
        raise SourceUnavailable('Capture lacks the terrain image registry')
    header = _source_file(root, probe['asset']['header_file']).read_bytes()
    if len(header) < 152:
        raise SourceUnavailable('Truncated terrain header')
    count, pointer = struct.unpack_from('<QQ', header, 0x88)
    if not 0 < count <= 4096 or int(region['pointer'], 16) != pointer:
        raise SourceUnavailable('Terrain image registry identity/count is invalid')
    data = _source_file(root, region['file']).read_bytes()
    if len(data) < count * 48:
        raise SourceUnavailable('Terrain image registry was not captured in full')
    descriptors = {}
    for offset in range(0, count * 48, 48):
        image, fmt = struct.unpack_from('<QI', data, offset)
        slot, minimum_mip = struct.unpack_from('<II', data, offset + 20)
        array = {78: 1, 99: 2}.get(fmt, 0)
        word = (slot | (minimum_mip << 16) | (array << 20)) & 0xFFFFFFFF
        if image in descriptors and descriptors[image] != word:
            raise SourceUnavailable('Conflicting descriptors for one terrain image')
        descriptors[image] = word
    return descriptors, {'file': region['file'], 'entry_bytes': 48, 'entry_count': count,
                         'sha256': hashlib.sha256(data[:count * 48]).hexdigest()}


def source_layer_records(root, sector, descriptors):
    """Return each source layer's bytes and native-equivalent packed record.

    Results are derived from captured inputs. They are not labeled as observed
    runtime uploads, even when they match uploads from another sector.
    """
    sides = sector.get('side_arrays', [])
    binding_side = next((s for s in sides if s.get('count_offset') == '0x110' and s.get('file')), None)
    weight_side = next((s for s in sides if s.get('count_offset') == '0x138' and s.get('file')), None)
    if binding_side is None or weight_side is None:
        raise SourceUnavailable('Capture lacks expanded layers or the weight table')
    layers = binding_side.get('layers', [])
    count = binding_side['count']
    if len(layers) != count:
        raise SourceUnavailable('Expanded source layer count does not match decoded bindings')
    data = _source_file(root, binding_side['file']).read_bytes()
    weights = _source_file(root, weight_side['file']).read_bytes()
    if len(data) < count * SOURCE_BYTES or len(weights) < weight_side['count'] * 2:
        raise SourceUnavailable('Truncated source layer or weight data')
    result = {}
    for layer in layers:
        slot = layer['layer']
        if not 0 <= slot < count or slot in result:
            raise ValueError('Invalid/duplicate terrain layer slot')
        raw = data[slot * SOURCE_BYTES:(slot + 1) * SOURCE_BYTES]
        if struct.unpack_from('<Q', raw)[0] != int(layer['material'], 16):
            raise ValueError('Expanded source material differs from decoded binding')
        if raw[0x10:0x30] != struct.pack('<8f', *layer['uv']):
            raise ValueError('Expanded source UV differs from decoded binding')
        index = struct.unpack_from('<I', raw, 0x34)[0]
        if index >= weight_side['count']:
            raise ValueError('Source layer weight index is outside its table')
        weight = struct.unpack_from('<H', weights, index * 2)[0]
        bindings = {int(t['semantic'], 16): int(t['image'], 16) for t in layer.get('images', [])}
        parameters = prepare_parameters(raw, weight, bindings, descriptors)
        result[slot] = {'source': raw, 'prepared': parameters, 'packed': pack_parameters(parameters),
                        'file': binding_side['file'], 'byte_offset': slot * SOURCE_BYTES,
                        'source_sha256': hashlib.sha256(raw).hexdigest()}
    return result
