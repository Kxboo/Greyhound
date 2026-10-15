"""Read preserved BO4 material DDS mip chains without generating lower levels.

Compressed payloads remain available for D3D uploads. Pillow decoding is used
only for the CPU reference; its BC interpolation need not be bitwise identical
to a GPU's compressed texture sampler.
"""
from pathlib import Path
import hashlib
import io
import struct

import numpy as np
from PIL import Image


BLOCK_BYTES = {71: 8, 72: 8, 74: 16, 75: 16, 77: 16, 78: 16,
               80: 8, 83: 16, 98: 16, 99: 16}
FOURCC_FORMAT = {b'DXT1': 71, b'DXT3': 74, b'DXT5': 77,
                 b'ATI1': 80, b'BC4U': 80, b'ATI2': 83, b'BC5U': 83}


def read_dds(path, decode=True):
    data = Path(path).read_bytes()
    if len(data) < 128 or data[:4] != b'DDS ' or struct.unpack_from('<I', data, 4)[0] != 124:
        raise ValueError(f'{path}: invalid DDS header')
    height, width = struct.unpack_from('<2I', data, 12)
    count = struct.unpack_from('<I', data, 28)[0] or 1
    if not (0 < width <= 16384 and 0 < height <= 16384 and 0 < count <= 15):
        raise ValueError(f'{path}: unsupported DDS dimensions/count')
    fourcc = data[84:88]
    if fourcc == b'DX10':
        if len(data) < 148:
            raise ValueError(f'{path}: truncated DX10 header')
        fmt, dimension, misc, array_size, _ = struct.unpack_from('<5I', data, 128)
        if dimension != 3 or array_size != 1 or misc & 4:
            raise ValueError(f'{path}: expected a single 2D material image')
        start = 148
    else:
        fmt, start = FOURCC_FORMAT.get(fourcc), 128
        if struct.unpack_from('<I', data, 112)[0]:
            raise ValueError(f'{path}: unsupported legacy DDS faces/volume')
    if fmt not in BLOCK_BYTES:
        raise ValueError(f'{path}: unsupported native DDS format {fmt}/{fourcc!r}')
    offset, w, h = start, width, height
    levels, compressed, metadata = [], [], []
    for mip in range(count):
        size = ((w + 3) // 4) * ((h + 3) // 4) * BLOCK_BYTES[fmt]
        payload = data[offset:offset + size]
        if len(payload) != size:
            raise ValueError(f'{path}: truncated mip {mip}')
        compressed.append(payload)
        metadata.append(dict(level=mip, width=w, height=h, offset=offset-start, bytes=size,
            all_zero_payload=not any(payload),
            invalid_bc7_blocks=sum(payload[k] == 0 for k in range(0, size, 16)) if fmt in (98, 99) else 0))
        if decode:
            header = bytearray(data[:start])
            struct.pack_into('<2I', header, 12, h, w)
            struct.pack_into('<I', header, 20, size)
            struct.pack_into('<I', header, 28, 1)
            # Pillow does not accept the BC1/2/3 sRGB enum. The compressed
            # texel decode is identical; apply the view's sRGB curve at sampling.
            if start == 148 and fmt in (72, 75, 78):
                struct.pack_into('<I', header, 128, fmt - 1)
            with Image.open(io.BytesIO(header + payload)) as image:
                levels.append(np.array(image.convert('RGBA')))
        offset += size
        if mip + 1 < count and w == 1 and h == 1:
            raise ValueError(f'{path}: duplicate levels past 1x1')
        w, h = max(1, w >> 1), max(1, h >> 1)
    if offset != len(data):
        raise ValueError(f'{path}: trailing bytes after mip chain')
    return dict(format=fmt, width=width, height=height, mip_count=count,
                complete_to_1x1=metadata[-1]['width'] == metadata[-1]['height'] == 1,
                payload_sha1=hashlib.sha1(data[start:]).hexdigest(),
                dds_sha256=hashlib.sha256(data).hexdigest(),
                metadata=metadata, levels=levels, compressed=compressed)


def load_texture(path, kind):
    from bo4_dxbc_emulator import Texture, srgb_decode_table, UNORM8
    chain = read_dds(path)
    levels = chain.pop('levels')
    if kind == 'r':
        levels = [np.ascontiguousarray(level[:, :, :1]) for level in levels]
    texture = Texture(levels, lut=srgb_decode_table() if kind == 'srgb' else UNORM8)
    texture.native_mips = chain
    texture.native_file = str(path)
    return texture
