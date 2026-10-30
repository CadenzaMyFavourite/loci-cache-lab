# Experimental method

## Question and hypothesis

Does a frequency-and-token-cost eviction heuristic improve conversation latency over stock llama.cpp slot selection when three or more conversations compete for two slots? The expected benefit is less redundant prefill. An alternative outcome is that stock host-RAM caching already recovers most of that work, leaving little opportunity for an external policy.

The policy is fixed before the repeated study. Its 32-admission history and 10% prefix threshold are not tuned against the reported results. It observes past admissions only and has no access to the future trace.

## Fixed environment

The artifact manifest records llama.cpp b11960, its commit and release archive hashes, the Qwen model revision and hash, and the CUDA runtime. Every completed arm has a launch manifest, fixture hash, executable hash, raw request records, and server log. Windows GPU telemetry identifies the driver and available memory. The script checks at least 3,584 MiB of free VRAM before launching an arm and does not change model/context/offload settings to make it fit.

All headline runs use full GPU offload, two independent KV partitions, Flash Attention enabled, f16 KV storage, a 12,288-token total context, no context shifting, and automatic fitting disabled. Each slot's capacity is read from `/slots`; oversized requests fail before HTTP inference.

## Workloads and arms

Each fixture contains six warmup requests followed by 60 measured requests. Inputs use the engine's chat template and tokenizer. Long garden notes are synthetic, not a sampled production conversation corpus. Middle filler tokens are removed to obtain the target prompt length; the system instruction and trailing role markers remain intact. A counter in the latest user message changes between turns. The model's generated answer never becomes the next input.

The recent scripted assistant turn confirms the conversation's unique secret. This is a deliberate probe design revision after the initial smoke test found unreliable baseline recall with repetitive long histories. Those diagnostic and original smoke runs remain separate from the headline study. They must not be combined with the final fixtures as if they were one experiment.

The six workload files cover one active conversation at 512/2,048/4,096 input tokens; equal A/B/C rotation at 2,048 tokens; a seeded 70/20/10 A/B/C activity distribution; and mixed 512/2,048-token hot histories plus occasional 4,096-token conversations. Rotation and skew also run with two clients.

For every workload/client configuration, compare uncached requests with host cache off, stock with 8,192 MiB of host cache, custom with the same host budget, and stock/custom with host cache disabled. The latter pair isolates an intentionally constrained deployment; it is not the default baseline. Common-prefix reuse inside a slot may still preserve a handful of structural tokens.

Five trial seeds use paired fixtures across policies. The execution order rotates by trial. The server restarts before every arm; engine startup warmup is retained, fixture warmup is labeled, and measured samples begin only after fixture warmup completes. This is steady-state conversation latency, not model cold-start time. Six warmup requests do not guarantee stationarity under every skewed trace.

The client uses a closed-loop window of one or two requests: as one completes, the next request becomes ready. There is no fixed arrival-rate claim. The CLI also supports `--burst` to enqueue all requests and expose FIFO admission wait, but that is not the main workload. Queue timing separates the harness admission wait from HTTP/server latency.

## Timing and counters

`ttft_ms` starts when a pre-tokenized request becomes ready and ends on its first nonempty SSE text. It includes scheduling, admission wait, serialization, HTTP, engine queueing, and inference. It excludes user typing, chat-template application, initial tokenization, model loading, and fixture construction. `http_ttft_ms` starts just before sending the HTTP request. Stream chunks are parsed as bytes to preserve UTF-8 boundaries; empty initial content does not end TTFT.

Timing runs force eight generated tokens with greedy sampling, fixed seed, and EOS disabled. Decode timing describes short replies; it is not a sustained-throughput benchmark. Correctness runs allow EOS and up to 32 tokens. Nsight runs are separate and excluded from latency summaries.

For this pinned revision, `timings.cache_n` counts reused prompt tokens, `timings.prompt_n` counts evaluated prompt tokens, and their sum equals the prepared prompt length. `tokens_cached` is total cached state after generation and must not be used as the reused-input count. Calibration verifies cold and repeated requests; the validation script reconciles every completed run's evaluated-token counts against the server's prompt-evaluation logs.

## Aggregation and uncertainty

Median and linear-interpolated P95 pool measured requests within one configuration. The report also retains means and minimum/maximum trial medians. Never average P95 values and call the result the pooled P95. Comparisons pair trial medians by seed and compute `100 × (1 − median(custom_trial_medians) / median(stock_trial_medians))`; positive values mean faster custom scheduling.

A seeded paired-trial bootstrap resamples the five trial pairs 5,000 times for an exploratory 95% percentile interval. Five blocks, serial dependence within each trace, and many unadjusted comparisons limit inferential strength. Intervals are not a production performance guarantee. Exploratory one-trial secondary results receive no confidence interval.

## Correctness and resource limits

The factual probe passes when the expected conversation code appears and no other known conversation code appears. Exact formatting and exact greedy output-token agreement are reported separately. Cached and uncached paths may use different batch sizes and floating-point kernels; a changed token sequence needs investigation rather than an automatic stale-cache diagnosis. These small factual probes do not establish general model-quality equivalence.

GPU memory, utilization, temperature, power and clocks are sampled approximately once per second. GPU memory is device-wide under WDDM and includes desktop applications; RSS is process system memory. Maxima include loading and may miss shorter peaks. Context/KV-precision experiments measure allocation tradeoffs, not a demonstrated 8 GB near-capacity limit or a battery-life improvement.

Completion means that every planned request attempt was recorded, including failures. Latency summaries condition on successful responses and report failure counts alongside them; a failed request is not assigned zero latency or retried invisibly. Interrupted runs with missing observations are archived before restarting the whole arm. Early collection stopped on an HTTP failure even though all requests had been recorded. Its first raw file was overwritten before archival was added; the retained summary discloses that gap. The second attempt's complete file, including two failures, is retained in the matrix. This recovery history and its possible selection effects are reported explicitly.

Remaining limits include one GPU, one model/quantization, Windows background activity, no enforced thermal equilibrium, no real-user trace corpus, and no measurement of phone performance. Report improvements and regressions by configuration. A broad deployment recommendation requires additional evidence.
