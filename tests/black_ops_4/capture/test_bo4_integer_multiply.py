"""DXBC multiply semantics, including the terrain CB1 layer-index regression."""
import sys as _tool_sys
from pathlib import Path as _ToolPath
_REPO = next(p for p in _ToolPath(__file__).resolve().parents if (p/'build-greyhound.ps1').is_file())
_tool_sys.path.insert(0, str(_REPO/'tools'))
import tool_bootstrap as _tool_bootstrap
_tool_bootstrap.activate(_REPO/'tools/tool_bootstrap.py')
import unittest
import numpy as np
from bo4_dxbc_emulator import Shader

class IntegerMultiplyTests(unittest.TestCase):
    def test_signed_full_width_negative_and_overflow(self):
        shader = Shader('''ps_5_0
dcl_temps 1
imul o0.xyzw, o1.xyzw, v0.xyzw, v1.xyzw
ret
''')
        a = np.array([[-1,-2147483648,2147483647,-123456789]],np.int32)
        b = np.array([[2,-1,2147483647,7654321]],np.int32)
        out,_ = shader.run(1,inputs={'v0':a.view(np.uint32),'v1':b.view(np.uint32)})
        products = [(int(x)*int(y)) & ((1<<64)-1) for x,y in zip(a[0],b[0])]
        np.testing.assert_array_equal(out[0].view(np.uint32),[[p>>32 for p in products]])
        np.testing.assert_array_equal(out[1].view(np.uint32),[[p&0xffffffff for p in products]])

    def test_unsigned_high_and_low_with_source_alias(self):
        shader = Shader('''ps_5_0
dcl_temps 2
mov r0.xyzw, v0.xyzw
umul r0.xyzw, r1.xyzw, r0.xyzw, v1.xyzw
mov o0.xyzw, r0.xyzw
mov o1.xyzw, r1.xyzw
ret
''')
        a = np.array([[0xffffffff,0x80000000,0x12345678,1]],np.uint32)
        b = np.array([[0xffffffff,3,0x87654321,0]],np.uint32)
        out,_ = shader.run(1,inputs={'v0':a,'v1':b})
        products = [int(x)*int(y) for x,y in zip(a[0],b[0])]
        np.testing.assert_array_equal(out[0].view(np.uint32),[[p>>32 for p in products]])
        np.testing.assert_array_equal(out[1].view(np.uint32),[[p&0xffffffff for p in products]])

    def test_terrain_layer_index_writes_low_destination(self):
        shader = Shader('''ps_5_0
dcl_temps 1
mov r0.x, v0.x
imul null, r0.x, r0.x, l(7)
mov o0.xyzw, cb1[r0.x + 2].xyzw
ret
''')
        cb = np.arange(224*4,dtype=np.uint32).reshape(224,4)
        indices=np.array([[0],[1],[5],[16],[31]],np.uint32)
        out,_=shader.run(len(indices),inputs={'v0':indices},cbuffers={1:cb})
        np.testing.assert_array_equal(out[0].view(np.uint32),cb[indices[:,0]*7+2])

    def test_null_destinations_masks_and_inactive_lanes(self):
        shader=Shader('''ps_5_0
dcl_temps 1
mov o0.xyzw, l(9,8,7,6)
mov o1.xyzw, l(5,4,3,2)
if_nz v0.x
imul null, o0.xz, -v0.wzyx, l(7)
umul o1.yw, null, v0.xyzw, l(0xffffffff)
imul null, null, v0.xyzw, v0.xyzw
endif
ret
''')
        values=np.array([[1,2,3,4],[0,6,7,8]],np.uint32)
        out,_=shader.run(2,inputs={'v0':values})
        np.testing.assert_array_equal(out[0].view(np.uint32),[[0xffffffe4,8,0xfffffff2,6],[9,8,7,6]])
        np.testing.assert_array_equal(out[1].view(np.uint32),[[5,1,3,3],[5,4,3,2]])

if __name__=='__main__':unittest.main()
