# Repository quality audit

Phase 4 prepares a reviewable release without changing the preserved research implementation or repeating the experimental matrix. The original README and ignore rules are snapshotted under local `phase4/baseline/`. The prior-file SHA-256 manifest covers 4,607 source, report, measurement and analysis files. Only the current README and `.gitignore` are authorized changes within that manifest; CI is also intentionally updated. New release files are additive.

## Build and dependencies

| Check | Observed result |
|---|---|
| `cargo fmt --check` | Passed |
| Clean `cargo build --release --locked --bins` | Passed from an isolated source directory and empty target; 23.82 seconds |
| `cargo test --all-targets --locked` | 25 passing test executions across targets, including shared modules exercised in multiple targets |
| `cargo clippy --all-targets --locked -- -D warnings` | Passed without warnings |
| Fresh Python virtual environment + locked requirements | Installed; `pip check`: no broken requirements |
| `python -m unittest discover -s tests -v` | Nine tests passed, including release normalization/failure accounting checks |
| Existing-asset, fresh-source three-arm GPU smoke demo | 36 measured + 18 warmup requests; zero failures; 25.03 seconds |
| Deployed engine/runtime DLL checks against pinned archives | Passed final environment check |

Tested toolchains: Rust 1.96.1 MSVC and Python 3.14.6. The updated Windows CI runs formatting, all Cargo targets, warnings-as-errors Clippy and Python tests. Remote CI has not run because this project has not been pushed.

The seven production Cargo dependencies and Axum test dependency are used. `cargo machete` was unavailable; no automated unused-dependency result is claimed. Resolved declarations for 165 Rust packages and 13 installed Python packages are recorded in the [notices](../THIRD_PARTY_NOTICES.md). Existing scoped dead-code allowances accommodate shared binary/test entry points. Historical Python entry points and unused imports are retained rather than risk changing research scripts; no new inference feature or speculative cleanup was introduced.

## Reproduction and configuration

The new demo accepts asset and binary roots as arguments and prepares fixtures with the running server's tokenizer/template. A search of `src/`, `scripts/`, `tests/` and CI found no hardcoded drive-specific source paths. Runtime manifests intentionally record real locations locally. The publication exporter normalizes those strings in copies; it never edits originals. Normalized historical fixture scopes must not be replayed as fresh server identities.

The demo verifies model/archive/executable/DLL checksums, free VRAM, a vacant port and accepted context capacity. Each mode gets a fresh owned server; sampling, prompt IDs and output limits remain fixed. Failure records survive, and failed requests make the command return an error after saving results. The mini-demo is deliberately descriptive, not a statistical revalidation of the timing-sensitive failure.

[Portable configurations](../evidence/configurations.json) retain complete run headers, including native properties/template and client options. [Request records](../evidence/requests.jsonl) retain measured counters, timestamps, output tokens and failures with original-source references. Full SSE, request payloads, logs, launch arguments and GPU samples remain in the separate archive. Original Phase 1 calibration/counter limitations are documented rather than repaired retrospectively.

## Publication boundaries

| Asset | Release policy |
|---|---|
| Rust/Python source, tests, locked dependencies, docs, CI | Include |
| Portable request records/configurations, measured figures, editable deck | Include |
| Full Phase 1–3 raw logs/SSE/workloads/configuration and historical report originals | Location-redacted archive alongside the source; retain private originals |
| Model, engine/runtime zips, DLLs, executables, virtual environments, build directories | Exclude; reproduce from pinned upstream assets |
| Profiler databases/large binary traces, authoring scratch files | Keep outside Git; archive separately if needed |

Bounded credential scanning covers OpenAI/GitHub/AWS key patterns, private-key headers and Windows home paths. It checks text and PPTX XML/relationships, without printing matching values. This is a useful check, not proof that every possible secret or sensitive string is absent. The raw archive is scanned after location normalization. The exporter records original and copied hashes. Source-tree size and local-link checks are part of final validation.

No model weights or third-party executable redistribution is proposed. llama.cpp is MIT licensed; this exact Qwen 3B model has a separate **Qwen Research License**, and CUDA has NVIDIA terms. See [exact upstream identities and agreements](../THIRD_PARTY_NOTICES.md).

## Reliability and presentation limits

- Default-cache P95 variability remains unresolved. Failure-free sensitivity also prevents a broad no-host-cache tail-parity claim.
- Five measured Phase 3 connection closures and one warmup closure remain unexplained. Successful-request quantiles are accompanied by failure counts; no silent retries were added.
- Earlier factual probes include wrong answers independent of an established cache-corruption mechanism. Selected later EOS probes all pass, but do not erase earlier failures or numerical differences.
- One model/device, synthetic histories, imperfect arrival wakeups, desktop activity and one-second memory samples constrain generalization.
- The four-case KV subset is not a full factorial or near-capacity experiment. Native allocation savings do not establish throughput gains.
- The nine-slide deck passed package, font-policy, native table/chart and artifact-tool import checks and all nine rendered slides were visually reviewed. Native Microsoft PowerPoint execution/font rendering was not tested. No video was fabricated; a manual recording guide is provided.

See [the handoff](../FINAL_HANDOFF.md) for exact executed commands and [archive policy](../DATA_ARCHIVE.md) for the preservation and publication workflow.
