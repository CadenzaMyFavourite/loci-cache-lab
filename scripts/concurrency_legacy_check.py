"""Replay the frozen Phase 1 client under normal server logging; never write Phase 1 data."""
import json
import subprocess
import argparse
from experiment import ROOT, server

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--out',default='phase2/legacy-check')
    args=parser.parse_args()
    exe=ROOT/'phase2/baseline/loci-cache-lab-phase1.exe'
    for cache in [8192,0]:
        for mode in ['stock','custom']:
            folder=ROOT/f'{args.out}/{mode}-ram{cache}'
            if folder.exists():raise RuntimeError('Preserve previous legacy check; use a new destination')
            with server(folder,cache):
                command=[str(exe),'run','--workload',str(ROOT/'workloads/seed-42/skewed-2048.json'),'--mode',mode,'--out',str(folder/'requests.jsonl'),'--trial','0','--concurrency','2','--predict','8','--host-cache-mib',str(cache)]
                result=subprocess.run(command,cwd=ROOT)
            records=[json.loads(line) for line in (folder/'requests.jsonl').read_text(encoding='utf-8').splitlines()[1:]]
            assert len(records)==66
            (folder/'complete.json').write_text(json.dumps({'exit_code':result.returncode,'attempts':len(records),'failures':sum(not r['success'] for r in records)}))
    print('Frozen Phase 1 replay complete')

if __name__=='__main__':main()
