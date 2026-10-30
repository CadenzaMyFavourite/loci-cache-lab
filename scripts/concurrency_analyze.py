"""Phase 2 analysis: client clocks and validated per-slot engine-log correlation."""
import argparse
from collections import defaultdict
import json
import pathlib
import re
import statistics
import numpy as np
from experiment import ROOT

STAMP=re.compile(r"^(\d+)\.(\d+)\.(\d+)\.(\d+) ")
TASK=re.compile(r"id\s+(\d+)\s*\| task\s+(\d+)\s*\|")

def parse_log(path):
    tasks={}
    deferred=[]
    selected={}
    for line in path.read_text(encoding="utf-8",errors="replace").splitlines():
        match=STAMP.match(line)
        if not match:continue
        a,b,c,d=map(int,match.groups())
        t=(a*60+b)*1000+c+d/1000
        post=re.search(r"post: new task, id = (\d+)/1",line)
        if post:tasks.setdefault(int(post[1]),{})["posted_ms"]=t
        if "defer task" in line:
            identity=re.search(r"id_task = (\d+)",line)
            deferred.append({"kind":"slot_unavailable","at_ms":t,"id_task":int(identity[1]) if identity else None,"line":line})
        if "decoding, decline task" in line:
            identity=re.search(r"id_task = (\d+)",line)
            deferred.append({"kind":"decode_gate","at_ms":t,"id_task":int(identity[1]) if identity else None,"line":line})
        selection=re.search(r"id\s+(\d+)\s*\| task -1 \| selected slot",line)
        if selection:selected[int(selection[1])]=t
        match=TASK.search(line)
        if not match:continue
        slot,identity=map(int,match.groups())
        item=tasks.setdefault(identity,{})
        if "processing task, is_child" in line:
            item.update(slot=slot,launched_ms=t)
            if slot in selected:item['selected_ms']=selected.pop(slot)
        if "process_toke" in line and "next token:" in line:
            token=re.search(r"next token:\s+(\d+)",line)
            item.setdefault("token_ids",[]).append(int(token[1]))
            item.setdefault("first_token_ms",t)
            item["last_token_ms"]=t
        if "prompt eval time" in line:
            prompt=re.search(r"=\s*([\d.]+) ms /\s*(\d+) tokens",line)
            item.update(prompt_ms=float(prompt[1]),evaluated=int(prompt[2]))
        if "stop processing: n_tokens" in line:item["released_ms"]=t
    return tasks,deferred

def correlate(rows,tasks):
    output=[]
    # Headers signal engine START. Validate the otherwise-inferred per-slot map
    # against exact generated tokens and evaluated-token counts, not just counts.
    errors=[]
    for slot in [0,1]:
        client=sorted([r for r in rows if r["success"] and r["actual_slot"]==slot],key=lambda r:r["headers_us"])
        engine=sorted([(tid,t) for tid,t in tasks.items() if t.get("slot")==slot and "released_ms" in t],key=lambda pair:pair[1]["launched_ms"])
        if len(client)!=len(engine):
            errors.append({"slot":slot,"client_count":len(client),"engine_count":len(engine)});continue
        for r,(tid,t) in zip(client,engine):
            if t.get("evaluated")!=r["timings"]["prompt_n"] or t.get("token_ids")!=r["output_tokens"]:
                errors.append({"slot":slot,"request":r["request_id"],"task":tid,"reason":"token or eval-count mismatch"});continue
            output.append({**r,"engine":{**t,"task_id":tid},"engine_queue_prepare_ms":t["launched_ms"]-t["posted_ms"],"engine_post_to_first_token_ms":t["first_token_ms"]-t["posted_ms"]})
    if errors:
        # Partial/ambiguous matching cannot support exact request-level claims.
        return [],errors
    return output,[]

def metrics(text):
    values={}
    for line in text.splitlines():
        if not line or line.startswith("#"):continue
        key,value=line.rsplit(" ",1)
        try:values[key]=float(value)
        except ValueError:pass
    return values

