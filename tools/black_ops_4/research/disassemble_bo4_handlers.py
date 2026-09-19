"""Offline Capstone disassembly of Greyhound's bounded BO4 handler capture."""

# Support direct execution and the isolated packaged Python runtime.
import sys as _tool_sys
from pathlib import Path as _ToolPath
TOOLS_ROOT = next(p for p in _ToolPath(__file__).resolve().parents if (p / "tool_bootstrap.py").is_file())
_tool_sys.path.insert(0, str(TOOLS_ROOT))
import tool_bootstrap as _tool_bootstrap
_tool_bootstrap.activate(__file__)
REPO_ROOT = TOOLS_ROOT.parent
import argparse
import json
from pathlib import Path
from capstone import Cs, CS_ARCH_X86, CS_MODE_64


def run(root):
    root=Path(root);report=json.loads((root/'collision_handlers.json').read_text())
    decoder=Cs(CS_ARCH_X86,CS_MODE_64)
    functions={int(f['rva'],16):f for f in report['functions']}
    for rva,record in functions.items():
        blob=(root/record['file']).read_bytes()
        instructions=list(decoder.disasm(blob,rva))
        decoded=sum(i.size for i in instructions)
        text='\n'.join(f'{i.address:08x}  {i.mnemonic:10s} {i.op_str}' for i in instructions)
        (root/(Path(record['file']).stem+'.asm')).write_text(text+'\n')
        record['decoded_bytes']=decoded;record['captured_bytes']=len(blob)
        record['calls']=[i.op_str for i in instructions if i.mnemonic in ('call','jmp')]
    (root/'disassembly_index.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'functions':len(functions),'fully_decoded':sum(f['decoded_bytes']==f['captured_bytes'] for f in functions.values())}))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('capture',type=Path);run(parser.parse_args().capture)
