# Adapted from TerrainReconstructor native source intake.
# MIT License
#
# Copyright (c) 2026 SuperTerrain contributors
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

"""Native BO4 terrain source intake; independent BC4 fields stay independent.

No CW index map, baked albedo reference, guessed tint or blend constants are
introduced. Binary files are mapped read-only; arbitrary samples decode only
the BC4 blocks they need, including both endpoint modes.
"""
from functools import cached_property
import json
from pathlib import Path

import numpy as np

SCHEMA = 'superterrain-bo4-source-package-v1'


def is_native(meta):
    return meta.get('schema') == SCHEMA


def resolve(root, relative):
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError('BO4 capture path escapes package: ' + str(relative))
    if not path.is_file(): raise ValueError('Missing BO4 capture file: ' + str(path))
    return path


def mapped(path, dtype, shape):
    expected = int(np.prod(shape))*np.dtype(dtype).itemsize
    if path.stat().st_size != expected:
        raise ValueError(f'BO4 array size mismatch: {path.name}: expected {expected} bytes')
    return np.memmap(path, mode='r', dtype=dtype, shape=shape)


def bilinear(fetch, rows, cols, size):
    rows, cols = np.broadcast_arrays(np.asarray(rows, float), np.asarray(cols, float))
    if not np.isfinite(rows).all() or not np.isfinite(cols).all():
        raise ValueError('Nonfinite sample coordinates')
    rows, cols = np.clip(rows, 0, size-1), np.clip(cols, 0, size-1)
    y0, x0 = np.floor(rows).astype(np.int64), np.floor(cols).astype(np.int64)
    y1, x1 = np.minimum(y0+1, size-1), np.minimum(x0+1, size-1)
    fy, fx = rows-y0, cols-x0
    return ((1-fy)*((1-fx)*fetch(y0, x0)+fx*fetch(y0, x1)) +
            fy*((1-fx)*fetch(y1, x0)+fx*fetch(y1, x1)))


