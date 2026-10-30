"""Inspect the prespecified surprising first-trial concurrent regression."""
import json
import pathlib
import statistics
import argparse
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT=pathlib.Path(__file__).resolve().parents[1]

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--results",default="results")
    parser.add_argument("--out",default="analysis")
    options=parser.parse_args()
    destination=ROOT/options.out
    destination.mkdir(parents=True,exist_ok=True)
    rows={}
    for mode in ["stock","custom"]:
        path=ROOT/f"{options.results}/full-t0-skewed-2048-c2-{mode}-ram0-f16-ctx12288/requests.jsonl"
        assert (path.parent/"complete.json").exists()
        rows[mode]=sorted([r for r in map(json.loads,path.read_text(encoding="utf-8").splitlines()[1:]) if r["phase"]=="measured"],key=lambda r:r["request_id"])
    facts={}
    colors={"stock":"#295D96","custom":"#B06C10"}
    fig,axes=plt.subplots(2,1,figsize=(11,7),layout="constrained",sharex=True)
    for mode,records in rows.items():
        hits=[r for r in records if r["reused_prompt_tokens"]>1000]
        misses=[r for r in records if r["reused_prompt_tokens"]<=1000]
        facts[mode]={"requests":len(records),"median_ms":statistics.median(r["ttft_ms"] for r in records),"mean_ms":statistics.mean(r["ttft_ms"] for r in records),"total_evaluated_tokens":sum(r["evaluated_prompt_tokens"] for r in records),"prefix_hits_over_1000_tokens":len(hits),"ttft_under_100_ms":sum(r["ttft_ms"]<100 for r in records),"hit_median_ms":statistics.median(r["ttft_ms"] for r in hits),"miss_median_ms":statistics.median(r["ttft_ms"] for r in misses)}
        axes[0].plot([r["request_id"] for r in records],[r["ttft_ms"] for r in records],marker="o" if mode=="stock" else "^",markersize=4,linewidth=1,color=colors[mode],label=mode)
        axes[1].step([r["request_id"] for r in records],[r["evaluated_prompt_tokens"] for r in records],where="mid",linewidth=1.2,color=colors[mode],linestyle="-" if mode=="stock" else "--",label=mode)
    facts["different_evaluation_counts_by_request"]=sum(a["evaluated_prompt_tokens"]!=b["evaluated_prompt_tokens"] for a,b in zip(rows["stock"],rows["custom"]))
    facts["scope"]="Exploratory diagnostic of trial 0 only; not an independent replication or proof of mechanism"
    (destination/"concurrent-diagnostic.json").write_text(json.dumps(facts,indent=2),encoding="utf-8")
    axes[0].set_ylabel("TTFT (ms)")
    axes[1].set_ylabel("Evaluated input tokens")
    axes[1].set_xlabel("Scripted request index (warmup excluded)")
    for axis in axes:
        axis.set_ylim(bottom=0)
        axis.grid(axis="y",alpha=.15)
        axis.spines[["top","right"]].set_visible(False)
    axes[0].legend(frameon=False)
    fig.suptitle("Concurrent skewed workload · host cache disabled · trial 0\nCache hits and fast visible responses are different measurements",fontsize=12)
    fig.savefig(destination/"concurrent-diagnostic.png",dpi=170)
    plt.close(fig)
    print(json.dumps(facts,indent=2))

if __name__=="__main__":
    main()
