"""Small Windows inference smoke demo. Never changes historical evidence."""
import argparse
import contextlib
import datetime
import hashlib
import json
import pathlib
import socket
import subprocess
import time
import urllib.request
import zipfile

ROOT=pathlib.Path(__file__).resolve().parents[1]
URL='http://127.0.0.1:8087'
MODEL='qwen2.5-3b-instruct-q4_k_m.gguf'
MODEL_SHA='626b4a6678b86442240e33df819e00132d3ba7dddfe1cdc4fbb18e0a9615c62d'

def sha(path):
    with path.open('rb') as source:return hashlib.file_digest(source,'sha256').hexdigest()

def api(path):
    with urllib.request.urlopen(URL+path,timeout=10) as response:return json.load(response)

def paths(args):
    return pathlib.Path(args.assets_root).resolve(),pathlib.Path(args.bin_dir).resolve()

def check(args):
    assets,bins=paths(args)
    required=[assets/'vendor/b11960/llama-server.exe',assets/'models'/MODEL,bins/'loci-cache-lab.exe',bins/'concurrency.exe']
    for p in required:
        if not p.is_file():raise RuntimeError(f'Missing {p.name}; see README setup/build commands')
    if sha(required[1])!=MODEL_SHA:raise RuntimeError('Model checksum differs from the pinned model')
    archive=assets/'downloads/llama-b11960-bin-win-cuda-12.4-x64.zip'
    # Verify the executable against the pinned upstream archive when available.
    binary_verified=False
    if archive.exists():
        expected='8d9d819261de10cc2f03921b8b79c779c5c458e21edb60c170ee30a7d462d684'
        if sha(archive)!=expected:raise RuntimeError('Engine archive checksum mismatch')
        with zipfile.ZipFile(archive) as z:
            name=next(n for n in z.namelist() if n.replace('\\','/').endswith('llama-server.exe'))
            if hashlib.sha256(z.read(name)).hexdigest()!=sha(required[0]):raise RuntimeError('Server differs from pinned archive')
        binary_verified=True
    else:
        raise RuntimeError('Pinned engine archive missing; run scripts/setup.py to verify the engine')
    runtime_archive=assets/'downloads/cudart-llama-bin-win-cuda-12.4-x64.zip'
    if not runtime_archive.exists() or sha(runtime_archive)!='8c79a9b226de4b3cacfd1f83d24f962d0773be79f1e7b75c6af4ded7e32ae1d6':
        raise RuntimeError('Pinned CUDA runtime archive missing or checksum mismatch')
    dll_count=0
    for archive_path in [archive,runtime_archive]:
        with zipfile.ZipFile(archive_path) as z:
            for name in z.namelist():
                if not name.lower().endswith('.dll'):continue
                deployed=assets/'vendor/b11960'/name.replace('\\','/').split('/')[-1]
                if not deployed.exists() or hashlib.sha256(z.read(name)).hexdigest()!=sha(deployed):
                    raise RuntimeError('Deployed DLL differs from its pinned archive: '+deployed.name)
                dll_count+=1
    subprocess.run([str(bins/'loci-cache-lab.exe'),'check','--min-free-mib','3584'],cwd=ROOT,check=True)
    result={'model_sha256':MODEL_SHA,'server_sha256':sha(required[0]),'server_verified_against_pinned_archive':binary_verified,
        'client_sha256':sha(bins/'concurrency.exe'),'verified_dll_entries':dll_count,'engine':'b11960','context':12288,'slots':2,'kv':'f16','predict':8}
    print('Environment verified: pinned model/engine; at least 3584 MiB free VRAM.',flush=True)
    return result

