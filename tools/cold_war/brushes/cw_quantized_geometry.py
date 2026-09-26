"""Decode captured CW quantized collision coordinates and counted shape streams.

The layout is supported by pointer/extent checks on the September 2026 captures.
Coordinate arithmetic follows C77B2A3..C77B34F, C778EE0 and C779AF0. Triangle
strip connectivity/winding and shape transform selectors remain separate research
questions. This module never supplies render materials or applies placements.
"""
from dataclasses import dataclass
import math
import struct


def f32(value):
    return struct.unpack('<f', struct.pack('<f', value))[0]


def axis_scales(minimum, maximum):
    if len(minimum) != 3 or len(maximum) != 3:
        raise ValueError('Expected three-axis bounds')
    if not all(math.isfinite(v) for v in (*minimum, *maximum)):
        raise ValueError('Nonfinite quantized bounds')
    if any(lo > hi for lo, hi in zip(minimum, maximum)):
        raise ValueError('Inverted quantized bounds')
    reciprocal = struct.unpack('<f', bytes.fromhex('80008037'))[0]
    try:
        scales = tuple(f32(max(8191.0, f32(hi-lo)) * reciprocal)
                       for lo, hi in zip(minimum, maximum))
    except OverflowError as error:
        raise ValueError('Quantized bounds exceed float32 range') from error
    if not all(math.isfinite(v) and v > 0 for v in scales):
        raise ValueError('Invalid quantized coordinate scale')
    return scales


def coordinate(minimum, scale, value, block=0):
    # Insert the nibble BEFORE float32 multiplication. Multiplying the byte
    # and adding a separately scaled block introduces different rounding.
    return minimum + f32((value + 256 * block) * scale)


@dataclass(frozen=True)
class Group:
    word: int
    width: int
    strip: bool
    start: int
    count: int
    axis_blocks: tuple
    vertices: tuple


@dataclass(frozen=True)
class Shape:
    index: int
    header_offset: int
    transform_selector: int
    minimum: tuple
    maximum: tuple
    scales: tuple
    contents: int
    surface_word: int
    n8: int
    n16: int
    stream_start: int
    stream_end: int
    tree_offset: int
    tree_bytes: int
    checked_pointers: int
    groups: tuple


@dataclass(frozen=True)
class Payload:
    selectors: bytes
    shapes: tuple
    extra_count: int
    extra_offset: int | None
    known_end: int


def decode_payload(raw, payload_address=None, *, apply_axis_offsets=True):
    """Decode every quantized shape; retain the separate extra-section boundary.

    Nonzero relocation pointers require the captured allocation address. Absent
    pointers can be serialized data; they do not justify guessing an address.
    No bounds-fitting or rescaling of the decoded coordinates is performed.
    """
    if len(raw) < 304:
        raise ValueError('Truncated collision payload header')
    selectors, count, extra = struct.unpack_from('<HHI', raw, 296)
    if count > 1024 or extra not in (0, 1):
        raise ValueError('Unsupported collision shape counts')
    header_start = (304 + selectors + 7) & ~7
    cursor = header_start + count * 80
    if cursor > len(raw):
        raise ValueError('Shape table outside payload')
    result = []
    for index in range(count):
        at = header_start + 80 * index
        pointers = struct.unpack_from('<4Q', raw, at)
        tree_bytes, selector, ng, n8, n16 = struct.unpack_from('<I4H', raw, at+32)
        bounds = struct.unpack_from('<6f', raw, at+44)
        lo, hi = bounds[:3], bounds[3:]
        scales = axis_scales(lo, hi)
        contents, surface = struct.unpack_from('<II', raw, at+68)
        byte_start = cursor
        word_start = (byte_start + 3*n8 + 1) & ~1
        group_start = (word_start + 6*n16 + 3) & ~3
        tree_start = group_start + 4*ng
        end = tree_start + tree_bytes
        if end > len(raw):
            raise ValueError(f'Shape {index} streams outside payload')
        checked = 0
        for pointer, expected in zip(pointers, (word_start, byte_start, group_start, tree_start)):
            if pointer:
                if payload_address is None or pointer != payload_address + expected:
                    raise ValueError(f'Shape {index} relocation pointer disagrees with allocation')
                checked += 1
        groups = []
        for gi in range(ng):
            word = struct.unpack_from('<I', raw, group_start + 4*gi)[0]
            width = 1 if word >> 31 else 2
            strip = bool(word & (1 << 30))
            field = (word >> 26) & 15
            number = field+3 if strip else 3*(field+1)
            start = word & 0x3fff
            if start + number > (n8 if width == 1 else n16):
                raise ValueError(f'Shape {index} group {gi} vertex range outside stream')
            offset = (byte_start if width == 1 else word_start) + 3*width*start
            values = struct.unpack_from('<'+str(3*number)+('B' if width == 1 else 'H'), raw, offset)
            blocks = tuple((word >> (14+4*a)) & 15 if width == 1 else 0 for a in range(3))
            vertices = []
            for j in range(number):
                vertex = []
                for axis in range(3):
                    k = axis*number+j if strip else (j % 3)*3*(field+1)+axis*(field+1)+j//3
                    vertex.append(coordinate(lo[axis], scales[axis], values[k],
                                             blocks[axis] if apply_axis_offsets else 0))
                vertices.append(tuple(vertex))
            groups.append(Group(word, width, strip, start, number, blocks, tuple(vertices)))
        result.append(Shape(index, at, selector, lo, hi, scales, contents, surface,
                            n8, n16, cursor, end, tree_start, tree_bytes, checked, tuple(groups)))
        # There is no padding between a shape's tree and the next byte stream.
        cursor = end
    extra_offset = (cursor+7) & ~7 if extra else None
    if extra:
        if extra_offset + 24 + 184 > len(raw):
            raise ValueError('Truncated extra collision section')
    elif (cursor+3) & ~3 != len(raw):
        raise ValueError('Unaccounted bytes after quantized collision streams')
    return Payload(bytes(raw[304:304+selectors]), tuple(result), extra, extra_offset, cursor)
