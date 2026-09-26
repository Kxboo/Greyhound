"""Coordinates use traced float32 arithmetic, counted shapes and source domains."""
from pathlib import Path
import struct
import sys

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT/'tools'))
import tool_bootstrap
tool_bootstrap.activate(ROOT/'tools/tool_bootstrap.py')
from cw_quantized_geometry import axis_scales, coordinate, decode_payload
from export_cw_clip_mesh_candidates import decode


def fixture(shapes=1, selectors=1, width=1, pointer_base=0, extra=False):
    table = (304+selectors+7) & ~7
    raw = bytearray(table+80*shapes)
    struct.pack_into('<HHI', raw, 296, selectors, shapes, int(extra))
    raw[304:304+selectors] = bytes(range(selectors))
    headers = []
    for i in range(shapes):
        at=table+80*i; start=len(raw); headers.append(at)
        # Unpadded one-byte tree on the first shape tests next-stream alignment.
        tail = 1 if shapes>1 and i==0 else 0
        data = (1,2,3, 4,5,6, 7,8,9)
        n8,n16 = (3,0) if width==1 else (0,3)
        lo = (1000.*i, -100., 0.); hi = (lo[0]+20000., 100., 100.)
        struct.pack_into('<I4H6fII', raw, at+32, tail,i,1,n8,n16,*lo,*hi,1,13<<20)
        if width==1:raw.extend(bytes(data))
        raw.extend(bytes(len(raw)%2))
        word_start=len(raw)
        if width==2:raw.extend(struct.pack('<9H',*data))
        raw.extend(bytes((-len(raw))%4)); group_at=len(raw)
        group=(1<<31)|(1<<14)|(2<<18)|(3<<22) if width==1 else 0
        raw.extend(struct.pack('<I',group));tree_at=len(raw);raw.extend(bytes(tail))
        if pointer_base:
            struct.pack_into('<4Q',raw,at,*(pointer_base+p for p in (word_start,start,group_at,tree_at)))
    if extra:
        raw.extend(bytes((-len(raw))%8));raw.extend(bytes(208))
    else:raw.extend(bytes((-len(raw))%4))
    return raw, headers


@pytest.mark.parametrize('span', [16.,8191.,8192.,20000.,100000.])
def test_coordinate_matches_independent_float32_operations(span):
    lo=(-17.25,2.5,0.);hi=(lo[0]+span,lo[1]+span,span)
    scales=axis_scales(lo,hi)
    expected=np.maximum(np.float32(8191),np.subtract(np.array(hi,np.float32),np.array(lo,np.float32))) * np.float32(1/65535)
    assert scales==tuple(map(float,expected))
    for scale,minimum in zip(scales,lo):
        for value,block in ((0,0),(255,15),(65535,0),(1,1)):
            assert coordinate(minimum,scale,value,block)==minimum+float(np.float32(value+256*block)*np.float32(scale))


@pytest.mark.parametrize('width', [1,2])
def test_counted_multishape_streams_and_relocation(width):
    raw,headers=fixture(shapes=2,selectors=9,width=width,pointer_base=0x12340000)
    result=decode_payload(raw,0x12340000)
    assert result.selectors==bytes(range(9))
    assert [s.header_offset for s in result.shapes]==headers
    assert [s.transform_selector for s in result.shapes]==[0,1]
    assert result.shapes[1].stream_start==result.shapes[0].stream_end
    for shape in result.shapes:
        assert shape.checked_pointers==4
        group=shape.groups[0]
        blocks=(1,2,3) if width==1 else (0,0,0)
        assert group.axis_blocks==blocks
        for row,vertex in enumerate(group.vertices):
            expected=tuple(shape.minimum[a]+float(np.float32(3*row+a+1+256*blocks[a])*np.float32(shape.scales[a])) for a in range(3))
            assert vertex==expected


def test_exporter_keeps_all_shapes_and_marks_unparsed_extra_branch():
    raw,_=fixture(shapes=2,selectors=9,extra=True)
    model=dict(name='multi',mins=[0,-100,0],maxs=[21000,100,100])
    vertices,triangles,report=decode(raw,model)
    assert len(vertices)==6 and len(triangles)==2
    assert report['shape_count']==2 and report['complete_vertex_coverage']
    assert report['extra_sections_not_decoded']==1
    assert report['complete_model_collision'] is False
    assert [s['transform_selector'] for s in report['shapes']]==[0,1]
    assert all(s['transform_applied'] is False for s in report['shapes'])
    # The legacy /8 arithmetic would incorrectly return 32.125 on the X axis.
    assert vertices[0][0] != 32.125


@pytest.mark.parametrize('mutation', ['short_header','short_stream','bad_pointer','bad_count','bad_range','nan','inverted','extra_bytes'])
def test_malformed_payload_rejected(mutation):
    raw,headers=fixture(pointer_base=0x12340000)
    at=headers[0]
    if mutation=='short_header':raw=raw[:300]
    elif mutation=='short_stream':raw=raw[:-1]
    elif mutation=='bad_pointer':struct.pack_into('<Q',raw,at,0x12340001)
    elif mutation=='bad_count':struct.pack_into('<H',raw,298,65535)
    elif mutation=='bad_range':
        group_at=(at+80+9+3)&~3
        word=struct.unpack_from('<I',raw,group_at)[0]
        struct.pack_into('<I',raw,group_at,word|0x3fff)
    elif mutation=='nan':struct.pack_into('<f',raw,at+44,float('nan'))
    elif mutation=='inverted':struct.pack_into('<f',raw,at+56,-1)
    elif mutation=='extra_bytes':raw.extend(bytes(4))
    with pytest.raises(ValueError):decode_payload(raw,0x12340000)


def test_relocated_payload_requires_capture_address():
    raw,_=fixture(pointer_base=0x12340000)
    with pytest.raises(ValueError,match='relocation'):decode_payload(raw)
