# Evidence and archive policy

The working research directory is larger and more machine-specific than the publication repository. Do not upload it wholesale. All historical originals remain in place; release preparation operates on copies.

## Evidence included in source

- `evidence/requests.jsonl`: 22,320 measured request attempts plus 2,372 warmups across canonical Phase 1–3 cohorts. Failures are retained; this is a compact measurement view, not the complete SSE trace.
- `evidence/configurations.json`: full location-normalized run headers, native properties/templates and client configuration for each canonical arm.
- `evidence/index.json`: cohort denominators, original request-source hashes and original/copy summary hashes.
- `evidence/*summary.json`, `early-binding.json`, `allocations.json`, `phase3-hardware.json`: inspectable retained results and the correlated failure example.
- `evidence/demo/`: location-normalized raw records, launch configuration and summary from the Phase 4 smoke run, with provenance.
- `analysis/*.png`: saved measured figures. Regenerate the small example with `python scripts/plot_evidence.py --out runs/example.png`.

The canonical cohort table deliberately excludes exploratory runs from its aggregate denominators. Those runs remain in the full archive. Numerical measurements, token IDs, failures and counters are not altered when locations are normalized. Review copies do not substitute for freshly prepared fixtures in a live benchmark.

## Separate raw archive

```powershell
.\.venv\Scripts\python.exe scripts/release_export.py --out runs/phase4-publication --archive
```

The destination must be new. This creates:

- `repository/`: a whitelisted source/evidence tree suitable for Git review.
- `publication-manifest.json`: original and publication SHA-256 values, sizes and changed-copy markers.
- `raw-evidence-redacted.zip`: location-normalized text/PNG/CSV copies from `results/`, `workloads/`, `environment/`, `analysis/`, `docs/`, the historical root reports, `phase2/`, `phase3/`, the Phase 4 smoke run and preservation snapshots/manifest.
- `archive-info.json`: archive SHA-256, size and file count.
- Inside the zip, `ARCHIVE_MANIFEST.json`: original and archive-copy hashes for each member.

The original result directories contain full configuration, native server logs/metrics, raw SSE, request payloads, GPU/RAM telemetry CSV files and exploratory controls. Historical baseline source snapshots are retained. Existing integrity files may refer to **original** byte hashes; use `archive_sha256` to validate redacted members. Location substitution changes bytes, not the measurements. For a bit-for-bit audit, retain the private originals with their prior manifests. The archive contains synthetic prompts/outputs, not user conversations.

Publication report copies redirect links to archive-only files here to avoid broken repository links. Exact historical report text and link targets remain in the raw archive; the original Phase 3 README is retained locally in `phase4/baseline/`. A reviewer with the archive should extract it to the repository root in a separate audit checkout and follow the original directory layout. Historical report generators can rewrite outputs, including the README: use a disposable audit checkout, not the release tree.

## Assets excluded from both the normal source tree and this text archive

`models/`, `downloads/`, `vendor/`, `target/`, `.venv/`, `runs/`, authoring scratch directories, executables/DLLs, profiler SQLite databases and binary Nsight traces are not in the source whitelist. Model/runtime downloads alone are several gigabytes. Recreate them using `scripts/setup.py` and the pinned [artifact manifest](environment/artifacts.json). Preserve any needed binary profiler artifacts separately, with hashes and applicable license/privacy review.

The exporter performs bounded credential/home-path scanning and includes no upload operation. No remote archive URL exists yet. Keep the archive local until a publication destination and review are authorized. The model's agreement is separate from the project's code license; see [notices](THIRD_PARTY_NOTICES.md).