def summarize(rows):
    measured=[r for r in rows if r["phase"]=="measured"]
    good=[r for r in measured if r["success"]]
    if not good:raise RuntimeError("No successful observations")
    values=[r["ttft_ms"] for r in good]
    warm=[r for r in good if r["timings"]["cache_n"]>=1000]
    med=lambda values:float(np.median(values)) if values else None
    return {"attempts":len(measured),"successes":len(good),"failures":len(measured)-len(good),"median_ms":med(values),"mean_ms":float(np.mean(values)),"p95_ms":float(np.quantile(values,.95)),"median_queue_us":1000*med([r['queue_ms'] for r in good]),"max_queue_us":max(r['queue_ms'] for r in good)*1000,"median_schedule_us":med([r['schedule_us'] for r in good]),"median_headers_ms":med([(r['headers_us']-r['http_dispatch_us'])/1000 for r in good]),"median_headers_to_content_ms":med([(r['first_content_us']-r['headers_us'])/1000 for r in good]),"median_terminal_to_eof_us":med([r['eof_us']-r['terminal_us'] for r in good]),"total_evaluated_tokens":sum(r['timings']['prompt_n'] for r in good),"total_reused_tokens":sum(r['timings']['cache_n'] for r in good),"warm_requests":len(warm),"warm_slow_over_100ms":sum(r['ttft_ms']>100 for r in warm),"warm_own_prompt_over_100ms":sum(r['timings']['prompt_ms']>100 for r in warm),"warm_headers_over_100ms":sum((r['headers_us']-r['http_dispatch_us'])>100000 for r in warm),"factual_passes":sum(r['probe_pass'] for r in good),"wrong_conversation_codes":sum(r['another_known_code'] for r in good)}

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--source",default="phase2")
    parser.add_argument("--out",default="phase2/analysis")
    args=parser.parse_args()
    output=ROOT/args.out;output.mkdir(parents=True,exist_ok=True)
    runs=[];correlations=[]
    pooled=defaultdict(list)
    for complete in sorted((ROOT/args.source).rglob("complete.json")):
        folder=complete.parent
        if not (folder/"input.json").exists():continue
        records=[json.loads(line) for line in (folder/"requests.jsonl").read_text(encoding="utf-8").splitlines()]
        meta,rows=records[0],records[1:]
        signature=json.loads((folder/"input.json").read_text(encoding='utf-8'))
        config=meta["config"]
        tasks,deferred=parse_log(folder/"server.log")
        joined,errors=correlate(rows,tasks) if signature['options']['verbosity']>=5 else ([],[])
        observed=metrics(json.loads((folder/"metrics.json").read_text(encoding='utf-8'))["after"]["text"])
        result={"source":str(folder.relative_to(ROOT)),"suite":signature['options']['suite'],"arm":config['arm'],"cache":config['host_cache_mib'],"trial":config['trial'],"transport":config['transport'],"verbosity":signature['options']['verbosity'],"snapshots":config['snapshots'],"progress":config['progress'],"release_delay_ms":config['release_delay_ms'],**summarize(rows),"logged_defer_events":len(deferred) if signature['options']['verbosity']>=5 else None,"matched_requests":len(joined),"correlation_errors":errors,"metrics_after":observed}
        result['batch_size']=signature['options'].get('batch_size',2048)
        if joined:
            measures=[r for r in joined if r['phase']=='measured']
            result['median_engine_queue_prepare_ms']=float(np.median([r['engine_queue_prepare_ms'] for r in measures]))
            result['logged_slot_unavailable_events']=sum(e['kind']=='slot_unavailable' for e in deferred)
            result['logged_decode_gate_events']=sum(e['kind']=='decode_gate' for e in deferred)
            result['completion_decode_gate_events']=sum(e['kind']=='decode_gate' and e['id_task'] in {r['engine']['task_id'] for r in joined} for e in deferred)
            result['median_engine_post_to_first_token_ms']=float(np.median([r['engine_post_to_first_token_ms'] for r in measures]))
            # Exact simultaneous first-token/prefill relation on engine clock.
            cold=[t for t in tasks.values() if t.get('evaluated',0)>1000 and 'first_token_ms' in t]
            for r in measures:
                t=r['engine']
                r['cold_prefill_overlap']=any(other.get('slot')!=t['slot'] and other['launched_ms']<t['first_token_ms'] and other['first_token_ms']>t['posted_ms'] for other in cold)
                r['decode_gate_events']=sum(e['kind']=='decode_gate' and e['id_task']==t['task_id'] for e in deferred)
            result['warm_slow_with_cold_overlap']=sum(r['ttft_ms']>100 and r['timings']['cache_n']>=1000 and r['cold_prefill_overlap'] for r in measures)
            # Feasible constant clock offset: dispatch <= server POST; engine launch <= headers.
            lower=max(r['http_dispatch_us']/1000-r['engine']['posted_ms'] for r in joined)
            upper=min(r['headers_us']/1000-r['engine']['launched_ms'] for r in joined)
            result['clock_offset_feasible_ms']=[lower,upper] if lower<=upper else None
            result['median_transport_residual_ms']=float(np.median([r['http_ttft_ms']-r['engine_post_to_first_token_ms'] for r in measures]))
            result['p95_transport_residual_ms']=float(np.quantile([r['http_ttft_ms']-r['engine_post_to_first_token_ms'] for r in measures],.95))
            if lower<=upper:
                gaps=[];stale_visibility=0
                for r in measures:
                    released=next((e['at_us']/1000 for e in r['events'] if e['event']=='slot_released'),None)
                    if released is not None:
                        gaps.append(released-r['engine']['released_ms']-(lower+upper)/2)
                    reserved=next((e['at_us']/1000 for e in r['events'] if e['event']=='slot_reserved'),None)
                    if reserved is not None:
                        for other in joined:
                            if other['request_id']==r['request_id']:continue
                            other_start=next((e['at_us']/1000 for e in other['events'] if e['event']=='slot_reserved'),None)
                            other_end=next((e['at_us']/1000 for e in other['events'] if e['event']=='slot_released'),None)
                            if other_start is not None and other_end is not None and other_start<=reserved<other_end and other['engine']['released_ms']+upper<reserved:
                                stale_visibility+=1
                result['median_client_lease_past_engine_release_ms']=float(np.median(gaps)) if gaps else None
                result['p95_client_lease_past_engine_release_ms']=float(np.quantile(gaps,.95)) if gaps else None
                result['reservations_excluding_already_idle_engine_slot']=stale_visibility
            # At actual engine selection, did explicit routing exclude an idle,
            # longer prefix? This is a counterfactual routing opportunity, not
            # a prediction of the alternate request's latency. Only KV-only
            # runs avoid ambiguity from host-cache restoration changing slots.
            if result['cache']==0:
                fixture=json.loads((ROOT/signature['fixture']).read_text(encoding='utf-8'))
                inputs={r['id']:r['tokens'] for r in fixture['requests']}
                def prefix(a,b):
                    return next((i for i,(x,y) in enumerate(zip(a,b)) if x!=y),min(len(a),len(b)))
                missed=[]
                for r in measures:
                    t=r['engine'];selection=t.get('selected_ms')
                    if selection is None or r['decision'] is None:continue
                    other_slot=1-t['slot']
                    previous=[a for a in joined if a['engine']['slot']==other_slot and a['engine']['launched_ms']<selection]
                    if not previous:continue
                    previous=max(previous,key=lambda a:a['engine']['launched_ms'])
                    if previous['engine']['released_ms']>=selection:continue
                    known=inputs[previous['request_id']]+previous['output_tokens'][:-1]
                    lcp=prefix(known,inputs[r['request_id']])
                    if lcp>r['timings']['cache_n']+1000:
                        reserved=next(e['at_us']/1000 for e in r['events'] if e['event']=='slot_reserved')
                        missed.append({'request_id':r['request_id'],'engine_task':t['task_id'],'other_slot':other_slot,'actual_reused':r['timings']['cache_n'],'alternate_prefix':lcp,'other_released_ms':previous['engine']['released_ms'],'selected_ms':selection,'other_definitely_became_idle_after_reservation':lower<=upper and previous['engine']['released_ms']+lower>reserved})
                result['missed_idle_prefix_opportunities']=missed
            correlations.append({"source":result['source'],"correlation":"inferred per-slot order, validated against exact token IDs and evaluation counters","clock_offset_feasible_ms":result['clock_offset_feasible_ms'],"requests":measures,"deferred":deferred})
        for r in rows:
            if r['success']:
                assert r['timings']['cache_n']+r['timings']['prompt_n']==r['input_tokens']
        runs.append(result)
        key=(result['suite'],result['arm'],result['cache'],result['transport'],result['verbosity'],result['release_delay_ms'],result['snapshots'],result['progress'],result['batch_size'])
        pooled[key].extend(r for r in rows if r['phase']=='measured')
    groups=[dict(zip(['suite','arm','cache','transport','verbosity','release_delay_ms','snapshots','progress','batch_size'],key),**summarize(rows)) for key,rows in pooled.items()]
    (output/'runs.json').write_text(json.dumps(runs,indent=2),encoding='utf-8')
    (output/'groups.json').write_text(json.dumps(groups,indent=2),encoding='utf-8')
    with (output/'correlated.jsonl').open('w',encoding='utf-8') as destination:
        for item in correlations:destination.write(json.dumps(item)+'\n')
    print(f"Analyzed {len(runs)} complete Phase 2 arms, {sum(r['attempts'] for r in runs)} measured attempts")
    print(json.dumps([{k:r.get(k) for k in ['suite','arm','cache','trial','median_ms','p95_ms','median_queue_us','median_headers_ms','median_headers_to_content_ms','logged_defer_events','warm_slow_over_100ms','warm_slow_with_cold_overlap','correlation_errors']} for r in runs],indent=2))

if __name__=='__main__':main()