class BC4Array:
    def __init__(self, path, width, height, slices):
        if width % 4 or height % 4 or min(width, height) <= 0 or slices < 0:
            raise ValueError('Invalid BO4 BC4 dimensions')
        self.blocks = (mapped(path, '<u8', (slices, height//4, width//4)) if slices else np.empty((0,height//4,width//4),np.uint64))
        self.width, self.height, self.slices = width, height, slices

    def texels(self, layer, rows, cols):
        if not 0 <= layer < self.slices: raise ValueError('BC4 slice out of range')
        rows, cols = np.broadcast_arrays(np.asarray(rows, np.int64), np.asarray(cols, np.int64))
        if np.any((rows < 0) | (rows >= self.height) | (cols < 0) | (cols >= self.width)):
            raise ValueError('BC4 texel out of range')
        bits = self.blocks[layer, rows//4, cols//4]
        first = (bits & np.uint64(255)).astype(float)
        second = ((bits >> np.uint64(8)) & np.uint64(255)).astype(float)
        shift = (16+3*((rows % 4)*4+cols % 4)).astype(np.uint64)
        index = ((bits >> shift) & np.uint64(7)).astype(np.int64)
        denominator = np.where(first > second, 7., 5.)
        weight = index-1
        interpolated = ((denominator-weight)*first+weight*second)/denominator
        value = np.where(index == 0, first, np.where(index == 1, second, interpolated))
        value = np.where((first <= second) & (index == 6), 0., value)
        value = np.where((first <= second) & (index == 7), 255., value)
        return value/255.


class Sector:
    def __init__(self, capture, row):
        self.capture, self.meta = capture, row
        self.index = int(row['sector'])
        if row.get('local_to_world'):raise ValueError('Rotated BO4 sector is not supported by native CAST export')
        self.size = int(row['grid_samples'])
        self.cell = float(row['units_per_sample'])
        self.origin = np.asarray(row['world_xy_origin'], float)
        self.bias = float(row['world_height_bias'])
        self.layers = row['layers']
        self.placement = np.asarray(row['placement'], float)
        if self.placement.shape != (4,) or self.placement[3] != 1:
            raise ValueError('Unverified BO4 placement scale')
        if self.size != int(row['tiles_across'])*32+1 or self.cell <= 0:
            raise ValueError('Invalid BO4 sampling grid')
        if abs(self.bias-(row['local_height_bias']+self.placement[2])) > 1e-5:
            raise ValueError('BO4 Z bias disagrees with captured placement')
        expected_origin = self.placement[:2]-(self.size-1)*self.cell/2
        if not np.allclose(self.origin, expected_origin, atol=1e-5, rtol=0):
            raise ValueError('BO4 XY origin disagrees with captured placement')
        if [l['slot'] for l in self.layers] != list(range(len(self.layers))):
            raise ValueError('Noncontiguous BO4 sector layer slots')
        for layer in self.layers:
            if layer['material'] not in capture.materials:
                raise ValueError('Missing BO4 material identity')
            uv = np.asarray(layer['uv_matrix_2x4'], float)
            if uv.shape != (8,) or not np.isfinite(uv).all(): raise ValueError('Invalid BO4 UV matrix')
        height = row['height']
        self.height_scale = float(height['scale'])
        if height['format'] != 'R16_UNORM_LE' or height['width'] != self.size+3 or height['height'] != self.size+3:
            raise ValueError('Unverified BO4 height layout')
        self.raw_height = mapped(resolve(capture.root, height['file']), '<u2', (height['height'], height['width']))
        weights = row['layer_weights']
        if (weights['format'] != 'BC4_UNORM' or weights['storage'] != 'slice_major'
                or weights['slices'] != len(self.layers)-1 or weights['base_layer'] != 0
                or weights['width'] != height['width'] or weights['height'] != height['height']
                or weights['slice_to_layer_slot'] != list(range(1, len(self.layers)))
                or not weights['independent_fields'] or weights['normalization_applied']):
            raise ValueError('Unverified BO4 weight layout')
        for slot, layer in enumerate(self.layers):
            if layer['weight_slice'] != (slot-1 if slot else None):
                raise ValueError('BO4 layer/slice association mismatch')
        self.weights = BC4Array(resolve(capture.root, weights['file']), weights['width'], weights['height'], weights['slices'])
        cut = row['cutout']
        if cut['packing'] != 'x8_y4_lsb_first' or cut['set_bit'] != 'solid' or cut['format'] != 'R32_UINT_LE':
            raise ValueError('Unverified BO4 cutout layout')
        if cut['width'] != row['tiles_across']*4+1 or cut['height'] != row['tiles_across']*8+1:
            raise ValueError('Invalid BO4 cutout dimensions')
        self.cutout = mapped(resolve(capture.root, cut['file']), '<u4', (cut['height'], cut['width']))

    def sample_height(self, rows, cols):
        return self.bias+self.height_scale*bilinear(lambda y, x: self.raw_height[y, x], rows, cols, self.size)

    def sample_weight(self, slot, rows, cols):
        if not 0 <= slot < len(self.layers): raise ValueError('BO4 layer slot out of range')
        if slot == 0: return np.ones(np.broadcast_shapes(np.shape(rows), np.shape(cols)), float)
        return bilinear(lambda y, x: self.weights.texels(slot-1, y, x), rows, cols, self.size)

    def sample_solid(self, rows, cols):
        rows, cols = np.broadcast_arrays(np.asarray(rows, np.int64), np.asarray(cols, np.int64))
        if np.any((rows < 0) | (rows >= self.size) | (cols < 0) | (cols >= self.size)):
            raise ValueError('Cutout sample outside used grid')
        shift = ((rows % 4)*8+cols % 8).astype(np.uint32)
        return ((self.cutout[rows//4, cols//8] >> shift) & 1).astype(bool)

    @cached_property
    def solid(self):
        # Row bands avoid constructing two full int64 coordinate lattices.
        out = np.empty((self.size, self.size), bool)
        for y in range(0, self.size, 128):
            rows = np.arange(y, min(y+128, self.size))[:, None]
            out[y:y+len(rows)] = self.sample_solid(rows, np.arange(self.size)[None, :])
        return out

    def uv(self, slot, world_x, world_y):
        m = self.layers[slot]['uv_matrix_2x4']
        # The measured terrain matrices are planar; an unverified Z term
        # must not be silently dropped by a future capture.
        if m[2] or m[6]: raise ValueError('Unverified BO4 nonplanar UV transform')
        return m[0]*world_x+m[1]*world_y+m[3], m[4]*world_x+m[5]*world_y+m[7]


class NativeCapture:
    is_native_bo4 = True

    def __init__(self, root, meta=None):
        self.root = Path(root).resolve()
        self.meta = meta or json.loads((self.root/'capture/terraingfx.json').read_text(encoding='utf8'))
        if not is_native(self.meta): raise ValueError('Not a native BO4 source package')
        if self.meta['path_base'] != 'package root (parent of capture)':
            raise ValueError('Unverified BO4 path base')
        self.materials = {m['name']: m for m in self.meta['materials']}
        if len(self.materials) != len(self.meta['materials']): raise ValueError('Duplicate BO4 material identity')
        for material in self.materials.values():
            for binding in material['bindings']:
                if binding.get('png_file'): resolve(self.root, binding['png_file'])
        self.sectors = [Sector(self, row) for row in self.meta['sectors']]
        if not self.sectors or len({s.index for s in self.sectors}) != len(self.sectors):
            raise ValueError('Empty or duplicate BO4 sectors')

    @property
    def index_map(self):
        raise ValueError('BO4 has independent layer fields; use the native BO4 reconstruction route, not CW index processing')

    def binding(self, layer, role):
        rows = [b for b in self.materials[layer['material']]['bindings'] if b['role'] == role and b.get('png_file')]
        files = {r['png_file'] for r in rows}
        if len(files) > 1: raise ValueError('Ambiguous BO4 material texture role: '+role)
        return rows[0] if rows else None

    def describe(self):
        return dict(game='black_ops_4', sectors=len(self.sectors), materials=len(self.materials),
                    layer_bindings=sum(len(s.layers) for s in self.sectors),
                    source_tiles=sum(s.meta['tiles_across']**2 for s in self.sectors),
                    weight_slices=sum(s.weights.slices for s in self.sectors),
                    discrete_index_created=False, weights_normalized=False)
