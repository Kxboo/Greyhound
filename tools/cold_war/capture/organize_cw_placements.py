"""Categorize a saved CW placement run; copy by default, or finalize it in place."""

# Support direct execution and the isolated packaged Python runtime.
import sys as _tool_sys
from pathlib import Path as _ToolPath
TOOLS_ROOT = next(p for p in _ToolPath(__file__).resolve().parents if (p / "tool_bootstrap.py").is_file())
_tool_sys.path.insert(0, str(TOOLS_ROOT))
import tool_bootstrap as _tool_bootstrap
_tool_bootstrap.activate(__file__)
REPO_ROOT = TOOLS_ROOT.parent
import argparse,hashlib,json,shutil,tempfile
from pathlib import Path

FILES={
 'fx_placements.json':'fx/placements.json','fx_assets.json':'fx/assets.json','fx_entity_references.json':'fx/entity_references.json',
 'fx_placement_candidates.json':'fx/source_candidates.json',
 'animation_model_placements.json':'animation/model_placements.json','animation_entity_references.json':'animation/entity_references.json',
 'named_animation_references.json':'animation/named_references.json','animation_assets.json':'animation/assets.json',
 'static_models.json':'models/static.json','non_static_models.json':'models/non_static.json','spline_models.json':'models/spline.json',
 'dynmodel_assets.json':'models/dynamic_definitions.json','light_placement_candidates.json':'lights/placements.json','light_placements.json':'lights/decoded_placements.json',
 'reflection_probes.json':'probes/placements.json','reflection_probe_bounds.json':'probes/bounds.json','sun_volumes.json':'sun/volumes.json',
 'trigger_geometry_candidates.json':'triggers/geometry.json',
 'bo3_mapping.json':'metadata/bo3_mapping.json','placement_catalog.json':'metadata/placement_catalog.json',
 'fx_anm_catalog.json':'metadata/fx_anm_catalog.json','non_static_report.json':'metadata/non_static_report.json',
 'placement_report.json':'metadata/placement_report.json','fx_anm_validation.json':'metadata/fx_anm_validation.json',
}
PATH_KEYS={'file','SourcePlacementFile','SourceEntityFile','SourceProbeFile','BoundsFile','EffectAssetFile','bo3_mapping','capture_report','deferred_spline_evidence','report','files'}
SOURCE_PROPERTIES={'Properties','AttachedEntityProperties','MatchedReferenceProperties','properties'}
PREFIXES={'non_static_models/':'models/by_class/','reflection_probes/':'probes/descriptors/','reflection_probe_bounds/':'probes/bounds_by_descriptor/'}

def mapped(path):
    # Deliberately preserve the existing entity/evidence subdirectories. They
    # contain internal relative paths and remain self-contained source evidence.
    for before,after in PREFIXES.items():
        if path.startswith(before):return after+path[len(before):]
    return FILES.get(path,path)

def rewrite(value,key=None,aliases=None):
    if key in SOURCE_PROPERTIES:return value
    if isinstance(value,dict):return {k:rewrite(v,k,aliases) for k,v in value.items()}
    if isinstance(value,list):return [rewrite(v,key,aliases) for v in value]
    if isinstance(value,str) and key in PATH_KEYS:return (aliases or {}).get(value,mapped(value))
    return value

def digest(path):
    result=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):result.update(block)
    return result.hexdigest()

def verify(directory,catalog):
    for record in catalog['files']:
        if digest(directory/record['file'])!=record['sha256']:
            raise ValueError('Organized file checksum mismatch: '+record['file'])

