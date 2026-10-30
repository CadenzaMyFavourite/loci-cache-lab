# Concurrent routing regression: evidence and limits

The original Rust scheduler makes a binding slot choice too early for concurrent llama.cpp inference. An idle slot at Rust admission need not be the best idle slot when the engine processes the HTTP task. Explicit `id_slot` prevents the engine from reconsidering that choice. This causes avoidable recomputation in observed traces and changes which requests wait behind a cold prefill. The frequency-weighted eviction formula is not required to reproduce the regression.

The safe routing correction delegates concurrent slot choice to llama.cpp (`id_slot = -1`) while retaining FIFO admission. It keeps the original custom mode available for reproduction and its sequential prefix policy available in corrected mode. This removes premature binding by construction, but fresh validation does **not** establish consistent P95 recovery. It is an opt-in fallback to existing engine behavior, not a new speedup over stock. Stock remains the recommended concurrent baseline.

## What the ablation establishes

The complete clean ablation is in [`phase2/ablation-clean`](../DATA_ARCHIVE.md). All four arms use the same seeded request inputs, two outstanding requests and eight generated tokens. A has native routing without a semaphore; B adds the original fair semaphore; C pins slots using prefix matching plus LRU; D is the original prefix/frequency policy. **Phase 1 stock corresponds to B.**

At host cache 0 MiB, the median of five trial medians was A 50.57 ms, B 55.57 ms, C 302.36 ms and D 300.77 ms. C and D evaluated exactly the same input-token totals in every paired trial. At 8,192 MiB, B was 57.70 ms, C 82.17 ms and D 75.57 ms. Both explicit policies increased tail latency. See the [full ablation and validation tables](concurrency-ablation.md), including uncertainty and failures.

FIFO waiting cannot explain this closed-loop regression: B's median queue wait is below one microsecond. There are only two outstanding jobs and two admission permits. The Rust prefix/retention decision also costs microseconds, not hundreds of milliseconds. This does not establish that FIFO is irrelevant under an open-loop burst or higher concurrency.

## A concrete missed-prefix and queueing chain

Separate verbose logs expose the mechanism. These runs are diagnostic because logging itself perturbs timing. Request/task correlation is inferred from per-slot launch order, then validated against **all generated token IDs and evaluated-token counts**. Ambiguous runs are rejected. Client and engine clocks are related only through a feasible offset interval, not assumed synchronized.

In `phase2/ablation/ablation-t0-custom-ram0-v5-default-delay0`:

| Event | Engine monotonic ms | Evidence |
|---|---:|---|
| Request 10, conversation B, posted | 3,142.126 | Native task 59 posted to engine queue |
| Other slot 1 releases its previous B task | 3,156.191 | Native release log |
| Pinned slot 0 selected for task 59 | 3,156.206 | Explicit selection log |
| Task 59 starts | 3,156.483 | Native launch log |
| Request 11, also B, posted | 3,158.886 | Native task 61 posted |
| Task 59 produces its first token | 3,446.420 | Native sampled-token log |
| Task 61 can start in slot 1 | 3,446.728 | Native launch log |

Request 10 reused **4** tokens and evaluated **2,044**. The now-idle other slot had a **2,034-token** matching prefix, reconstructed from its prior prompt plus generated tokens excluding the last sampled token. Clock bounds establish that the other slot became idle **after** Rust reserved slot 0. Its availability was therefore impossible for that dispatch-time decision to use. Native automatic routing checks the live idle slots at this later selection point; a pinned request cannot select the other slot.

Request 11 reused **2,034** tokens and evaluated only **14**, yet its visible TTFT was **326.07 ms**. Its native POST-to-launch interval was **287.84 ms**; its own prompt timing was **36.636 ms**. Its completion task was declined while decode was running. The cold prefill from request 10 is on its observed critical path. A high cache-hit count did not make request 11 fast.

Across the five verbose no-host-cache D trials, the same conservative reconstruction finds **27 measured requests** with an idle alternative prefix more than 1,000 tokens longer than actual reuse. In all 27, that alternative became idle after Rust's reservation. These are routing opportunities, not estimates of alternate-run latency. Cache contents and future overlap would change after any different decision. The detector only makes this claim without host caching, where RAM restoration cannot change the reconstructed residency.

Reproduce the extraction with:

