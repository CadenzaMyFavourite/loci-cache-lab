# Release checklist

## Verified locally

- [x] Preserved prior source, raw measurements, analysis and reports; archived the prior README/ignore rules locally.
- [x] Rewrote README with native baseline attribution, concurrency failure, fallback semantics, uncertain tails and precision limitations.
- [x] Built all release binaries from an isolated source directory and empty Cargo target.
- [x] Passed Rust formatting, all-target tests (25 executions) and warnings-as-errors Clippy.
- [x] Installed pinned Python requirements in a fresh virtual environment; dependency check and nine tests passed.
- [x] Ran a small three-arm benchmark against existing pinned assets: 36 measured + 18 warmups, zero failures, 25.03 seconds.
- [x] Verified deployed engine/runtime DLLs against checksum-pinned upstream archives.
- [x] Added repeatable demo/server/workload/chart commands, failure accounting tests and a saved-data plot.
- [x] Added complete portable run headers and measurement provenance without editing originals.
- [x] Prepared a source whitelist and separate location-redacted raw-evidence archive.
- [x] Checked the publication candidate for bounded credential patterns, private home paths, oversized assets and broken local Markdown links.
- [x] Prepared and structurally validated the nine-slide editable deck; visually inspected all slides.
- [x] Wrote the 130–180-word application answer, approximately 90-second explanation and interview bank.
- [x] Recorded model/engine/runtime attribution and separate model licensing.

## Explicit limits and remaining publication actions

- [ ] Remote CI: workflow is ready; not run because nothing has been pushed.
- [ ] Native Microsoft PowerPoint playback: package/import/render validation passed; application-level playback was not tested.
- [ ] Optional screen recording: manual storyboard only; no video exists.
- [ ] Decide the remote raw-archive destination and verify access/links there after explicit publication authorization.
- [ ] Review source and archive manifests before upload. Bounded scans cannot prove universal absence of sensitive information.
- [ ] Resolve transport closures, residual tail variability and earlier factual disagreements before claiming production reliability or a routing speedup.

Publish only the reviewed `repository/` export described in [FINAL_HANDOFF.md](FINAL_HANDOFF.md). No push, release creation or upload was performed.
