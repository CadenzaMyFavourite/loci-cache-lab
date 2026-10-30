# Phase 2 hypotheses and decision rules

Written before new GPU measurements. Phase 1 is retained, including its transport failures and evidence gap.

| Hypothesis | Discriminating test | Evidence against it |
|---|---|---|
| H1: FIFO admission causes the regression | A (engine routing, no semaphore) vs B (same routing plus existing semaphore); measure actual queue entry/exit | Negligible queue durations and similar A/B distributions |
| H2: External slot reservation/explicit assignment is costly | B vs C (prefix + LRU explicit slots), with identical admission; correlate reserved intervals with engine slot launch/release | Similar B/C and no conflicting/late slot assignments |
| H3: Frequency-weighted eviction makes worse cache choices | C vs D (original frequency retention); compare evaluated tokens per request and latency | C and D regress similarly, or token reuse is unchanged |
| H4: Continuous batching moves cold prefill onto warm requests' critical paths | Examine low-evaluation-token requests with long prompt time and overlapping cold-prefill tasks; compare critical-path overlap across arms | Slow warm requests occur without overlapping cold work |
| H5: RAM restoration/internal engine state explains differences | Repeat both cache budgets; compare actual cache_n against predicted LCP, logs and metrics | Regression remains without RAM restoration |
| H6: Transport/SSE buffering rather than GPU work dominates | Record headers, first bytes/SSE/content, every token event, terminal event/EOF; compare timing to engine prompt time; separate transport-control diagnostics | Client excess is small and engine prompt time explains TTFT |

A/B/C/D all use the existing seeded skewed-2048 fixtures, two outstanding requests, eight greedy output tokens, 12,288 context, two slots, f16 KV, and a fresh server per arm. The original Phase 1 stock arm corresponds to B, not A.

Start with short diagnostics. Main ablation: five paired seeds × 60 measured attempts plus six warmup attempts per arm × four arms × two cache budgets. Rotate arm order. Keep failed observations; never retry a timed request. Diagnostic polling/progress streams are separate from headline runs.

Use monotonic client events as directly measured timestamps. HTTP headers are an observable engine-start signal for this server revision, not proof of exact server acceptance time. Native completion lacks a request/task identifier; offline per-slot ordering can correlate logs only when counts, tokens and event order agree. Reject ambiguous matches. Server/client clocks are not assumed synchronized. Polling and log instrumentation can perturb scheduling and are labeled.

Only choose a fix after the ablation. Prefer preserving engine ownership of slot availability over releasing a Rust lease early while inference may still be active. A fallback that restores stock performance is a regression correction, not a novel improvement over stock. Validation must examine P95 and failures as well as medians. No latency speedup is acceptable if factual isolation or cancellation safety is broken.
