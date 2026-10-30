"""Summarize sampled hardware and observed batch/overlap counters."""
import json
from collections import defaultdict
import numpy as np
from experiment import ROOT

if __name__=='__main__':
    result={'scope':'one-second samples over each server lifetime, including startup/warmup; system GPU, not process-exclusive; ranges can miss peaks','runs':[],'groups':[]}
    grouped=defaultdict(list)
    summary=json.loads((ROOT/'phase3/analysis/summary.json').read_text(encoding='utf-8'))
    for run in summary['runs']:
        folder=ROOT/run['source'];samples=[];errors=[]
        for line in (folder/'telemetry.jsonl').read_text(encoding='utf-8').splitlines():
            sample=json.loads(line)
            if 'gpu_csv' not in sample:errors.append(sample);continue
            samples.append([float(v.strip()) for v in sample['gpu_csv'].split(',')])
        matrix=np.asarray(samples)
        fields=['gpu_used_mib','gpu_free_mib','temperature_c','power_w','sm_mhz','memory_mhz','gpu_util_percent']
        ranges={name:[float(matrix[:,i].min()),float(np.median(matrix[:,i])),float(matrix[:,i].max())] for i,name in enumerate(fields)}
        result['runs'].append({'source':run['source'],'cache':run['cache'],'arm':run['arm'],'trial':run['trial'],'samples':len(samples),'ranges':ranges,'sampling_errors':errors,
            'client_overlap':run['summary']['client_overlap'],'engine_overlap':run['engine_overlap'],
            'native_busy_slots_per_decode_all_phases':run['metrics_after']['llamacpp:n_busy_slots_per_decode'],
            'native_decode_calls_all_phases':run['metrics_after']['llamacpp:n_decode_total']})
        grouped[(run['cache'],run['arm'])].extend(samples)
    for (cache,arm),samples in grouped.items():
        a=np.asarray(samples)
        selected=[r for r in result['runs'] if r['cache']==cache and r['arm']==arm]
        result['groups'].append({'cache':cache,'arm':arm,'samples':len(samples),'ranges':{name:[float(a[:,i].min()),float(np.median(a[:,i])),float(a[:,i].max())] for i,name in enumerate(fields)},
            'median_engine_mean_active':float(np.median([r['engine_overlap']['mean_active'] for r in selected if r['engine_overlap'] is not None])),
            'median_engine_two_slot_wall_fraction':float(np.median([r['engine_overlap']['fraction_wall_time_with_two_or_more'] for r in selected if r['engine_overlap'] is not None])),
            'median_native_busy_slots_per_decode':float(np.median([r['native_busy_slots_per_decode_all_phases'] for r in selected]))})
    (ROOT/'phase3/analysis/hardware.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print('Summarized hardware and overlap for',len(result['runs']),'arms')
