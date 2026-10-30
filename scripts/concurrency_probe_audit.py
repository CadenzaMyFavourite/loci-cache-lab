"""Investigate factual/greedy disagreements using zero-reuse native controls.

This is correctness evidence only, never a headline latency collection.
"""
import concurrent.futures
import hashlib
import json
from experiment import ROOT,server,api

def main():
    folder=ROOT/'phase2/probe-audit'
    if folder.exists():raise RuntimeError('Preserve the prior probe audit')
    summary=json.loads((ROOT/'phase2/analysis-final/summary.json').read_text(encoding='utf-8'))
    selected={(m['trial'],m['request_id']) for r in summary['correctness'] for m in r['greedy_token_mismatches']}
    for path in (ROOT/'phase2/correctness').rglob('requests.jsonl'):
        for row in map(json.loads,path.read_text(encoding='utf-8').splitlines()[1:]):
            if row['phase']=='measured' and not row['probe_pass']:selected.add((row['trial'],row['request_id']))
    selected.add((0,6))
    fixtures={i:json.loads((ROOT/f'phase2/workloads/seed-{142+i}/skewed-2048.json').read_text(encoding='utf-8')) for i in range(2)}
    cases=[];seen=set()
    for trial,identity in sorted(selected):
        request=next(r for r in fixtures[trial]['requests'] if r['id']==identity)
        key=hashlib.sha256(json.dumps(request['tokens']).encode()).hexdigest()
        if key in seen:continue
        seen.add(key);cases.append({'fixture_seed':142+trial,**request,'prompt_sha256':key})
    folder.mkdir(parents=True)
    (folder/'input.json').write_text(json.dumps({'purpose':'mismatch investigation; not timing evidence','sampling':{'n_predict':32,'temperature':0,'seed':42,'ignore_eos':False},'cases':cases},indent=2),encoding='utf-8')
    allrows=[]
    for concurrency in [1,2]:
        with server(folder/f'uncached-c{concurrency}',0,extra_args=['-lv','3','--batch-size','2048']):
            def one(job):
                repeat,case=job
                response=api('/completion',{'prompt':case['tokens'],'stream':False,'cache_prompt':False,'id_slot':-1,'n_predict':32,'temperature':0,'seed':42,'ignore_eos':False,'return_tokens':True})
                assert response['timings']['cache_n']==0
                assert response['timings']['prompt_n']==len(case['tokens'])
                return {'schema_version':1,'concurrency':concurrency,'repeat':repeat,'fixture_seed':case['fixture_seed'],'request_id':case['id'],'prompt_sha256':case['prompt_sha256'],'expected':case['expected'],'probe_pass':case['expected'] in response['content'],'response':response}
            jobs=[(repeat,case) for repeat in range(2) for case in cases]
            with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
                rows=list(executor.map(one,jobs))
            allrows.extend(rows)
            # Inspect the exact synthetic prompt around both the system and final turn.
            if concurrency==1:
                texts=[]
                for case in cases:
                    content=api('/detokenize',{'tokens':case['tokens']})['content']
                    texts.append({'prompt_sha256':case['prompt_sha256'],'request_id':case['id'],'head':content[:400],'tail':content[-600:]})
                (folder/'prompt-inspection.json').write_text(json.dumps(texts,indent=2),encoding='utf-8')
    (folder/'results.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in allrows),encoding='utf-8')
    (folder/'audit-complete.json').write_text(json.dumps({'unique_prompts':len(cases),'attempts':len(allrows),'factual_passes':sum(r['probe_pass'] for r in allrows),'all_evaluated':True}),encoding='utf-8')
    print(json.dumps({'unique_prompts':len(cases),'attempts':len(allrows),'factual_passes':sum(r['probe_pass'] for r in allrows)}))
    for r in allrows:
        print(r['concurrency'],r['repeat'],r['request_id'],r['expected'],repr(r['response']['content']))

if __name__=='__main__':main()