@contextlib.contextmanager
def server(args,folder):
    assets,bins=paths(args)
    if folder.exists():raise RuntimeError('Server evidence destination already exists')
    with socket.socket() as sock:
        if sock.connect_ex(('127.0.0.1',8087))==0:raise RuntimeError('Port 8087 is already in use; refusing to attach or stop another server')
    subprocess.run([str(bins/'loci-cache-lab.exe'),'check','--min-free-mib','3584'],cwd=ROOT,stdout=subprocess.DEVNULL,check=True)
    folder.mkdir(parents=True)
    command=[str(assets/'vendor/b11960/llama-server.exe'),'-m',str(assets/'models'/MODEL),
        '--host','127.0.0.1','--port','8087','-ngl','all','-np','2','-c','12288','--no-kv-unified',
        '--no-context-shift','--fit','off','--cache-type-k','f16','--cache-type-v','f16','--flash-attn','on',
        '--cache-ram',str(args.cache_mib),'--metrics','--slots','--perf','--log-timestamps','-lv','3','--batch-size','2048']
    manifest={'schema_version':1,'started_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'args':command,
        'model_sha256':MODEL_SHA,'server_sha256':sha(assets/'vendor/b11960/llama-server.exe'),
        'gpu':subprocess.check_output(['nvidia-smi','--query-gpu=name,memory.total,memory.free,driver_version','--format=csv'],text=True)}
    (folder/'launch.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    log=(folder/'server.log').open('x',encoding='utf-8')
    process=subprocess.Popen(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        deadline=time.monotonic()+180
        while time.monotonic()<deadline:
            if process.poll() is not None:raise RuntimeError(f'Server exited {process.returncode}; inspect server.log')
            try:
                if api('/health').get('status')=='ok':break
            except (OSError,ValueError):pass
            time.sleep(.25)
        else:raise RuntimeError('Server readiness timed out')
        slots=api('/slots')
        if len(slots)!=2 or min(s['n_ctx'] for s in slots)!=6144:raise RuntimeError('Unexpected slot capacity; configuration was not accepted')
        yield
    finally:
        process.terminate()
        try:process.wait(timeout=15)
        except subprocess.TimeoutExpired:process.kill();process.wait()
        log.close()

def prepare(args,out):
    _,bins=paths(args)
    if out.exists():raise RuntimeError('Refusing to overwrite fixtures')
    subprocess.run([str(bins/'loci-cache-lab.exe'),'prepare','--out',str(out),'--requests',str(args.requests),'--seed','42'],cwd=ROOT,check=True,stdout=subprocess.DEVNULL)

def run_arm(args,arm,fixture,out):
    _,bins=paths(args)
    if out.exists():raise RuntimeError('Refusing to overwrite request evidence')
    route={'stock':'fifo','custom':'custom','corrected':'corrected'}[arm]
    command=[str(bins/'concurrency.exe'),'--workload',str(fixture),'--out',str(out),'--arm',route,
        '--requests',str(args.requests),'--host-cache-mib',str(args.cache_mib)]
    completed=subprocess.run(command,cwd=ROOT)
    if completed.returncode:raise RuntimeError(f'Client failed with exit {completed.returncode}; retained partial evidence')
    rows=[json.loads(s) for s in out.read_text(encoding='utf-8').splitlines()[1:]]
    if len(rows)!=args.requests+6:raise RuntimeError('Incomplete request coverage')
    return rows

def summarize(rows):
    import numpy as np
    measured=[r for r in rows if r['phase']=='measured'];good=[r for r in measured if r['success']]
    values=[r['ttft_ms'] for r in good]
    return {'attempts':len(measured),'failures':len(measured)-len(good),'warmup_failures':sum(not r['success'] for r in rows if r['phase']=='warmup'),
        'median_ttft_ms':float(np.median(values)) if values else None,'p95_ttft_ms':float(np.quantile(values,.95)) if values else None,
        'evaluated_tokens':sum(r['timings']['prompt_n'] for r in good),'reused_tokens':sum(r['timings']['cache_n'] for r in good)}

def chart(folder):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    report=json.loads((folder/'summary.json').read_text(encoding='utf-8'))
    arms=list(report['arms']);fig,ax=plt.subplots(figsize=(8.5,4.6))
    for i,arm in enumerate(arms):
        r=report['arms'][arm]
        if r['median_ttft_ms'] is not None:
            ax.scatter(i,r['median_ttft_ms'],s=70,color=['#2671aa','#c54646','#7653a3'][i],label='Median' if i==0 else None)
            ax.scatter(i,r['p95_ttft_ms'],s=65,marker='^',facecolors='none',edgecolors='#555',label='P95' if i==0 else None)
    ax.set_xticks(range(len(arms)),[f"{a}\n{report['arms'][a]['failures']} measured failures" for a in arms])
    ax.set_ylabel('Ready to first visible output (ms)');ax.set_ylim(bottom=0);ax.grid(axis='y',alpha=.2);ax.legend()
    ax.set_title('Mini-demo: one descriptive smoke trial')
    fig.text(.5,.015,f"{report['requests']} measured requests per mode + 6 warmups; 2 clients; 8 output tokens. No speedup inference.",ha='center',fontsize=9)
    fig.tight_layout(rect=[0,.05,1,1]);fig.savefig(folder/'comparison.png',dpi=160);plt.close(fig)
    print('Chart:',folder/'comparison.png')

def compare(args):
    start=time.monotonic();out=pathlib.Path(args.out).resolve()
    if out.exists():raise RuntimeError('Choose a fresh --out directory')
    identity=check(args);out.mkdir(parents=True)
    (out/'identity.json').write_text(json.dumps(identity,indent=2),encoding='utf-8')
    with server(args,out/'preparation'):prepare(args,out/'workloads')
    fixture=out/'workloads/skewed-2048.json';summaries={}
    for arm in ['stock','custom','corrected']:
        folder=out/arm
        with server(args,folder):rows=run_arm(args,arm,fixture,folder/'requests.jsonl')
        summaries[arm]=summarize(rows)
    result={'schema_version':1,'purpose':'small smoke demonstration; not repeated research evidence',
        'requests':args.requests,'concurrency':2,'output_tokens':8,'cache_mib':args.cache_mib,
        'fixture_sha256':sha(fixture),'arms':summaries,'elapsed_seconds':time.monotonic()-start}
    (out/'summary.json').write_text(json.dumps(result,indent=2),encoding='utf-8');chart(out)
    print(json.dumps(result,indent=2))
    if any(r['failures'] or r['warmup_failures'] for r in summaries.values()):
        raise RuntimeError('Demo contains failed requests; summary and traces retained, with no retries')

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('command',choices=['check','server','prepare','run','compare','chart'])
    p.add_argument('--assets-root',default=str(ROOT));p.add_argument('--bin-dir',default=str(ROOT/'target/release'))
    p.add_argument('--out',default='runs/demo-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d-%H%M%S'))
    p.add_argument('--requests',type=int,default=12);p.add_argument('--cache-mib',type=int,choices=[0,8192],default=8192)
    p.add_argument('--arm',choices=['stock','custom','corrected'],default='stock');p.add_argument('--workload')
    a=p.parse_args()
    if not 1<=a.requests<=60:p.error('--requests must be between 1 and 60')
    out=pathlib.Path(a.out).resolve()
    if a.command=='check':check(a)
    elif a.command=='chart':chart(out)
    elif a.command=='compare':compare(a)
    elif a.command=='prepare':prepare(a,out)
    elif a.command=='run':
        if not a.workload:p.error('--workload is required for run')
        rows=run_arm(a,a.arm,pathlib.Path(a.workload).resolve(),out);result=summarize(rows);print(json.dumps(result,indent=2))
        if result['failures'] or result['warmup_failures']:raise RuntimeError('Failed requests retained in the output')
    else:
        check(a)
        with server(a,out):
            print('Server ready on '+URL+'; Ctrl+C stops only this owned process.',flush=True)
            try:
                while True:time.sleep(.5)
            except KeyboardInterrupt:pass

if __name__=='__main__':main()
