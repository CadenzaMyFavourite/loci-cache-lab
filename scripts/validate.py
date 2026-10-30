"""Audit completed runs and exercise live capacity/scope failures separately."""
import argparse
from collections import Counter
import hashlib
import json
import pathlib
import re
import subprocess
import numpy as np
from experiment import ROOT, BIN, api, request_args, server

RESULTS=ROOT/"results"
ANALYSIS=ROOT/"analysis"
WORKLOADS=ROOT/"workloads"

def audit():
    findings={"completed_runs":0,"requests":0,"counter_consistency":0,"log_counter_matches":0,"factual_probes":{},"greedy_comparisons":{},"fixture_hash_matches":0}
    findings["full_custom_routing_predictions"]={}
    calibration_path=RESULTS/"calibration.json"
    if calibration_path.exists():
        calibration=json.loads(calibration_path.read_text(encoding="utf-8"))
        for sample in calibration:
            timing=sample["response"]["timings"]
            size=sample["input_tokens"]
            assert timing["cache_n"]+timing["prompt_n"]==size
            assert timing["prompt_n"]==(size if sample["phase"]=="cold" else 1)
            assert timing["cache_n"]==(0 if sample["phase"]=="cold" else size-1)
        findings["calibrated_cold_warm_requests"]=len(calibration)
    full_executable_hashes=set()
    baseline={}
    compare=[]
    for path in sorted(RESULTS.rglob("requests.jsonl")):
        if "failed-attempts" in path.relative_to(RESULTS).parts:
            continue
        if not (path.parent/"complete.json").exists():
            continue
        rows=[json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        meta=rows.pop(0)
        findings["completed_runs"]+=1
        findings["requests"]+=len(rows)
        findings.setdefault("request_failures",0)
        findings["request_failures"]+=sum(not r["success"] for r in rows)
        for row in rows:
            if not row["success"]:
                continue
            assert row["reused_prompt_tokens"]+row["evaluated_prompt_tokens"]==row["input_tokens"],path
            assert row["server_final"]["truncated"] is False,path
            findings["counter_consistency"]+=1
            if path.parent.name.startswith("full-") and row["mode"]=="custom" and row["phase"]=="measured":
                item=findings["full_custom_routing_predictions"].setdefault(str(row["host_cache_mib"]),{"requests":0,"engine_reuse_above_prediction":0,"engine_reuse_below_prediction":0})
                item["requests"]+=1
                predicted=row["decision"]["predicted_prefix_tokens"]
                item["engine_reuse_above_prediction"]+=row["reused_prompt_tokens"]>predicted
                item["engine_reuse_below_prediction"]+=row["reused_prompt_tokens"]<predicted
        log=(path.parent/"server.log").read_text(encoding="utf-8",errors="replace")
        log_counts=[int(x) for x in re.findall(r"prompt eval time\s*=\s*[\d.]+ ms /\s*(\d+) tokens",log)]
        successful=[r for r in rows if r["success"]]
        assert Counter(log_counts)==Counter(r["evaluated_prompt_tokens"] for r in successful),(path,len(log_counts),len(successful))
        findings["log_counter_matches"]+=len(successful)
        inputs=path.parent/"inputs.json"
        if inputs.exists():
            manifest=json.loads(inputs.read_text(encoding="utf-8"))
            actual=hashlib.sha256((ROOT/manifest["fixture"]).read_bytes()).hexdigest()
            assert actual==manifest["fixture_sha256"],path
            findings["fixture_hash_matches"]+=1
            if path.parent.name.startswith("full-"):
                full_executable_hashes.add(manifest["executable_sha256"])
        if path.parent.name.startswith("correctness-"):
            findings["factual_probes"][path.parent.name]={"total":len(rows),"factual_passes":sum(r["probe_pass"] for r in rows),"exact_format":sum(r.get("probe_exact",False) for r in rows)}
            for row in rows:
                key=(row["workload"],row["trial"],row["request_id"])
                if row["mode"]=="uncached":
                    baseline[key]=row["output_tokens"]
                else:
                    compare.append((path.parent.name,key,row["output_tokens"]))
    for name,key,tokens in compare:
        item=findings["greedy_comparisons"].setdefault(name,{"total":0,"exact_token_matches":0})
        item["total"]+=1
        item["exact_token_matches"]+=tokens==baseline[key]
    if full_executable_hashes:
        assert len(full_executable_hashes)==1,"main study mixed inference-client executables"
    findings["full_executable_sha256"]=sorted(full_executable_hashes)
    # Independent NumPy recomputation from the exact immutable source snapshot
    # used by analyze.py, so newly finishing arms cannot race this audit.
    if (ANALYSIS/"sources.json").exists():
        snapshot=json.loads((ANALYSIS/"sources.json").read_text(encoding="utf-8"))
        grouped={}
        by_trial={}
        for source in snapshot:
            path=ROOT/source["path"]
            for row in [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()[1:]]:
                if row["phase"]!="measured" or not row["success"]:
                    continue
                key=(path.parent.name.split("-t")[0],row["workload"],row["concurrency"],row["mode"],row["host_cache_mib"],row["kv"],row["context"])
                grouped.setdefault(key,[]).append(row["ttft_ms"])
                by_trial.setdefault(key+(row["trial"],),[]).append(row["ttft_ms"])
        summaries=json.loads((ANALYSIS/"summary.json").read_text(encoding="utf-8"))
        for item in summaries:
            key=tuple(item[k] for k in ["suite","workload","concurrency","mode","host_cache_mib","kv","context"])
            values=np.array(grouped[key])
            assert len(values)==item["n"]-item["failures"],key
            assert np.isclose(np.median(values),item["median_ms"],rtol=1e-12),key
            assert np.isclose(np.quantile(values,.95),item["p95_ms"],rtol=1e-12),key
            assert np.isclose(np.mean(values),item["mean_ms"],rtol=1e-12),key
        findings["independently_recomputed_summary_groups"]=len(summaries)
        comparison_path=ANALYSIS/"comparisons.json"
        if comparison_path.exists():
            comparisons=json.loads(comparison_path.read_text(encoding="utf-8"))
            for item in comparisons:
                common=(item["suite"],item["workload"],item["concurrency"])
                suffix=(item["host_cache_mib"],item["kv"],item["context"])
                stock_key=common+("stock",)+suffix
                custom_key=common+("custom",)+suffix
                trials={key[-1] for key in by_trial if key[:-1]==stock_key} & {key[-1] for key in by_trial if key[:-1]==custom_key}
                stock_center=np.median([np.median(by_trial[stock_key+(trial,)]) for trial in trials])
                custom_center=np.median([np.median(by_trial[custom_key+(trial,)]) for trial in trials])
                assert np.isclose(stock_center,item["stock_median_of_trial_medians_ms"],rtol=1e-12)
                assert np.isclose(custom_center,item["custom_median_of_trial_medians_ms"],rtol=1e-12)
                assert np.isclose(100*(1-custom_center/stock_center),item["change_percent_positive_is_faster"],rtol=1e-10,atol=1e-10)
            findings["independently_recomputed_paired_comparisons"]=len(comparisons)
    ANALYSIS.mkdir(parents=True,exist_ok=True)
    (ANALYSIS/"validation.json").write_text(json.dumps(findings,indent=2),encoding="utf-8")
    print(json.dumps(findings,indent=2))

def live_negative():
    folder=RESULTS/"negative-controls"
    fixture=json.loads((WORKLOADS/"seed-42/single-512.json").read_text(encoding="utf-8"))
    rows=[]
    with server(folder):
        for kind in ["oversized","changed_template"]:
            changed=json.loads(json.dumps(fixture))
            if kind=="oversized":
                changed["requests"][0]["tokens"]=[1]*6200
            else:
                changed["scope"]="a different model or template"
            path=folder/f"{kind}.json"
            path.write_text(json.dumps(changed),encoding="utf-8")
            result=subprocess.run([str(x) for x in request_args(path,"custom",folder/f"{kind}.jsonl",0,1,8192,"f16",12288)],cwd=ROOT,capture_output=True,text=True)
            assert result.returncode!=0,kind
            rows.append({"test":kind,"returncode":result.returncode,"stderr":result.stderr})
        # The model must follow a changed instruction rather than reuse stale text.
        for code in ["A-796","B-797"]:
            prompt=f"<|im_start|>system\nYour secret code is {code}.<|im_end|>\n<|im_start|>user\nWhat is your secret code? Reply with only the code.<|im_end|>\n<|im_start|>assistant\n"
            response=api("/completion",{"prompt":prompt,"n_predict":16,"temperature":0,"cache_prompt":True,"id_slot":0})
            (folder/f"changed-system-{code}.json").write_text(json.dumps(response,indent=2),encoding="utf-8")
            assert code in response["content"],response
            rows.append({"test":"changed_system","expected":code,"response":response})
    (folder/"checks.json").write_text(json.dumps(rows,indent=2),encoding="utf-8")
    print("Live capacity, model/template-scope, and changed-system controls passed")

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--live",action="store_true")
    parser.add_argument("--results",default="results")
    parser.add_argument("--analysis",default="analysis")
    parser.add_argument("--workloads",default="workloads")
    args=parser.parse_args()
    RESULTS=ROOT/args.results
    ANALYSIS=ROOT/args.analysis
    WORKLOADS=ROOT/args.workloads
    live_negative() if args.live else audit()
