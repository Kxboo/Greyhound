const fs=require('fs'),path=require('path'),assert=require('assert');
const {audit}=require('../tools/capture/audit_cw_map_data.cjs');
const parent=path.resolve(__dirname,'../test-output');fs.mkdirSync(parent,{recursive:true});
const root=fs.mkdtempSync(path.join(parent,'audit-test-'));
const created=[];
function save(name,data){const p=path.join(root,name);if(!created.includes(p))created.push(p);fs.writeFileSync(p,typeof data==='object'&&!Buffer.isBuffer(data)?JSON.stringify(data):data);}
try{
  const records=Buffer.alloc(48),properties=Buffer.alloc(32);
  records.writeUInt32LE(1,0);properties.writeBigUInt64LE(0x10000n,0);properties.writeBigUInt64LE(0x20000n,8);properties.writeUInt16LE(2,24);
  const key=Buffer.from('classname\0'),value=Buffer.from('worldspawn\0');
  const packed=Buffer.concat([records,properties,key,value]);save('small_records.bin',packed);
  const storage={
    'typed/entity_records.bin':{file:'small_records.bin',offset:0,bytes:48},
    'typed/properties_0.bin':{file:'small_records.bin',offset:48,bytes:32},
    'typed/strings/0x10000.bin':{file:'small_records.bin',offset:80,bytes:key.length},
    'typed/strings/0x20000.bin':{file:'small_records.bin',offset:80+key.length,bytes:value.length}};
  const evidence={storage,pool_index:142},decoded={source_name_hash:'0x1',complete:true,
    arrays:[{file:'typed/entity_records.bin',count:1,candidate_stride:48,captured_bytes:48},
      {file:'typed/properties_0.bin',count:1,candidate_stride:32,captured_bytes:32}],
    entities:[{index:0,properties:[{key:{text:'classname'},type_tag:2,string_candidate:{text:'worldspawn'}}]}]};
  save('evidence.json',evidence);save('decoded_candidates.json',decoded);
  assert.equal(audit(root).classes.worldspawn,1);
  decoded.entities[0].properties[0].string_candidate.text='wrong';save('decoded_candidates.json',decoded);
  assert.throws(()=>audit(root),/String mismatch/);
  decoded.entities[0].properties[0].string_candidate.text='worldspawn';save('decoded_candidates.json',decoded);
  storage['typed/properties_0.bin'].offset=packed.length;save('evidence.json',evidence);
  assert.throws(()=>audit(root),/Invalid packed range/);
  storage['typed/properties_0.bin'].offset=48;save('evidence.json',evidence);
  save('small_records.bin',packed.subarray(0,packed.length-1));assert.throws(()=>audit(root),/Invalid packed range/);
  console.log('Map-data audit tests passed: valid packed capture, wrong decode, invalid range, truncation');
}finally{for(const p of created)fs.unlinkSync(p);fs.rmdirSync(root);}
