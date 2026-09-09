import json, struct
from pathlib import Path
import lz4.block

def load_names(filename):
    b=Path(filename).read_bytes()
    magic,version,count,packed,unpacked=struct.unpack_from('<IHIII',b)
    assert magic==0x20494e57 and version==1
    raw=lz4.block.decompress(b[18:18+packed],uncompressed_size=unpacked)
    names={};offset=0
    for i in range(count):
        key=struct.unpack_from('<Q',raw,offset)[0];offset+=8
        end=raw.index(0,offset)
        names[key & 0xfffffffffffffff]=raw[offset:end].decode('utf8');offset=end+1
    return names

if __name__=='__main__':
    path=Path('research/cw-clip/selected-collision-5840/ownership/report.json')
    report=json.loads(path.read_text())
    names=load_names('repos/Greyhound/bin/cli/package_index/fnv1a_xmodels.wni')
    for row in report['entries']:
        row['name_candidate']=names.get(int(row['hash'],16)&0xfffffffffffffff)
    output=path.with_name('named-report.json');output.write_text(json.dumps(report,indent=2))
    print('resolved',sum(bool(x['name_candidate']) for x in report['entries']))
    print('brush names',[(x['index'],x['name_candidate'],x['brushes'],bool(x['owners'])) for x in report['entries'] if x['brushes']][:15])
