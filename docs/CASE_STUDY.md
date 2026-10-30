# Conversation caching: an engineering case study

## Question and initial hypothesis

Could Rust keep expensive, frequently requested conversation prefixes resident and reduce TTFT beyond llama.cpp's native cache? The experiment uses one RTX 4070 Laptop GPU, one Qwen2.5-3B-Instruct Q4_K_M model and two inference slots. Fixed synthetic histories let every policy receive identical token arrays without feeding generated text into future requests.

## Baseline first

The repeated 2,048-token control measured 285.5 ms uncached and 18.3 ms with stock caching. That improvement belongs to the existing engine. The Rust heuristic retains native longest-prefix preference, then changes miss eviction to cached-token count times frequency in the previous 32 admissions. The engine owns KV validity and computation.

## The first optimization failed under concurrency

In the clean constrained ablation, stock plus FIFO had a median of trial medians of 55.57 ms, explicit prefix/LRU 302.36 ms, and the original custom policy 300.77 ms. Their pooled P95 values were 336.22/584.46/588.74 ms. Five paired trials of 60 requests per arm produced no failures. Removing frequency weighting did not remove the regression, and direct FIFO/routing costs were microseconds.

Rust's live-slot metadata lags engine availability. More importantly, a slot can become idle *after* Rust commits but *before* the engine handles the request. Explicit `id_slot` prevents reconsideration. In the [recorded trace](../evidence/early-binding.json), another slot becomes idle with a 2,034-token match, yet the pinned request reuses four tokens and evaluates 2,044. A following request reuses 2,034 tokens but waits 287.84 ms from native POST to launch behind that work.

Task correlation uses inferred per-slot order and checks exact generated tokens/evaluation counts. The alternate prefix is reconstructed availability evidence. It is not a measured alternate-run latency or proof of the sole cause of every Phase 1 delay. Native POST-to-launch also includes preparation/cache work and is not exact network acceptance.

## A safe fallback needs independent validation

Corrected concurrent mode retains the fair semaphore and sends `id_slot = -1`, letting llama.cpp consider live state at admission. It keeps the sequential custom policy at concurrency 1. Under two clients, the fallback and stock FIFO share inference semantics. Tests compare effective HTTP requests, events, state and cancellation; 2,640 live paired bodies agree.

Twenty paired fixed-arrival trials per cache setting retain request readiness, queue admission, dispatch and first visible content separately. With no host cache, P95 changes +1.84%, with an all-trial interval of −0.24% to +8.75%. Failure-free sensitivity widens to −1.08% to +19.26%. With default host caching, the P95 point ranking flips after sample expansion and remains uncertain. Five measured connection closures and one warmup failure remain in the evidence.

The result establishes equivalent routing semantics and a volatile empirical tail, not a distinct faster corrected algorithm. The precise physical source of residual P95 variation remains unresolved. Actual timer wakeups differ from planned arrivals, native batching changes overlap, and laptop/transport variation remain possible contributors. The reports do not assign a CUDA or HTTP cause without evidence.

## Quantizing KV exposes a different tradeoff

Four selected cases span total contexts 9,216/16,384, inputs 2,048/4,096 and outputs 32/128. Crossing both precisions and routing labels gives 80 arms with five paired trials per cell. q8_0 lowers native KV buffers from 324 to 172.15 MiB and 576 to 306.03 MiB, about 46.9%. The model buffer stays unchanged.

All eight paired per-stream decode-rate point estimates are 3.34–5.70% lower with q8_0; some intervals include improvements. TTFT is mixed. One-second system GPU maxima are separate from native allocation and can miss peaks. This selected matrix is not a full factorial or a near-capacity test.

All 120 selected EOS factual probes pass. Fixed-length token sequences and cold top-eight log probabilities differ across precision; some same-precision controls differ too. These observations are not a universal accuracy guarantee or automatic evidence of cache corruption. See [the precision report](kv-cache-precision.md).

## What remains valuable to test

- Randomized trial blocks and tighter arrival fidelity to estimate the default-cache tail more precisely.
- An isolated transport experiment for connection closure before headers, retaining all failures.
- Controlled engine states and numerical probes to explain residual output disagreements.
- Representative workload traces and a specific GPU synchronization/copy hypothesis before collecting new Nsight timing.

The practical default remains stock routing for concurrent work. The contribution is the Rust implementation, validation harness and defensible failure investigation. No new CUDA kernel, production deployment or universal speedup is claimed.

Evidence: [request records](../evidence/requests.jsonl), [source/hash index](../evidence/index.json), [Phase 2](../PHASE2_REPORT.md), [Phase 3](../PHASE3_REPORT.md), [editable deck](../presentations/engineering-case-study.pptx).
