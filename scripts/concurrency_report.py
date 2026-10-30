"""Regenerate Phase 2 tables, paired uncertainty, correctness audit and figure.

Only reads immutable collections; does not regenerate Phase 1 analysis.
"""
import json
import re
from collections import defaultdict
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from experiment import ROOT
from concurrency_analyze import summarize, metrics, parse_log

OUT=ROOT/'phase2/analysis-final'
ARMS={'stock':'A: engine','fifo':'B: engine + FIFO','lru':'C: explicit LRU',
      'custom':'D: original custom','corrected':'E: concurrent fallback'}
COLORS={'stock':'#19745e','fifo':'#2671aa','lru':'#b97720','custom':'#c54646','corrected':'#7653a3'}

def activity(intervals):
    """Time-weighted active requests; simultaneous endpoints are grouped."""
    changes=defaultdict(int)
    for begin,end in intervals:
        assert end>=begin
        if end==begin:continue
        changes[begin]+=1;changes[end]-=1
    if not changes:return None
    count=0;area=0.;overlap=0.;peak=0;previous=min(changes)
    for at,delta in sorted(changes.items()):
        area+=count*(at-previous)
        if count>=2:overlap+=at-previous
        count+=delta;peak=max(peak,count);previous=at
    span=max(changes)-min(changes)
    return {'mean_active':area/span,'fraction_wall_time_with_two_or_more':overlap/span,'max_active':peak}

def load(cohort):
    runs=[]
    for marker in sorted((ROOT/'phase2'/cohort).rglob('complete.json')):
        folder=marker.parent
        signature=json.loads((folder/'input.json').read_text(encoding='utf-8'))
        records=[json.loads(s) for s in (folder/'requests.jsonl').read_text(encoding='utf-8').splitlines()]
        rows=records[1:]
        assert len(rows)==signature['options']['requests']+6
        assert len({r['request_id'] for r in rows})==len(rows)
        for row in rows:
            if row['success']:
                assert row['timings']['cache_n']+row['timings']['prompt_n']==row['input_tokens']
        rawmetrics=json.loads((folder/'metrics.json').read_text(encoding='utf-8'))
        before,after=[metrics(rawmetrics[k]['text']) for k in ['before','after']]
        for key,counter in [('prompt_n','llamacpp:prompt_tokens_total'),('cache_n','llamacpp:prompt_tokens_cached_total')]:
            observed=after[counter]-before[counter]
            if all(r['success'] for r in rows):
                assert observed==sum(r['timings'][key] for r in rows),(folder,counter)
        tasks,_=parse_log(folder/'server.log')
        engine=sorted([t for t in tasks.values() if 'launched_ms' in t and 'released_ms' in t],key=lambda t:t['launched_ms'])
        assert all(r['success'] for r in rows if r['phase']=='warmup')
        # Warmup is a completed six-request barrier before measured dispatch.
        engine=engine[6:]
        measured=[r for r in rows if r['phase']=='measured']
        overlap={'client_dispatch_to_eof_or_error':activity([(r['http_dispatch_us'],r['eof_us'] or r['done_us']) for r in measured if r['http_dispatch_us'] is not None]),
                 'engine_launch_to_release':activity([(t['launched_ms'],t['released_ms']) for t in engine]),
                 'scope':'measured-phase intervals; native task mapping not needed; active slots do not imply simultaneous GPU kernels'}
        runs.append({'source':str(folder.relative_to(ROOT)), 'signature':signature,
                     'arm':signature['arm'],'cache':signature['cache'],'trial':signature['trial'],
                     'rows':rows,'summary':summarize(rows),
                     'overlap':overlap,
                     'metrics_delta':{k:after[k]-before[k] for k in before if k in after}})
    return runs

def interval(values):
    """Resample independent paired trial seeds, never individual requests."""
    values=np.asarray(values,dtype=float)
    rng=np.random.default_rng(20261029)
    samples=np.median(values[rng.integers(0,len(values),size=(20000,len(values)))],axis=1)
    return np.quantile(samples,[.025,.975]).tolist()

