# Final handoff

## What is ready

The project is prepared as an engineering portfolio: reproducible Rust implementation/tests, a ten-minute README path, portable evidence, a small Windows demo, a concise case study, an editable nine-slide deck, application response and interview prompts. Research originals are preserved. Stock native routing remains the concurrent recommendation; corrected mode is a native fallback with no independently established speedup.

Start with [README](README.md), [demo](docs/DEMO.md), [case study](docs/CASE_STUDY.md), [slides](presentations/engineering-case-study.pptx), and [application response](docs/APPLICATION_RESPONSE.md). The [audit](docs/REPOSITORY_AUDIT.md) and [checklist](RELEASE_CHECKLIST.md) distinguish completed local checks from outstanding work.

## Commands actually executed

All commands below ran locally from the research repository root. They did not push or publish. Toolchain: Rust 1.96.1 MSVC, Python 3.14.6, RTX 4070 Laptop GPU 8 GB, driver 616.92.

```powershell
cargo fmt --check
cargo build --release --locked --bins --manifest-path runs/phase4-clean/Cargo.toml --target-dir runs/phase4-clean/target
cargo test --all-targets --locked --manifest-path runs/phase4-clean/Cargo.toml --target-dir runs/phase4-clean/target
cargo clippy --all-targets --locked --manifest-path runs/phase4-clean/Cargo.toml --target-dir runs/phase4-clean/target -- -D warnings
```

The source copy had no initial build artifacts; release compilation took 23.82 seconds. Formatting passed, 25 Rust test executions passed, and Clippy passed with warnings denied. Shared modules are exercised by multiple targets, so this is not a claim of 25 distinct test cases.

```powershell
.\.venv\Scripts\python.exe -m venv runs/phase4-python
.\runs\phase4-python\Scripts\python.exe -m pip install -r requirements.lock.txt
.\runs\phase4-python\Scripts\python.exe -m pip check
.\runs\phase4-python\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe runs/phase4-clean/scripts/demo.py compare --assets-root . --bin-dir runs/phase4-clean/target/release --out runs/phase4-mini-demo
.\runs\phase4-python\Scripts\python.exe runs/phase4-clean/scripts/demo.py check --assets-root . --bin-dir runs/phase4-clean/target/release
```

Fresh Python installation and dependency checks passed; nine Python tests passed after the release tests were added. The GPU smoke run completed in 25.03 seconds: three modes, 12 measured + six warmups each, no failures. All three evaluated 2,190 input tokens and reused 22,386 measured tokens. This sample is an execution check, not evidence of a new ranking. The final environment check additionally verified all deployed engine/runtime DLL entries against pinned archives. See [portable smoke evidence](evidence/demo/summary.json).

```powershell
.\runs\phase4-python\Scripts\python.exe scripts/release_evidence.py
.\runs\phase4-python\Scripts\python.exe scripts/plot_evidence.py --out runs/phase4-evidence-example.png
.\runs\phase4-python\Scripts\python.exe scripts/release_export.py --out runs/phase4-publication-final --archive
.\runs\phase4-python\Scripts\python.exe scripts/release_check.py --publication runs/phase4-publication-final/repository --out phase4/release-validation.json
```

The last check validates preservation, copied manifests, local links, portable evidence denominators, application length, bounded credential/home-path rules, file size policy and deck structure. Original/copy hashes and archive checksums are saved alongside the candidate. Detailed local command outputs are retained in ignored `phase4/*.log`. The publication copy's tests and saved-evidence plotting are also checked from its own directory.

The deck was built with `presentations/build_deck.mjs` in the supplied `@oai/artifact-tool` runtime. Nine slides, two native charts with embedded values, native tables, font policy and package import checks passed; all rendered slides were reviewed. PowerPoint itself was not tested. Rebuilding the deck is optional and requires that authoring dependency; inference reproduction does not.

## Files to include in Git

Use the reviewed **`runs/phase4-publication-final/repository/`** copy as the publication source. Earlier candidates under `runs/` are private drafts. It contains:

- `src/`, `tests/`, `scripts/`, Cargo manifests/lockfile, locked Python requirements and `.github/workflows/ci.yml`.
- README, license/notices, Phase 2/3 report copies, archive guide, checklist, handoff and `demo.ps1`.
- `docs/*.md`, `analysis/*.png`, `evidence/*.json*` and smoke evidence, `environment/artifacts.json`.
- `presentations/build_deck.mjs` and `presentations/engineering-case-study.pptx`.

Report copies normalize private locations and link archive-only references to the archive guide. Original text remains local/in the separate archive. The publication manifest outside `repository/` records all copied hashes. Do not run `git add .` over the full research workspace as a substitute for reviewing this export. No Git commit or public remote operation was created in Phase 4.

## Assets to archive separately

Keep `raw-evidence-redacted.zip`, `archive-info.json` and `publication-manifest.json` alongside the release candidate, outside the Git source. Retain original `results/`, `workloads/`, `environment/`, `analysis/`, historical reports, `phase2/`, `phase3/` and prior manifests locally for byte-exact audit. Archive copies redact locations; their hashes differ from originals. See [DATA_ARCHIVE.md](DATA_ARCHIVE.md).

Exclude model weights, upstream engine/runtime archives, DLLs/executables, vendor source copies, virtual environments, build output, scratch decks and binary profiler databases/traces. Recreate pinned assets from upstream; their license terms are separate. The source and raw archive have bounded scans, not a guarantee against every possible sensitive string.

## Outstanding concerns

Residual default-cache P95 variability, rare pre-header transport closures and earlier factual/numerical disagreements remain documented. Later selected factual probes do not erase earlier failures. The precision subset is not a full factorial or near-capacity test; lower KV allocation is not a throughput claim. The project is a reproducible single-device research portfolio, not a production reliability certification. Remote CI and native PowerPoint playback remain unexecuted. A recording guide is provided; no video exists.

## Simplest reproduction

On Windows with the pinned model/engine assets already available: install locked requirements, `cargo build --release --locked --bins`, then run **`.\demo.ps1`**. The demo checks VRAM/checksums, prepares fresh fixtures, resets the owned server between three arms and saves raw results plus a chart. Use `scripts/demo.py compare --assets-root <asset-directory>` when assets are in another checkout. First downloads and compilation are outside the observed 25-second smoke runtime. GPU-free entry: tests, then `python scripts/plot_evidence.py --out runs/example.png`.
