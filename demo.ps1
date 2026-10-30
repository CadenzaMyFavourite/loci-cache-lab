param([string]$OutDir = "", [string]$AssetsRoot = "")
$ErrorActionPreference = "Stop"
$demoPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $demoPython)) { throw "Create .venv and install requirements.lock.txt first (see README)." }
$demoArgs = @((Join-Path $PSScriptRoot "scripts\demo.py"), "compare")
if ($OutDir) { $demoArgs += @("--out", $OutDir) }
if ($AssetsRoot) { $demoArgs += @("--assets-root", $AssetsRoot) }
Push-Location $PSScriptRoot
try { & $demoPython @demoArgs; if ($LASTEXITCODE -ne 0) { throw "Demo failed; retained evidence is under the chosen output directory." } }
finally { Pop-Location }