```powershell
.venv\Scripts\python.exe scripts/concurrency_analyze.py --source phase2/ablation --out phase2/analysis-verbose
```

Per-run counts, clock bounds and request identities are in [`analysis-verbose/runs.json`](../DATA_ARCHIVE.md). Validated request/log maps and raw decline events are in `phase2/analysis-verbose/correlated.jsonl`.

## Why equal token totals can have different TTFT

The clean trial 0 with host caching disabled has **57,653 evaluated tokens** in both A and D, with 32 warm requests each. Their medians are **176.13 ms** and **296.75 ms**. The original Phase 1 exploratory example likewise had equal totals with a larger median difference. Neither observation isolates eviction as a cause.

Token totals discard ordering and overlap. A cached request can wait before launch for someone else's prefill, or share a decode/prefill batch after launch. Different choices also change when the next closed-loop request is dispatched. The distributions have a fast cached group and a slow prefill group; a few requests crossing the middle can greatly change the median. The P95 and mean must be inspected alongside it.

## Findings for each hypothesis

| Hypothesis | Finding |
|---|---|
| FIFO admission | Negligible direct queue duration in this workload; removing the semaphore does not remove the explicit-routing regression. |
| External reservation lifetime | Rust retains its lease through stream EOF. The engine often releases earlier. RAM-cache verbose trials show reservations excluding an already-idle engine slot; late release gaps are usually milliseconds. These gaps exist, but do not directly explain a 300 ms delay. More decisively, slots become idle **after dispatch and before engine selection**, when an early release alone would not fix the binding choice. |
| Engine-managed vs explicit assignment | The C/D comparison with B reproduces the problem. Source and reconstructed histories show specific lost native prefix-selection opportunities. |
| Frequency-weighted eviction | Replacing it with LRU does not cure the regression; no-host-cache C/D evaluated totals are identical in every clean trial. This does not establish that the heuristic can never matter on another workload. |
| Continuous batching | Native decode-gate events and the request 10→11 chain show server-side blocking and overlap. `prompt_ms` is wall time around prompt processing, not isolated CUDA kernel duration. |
| Host cache/internal state | Default RAM caching remains enabled in the main comparison. Native save/load and idle-slot saving have costs beyond evaluated-token totals. They amplify some tails but cannot be the sole cause: the regression persists with host caching disabled. |
| Client/transport | Direct dispatch, headers, SSE/content and EOF events distinguish waits. In correlated verbose runs, client HTTP TTFT minus engine POST-to-first-token is generally only a few milliseconds. The 287.84 ms queue interval above is inside the engine. Separate legacy replays retained connection failures; those are not counted as zero-latency successes. |

## Source-level checks

The inspected source is llama.cpp **b11960**, commit `8642541b255bfb5dc39cd351a178be09013a55d6`, retained under ignored `vendor/source/server-context.cpp`:

- `get_available_slot` honors explicit `task.id_slot`, restricting prefix comparison to that slot. Automatic routing searches currently idle slots by longest prefix, then LRU, with the stock similarity threshold.
- `process_single_task` declines completion tasks during yielding encode/decode and offers them again after decode finishes. This is distinct from `queue_tasks.defer` for unavailable slots.
- Once an idle slot is chosen, the engine may save/load RAM prompt state, then launch the request and save other idle slots when configured. This is not client scheduling time.
- An explicitly busy slot would be deferred. The inspected verbose cohort has **zero unavailable-slot defer events**, so this is not evidence of a double-reservation bug.

Native `requests_deferred` is an instantaneous endpoint gauge; its final zero does not prove there was no internal delay. Log counts of `decoding, decline task` include internal task types; the analysis separately counts only declines matching correlated completion-task IDs. No claim is based on treating all those lines as user requests.

## What remains uncertain

The ablation establishes an explicit-routing regression and observed mechanisms, not a complete counterfactual decomposition of every millisecond in Phase 1. Detailed logs perturb execution, kernel scheduling was not isolated, and a fixed synthetic trace is sensitive to request overlap and background GPU load. The exact original ratio did not reproduce in every frozen-binary replay. The report retains both successful and unsuccessful reproductions.

No Nsight capture was needed to justify the safe fallback: client timestamps, native queue/launch/token logs and source already expose the relevant queueing and binding behavior. Attributing the remaining variance to a particular CUDA synchronization primitive would require a separate trace experiment.
