"""Create held-out seeded fixtures without touching original workload files."""
import subprocess
import argparse
from experiment import ROOT,server

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--out',default='phase2/workloads')
    parser.add_argument('--log',default='phase2/heldout-preparation')
    args=parser.parse_args()
    if (ROOT/args.log).exists() or any((ROOT/args.out/f'seed-{seed}').exists() for seed in range(142,147)):
        raise RuntimeError('Held-out artifacts already exist; use the saved fixtures or choose fresh --out and --log paths')
    with server(ROOT/args.log,8192):
        for seed in range(142,147):
            subprocess.run([str(ROOT/'phase2/baseline/loci-cache-lab-phase1.exe'),'prepare','--out',f'{args.out}/seed-{seed}','--seed',str(seed),'--requests','60'],cwd=ROOT,check=True)
