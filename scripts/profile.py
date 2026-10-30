"""Capture a separate Nsight trace; never mix profiled latency with benchmark data."""
import hashlib
import json
import subprocess
import time
import argparse
from experiment import ROOT, SERVER, MODEL, api, run

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--out",default="results/profile")
    parser.add_argument("--workloads",default="workloads")
    options=parser.parse_args()
    candidates=list((ROOT/"vendor/nsight").rglob("target-windows-x64/nsys.exe"))
    if not candidates:
        raise RuntimeError("Download/extract the official Nsight Systems portable Windows archive into vendor/nsight. See docs/PROFILING.md")
    nsys=candidates[0]
    folder=ROOT/options.out
    folder.mkdir(parents=True,exist_ok=True)
    run([ROOT/"target/release/loci-cache-lab.exe","check"],stdout=subprocess.DEVNULL)
    args=[nsys,"profile","--trace=cuda,nvtx","--sample=none","--cpuctxsw=none","--duration=25","--kill=true","--force-overwrite=true",f"--output={folder/'cold-warm'}",SERVER,"-m",MODEL,"--host","127.0.0.1","--port","8087","-ngl","all","-np","2","-c","12288","--no-kv-unified","--no-context-shift","--fit","off","--flash-attn","on","--cache-ram","8192","--slots","--perf"]
    manifest={"args":[str(x) for x in args],"nsys_version":subprocess.check_output([str(nsys),"--version"],text=True),"nsys_exe_sha256":hashlib.sha256(nsys.read_bytes()).hexdigest()}
    (folder/"launch.json").write_text(json.dumps(manifest,indent=2),encoding="utf-8")
    rows=[]
    with (folder/"profile.log").open("w",encoding="utf-8") as log:
        process=subprocess.Popen([str(x) for x in args],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            deadline=time.monotonic()+20
            while time.monotonic()<deadline:
                if process.poll() is not None:
                    raise RuntimeError("Profiler exited before server readiness; inspect profile.log")
                try:
                    if api("/health").get("status")=="ok":
                        break
                except Exception:
                    time.sleep(.25)
            else:
                raise RuntimeError("Profiled server readiness timed out")
            fixture=json.loads((ROOT/f"{options.workloads}/seed-42/single-2048.json").read_text(encoding="utf-8"))
            for i in range(12):
                result=api("/completion",{"prompt":fixture["requests"][0]["tokens"],"n_predict":8,"temperature":0,"cache_prompt":True,"id_slot":0})
                rows.append({"index":i,"phase":"cold" if i==0 else "warm","response":result})
            process.wait(timeout=90)
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=10)
    (folder/"requests.json").write_text(json.dumps(rows,indent=2),encoding="utf-8")
    report=folder/"cold-warm.nsys-rep"
    if not report.exists():
        raise RuntimeError("Nsight report missing; inspect profile.log")
    with (folder/"stats.txt").open("w",encoding="utf-8") as output:
        run([nsys,"stats","--report","cuda_gpu_kern_sum,cuda_gpu_mem_time_sum,cuda_api_sum",report],stdout=output,stderr=subprocess.STDOUT)
    print(report)

if __name__=="__main__":
    main()
