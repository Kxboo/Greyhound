
import sys as _tool_sys
from pathlib import Path as _ToolPath
REPO_ROOT = next(p for p in _ToolPath(__file__).resolve().parents if (p / "build-greyhound.ps1").is_file())
TOOLS_ROOT = REPO_ROOT / "tools"
_tool_sys.path.insert(0, str(TOOLS_ROOT))
import tool_bootstrap as _tool_bootstrap
_tool_bootstrap.activate(TOOLS_ROOT / "tool_bootstrap.py")
import hashlib
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest

from decode_cw_navigation_graph import decode


class GraphTests(unittest.TestCase):
    def fixture(self, root, broken_partner=False, broken_mask=False, missing_name=False):
        nodes=bytearray(352);points=bytearray();entities=[]
        for i in range(2):
            at=i*176
            struct.pack_into('<Q',nodes,at,0x1000+i*24)
            struct.pack_into('<3f',nodes,at+8,2,5,5)
            struct.pack_into('<3f',nodes,at+20,i*20,0,0)
            struct.pack_into('<2f',nodes,at+32,1,0)
            struct.pack_into('<H',nodes,at+40,20)
            struct.pack_into('<I',nodes,at+68,0 if broken_mask else 1024)
            struct.pack_into('<II',nodes,at+84,2 if broken_partner and i==0 else 1-i,0xFFFFFFFF)
            struct.pack_into('<f',nodes,at+92,1)
            struct.pack_into('<H',nodes,at+116,2)
            points.extend(struct.pack('<6f',i*20+2,-4,0.125,i*20+2,4,0.125))
            entities.append(dict(index=100+i,classname='node_negotiation_volume',origin=[i*20.,0.,0.],angles=[0.,0.,0.],
                conversion_keyvalues=dict(classname='node_negotiation_volume',width='4',length='10',height='10',
                    targetname='a' if i==0 else 'b',target='missing' if missing_name and i==0 else 'b' if i==0 else 'a',
                    movementtype_ignore='vehicle',cost_modifier='1')))
        header=bytearray(80);struct.pack_into('<Q',header,0,0x123);struct.pack_into('<I',header,8,2)
        blobs={'header.bin':header,'nodes176.bin':nodes,'children12.bin':points}
        for name,data in blobs.items():(root/name).write_bytes(data)
        capture=dict(required_reads_unchanged=True,map_hash='0x123',files=[dict(file=n,bytes=len(b),sha256=hashlib.sha256(b).hexdigest()) for n,b in blobs.items()])
        (root/'capture.json').write_text(json.dumps(capture))
        children=dict(address='0x1000',readback_unchanged=True,node_and_header_readback_unchanged=True,
                      arrays=[dict(node=i,address=0x1000+i*24,count=2) for i in range(2)])
        (root/'children-capture.json').write_text(json.dumps(children))
        return dict(map='fixture',source=dict(name_hash='0x123'),entities=entities)

    def test_pair_points_and_source_restrictions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);result=decode(root,self.fixture(root))
            self.assertEqual(result['summary']['volume_pairs'],1)
            self.assertEqual(result['summary']['edge_points'],4)
            self.assertEqual(result['volume_pairs'][0]['directions'][0]['movement_ignore_names'],['vehicle'])
            self.assertEqual(result['nodes'][0]['edge_points'][0],[2.,-4.,0.125])

    def test_missing_text_target_recovers_compiled_partner(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);result=decode(root,self.fixture(root,missing_name=True))
            self.assertEqual(result['recovered_targets'][0]['compiled_partner_entity'],101)

    def test_reject_bad_partner(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);doc=self.fixture(root,broken_partner=True)
            with self.assertRaisesRegex(ValueError,'reciprocal'):decode(root,doc)

    def test_reject_movement_mask_disagreement(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);doc=self.fixture(root,broken_mask=True)
            with self.assertRaisesRegex(ValueError,'movement-ignore bit'):decode(root,doc)

    def test_reject_capture_corruption(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);doc=self.fixture(root)
            (root/'children12.bin').write_bytes(b'broken')
            with self.assertRaisesRegex(ValueError,'integrity'):decode(root,doc)


if __name__=='__main__':unittest.main()
