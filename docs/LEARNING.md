# Understand and defend the project

## Checkpoint 1: where the time goes

**Prefill** processes the input prompt and creates the model's intermediate attention state. **Decode** generates additional tokens one at a time. **TTFT** includes the time before the first visible output, so a prefill reduction may help TTFT even when decode speed stays unchanged.

Explain aloud: why can a 2,000-token conversation followed by a five-token message be expensive even though the new message is short?

## Checkpoint 2: what a KV cache stores

The cache stores attention keys and values, not a completed answer. An identical token prefix can reuse those intermediate computations. Changing an early system instruction invalidates the following prefix. A semantically similar paraphrase is not the same token sequence.

An approximate KV memory formula is `2 × layers × cached_tokens × KV_heads × head_dimension × bytes_per_value`; the first 2 accounts for keys and values. Runtime alignment and other buffers add overhead. Quantized model weights and KV precision are separate choices: Q4 weights do not mean the KV cache also uses four bits per value.

Explain aloud: why do we compare token IDs rather than conversation names or text character prefixes?

## Checkpoint 3: what Rust contributes

`Scheduler` owns metadata about the two slots. The shared `Mutex` protects a brief state update; it is released before network I/O. A `Semaphore` limits admitted requests. A `Lease` invalidates uncertain state in `Drop`, including when an async future is cancelled. Each successful request replaces its slot metadata with a conservative known token sequence.

Explain aloud: why would holding the scheduler lock while awaiting HTTP prevent useful concurrency?

## Checkpoint 4: what makes the baseline fair

llama.cpp already implements prefix matching, LRU fallback, and host-RAM prompt caching. Comparing against caching disabled only demonstrates that caching helps. The main question compares custom scheduling against the existing caching features under the same resource budget.

Explain aloud: why does preserving a third conversation in host RAM change the expected value of a custom GPU-slot eviction policy?

## Checkpoint 5: what the experiment cannot prove

A lower median on one trace does not establish better performance everywhere. P95 can worsen. Preallocated KV memory can stay the same size even when the cache retains more useful tokens. Desktop results do not establish phone performance or battery benefits. Numerical differences can arise from batching even with greedy sampling.

Explain aloud: what evidence would make you reject your own optimization?

## Checkpoint 6: useful next research

After reading the measured report, locate a policy decision where custom and stock differ. Inspect the saved request, server log, cached/evaluated-token counters, and timing. Explain whether the change saved prefill, introduced a transfer, changed queueing, or merely coincided with clock variation. If the data cannot distinguish those mechanisms, state that clearly.
