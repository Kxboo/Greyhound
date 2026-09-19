// Read the GDT tool's real parser without modifying it or writing any GDT.
const fs=require('fs'),path=require('path'),vm=require('vm'),assert=require('assert');
const [app,root]=process.argv.slice(2);
if(!app||!root)throw Error('Usage: node verify_bo4_gdt_intake.cjs <GDT project> <materials package>');
// Reuse the application's existing DOM stub, not an alternate material parser.
const harness=fs.readFileSync(path.join(app,'tests/test_superterrain.js'),'utf8');
const end=harness.indexOf("const assert = require('assert');");
if(end<0)throw Error('GDT verification harness changed');
const context={require,console,process:{argv:['node','verification',path.join(app,'src/index.html')]},
  Event,Blob,URL,Response,DecompressionStream,atob,setTimeout,clearTimeout};
vm.createContext(context);
vm.runInContext(harness.slice(0,end)+'\nglobalThis.api=ctx;',context);
const api=context.api;
const recipe=JSON.parse(fs.readFileSync(path.join(root,'superterrain_materials.json')));
const report=JSON.parse(fs.readFileSync(path.join(root,'material_report.json')));
const infos={},buckets={},allImages=new Map();
for(const m of report.materials){
 const name=path.basename(m.source_txt).replace(/_images\.txt$/i,'').toLowerCase();
 infos[name]=api.parseMatInfoText(fs.readFileSync(path.join(root,m.package_txt.images.file),'utf8'));
 buckets[name]=m.packaged_images.map(im=>{
  assert(fs.existsSync(path.join(root,im.file)),im.file);
  const file={name:path.basename(im.file),webkitRelativePath:'materials/'+im.file};
  allImages.set(path.parse(file.name).name.toLowerCase(),file);return file;
 });
}
const expanded=api.expandSuperTerrainRecipe(recipe,infos,buckets), used=new Set(), checks=[];
// Use the declared variant, not endsWith('_blend'): a captured opaque asset
// can already have '_blend' in its original name.
for(const row of recipe.materials){
 for(const [field,type] of [['opaque_material','lit'],['blend_material','lit_decal']]){
  const name=row[field];
  const result=api.buildFlatMaterialEntry(name,expanded.buckets[name],'black_ops_4','lit',expanded.infos[name],null,used,{},allImages);
  assert.equal(result.treeEntry.name,name);
  assert.equal(result.treeEntry.materialType,type);
  assert.equal(result.missingReferencedSourceImages.length,0, name);
  const source=infos[row.source_material];
  assert.equal(result.treeEntry.colorMap.toLowerCase(),source.roleValues.color.toLowerCase(),name+' color');
  assert.equal(result.treeEntry.normalMap.toLowerCase(),source.roleValues.normal.toLowerCase(),name+' normal');
  checks.push({material:name,type,color:result.treeEntry.colorMap,normal:result.treeEntry.normalMap,
    gloss:result.treeEntry.glossMap,occlusion:result.treeEntry.occMap,
    missing_replacements:result.missingImageReplacements});
 }
}
const audit={status:'verified_with_GDT_source_parser',source:path.join(app,'src/index.html'),
 source_sha256:require('crypto').createHash('sha256').update(fs.readFileSync(path.join(app,'src/index.html'))).digest('hex'),
 material_definitions:report.materials.length,material_variants:checks.length,checks,
 scope:'Parser and material assembly in memory; no GDT written, no BO3 compiler or desktop binary validation'};
fs.writeFileSync(path.join(root,'intake_verification.json'),JSON.stringify(audit,null,2)+'\n');
console.log(JSON.stringify({status:audit.status,material_definitions:audit.material_definitions,material_variants:checks.length}));
