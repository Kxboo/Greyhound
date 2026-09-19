"""Locate CW compound-model brush components using their counted section layout.

The 80-byte quantized-surface headers precede inline byte/word coordinates,
group words, and unpadded acceleration data. Their live pointers independently
validate these offsets. The following 8-aligned brush header is the same
208-byte structure used by the established world-brush decoder.
Compact triangle topology is deliberately not promoted to verified brushes.
"""

# Support direct execution and the isolated packaged Python runtime.
import sys as _tool_sys
from pathlib import Path as _ToolPath
TOOLS_ROOT = next(p for p in _ToolPath(__file__).resolve().parents if (p / "tool_bootstrap.py").is_file())
_tool_sys.path.insert(0, str(TOOLS_ROOT))
import tool_bootstrap as _tool_bootstrap
_tool_bootstrap.activate(__file__)
REPO_ROOT = TOOLS_ROOT.parent
import hashlib,json,struct
from pathlib import Path
from audit_cw_clip_payloads import read_logical
from export_cross_map_cw_geometry import decode_brushes


def prepare(native,destination):
    evidence=json.loads((native/'evidence.json').read_text())
    source=json.loads((native/'clip_map_models.json').read_text())
    owners=json.loads((native/'model_collision_owners.json').read_text())
    wanted={int(m['collision_pointer'],16) for m in owners['models']}
    rows=[];diagnostics={}
    destination.mkdir(parents=True,exist_ok=True);(destination/'payloads').mkdir(exist_ok=True)
    for index,model in enumerate(source['models']):
        pointer=int(model['record_address'],16)
        if pointer not in wanted:continue
        result=dict(index=index,record_address=model['record_address'],name=model['name'])
        try:
            payload=model['payload']
            if payload['status']!='captured' or not payload['readback_unchanged']:raise ValueError('unstable_source')
            raw=read_logical(native,evidence,payload['file'])
            if len(raw)!=payload['allocated_bytes']:raise ValueError('incomplete_source')
            base=int(payload['address'],16)
            bindings,count=struct.unpack_from('<2H',raw,296);brush_components=struct.unpack_from('<I',raw,300)[0]
            if not bindings or bindings>1024 or count>4096 or brush_components>16:raise ValueError('unsupported_compound_counts')
            header=(304+bindings+7)&~7;pos=header+80*count
            if pos>len(raw):raise ValueError('header_outside_allocation')
            checked=0
            for i in range(count):
                h=header+80*i
                q16,q8,qgroups,qtree=struct.unpack_from('<4Q',raw,h)
                tail=struct.unpack_from('<I',raw,h+32)[0];ng,n8,n16=struct.unpack_from('<3H',raw,h+38)
                b8=pos;b16=(b8+3*n8+1)&~1;groups=(b16+6*n16+3)&~3;tree=groups+4*ng;pos=tree+tail
                if pos>len(raw):raise ValueError('surface_extent_outside_allocation')
                for pointer_value,offset,length in ((q8,b8,3*n8),(q16,b16,6*n16),(qgroups,groups,4*ng),(qtree,tree,tail)):
                    if pointer_value:
                        if pointer_value!=base+offset or not length:raise ValueError('surface_pointer_disagrees_with_layout')
                        checked+=1
            result.update(compact_triangle_surfaces=count,verified_section_pointers=checked,
                          source_payload_sha256=hashlib.sha256(raw).hexdigest())
            if brush_components==0:
                if ((pos+3)&~3)!=len(raw) and count:raise ValueError('unaccounted_payload_tail')
                result['status']='compact_triangles_only' if count else 'no_collision_geometry'
            elif brush_components!=1:
                result['status']='multiple_brush_components_not_decoded'
            else:
                at=(pos+7)&~7
                if at+208>len(raw):raise ValueError('missing_brush_component_header')
                # Adapt offsets for the existing decoder without modifying any
                # stored geometry bytes. Virtual base translates pointer checks.
                adapted=bytes(312)+raw[at:]
                box=struct.unpack_from('<6f',adapted,336)
                local=dict(model,index=index,mins=list(box[:3]),maxs=list(box[3:]),
                    payload=dict(payload,address=hex(base+at-312)))
                decoded=decode_brushes(adapted,local)
                if not decoded or decoded['status']!='decoded':
                    result['status']='brush_component_'+str(decoded and decoded['status'])
                else:
                    name=f'payloads/{index:05d}.bin';(destination/name).write_bytes(adapted)
                    local.update(status='decoded',brush_count=decoded['brush_count'])
                    local['payload'].update(file=name,sha256=hashlib.sha256(adapted).hexdigest())
                    local['component_source']=dict(source_file=payload['file'],source_offset=at,adapter_prefix_bytes=312,
                        source_payload_sha256=hashlib.sha256(raw).hexdigest(),compact_triangle_surfaces_not_exported=count)
                    rows.append(local);result.update(status='decoded_brush_component',source_offset=at,brush_count=decoded['brush_count'])
        except (ValueError,struct.error) as exc:
            result.update(status='unsupported',reason=str(exc))
        diagnostics[model['record_address']]=result
    world=json.loads((native/'collision_world_instances.json').read_text())
    doc=dict(schema='cw_local_brush_components_v1',map_hash=world['map_hash'],models=rows,instances=[])
    (destination/'capture.json').write_text(json.dumps(doc,indent=2))
    (destination/'components.json').write_text(json.dumps(diagnostics,indent=2))
    return doc,diagnostics
