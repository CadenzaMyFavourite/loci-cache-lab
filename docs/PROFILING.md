# Profiling separately from headline latency

The project uses NVIDIA's portable Nsight Systems 2026.3.2.476 Windows archive. It needs no MSI installation. Download from the [official redistribution directory](https://developer.download.nvidia.com/compute/cuda/redist/nsight_systems/windows-x86_64/), extract under `vendor/nsight`, and retain NVIDIA's license files. SHA256 and the profiler version are recorded with the capture.

```powershell
python scripts/setup_profiler.py
.\.venv\Scripts\python.exe scripts/profile.py
```

This captures CUDA and NVTX activity during a cold 2,048-token request followed by repeated warm requests. CPU sampling and CPU context-switch tracing are disabled. The profiler stops its own inference process after 25 seconds; do not run another experiment simultaneously. Inspect `results/profile/profile.log` for collection warnings before interpreting `stats.txt` or the `.nsys-rep` trace.

Open the trace in Nsight Systems to compare the first prefill with later warm-prefill spans. Inspect kernel durations, memory transfers, and CUDA API synchronization. Kernel names alone do not prove a bottleneck: match a time range to the corresponding request and distinguish startup allocations from steady-state inference. The summary includes model loading and is not a per-request breakdown. Profiled times are excluded from all benchmark figures.

If tracing is unavailable because of device permissions or driver/tool incompatibility, preserve the error log and label profiling unavailable. Server timing counters alone cannot establish kernel-level causes.
