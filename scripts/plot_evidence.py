"""Regenerate a small figure from portable measured evidence, without a GPU."""
import argparse
import json
import pathlib
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT=pathlib.Path(__file__).resolve().parents[1]
def main():
    p=argparse.ArgumentParser();p.add_argument('--out',default='runs/evidence-example.png');a=p.parse_args()
    groups={arm:[] for arm in ['fifo','lru','custom']}
    for line in (ROOT/'evidence/requests.jsonl').open(encoding='utf-8'):
        r=json.loads(line)
        if r['stage']=='phase2-ablation' and r['cache_mib']==0 and r['phase']=='measured' and r['success'] and r['arm'] in groups:groups[r['arm']].append(r['ttft_ms'])
    if any(len(v)!=300 for v in groups.values()):raise RuntimeError('Expected five × 60 retained observations per arm')
    fig,ax=plt.subplots(figsize=(8,4.5))
    for i,(arm,v) in enumerate(groups.items()):
        ax.scatter(i,np.median(v),s=70,color=['#2671aa','#b97720','#c54646'][i],label='Pooled median' if i==0 else None)
        ax.scatter(i,np.quantile(v,.95),s=65,marker='^',color='#555',label='Pooled P95' if i==0 else None)
    ax.set_xticks([0,1,2],['Stock + FIFO','Explicit prefix/LRU','Original custom']);ax.set_ylabel('TTFT (ms)');ax.set_ylim(bottom=0);ax.grid(axis='y',alpha=.2);ax.legend()
    ax.set_title('Retained Phase 2 ablation: host cache disabled')
    fig.text(.5,.01,'5 paired trials × 60 measured requests per arm. Pooled median differs from the median of trial medians.',ha='center',fontsize=9)
    fig.tight_layout(rect=[0,.04,1,1]);out=ROOT/a.out;out.parent.mkdir(parents=True,exist_ok=True);fig.savefig(out,dpi=150);plt.close(fig)
    print(out)
if __name__=='__main__':main()
