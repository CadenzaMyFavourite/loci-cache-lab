# FIFO and corrected routing under two-client concurrency

## Finding from source and tests

The two modes are semantically equivalent for native inference under the **two-client** configuration in Phase 2. There is no extra slot decision, cache control, state mutation or cancellation branch in corrected mode. This does not imply identical wall-clock execution or bitwise-identical model outputs across independent runs. Corrected mode in the original main CLI deliberately differs at concurrency 1, where it retains the custom prefix policy.

| Concern | `fifo` | `corrected`, two clients |
|---|---|---|
| Native route | `id_slot = -1` | Same |
| Cache controls | `cache_prompt = true` | Same |
| Input | Saved token array | Same paired array |
| Generation | Eight tokens, temperature 0, seed 42, EOS ignored; native streaming/token/timing flags | Same |
| Client | Reqwest, 10 s connect / 180 s request timeout, default pooling | Same |
| Admission | Fair two-permit semaphore | Same |
| Metadata lock | Read empty routing state's busy count | Same |
| Slot reservation | None | None |
| Dispatch | After permit and body construction | Same code |
| Completion | Consume terminal event and EOF, check visible content and truncation, release permit | Same code |
| Cancellation/error | Owned permit drops; no external slot lease exists to mutate | Same code |
| Backend launch | Same pinned model, two slots, f16, context/batch/offload/cache flags within each pair | Same |

`src/concurrency.rs`: `Arm::Fifo.gated()` and `Arm::Corrected.gated()` are both true; `explicit()` is false for both. In `src/bin/concurrency.rs::one`, those predicates control every routing/admission branch. Neither mode calls `Routing::reserve`, `finish` or `invalidate`. The body includes no treatment label. In `src/main.rs`, `Mode::Corrected.explicit(2)` is false, matching stock. The source is retained unchanged from Phase 2 and archived in `phase3/baseline/src`.

## Supporting checks

`tests/phase3_equivalence.rs` includes the actual preserved Phase 2 implementation, so its tests execute that request path instead of a simplified copy. An HTTP fixture captures both modes' parsed payloads, request identity/content-type headers, output tokens, ordered event names, permit counts and routing state. The mock emits an empty initial event and then content/terminal events. The captures agree. A separate cancellation test waits until dispatch, aborts each mode, and verifies permit return and no routing-state mutation.

Existing tests cover explicit-route cancellation and FIFO fairness separately. The new fixed-arrival harness tests that all planned arrivals occur while earlier streams are still waiting, that FIFO admission order is retained, and that duplicates, invalid schedules and oversized requests are rejected. Run:

```powershell
cargo test --all-targets --locked
```

Live paired Phase 3 runs additionally save the exact transmitted JSON string for every request and compare it across treatments, including failed attempts. All **2,640 paired bodies across forty trial/cache pairs** agree. The paired fixtures contain identical prompts and arrival offsets. Server launch argument arrays also agree exactly within every pair; start-time/hardware observations are not required to match. These are configuration equivalence checks, not assertions that runtime counters must match.

## Operational differences outside inference semantics

Phase 2 stores different arm names and output paths in its local JSONL. It flushes a row synchronously after a completion, then advances a two-request closed-loop window. Independent runtime interleavings, response parsing, filesystem work and completion order can therefore alter later dispatch times, even with the same routing semantics. JSONL label lengths differ; their causal contribution to the original P95 gap has not been isolated. No speculative speedup is assigned to those few bytes.

Phase 3 deliberately controls both the offered-arrival process and logging: a clock-driven producer enqueues prepared requests independently of completions, an ordered dispatcher holds at most two permits, and per-request traces use the same canonical `engine_fifo` label. Disk output is buffered until the arm ends. The requested treatment name appears only in run metadata and filenames. Thus both treatments exercise the same engine-routing function. The new harness does not claim to reproduce every scheduling detail of the earlier client.

A fixed offered arrival is distinct from a fixed dispatch. Busy requests still wait in the client FIFO, so overload can change dispatch times. The saved ready, admitted and dispatch timestamps expose this effect. Scheduled-arrival-to-content includes producer lateness; actual-ready-to-content includes queueing; dispatch-to-content excludes client admission wait. Engine POST-to-launch is observed only in separate verbose runs; it includes queue and preparation/cache-loading work, not exact network acceptance.

The remaining performance question is empirical: whether independent runs of the equivalent route show a stable treatment-associated difference after controlling arrivals. [The Phase 3 report](../PHASE3_REPORT.md) carries the results and uncertainty; code equivalence alone is not a claim of measured performance equivalence.
