"""Repeated selected precision cases, after the primary tail investigation."""
import argparse
import datetime
import hashlib
import json
import random
import re
import subprocess
from experiment import ROOT,server,api
from concurrency_experiment import metrics

CASES=[(9216,2048,32),(9216,4096,128),(16384,2048,128),(16384,4096,32)]
BIN=ROOT/'target/release/precision.exe'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def prepare(args):
    folder=ROOT/args.workloads
    if folder.exists():raise RuntimeError('Preserve existing precision fixtures')
    if (ROOT/args.prepare_out).exists():raise RuntimeError('Preserve precision preparation log')
    with server(ROOT/args.prepare_out,8192):
        props=api('/props');scope=json.dumps({'model':props['model_path'],'template':props['chat_template']},sort_keys=True,separators=(',',':'),ensure_ascii=False)
        folder.mkdir()
        for trial in range(5):
            rng=random.Random(342+trial)
            measured=['A','A','B','C','A','B'];rng.shuffle(measured)
            for size in [2048,4096]:
                requests=[]
                for i,conversation in enumerate(['A','B']+measured):
                    code=f'{conversation}-{731+ord(conversation)}'
                    history=(f'Conversation {conversation} discusses a private garden, its soil, water, seasons, paths, trees, and observations. ')*700
                    rendered=api('/apply-template',{'messages':[
                        {'role':'system','content':f"Conversation {conversation}. Your secret code is {code}. When asked, reply with only that exact secret code. Never use another conversation's code."},
                        {'role':'user','content':history},
                        {'role':'assistant','content':f'I have read the notes. The exact secret code is {code}.'},
                        {'role':'user','content':f'Turn {i:03}. What is your secret code?'}],'add_generation_prompt':True})['prompt']
                    full=api('/tokenize',{'content':rendered,'add_special':True,'parse_special':True})['tokens']
                    tokens=full[:size-128]+full[-128:];assert len(tokens)==size
                    requests.append({'id':i,'conversation':conversation,'tokens':tokens,'expected':code,'phase':'warmup' if i<2 else 'measured','arrival_ms':i*10})
                (folder/f't{trial}-input{size}.json').write_text(json.dumps({'schema_version':3,'scope':scope,'seed':342+trial,'requests':requests}),encoding='utf-8')

def allocations(args):
    for context in [9216,16384]:
        for kv in ['f16','q8_0']:
            folder=ROOT/args.allocations/f'{kv}-ctx{context}'
            if folder.exists():raise RuntimeError('Preserve allocation calibration')
            with server(folder,8192,kv,context,extra_args=['-lv','5','--batch-size','2048']):
                (folder/'ready-gpu.csv').write_text(subprocess.check_output(['nvidia-smi','--query-gpu=memory.used,memory.free,temperature.gpu,power.draw,clocks.sm','--format=csv'],text=True),encoding='utf-8')
                slots=api('/slots')
            text=(folder/'server.log').read_text(encoding='utf-8')
            values={}
            for kind in ['KV','model','compute']:
                matches=re.findall(r'CUDA\d+ '+kind+r' buffer size =\s*([\d.]+) MiB',text)
                assert matches,(folder,kind)
                values[kind+'_mib']=sum(map(float,matches))
            (folder/'allocation.json').write_text(json.dumps({'context':context,'kv':kv,'slots':slots,'native_gpu_buffers':values,'scope':'exact sizes printed by backend, not total process VRAM or request peak'},indent=2),encoding='utf-8')
            print('ALLOCATION',context,kv,values,flush=True)

def collect(args):
    cases=CASES if not args.correctness else [(16384,4096,32)]
    for trial in range(args.trials):
        for context,size,predict in cases:
            fixture=ROOT/args.workloads/f't{trial}-input{size}.json'
            arms=[(kv,arm) for kv in ['f16','q8_0'] for arm in ['fifo','corrected']]
            arms=arms[trial%4:]+arms[:trial%4]
            for kv,arm in arms:
                folder=ROOT/args.out/f't{trial}-{arm}-{kv}-ctx{context}-in{size}-out{predict}'
                signature={'suite':'precision-correctness' if args.correctness else 'precision','trial':trial,'arm':arm,'kv':kv,'context':context,'input_tokens':size,'predict':predict,'host_cache_mib':8192,'fixture_sha256':sha(fixture),'binary_sha256':sha(BIN),'options':vars(args).copy()}
                if (folder/'complete.json').exists():
                    assert json.loads((folder/'input.json').read_text(encoding='utf-8'))==signature,folder
                    continue
                if folder.exists():raise RuntimeError(f'Incomplete attempt preserved at {folder}')
                folder.mkdir(parents=True)
                (folder/'input.json').write_text(json.dumps(signature,indent=2),encoding='utf-8')
                with server(folder,8192,kv,context,extra_args=['-lv','3','--batch-size','2048']):
                    before=metrics()
                    (folder/'ready-gpu.csv').write_text(subprocess.check_output(['nvidia-smi','--query-gpu=memory.used,memory.free,temperature.gpu,power.draw,clocks.sm','--format=csv'],text=True),encoding='utf-8')
                    command=[str(BIN),'--workload',str(fixture),'--out',str(folder/'requests.jsonl'),'--arm',arm,'--trial',str(trial),'--host-cache-mib','8192','--kv',kv,'--context',str(context),'--predict',str(predict)]
                    if args.correctness:command.append('--correctness')
                    subprocess.run(command,cwd=ROOT,check=True)
                    (folder/'metrics.json').write_text(json.dumps({'before':before,'after':metrics()}),encoding='utf-8')
                    # Outside timing and after metric capture: compare native
                    # pre-sampling top-eight log probabilities on a cold prompt.
                    probe_prompt=json.loads(fixture.read_text(encoding='utf-8'))['requests'][2]['tokens']
                    probe_body={'prompt':probe_prompt,'cache_prompt':False,'id_slot':-1,'n_predict':1,
                        'temperature':0,'seed':42,'return_tokens':True,'n_probs':8,'post_sampling_probs':False}
                    probe=api('/completion',probe_body)
                    assert probe['timings']['cache_n']==0 and probe['timings']['prompt_n']==size
                    (folder/'numeric-probe.json').write_text(json.dumps({'request':probe_body,'response':probe}),encoding='utf-8')
                rows=[json.loads(s) for s in (folder/'requests.jsonl').read_text(encoding='utf-8').splitlines()[1:]]
                assert len(rows)==8
                (folder/'complete.json').write_text(json.dumps({'attempts':len(rows),'failures':sum(not r['success'] for r in rows),'completed_utc':datetime.datetime.now(datetime.timezone.utc).isoformat()}),encoding='utf-8')
                print('COMPLETE',folder.name,flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--prepare',action='store_true');p.add_argument('--allocate',action='store_true');p.add_argument('--trials',type=int,default=5);p.add_argument('--correctness',action='store_true');p.add_argument('--out',default='phase3/precision');p.add_argument('--workloads',default='phase3/precision-workloads');p.add_argument('--prepare-out',default='phase3/precision-preparation');p.add_argument('--allocations',default='phase3/allocations');args=p.parse_args()
    if args.prepare:prepare(args)
    elif args.allocate:allocations(args)
    else:collect(args)
