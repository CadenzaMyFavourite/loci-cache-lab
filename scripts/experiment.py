"""Reset the engine per trial; capture launch manifests, logs and telemetry.

Run with .venv/Scripts/python.exe scripts/experiment.py --suite full
All server processes owned by this script are stopped in finally blocks.
"""
import argparse
import contextlib
import datetime
import json
import hashlib
import pathlib
import shutil
import subprocess
import threading
import time
import urllib.request

import psutil

ROOT = pathlib.Path(__file__).resolve().parents[1]
BIN = ROOT / "target/release/loci-cache-lab.exe"
SERVER = ROOT / "vendor/b11960/llama-server.exe"
MODEL = ROOT / "models/qwen2.5-3b-instruct-q4_k_m.gguf"
URL = "http://127.0.0.1:8087"

def api(path, body=None):
    request = urllib.request.Request(URL + path, data=None if body is None else json.dumps(body).encode(), headers={"Content-Type":"application/json"})
    with urllib.request.urlopen(request, timeout=180) as response:
        return json.load(response)

def run(command, **kwargs):
    return subprocess.run([str(x) for x in command], cwd=ROOT, check=True, **kwargs)

def telemetry(process, path, stop):
    query = ["nvidia-smi", "--query-gpu=memory.used,memory.free,temperature.gpu,power.draw,clocks.sm,clocks.mem,utilization.gpu", "--format=csv,noheader,nounits"]
    with path.open("w",encoding="utf-8") as destination:
        while not stop.is_set():
            try:
                sample = subprocess.check_output(query, text=True, creationflags=subprocess.CREATE_NO_WINDOW).strip()
                info = psutil.Process(process.pid).memory_info()
                row = {"unix_ms":time.time()*1000,"gpu_csv":sample,"process_rss_bytes":info.rss,"available_ram_bytes":psutil.virtual_memory().available}
                destination.write(json.dumps(row)+"\n")
                destination.flush()
            except (OSError, subprocess.SubprocessError, psutil.Error) as error:
                destination.write(json.dumps({"error":str(error)})+"\n")
            stop.wait(1)

