"""Generate only Phase 3 tables and charts from retained complete measurements."""
import json
import argparse
from collections import defaultdict
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from experiment import ROOT

COLORS={'fifo':'#2671aa','corrected':'#7653a3'}
LABELS={'fifo':'Stock FIFO','corrected':'Corrected'}
TAIL=ROOT/'phase3/analysis'
PRECISION=ROOT/'phase3/precision-analysis'
ALLOCATIONS=ROOT/'phase3/allocations'
CHARTS=ROOT/'analysis'

def tail():
    summary=json.loads((TAIL/'summary.json').read_text(encoding='utf-8'))
    rows=defaultdict(list)
    for run in summary['runs']:
        folder=ROOT/run['source']
        records=[json.loads(s) for s in (folder/'requests.jsonl').read_text(encoding='utf-8').splitlines()[1:]]
        rows[(run['cache'],run['arm'])].extend(r for r in records if r['phase']=='measured' and r['success'])
    lines=['# Phase 3 generated tail tables','','All latency percentiles pool successful measured requests. Queue is actual ready→admission; HTTP is dispatch→first content. Rates condition on success. Trials, failures and exact estimands remain in summary.json.','',
        '| Host MiB | Route | Trials | Attempts | Failures | Median TTFT ms | P95 ms | P99 ms | HTTP P95 ms | Queue P95 ms | >100 ms % | >300 ms % | >500 ms % | Evaluated | Reused |',
        '|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for g in summary['groups']:
        q=g['latency'];rates=g['exceedance_success_fraction']
        lines.append(f"| {g['cache']} | {LABELS[g['arm']]} | {g['trials']} | {g['attempts']} | {g['failures']} | {q['ttft_ms']['median']:.2f} | {q['ttft_ms']['p95']:.2f} | {q['ttft_ms']['p99']:.2f} | {q['http_ttft_ms']['p95']:.2f} | {q['queue_ms']['p95']:.2f} | {rates['100']*100:.2f} | {rates['300']*100:.2f} | {rates['500']*100:.2f} | {g['evaluated_tokens']} | {g['reused_tokens']} |")
    lines+=['','| Host MiB | P95 change % (95% trial-cluster interval) | P99 change % (95% interval) | >500 ms change percentage points (95% interval) |','|---:|---|---|---|']
    for p in summary['paired']:
        def value(metric,quantile):
            r=p['metrics'][metric][quantile];lo,hi=r['change_95_percent']
            return f"{r['change_percent']:+.2f} [{lo:+.2f}, {hi:+.2f}]"
        r=p['metrics']['over_500ms'];lo,hi=r['delta_95_percentage_points']
        lines.append(f"| {p['cache']} | {value('ttft_ms','p95')} | {value('ttft_ms','p99')} | {r['delta_percentage_points']:+.2f} [{lo:+.2f}, {hi:+.2f}] |")
    (TAIL/'tables.md').write_text('\n'.join(lines),encoding='utf-8')
    plt.rcParams.update({'font.size':10,'axes.spines.top':False,'axes.spines.right':False})
    fig,axes=plt.subplots(2,2,figsize=(12,8),sharey=True,sharex=True)
    for col,cache in enumerate([8192,0]):
        for row,metric in enumerate(['ttft_ms','http_ttft_ms']):
            ax=axes[row,col]
            for arm in ['fifo','corrected']:
                a=np.sort([r[metric] for r in rows[(cache,arm)]])
                survival=(len(a)-np.arange(len(a)))/len(a)
                ax.step(a,survival,where='post',color=COLORS[arm],label=LABELS[arm],linestyle='-' if arm=='fifo' else '--')
            for y,label in [(.05,'P95 tail'),(.01,'P99 tail')]:
                ax.axhline(y,color='#aaa',lw=.7);ax.text(.98,y,label,transform=ax.get_yaxis_transform(),ha='right',va='bottom',color='#555',fontsize=9)
            ax.set_yscale('log');ax.set_ylim(.0006,1.05);ax.grid(alpha=.15)
            ax.set_title(f"Host cache {cache:,} MiB · {'ready → first content' if row==0 else 'dispatch → first content'}")
            ax.set_xlabel('Latency (ms)')
            if col==0:ax.set_ylabel('Fraction at or above latency (log scale)')
            if row==0 and col==0:ax.legend(loc='lower left')
    n=summary['groups'][0]['trials'];count=summary['groups'][0]['attempts']
    fig.suptitle('Fixed offered arrivals: request and HTTP tail distributions',fontsize=15)
    fig.text(.5,.015,f'{n} paired trials · {count:,} attempts per route/cache · 2 live HTTP streams · 8 output tokens\nReady TTFT includes client queueing; HTTP TTFT excludes it. Success-conditional curves; failures remain in tables.',ha='center',fontsize=9)
    fig.tight_layout(rect=[0,.06,1,.95]);fig.savefig(CHARTS/'phase3-tail-distributions.png',dpi=180);plt.close(fig)
    fig,axes=plt.subplots(1,2,figsize=(12,5.4),sharey=True)
    for ax,cache in zip(axes,[8192,0]):
        a={r['trial']:r for r in summary['runs'] if r['arm']=='fifo' and r['cache']==cache}
        b={r['trial']:r for r in summary['runs'] if r['arm']=='corrected' and r['cache']==cache}
        trials=sorted(a)
        differences=[b[t]['summary']['latency']['ttft_ms']['p95']-a[t]['summary']['latency']['ttft_ms']['p95'] for t in trials]
        ax.scatter(np.array(trials)+1,differences,color=COLORS['corrected'],s=30)
        ax.axhline(0,color='#777',lw=1);ax.set_title(f'Host cache {cache:,} MiB')
        ax.set_xlabel('Paired trial (one independent seeded request sequence)');ax.grid(axis='y',alpha=.2)
        ax.set_xticks([t for t in [1,5,10,15,20] if t<=max(trials)+1])
        pair=next(p for p in summary['paired'] if p['cache']==cache)['metrics']['ttft_ms']['p95']
        lo,hi=pair['delta_95_ms']
        fig.text(.27 if cache==8192 else .76,.105,f"Pooled P95 difference: {pair['delta_ms']:+.1f} ms\n95% paired cluster interval: [{lo:+.1f}, {hi:+.1f}]",ha='center',fontsize=9)
    axes[0].set_ylabel('Per-trial P95: corrected − stock (ms)')
    fig.suptitle('Paired trial P95 variation and pooled uncertainty',fontsize=13)
    fig.text(.5,.015,'Each point uses 60 requests. Pooled intervals resample entire paired trials, retaining within-trial dependence.',ha='center',fontsize=9)
    fig.tight_layout(rect=[0,.2,1,.92]);fig.savefig(CHARTS/'phase3-trial-p95.png',dpi=180);plt.close(fig)

def precision():
    source=PRECISION/'summary.json'
    if not source.exists():return
    s=json.loads(source.read_text(encoding='utf-8'))
    allocations=[json.loads(p.read_text(encoding='utf-8')) for p in ALLOCATIONS.rglob('allocation.json')]
    lines=['# Generated precision table','','Medians of five per-trial summaries. Each row has 30 measured attempts; two separate warmups per trial. GPU maxima are one-second system-wide samples in the timed window, not exact or process-exclusive peaks.','',
        '| Context | Input | Output | Route | KV | Median TTFT ms | Decode tokens/s per stream | Prefill ms | Decode ms | End-to-end output tokens/s | Ready GPU MiB | Sampled timing peak GPU MiB | Failures | Factual passes |',
        '|---:|---:|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for g in s['groups']:
        lines.append(f"| {g['context']} | {g['input_tokens']} | {g['predict']} | {LABELS[g['arm']]} | {g['kv']} | {g['median_ttft_ms']:.2f} | {g['median_decode_tps']:.2f} | {g['median_prefill_ms']:.2f} | {g['median_decode_ms']:.2f} | {g['end_to_end_output_tps']:.2f} | {g['ready_system_gpu_mib']:.0f} | {g['sampled_peak_system_gpu_mib']:.0f} | {g['failures']} | {g['factual_passes']}/{g['attempts']} |")
    (PRECISION/'tables.md').write_text('\n'.join(lines),encoding='utf-8')
    fig,axes=plt.subplots(1,3,figsize=(15,5.6),gridspec_kw={'width_ratios':[.8,1.3,1.3]})
    ax=axes[0]
    for i,context in enumerate([9216,16384]):
        for j,kv in enumerate(['f16','q8_0']):
            value=next(a['native_gpu_buffers']['KV_mib'] for a in allocations if a['context']==context and a['kv']==kv)
            x=i+(j-.5)*.34
            ax.bar(x,value,width=.3,color=['#476a89','#dc9a37'][j],label=kv if i==0 else None)
            ax.annotate(f'{value:.1f}',(x,value),xytext=(0,4),textcoords='offset points',ha='center',fontsize=9)
    ax.set_xticks([0,1],['9,216','16,384']);ax.set_xlabel('Total context tokens');ax.set_ylabel('Native allocated KV buffer (MiB)');ax.set_ylim(0,max(a['native_gpu_buffers']['KV_mib'] for a in allocations)*1.18);ax.legend();ax.grid(axis='y',alpha=.15)
    configs=sorted({(p['context'],p['input_tokens'],p['predict']) for p in s['paired_precision']})
    for ax,metric,title in zip(axes[1:],['median_ttft_ms','median_decode_tps'],['TTFT change (negative is lower)','Decode rate change (positive is faster)']):
        for i,config in enumerate(configs):
            for j,arm in enumerate(['fifo','corrected']):
                r=next(p for p in s['paired_precision'] if (p['context'],p['input_tokens'],p['predict'])==config and p['arm']==arm)['metrics'][metric]
                x=r['paired_median_change_percent'];lo,hi=r['exploratory_trial_bootstrap_95_percent'];y=i+(j-.5)*.18
                ax.errorbar(x,y,xerr=[[x-lo],[hi-x]],fmt='o' if arm=='fifo' else '^',color=COLORS[arm],capsize=3,label=LABELS[arm] if i==0 else None)
        ax.axvline(0,color='#888',lw=1);ax.set_yticks(range(len(configs)),[f'ctx {c:,}\nin {size:,} / out {out}' for c,size,out in configs]);ax.invert_yaxis();ax.set_xlabel('q8_0 versus f16 (%)');ax.set_title(title,fontsize=11);ax.grid(axis='x',alpha=.15);ax.legend(fontsize=8)
    fig.suptitle('KV precision: allocation savings and measured latency/throughput tradeoffs',fontsize=14)
    fig.text(.5,.015,'Four selected cases spanning all requested levels · 5 paired trials × 6 measured requests per cell\nIntervals resample paired trial seeds. Cases are a balanced subset, not a full factorial or near-capacity experiment.',ha='center',fontsize=9)
    fig.tight_layout(rect=[0,.07,1,.93]);fig.savefig(CHARTS/'phase3-kv-precision.png',dpi=180);plt.close(fig)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--tail-analysis',default='phase3/analysis');p.add_argument('--precision-analysis',default='phase3/precision-analysis');p.add_argument('--allocations',default='phase3/allocations');p.add_argument('--charts-out',default='analysis');args=p.parse_args()
    TAIL=ROOT/args.tail_analysis;PRECISION=ROOT/args.precision_analysis;ALLOCATIONS=ROOT/args.allocations;CHARTS=ROOT/args.charts_out;CHARTS.mkdir(parents=True,exist_ok=True)
    tail();precision()
    print('Regenerated Phase 3 tables and charts from retained measurements')
