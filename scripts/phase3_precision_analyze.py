"""Saved precision measurements, allocations, token comparisons and numeric probes."""
import argparse
import json
from collections import defaultdict
import numpy as np
from experiment import ROOT
from concurrency_analyze import metrics

def load(source):
    runs=[]
    for marker in sorted((ROOT/source).rglob('complete.json')):
        folder=marker.parent;sig=json.loads((folder/'input.json').read_text(encoding='utf-8'))
        records=[json.loads(s) for s in (folder/'requests.jsonl').read_text(encoding='utf-8').splitlines()]
        rows=records[1:];assert len(rows)==8 and len({r['request_id'] for r in rows})==8
        good=[r for r in rows if r['phase']=='measured' and r['success']]
        if not good:raise RuntimeError(f'No successful measured responses in {folder}; raw failures preserved')
        for r in rows:
            if r['success']:
                assert r['input_tokens']==r['timings']['cache_n']+r['timings']['prompt_n']
                if sig['suite']=='precision':
                    assert r['timings']['predicted_n']==sig['predict'] and len(r['output_tokens'])==sig['predict'],(folder,r['request_id'])
        raw=json.loads((folder/'metrics.json').read_text(encoding='utf-8'));before,after=[metrics(raw[k]['text']) for k in ['before','after']]
        if all(r['success'] for r in rows):
            for key,name in [('prompt_n','prompt_tokens_total'),('cache_n','prompt_tokens_cached_total')]:
                assert sum(r['timings'][key] for r in rows)==after['llamacpp:'+name]-before['llamacpp:'+name]
        samples=[];sample_times=[]
        for line in (folder/'telemetry.jsonl').read_text(encoding='utf-8').splitlines():
            sample=json.loads(line)
            if 'gpu_csv' in sample:
                samples.append([float(x.strip()) for x in sample['gpu_csv'].split(',')]);sample_times.append(sample['unix_ms'])
        a=np.asarray(samples)
        origin_ms=records[0]['clock']['origin_unix_ns']/1e6
        begin=origin_ms+min(r['http_dispatch_us'] for r in rows if r['phase']=='measured')/1000
        end=origin_ms+max(r['eof_us'] or r['done_us'] for r in rows if r['phase']=='measured')/1000
        active=a[(np.asarray(sample_times)>=begin)&(np.asarray(sample_times)<=end)]
        ready=(folder/'ready-gpu.csv').read_text(encoding='utf-8').splitlines()[1].split(',')[0].split()[0]
        stats={'attempts':6,'successes':len(good),'failures':6-len(good),
            'median_ttft_ms':float(np.median([r['ttft_ms'] for r in good])),
            'median_http_ttft_ms':float(np.median([r['http_ttft_ms'] for r in good])),
            'median_decode_tps':float(np.median([r['timings']['predicted_per_second'] for r in good])),
            'median_prefill_ms':float(np.median([r['timings']['prompt_ms'] for r in good])),
            'median_decode_ms':float(np.median([r['timings']['predicted_ms'] for r in good])),
            'end_to_end_output_tps':sum(len(r['output_tokens']) for r in good)/((max(r['eof_us'] or r['done_us'] for r in rows if r['phase']=='measured')-min(r['http_dispatch_us'] for r in rows if r['phase']=='measured'))/1e6),
            'evaluated_tokens':sum(r['timings']['prompt_n'] for r in good),'reused_tokens':sum(r['timings']['cache_n'] for r in good),
            'factual_passes':sum(r['probe_pass'] for r in good),'exact_code_outputs':sum(r['probe_exact'] for r in good),'other_known_codes':sum(r['another_known_code'] for r in good),
            'ready_system_gpu_mib':float(ready),'sampled_peak_system_gpu_mib':float(active[:,0].max()) if len(active) else None,
            'timing_window_memory_samples':len(active),'lifetime_sampled_peak_system_gpu_mib':float(a[:,0].max()),
            'temperature_range_c':[float(a[:,2].min()),float(a[:,2].max())],
            'power_range_w':[float(a[:,3].min()),float(a[:,3].max())],
            'sm_clock_range_mhz':[float(a[:,4].min()),float(a[:,4].max())],
            'native_busy_slots_per_decode_including_warmup':after['llamacpp:n_busy_slots_per_decode'],
            'native_decode_calls_including_warmup':after['llamacpp:n_decode_total']-before['llamacpp:n_decode_total']}
        probe=json.loads((folder/'numeric-probe.json').read_text(encoding='utf-8'))
        assert probe['response']['timings']['cache_n']==0
        runs.append({'source':str(folder.relative_to(ROOT)),'signature':sig,'rows':rows,'summary':stats,'numeric_probe':probe['response']})
    return runs

def paired_interval(values):
    a=np.asarray(values);rng=np.random.default_rng(20261031)
    draws=np.median(a[rng.integers(0,len(a),size=(10000,len(a)))],axis=1)
    return {'paired_median_change_percent':float(np.median(a)),'exploratory_trial_bootstrap_95_percent':np.quantile(draws,[.025,.975]).tolist(),'trials':a.tolist()}

