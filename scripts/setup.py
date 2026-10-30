"""Download pinned upstream artifacts, verify publisher hashes, record provenance."""
import hashlib
import json
import pathlib
import subprocess
import urllib.request
import zipfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
TAG = "b11960"
REVISION = "7dabda4d13d513e3e842b20f0d435c732f172cbe"
MODEL = "qwen2.5-3b-instruct-q4_k_m.gguf"
COMMIT = "8642541b255bfb5dc39cd351a178be09013a55d6"
HASHES = {
    "cudart-llama-bin-win-cuda-12.4-x64.zip": "8c79a9b226de4b3cacfd1f83d24f962d0773be79f1e7b75c6af4ded7e32ae1d6",
    "llama-b11960-bin-win-cuda-12.4-x64.zip": "8d9d819261de10cc2f03921b8b79c779c5c458e21edb60c170ee30a7d462d684",
    MODEL: "626b4a6678b86442240e33df819e00132d3ba7dddfe1cdc4fbb18e0a9615c62d",
}

def get_json(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "loci-cache-lab"})) as response:
        return json.load(response)

def sha256(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()

def download(url, path, expected=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        partial = path.with_suffix(path.suffix + ".part")
        subprocess.run(["curl.exe", "--silent", "--show-error", "--fail", "--location", "--retry", "3", "--continue-at", "-", "--output", str(partial), url], check=True)
        partial.replace(path)
    actual = sha256(path)
    if expected and actual != expected:
        raise RuntimeError(f"SHA256 mismatch for {path.name}: {actual} != {expected}")
    return {"url": url, "path": str(path.relative_to(ROOT)), "sha256": actual, "publisher_sha256": expected, "bytes": path.stat().st_size}

def main():
    release = get_json(f"https://api.github.com/repos/ggml-org/llama.cpp/releases/tags/{TAG}")
    assert release["target_commitish"] == COMMIT, "upstream release target changed"
    records = []
    binary_dir = ROOT / "vendor" / TAG
    binary_dir.mkdir(parents=True, exist_ok=True)
    for asset in release["assets"]:
        if asset["name"] in [f"llama-{TAG}-bin-win-cuda-12.4-x64.zip", "cudart-llama-bin-win-cuda-12.4-x64.zip"]:
            assert asset["digest"] == "sha256:"+HASHES[asset["name"]], "upstream release hash changed"
            record = download(asset["browser_download_url"], ROOT / "downloads" / asset["name"], HASHES[asset["name"]])
            records.append(record)
            with zipfile.ZipFile(ROOT / record["path"]) as archive:
                archive.extractall(binary_dir)
    model_info = get_json(f"https://huggingface.co/api/models/Qwen/Qwen2.5-3B-Instruct-GGUF/revision/{REVISION}?blobs=true")
    model_entry = next(item for item in model_info["siblings"] if item["rfilename"] == MODEL)
    assert model_entry["lfs"]["sha256"] == HASHES[MODEL], "upstream model hash changed"
    records.append(download(f"https://huggingface.co/Qwen/Qwen2.5-3B-Instruct-GGUF/resolve/{REVISION}/{MODEL}", ROOT / "models" / MODEL, model_entry["lfs"]["sha256"]))
    # The small server source files make the baseline algorithm locally inspectable.
    for name in ["README.md", "server-context.cpp", "server-task.cpp", "server-common.cpp"]:
        download(f"https://raw.githubusercontent.com/ggml-org/llama.cpp/{TAG}/tools/server/{name}", ROOT / "vendor" / "source" / name)
    manifest = {"schema_version": 1, "llama_tag": TAG, "llama_commit": release["target_commitish"], "model_revision": REVISION, "artifacts": records}
    (ROOT / "environment").mkdir(exist_ok=True)
    (ROOT / "environment" / "artifacts.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2), flush=True)

if __name__ == "__main__":
    main()
