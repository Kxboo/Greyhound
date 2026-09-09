"""Greyhound's packaged CW brush-to-Radiant pipeline. No BO3 installation needed."""
import argparse, contextlib, hashlib, io, json, os, re, sys, traceback, shutil
from collections import Counter
from pathlib import Path

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE/'pipeline'))
from cw_export_progress import write_progress
from cw_export_layout import map_name, publish

def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--capture',required=True,type=Path)
    p.add_argument('--output',required=True,type=Path)
    p.add_argument('--map-path',default='')
    p.add_argument('--auto-types',action='store_true')
    p.add_argument('--trigger-capture',type=Path)
    a=p.parse_args();a.capture=a.capture.resolve();a.output=a.output.resolve()
    progress=a.capture/'radiant_progress.json'
    def status(stage,percent=0,**extra):
        data=dict(stage=stage,percent=percent,**extra)
        if not write_progress(progress,data):
            # Do not convert a transient progress-file lock into export failure.
            # The final export_report.json remains the completion authority.
            return False
        return True
    try:
        if (a.output/'metadata/export_report.json').exists():raise ValueError('Output already exists; use a new capture')
        manifest=json.loads((HERE/'manifest.json').read_text())
        for name,digest in manifest['files'].items():
            target=(HERE/name).resolve()
            if not target.is_relative_to(HERE) or sha(target)!=digest:raise ValueError('Packaged converter failed integrity check: '+name)
        status('Checking verified capture')
        owners=json.loads((a.capture/'collision_world_instances.json').read_text())
        key=int(owners['map_hash'],16)
        from cw_collision_names import hash63
        resolved=a.map_path.replace('\\','/')
        name=map_name(key,resolved)
        if not re.fullmatch('[A-Za-z0-9_-]+',name):name='cw_map_'+format(key,'016x')
        work=a.capture/'radiant_work';work.mkdir(exist_ok=False)
        reference=json.loads((HERE/'bo3_reference.json').read_text())
        tool_gdt=work/'tool_materials.gdt'
        tool_gdt.write_text('{\n'+''.join('"'+m['name']+'" ( "material.gdf" ) { "noDraw" "'+m['properties'].get('noDraw','0')+'" }\n'
            for m in reference['materials'])+'}\n')
        log=(a.capture/'radiant_conversion.log').open('w',encoding='utf-8')
        class ProgressLog(io.TextIOBase):
            pending=''
            def write(self,text):
                log.write(text);log.flush();self.pending+=text
                while '\n' in self.pending:
                    line,self.pending=self.pending.split('\n',1)
                    match=re.match(r'(Hulls|Placements): (\d+)/(\d+)',line)
                    if match:status(line,100*int(match[2])//max(1,int(match[3])))
                return len(text)
            def flush(self):
                if not log.closed:log.flush()
        stream=ProgressLog()
        def run(module,args,stage):
            status(stage);sys.argv=[module,*map(str,args)]
            with contextlib.redirect_stdout(stream):__import__(module).main()
        normalized=work/'normalized';geometry=work/'geometry';staged=work/'final'
        run('prepare_cw_native_brush_capture',[a.capture,'--map',name,'--verified-map-hash',format(key,'x'),'--output',normalized],'Checking brush ownership and placements')
        run('export_cw_radiant_brushes',[normalized,'--output',geometry,'--gdt',tool_gdt,'--max-faces','12','--cleanup-world-tolerance','0.01','--halfspace-partitions','--canonical-planes'],'Building brush hulls')
        assignments=None
        if a.auto_types:
            status('Selecting BO3 brush and tool types from captured properties')
            from assign_cw_bo3_types import apply
            assignments=apply(normalized,a.capture,reference,geometry)
        run('separate_cw_tool_surface_projections',[geometry,'--output',staged,'--gdt',tool_gdt],'Writing Radiant tool surfaces')
        if assignments is not None:shutil.copy2(geometry/'material_assignments.json',staged/'material_assignments.json')
        volumes=None
        if a.trigger_capture:
            status('Writing separate trigger and volume prefabs')
            from export_cw_bo3_trigger_entities import export as export_entities
            with contextlib.redirect_stdout(stream):volumes=export_entities(a.trigger_capture,name,staged,reference,expected_hash=key)
        status('Verifying complete brush coverage')
        capture=json.loads((normalized/'capture.json').read_text());m=json.loads((staged/'collision_metadata.json').read_text())
        expected={(i['collision_world'],i['instance_index'],i['model_index'],bi) for i in capture['instances'] for bi in range(capture['models'][i['model_index']]['brush_count'])}
        actual={}
        for row in m['rows']:
            k=(row['collision_world'],row['instance_index'],row['collision_asset_index'],row['brush_index'])
            actual.setdefault(k,[]).append(row['partition_piece'])
        if set(actual)!=expected or any(sorted(ids)!=list(range(len(ids))) for ids in actual.values()):raise ValueError('Brush coverage verification failed')
        if len(m['partition_certificates'])!=capture['summary']['unique_brushes']:raise ValueError('Missing hull certificates')
        if not expected:raise ValueError('No supported placed brushes; no prefab exported')
        target=staged/(name+'_brush_collision.map')
        if sha(target)!=m['map_sha256']:raise ValueError('Map integrity check failed')
        from split_cw_brush_roles import split as split_brush_roles
        status('Separating collision clips from other brush roles')
        brush_prefabs=split_brush_roles(staged,reference)
        report=dict(schema='greyhound-cw-radiant-v5',status='exported',map=name,map_hash=owners['map_hash'],name_resolved=not name.startswith('cw_map_'),
            map_file=target.name,summary=m['summary'],bounded_cleanup=m['bounded_cleanup'],all_placed_brushes_present=True,
            source_capture=str(a.capture),converter_manifest_sha256=sha(HERE/'manifest.json'),map_sha256=sha(target),
            scope='Supported brush hulls only; other collision mesh layouts and render models are not included.',
            compiler_validated=False,compile_note='Prefab export only. No BO3 map host, compilation, lighting or linking was performed.')
        report['automatic_materials']=assignments['summary'] if assignments else {'enabled':False}
        report['trigger_entities']=volumes['summary'] if volumes else {'enabled':False}
        report['bo3_reference_sha256']=sha(HERE/'bo3_reference.json')
        report['scope']='Brush collision and optional supported trigger/volume entities. Render models, unsupported layouts and gameplay scripts are separate.'
        report['primary_map_file']=target.name
        report['prefabs']=brush_prefabs
        report['summary']['collision_clip_brushes']=brush_prefabs['brushes_clips']['brushes']
        report['summary']['other_brushes']=brush_prefabs['other_brushes']['brushes']
        report['all_placed_brushes_present_across_prefabs']=True
        if volumes is not None:
            report['prefabs'].update(volumes['map_files'])
        report['prefab_layout']='separate_world_space_prefabs'
        (staged/'export_report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        shutil.copy2(HERE/'manifest.json',staged/'converter_manifest.json')
        log.close();a.output.parent.mkdir(parents=True,exist_ok=True);publish(staged,a.output)
        status('Export complete: '+str(len(report['prefabs']))+' separate prefab(s) in '+str(a.output),100,status='exported',output=str(a.output),map_file=report['primary_map_file'],prefabs=report['prefabs'])
        return 0
    except Exception as error:
        (a.capture/'radiant_error.log').write_text(traceback.format_exc(),encoding='utf-8')
        status('Brush export failed: '+str(error),0,status='failed')
        return 1

if __name__=='__main__':sys.exit(main())
