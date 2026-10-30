"""Immutable fixed-arrival experiments. Reuses the pinned server lifecycle."""
import argparse
import datetime
import hashlib
import json
import subprocess
from experiment import ROOT,server,api
from concurrency_experiment import metrics

BIN=ROOT/'target/release/phase3.exe'
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def prepare(args):
    folder=ROOT/args.workloads
    if folder.exists():raise RuntimeError('Preparation already exists; preserve it')
    # Twenty independent sequences, generated using the pinned original CLI.
    if (ROOT/args.prepare_out).exists():raise RuntimeError('Preparation log already exists')
    with server(ROOT/args.prepare_out,8192):
        for trial in range(20):
            dest=folder/f'seed-{args.seed_start+trial}'
            subprocess.run([str(ROOT/'target/release/loci-cache-lab.exe'),'prepare','--out',str(dest),'--seed',str(args.seed_start+trial),'--requests','60'],cwd=ROOT,check=True,stdout=subprocess.DEVNULL)
            raw=json.loads((dest/'skewed-2048.json').read_text(encoding='utf-8'))
            requests=raw['requests']
            for phase in ['warmup','measured']:
                for i,r in enumerate(q for q in requests if q['phase']==phase):
                    r['arrival_ms']=(i//2)*600+(i%2)*10
            raw['schema_version']=3
            (dest/'arrivals.json').write_text(json.dumps(raw),encoding='utf-8')
    print('Prepared 20 fixed-arrival seeded fixtures',flush=True)

def collect(args):
    arms=['fifo','corrected']
    for trial in range(args.trial_start,args.trial_start+args.trials):
        source=ROOT/args.workloads/f'seed-{args.seed_start+trial}/arrivals.json'
        fixture=json.loads(source.read_text(encoding='utf-8'))
        assert 0<args.requests<=sum(r['phase']=='measured' for r in fixture['requests'])
        for phase in ['warmup','measured']:
            fixture['requests']=[r for r in fixture['requests'] if r['phase']!=phase]+[r for r in fixture['requests'] if r['phase']==phase][:6 if phase=='warmup' else args.requests]
        for cache in [8192,0]:
            for arm in arms[trial%2:]+arms[:trial%2]:
                name=f't{trial:02}-{arm}-ram{cache}-v{args.verbosity}'
                folder=ROOT/args.out/name
                signature={'suite':'tail','trial':trial,'arm':arm,'cache':cache,'binary_sha256':sha(BIN),'fixture_sha256':sha(source),'options':vars(args).copy()}
                if (folder/'complete.json').exists():
                    previous=json.loads((folder/'input.json').read_text(encoding='utf-8'))
                    # Cohort extension changes only the outer loop bounds.
                    for value in [previous,signature]:
                        for key in ['trial_start','trials']:value['options'].pop(key,None)
                        for key,default in [('workloads','phase3/workloads'),('prepare_out','phase3/preparation'),('seed_start',242)]:
                            if value['options'].get(key,default)==default:value['options'].pop(key,None)
                    assert previous==signature,folder
                    continue
                if folder.exists():raise RuntimeError(f'Incomplete attempt preserved: {folder}; choose another output')
                folder.mkdir(parents=True)
                (folder/'input.json').write_text(json.dumps(signature,indent=2),encoding='utf-8')
                (folder/'workload.json').write_text(json.dumps(fixture),encoding='utf-8')
                with server(folder,cache,extra_args=['-lv',str(args.verbosity),'--batch-size','2048']):
                    before=metrics()
                    (folder/'ready-gpu.csv').write_text(subprocess.check_output(['nvidia-smi','--query-gpu=memory.used,memory.free,temperature.gpu,power.draw,clocks.sm','--format=csv'],text=True),encoding='utf-8')
                    subprocess.run([str(BIN),'--workload',str(folder/'workload.json'),'--out',str(folder/'requests.jsonl'),'--arm',arm,'--trial',str(trial),'--host-cache-mib',str(cache)],cwd=ROOT,check=True)
                    after=metrics()
                    (folder/'metrics.json').write_text(json.dumps({'before':before,'after':after}),encoding='utf-8')
                records=[json.loads(s) for s in (folder/'requests.jsonl').read_text(encoding='utf-8').splitlines()[1:]]
                assert len(records)==args.requests+6
                assert len({r['request_id'] for r in records})==len(records)
                (folder/'complete.json').write_text(json.dumps({'attempts':len(records),'failures':sum(not r['success'] for r in records),'utc':datetime.datetime.now(datetime.timezone.utc).isoformat()}),encoding='utf-8')
                print('COMPLETE',name,flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--prepare',action='store_true')
    parser.add_argument('--trials',type=int,default=10)
    parser.add_argument('--trial-start',type=int,default=0)
    parser.add_argument('--requests',type=int,default=60)
    parser.add_argument('--verbosity',type=int,default=3)
    parser.add_argument('--out',default='phase3/tail')
    parser.add_argument('--workloads',default='phase3/workloads')
    parser.add_argument('--prepare-out',default='phase3/preparation')
    parser.add_argument('--seed-start',type=int,default=242)
    args=parser.parse_args()
    if args.prepare:prepare(args)
    else:collect(args)
