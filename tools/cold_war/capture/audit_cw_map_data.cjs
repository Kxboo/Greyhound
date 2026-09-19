// Offline source validation only. No geometry conversion or process access.
const fs=require('fs'),path=require('path'),crypto=require('crypto');
const sha=b=>crypto.createHash('sha256').update(b).digest('hex');
function audit(directory){
  const root=path.resolve(directory),cache=new Map();
  const load=file=>{
    const p=path.resolve(root,file);
    if(!p.startsWith(root+path.sep))throw Error('Source path escapes capture: '+file);
    if(!cache.has(p))cache.set(p,fs.readFileSync(p));return cache.get(p);
  };
  const evidence=JSON.parse(load('evidence.json')),decoded=JSON.parse(load('decoded_candidates.json'));
  const read=(file,expected)=>{
    if(expected===0)return Buffer.alloc(0);
    const storage=evidence.storage[file];let b;
    if(storage){
      const packed=load(storage.file),{offset,bytes}=storage;
      if(!Number.isSafeInteger(offset)||!Number.isSafeInteger(bytes)||offset<0||bytes<0||offset+bytes>packed.length)
        throw Error('Invalid packed range: '+file);
      b=packed.subarray(offset,offset+bytes);
    }else b=load(file);
    if(expected!==undefined&&b.length!==expected)throw Error('Wrong byte count: '+file);
    return b;
  };
  const str=address=>{
    const b=read('typed/strings/0x'+address.toString(16).toUpperCase()+'.bin'),end=b.indexOf(0);
    if(end<0)throw Error('Unterminated captured string');return b.subarray(0,end).toString('utf8');
  };
  const arrays=decoded.arrays.map(a=>{
    const expected=a.count*a.candidate_stride;
    if(!Number.isSafeInteger(expected)||a.captured_bytes!==expected)throw Error('Incomplete array '+a.file);
    return {file:a.file,bytes:expected,sha256:sha(read(a.file,expected))};
  });
  const records=read('typed/entity_records.bin',decoded.entities.length*48);
  const types={},classes={},normalized=[];let properties=0;
  for(const entity of decoded.entities){
    const i=entity.index,r=records.subarray(i*48,i*48+48);
    if(r.length!==48||r.readUInt32LE(0)!==entity.properties.length)throw Error('Entity/property count mismatch '+i);
    const b=read('typed/properties_'+i+'.bin',entity.properties.length*32),values=[];
    for(let j=0;j<entity.properties.length;j++){
      const native=entity.properties[j],k=b.subarray(j*32,j*32+32),type=k.readUInt16LE(24);
      const name=str(k.readBigUInt64LE(0)),raw=k.subarray(8,24);
      if(type!==native.type_tag||name!==native.key.text)throw Error('Raw/native key or type mismatch '+i+':'+j);
      let value=raw.toString('hex');
      if(type===2){value=str(raw.readBigUInt64LE(0));if(value!==native.string_candidate.text)throw Error('String mismatch');}
      if(type===3){value=[0,4,8].map(o=>raw.readFloatLE(o));if(JSON.stringify(value)!==JSON.stringify(native.vector_candidate))throw Error('Vector mismatch');}
      if(type===4)value='0x'+raw.readBigUInt64LE(0).toString(16).toUpperCase();
      if(type===5)value=raw.readFloatLE(0);
      if(type===6)value={signed:raw.readInt32LE(0),unsigned:raw.readUInt32LE(0)};
      if(native.raw_value_hex!==undefined&&native.raw_value_hex!==raw.toString('hex'))throw Error('Raw value mismatch');
      if(type===4&&native.asset_hash_candidate!==undefined&&native.asset_hash_candidate!==value)throw Error('Hash mismatch');
      if(type===5&&native.float_candidate!==undefined&&native.float_candidate!==value)throw Error('Float mismatch');
      if(type===6&&native.int32_candidate!==undefined&&(native.int32_candidate!==value.signed||native.uint32_candidate!==value.unsigned))throw Error('Integer mismatch');
      types[type]=(types[type]||0)+1;properties++;
      if(name==='classname')classes[value]=(classes[value]||0)+1;
      values.push({key:name,type,value});
    }
    normalized.push({index:i,raw_reference:r.readUInt32LE(16),id:r.readUInt32LE(20),
      record_vectors:[24,28,32,36,40,44].map(o=>r.readFloatLE(o)),properties:values});
  }
  const verification=evidence.verifications||[];
  const result={schema:'cw-map-data-audit-v1',directory:root,pool:evidence.pool_index,
    map_hash:decoded.source_name_hash,entities:normalized.length,properties,types,classes,
    semantic_sha256:sha(JSON.stringify(normalized)),arrays,
    typed_complete:decoded.complete,readback_unchanged:decoded.readback_unchanged??null,
    verification_ranges:verification.length,
    verification_failures:verification.filter(v=>!['unchanged','empty'].includes(v.status)),
    evidence_sha256:sha(load('evidence.json')),decoded_sha256:sha(load('decoded_candidates.json')),
    geometry:decoded.geometry_validation??null};
  if(evidence.pool_index===0x80){
    result.tail_classes=normalized.slice(-8).map(e=>({index:e.index,classname:e.properties.find(p=>p.key==='classname')?.value}));
  }
  return result;
}
if(require.main===module){
  const [output,...inputs]=process.argv.slice(2);
  if(!output||!inputs.length)throw Error('Usage: node audit_cw_map_data.cjs OUTPUT.json CAPTURE_DIR [CAPTURE_DIR ...]');
  const reports=inputs.map(audit),comparisons=[];
  for(let i=0;i<reports.length;i++)for(let j=i+1;j<reports.length;j++){
    const a=reports[i],b=reports[j];if(a.pool!==b.pool)continue;
    comparisons.push({first:a.directory,second:b.directory,pool:a.pool,
      same_map_hash:a.map_hash===b.map_hash,same_semantic_values:a.semantic_sha256===b.semantic_sha256,
      same_raw_arrays:JSON.stringify(a.arrays)===JSON.stringify(b.arrays)});
  }
  fs.writeFileSync(output,JSON.stringify({reports,comparisons},null,2));
  console.log(JSON.stringify({captures:reports.map(r=>({pool:r.pool,entities:r.entities,properties:r.properties,readback:r.readback_unchanged})),comparisons},null,2));
}
module.exports={audit};