@contextlib.contextmanager
def server(folder, host_cache=8192, kv="f16", context=12288, extra_args=()):
    folder.mkdir(parents=True, exist_ok=True)
    run([BIN,"check","--min-free-mib","3584"],stdout=subprocess.DEVNULL)
    # Never attach to an unrelated existing inference server.
    try:
        api("/health")
    except Exception:
        pass
    else:
        raise RuntimeError("Port 8087 already serves a model; stop it explicitly before this experiment")
    args = [SERVER,"-m",MODEL,"--host","127.0.0.1","--port","8087","-ngl","all","-np","2","-c",str(context),"--no-kv-unified","--no-context-shift","--fit","off","--cache-type-k",kv,"--cache-type-v",kv,"--flash-attn","on","--cache-ram",str(host_cache),"--metrics","--slots","--perf","--log-timestamps"]
    args.extend(extra_args)
    manifest = {"schema_version":1,"started_utc":datetime.datetime.now(datetime.timezone.utc).isoformat(),"args":[str(x) for x in args],"hardware":{"cpu":__import__('platform').processor(),"ram_bytes":psutil.virtual_memory().total,"gpu":subprocess.check_output(["nvidia-smi","--query-gpu=name,memory.total,memory.free,driver_version","--format=csv"],text=True)},"artifacts":json.loads((ROOT/"environment/artifacts.json").read_text())}
    (folder/"launch.json").write_text(json.dumps(manifest,indent=2),encoding="utf-8")
    log = (folder/"server.log").open("w",encoding="utf-8")
    process = subprocess.Popen([str(x) for x in args],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
    stop = threading.Event()
    sampler = threading.Thread(target=telemetry,args=(process,folder/"telemetry.jsonl",stop),daemon=True)
    sampler.start()
    try:
        deadline=time.monotonic()+180
        while time.monotonic()<deadline:
            if process.poll() is not None:
                raise RuntimeError(f"Engine exited {process.returncode}; inspect {folder/'server.log'}")
            try:
                if api("/health").get("status")=="ok":
                    break
            except Exception:
                time.sleep(0.5)
        else:
            raise RuntimeError("Engine readiness timed out")
        slots=api("/slots")
        assert len(slots)==2 and min(s["n_ctx"] for s in slots)>=context//2, slots
        yield process
    finally:
        stop.set()
        sampler.join(timeout=5)
        process.terminate()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        log.close()

def request_args(workload, mode, path, trial, concurrency, host_cache, kv, context, predict=32, correctness=False):
    args=[BIN,"run","--workload",workload,"--mode",mode,"--out",path,"--trial",str(trial),"--concurrency",str(concurrency),"--host-cache-mib",str(host_cache),"--kv",kv,"--context",str(context),"--predict",str(predict)]
    if correctness:
        args.append("--correctness")
    return args

def calibrate(folder, workloads="workloads"):
    """Independent cold process per size, followed by same-prompt warm requests."""
    rows=[]
    for size in [512,2048,4096]:
        with server(folder/f"calibration-{size}"):
            fixture=json.loads((ROOT/f"{workloads}/seed-42/single-{size}.json").read_text())
            prompt=fixture["requests"][0]["tokens"]
            for i in range(12):
                result=api("/completion",{"prompt":prompt,"n_predict":1,"temperature":0,"cache_prompt":True,"id_slot":0})
                rows.append({"input_tokens":size,"phase":"cold" if i==0 else "warm","index":i,"response":result})
    (folder/"calibration.json").write_text(json.dumps(rows,indent=2),encoding="utf-8")

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--suite",choices=["prepare","smoke","full","secondary","correctness","calibrate"],default="smoke")
    parser.add_argument("--trials",type=int,default=5)
    parser.add_argument("--requests",type=int,default=60)
    parser.add_argument("--predict",type=int,default=8,help="Timing-run decode length; correctness always permits 32 tokens")
    parser.add_argument("--out",default="results")
    parser.add_argument("--workloads",default="workloads",help="Separate fixture root for independent collections")
    args=parser.parse_args()
    folder=ROOT/args.out
    folder.mkdir(parents=True,exist_ok=True)
    if args.suite=="prepare":
        with server(folder/"preparation"):
            for trial in range(args.trials):
                run([BIN,"prepare","--out",f"{args.workloads}/seed-{42+trial}","--seed",str(42+trial),"--requests",str(args.requests)])
        return
    if args.suite=="calibrate":
        calibrate(folder,args.workloads)
        return
    modes=[("uncached",0),("stock",8192),("custom",8192),("stock",0),("custom",0)]
    workloads=["single-512","single-2048","single-4096","rotation-2048","skewed-2048","mixed-2048"]
    if args.suite=="smoke":
        workloads=["rotation-2048"]
    if args.suite=="correctness":
        workloads=["rotation-2048","mixed-2048"]
    if args.suite=="secondary":
        workloads=["single-4096","rotation-2048"]
    settings=[("f16",12288)] if args.suite!="secondary" else [("f16",9216),("q8_0",9216),("f16",16384),("q8_0",16384)]
    for trial in range(args.trials):
        for kv,context in settings:
            for workload in workloads:
                concurrencies=[1,2] if workload in ["rotation-2048","skewed-2048"] and args.suite=="full" else [1]
                for concurrency in concurrencies:
                    # Rotate arm order between trials, preserving the same fixtures.
                    arms=modes[trial%len(modes):]+modes[:trial%len(modes)]
                    if args.suite=="secondary":
                        arms=[("stock",8192),("custom",8192)]
                    for mode,cache in arms:
                        name=f"{args.suite}-t{trial}-{workload}-c{concurrency}-{mode}-ram{cache}-{kv}-ctx{context}"
                        destination=folder/name
                        workload_path=ROOT/f"{args.workloads}/seed-{42+trial}/{workload}.json"
                        if (destination/"complete.json").exists():
                            previous=json.loads((destination/"inputs.json").read_text(encoding="utf-8"))
                            expected_predict=32 if args.suite=="correctness" else args.predict
                            if previous["predict"]!=expected_predict or previous["fixture_sha256"]!=hashlib.sha256(workload_path.read_bytes()).hexdigest() or previous["executable_sha256"]!=hashlib.sha256(BIN.read_bytes()).hexdigest():
                                raise RuntimeError(f"Completed arm {name} used different inputs/executable; use a new --out directory")
                            print("skip",name,flush=True)
                            continue
                        if destination.exists():
                            archive=folder/"failed-attempts"/(name+"-"+datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))
                            archive.parent.mkdir(parents=True,exist_ok=True)
                            shutil.copytree(destination,archive)
                            print("archived incomplete attempt",archive,flush=True)
                            # Prevent a preflight failure from being mistaken for
                            # the previous attempt's complete request file.
                            previous_requests=destination/"requests.jsonl"
                            if previous_requests.exists():
                                previous_requests.unlink()
                        if not workload_path.exists():
                            raise RuntimeError("Prepare all trial seeds first")
                        destination.mkdir(parents=True,exist_ok=True)
                        (destination/"inputs.json").write_text(json.dumps({"fixture":str(workload_path.relative_to(ROOT)),"fixture_sha256":hashlib.sha256(workload_path.read_bytes()).hexdigest(),"executable_sha256":hashlib.sha256(BIN.read_bytes()).hexdigest(),"predict":32 if args.suite=="correctness" else args.predict},indent=2),encoding="utf-8")
                        with server(destination,cache,kv,context):
                            command=request_args(workload_path,mode,destination/"requests.jsonl",trial,concurrency,cache,kv,context,predict=32 if args.suite=="correctness" else args.predict,correctness=args.suite=="correctness")
                            result=subprocess.run([str(x) for x in command],cwd=ROOT)
                            records=[json.loads(line) for line in (destination/"requests.jsonl").read_text(encoding="utf-8").splitlines()[1:]] if (destination/"requests.jsonl").exists() else []
                            expected=json.loads(workload_path.read_text(encoding="utf-8"))["requests"]
                            if len(records)!=len(expected) or {r["request_id"] for r in records}!={r["id"] for r in expected}:
                                raise RuntimeError(f"Run aborted before recording every request; exit {result.returncode}, inspect {destination}")
                            failures=sum(not r["success"] for r in records)
                            if result.returncode!=0 and failures==0:
                                raise RuntimeError(f"Unexpected client exit {result.returncode}; inspect {destination}")
                        (destination/"complete.json").write_text(json.dumps({"schema_version":1,"completed":True,"request_failures":failures,"note":"Every planned request is recorded. Failures remain in the dataset; latency summaries condition on successful responses."}),encoding="utf-8")
                        print("complete",name,flush=True)

if __name__=="__main__":
    main()
