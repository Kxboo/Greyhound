"""Explain placement counts without dropping source records or changing exports."""

# Support direct execution and the isolated packaged Python runtime.
import sys as _tool_sys
from pathlib import Path as _ToolPath
TOOLS_ROOT = next(p for p in _ToolPath(__file__).resolve().parents if (p / "tool_bootstrap.py").is_file())
_tool_sys.path.insert(0, str(TOOLS_ROOT))
import tool_bootstrap as _tool_bootstrap
_tool_bootstrap.activate(__file__)
REPO_ROOT = TOOLS_ROOT.parent
import collections,hashlib,json,math
from pathlib import Path
import numpy as np

REPO=REPO_ROOT
ROOT=REPO/'src/WraithXCOD/x64/Release/exported_files/black_ops_cw/placements/run_01'

def xyz(row,key):return tuple(row[key][a] for a in 'XYZ')
def key(row):
    q=tuple(row['RotationQuaternion'][a] for a in 'XYZW')
    if next((x for x in reversed(q) if x),1)<0:q=tuple(-x for x in q)
    return (row.get('SourceName',row['Name']),xyz(row,'Position'),q,xyz(row,'ModelScale'),row.get('RequiresSplineDeformation'),row.get('SplineInstanceIndex'))

def main():
    rows=json.loads((ROOT/'static_models.json').read_text())
    names=collections.Counter(r['Name'] for r in rows)
    groups=collections.defaultdict(list);identities=collections.defaultdict(list)
    for i,r in enumerate(rows):groups[r['District']].append(i);identities[key(r)].append(i)
    duplicates=[v for v in identities.values() if len(v)>1]
    report=dict(total=len(rows),unique_names=len(names),top_models=names.most_common(60),
        transform_duplicate_groups=len(duplicates),transform_duplicate_excess=sum(len(v)-1 for v in duplicates),
        cross_district_duplicate_groups=sum(len({rows[i]['District'] for i in v})>1 for v in duplicates),
        cross_source_duplicate_groups=sum(len({rows[i]['PlacementSource'] for i in v})>1 for v in duplicates),
        duplicate_examples=[[dict(index=i,name=rows[i]['Name'],district=rows[i]['District'],source=rows[i]['PlacementSource'],flags=rows[i]['ReferenceFlagsRaw']) for i in v[:12]] for v in sorted(duplicates,key=len,reverse=True)[:15]],
        district_summary=[],source_summary={},named_categories={},
        source_file=str(ROOT/'static_models.json'),classification='Name categories are descriptive heuristics, not decoded runtime visibility.')
    for district,ids in sorted(groups.items()):
        subset=[rows[i] for i in ids];p=np.array([xyz(r,'Position') for r in subset]);c=collections.Counter(r['Name'] for r in subset)
        report['district_summary'].append(dict(district=district,placements=len(ids),unique_names=len(c),top_models=c.most_common(20),
            sources=dict(collections.Counter(r['PlacementSource'] for r in subset)),
            flags=dict(collections.Counter(r['ReferenceFlagsRaw'] for r in subset)),
            bounds=[p.min(0).tolist(),p.max(0).tolist()],spline=sum(r.get('RequiresSplineDeformation',False) for r in subset),
            resolved=sum(r['NameResolved'] for r in subset)))
    for source in sorted({r['PlacementSource'] for r in rows}):
        sub=[r for r in rows if r['PlacementSource']==source];c=collections.Counter(r['Name'] for r in sub)
        report['source_summary'][source]=dict(placements=len(sub),unique_names=len(c),top_models=c.most_common(35))
    for category,tokens in {'proxy':['proxy','imposter','impostor'], 'vegetation':['grass','foliage','weed','bush','shrub','fern','flower','tree','moss','vine'], 'helpers':['tag_origin','tag_point'], 'unresolved':['xmodel_']}.items():
        c={n:v for n,v in names.items() if any(t in n.lower() for t in tokens)}
        report['named_categories'][category]=dict(placements=sum(c.values()),unique_names=len(c),top_models=sorted(c.items(),key=lambda a:-a[1])[:20])
    out=REPO/'test-output/cw-placement-counts';out.mkdir(parents=True,exist_ok=True)
    (out/'audit.json').write_text(json.dumps(report,indent=2))
    lines=['Model\tPlacements\tLive\tPackage']
    counters={s:collections.Counter(r['Name'] for r in rows if r['PlacementSource']==s) for s in ['live','local_package']}
    lines += [f"{n}\t{count}\t{counters['live'][n]}\t{counters['local_package'][n]}" for n,count in names.most_common()]
    (out/'model_counts.tsv').write_text('\n'.join(lines)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k not in ('district_summary','duplicate_examples','source_file')},indent=2),flush=True)
    print('districts',[(r['district'],r['placements'],r['unique_names'],r['top_models'][:3]) for r in report['district_summary']])

if __name__=='__main__':main()
