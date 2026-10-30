"""Recompute every published number and static figure from raw request JSONL."""
import argparse
from collections import defaultdict
import csv
import json
import math
import pathlib
import random
import statistics

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT=pathlib.Path(__file__).resolve().parents[1]
COLORS={"uncached":"#8A8D91","stock":"#295D96","custom":"#B06C10"}

def percentile(values,p):
    values=sorted(values)
    position=(len(values)-1)*p
    lo=math.floor(position)
    hi=math.ceil(position)
    return values[lo]+(values[hi]-values[lo])*(position-lo)

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--results",default="results")
    parser.add_argument("--out",default="analysis")
    args=parser.parse_args()
    source=ROOT/args.results
    destination=ROOT/args.out
    destination.mkdir(parents=True,exist_ok=True)
    groups=defaultdict(list)
    all_rows=[]
    files=[]
    resources=[]
    for path in sorted(source.rglob("requests.jsonl")):
        if "failed-attempts" in path.relative_to(source).parts:
            continue
        if not (path.parent/"complete.json").exists():
            continue
        records=[json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        meta=records[0]
        seen=set()
        for row in records[1:]:
            assert row["request_id"] not in seen, f"duplicate request in {path}"
            seen.add(row["request_id"])
            row["suite"]=path.parent.name.split("-t")[0]
            row["source"]=str(path.relative_to(ROOT))
            if row["phase"]!="measured":
                continue
            key=(row["suite"],row["workload"],row["concurrency"],row["mode"],row["host_cache_mib"],row["kv"],row["context"])
            groups[key].append(row)
            all_rows.append(row)
        files.append({"path":str(path.relative_to(ROOT)),"metadata":meta})
        samples=[]
        for line in (path.parent/"telemetry.jsonl").read_text(encoding="utf-8").splitlines():
            sample=json.loads(line)
            if "gpu_csv" in sample:
                fields=sample["gpu_csv"].splitlines()[0].split(",")
                values=[]
                for value in fields:
                    try: values.append(float(value.strip()))
                    except ValueError: values.append(None)
                samples.append((sample,values))
        if samples:
            def peak(index):
                available=[v[index] for s,v in samples if v[index] is not None]
                return max(available) if available else None
            resources.append({"path":str(path.parent.relative_to(ROOT)),"config":meta["config"],"workload":meta["workload"],"samples":len(samples),"sampled_global_gpu_peak_mib":peak(0),"sampled_temperature_peak_c":peak(2),"sampled_power_peak_w":peak(3),"sampled_sm_clock_peak_mhz":peak(4),"sampled_process_rss_peak_mib":max(s["process_rss_bytes"] for s,v in samples)/1024**2})
    if not all_rows:
        raise RuntimeError("No completed measurements: refusing to generate illustrative results")
    summary=[]
    for key,rows in sorted(groups.items()):
        good=[r for r in rows if r["success"]]
        assert good, key
        values=[r["ttft_ms"] for r in good]
        trials=defaultdict(list)
        for r in good:
            trials[r["trial"]].append(r["ttft_ms"])
        medians=[statistics.median(v) for v in trials.values()]
        entry=dict(zip(["suite","workload","concurrency","mode","host_cache_mib","kv","context"],key))
        entry.update(n=len(rows),failures=len(rows)-len(good),trials=len(trials),median_ms=statistics.median(values),p95_ms=percentile(values,.95),median_queue_ms=statistics.median(r["queue_ms"] for r in good),median_schedule_us=1000*statistics.median(r["schedule_ms"] for r in good),trial_median_min=min(medians),trial_median_max=max(medians),probe_passes=sum(r["probe_pass"] for r in good))
        entry["mean_ms"]=statistics.mean(values)
        for field in ["reused_prompt_tokens","evaluated_prompt_tokens","prefill_ms","decode_ms","decode_tokens_per_second"]:
            available=[r[field] for r in good if isinstance(r.get(field),(int,float))]
            entry["median_"+field]=statistics.median(available) if available else None
            entry["mean_"+field]=statistics.mean(available) if available else None
        summary.append(entry)
    (destination/"summary.json").write_text(json.dumps(summary,indent=2)+"\n",encoding="utf-8")
    failure_rows=[{k:r.get(k) for k in ["source","suite","workload","trial","mode","host_cache_mib","concurrency","phase","request_id","error","total_ms"]} for r in all_rows if not r["success"]]
    # Include warmup failures too; all_rows intentionally contains measured rows only.
    for item in files:
        for row in [json.loads(line) for line in (ROOT/item["path"]).read_text(encoding="utf-8").splitlines()[1:]]:
            if row["phase"]=="warmup" and not row["success"]:
                row.update(source=item["path"],suite=pathlib.Path(item["path"]).parent.name.split("-t")[0])
                failure_rows.append({k:row.get(k) for k in ["source","suite","workload","trial","mode","host_cache_mib","concurrency","phase","request_id","error","total_ms"]})
    (destination/"failures.json").write_text(json.dumps(failure_rows,indent=2)+"\n",encoding="utf-8")
    with (destination/"summary.csv").open("w",newline="",encoding="utf-8") as output:
        writer=csv.DictWriter(output,fieldnames=summary[0].keys())
        writer.writeheader()
        writer.writerows(summary)
    comparisons=[]
    for key,custom in groups.items():
        suite,workload,concurrency,mode,cache,kv,context=key
        if mode!="custom":
            continue
        stock=groups.get((suite,workload,concurrency,"stock",cache,kv,context),[])
        if not stock:
            continue
        paired=[]
        clean_pairs=[]
        failed_trials=[]
        for trial in sorted(set(r["trial"] for r in custom)):
            a=[r["ttft_ms"] for r in stock if r["trial"]==trial and r["success"]]
            b=[r["ttft_ms"] for r in custom if r["trial"]==trial and r["success"]]
            if a and b:
                paired.append((statistics.median(a),statistics.median(b)))
                if any(not r["success"] for r in stock+custom if r["trial"]==trial):
                    failed_trials.append(trial)
                else:
                    clean_pairs.append(paired[-1])
        relative=100*(1-statistics.median(b for a,b in paired)/statistics.median(a for a,b in paired))
        interval=None
        if len(paired)>=5:
            rng=random.Random(42)
            draws=[]
            for _ in range(5000):
                sampled=rng.choices(paired,k=len(paired))
                draws.append(100*(1-statistics.median(b for a,b in sampled)/statistics.median(a for a,b in sampled)))
            interval=[percentile(draws,.025),percentile(draws,.975)]
        sensitivity=None if not clean_pairs else 100*(1-statistics.median(b for a,b in clean_pairs)/statistics.median(a for a,b in clean_pairs))
        comparisons.append({"suite":suite,"workload":workload,"concurrency":concurrency,"host_cache_mib":cache,"kv":kv,"context":context,"paired_trials":len(paired),"change_percent_positive_is_faster":relative,"bootstrap_95_percent_interval":interval,"excluded_failure_trials_for_sensitivity":failed_trials,"failure_free_paired_trials":len(clean_pairs),"failure_free_change_percent_positive_is_faster":sensitivity,"method":"paired-trial bootstrap of ratio of medians; exploratory, five blocks, no multiplicity correction"})
        comparisons[-1]["stock_median_of_trial_medians_ms"]=statistics.median(a for a,b in paired)
        comparisons[-1]["custom_median_of_trial_medians_ms"]=statistics.median(b for a,b in paired)
    (destination/"comparisons.json").write_text(json.dumps(comparisons,indent=2)+"\n",encoding="utf-8")
    (destination/"sources.json").write_text(json.dumps(files,indent=2)+"\n",encoding="utf-8")
    (destination/"resources.json").write_text(json.dumps(resources,indent=2)+"\n",encoding="utf-8")
    precision_pairs=defaultdict(dict)
    for row in all_rows:
        if row["suite"]=="secondary" and row["success"]:
            key=(row["workload"],row["mode"],row["context"],row["trial"],row["request_id"])
            precision_pairs[key][row["kv"]]=row["output_tokens"]
    precision_groups={}
    for key,pair in precision_pairs.items():
        if "f16" in pair and "q8_0" in pair:
            group=key[:3]
            entry=precision_groups.setdefault(group,{"workload":group[0],"mode":group[1],"context":group[2],"pairs":0,"exact_first_output_token_matches":0})
            entry["pairs"]+=1
            entry["exact_first_output_token_matches"]+=pair["f16"]==pair["q8_0"]
    (destination/"kv-output-comparisons.json").write_text(json.dumps(list(precision_groups.values()),indent=2)+"\n",encoding="utf-8")
    # A token-count consistency check catches counter misinterpretation.
    for row in all_rows:
        if row["success"] and row.get("reused_prompt_tokens") is not None and row.get("evaluated_prompt_tokens") is not None:
            assert row["reused_prompt_tokens"]+row["evaluated_prompt_tokens"]==row["input_tokens"], row
    plt.rcParams.update({"font.family":"DejaVu Sans","font.size":11,"axes.spines.top":False,"axes.spines.right":False,"figure.facecolor":"white"})
    suites=sorted(set(r["suite"] for r in summary if r["suite"]!="correctness"))
    singles=[r for r in summary if r["suite"]=="full" and r["workload"].startswith("single-") and r["concurrency"]==1]
    if singles:
        fig,axis=plt.subplots(figsize=(8.5,5),layout="constrained")
        for mode,cache,marker in [("uncached",0,"o"),("stock",8192,"s"),("custom",8192,"^")]:
            points=sorted((int(r["workload"].split("-")[1]),r["median_ms"]) for r in singles if r["mode"]==mode and r["host_cache_mib"]==cache)
            if points:
                axis.plot([a for a,b in points],[b for a,b in points],marker=marker,color=COLORS[mode],label=f"{mode} (host {cache} MiB)")
        axis.set_xticks([512,2048,4096])
        axis.set_xlabel("Input tokens")
        axis.set_ylabel("Median time to first visible output (ms)")
        axis.set_ylim(bottom=0)
        axis.set_title("Repeated conversation: cached versus uncached")
        axis.legend(frameon=False)
        axis.grid(axis="y",alpha=.15)
        fig.savefig(destination/"cached-vs-uncached.png",dpi=170)
        plt.close(fig)
    for suite in suites:
        for concurrency in sorted(set(r["concurrency"] for r in summary if r["suite"]==suite)):
            for cache in [8192,0]:
                selected=[r for r in summary if r["suite"]==suite and r["concurrency"]==concurrency and r["host_cache_mib"]==cache and r["kv"]=="f16" and r["context"]==12288]
                if not selected:
                    continue
                order=["single-512","single-2048","single-4096","rotation-2048","skewed-2048","mixed-2048"]
                names=sorted(set(r["workload"] for r in selected),key=lambda name:order.index(name))
                fig,axes=plt.subplots(1,2,figsize=(13,5.5),layout="constrained")
                for axis,metric,title in zip(axes,["median_ms","p95_ms"],["Median","P95"]):
                    modes=["uncached","stock","custom"] if cache==0 else ["stock","custom"]
                    width=.72/len(modes)
                    for index,mode in enumerate(modes):
                        values=[]
                        for name in names:
                            match=next((r for r in selected if r["mode"]==mode and r["workload"]==name),None)
                            values.append(float("nan") if match is None else match[metric])
                        positions=[i+(index-(len(modes)-1)/2)*width for i in range(len(names))]
                        bars=axis.bar(positions,values,width,color=COLORS[mode],label=mode,hatch="//" if mode=="custom" else None)
                        if metric=="median_ms":
                            ranges=[next((r for r in selected if r["mode"]==mode and r["workload"]==name),None) for name in names]
                            low=[max(0,r["median_ms"]-r["trial_median_min"]) if r else 0 for r in ranges]
                            high=[max(0,r["trial_median_max"]-r["median_ms"]) if r else 0 for r in ranges]
                            axis.errorbar(positions,values,yerr=[low,high],fmt="none",ecolor="#252525",capsize=3,linewidth=1)
                            # Put labels above the whisker caps; the first render
                            # showed vertical error bars crossing numeric labels.
                            for position,value,upper in zip(positions,values,high):
                                axis.annotate(f"{value:.1f}",(position,value+upper),xytext=(0,3),textcoords="offset points",ha="center",fontsize=8)
                        else:
                            axis.bar_label(bars,fmt="%.1f",padding=3,fontsize=8)
                    axis.set_xticks(range(len(names)),[n.replace("-","\n") for n in names])
                    axis.set_ylabel("Time to first visible output (ms)")
                    axis.set_title(title)
                    axis.set_ylim(bottom=0)
                    axis.grid(axis="y",alpha=.15)
                    axis.set_axisbelow(True)
                # Reserve a blank top band so the legend cannot cover marks or
                # the numeric labels above the trial-range whiskers.
                axes[0].set_ylim(top=axes[0].get_ylim()[1]*1.25)
                axes[0].legend(frameon=False,loc="upper right")
                counts=sorted(set(r["n"] for r in selected))
                trials=sorted(set(r["trials"] for r in selected))
                fig.suptitle(f"{suite.capitalize()} · {concurrency} client(s) · host cache {cache} MiB\n{','.join(map(str,counts))} attempts/arm; {','.join(map(str,trials))} trial(s); TTFT on successes\nMedian whiskers = trial range; failure counts in report",fontsize=11)
                fig.savefig(destination/f"{suite}-c{concurrency}-ram{cache}.png",dpi=170)
                plt.close(fig)
    lines=["# Measured results","","Generated from completed raw runs only. Median and P95 pool measured requests; trial ranges show block variation.","","| Suite | Workload | Clients | Policy | Host MiB | Trials | n | Median ms | P95 ms | Failures |","|---|---|---:|---|---:|---:|---:|---:|---:|---:|"]
    for r in summary:
        lines.append(f"| {r['suite']} | {r['workload']} | {r['concurrency']} | {r['mode']} | {r['host_cache_mib']} | {r['trials']} | {r['n']} | {r['median_ms']:.2f} | {r['p95_ms']:.2f} | {r['failures']} |")
    (destination/"RESULTS.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
    print(f"Analyzed {len(all_rows)} measured requests across {len(files)} completed runs")

if __name__=="__main__":
    main()
