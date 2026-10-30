"""Optional portable profiler setup; does not install MSI packages or services."""
import json
import zipfile
from setup import ROOT, download

URL="https://developer.download.nvidia.com/compute/cuda/redist/nsight_systems/windows-x86_64/nsight_systems-windows-x86_64-2026.3.2.476-archive.zip"
SHA256="e4d1e8dce8875b01fcb295623974d755e77eb8e346e7e52aba9e9e7fad376887"

def main():
    record=download(URL,ROOT/"downloads/nsight-systems-portable.zip",SHA256)
    record["pinned_sha256"]=record.pop("publisher_sha256")
    record["hash_origin"]="observed and pinned during initial setup; distributed over official NVIDIA HTTPS"
    with zipfile.ZipFile(ROOT/record["path"]) as archive:
        archive.extractall(ROOT/"vendor/nsight")
    (ROOT/"environment/profiler.json").write_text(json.dumps(record,indent=2),encoding="utf-8")
    print("Portable Nsight Systems extracted")

if __name__=="__main__":
    main()
