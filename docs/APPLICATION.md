# Loci application material

## Short project paragraph

I investigated conversation-cache scheduling on an 8 GB RTX 4070 Laptop GPU with Qwen2.5-3B and llama.cpp. I built a Rust scheduler and streaming benchmark covering 200 experiment arms and 12,000 measured request attempts. Stock caching reduced repeated 2,048-token median TTFT from 285.5 ms to 18.3 ms. The custom heuristic's mixed-length paired change was -0.6% (positive means faster; exploratory 95% interval [-0.9, +2.2]%), with regressions under concurrency. I audited reuse counters against engine logs, compared factual and greedy outputs, captured a separate Nsight Systems trace, and measured KV-precision memory tradeoffs. The analysis retains transport failures and documents a collection-data gap. This project taught me to profile existing runtime behavior before adding scheduling complexity.

## Resume bullet

Built a Rust conversation-cache scheduler and reproducible CUDA inference benchmark; evaluated 12k request attempts across 200 experiment arms, with stock-cache baselines, P95 latency, cache-counter audits, output checks, and Nsight profiling.

## Interview walkthrough

1. **Problem:** Long histories make prefill expensive, even when the latest user message is short. More conversations than slots can cause repeated work.
2. **Baseline:** llama.cpp already offers prefix matching, LRU fallback, and RAM prompt caching. The comparison preserves those features before testing a constrained host-cache-disabled case.
3. **Change:** Keep prefix matching; change miss eviction using cached token count times recent conversation frequency. Use leases and FIFO admission to handle concurrent requests safely.
4. **Evidence:** Explain the uncached-to-stock change (285.5 to 18.3 ms), then separately explain the custom-versus-stock mixed result (-0.6%). Show the complete matrix and a P95 regression rather than quoting the best cell alone.
5. **Correctness:** Describe the unreliable original probe, the uncached diagnostic, the revised fixture, exact-token differences, and the remaining baseline factual miss.
6. **Limits:** Synthetic traces, one GPU/model, five blocks, short replies, background activity, and no evidence of mobile or battery benefits. Point to the next measurement that would change a deployment choice.

7. **Reliability:** The retained matrix contains 4 failed measured requests and 1 failed warmup request; TTFT statistics condition on success. Explain the whole-arm restart, the lost original raw file, the preserved second-attempt errors, and the archival fix. Do not describe the collection as failure-free.

Application files are drafts for review. Replace a local repository reference with a published URL only after reviewing and publishing the repository.
