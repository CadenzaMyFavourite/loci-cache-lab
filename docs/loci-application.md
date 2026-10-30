# Loci application paragraph

I built a reproducible Rust/Tokio experiment on conversation caching with llama.cpp and an 8 GB RTX 4070 Laptop GPU. Stock caching reduced the repeated 2,048-token control's median time to first token from 285.5 ms to 18.3 ms. My frequency-weighted slot policy then exposed a two-client latency regression. I instrumented the client and correlated its traces with native engine logs, ruled out FIFO wait as the direct bottleneck, and traced how early slot binding could miss a newly idle matching prefix and delay cached requests behind prefill. I added a native-routing fallback, tested its wire-level equivalence to stock, and used predetermined arrivals and paired-trial uncertainty to investigate tail variability. The reports retain regressions, failures and output disagreements; I do not claim an unverified scheduler speedup.

Evidence: [Phase 1 baseline](REPORT.md), [Phase 2 mechanism](concurrency-root-cause.md), [Phase 3 validation](../PHASE3_REPORT.md), [source and reproduction](../README.md).

This is a project paragraph, not a claim of production deployment or an application submission. Add the final public repository URL only after reviewing and authorizing publication.
