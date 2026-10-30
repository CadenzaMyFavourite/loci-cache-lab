"""Create portable review evidence without editing a historical measurement."""
import hashlib
import json
import pathlib
import re

ROOT=pathlib.Path(__file__).resolve().parents[1]
def sha(path):
    with path.open('rb') as source:return hashlib.file_digest(source,'sha256').hexdigest()

def portable(value):
    if isinstance(value,dict):return {k:portable(v) for k,v in value.items()}
    if isinstance(value,list):return [portable(v) for v in value]
    if not isinstance(value,str):return value
    # Some scopes and HTTP errors contain a JSON string inside a JSON string.
    try:
        nested=json.loads(value)
        if isinstance(nested,(dict,list)):return json.dumps(portable(nested),separators=(',',':'),ensure_ascii=False)
    except (ValueError,TypeError):pass
    for form in [str(ROOT),str(ROOT).replace('\\','/'),str(ROOT).replace('\\','\\\\')]:value=value.replace(form,'<WORKSPACE>')
    value=re.sub(r'(?i)[A-Z]:[\\/]+Users[\\/]+[^\\/\s"<>]+', '<USER_HOME>',value)
    return value

def demo_copy(out):
    """Expose the small release smoke run when available; never launch a model."""
    source=ROOT/'runs/phase4-mini-demo'
    if not (source/'summary.json').exists():return
    selected=[source/'summary.json',source/'identity.json',source/'preparation/launch.json']
    for arm in ['stock','custom','corrected']:
        selected.extend([source/arm/'launch.json',source/arm/'requests.jsonl'])
    lineage=[]
    for path in selected:
        target=out/'demo'/path.relative_to(source);target.parent.mkdir(parents=True,exist_ok=True)
        if path.suffix=='.jsonl':
            rows=[portable(json.loads(line)) for line in path.read_text(encoding='utf-8').splitlines()]
            target.write_text(''.join(json.dumps(row,separators=(',',':'))+'\n' for row in rows),encoding='utf-8')
        else:target.write_text(json.dumps(portable(json.loads(path.read_text(encoding='utf-8'))),indent=2),encoding='utf-8')
        lineage.append({'source':str(path.relative_to(ROOT)).replace('\\','/'),'original_sha256':sha(path),
            'review_path':str(target.relative_to(out)).replace('\\','/'),'review_sha256':sha(target)})
    (out/'demo/provenance.json').write_text(json.dumps(lineage,indent=2),encoding='utf-8')

