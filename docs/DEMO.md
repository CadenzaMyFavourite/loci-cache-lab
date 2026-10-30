# Mini-demo

The live demo checks the existing implementation on a small fixed workload. It does not reproduce the full study or guarantee a particular race/interleaving. The historical failure is inspectable separately in [early-binding.json](../evidence/early-binding.json).

## One command

From the repository root with the pinned assets, a built Rust package and installed Python requirements:

```powershell
.\demo.ps1
```

Default: 12 measured requests and six warmups per mode, two clients, eight output tokens, 2,048-token skewed histories, f16 KV, context 12,288 and host cache 8,192 MiB. The script validates checksums and memory, prepares fresh native-tokenizer fixtures, resets the engine between stock/custom/corrected, retains raw records, and creates `summary.json` and `comparison.png` in a new `runs/demo-*` directory. It refuses existing output directories and does not retry failed requests. A failed request makes the command fail after saving the summary/chart.

The release check used an empty Rust target directory and an isolated source copy. Its smoke run took 25.03 seconds with zero failures across 36 measured and 18 warmup requests. Observed TTFT differences in that sample are descriptive only. All three modes evaluated 2,190 measured input tokens and reused 22,386 each.

## Separate commands

Use fresh directory names each time. An already-running server is intentionally refused by automatic compare mode.

```powershell
# Validate hardware, pinned model/engine archives and deployed DLLs
.\.venv\Scripts\python.exe scripts/demo.py check

# Terminal 1: owned server, stopped by Ctrl+C
.\.venv\Scripts\python.exe scripts/demo.py server --out runs/manual-server

# Terminal 2: prepare native-template/tokenizer fixtures against that server
.\.venv\Scripts\python.exe scripts/demo.py prepare --out runs/manual-workloads
.\.venv\Scripts\python.exe scripts/demo.py run --arm stock --workload runs/manual-workloads/skewed-2048.json --out runs/manual-stock.jsonl
```

For fair policy comparison, stop that server and use the automatic three-arm reset:

```powershell
.\.venv\Scripts\python.exe scripts/demo.py compare --out runs/manual-comparison
.\.venv\Scripts\python.exe scripts/demo.py chart --out runs/manual-comparison
```

`--cache-mib 0` selects the separately labeled constrained configuration. `--assets-root` can reuse model/binaries in another checkout; `--bin-dir` can select a fresh Rust build. Paths are arguments, not machine-specific source constants. Recorded fixture scopes use the actual server identity. Do not send location-normalized historical fixtures back to a server as if they were newly prepared inputs.

Saved-evidence chart, no GPU:

```powershell
.\.venv\Scripts\python.exe scripts/plot_evidence.py --out runs/evidence-example.png
```

This reads the retained five-trial Phase 2 request records. Its pooled median differs from the original report's median of trial medians; the figure labels the estimand explicitly.

## Inspect the result

Check failures before latency, then confirm native `cache_n + prompt_n == input_tokens`. Compare evaluated/reused work with TTFT and queueing. Do not use a single smoke trial to rank equivalent routes. If setup fails, inspect free VRAM, port 8087, model checksum and slot capacity rather than change context, cache precision or offload automatically.

The [recording storyboard](RECORDING_GUIDE.md) pairs the live smoke run with the recorded failure. No screen recording or video is included.
