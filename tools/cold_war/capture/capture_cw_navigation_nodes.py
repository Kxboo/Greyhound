"""Read bounded GAME_MAP navigation records and children, anchored to ENTITYLIST.

Requires an unchanged saved entity capture and a verified module base. Opens the
game with read/query access only. No memory writes or desktop interaction.
"""

# Support direct execution and the isolated packaged Python runtime.
import sys as _tool_sys
from pathlib import Path as _ToolPath
TOOLS_ROOT = next(p for p in _ToolPath(__file__).resolve().parents if (p / "tool_bootstrap.py").is_file())
_tool_sys.path.insert(0, str(TOOLS_ROOT))
import tool_bootstrap as _tool_bootstrap
_tool_bootstrap.activate(__file__)
REPO_ROOT = TOOLS_ROOT.parent
import argparse
import ctypes
import hashlib
import json
from pathlib import Path
import struct
from datetime import datetime, timezone
from decode_cw_entitylist import Capture, require


def capture(entity_root, output, pid, module_base):
    source = Capture(entity_root)
    evidence = source.evidence
    decoded = source.json('decoded_candidates.json')
    require(evidence['process']['pid'] == pid and int(evidence['process']['module_base'], 16) == module_base,
            'Process does not match the saved ENTITYLIST capture')
    descriptor_address = int(next(r['address'] for r in evidence['reads'] if r['file']=='descriptor_start.bin'), 16)
    pool_table = descriptor_address - 0x8E * 32
    expected = source.read('descriptor_start.bin', 32)
    expected_headers = source.read('headers.bin')
    entities = source.read('typed/entity_records.bin')
    entity_array = next(a for a in decoded['arrays'] if a['file']=='typed/entity_records.bin')
    output = Path(output).resolve()
    require(not output.exists(), 'Use a new evidence directory')
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.ReadProcessMemory.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel.OpenProcess(0x410, False, pid)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    reads = []
    total = 0

    def memory(address, length):
        nonlocal total
        require(0x10000 <= address < 0x800000000000 and 0 < length <= 8*1024*1024 and total+length <= 64*1024*1024,
                'Read bounds exceeded')
        total += length
        buffer = ctypes.create_string_buffer(length)
        got = ctypes.c_size_t()
        if not kernel.ReadProcessMemory(handle, address, buffer, length, ctypes.byref(got)) or got.value != length:
            raise ctypes.WinError(ctypes.get_last_error())
        return buffer.raw

    def stable(address, length, name):
        data = memory(address, length)
        require(data == memory(address, length), 'Readback changed: '+name)
        reads.append((name, address, data))
        return data

    def verify_entities():
        require(memory(descriptor_address, 32) == expected, 'ENTITYLIST descriptor changed')
        require(memory(struct.unpack_from('<Q', expected)[0], len(expected_headers)) == expected_headers, 'ENTITYLIST headers changed')
        require(memory(int(entity_array['address'],16),len(entities)) == entities, 'ENTITYLIST records changed')

    try:
        require(memory(module_base, 2) == b'MZ', 'Stale module base')
        verify_entities()
        descriptor = stable(pool_table+0x1A*32,32,'descriptor.bin')
        pointer, stride, capacity = struct.unpack_from('<QII', descriptor)
        loaded, = struct.unpack_from('<I',descriptor,20)
        require(stride==80 and 0 < loaded <= capacity <= 32, 'Unexpected GAME_MAP descriptor')
        headers = stable(pointer, stride*capacity,'headers.bin')
        free = set()
        at, = struct.unpack_from('<Q',descriptor,24)
        while at:
            require(pointer <= at < pointer+len(headers) and (at-pointer)%stride==0, 'Invalid free-list address')
            index=(at-pointer)//stride
            require(index not in free,'Cyclic free-list')
            free.add(index)
            at,=struct.unpack_from('<Q',headers,index*stride)
        require(len(free)==capacity-loaded,'Free-list occupancy mismatch')
        matching=[i for i in range(capacity) if i not in free and struct.unpack_from('<Q',headers,i*stride)[0]==int(decoded['source_name_hash'],16)]
        require(len(matching)==1,'GAME_MAP does not uniquely match the saved entity map')
        header=headers[matching[0]*stride:(matching[0]+1)*stride]
        count,=struct.unpack_from('<I',header,8)
        nodes_pointer,=struct.unpack_from('<Q',header,16)
        require(0<count<=32768,'Unexpected node count')
        nodes=stable(nodes_pointer,count*176,'nodes176.bin')
        arrays=[]
        for i in range(count):
            child_pointer,=struct.unpack_from('<Q',nodes,i*176)
            child_count,=struct.unpack_from('<H',nodes,i*176+116)
            if child_pointer:
                require(0<child_count<1024,'Unexpected child count')
                arrays.append(dict(node=i,address=child_pointer,count=child_count))
        require(bool(arrays),'No bounded child arrays')
        require(all(a['address']+12*a['count']==b['address'] for a,b in zip(arrays,arrays[1:])), 'Child arrays are not a contiguous partition')
        end=arrays[-1]['address']+12*arrays[-1]['count']
        require(end==struct.unpack_from('<Q',header,40)[0],'Child end does not match next section')
        stable(arrays[0]['address'],end-arrays[0]['address'],'children12.bin')
        verify_entities()
        require(memory(pool_table+0x1A*32,32)==descriptor and memory(pointer,len(headers))==headers and memory(nodes_pointer,len(nodes))==nodes,
                'GAME_MAP changed during capture')
        output.mkdir(parents=True)
        for name,at,data in reads:
            (output/name).write_bytes(data)
        (output/'header.bin').write_bytes(header)
        children=dict(address=hex(arrays[0]['address']), arrays=arrays,
                      readback_unchanged=True,node_and_header_readback_unchanged=True)
        (output/'children-capture.json').write_text(json.dumps(children,indent=2)+'\n')
        report=dict(schema='cw-game-map-node-capture-v1', map_hash=decoded['source_name_hash'],
                    entity_capture=str(source.root), pid=pid,module_base=hex(module_base),node_count=count,
                    child_arrays=len(arrays),child_records=sum(a['count'] for a in arrays),
                    required_reads_unchanged=True,atomic_snapshot=False,read_only=True,
                    finished_utc=datetime.now(timezone.utc).isoformat(),total_read_bytes=total,
                    files=[dict(file=name,address=hex(at),bytes=len(data),sha256=hashlib.sha256(data).hexdigest()) for name,at,data in reads],
                    scope='Count/partition-bounded candidate GAME_MAP records; fields and link semantics require independent validation')
        (output/'capture.json').write_text(json.dumps(report,indent=2)+'\n')
        return report
    finally:
        kernel.CloseHandle(handle)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--entities',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--pid',type=int,required=True)
    p.add_argument('--module-base',type=lambda v:int(v,0),required=True)
    a=p.parse_args()
    result=capture(a.entities,a.output,a.pid,a.module_base)
    print(json.dumps({k:v for k,v in result.items() if k!='files'}))