def main():
    out=ROOT/'evidence';out.mkdir(exist_ok=True)
    sources={
        'phase1-summary.json':'analysis/summary.json',
        'phase2-summary.json':'phase2/analysis-final/summary.json',
        'phase3-tail-summary.json':'phase3/analysis/summary.json',
        'phase3-precision-summary.json':'phase3/precision-analysis/summary.json',
        'phase3-correctness-summary.json':'phase3/precision-correctness-analysis/summary.json',
        'phase3-hardware.json':'phase3/analysis/hardware.json'}
    provenance={};counts={}
    for name,source in sources.items():
        p=ROOT/source
        (out/name).write_text(json.dumps(portable(json.loads(p.read_text(encoding='utf-8'))),indent=2),encoding='utf-8')
        provenance[name]={'original':source,'original_sha256':sha(p),'review_copy_sha256':sha(out/name),'transformation':'only machine-specific location strings normalized'}
    cohorts=[('phase1',ROOT/'results','full-*'),('phase2-ablation',ROOT/'phase2/ablation-clean','*'),
        ('phase2-validation',ROOT/'phase2/validation','*'),('phase2-correctness',ROOT/'phase2/correctness','*'),
        ('phase3-tail',ROOT/'phase3/tail','*'),('phase3-precision',ROOT/'phase3/precision','*'),('phase3-correctness',ROOT/'phase3/precision-correctness','*')]
    lineage=[];configurations=[]
    with (out/'requests.jsonl').open('w',encoding='utf-8') as destination:
        for stage,folder,pattern in cohorts:
            counts[stage]={'arms':0,'measured':0,'warmup':0,'measured_failures':0,'warmup_failures':0}
            for arm in sorted(folder.glob(pattern)):
                path=arm/'requests.jsonl'
                if not path.exists() or not (arm/'complete.json').exists():continue
                records=[json.loads(s) for s in path.read_text(encoding='utf-8').splitlines()]
                meta=records[0];config=meta['config'];counts[stage]['arms']+=1
                source=str(path.relative_to(ROOT)).replace('\\','/')
                lineage.append({'source':source,'sha256':sha(path)})
                configurations.append({'stage':stage,'source':source,'header':portable(meta)})
                for r in records[1:]:
                    phase=r['phase'];counts[stage][phase]+=1
                    if not r['success']:counts[stage][phase+'_failures']+=1
                    timing=r.get('timings') or (r.get('server_final') or {}).get('timings')
                    record={'stage':stage,'source':source,'schema_version':r['schema_version'],'trial':r.get('trial',config.get('trial')),
                        'arm':r.get('arm',r.get('mode',config.get('arm',config.get('mode')))),
                        'cache_mib':r.get('host_cache_mib',config.get('host_cache_mib')),'kv':r.get('kv',config.get('kv','f16')),
                        'context':r.get('context',config.get('context',12288)),
                        'request_id':r['request_id'],'phase':phase,'conversation':r['conversation'],'input_tokens':r['input_tokens'],
                        'success':r['success'],'error':r.get('error'),'ttft_ms':r.get('ttft_ms'),'http_ttft_ms':r.get('http_ttft_ms'),
                        'queue_ms':r.get('queue_ms'),'timings':timing,'output_tokens':r.get('output_tokens',[]),
                        'probe_pass':r.get('probe_pass'),'another_known_code':r.get('another_known_code'),
                        'decision':r.get('decision')}
                    for key in ['created_us','planned_us','admitted_us','http_dispatch_us','headers_us','first_content_us','eof_us','done_us','arrival_lateness_ms','scheduled_ttft_ms']:
                        if key in r:record[key]=r[key]
                    destination.write(json.dumps(portable(record),separators=(',',':'))+'\n')
    trace_source=ROOT/'phase2/analysis-verbose/correlated.jsonl'
    for line in trace_source.open(encoding='utf-8'):
        group=json.loads(line)
        if group['source'].replace('\\','/').endswith('ablation-t0-custom-ram0-v5-default-delay0'):
            selected=[r for r in group['requests'] if r['request_id'] in [10,11]]
            break
    trace={'source':'phase2/analysis-verbose/correlated.jsonl','source_sha256':sha(trace_source),
        'correlation':group['correlation'],'clock_offset_feasible_ms':group['clock_offset_feasible_ms'],
        'alternate_slot':1,'alternate_prefix_tokens':2034,'alternate_released_engine_ms':3156.191,
        'limitation':'Reconstructed routing opportunity, not a prediction of alternate-run latency. Verbose diagnostics are separate from headline timing.',
        'requests':[{k:r[k] for k in ['request_id','conversation','input_tokens','ttft_ms','http_ttft_ms','timings','engine','engine_queue_prepare_ms','output_tokens']} for r in selected]}
    (out/'early-binding.json').write_text(json.dumps(trace,indent=2),encoding='utf-8')
    allocations=[json.loads(p.read_text(encoding='utf-8')) for p in sorted((ROOT/'phase3/allocations').rglob('allocation.json'))]
    (out/'allocations.json').write_text(json.dumps(allocations,indent=2),encoding='utf-8')
    (out/'configurations.json').write_text(json.dumps(configurations,indent=2),encoding='utf-8')
    (out/'index.json').write_text(json.dumps({'schema_version':1,'purpose':'Portable review copies; historical originals remain unchanged',
        'configurations':'configurations.json',
        'normalization':'Machine locations become <WORKSPACE> or <USER_HOME>; request measurements and failures are retained',
        'cohorts':counts,'summaries':provenance,'request_sources':lineage},indent=2),encoding='utf-8')
    demo_copy(out)
    print(json.dumps(counts,indent=2))

if __name__=='__main__':main()
