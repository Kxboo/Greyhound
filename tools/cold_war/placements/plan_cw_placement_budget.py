"""Read-only, name/size based budget candidates; not a visibility classifier."""

# Support direct execution and the isolated packaged Python runtime.
import sys as _tool_sys
from pathlib import Path as _ToolPath
TOOLS_ROOT = next(p for p in _ToolPath(__file__).resolve().parents if (p / "tool_bootstrap.py").is_file())
_tool_sys.path.insert(0, str(TOOLS_ROOT))
import tool_bootstrap as _tool_bootstrap
_tool_bootstrap.activate(__file__)
REPO_ROOT = TOOLS_ROOT.parent
import collections,json,re
from pathlib import Path
import numpy as np

REPO=REPO_ROOT
ROOT=REPO/'src/WraithXCOD/x64/Release/exported_files/black_ops_cw/placements/run_01/split'

def group(name):
    tokens=set(name.lower().split('_'))
    if name.startswith('xmodel_'):return 'unresolved_keep'
    if name=='tag_origin':return 'helper_review'
    if tokens&{'tree','foliage','weed','weeds','grass','flower','flowers','fern','moss','vine','vines','bush','shrub'}:return 'vegetation_review'
    if tokens&{'bolt','bolts','screw','screws','washer','nut','nuts'}:return 'fasteners'
    if tokens&{'bracket','brackets','strap','clamp','clamps','coupling'}:return 'brackets_fittings_review'
    if tokens&{'trash','bottle','bottles','paper','paperbag','newspaper','wrapper','snack','cup','drink','can','cans','cigarette','ashtray'}:return 'loose_clutter'
    if tokens&{'debris','rubble','clump','pebble','pebbles'}:return 'rubble_review'
    if tokens&{'book','books','magazine','magazines','cassette','cd','dvd','vhs'} or ('case' in tokens and 'movie' in tokens):return 'shelf_items_review'
    return 'other_keep'

def main():
    rows=json.loads((ROOT/'static_models_main_live.json').read_text())
    models=collections.defaultdict(list)
    for r in rows:models[r['Name']].append(r)
    ranked=[]
    for name,instances in models.items():
        sizes=np.array([[r['BoundsMax'][a]-r['BoundsMin'][a] for a in 'XYZ'] for r in instances])
        maximum=sizes.max(axis=1)
        ranked.append(dict(name=name,instances=len(instances),category=group(name),
            world_aabb_max_side_median=float(np.median(maximum)),world_aabb_max_side_max=float(maximum.max()),
            spline_instances=sum(bool(r['RequiresSplineDeformation']) for r in instances)))
    ranked.sort(key=lambda r:(-r['instances'],r['name']))
    categories=[]
    for cat in sorted({r['category'] for r in ranked}):
        members=[r for r in ranked if r['category']==cat]
        categories.append(dict(category=cat,models=len(members),placements=sum(r['instances'] for r in members),
            placements_with_all_instances_at_most_32=sum(r['instances'] for r in members if r['world_aabb_max_side_max']<=32),
            placements_with_all_instances_at_most_64=sum(r['instances'] for r in members if r['world_aabb_max_side_max']<=64),
            placements_with_all_instances_at_most_128=sum(r['instances'] for r in members if r['world_aabb_max_side_max']<=128)))
    # A proposal only. No source placement rows or filenames are changed.
    plans=[];excluded=set()
    stages=[('Small fasteners',{'fasteners'},64),
        ('Small brackets and fittings',{'brackets_fittings_review'},64),
        ('Small loose clutter',{'loose_clutter'},64),
        ('Small rubble',{'rubble_review'},64),
        ('Small shelf items',{'shelf_items_review'},64)]
    byname={r['name']:r for r in ranked}
    for label,cats,size in stages:
        chosen={r['name'] for r in ranked if r['category'] in cats and r['world_aabb_max_side_max']<=size and r['spline_instances']==0}
        count=sum(byname[n]['instances'] for n in chosen)
        excluded|=chosen
        plans.append(dict(label=label,models=sorted(chosen),placements=count,remaining=len(rows)-sum(byname[n]['instances'] for n in excluded)))
    static_remainder=[r for r in rows if r['Name'] not in excluded]
    deferred_splines=[r for r in static_remainder if r['RequiresSplineDeformation']]
    package_unaffected=True
    plan=dict(source_file=str(ROOT/'static_models_main_live.json'),source_count=len(rows),
        hard_budget=65536,changes_applied=False,stages=plans,
        detail_only_remaining=len(static_remainder),
        optional_spline_holdback=dict(placements=len(deferred_splines),
            unique_models=len({r['Name'] for r in deferred_splines}),
            top_models=collections.Counter(r['Name'] for r in deferred_splines).most_common(20),
            remaining=len(static_remainder)-len(deferred_splines),
            reason='RequiresSplineDeformation flag is present; this placement export does not carry deformation controls. This is not evidence of visual insignificance.'),
        restores_from='Original placement JSON retains every model and transform. Apply selections as disjoint keep/deferred arrays if approved.',
        caveat='Name and size selection estimates visual cost; it does not prove an object unimportant. The budget excludes package foliage and any other BO3 map entities already present.')
    out=REPO/'test-output/cw-placement-counts'
    (out/'proposed_budget_plan.json').write_text(json.dumps(plan,indent=2))
    (out/'budget_candidates.json').write_text(json.dumps(dict(placements=len(rows),budget=65536,
        minimum_to_defer=len(rows)-65536,categories=categories,models=ranked,
        caveat='Categories are reviewed-name candidates only. Size uses captured world AABBs; spline bounds/geometry require extra care. No placements removed.'),indent=2))
    print(json.dumps({k:v for k,v in plan.items() if k!='stages'},indent=2))
    print('STAGES',[(p['label'],p['placements'],p['remaining']) for p in plans])

if __name__=='__main__':main()
