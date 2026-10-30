# Interview question bank

Use these as prompts for reasoning, not claims of experience beyond the retained project. The [case study](CASE_STUDY.md) and [Phase 3 report](../PHASE3_REPORT.md) supply the evidence behind the answer cues.

## Rust scheduling and correctness

1. **What does the scheduler actually cache?** It stores token-prefix/routing metadata. llama.cpp owns and validates KV tensors; Rust never returns a cached answer.
2. **Why token IDs rather than string prefixes?** Token boundaries, chat templates, system prompts and model identity define the computational prefix. A text similarity score does not establish equivalent KV state.
3. **What is the eviction score?** Known cached-token count times conversation frequency in the previous 32 admissions; ties use least recent use then slot ID. It is a heuristic with no calibrated estimate of future cost.
4. **How is concurrency bounded fairly?** A Tokio semaphore bounds admitted requests; queued acquisitions are FIFO. Record readiness, queue entry, admission and dispatch separately. FIFO admission does not imply equal engine completion times.
5. **What happens when a task is cancelled?** Owned permits and leases must release on drop. Invalidate uncertain routing hints rather than mark an incomplete response as a known prefix. Existing tests exercise cancellation and permit return.
6. **Why avoid holding a mutex across network awaits?** It can serialize unrelated requests or create cancellation hazards. Keep state mutations bounded; let the lease/permit represent ownership across streaming awaits.
7. **Why not release the slot when the first token arrives?** Decode is still using native state. Shorter external reservation alone does not make an explicitly assigned busy slot safe to reuse. A change needs a native availability contract and measurements.
8. **Is corrected routing an improved algorithm?** At two clients it sends `id_slot = -1` with stock FIFO semantics. It removes the early client commitment and delegates selection; no independent concurrent speedup is established.

## Transformers and engine behavior

9. **How do prefill and decode differ?** Prefill processes input positions and builds KV state; decode repeatedly generates one next token per live sequence. Their batching and resource behavior differ, so TTFT and decode rate are separate metrics.
10. **What is stored in a KV cache?** Per-layer attention keys and values for retained positions. Allocation depends on layers, KV heads, head dimensions, capacity and precision, with implementation overhead. Fewer evaluated tokens need not lower allocated VRAM.
11. **How does continuous batching affect this failure?** Engine state can change between HTTP submission and native task admission. Pinning a slot externally prevents the engine from considering a better slot that becomes idle in that interval.
12. **Why can a cache hit still be slow?** It can wait behind another request's prefill or engine preparation. In the trace, a request with 2,034 reused tokens waited 287.84 ms from native POST to launch.
13. **Does host caching change the conclusion?** Restoring a prefix from RAM can reduce the cost of slot eviction. The main comparison keeps it enabled; disabled-cache ablations isolate a constrained mechanism and are labeled accordingly.
14. **What did q8_0 establish?** About 46.9% less native KV allocation in two contexts. Decode-rate point estimates were lower in the selected cases and TTFT was mixed. Those are allocation and performance measurements, not a universal recommendation.

## Measurement and scientific method

15. **Where does TTFT start and end?** Ready-to-first-visible-content includes client queueing. Dispatch-to-first-content excludes that queue. Planned-arrival latency also includes producer wakeup lateness. Empty SSE events are not visible output.
16. **How were client and engine clocks correlated?** Use request/task order, native events, feasible clock offsets, evaluated/reused counts and generated tokens. Mark reconstructed matches and preparation-inclusive intervals; do not call native POST an exact HTTP acceptance timestamp.
17. **Why use predetermined arrivals?** Closed-loop dispatch depends on earlier completions and therefore treatment. Planned arrivals control offered load more directly, while actual timer lateness must still be recorded.
18. **Why does P95 need trial-level uncertainty?** Requests share cache state, temperatures and overlapping work. Resampling requests as independent observations understates dependence. Resample paired whole trials and show pooled and per-trial estimates with failure sensitivity.
19. **What would justify calling an optimization successful?** A repeatable effect versus a fair native baseline, acceptable tail behavior, no hidden failures/configuration changes, and preserved correctness. A favorable median or equal token total is insufficient.
20. **What do the output disagreements mean?** Greedy outputs can change with floating-point/batching differences; they are not automatically corruption. Separate same-precision controls, cold controls, token/log-probability differences and factual probes. Earlier wrong probe answers remain unresolved even though the selected later EOS probes all pass.
21. **How should failures enter the analysis?** Preserve them and their phase/configuration. Do not replace them with zero latency or silently retry. Quantiles describe successful requests, alongside failure rates and sensitivity analyses.

## Profiling and next steps

22. **When would Nsight help?** After a concrete hypothesis about GPU synchronization, copies or CPU launch gaps. Collect representative traces separately from headline timing and correlate them with engine events; do not infer a CUDA bottleneck from TTFT alone.
23. **What do memory samples miss?** One-second whole-system GPU samples include desktop activity and miss short peaks. Native buffer allocation is a different measurement from sampled peak residency.
24. **What would you do next?** Improve arrival fidelity and randomized trial blocking; isolate pre-header connection closures; study numerical differences under controlled engine state; then test representative workloads before generalizing to other models or devices.
25. **What should a reviewer reproduce first?** The GPU-free tests and saved-data plot, then the roughly 25-second three-arm smoke demo with existing assets. A smoke result validates execution, not the historical timing-sensitive interleaving or a new performance ranking.
