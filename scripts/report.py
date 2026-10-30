"""Write the research report and application draft only after the full matrix exists."""
import json
import pathlib
import statistics
import argparse
import os
from collections import defaultdict

ROOT=pathlib.Path(__file__).resolve().parents[1]

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--results",default="results")
    parser.add_argument("--analysis",default="analysis")
    parser.add_argument("--out",default="docs")
    options=parser.parse_args()
    analysis=ROOT/options.analysis
    results=ROOT/options.results
    destination=ROOT/options.out
    destination.mkdir(parents=True,exist_ok=True)
    summary=json.loads((analysis/"summary.json").read_text(encoding="utf-8"))
    comparisons=json.loads((analysis/"comparisons.json").read_text(encoding="utf-8"))
    validation=json.loads((analysis/"validation.json").read_text(encoding="utf-8"))
    resources=json.loads((analysis/"resources.json").read_text(encoding="utf-8"))
    full=[r for r in summary if r["suite"]=="full"]
    assert len(full)==40 and all(r["trials"]==5 and r["n"]==300 for r in full), "Full study incomplete: refusing an application-ready result"
    full_failures=sum(r["failures"] for r in full)
    failure_inventory=json.loads((analysis/"failures.json").read_text(encoding="utf-8"))
    warmup_failures=sum(r["suite"]=="full" and r["phase"]=="warmup" for r in failure_inventory)
    secondary=[r for r in summary if r["suite"]=="secondary"]
    assert len(secondary)==16 and all(r["n"]==60 and r["failures"]==0 for r in secondary), "Secondary matrix incomplete"
    assert len(validation["factual_probes"])==10, "Correctness matrix incomplete"
    assert (results/"negative-controls/checks.json").exists(), "Live negative controls must complete first"
    assert (results/"profile/cold-warm.nsys-rep").exists(), "Nsight capture missing"
    def row(workload,mode,cache=8192,concurrency=1):
        return next(r for r in full if r["workload"]==workload and r["mode"]==mode and r["host_cache_mib"]==cache and r["concurrency"]==concurrency)
    def comparison(workload,cache=8192,concurrency=1):
        return next(r for r in comparisons if r["suite"]=="full" and r["workload"]==workload and r["host_cache_mib"]==cache and r["concurrency"]==concurrency)
    def interval(c):
        bounds=c["bootstrap_95_percent_interval"]
        return "unavailable" if bounds is None else f"[{bounds[0]:+.1f}, {bounds[1]:+.1f}]"
    uncached=row("single-2048","uncached",0)
    stock=row("single-2048","stock")
    main_comparisons=[c for c in comparisons if c["suite"]=="full" and c["host_cache_mib"]==8192]
    best=max(main_comparisons,key=lambda c:c["change_percent_positive_is_faster"])
    worst=min(main_comparisons,key=lambda c:c["change_percent_positive_is_faster"])
    mixed=comparison("mixed-2048")
    text=["# When does conversation-aware eviction help local inference?","",
          "## Findings","",
          f"On an RTX 4070 Laptop GPU, stock prompt caching reduced the median TTFT of the repeated 2,048-token conversation from **{uncached['median_ms']:.1f} ms** uncached to **{stock['median_ms']:.1f} ms**. This is the caching baseline, not a gain attributable to Rust scheduling.","",
          f"Against stock caching with the same 8,192 MiB host-cache budget, custom scheduling's paired median changes ranged from **{worst['change_percent_positive_is_faster']:+.1f}%** to **{best['change_percent_positive_is_faster']:+.1f}%** across the eight workload/client configurations. Positive values mean faster custom scheduling. These are trace-specific comparisons on one device, not a universal speedup.","",
          f"The mixed-length, single-client comparison changed by **{mixed['change_percent_positive_is_faster']:+.1f}%**, with exploratory paired-bootstrap 95% interval **{interval(mixed)}%**. See the full matrix below, including P95 regressions.","",
          "![Cached versus uncached TTFT](../analysis/cached-vs-uncached.png)","",
          "## Study and implementation","",
          "The Rust implementation keeps longest-prefix matching, then changes miss eviction to retain prefixes with higher token cost and greater frequency in the preceding 32 admissions. It uses no future request information. llama.cpp performs inference and validates all actual cache reuse.","",
          f"The repeated study comprises **200 fresh-server arms and 12,000 measured request attempts**, plus 1,200 labeled warmup requests. The retained matrix includes **{full_failures} failed measured requests and {warmup_failures} failed warmup requests**. Latency summaries condition on successful responses; failures are not assigned zero latency. Every configuration has five paired trial seeds with 60 measured attempts each. The model is Qwen2.5-3B-Instruct Q4_K_M, running llama.cpp b11960's CUDA 12.4 binaries. There are two fixed slots with 6,144 tokens each. Timing runs generate eight tokens. Launch arguments, fixtures and retained raw counters accompany the results.","",
          "TTFT starts with a prepared request and ends at the first nonempty streamed output. Tokenization and model loading are outside that interval. The main workload uses one or two closed-loop clients; it is not an open-loop service-load test.","",
          "## Main comparison: stock host caching enabled","",
          "Both policies receive the same 8,192 MiB host-RAM cache budget. Each row contains 300 measured attempts per policy. Median columns show the median of the five trial medians, matching the paired change and interval. P95 pools successful responses; failure counts appear separately. The plots and `summary.json` also retain pooled request medians. All latency statistics condition on success.","",
          "| Workload | Clients | Stock median ms | Custom median ms | Paired change % | 95% interval % | Stock P95 ms | Custom P95 ms | Failures stock/custom |",
          "|---|---:|---:|---:|---:|---|---:|---:|---:|"]
    configurations=[("single-512",1),("single-2048",1),("single-4096",1),("rotation-2048",1),("rotation-2048",2),("skewed-2048",1),("skewed-2048",2),("mixed-2048",1)]
    def table(cache):
        rows=[]
        for workload,concurrency in configurations:
            a=row(workload,"stock",cache,concurrency)
            b=row(workload,"custom",cache,concurrency)
            c=comparison(workload,cache,concurrency)
            rows.append(f"| {workload} | {concurrency} | {c['stock_median_of_trial_medians_ms']:.2f} | {c['custom_median_of_trial_medians_ms']:.2f} | {c['change_percent_positive_is_faster']:+.1f} | {interval(c)} | {a['p95_ms']:.2f} | {b['p95_ms']:.2f} | {a['failures']} / {b['failures']} |")
        return rows
    text+=table(8192)
    text += ["","The single-conversation rows are controls with no competing history to evict. Small timing differences there cannot establish an eviction-policy benefit. Use the multi-conversation rows and their uncertainty when assessing the policy; even those require representative traces before deployment."]
    text += ["","![Main comparison, one client](../analysis/full-c1-ram8192.png)","",
             "![Main comparison, two clients](../analysis/full-c2-ram8192.png)","",
             "## Constrained comparison: host cache disabled","",
             "This removes the stock RAM-cache safety net from both policies. It isolates slot retention, but must not be substituted for the default-caching baseline. Some workloads can reduce average recomputation without changing the median because fewer than half of requests benefit.","",
             "| Workload | Clients | Stock median ms | Custom median ms | Paired change % | 95% interval % | Stock P95 ms | Custom P95 ms | Failures stock/custom |",
             "|---|---:|---:|---:|---:|---|---:|---:|---:|"]
    text+=table(0)
    diagnostic_path=analysis/"concurrent-diagnostic.json"
    if diagnostic_path.exists():
        diagnostic=json.loads(diagnostic_path.read_text(encoding="utf-8"))
        a=diagnostic["stock"]
        b=diagnostic["custom"]
        text += ["","### Investigating the concurrent regression","",
                 f"In the exploratory first-trial skewed, two-client case with host caching disabled, stock evaluated {a['total_evaluated_tokens']:,} input tokens and custom evaluated {b['total_evaluated_tokens']:,}; they had {a['prefix_hits_over_1000_tokens']} and {b['prefix_hits_over_1000_tokens']} requests with more than 1,000 reused tokens. Their medians were {a['median_ms']:.1f} and {b['median_ms']:.1f} ms; their means were {a['mean_ms']:.1f} and {b['mean_ms']:.1f} ms. Only {a['ttft_under_100_ms']} stock and {b['ttft_under_100_ms']} custom requests finished TTFT below 100 ms. A few requests crossing the middle of this bimodal distribution can produce a much larger median ratio than mean ratio.","",
                 "Concurrent batching, request overlap, and slot availability can affect latency beyond total cache hits. External slot reservation waits for the client to finish receiving a response, while the engine observes its own slot state directly. This is a mechanism to investigate, not a causal finding established by this trace. The diagnostic uses trial 0 only; the five-trial matrix above is the primary comparison.","",
                 "![Concurrent diagnostic](../analysis/concurrent-diagnostic.png)"]
    text += ["",
             "## Why the numbers can change","",
             "Stock llama.cpp already matches common prefixes and saves/restores displaced prompts in host RAM. An eviction heuristic has an opportunity when it keeps a frequently reused history resident, avoiding later prefill or restore work. It can also preserve an outdated hot history, change which idle slot receives a request, or add routing overhead. A latency difference without a corresponding change in reuse should not automatically be attributed to smarter eviction.","",
             "| Configuration | Policy | Median reused input tokens | Median evaluated input tokens | Median prefill ms | Median scheduling microseconds |",
             "|---|---|---:|---:|---:|---:|"]
    for cache in [8192,0]:
        for mode in ["stock","custom"]:
            r=row("mixed-2048",mode,cache)
            text.append(f"| Mixed, host {cache} MiB | {mode} | {r['median_reused_prompt_tokens']:.0f} | {r['median_evaluated_prompt_tokens']:.0f} | {r['median_prefill_ms']:.2f} | {r['median_schedule_us']:.2f} |")
    routing=validation["full_custom_routing_predictions"]
    off=routing["0"]
    on=routing["8192"]
    text += ["",f"With host caching disabled, the custom scheduler's prefix prediction exceeded the engine's actual reused-input count on {off['engine_reuse_below_prediction']} of {off['requests']:,} measured requests. With host caching enabled, the engine reused more than the slot-local prediction on {on['engine_reuse_above_prediction']} of {on['requests']:,} requests. This is direct evidence that the RAM-cache layer adds reuse beyond the Rust slot metadata; it is a separate check from output quality."]
    text += ["","The separate Nsight Systems capture contains CUDA matrix multiplication, matrix-vector, attention, memory-transfer, and synchronization activity. Its kernel summary includes startup and multiple requests, so it is not a per-request bottleneck attribution. The trace and summary are in `results/profile/` and are excluded from every timing chart.","",
             "## Correctness and quality","",
             "The correctness suite uses greedy generation with EOS enabled and up to 32 tokens. It measures factual recall separately from exact formatting. The initial probe design sometimes failed in a fresh uncached process; revised fixtures include a recent scripted confirmation. The original diagnostics remain available and are excluded from the final timing matrix.","",
             "| Correctness arm | Factual passes / requests | Exact-format matches | Exact generated-token agreement with uncached |",
             "|---|---:|---:|---:|"]
    for name,checks in sorted(validation["factual_probes"].items()):
        match=validation["greedy_comparisons"].get(name)
        tokens="baseline" if match is None else f"{match['exact_token_matches']} / {match['total']}"
        text.append(f"| {name.removeprefix('correctness-t0-').removesuffix('-f16-ctx12288')} | {checks['factual_passes']} / {checks['total']} | {checks['exact_format']} | {tokens} |")
    text += ["","These counts include six warmup and 60 measured requests per arm. The repeated mixed-workload factual miss is also present in its uncached baseline. Exact generated-token differences remain and are not claimed to establish bitwise equivalence. Backend batch-size changes are one possible contributor; these probes cannot establish general model-quality preservation.","",
             f"The validation audit reconciled **{validation['counter_consistency']:,}** completed requests' cache/evaluation counts and **{validation['log_counter_matches']:,}** evaluated-token counts against engine logs. Unit tests cover prefix changes, busy-slot handling, eviction, scope reset, cancellation, FIFO admission and streaming boundaries. Live controls exercise oversized requests, changed scope, and changed system instructions; see `results/negative-controls/checks.json`.","",
             "## Memory and secondary experiments","",
             "A one-trial secondary study varies f16/q8_0 KV precision and 9,216/16,384 total context tokens. This measures allocation and latency tradeoffs while the 3B model fits; it does not demonstrate behavior near the 8 GB capacity limit. Short output differences must not be treated as a full quality evaluation.","",
             "| KV type | Total context | Workload | Policy | Median TTFT ms | Sampled device-wide GPU peak MiB |",
             "|---|---:|---|---|---:|---:|"]
    for r in summary:
        if r["suite"]!="secondary":
            continue
        matched=[s for s in resources if pathlib.Path(s["path"]).name.startswith("secondary-") and s["workload"]==r["workload"] and all(s["config"][k]==r[k] for k in ["mode","kv","context"])]
        peak=max((s["sampled_global_gpu_peak_mib"] for s in matched),default=None)
        text.append(f"| {r['kv']} | {r['context']} | {r['workload']} | {r['mode']} | {r['median_ms']:.2f} | {'unavailable' if peak is None else f'{peak:.0f}'} |")
    memory_pair={}
    for precision in ["f16","q8_0"]:
        points=[r["sampled_global_gpu_peak_mib"] for r in resources if pathlib.Path(r["path"]).name.startswith("secondary-") and r["workload"]=="single-4096" and r["config"]["mode"]=="stock" and r["config"]["context"]==16384 and r["config"]["kv"]==precision]
        if points:
            memory_pair[precision]=max(points)
    if len(memory_pair)==2:
        text += ["",f"In the one-trial stock 4,096-token workload with 16,384 total context, sampled device-wide GPU peak was {memory_pair['f16']:.0f} MiB with f16 and {memory_pair['q8_0']:.0f} MiB with q8_0, a difference of {memory_pair['f16']-memory_pair['q8_0']:.0f} MiB. This is an observed allocation tradeoff on this setup, not evidence that quantization uniformly improves latency or preserves output quality."]
    precision_path=analysis/"kv-output-comparisons.json"
    if precision_path.exists():
        precision=json.loads(precision_path.read_text(encoding="utf-8"))
        if precision:
            text += ["","The secondary study also compares exact output-token sequences under f16 and q8_0 for the same scripted requests. Each is an eight-token reply; disagreement demonstrates a numerical/output difference, not a measured semantic-quality loss.","",
                     "| Workload | Total context | Policy | Exact f16/q8_0 output matches |",
                     "|---|---:|---|---:|"]
            for item in precision:
                text.append(f"| {item['workload']} | {item['context']} | {item['mode']} | {item['exact_first_output_token_matches']} / {item['pairs']} |")
    text += ["","GPU samples are approximately one second apart, device-wide, include loading and desktop activity, and can miss transient peaks. Process RSS is system RAM. Preserving more useful tokens inside an already allocated KV buffer does not itself reduce allocated VRAM.","",
             "## Collection failure and recovery","",
             f"Trial 3's skewed, two-client stock arm with host cache disabled first recorded an HTTP connection-close error on request 26. Collection stopped and that whole arm was restarted. The first resume overwrote the original raw JSONL before archival was implemented; its inspected error summary survives in `results/failed-attempts/observed-http-failure.json`. The second attempt recorded two connection-close errors (requests 39 and 48). Its complete request file is retained in the matrix, including those failures, and archived separately. Collection then continued without per-request retries. The retained matrix contains {full_failures} failed measured requests; latency is conditional on success. The first attempt's missing raw timings limit fault analysis and may introduce selection effects. The transport fault's root cause remains unresolved. Resumes now preserve incomplete attempts, and failure-containing runs that recorded every planned request are retained with explicit failure counts.","",
             "## Interpretation and limits","",
             "Keep stock caching as the general starting point. Adopt a different eviction policy only after its gains and tail-latency costs hold on representative traces and memory budgets. This study supports configuration-specific observations on one Windows laptop, not mobile, battery-life, or multi-device conclusions.","",
             "The main limits are synthetic repetitive histories, short output runs, five trial blocks, multiple exploratory comparisons, background desktop/controller activity, and no enforced thermal equilibrium. The laptop was observed plugged in under the Balanced power scheme, but AC state was not logged continuously. The server is reset per arm, so the study does not measure cold model startup or every long-lived-cache state.","",
             "Reproduce with the commands in the README. Exact definitions and aggregation are in [METHODS.md](METHODS.md); inspect `analysis/summary.json`, `comparisons.json`, `resources.json` and `validation.json` for evidence and uncertainty. All figures are generated from completed raw runs, and no illustrative speedups are used."]
    affected=[c for c in comparisons if c["suite"]=="full" and c["excluded_failure_trials_for_sensitivity"]]
    failure_path=analysis/"failures.json"
    if failure_path.exists():
        failures=json.loads(failure_path.read_text(encoding="utf-8"))
        text += ["","## Retained request failures","",
                 "This inventory includes measured and warmup failures. It is separate from the overwritten first attempt summarized in the collection-history section.","",
                 "| Workload | Trial | Clients | Policy | Host MiB | Phase | Request | Error |",
                 "|---|---:|---:|---|---:|---|---:|---|"]
        for r in failures:
            text.append(f"| {r['workload']} | {r['trial']} | {r['concurrency']} | {r['mode']} | {r['host_cache_mib']} | {r['phase']} | {r['request_id']} | {r['error']} |")
    if affected:
        text += ["","## Sensitivity to observed transport failures","",
                 "A request that was not received can also change later cache state. The affected arm is therefore a confounded policy comparison, not merely a missing latency value. The primary matrix keeps all observations. This post hoc check omits each affected trial from both policies; it does not recover the lost first-attempt data or prove a transport cause.","",
                 "| Workload | Clients | Host cache MiB | Omitted trials | Remaining paired trials | Paired change % |",
                 "|---|---:|---:|---|---:|---:|"]
        for c in affected:
            text.append(f"| {c['workload']} | {c['concurrency']} | {c['host_cache_mib']} | {c['excluded_failure_trials_for_sensitivity']} | {c['failure_free_paired_trials']} | {c['failure_free_change_percent_positive_is_faster']:+.1f} |")
    if results!=ROOT/"results":
        text=[f"The independent retained matrix contains {full_failures} failed measured requests. Latency summaries condition on successful responses and failures remain explicit observations. Consult this collection's raw request files and archived attempts; the original project's collection history is documented separately in the canonical report." if line.startswith("Trial 3's skewed") else line.replace("The repeated mixed-workload factual miss is also present in its uncached baseline. ","Compare factual misses with the uncached baseline shown above. ") for line in text]
    report_text="\n".join(text)+"\n"
    report_text=report_text.replace("1 failed warmup requests","1 failed warmup request")
    image_prefix=pathlib.Path(os.path.relpath(analysis,destination)).as_posix()+"/"
    methods_path=pathlib.Path(os.path.relpath(ROOT/"docs/METHODS.md",destination)).as_posix()
    report_text=report_text.replace("../analysis/",image_prefix).replace("](METHODS.md)",f"]({methods_path})")
    (destination/"REPORT.md").write_text(report_text,encoding="utf-8")
    app=["# Loci application material","","## Short project paragraph","",
         f"I investigated conversation-cache scheduling on an 8 GB RTX 4070 Laptop GPU with Qwen2.5-3B and llama.cpp. I built a Rust scheduler and streaming benchmark covering 200 experiment arms and 12,000 measured request attempts. Stock caching reduced repeated 2,048-token median TTFT from {uncached['median_ms']:.1f} ms to {stock['median_ms']:.1f} ms. The custom heuristic's mixed-length paired change was {mixed['change_percent_positive_is_faster']:+.1f}% (positive means faster; exploratory 95% interval {interval(mixed)}%), with regressions under concurrency. I audited reuse counters against engine logs, compared factual and greedy outputs, captured a separate Nsight Systems trace, and measured KV-precision memory tradeoffs. The analysis retains transport failures and documents a collection-data gap. This project taught me to profile existing runtime behavior before adding scheduling complexity.","",
         "## Resume bullet","",
         "Built a Rust conversation-cache scheduler and reproducible CUDA inference benchmark; evaluated 12k request attempts across 200 experiment arms, with stock-cache baselines, P95 latency, cache-counter audits, output checks, and Nsight profiling.","",
         "## Interview walkthrough","",
         "1. **Problem:** Long histories make prefill expensive, even when the latest user message is short. More conversations than slots can cause repeated work.",
         "2. **Baseline:** llama.cpp already offers prefix matching, LRU fallback, and RAM prompt caching. The comparison preserves those features before testing a constrained host-cache-disabled case.",
         "3. **Change:** Keep prefix matching; change miss eviction using cached token count times recent conversation frequency. Use leases and FIFO admission to handle concurrent requests safely.",
         f"4. **Evidence:** Explain the uncached-to-stock change ({uncached['median_ms']:.1f} to {stock['median_ms']:.1f} ms), then separately explain the custom-versus-stock mixed result ({mixed['change_percent_positive_is_faster']:+.1f}%). Show the complete matrix and a P95 regression rather than quoting the best cell alone.",
         "5. **Correctness:** Describe the unreliable original probe, the uncached diagnostic, the revised fixture, exact-token differences, and the remaining baseline factual miss.",
         "6. **Limits:** Synthetic traces, one GPU/model, five blocks, short replies, background activity, and no evidence of mobile or battery benefits. Point to the next measurement that would change a deployment choice.","",
         f"7. **Reliability:** The retained matrix contains {full_failures} failed measured requests and {warmup_failures} failed warmup requests; TTFT statistics condition on success. Explain the whole-arm restart, the lost original raw file, the preserved second-attempt errors, and the archival fix. Do not describe the collection as failure-free.","",
         "Application files are drafts for review. Replace a local repository reference with a published URL only after reviewing and publishing the repository."]
    (destination/"APPLICATION.md").write_text(("\n".join(app)+"\n").replace("1 failed warmup requests","1 failed warmup request"),encoding="utf-8")
    if destination==ROOT/"docs" and analysis==ROOT/"analysis" and results==ROOT/"results":
        readme_path=ROOT/"README.md"
        readme=readme_path.read_text(encoding="utf-8")
        begin="<!-- BEGIN MEASURED SUMMARY -->"
        end="<!-- END MEASURED SUMMARY -->"
        measured=f"""{begin}
## Measured outcome

**Stock caching provides the large baseline gain; the custom policy is workload-dependent and has concurrency regressions.** In the repeated 2,048-token control, median TTFT was {uncached['median_ms']:.1f} ms uncached and {stock['median_ms']:.1f} ms with stock caching. That gain belongs to the existing cache, not the Rust policy.

The custom-versus-stock mixed-length comparison changed paired median TTFT by {mixed['change_percent_positive_is_faster']:+.1f}% (positive means faster), with exploratory 95% interval {interval(mixed)}%. The retained matrix contains 200 fresh-server arms, 12,000 measured attempts, {full_failures} failed measured requests plus {warmup_failures} failed warmup requests, five trial seeds, P95 regressions, and output checks. Latency conditions on successful responses. See [the report](docs/REPORT.md), including its collection-failure disclosure, before drawing a deployment conclusion.

![Measured cached versus uncached TTFT](analysis/cached-vs-uncached.png)
{end}

"""
        if begin in readme:
            start=readme.index(begin)
            finish=readme.index(end,start)+len(end)
            readme=readme[:start]+measured.rstrip()+readme[finish:]
        else:
            readme=readme.replace("## Reproduce",measured+"## Reproduce",1)
        readme_path.write_text(readme,encoding="utf-8")
    print(f"Generated report and application draft in {destination}")

if __name__=="__main__":
    main()