def analyze(runs):
    groups=defaultdict(list)
    for r in runs:
        s=r['signature'];groups[(s['context'],s['input_tokens'],s['predict'],s['arm'],s['kv'])].append(r)
    aggregated=[];pairs=[]
    for key,selected in sorted(groups.items()):
        assert sorted(r['signature']['trial'] for r in selected)==list(range(5)),key
        allrows=[r for run in selected for r in run['rows'] if r['phase']=='measured']
        def available_median(key):
            values=[r['summary'][key] for r in selected if r['summary'][key] is not None]
            return float(np.median(values)) if values else None
        fields={k:available_median(k) for k in ['median_ttft_ms','median_decode_tps','median_prefill_ms','median_decode_ms','end_to_end_output_tps','ready_system_gpu_mib','sampled_peak_system_gpu_mib']}
        aggregated.append({'context':key[0],'input_tokens':key[1],'predict':key[2],'arm':key[3],'kv':key[4],'trials':5,'attempts':len(allrows),'failures':sum(not r['success'] for r in allrows),'factual_passes':sum(r['success'] and r['probe_pass'] for r in allrows),
            'evaluated_tokens':sum(r['timings']['prompt_n'] for r in allrows if r['success']),
            'reused_tokens':sum(r['timings']['cache_n'] for r in allrows if r['success']),**fields})
    configs=sorted({key[:4] for key in groups})
    for config in configs:
        a={r['signature']['trial']:r for r in groups[config+('f16',)]};b={r['signature']['trial']:r for r in groups[config+('q8_0',)]}
        comparisons={}
        for metric in ['median_ttft_ms','median_decode_tps','median_prefill_ms','median_decode_ms','end_to_end_output_tps']:
            comparisons[metric]=paired_interval([100*(b[t]['summary'][metric]/a[t]['summary'][metric]-1) for t in range(5)])
        mismatches=[];logprobs=[]
        for trial in range(5):
            left={r['request_id']:r for r in a[trial]['rows'] if r['phase']=='measured'}
            for r in b[trial]['rows']:
                if r['phase']!='measured':continue
                other=left[r['request_id']]
                assert other['wire_body']==r['wire_body']
                if r['success'] and other['success'] and r['output_tokens']!=other['output_tokens']:
                    mismatches.append({'trial':trial,'request_id':r['request_id'],'f16_output':other['output'],'q8_output':r['output'],'f16_probe_pass':other['probe_pass'],'q8_probe_pass':r['probe_pass']})
            pa,pb=[run[trial]['numeric_probe']['completion_probabilities'][0] for run in [a,b]]
            topa,topb=[{v['id']:v['logprob'] for v in p['top_logprobs']} for p in [pa,pb]]
            shared=set(topa)&set(topb)
            logprobs.append({'trial':trial,'first_token_f16':pa['id'],'first_token_q8':pb['id'],'shared_top_eight_candidates':len(shared),
                'max_abs_logprob_delta_shared':max(abs(topa[k]-topb[k]) for k in shared),
                'mean_abs_logprob_delta_shared':float(np.mean([abs(topa[k]-topb[k]) for k in shared]))})
        pairs.append({'context':config[0],'input_tokens':config[1],'predict':config[2],'arm':config[3],
            'comparison':'q8_0 versus f16; five paired trial seeds','metrics':comparisons,'greedy_token_mismatches':mismatches,'cold_first_token_logprob_comparisons':logprobs})
    # Same-precision label controls characterize baseline output variation too.
    label_controls=[]
    for config in sorted({key[:3]+(key[4],) for key in groups}):
        context,size,predict,kv=config
        a={r['signature']['trial']:r for r in groups[(context,size,predict,'fifo',kv)]};b={r['signature']['trial']:r for r in groups[(context,size,predict,'corrected',kv)]}
        compared=0;mismatches=0
        for trial in range(5):
            left={r['request_id']:r for r in a[trial]['rows'] if r['phase']=='measured'}
            for r in b[trial]['rows']:
                if r['phase']=='measured' and r['success'] and left[r['request_id']]['success']:
                    compared+=1;mismatches+=r['output_tokens']!=left[r['request_id']]['output_tokens']
        label_controls.append({'context':context,'input_tokens':size,'predict':predict,'kv':kv,'compared':compared,'token_mismatches':mismatches})
    return {'groups':aggregated,'paired_precision':pairs,'same_precision_label_controls':label_controls,'runs':[{k:v for k,v in r.items() if k!='rows'} for r in runs]}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--source',default='phase3/precision');p.add_argument('--out',default='phase3/precision-analysis');args=p.parse_args()
    runs=load(args.source);result=analyze(runs);out=ROOT/args.out;out.mkdir(parents=True,exist_ok=True)
    (out/'summary.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print('Analyzed',len(runs),'precision arms')
    for g in result['groups']:print(g)
