"""Trial-cluster inference for the fixed-arrival experiment; no prior files edited."""
import argparse
import json
from collections import defaultdict
import numpy as np
from experiment import ROOT
from concurrency_analyze import metrics,parse_log,correlate
from concurrency_report import activity

METRICS=['scheduled_ttft_ms','ttft_ms','http_ttft_ms','queue_ms','arrival_lateness_ms']
def quantiles(values):
    a=np.asarray(values,dtype=float)
    return dict(zip(['median','p95','p99'],map(float,np.quantile(a,[.5,.95,.99])))) if len(a) else None

def summary(rows):
    warmup_failures=sum(not r['success'] for r in rows if r['phase']=='warmup')
    rows=[r for r in rows if r['phase']=='measured'];good=[r for r in rows if r['success']]
    return {'attempts':len(rows),'successes':len(good),'failures':len(rows)-len(good),'warmup_failures':warmup_failures,
        'latency':{k:quantiles([r[k] for r in good]) for k in METRICS},
        'exceedance_success_fraction':{str(t):float(np.mean([r['ttft_ms']>t for r in good])) for t in [100,300,500]},
        'exceedance_attempt_bounds':{str(t):[sum(r['ttft_ms']>t for r in good)/len(rows),(sum(r['ttft_ms']>t for r in good)+len(rows)-len(good))/len(rows)] for t in [100,300,500]},
        'evaluated_tokens':sum(r['timings']['prompt_n'] for r in good),
        'reused_tokens':sum(r['timings']['cache_n'] for r in good),
        'factual_passes':sum(r['probe_pass'] for r in good),
        'client_overlap':activity([(r['http_dispatch_us'],r['eof_us'] or r['done_us']) for r in rows if r['http_dispatch_us'] is not None])}

def load(source):
    runs=[]
    for marker in sorted((ROOT/source).rglob('complete.json')):
        folder=marker.parent
        sig=json.loads((folder/'input.json').read_text(encoding='utf-8'))
        records=[json.loads(s) for s in (folder/'requests.jsonl').read_text(encoding='utf-8').splitlines()]
        config=records[0]['config'];rows=records[1:]
        fixture=json.loads((folder/'workload.json').read_text(encoding='utf-8'))
        assert len(rows)==len(fixture['requests']) and len({r['request_id'] for r in rows})==len(rows)
        for r in rows:
            body=json.loads(r['wire_body'])
            assert body['id_slot']==-1 and body['cache_prompt'] is True
            if r['success']:assert r['timings']['prompt_n']+r['timings']['cache_n']==r['input_tokens']
        raw=json.loads((folder/'metrics.json').read_text(encoding='utf-8'))
        before,after=[metrics(raw[k]['text']) for k in ['before','after']]
        if all(r['success'] for r in rows):
            for key,name in [('prompt_n','prompt_tokens_total'),('cache_n','prompt_tokens_cached_total')]:
                assert sum(r['timings'][key] for r in rows)==after['llamacpp:'+name]-before['llamacpp:'+name],(folder,key)
        tasks,declines=parse_log(folder/'server.log')
        joined,errors=correlate(rows,tasks) if sig['options']['verbosity']>=5 else ([],[])
        evidence=None
        if joined:
            measured=[r for r in joined if r['phase']=='measured']
            evidence={'matched':len(joined),'engine_post_to_launch_ms':quantiles([r['engine_queue_prepare_ms'] for r in measured]),
                'engine_post_to_first_token_ms':quantiles([r['engine_post_to_first_token_ms'] for r in measured]),
                'completion_decode_gate_events':sum(e['kind']=='decode_gate' and e['id_task'] in {r['engine']['task_id'] for r in joined} for e in declines),
                'slot_unavailable_events':sum(e['kind']=='slot_unavailable' for e in declines),'validated_requests':measured}
        intervals=sorted([t for t in tasks.values() if 'launched_ms' in t and 'released_ms' in t],key=lambda t:t['launched_ms'])[6:]
        warmup_failed=any(not r['success'] for r in rows if r['phase']=='warmup')
        runs.append({'source':str(folder.relative_to(ROOT)),'trial':sig['trial'],'arm':sig['arm'],'cache':sig['cache'],
            'signature':sig,'rows':rows,'fixture':fixture,'summary':summary(rows),
            'metrics_after':after,'engine_overlap':None if warmup_failed else activity([(t['launched_ms'],t['released_ms']) for t in intervals]),
            'engine_evidence':evidence,'correlation_errors':errors})
    return runs

def paired_bootstrap(a,b,resamples=10000):
    """Resample whole paired trials; requests within a trial stay dependent."""
    assert sorted(a)==sorted(b)
    trials=sorted(a);rng=np.random.default_rng(20261030)
    indices=rng.integers(0,len(trials),size=(resamples,len(trials)))
    result={}
    for metric in METRICS:
        arrays=[]
        for arm in [a,b]:
            arrays.append(np.array([[r[metric] if r['success'] else np.nan for r in sorted(arm[t],key=lambda r:r['request_id']) if r['phase']=='measured'] for t in trials]))
        observed=[np.nanquantile(values,[.5,.95,.99]) for values in arrays]
        draws=[]
        for values in arrays:
            chunks=[]
            for offset in range(0,resamples,500):
                matrix=values[indices[offset:offset+500]].reshape(-1,values.shape[0]*values.shape[1])
                chunks.append(np.nanquantile(matrix,[.5,.95,.99],axis=1).T)
            draws.append(np.concatenate(chunks))
        result[metric]={}
        for i,q in enumerate(['median','p95','p99']):
            delta=draws[1][:,i]-draws[0][:,i]
            ratio=100*(draws[1][:,i]/np.maximum(draws[0][:,i],1e-9)-1)
            result[metric][q]={'fifo_ms':float(observed[0][i]),'corrected_ms':float(observed[1][i]),
                'delta_ms':float(observed[1][i]-observed[0][i]),'delta_95_ms':np.quantile(delta,[.025,.975]).tolist(),
                'change_percent':float(100*(observed[1][i]/max(observed[0][i],1e-9)-1)),'change_95_percent':np.quantile(ratio,[.025,.975]).tolist()}
    for threshold in [100,300,500]:
        counts=[]
        for arm in [a,b]:
            counts.append(np.array([[sum(r['success'] and r['ttft_ms']>threshold for r in arm[t] if r['phase']=='measured'),sum(r['success'] for r in arm[t] if r['phase']=='measured')] for t in trials]))
        rates=[v[indices].sum(axis=1) for v in counts]
        diffs=100*(rates[1][:,0]/rates[1][:,1]-rates[0][:,0]/rates[0][:,1])
        result[f'over_{threshold}ms']={'delta_percentage_points':float(100*(counts[1][:,0].sum()/counts[1][:,1].sum()-counts[0][:,0].sum()/counts[0][:,1].sum())),
            'delta_95_percentage_points':np.quantile(diffs,[.025,.975]).tolist()}
    return result

