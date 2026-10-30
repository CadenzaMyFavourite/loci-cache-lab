"""Fill generated evidence regions in the authored Phase 3 release documents."""
import json
import re
from experiment import ROOT

def block(path,name,value):
    path=ROOT/path;content=path.read_text(encoding='utf-8')
    placeholder=f'<!-- {name} -->';begin=f'<!-- {name}_START -->';end=f'<!-- {name}_END -->'
    replacement=begin+'\n\n'+value+'\n\n'+end
    if placeholder in content:content=content.replace(placeholder,replacement)
    else:
        content,count=re.subn(re.escape(begin)+r'.*?'+re.escape(end),lambda _:replacement,content,flags=re.S)
        assert count==1,(path,name)
    path.write_text(content,encoding='utf-8')

if __name__=='__main__':
    p=json.loads((ROOT/'phase3/precision-analysis/summary.json').read_text(encoding='utf-8'))
    c=json.loads((ROOT/'phase3/precision-correctness-analysis/summary.json').read_text(encoding='utf-8'))
    table=(ROOT/'phase3/precision-analysis/tables.md').read_text(encoding='utf-8')
    table=table[table.index('| Context |'):]
    block('docs/kv-cache-precision.md','PRECISION_TABLE',table)
    lines=['All eight paired per-stream decode-rate point estimates are lower with q8_0: **3.34–5.70% slower**. Some five-trial intervals include improvements, so this is not a universal slowdown claim. TTFT is mixed and often very uncertain; one stock case has a +3.30% point estimate and an interval extending to +326.12%. Allocation savings do not establish lower latency.','',
        '| Context / input / output | Route | Paired TTFT change % [95% interval] | Paired decode-rate change % [95% interval] |',
        '|---|---|---|---|']
    for row in p['paired_precision']:
        def cell(metric):
            r=row['metrics'][metric];lo,hi=r['exploratory_trial_bootstrap_95_percent']
            return f"{r['paired_median_change_percent']:+.2f} [{lo:+.2f}, {hi:+.2f}]"
        lines.append(f"| {row['context']} / {row['input_tokens']} / {row['predict']} | {row['arm']} | {cell('median_ttft_ms')} | {cell('median_decode_tps')} |")
    lines+=['','These paired percentage medians are not ratios of the medians in the preceding table. Cache/evaluated counts and batching vary between independent runs. For example, corrected mode at context 16,384/input 4,096 evaluates 28,943 measured tokens with f16 and 24,864 with q8_0; stock evaluates 28,943 with each. Do not attribute every TTFT change solely to quantization arithmetic. All 480 measured timing requests and 160 warmups succeeded.']
    block('docs/kv-cache-precision.md','PRECISION_INTERPRETATION','\n'.join(lines))
    mismatches=sum(len(r['greedy_token_mismatches']) for r in p['paired_precision'])
    label_diffs=sum(r['token_mismatches'] for r in p['same_precision_label_controls'])
    probpairs=[r for pair in p['paired_precision'] for r in pair['cold_first_token_logprob_comparisons']]
    argmax=sum(r['first_token_f16']!=r['first_token_q8'] for r in probpairs)
    logdelta=max(r['max_abs_logprob_delta_shared'] for r in probpairs)
    eos_mismatches=sum(len(r['greedy_token_mismatches']) for r in c['paired_precision'])
    correctness=f"Timing token sequences differ in **{mismatches}/240 f16/q8_0 paired outputs**, compared with **{label_diffs}/240 same-precision label comparisons**. Forced generation beyond EOS makes full-sequence divergence easier; these are not factual error rates. The cold controls switch their first-token argmax in **{argmax}/{len(probpairs)} paired cells**. Maximum shared-candidate log-probability difference is **{logdelta:.3f} natural-log units**, including low-probability candidates. These cells repeat prompts across labels/contexts and are not independent input examples.\n\n"
    correctness+='| EOS probe route | KV | Factual passes | Measured request failures |\n|---|---|---:|---:|\n'
    for row in c['groups']:correctness+=f"| {row['arm']} | {row['kv']} | {row['factual_passes']}/{row['attempts']} | {row['failures']} |\n"
    correctness+=f"\nAll **120/120 selected EOS-enabled probes** pass the factual criterion, with zero measured or warmup request failures. There are **{eos_mismatches}/60 f16/q8_0 token-sequence mismatches** in these probes: f16 gives a verbose correct answer while q8_0 gives the exact code. Neither precision has a same-precision label mismatch in the EOS controls. This selected 4,096-input case does not establish perfect correctness for every workload or the 2,048-input cases. Timing outputs contain factual failures and remain inspectable."
    block('docs/kv-cache-precision.md','PRECISION_CORRECTNESS',correctness)
    block('PHASE3_REPORT.md','PRECISION_FINDING','The independent repeated precision study finds a clear allocation tradeoff: q8_0 reduces the native KV buffer by about **46.9%**, while paired per-stream decode-rate point estimates are **3.34–5.70% lower**. TTFT changes are mixed and uncertain. All selected EOS factual probes pass, but token sequences and cold numerical outputs differ. Compression is not reported as an automatic speedup.')
    precision='''Four preregistered selected context/input/output cases span 9,216/16,384 total context, 2,048/4,096 input and 32/128 output tokens. Crossing both precisions and both routing labels gives **80 timing arms**, with five paired trials per cell, six measured requests and two warmups: **480 measured attempts and 160 warmups**. A separate 20-arm EOS-enabled study contributes 120 measured factual probes and 40 warmups. Both collections have zero request failures.

| Total context | f16 allocated KV MiB | q8_0 allocated KV MiB |
|---:|---:|---:|
| 9216 | 324.00 | 172.15 |
| 16384 | 576.00 | 306.03 |

The model buffer remains 1,834.83 MiB. Native allocation is measured outside normal-log timing; ready GPU usage and one-second timed-window system maxima are sampled in every trial. A smaller KV allocation does not imply the same percentage reduction in total VRAM. This is an allocation comparison with headroom, not a near-capacity test.

All eight paired decode-rate point estimates regress **3.34–5.70%** with q8_0; several intervals include a benefit, so the evidence does not support an invariant penalty either. TTFT sometimes improves and sometimes regresses, with wide intervals and some different cache/evaluation counts. For example, the 9,216/2,048/32 stock comparison has a **−4.24%** per-stream decode-rate change **[−4.65%, −1.32%]**. The 9,216/4,096/128 stock TTFT change is **+3.30% [−35.17%, +326.12%]**. No universal latency improvement is claimed.

Across fixed-length timing outputs, **197/240 paired f16/q8_0 sequences differ**, versus **14/240 same-precision label controls**. Separate cold first-token controls observe four argmax changes in forty paired cells and retain top-eight pre-sampling log probabilities. These repeated cells are not forty independent prompts. All **120 selected EOS-enabled factual probes pass**; four of sixty paired precision sequences differ only by a verbose versus concise correct answer. This does not establish correctness outside that selected case, and timing-output factual failures remain visible.

![KV precision tradeoffs](analysis/phase3-kv-precision.png)

The [precision report](docs/kv-cache-precision.md) contains the exact selected design, per-case tables, paired uncertainty, numerical details, native allocation and sampled-memory limits. [Raw precision summary](phase3/precision-analysis/summary.json) and [EOS controls](phase3/precision-correctness-analysis/summary.json) preserve regressions and output differences. The selected matrix is not a full factorial and cannot isolate every context/input/output interaction.'''
    block('PHASE3_REPORT.md','PRECISION_RESULTS',precision)
    readme='''## Current findings

The fixed-arrival study expanded from ten to **twenty paired trials**, totaling **4,800 measured attempts**. With host caching disabled, stock/corrected P95 was **570.06/580.54 ms**, a paired pooled change of **+1.84% [−0.24%, +8.75%]**. A failure-free sensitivity interval is wider. With normal host caching, the P95 ranking flipped during sample expansion and remains unresolved. **No intrinsic corrected-mode speedup is established.** Five measured connection failures and one warmup failure are retained.

![Controlled tail distributions](analysis/phase3-tail-distributions.png)

The independent precision matrix has **five paired trials per selected configuration**. q8_0 lowers native KV allocation from **324 to 172.15 MiB** at 9,216 context tokens and **576 to 306.03 MiB** at 16,384. Per-stream decode-rate point estimates regress **3.34–5.70%**; TTFT changes and intervals are mixed. All 120 selected EOS factual probes pass, while numerical and token differences remain. See [the precision report](docs/kv-cache-precision.md) for scope, regressions and uncertainty.

The practical default remains **stock native routing for concurrent work**. The original custom policy remains an experiment; corrected mode delegates concurrent decisions to the engine. Neither a new mode name nor a smaller buffer is evidence of a new inference speedup.'''
    block('README.md','PHASE3_FINAL',readme)
    print('Filled Phase 3 release documents from retained summaries')
