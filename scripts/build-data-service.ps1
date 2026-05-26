param(
  [string]$Python = $env:ASTOCK_BACKTESTER_PYTHON
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$bundledPython = Join-Path $repoRoot ".tools\python-3.11.9\python.exe"
if (-not $Python) {
  if (Test-Path $bundledPython) {
    $Python = $bundledPython
  } else {
    $Python = "python"
  }
}

$distDir = Join-Path $repoRoot "src-tauri\bin"
$workDir = Join-Path $repoRoot ".pyinstaller\build"
$specDir = Join-Path $repoRoot ".pyinstaller\spec"
$targetExe = Join-Path $distDir "astock-data-service.exe"

New-Item -ItemType Directory -Force $distDir | Out-Null
New-Item -ItemType Directory -Force $workDir | Out-Null
New-Item -ItemType Directory -Force $specDir | Out-Null

$pythonCommand = Get-Command $Python -ErrorAction SilentlyContinue
if (-not $pythonCommand) {
  throw "Python executable not found: $Python. Install Python 3.11+ or set ASTOCK_BACKTESTER_PYTHON."
}

if (Test-Path $targetExe) {
  Remove-Item -LiteralPath $targetExe -Force
}

Push-Location $repoRoot
try {
  & $pythonCommand.Source -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --name astock-data-service `
    --distpath $distDir `
    --workpath $workDir `
    --specpath $specDir `
    --paths backend `
    --collect-all adata `
    --hidden-import requests `
    --hidden-import bs4 `
    backend\astock_backtester\service.py
  if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed with exit code $LASTEXITCODE"
  }
} finally {
  Pop-Location
}

if (-not (Test-Path $targetExe)) {
  throw "astock-data-service.exe was not created"
}
