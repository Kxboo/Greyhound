import ctypes
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parent/'pipeline'))
from cw_export_progress import write_progress


class ProgressTests(unittest.TestCase):
    @unittest.skipUnless(os.name=='nt','Windows file-sharing regression')
    def test_real_reader_lock_does_not_abort_export_and_next_update_recovers(self):
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.CreateFileW.argtypes=[ctypes.c_wchar_p,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_void_p,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_void_p]
        kernel.CreateFileW.restype=ctypes.c_void_p
        kernel.CloseHandle.argtypes=[ctypes.c_void_p]
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'progress.json';write_progress(path,{'percent':1})
            handle=kernel.CreateFileW(str(path),0x80000000,3,None,3,0x80,None)
            self.assertNotEqual(handle,ctypes.c_void_p(-1).value)
            try:
                self.assertFalse(write_progress(path,{'percent':2},attempts=1))
                self.assertEqual(json.loads(path.read_text()),{'percent':1})
            finally:kernel.CloseHandle(handle)
            self.assertTrue(write_progress(path,{'percent':3}))
            self.assertEqual(json.loads(path.read_text()),{'percent':3})

    def test_transient_lock_retries_before_dropping_update(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'progress.json';replace=os.replace
            calls=[]
            def briefly_locked(source,destination):
                calls.append(1)
                if len(calls)<3:raise PermissionError('busy reader')
                replace(source,destination)
            with patch('cw_export_progress.os.replace',briefly_locked),patch('cw_export_progress.time.sleep'):
                self.assertTrue(write_progress(path,{'percent':100}))
            self.assertEqual(len(calls),3)


if __name__=='__main__':unittest.main()