def organize(source,destination):
    source=Path(source).resolve();destination=Path(destination).resolve()
    if destination.exists():raise ValueError('Choose a new output directory; existing captures are preserved.')
    if destination==source or source in destination.parents:raise ValueError('Output must not be inside the source run.')
    if not (source/'fx_anm_catalog.json').is_file():raise ValueError('Expected a completed focused capture.')
    # Preflight every destination before writing, including fallback metadata.
    # A collision must never silently replace another captured file.
    paths=[];aliases={};targets=set()
    for path in sorted(source.rglob('*')):
        if path.is_symlink() or (hasattr(path,'is_junction') and path.is_junction()):
            raise ValueError('Capture links are not supported: '+str(path))
        if not path.is_file():continue
        relative=path.relative_to(source).as_posix();target_relative=mapped(relative)
        if '/' not in target_relative and target_relative not in FILES.values():
            target_relative=('metadata/' if path.suffix=='.json' else 'notes/')+target_relative
        if target_relative.casefold() in targets:raise ValueError('Output path collision: '+target_relative)
        targets.add(target_relative.casefold());aliases[relative]=target_relative;paths.append(path)
    destination.mkdir(parents=True)
    records=[]
    for path in paths:
        relative=path.relative_to(source).as_posix();target_relative=aliases[relative]
        source_hash=digest(path)
        target=destination/target_relative;target.parent.mkdir(parents=True,exist_ok=True)
        # Evidence JSON must remain byte-for-byte unchanged. Rewrite only public
        # path fields; never rewrite captured authoring property values.
        if path.suffix=='.json' and not relative.startswith('diagnostics/'):
            data=json.loads(path.read_text(encoding='utf-8'));target.write_text(json.dumps(rewrite(data,aliases=aliases),indent=2)+'\n',encoding='utf-8')
        else:shutil.copy2(path,target)
        if digest(path)!=source_hash:raise ValueError('Source changed during organization: '+relative)
        records.append({'source':relative,'file':target_relative,'source_sha256':source_hash,'sha256':digest(target)})
    catalog={'schema':'cw-organized-placements-v1','source_run':str(source),'map_hash':json.loads((source/'fx_anm_catalog.json').read_text())['map_hash'],
        'categories':{'fx':'fx/','animation':'animation/','models':'models/','entities':'entities/','lights':'lights/','probes':'probes/','sun':'sun/','triggers':'triggers/','evidence':'diagnostics/','reports':'metadata/'},
        'path_aliases':aliases,'prefix_aliases':PREFIXES,'files':records}
    (destination/'catalog.json').write_text(json.dumps(catalog,indent=2)+'\n')
    (destination/'README.md').write_text('''# Cold War placements

Start with `catalog.json` for the map hash, complete file inventory, old-to-new
path aliases, and source/output SHA-256 checksums. All public paths are relative
to this run root. Only categories captured for this run will contain files.

| Folder | Contents / next step |
| --- | --- |
| `models/` | Select `static.json` or `non_static.json` in Models from JSON. |
| `animation/` | Model placements, entity references and named animation assets. |
| `fx/` | Effect placements, referenced assets and source candidates. |
| `entities/` | Original entity classes and properties. |
| `lights/`, `probes/`, `sun/` | Lighting records, candidates and influence bounds. |
| `triggers/` | Trigger geometry and source references. |
| `metadata/` | Completeness reports, mappings and available validation results. |
| `diagnostics/` | Unchanged raw evidence for independent decoding. |

These files contain placement data, not the model meshes. Spline records require
deformation and are not interchangeable with rigid static placements. Multiple
instances of a model are intentional; do not deduplicate rows by model name.

Source and output hashes can differ for public JSON because file references are
rewritten. Captured authoring properties and diagnostic evidence are preserved.
Flat-layout auditors should run before organization; their saved results move
into `metadata/`. A checksum check establishes file integrity, not complete BO3
visual equivalence, compilation or gameplay behavior.
''',encoding='utf-8')
    return catalog

def organize_in_place(source):
    source=Path(source).resolve()
    if (source/'catalog.json').is_file():
        catalog=json.loads((source/'catalog.json').read_text(encoding='utf-8'))
        if catalog.get('schema')!='cw-organized-placements-v1':raise ValueError('Unknown placement catalog schema')
        verify(source,catalog)
        return catalog
    # Both renames stay on the same volume. Publish only after validating the
    # staged run and checking that no input was added, removed or changed.
    workspace=Path(tempfile.mkdtemp(prefix=source.name+'.organizing-',dir=source.parent))
    staged=workspace/'organized';backup=workspace/'original'
    try:
        catalog=organize(source,staged)
        verify(staged,catalog)
        actual={p.relative_to(source).as_posix() for p in source.rglob('*') if p.is_file()}
        if actual!={r['source'] for r in catalog['files']}:raise ValueError('Source file inventory changed')
        for record in catalog['files']:
            if digest(source/record['source'])!=record['source_sha256']:
                raise ValueError('Source changed before publication: '+record['source'])
        source.rename(backup)
        try:staged.rename(source)
        except Exception:
            backup.rename(source)
            raise
        # Only this transaction's verified backup can be removed. If cleanup
        # fails, keep it and report its location rather than undoing publication.
        try:shutil.rmtree(backup)
        except OSError:catalog['retained_backup']=str(backup)
        return catalog
    finally:
        if not backup.exists():shutil.rmtree(workspace)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('source',type=Path);p.add_argument('destination',type=Path,nargs='?')
    p.add_argument('--in-place',action='store_true',help='Replace a completed flat run after staged checksum verification')
    a=p.parse_args()
    if a.in_place == (a.destination is not None):p.error('Supply a destination OR --in-place')
    result=organize_in_place(a.source) if a.in_place else organize(a.source,a.destination)
    print(json.dumps({'directory':str((a.source if a.in_place else a.destination).resolve()),'files':len(result['files']),'map_hash':result['map_hash'],'retained_backup':result.get('retained_backup')},indent=2))
