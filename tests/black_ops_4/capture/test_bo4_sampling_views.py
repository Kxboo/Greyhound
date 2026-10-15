"""Synthetic view-limit and source-profile regressions for terrain materials."""
import sys
from pathlib import Path
REPO_ROOT=next(p for p in Path(__file__).resolve().parents if (p/'build-greyhound.ps1').is_file())
sys.path.insert(0,str(REPO_ROOT/'tools'))
import tool_bootstrap
tool_bootstrap.activate(REPO_ROOT/'tools/tool_bootstrap.py')
import hashlib,json,tempfile,unittest
import numpy as np
from bo4_dxbc_emulator import Texture,VirtualArray
from bo4_terrain_gbuffer import sampling_profile

class ArrayViewTests(unittest.TestCase):
    def texture(self):
        return Texture([np.full((1,n,n,1),v,np.float32)for n,v in ((8,.1),(4,.2),(2,.8),(1,1.))])

    def test_fractional_lod_clamps_before_slice_offset(self):
        tex=self.texture();array=VirtualArray({7:tex},(16,16),count=8,mip_levels=3)
        lod=np.array([1,1.5,2,2.5,100],np.float32)
        result=array.sample(np.full(5,.5),np.full(5,.5),np.full(5,7),lod)
        np.testing.assert_allclose(result[:,0],[.1,.15,.2,.2,.2],atol=1e-7)
        self.assertEqual(array.mip_count(),3)
        self.assertEqual(len(tex.levels),4)  # Raw source tails are preserved.

    def test_full_chain_remains_default_without_evidence(self):
        array=VirtualArray({0:self.texture()},(16,16))
        result=array.sample(np.array([.5]),np.array([.5]),np.array([0]),np.array([100.]))
        self.assertEqual(float(result[0,0]),1.)
        self.assertEqual(array.mip_count(),5)

    def test_load_cannot_read_a_tail_outside_the_view(self):
        array=VirtualArray({0:self.texture()},(16,16),mip_levels=3)
        x=y=s=np.array([0])
        np.testing.assert_allclose(array.load(x,y,s,2)[0,0],.2)
        np.testing.assert_array_equal(array.load(x,y,s,3),np.zeros((1,4)))

    def test_invalid_mip_count_fails(self):
        for count in (0,-1,6):
            with self.subTest(count=count),self.assertRaises(ValueError):
                VirtualArray({0:self.texture()},(16,16),mip_levels=count)

class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup)
        self.root=Path(self.folder.name);(self.root/'capture').mkdir()
        self.doc={'asset':{'name':'terrain_fixture'},'sectors':[{'sector':0,'layers':[{'slot':0,'runtime':{'raw_hex':'01020304'}}]}]}
        self.profile={'schema':'superterrain-bo4-terrain-sampling-v1','asset':'terrain_fixture',
                      'layer_records_sha256':hashlib.sha256(bytes.fromhex('01020304')).hexdigest()}

    def write(self):
        (self.root/'capture/terrain_sampling.json').write_text(json.dumps(self.profile))

    def test_no_profile_is_explicitly_unverified(self):
        self.assertIsNone(sampling_profile(self.root,self.doc))

    def test_profile_matches_source_inputs(self):
        self.write();self.assertEqual(sampling_profile(self.root,self.doc),self.profile)

    def test_other_map_profile_rejected(self):
        self.profile['asset']='different_map';self.write()
        with self.assertRaises(ValueError):sampling_profile(self.root,self.doc)

    def test_changed_layer_inputs_rejected(self):
        self.write();self.doc['sectors'][0]['layers'][0]['runtime']['raw_hex']='01020305'
        with self.assertRaises(ValueError):sampling_profile(self.root,self.doc)

if __name__=='__main__':unittest.main()