def aggregate(runs,expected):
    groups=[]
    for cache in [8192,0]:
        for arm in expected:
            selected=[r for r in runs if r['cache']==cache and r['arm']==arm]
            assert sorted(r['trial'] for r in selected)==list(range(5)),(cache,arm)
            rows=[row for r in selected for row in r['rows']]
            medians=[r['summary']['median_ms'] for r in selected]
            groups.append({'arm':arm,'cache':cache,'trials':5,**summarize(rows),
                           'median_of_trial_medians_ms':float(np.median(medians)),
                           'trial_median_interval_ms':interval(medians),
                           'trial_medians_ms':medians,
                           'trial_p95_ms':[r['summary']['p95_ms'] for r in selected],
                           'warmup_failures':sum(not row['success'] for row in rows if row['phase']=='warmup'),
                           'measured_over_500ms':sum(row['success'] and row['ttft_ms']>500 for row in rows if row['phase']=='measured'),
                           'metrics_delta_by_trial':[r['metrics_delta'] for r in selected]})
    return groups

def paired(runs,left,right,cache):
    a={r['trial']:r for r in runs if r['arm']==left and r['cache']==cache}
    b={r['trial']:r for r in runs if r['arm']==right and r['cache']==cache}
    assert sorted(a)==sorted(b)==list(range(5))
    # Negative is faster for right; medians of paired percent changes.
    differences={}
    for metric in ['median_ms','p95_ms','mean_ms']:
        changes=[100*(b[i]['summary'][metric]/a[i]['summary'][metric]-1) for i in range(5)]
        differences[metric]={'paired_change_percent':float(np.median(changes)),
                             'exploratory_95_interval_percent':interval(changes),'trials':changes}
    # Pooled P95 is a different estimand from median paired trial-P95 change.
    # Preserve whole-trial dependence; cache the 126 possible bootstrap multisets.
    arrays=[]
    for collection in [a,b]:
        arrays.append([np.array([r['ttft_ms'] for r in collection[i]['rows'] if r['phase']=='measured' and r['success']]) for i in range(5)])
    rng=np.random.default_rng(20261029);memo={};changes=[]
    for indices in rng.integers(0,5,size=(20000,5)):
        key=tuple(sorted(indices))
        if key not in memo:
            q=[np.quantile(np.concatenate([values[i] for i in key]),.95) for values in arrays]
            memo[key]=100*(q[1]/q[0]-1)
        changes.append(memo[key])
    point=[np.quantile(np.concatenate(values),.95) for values in arrays]
    pooled={'change_percent':100*(point[1]/point[0]-1),'exploratory_paired_cluster_95_interval_percent':np.quantile(changes,[.025,.975]).tolist()}
    return {'left':left,'right':right,'cache':cache,'metrics':differences,'pooled_p95':pooled}

def correctness(runs):
    output=[]
    for cache in [8192,0]:
        byarm=defaultdict(dict)
        for run in runs:
            if run['cache']!=cache:continue
            for row in run['rows']:
                if row['phase']=='measured':byarm[run['arm']][(run['trial'],row['request_id'])]=row
        for arm,rows in byarm.items():
            baseline=byarm['fifo'];pairs=[(baseline[k],r) for k,r in rows.items() if baseline[k]['success'] and r['success']]
            mismatch=[{'trial':a['trial'],'request_id':a['request_id'],'baseline_output':a['output'],'output':b['output'],'baseline_tokens':a['output_tokens'],'tokens':b['output_tokens']} for a,b in pairs if a['output_tokens']!=b['output_tokens']]
            output.append({'cache':cache,'arm':arm,'attempts':len(rows),'failures':sum(not r['success'] for r in rows.values()),
                           'factual_passes':sum(r['success'] and r['probe_pass'] for r in rows.values()),
                           'wrong_conversation_codes':sum(r['success'] and r['another_known_code'] for r in rows.values()),
                           'compared_successful_pairs':len(pairs),'greedy_token_mismatches':mismatch})
    return output

