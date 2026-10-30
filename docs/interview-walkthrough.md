# Interview walkthrough

## A two-minute explanation

“I studied when a Rust conversation scheduler helps a local model serving three conversations with two GPU inference slots. I first established the existing cache baseline: the repeated 2,048-token control went from 285.5 ms uncached to 18.3 ms with stock llama.cpp caching. That gain belongs to llama.cpp.

“My Rust policy retained longest-prefix routing and changed eviction using cached tokens times recent conversation frequency. Concurrent tests exposed a regression. Instrumentation showed FIFO wait was tiny. The important decision was *when* a slot was chosen: Rust committed before HTTP dispatch, while native routing could consider a matching slot that became idle before engine admission. A traced request recomputed about 2,000 tokens unnecessarily, then blocked a nearly cached request.

“I added a concurrent fallback to native routing. Its HTTP requests and admission behavior match stock, so an independently observed P95 difference is not evidence of a different scheduling algorithm. I tested fixed offered arrivals, separated queueing from HTTP latency, and resampled paired trial blocks. I report uncertain tails and output differences alongside successful measurements. I would choose stock for concurrent work without stronger evidence for extra scheduling complexity.”

Use the current numerical tail and precision tables in the [Phase 3 report](../PHASE3_REPORT.md), not a remembered best trial.

## Explain the inference path

- **Prefill** processes input tokens and creates attention key/value state. A reused prefix reduces evaluated input work.
- **Decode** generates output tokens using that state. Native per-stream decode timings can include interference from other requests.
- **KV caching** retains intermediate computation, not a previously generated answer. The engine validates token reuse. Rust metadata only hints at routing.
- **Slots** hold live inference/KV state. The native RAM prompt cache can save and restore histories displaced from GPU slots. Preserving it in the main comparison avoids weakening stock artificially.
- **Continuous batching** changes overlap: a cached request can wait behind another request's prefill. Equal total evaluated-token counts need not imply equal latency distributions.

## Defend the scheduling policy

The policy uses token-level longest common prefixes above the native 10% threshold. On a miss it chooses an empty slot or the smallest `known_cached_tokens × frequency_in_previous_32_admissions`. Ties use least recent admission then slot ID. The score is a heuristic proxy for retention value, not a proven cost model or future-request oracle. The 32-admission window bounds memory and adapts to activity changes.

An owned semaphore permit bounds concurrency and gives queued admissions FIFO order. Explicit reservations remain busy until completion; cancellation/errors invalidate uncertain metadata. Scope changes and process restart discard hints. Releasing a lease early without authoritative engine state would require a new correctness argument. The concurrent fallback avoids that need by giving native routing the slot choice.

The original `custom` implementation stays available for reproduction. Corrected mode is custom at concurrency 1 and native routing at concurrency greater than 1. Under two-client concurrency, `fifo` and `corrected` have the same inference semantics; adding the corrected label does not create a new native optimization.

## Defend the measurements

| Quantity | Meaning and limitation |
|---|---|
| Scheduled TTFT | Predetermined arrival to first nonempty output; includes producer lateness and queueing |
| Ready TTFT | Actual prepared-request readiness to first output; includes client FIFO wait |
| HTTP TTFT | Dispatch to first output; includes transport, engine waiting, prefill and streaming |
| Client queue | Actual ready to FIFO permit admission |
| Engine POST→launch | Direct native log interval, including engine waiting and preparation; not exact network acceptance |
| Cache/evaluation counters | Native `cache_n` and `prompt_n`, checked against input length and full-arm metrics |
| Peak GPU usage | Sampled system-wide maximum, not an exact or exclusive allocation peak |

Fixed offered arrivals are independent of completions; actual dispatch still depends on permits. This exposes overload/queueing rather than pretending every scheduled request reaches the GPU immediately. Disk traces are buffered outside measured dispatch progression. An interrupted client could lose buffered rows; complete arms are checked for every planned request and no timed failure is retried.

Percentiles are not additive. P95(queue) plus P95(HTTP) is not P95(total). The median of per-trial P95 values differs from pooled P95. In Phase 2, 13 versus 17 requests above 500 ms out of 300 crossed the pooled 95th-percentile cutoff and produced a large ratio. Always show tail counts and uncertainty beside that ratio.

Requests within a trial share cache state, thermals and arrival history. Bootstrap entire paired trial blocks, not independent requests. Fresh server processes reset cache state, but do not reset the physical laptop or background OS activity. Alternating arm order helps with drift; it does not prove absence of confounding. An interval containing zero does not prove equivalence. The practical equivalence criterion and sample cap are declared before interpretation.

## Explain precision results without overclaiming

The independent study pairs f16/q8_0 KV precision within four selected context/input/output cases, with five trials per routing/precision cell. It spans every requested level but is not the full factorial. Native KV allocation is measured separately from sampled GPU usage. A smaller fixed buffer is an allocation saving; throughput and TTFT need their own evidence.

Quantized KV can introduce numerical error and conversion work. Cold top-eight pre-sampling log probabilities, greedy token sequences and separate EOS-enabled factual probes are retained. Top-eight overlap is not a full-vocabulary KL divergence or perplexity measure. Same-precision label controls help contextualize output variation. A wrong answer or mismatch alone does not prove cache corruption; neither does the absence of another conversation's code establish perfect correctness.

## Limitations and next work

One GPU, one 3B quantized model, fixed slot partitions and synthetic traces constrain generalization. Eight-token primary timing and 32/128-token precision timing answer different questions. Context allocation changes do not prove operation near VRAM capacity. No universal q8_0 or Rust speedup is assumed.

A next experiment would use representative arrival distributions and independent randomized blocks, investigate unresolved numerical disagreements with authoritative engine-level state checks, and profile a specific remaining synchronization hypothesis. It would preserve the same stock baseline and error accounting. Explain which finding motivates that experiment before proposing more infrastructure.
