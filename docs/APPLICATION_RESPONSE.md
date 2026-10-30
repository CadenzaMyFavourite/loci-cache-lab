# Loci application response

## Written answer

I investigated whether a Rust conversation scheduler could reduce time to first token beyond llama.cpp's native caching on an RTX 4070 Laptop GPU. I built a streaming benchmark with fixed tokenized histories, paired trials, cache counters, and cancellation tests. Native caching reduced a repeated 2,048-token control from 285.5 to 18.3 ms; that gain belongs to llama.cpp.

My frequency-weighted retention policy regressed with two clients. An ablation separated FIFO admission, explicit slot routing, and eviction policy. Correlated client and engine traces showed premature slot binding: one request evaluated 2,044 tokens despite a later-idle slot matching 2,034, delaying another cached request.

I changed concurrent mode to delegate slot selection to the engine, then checked effective HTTP requests, correctness probes, and twenty paired fixed-arrival trials per cache setting. The corrected mode was not reliably faster than stock, and residual P95 variability and transport failures remain documented. The outcome is a reproducible negative result, a supported failure mechanism, and a conservative routing fallback.

## Approximately 90-second spoken explanation

I wanted to know whether a small Rust scheduler could improve conversation caching beyond llama.cpp on an eight-gigabyte laptop GPU. I used fixed synthetic histories, so generated answers could never change later inputs.

First I measured the native baseline. Repeating a 2,048-token prompt reduced time to first token from about 286 milliseconds to 18. That was llama.cpp's caching benefit.

My scheduler preferred matching prefixes and retained expensive, frequent conversations. With two clients it became much slower. I separated FIFO admission, explicit slot routing, and frequency weighting. Removing frequency weighting did not fix it.

Client timestamps and engine logs exposed a timing problem. Rust chose a slot before the engine handled the request. Meanwhile another slot became idle with a much better prefix. The pinned request still evaluated 2,044 tokens, and a following cached request waited behind that work.

The correction delegates concurrent slot selection to llama.cpp. It is a native-routing fallback, not a new faster algorithm. I verified matching request bodies and ran twenty paired fixed-arrival trials per cache setting. The remaining tail differences were not stable enough to claim a speedup, and I retained failures and numerical disagreements.

My main lesson was to measure where a decision becomes binding, distinguish reused work from latency, and keep negative results reproducible.

## Evidence to bring to the interview

The written answer and spoken text exclude headings and this evidence section from word counts. Timing depends on speaking pace; rehearse the spoken version rather than claim an exact duration.

- [Baseline and full narrative](../README.md)
- [Premature-binding trace](../evidence/early-binding.json) and [ablation](../evidence/phase2-summary.json)
- [Equivalent fallback semantics](phase3-equivalence.md) and [tail uncertainty](../PHASE3_REPORT.md)
- [Case study](CASE_STUDY.md), [slides](../presentations/engineering-case-study.pptx), [interview questions](INTERVIEW_QUESTIONS.md)

Earlier application drafts remain preserved in this repository's historical documents. This is the release application response.
