"""Partition a CW placement array; preserve all source rows exactly once.

Split only by the recorded decode source, not by vegetation names or visibility.
"""

# Support direct execution and the isolated packaged Python runtime.
import sys as _tool_sys
from pathlib import Path as _ToolPath
TOOLS_ROOT = next(p for p in _ToolPath(__file__).resolve().parents if (p / "tool_bootstrap.py").is_file())
_tool_sys.path.insert(0, str(TOOLS_ROOT))
import tool_bootstrap as _tool_bootstrap
_tool_bootstrap.activate(__file__)
REPO_ROOT = TOOLS_ROOT.parent
import collections,hashlib,json
from pathlib import Path

REPO=REPO_ROOT
ROOT=REPO/'src/WraithXCOD/x64/Release/exported_files/black_ops_cw/placements/run_01'
def category(row):
    if row['PlacementSource']=='live':return 'main_live'
    if row['PlacementSource']=='local_package':return 'local_package'
    raise ValueError('Unexpected placement source')

def main():
    source=ROOT/'static_models.json'
    rows=json.loads(source.read_text())
    groups={name:[] for name in ('main_live','local_package')}
    for i,r in enumerate(rows):groups[category(r)].append(i)
    out=ROOT/'split';out.mkdir(exist_ok=True)
    old=json.loads((out/'split_report.json').read_text()) if (out/'split_report.json').exists() else {}
    superseded=[r for r in old.get('files',[]) if r['file'] in ('static_models_package_ground_cover.json','static_models_package_trees.json')]
    summaries=[]
    for name,indices in groups.items():
        path=out/f'static_models_{name}.json'
        # One record per line keeps these large plain arrays compact and usable.
        data=('[\n'+',\n'.join(json.dumps(rows[i],ensure_ascii=False,separators=(',',':')) for i in indices)+'\n]\n').encode('utf-8')
        if path.exists() and path.read_bytes()!=data:raise ValueError('Different existing split retained: '+str(path))
        if not path.exists():path.write_bytes(data)
        restored=json.loads(path.read_bytes())
        assert len(restored)==len(indices)
        assert all(actual==rows[i] for actual,i in zip(restored,indices))
        c=collections.Counter(r['Name'] for r in restored)
        summaries.append(dict(file=path.name,placements=len(indices),unique_models=len(c),bytes=len(data),
            sha256=hashlib.sha256(data).hexdigest(),districts=sorted({r['District'] for r in restored}),
            models=dict(c.most_common()),all_rows_equal_source=True))
        print(name,len(indices),'placements',len(c),'models',round(len(data)/1048576,2),'MiB',flush=True)
    assert sorted(i for ids in groups.values() for i in ids)==list(range(len(rows)))
    report=dict(schema='cw-placement-source-split-v2',source=str(source),
        source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),source_count=len(rows),
        semantics='Non-overlapping import selections, not decoded visibility or player-collision classifications.',
        policy=dict(main_live='All live-source districts, including their authored vegetation.',
            local_package='All locally decoded package districts, including both ground cover and trees.'),
        no_transforms_changed=True,no_records_removed=True,source_indices_partitioned_exactly_once=True,
        exact_transform_duplicates_preserved=True,files=summaries,superseded_generated_files=superseded)
    (out/'split_report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    (out/'README.txt').write_text(
        'CW placement JSON split by decode source\n\n'
        'static_models_main_live.json: 106,785 live-source placements. Includes authored vegetation and helpers.\n'
        'static_models_local_package.json: 152,832 package-source placements across 14 vegetation models, including grass, weeds and trees.\n\n'
        'Every original row is in exactly one file, in source order, with every field preserved.\n'
        'These are plain placement arrays for the same importer. Both files together reproduce the full source export.\n'
        'Do not also import the original full static_models.json, which would duplicate the selections.\n'
        'No source data was deleted; visibility/proxy and spline limitations still apply. See split_report.json.\n',encoding='utf-8')

if __name__=='__main__':main()
