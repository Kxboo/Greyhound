"""Terrain package geometry and publication regressions, without a running game."""
from pathlib import Path
import importlib.util
import json
import sys
import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT/'tools/cold_war/terrain'))
import bake
import finalize


def test_height_texel_centres_clamp_and_interpolation():
    height=np.array([[0,65535],[65535,0]],dtype='<u2')
    uv=np.array([[.25,.25],[.75,.25],[.5,.5],[-1,-1],[2,2]])
    np.testing.assert_allclose(bake.sample_height(height,uv),[0,1,.5,0,0],atol=1e-7)


def test_mask_decodes_bit_order_and_bounds_last_tile(tmp_path):
    words=np.full((8,4),0xffffffff,dtype='<u4')
    words[0,0] &= np.uint32(0xfffffffd)  # X=1,Y=0
    p=tmp_path/'mask.bin';words.tofile(p)
    solid=bake.solid_mask(dict(file=str(p),width=4,height=8))
    assert solid.shape==(33,33)
    assert not solid[0,1] and solid[0,2] and solid[1,1]
    keep=bake.cells(solid,0,0)
    assert not keep[-1,:].any() and not keep[:,-1].any()
    assert not keep[0,0] and not keep[0,1] and keep[1,1]
    with pytest.raises(ValueError):bake.cells(solid,1,0)


def test_publish_rejects_missing_images_and_preserves_work(tmp_path):
    root=tmp_path/'run';root.mkdir();work=root/'_work';work.mkdir()
    (work/'keep.bin').write_bytes(b'source')
    folder=root/'terrain';folder.mkdir();(folder/'_mat_info').mkdir()
    (folder/'_mat_info/mat.txt').write_text('material')
    (folder/'export_report.json').write_text(json.dumps(dict(tiles=[[0,0]])))
    (root/'terrain_export.json').write_text(json.dumps(dict(packages=[dict(name='terrain')])))
    with pytest.raises(ValueError,match='Missing baked image'):finalize.finalize(root)
    assert (work/'keep.bin').read_bytes()==b'source'


def test_unsupported_shader_fails_before_dispatch(tmp_path):
    path=tmp_path/'shader';path.write_bytes(b'not the verified shader')
    source=tmp_path/'inputs.json';source.write_text(json.dumps(dict(shader=str(path))))
    from argparse import Namespace
    with pytest.raises(ValueError,match='Unvalidated'):bake.main(Namespace(inputs=source))
