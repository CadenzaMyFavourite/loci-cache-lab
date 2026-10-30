# Third-party software and model notices

The repository's original Rust/Python code is MIT licensed under [LICENSE](LICENSE). Dependency and downloaded-asset licenses remain separate. The publication tree contains no model weights, llama.cpp executables, CUDA DLLs or profiler binaries.

| Component | Version / identity | License / source |
|---|---|---|
| llama.cpp | b11960, commit `8642541b255bfb5dc39cd351a178be09013a55d6` | MIT. Copyright (c) 2023–2026 The ggml authors. [Pinned license](https://github.com/ggml-org/llama.cpp/blob/b11960/LICENSE) |
| Qwen2.5-3B-Instruct-GGUF | revision `7dabda4d13d513e3e842b20f0d435c732f172cbe`, Q4_K_M | **Qwen Research License**, separately governing this exact 3B model. [Pinned agreement](https://huggingface.co/Qwen/Qwen2.5-3B-Instruct-GGUF/blob/7dabda4d13d513e3e842b20f0d435c732f172cbe/LICENSE) |
| NVIDIA CUDA runtime | CUDA 12.4 matching the pinned Windows release | NVIDIA software license and CUDA supplement. [Versioned terms](https://docs.nvidia.com/cuda/archive/12.4.0/eula/index.html) |
| NVIDIA Nsight tools | Historical profiling only | NVIDIA terms. Not included in the publication tree |
| Rust crates | Exact versions in Cargo.lock | [Resolved license declarations](evidence/dependency-licenses.json), including transitive packages. No prebuilt Rust executable is shipped |
| Python packages | Exact versions in requirements.lock.txt | [Installed package declarations](evidence/python-dependencies.json). No virtual environment or vendored package is shipped |

This exact Qwen model's agreement grants use for research/evaluation and requires a separate license request for commercial use. Do not assume the licenses of other Qwen model sizes apply. The mini-demo uses existing weights on the research machine or downloads them from the original publisher through setup. Review the linked agreement before adopting the model in another setting.

Publisher attribution: “Qwen is licensed under the Qwen RESEARCH LICENSE AGREEMENT, Copyright (c) Alibaba Cloud. All Rights Reserved.”

Setup verifies pinned archive/model checksums in [environment/artifacts.json](environment/artifacts.json). It downloads upstream assets into ignored directories instead of relicensing or repackaging them. Model outputs in the evidence are synthetic factual probes and fixed-length generation traces. The project does not use those outputs to train or distribute another model.

The optional editable deck was authored with `@oai/artifact-tool` in the supplied authoring runtime. That library and proprietary fonts are not distributed. Text remains editable and charts embed their literal measured values. Rebuilding the deck is optional and does not affect inference reproduction.
