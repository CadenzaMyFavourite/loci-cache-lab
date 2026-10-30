"""Phase 2 only: reuse server lifecycle, model, fixtures and telemetry from Phase 1."""
import argparse
import datetime
import hashlib
import json
import pathlib
import subprocess
import time
import urllib.request
from experiment import ROOT, server, URL

BIN=ROOT/"target/release/concurrency.exe"

def metrics():
    before=time.time_ns()
    with urllib.request.urlopen(URL+"/metrics",timeout=30) as response:
        body=response.read().decode()
    return {"before_unix_ns":before,"after_unix_ns":time.time_ns(),"text":body}

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--suite",choices=["diagnostic","ablation","validation","correctness"],required=True)
    parser.add_argument("--trials",type=int,default=5)
    parser.add_argument("--requests",type=int,default=60)
    parser.add_argument("--verbosity",type=int,default=3)
    parser.add_argument("--snapshots",action="store_true")
    parser.add_argument("--progress",action="store_true")
    parser.add_argument("--transport",choices=["default","fresh"],default="default")
    parser.add_argument("--release-delay-ms",type=int,default=0)
    parser.add_argument("--arms",nargs="+",default=None)
    parser.add_argument("--cache",nargs="+",type=int,default=[8192,0])
    parser.add_argument("--out",default="phase2/results")
    parser.add_argument("--batch-size",type=int,default=2048)
    parser.add_argument("--seed-start",type=int,default=42)
    parser.add_argument("--workloads",default="workloads")
    args=parser.parse_args()
    arms=args.arms or (["stock","fifo","custom","corrected"] if args.suite=="validation" else ["stock","fifo","lru","custom"])
    for trial in range(args.trials):
        fixture=ROOT/f"{args.workloads}/seed-{args.seed_start+trial}/skewed-2048.json"
        assert fixture.exists(),fixture
        for cache in args.cache:
            ordered=arms[trial%len(arms):]+arms[:trial%len(arms)]
            for arm in ordered:
                name=f"{args.suite}-t{trial}-{arm}-ram{cache}-v{args.verbosity}-{args.transport}-delay{args.release_delay_ms}"
                if args.batch_size!=2048:name+=f"-batch{args.batch_size}"
                folder=ROOT/args.out/name
                signature={"fixture_sha256":hashlib.sha256(fixture.read_bytes()).hexdigest(),"binary_sha256":hashlib.sha256(BIN.read_bytes()).hexdigest(),"fixture":str(fixture.relative_to(ROOT)),"options":vars(args),"arm":arm,"trial":trial,"cache":cache}
                if (folder/"complete.json").exists():
                    previous=json.loads((folder/"input.json").read_text(encoding='utf-8'))
                    def comparable(value):
                        value=json.loads(json.dumps(value))
                        for key,default in [('batch_size',2048),('seed_start',42),('workloads','workloads')]:
                            if value['options'].get(key,default)==default:value['options'].pop(key,None)
                        return value
                    if comparable(previous)!=comparable(signature):
                        raise RuntimeError(f"Refusing to mix inputs in {folder}")
                    continue
                if folder.exists():
                    raise RuntimeError(f"Incomplete attempt preserved in {folder}; choose a new --out directory")
                folder.mkdir(parents=True)
                (folder/"input.json").write_text(json.dumps(signature,indent=2),encoding="utf-8")
                with server(folder,cache,extra_args=["-lv",str(args.verbosity),"--batch-size",str(args.batch_size)]):
                    before=metrics()
                    command=[str(BIN),"--workload",str(fixture),"--out",str(folder/"requests.jsonl"),"--arm",arm,"--trial",str(trial),"--host-cache-mib",str(cache),"--requests",str(args.requests),"--transport",args.transport,"--release-delay-ms",str(args.release_delay_ms)]
                    if args.suite=="correctness":command.append("--correctness")
                    if args.progress:command.append("--progress")
                    if args.snapshots:command.append("--snapshots")
                    subprocess.run(command,cwd=ROOT,check=True)
                    after=metrics()
                    (folder/"metrics.json").write_text(json.dumps({"before":before,"after":after},indent=2),encoding="utf-8")
                rows=[json.loads(line) for line in (folder/"requests.jsonl").read_text(encoding="utf-8").splitlines()[1:]]
                assert len(rows)==args.requests+6 and len({r['request_id'] for r in rows})==len(rows)
                (folder/"complete.json").write_text(json.dumps({"attempts":len(rows),"failures":sum(not r['success'] for r in rows),"completed_utc":datetime.datetime.now(datetime.timezone.utc).isoformat()}),encoding="utf-8")
                print("COMPLETE",name,flush=True)

if __name__=="__main__":main()