def analyze(runs,resamples):
    result={'runs':[{k:v for k,v in r.items() if k not in ['rows','fixture','engine_evidence']} for r in runs],
            'groups':[],'paired':[],'wire_equivalence':[]}
    for cache in sorted({r['cache'] for r in runs},reverse=True):
        paired={arm:{r['trial']:r for r in runs if r['cache']==cache and r['arm']==arm} for arm in ['fifo','corrected']}
        assert sorted(paired['fifo'])==sorted(paired['corrected'])
        for trial in sorted(paired['fifo']):
            a,b=[paired[arm][trial] for arm in ['fifo','corrected']]
            assert a['fixture']==b['fixture']
            wa={r['request_id']:r['wire_body'] for r in a['rows']};wb={r['request_id']:r['wire_body'] for r in b['rows']}
            assert wa==wb
            la,lb=[json.loads((ROOT/r['source']/'launch.json').read_text(encoding='utf-8')) for r in [a,b]]
            assert la['args']==lb['args']
            result['wire_equivalence'].append({'trial':trial,'cache':cache,'requests':len(wa),'identical_bodies_and_arrivals_and_server_args':True})
        for arm in ['fifo','corrected']:
            selected=list(paired[arm].values());rows=[q for r in selected for q in r['rows']]
            result['groups'].append({'cache':cache,'arm':arm,'trials':len(selected),**summary(rows)})
        result['paired'].append({'cache':cache,'trials':len(paired['fifo']),
            'comparison':'corrected minus fifo; paired whole-trial percentile bootstrap; success-conditional latency',
            'metrics':paired_bootstrap({t:r['rows'] for t,r in paired['fifo'].items()},{t:r['rows'] for t,r in paired['corrected'].items()},resamples)})
        clean=[t for t in paired['fifo'] if all(r['success'] for arm in ['fifo','corrected'] for r in paired[arm][t]['rows'] if r['phase']=='warmup')]
        if len(clean)!=len(paired['fifo']):
            result['paired'][-1]['warmup_failure_sensitivity']={'included_trials':clean,'excluded_trials':sorted(set(paired['fifo'])-set(clean)),
                'scope':'post-hoc sensitivity excluding the whole affected pair; original all-trial comparison remains primary',
                'metrics':paired_bootstrap({t:paired['fifo'][t]['rows'] for t in clean},{t:paired['corrected'][t]['rows'] for t in clean},resamples)}
        complete=[t for t in paired['fifo'] if all(r['success'] for arm in ['fifo','corrected'] for r in paired[arm][t]['rows'])]
        if len(complete)!=len(paired['fifo']):
            result['paired'][-1]['failure_free_sensitivity']={'included_trials':complete,'excluded_trials':sorted(set(paired['fifo'])-set(complete)),
                'scope':'post-hoc whole-pair exclusion of any request failure; all-trial results remain primary',
                'metrics':paired_bootstrap({t:paired['fifo'][t]['rows'] for t in complete},{t:paired['corrected'][t]['rows'] for t in complete},resamples)}
    return result

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--source',default='phase3/tail');parser.add_argument('--out',default='phase3/analysis');parser.add_argument('--resamples',type=int,default=10000)
    args=parser.parse_args();runs=load(args.source);result=analyze(runs,args.resamples)
    out=ROOT/args.out;out.mkdir(parents=True,exist_ok=True)
    (out/'summary.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    evidence=[{'source':r['source'],'evidence':r['engine_evidence'],'errors':r['correlation_errors']} for r in runs if r['engine_evidence'] or r['correlation_errors']]
    (out/'engine-evidence.json').write_text(json.dumps(evidence),encoding='utf-8')
    for group in result['groups']:
        print(group['cache'],group['arm'],group['trials'],group['latency']['ttft_ms'],'failures',group['failures'],'queue',group['latency']['queue_ms'])
    expand=False
    for pair in result['paired']:
        p95=pair['metrics']['ttft_ms']['p95'];p99=pair['metrics']['ttft_ms']['p99']
        wide=(np.ptp(p95['change_95_percent'])>20 or np.ptp(p99['change_95_percent'])>30)
        expand=expand or wide
        print('PAIRED',pair['cache'],'P95',p95,'P99',p99,'wide',bool(wide))
    (out/'sample-decision.json').write_text(json.dumps({'expand_if_below_20_trials':bool(expand),'criterion':'P95 ratio CI width >20 percentage points or P99 >30','trials':sorted({r['trial'] for r in runs})}),encoding='utf-8')

if __name__=='__main__':main()