def telemetry(runs):
    groups=defaultdict(list)
    errors=[]
    for run in runs:
        for line in (ROOT/run['source']/'telemetry.jsonl').read_text(encoding='utf-8').splitlines():
            sample=json.loads(line)
            if 'error' in sample:
                errors.append({'source':run['source'],**sample});continue
            values=[float(s.strip()) for s in sample['gpu_csv'].split(',')]
            groups[(run['arm'],run['cache'])].append({**dict(zip(['gpu_used_mib','gpu_free_mib','temperature_c','power_w','sm_mhz','memory_mhz','gpu_util_percent'],values)), 'process_rss_mib':sample['process_rss_bytes']/2**20,'available_ram_mib':sample['available_ram_bytes']/2**20})
    result=[]
    for (arm,cache),samples in groups.items():
        result.append({'arm':arm,'cache':cache,'samples':len(samples),'ranges':{key:[min(s[key] for s in samples),float(np.median([s[key] for s in samples])),max(s[key] for s in samples)] for key in samples[0]}})
    return {'scope':'one-second system-GPU/process-RSS samples include model loading, warmup and metrics; not per-request peaks or exclusive GPU attribution','groups':result,'errors':errors}

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    ablation=load('ablation-clean');validation=load('validation');probes=load('correctness')
    groups={'ablation':aggregate(ablation,['stock','fifo','lru','custom']),
            'validation':aggregate(validation,['fifo','custom','corrected'])}
    pairs={'ablation':[paired(ablation,a,b,c) for c in [8192,0] for a,b in [('stock','fifo'),('fifo','lru'),('lru','custom'),('fifo','custom')]],
           'validation':[paired(validation,a,b,c) for c in [8192,0] for a,b in [('fifo','custom'),('custom','corrected'),('fifo','corrected')]]}
    (OUT/'summary.json').write_text(json.dumps({'groups':groups,'paired':pairs,'correctness':correctness(probes)},indent=2),encoding='utf-8')
    (OUT/'telemetry.json').write_text(json.dumps(telemetry(ablation+validation),indent=2),encoding='utf-8')
    (OUT/'runs.json').write_text(json.dumps([{k:v for k,v in r.items() if k!='rows'} for r in ablation+validation+probes],indent=2),encoding='utf-8')
    lines=['# Generated Phase 2 tables','','Median = median of five trial medians. P95 = pooled successful requests. Each timing arm has 300 measured attempts. Failures remain in raw data and are excluded from latency quantiles.','']
    for cohort,rows in groups.items():
        lines.extend([f'## {cohort}','','| Host MiB | Arm | Median ms | P95 ms | Eval tokens | Reused tokens | Queue median µs | Schedule median µs | Failures |','|---:|---|---:|---:|---:|---:|---:|---:|---:|'])
        for r in rows:
            lines.append(f"| {r['cache']} | {ARMS[r['arm']]} | {r['median_of_trial_medians_ms']:.2f} | {r['p95_ms']:.2f} | {r['total_evaluated_tokens']} | {r['total_reused_tokens']} | {r['median_queue_us']:.2f} | {r['median_schedule_us']:.2f} | {r['failures']} |")
        lines.append('')
    (OUT/'tables.md').write_text('\n'.join(lines),encoding='utf-8')
    overlap_lines=['| Cohort | Host MiB | Arm | Client mean active | Engine mean active | Engine wall time ≥2 slots % | Native busy slots/decode | Native decode calls |',
                   '|---|---:|---|---:|---:|---:|---:|---:|']
    for cohort,runs in [('ablation',ablation),('validation',validation)]:
        for r in groups[cohort]:
            selected=[s for s in runs if s['arm']==r['arm'] and s['cache']==r['cache']]
            med=lambda f:float(np.median([f(s) for s in selected]))
            overlap_lines.append(f"| {cohort} | {r['cache']} | {ARMS[r['arm']]} | {med(lambda s:s['overlap']['client_dispatch_to_eof_or_error']['mean_active']):.3f} | {med(lambda s:s['overlap']['engine_launch_to_release']['mean_active']):.3f} | {100*med(lambda s:s['overlap']['engine_launch_to_release']['fraction_wall_time_with_two_or_more']):.1f} | {med(lambda s:s['metrics_delta']['llamacpp:n_busy_slots_per_decode']):.3f} | {med(lambda s:s['metrics_delta']['llamacpp:n_decode_total']):.0f} |")
    (OUT/'overlap.md').write_text('\n'.join(overlap_lines),encoding='utf-8')
    document=ROOT/'docs/concurrency-ablation.md'
    content=document.read_text(encoding='utf-8')
    tables='\n'.join(lines[4:]).replace('## ablation','### Clean ablation (seeds 42–46)').replace('## validation','### Fresh validation (seeds 142–146)')
    probe_lines=['| Host MiB | Arm | Attempts | Factual passes | Request failures | Other conversation codes | Token mismatches vs B |',
                 '|---:|---|---:|---:|---:|---:|---:|']
    probe_summary=correctness(probes)
    for r in sorted(probe_summary,key=lambda r:(-r['cache'],r['arm'])):
        probe_lines.append(f"| {r['cache']} | {ARMS[r['arm']]} | {r['attempts']} | {r['factual_passes']} | {r['failures']} | {r['wrong_conversation_codes']} | {len(r['greedy_token_mismatches'])} |")
    for name,value in [('TABLES',tables),('CORRECTNESS','\n'.join(probe_lines)),('OVERLAP','\n'.join(overlap_lines))]:
        begin,end=f'<!-- GENERATED_{name}_START -->',f'<!-- GENERATED_{name}_END -->'
        block=begin+'\n\n'+value+'\n\n'+end
        placeholder=f'<!-- GENERATED_{name} -->'
        if placeholder in content:content=content.replace(placeholder,block)
        else:
            content,count=re.subn(re.escape(begin)+r'.*?'+re.escape(end),lambda _:block,content,flags=re.S)
            assert count==1,(document,name)
    document.write_text(content,encoding='utf-8')
    plt.rcParams.update({'font.size':10,'axes.spines.top':False,'axes.spines.right':False})
    fig,axes=plt.subplots(2,2,figsize=(13,8),sharey=True)
    for row,cohort in enumerate(['ablation','validation']):
        for col,cache in enumerate([8192,0]):
            ax=axes[row,col];data=[r for r in groups[cohort] if r['cache']==cache]
            for x,r in enumerate(data):
                y=r['median_of_trial_medians_ms'];low,high=r['trial_median_interval_ms']
                ax.errorbar(x,y,yerr=[[y-low],[high-y]],fmt='o',color=COLORS[r['arm']],capsize=4,markersize=8,zorder=3)
                ax.scatter(x,r['p95_ms'],marker='^',facecolors='none',edgecolors=COLORS[r['arm']],s=75,zorder=3)
                ax.annotate(f'{y:.1f}',(x,y),xytext=(12,0) if y<100 else (0,-18),textcoords='offset points',ha='left' if y<100 else 'center',va='center',fontsize=9)
                ax.annotate(f"{r['p95_ms']:.1f}",(x,r['p95_ms']),xytext=(0,8),textcoords='offset points',ha='center',fontsize=9)
                ax.scatter(np.full(5,x)+np.linspace(-.1,.1,5),r['trial_medians_ms'],s=10,color=COLORS[r['arm']],alpha=.4)
            ax.set_xticks(range(len(data)),[ARMS[r['arm']].replace(': ','\n') for r in data])
            ax.set_title(f"{'Ablation: seeds 42–46' if row==0 else 'Fresh validation: seeds 142–146'} · host cache {cache:,} MiB",fontsize=11)
            ax.grid(axis='y',alpha=.2);ax.set_ylim(0,720);ax.set_xlim(-.5,len(data)-.5)
            if col==0:ax.set_ylabel('Time to first visible output (ms)')
    fig.suptitle('Concurrent slot routing: ablation and fresh fallback validation',fontsize=15,y=.98)
    fig.text(.5,.035,'● Median of trial medians, with exploratory trial-seed bootstrap 95% interval   △ Pooled P95\nTwo clients · skewed 2,048 tokens · 8 output tokens · 5 × 60 requests per arm · same fixed GPU configuration',ha='center',fontsize=10)
    fig.tight_layout(rect=[0,.085,1,.95])
    target=ROOT/'analysis/concurrency-before-after.png';fig.savefig(target,dpi=180);plt.close(fig)
    print('\n'.join(lines))
    print('Paired comparisons:',json.dumps(pairs,indent=2))
    print('Correctness:',json.dumps(correctness(probes),indent=2))

if __name__=='__main__':main()
