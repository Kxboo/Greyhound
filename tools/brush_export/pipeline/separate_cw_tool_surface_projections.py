"""Give each invisible tool-brush piece a distinct texture projection offset."""
import argparse,hashlib,json,re
from pathlib import Path
from build_cw_bo3_brush_prototype import materials

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('export',type=Path);p.add_argument('--output',type=Path,required=True);p.add_argument('--gdt',type=Path,required=True);a=p.parse_args()
    m=json.loads((a.export/'collision_metadata.json').read_text());name=m['map']+'_brush_collision.map';source=(a.export/name).read_text();assert hashlib.sha256((a.export/name).read_bytes()).hexdigest()==m['map_sha256']
    known=materials(a.gdt)
    for row in m['rows']:assert row['assigned_material'] in known
    if a.output.exists():raise ValueError('Select a fresh projection output directory')
    pattern=re.compile(r'^(\s*\(.*\)\s+)(\S+)( 64 64 )0( 0 0 0 lightmap_gray .*)$')
    index=None;changed=0;seen=0;lines=[]
    for line in source.splitlines():
        if line.startswith('// brush '):index=int(line.split()[-1]);assert index==m['rows'][index]['map_brush_index']
        match=pattern.fullmatch(line)
        if match:
            assert index is not None and match[2]==m['rows'][index]['assigned_material']
            seen+=1
            # This modifies only the first offset in the six-number material
            # projection block. Plane-defining points and material are untouched.
            if known[match[2]].get('noDraw')=='1':
                offset=format((index+1)/8,'.17g')
                line=match[1]+match[2]+match[3]+offset+match[4];changed+=1
        elif line.lstrip().startswith('('):raise ValueError('Unrecognized face serialization')
        lines.append(line)
    assert seen==sum(r['face_count'] for r in m['rows'])
    result='\n'.join(lines)+'\n'
    # Strip exactly this field to prove no other byte in the source map changed.
    restored=re.sub(r'(\) \S+ 64 64 )[-+0-9.eE]+( 0 0 0 lightmap_gray)',r'\g<1>0\2',result)
    assert restored==source
    a.output.mkdir(parents=True);dest=a.output/name;dest.write_text(result)
    m['texture_projection']=dict(method='Invisible tools only: per-piece first material projection offset (piece_index+1)/8; visible materials and lightmap projection unchanged',source_map_sha256=m['map_sha256'],changed_face_projections=changed,unchanged_visible_face_projections=seen-changed,all_other_map_text_identical=True,all_materials_noDraw=seen==changed,purpose='Prevent invisible tool-surface merging from producing invalid merged windings; collision planes and material names unchanged')
    m['map_sha256']=hashlib.sha256(dest.read_bytes()).hexdigest();m['implementation_sha256'][Path(__file__).name]=hashlib.sha256(Path(__file__).read_bytes()).hexdigest();(a.output/'collision_metadata.json').write_text(json.dumps(m,indent=2));print(json.dumps(m['texture_projection'],indent=2))

if __name__=='__main__':main()
